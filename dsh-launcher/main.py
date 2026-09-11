"""DeepSeek Harness 启动器（PySide6 GUI）。

主窗口分两个页签：
- 「控制」：安装 / 构建 / 启动 / 停止四个操作 + 日志窗（原有功能）；
- 「插件」：web profile 的第三方插件安装 / 卸载、安装前快照列表，
  以及插件兼容性问题导致 DSH 无法启动时的三个恢复动作
  （卸载最近插件并重试 / 回滚到安装前状态并重试 / 卸载指定插件并重试）。

功能与 quick-start.bat 对齐：
- 安装 = pnpm install
- 构建 = pnpm run clean 然后 pnpm run build
- 启动 = pnpm dsh web --port <port>（常驻 Web 服务）
- 停止 = 杀掉整棵进程树，释放端口

所有子进程通过 QProcess 异步运行，不阻塞界面。多步操作（回滚、
卸载并重试等）以“任务链”执行：任一步失败即中止后续步骤，日志呈现全过程。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import plugin_manager as pm
from config import DEFAULT_PORT, LauncherConfig
from proc_utils import free_port, kill_process_tree


@dataclass
class _Step:
    """任务链中的一步：一个子进程。

    service=True 标记最后的“常驻服务”步（dsh web）：启动后持续运行，
    不阻塞链条等待其退出；它的退出（正常或被杀）即链条结束。
    """

    label: str
    program: str
    args: list[str]
    cwd: Path
    service: bool = False


class LauncherWindow(QMainWindow):
    """启动器主窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DeepSeek Harness 启动器")
        self.resize(960, 700)

        self.config = LauncherConfig.load()
        # 当前运行中的任务进程；None 表示空闲
        self.process: QProcess | None = None
        # 标记当前进程是否为“启动”任务（决定关窗提示措辞）
        self.is_serving = False
        # 当前任务链：{name, steps, index, on_success}；None 表示无链条
        self._chain: dict | None = None
        # 插件列表的缓存（刷新按钮状态时避免重复读盘）
        self._latest_plugin_name: str | None = None
        self._snapshot_count = 0

        self._build_ui()
        self._refresh_plugin_lists()
        self._refresh_button_states()

    # ---- UI 构建 ----

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_control_tab(), "控制")
        self.tabs.addTab(self._build_plugins_tab(), "插件")
        root.addWidget(self.tabs)

    def _build_control_tab(self) -> QWidget:
        tab = QWidget()
        root = QVBoxLayout(tab)

        # 第一行：项目目录选择
        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("项目目录:"))
        self.dir_edit = QLineEdit(self.config.project_root)
        self.dir_edit.setReadOnly(True)
        self.dir_edit.setPlaceholderText("请选择 DeepSeek Harness 项目根目录")
        dir_row.addWidget(self.dir_edit, stretch=1)
        self.browse_btn = QPushButton("选择...")
        self.browse_btn.clicked.connect(self._on_browse)
        dir_row.addWidget(self.browse_btn)
        root.addLayout(dir_row)

        # 第二行：控制区（按钮 + 端口 + 开关）
        ctrl_row = QHBoxLayout()
        self.install_btn = QPushButton("安装")
        self.install_btn.clicked.connect(self._on_install)
        ctrl_row.addWidget(self.install_btn)

        self.build_btn = QPushButton("构建")
        self.build_btn.clicked.connect(self._on_build)
        ctrl_row.addWidget(self.build_btn)

        self.start_btn = QPushButton("启动")
        self.start_btn.clicked.connect(self._on_start)
        ctrl_row.addWidget(self.start_btn)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self._on_stop)
        ctrl_row.addWidget(self.stop_btn)

        ctrl_row.addStretch(1)

        ctrl_row.addWidget(QLabel("端口:"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(self.config.port or DEFAULT_PORT)
        self.port_spin.valueChanged.connect(self._on_port_changed)
        ctrl_row.addWidget(self.port_spin)

        self.open_web_check = QCheckBox("启动后打开 Web")
        self.open_web_check.setChecked(self.config.open_web_after_start)
        self.open_web_check.toggled.connect(self._on_open_web_toggled)
        ctrl_row.addWidget(self.open_web_check)

        self.no_auth_check = QCheckBox("免 token 认证")
        self.no_auth_check.setChecked(self.config.no_auth)
        self.no_auth_check.toggled.connect(self._on_no_auth_toggled)
        ctrl_row.addWidget(self.no_auth_check)

        root.addLayout(ctrl_row)

        # 日志区
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 10))
        self.log_view.setMaximumBlockCount(20000)  # 限制行数，防止长时间运行内存膨胀
        root.addWidget(self.log_view, stretch=1)

        # 底部状态行
        bottom_row = QHBoxLayout()
        self.status_label = QLabel("空闲")
        bottom_row.addWidget(self.status_label, stretch=1)
        self.clear_btn = QPushButton("清空日志")
        self.clear_btn.clicked.connect(self.log_view.clear)
        bottom_row.addWidget(self.clear_btn)
        root.addLayout(bottom_row)
        return tab

    def _build_plugins_tab(self) -> QWidget:
        tab = QWidget()
        root = QVBoxLayout(tab)

        # 安装行：自由文本（任意 pnpm 依赖 spec）+ 本地目录/压缩包选择
        install_row = QHBoxLayout()
        install_row.addWidget(QLabel("插件包:"))
        self.plugin_spec_edit = QLineEdit()
        self.plugin_spec_edit.setPlaceholderText(
            "npm 包名（可带版本，如 dsh-usage-statistics-panel@1.2.0）、github:owner/repo、本地源码目录或 .tgz 包"
        )
        self.plugin_spec_edit.returnPressed.connect(self._on_plugin_install)
        install_row.addWidget(self.plugin_spec_edit, stretch=1)
        self.plugin_browse_dir_btn = QPushButton("目录…")
        self.plugin_browse_dir_btn.clicked.connect(self._on_plugin_browse_dir)
        install_row.addWidget(self.plugin_browse_dir_btn)
        self.plugin_browse_pkg_btn = QPushButton("包…")
        self.plugin_browse_pkg_btn.clicked.connect(self._on_plugin_browse_pkg)
        install_row.addWidget(self.plugin_browse_pkg_btn)
        self.plugin_install_btn = QPushButton("安装")
        self.plugin_install_btn.clicked.connect(self._on_plugin_install)
        install_row.addWidget(self.plugin_install_btn)
        root.addLayout(install_row)

        # 第三方插件组：列表 + 卸载按钮
        plugins_group = QGroupBox("第三方插件（web profile，按安装顺序；卸载不拍快照）")
        pg = QHBoxLayout(plugins_group)
        self.plugin_list = QListWidget()
        self.plugin_list.itemSelectionChanged.connect(self._refresh_button_states)
        pg.addWidget(self.plugin_list, stretch=1)
        pb = QVBoxLayout()
        self.plugin_refresh_btn = QPushButton("刷新插件")
        self.plugin_refresh_btn.clicked.connect(self._on_plugin_refresh)
        pb.addWidget(self.plugin_refresh_btn)
        self.plugin_uninstall_btn = QPushButton("卸载选中")
        self.plugin_uninstall_btn.clicked.connect(lambda: self._on_plugin_uninstall(False))
        pb.addWidget(self.plugin_uninstall_btn)
        self.plugin_uninstall_restart_btn = QPushButton("卸载选中并重试")
        self.plugin_uninstall_restart_btn.clicked.connect(lambda: self._on_plugin_uninstall(True))
        pb.addWidget(self.plugin_uninstall_restart_btn)
        self.plugin_remove_latest_btn = QPushButton("卸载最近并重试")
        self.plugin_remove_latest_btn.clicked.connect(self._on_plugin_remove_latest)
        pb.addWidget(self.plugin_remove_latest_btn)
        pb.addStretch(1)
        pg.addLayout(pb)
        root.addWidget(plugins_group, stretch=1)

        # 快照组：列表 + 回滚按钮
        snaps_group = QGroupBox("安装前快照（最新在前，每次经本启动器安装前自动拍摄，最多保留 5 份）")
        sg = QHBoxLayout(snaps_group)
        self.snap_list = QListWidget()
        self.snap_list.setFixedHeight(110)
        self.snap_list.itemSelectionChanged.connect(self._refresh_button_states)
        sg.addWidget(self.snap_list, stretch=1)
        sb = QVBoxLayout()
        self.snap_rollback_btn = QPushButton("回滚到选中并重试")
        self.snap_rollback_btn.clicked.connect(lambda: self._on_rollback(False))
        sb.addWidget(self.snap_rollback_btn)
        self.snap_rollback_latest_btn = QPushButton("回滚到最新并重试")
        self.snap_rollback_latest_btn.clicked.connect(lambda: self._on_rollback(True))
        sb.addWidget(self.snap_rollback_latest_btn)
        sb.addStretch(1)
        sg.addLayout(sb)
        root.addWidget(snaps_group)
        return tab

    # ---- 配置项变更 ----

    def _on_browse(self) -> None:
        # 上次选过目录时，对话框定位到其父级，便于确认/更换；否则从用户主目录开始
        if self.config.project_root and Path(self.config.project_root).is_dir():
            start_dir = str(Path(self.config.project_root).parent)
        else:
            start_dir = str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "选择项目根目录", start_dir)
        if not chosen:
            return
        self.config.project_root = chosen
        self.dir_edit.setText(chosen)
        self.config.save()
        self._refresh_button_states()

    def _on_port_changed(self, value: int) -> None:
        self.config.port = value
        self.config.save()

    def _on_open_web_toggled(self, checked: bool) -> None:
        self.config.open_web_after_start = checked
        self.config.save()

    def _on_no_auth_toggled(self, checked: bool) -> None:
        self.config.no_auth = checked
        self.config.save()

    # ---- 前置检查（软提示）----

    def _project_root(self) -> Path | None:
        """返回已配置的项目根 Path，未配置或不含 package.json 时提示并返回 None。"""
        root = self.config.project_root
        if not root:
            self._warn("请先选择项目根目录。")
            return None
        path = Path(root)
        if not (path / "package.json").is_file():
            self._warn(f"所选目录不是项目根（未找到 package.json）:\n{root}")
            return None
        return path

    def _profile(self) -> Path:
        """web profile 目录（插件管理对象，固定 web）。"""
        return pm.web_profile_dir()

    def _warn(self, message: str) -> None:
        QMessageBox.warning(self, "提示", message)

    def _confirm(self, title: str, message: str) -> bool:
        return (
            QMessageBox.question(self, title, message, QMessageBox.Yes | QMessageBox.No)
            == QMessageBox.Yes
        )

    # ---- 任务：安装 / 构建 / 启动（控制页签）----

    def _on_install(self) -> None:
        root = self._project_root()
        if root is None:
            return
        # Windows 上 pnpm 是 pnpm.cmd，QProcess 直连可执行名会找不到，
        # 统一通过 cmd /c 调用，与构建/启动保持一致
        self._run_chain("安装", [_Step("pnpm install", "cmd", ["/c", "pnpm install"], root)])

    def _on_build(self) -> None:
        root = self._project_root()
        if root is None:
            return
        if not (root / "node_modules").is_dir():
            self._warn("未找到 node_modules，请先执行“安装”。")
            return
        # 用 shell 串联两步，任一步失败则中止（&&）
        self._run_chain(
            "构建",
            [_Step("pnpm run clean && pnpm run build", "cmd", ["/c", "pnpm run clean && pnpm run build"], root)],
        )

    def _on_start(self) -> None:
        root = self._project_root()
        if root is None:
            return
        if not (root / "node_modules").is_dir():
            self._warn("未找到 node_modules，请先执行“安装”。")
            return
        if not (root / "apps" / "web" / "dist" / "index.html").is_file():
            self._warn("Web 前端尚未构建，请先执行“构建”。")
            return
        self._run_chain("启动", [self._service_step(root)])

    def _on_stop(self) -> None:
        if self.process is None:
            return
        self._append_log("[停止] 正在终止进程树...\n")
        pid = int(self.process.processId())
        if pid > 0:
            kill_process_tree(pid)
        # QProcess 自身也发一个终止信号兜底；退出信号到达后链条自然结束
        self.process.kill()

    # ---- 任务：插件管理（插件页签）----

    def _on_plugin_browse_dir(self) -> None:
        """选择本地插件源码目录（link 语义：源码改动重启即生效）。"""
        chosen = QFileDialog.getExistingDirectory(self, "选择插件源码目录")
        if chosen:
            self.plugin_spec_edit.setText(chosen)

    def _on_plugin_browse_pkg(self) -> None:
        """选择本地插件压缩包（pnpm pack 产物）。"""
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "选择插件压缩包",
            filter="插件包 (*.tgz *.tar.gz *.tar);;所有文件 (*)",
        )
        if chosen:
            self.plugin_spec_edit.setText(chosen)

    def _on_plugin_refresh(self) -> None:
        """重新读取 profile manifest 与快照目录，刷新插件/快照两个列表。

        列表原先只在本启动器自身安装/卸载/回滚成功时刷新；在 DSH（Web 界面或命令行）
        里安装/卸载插件后，本窗口不会感知，需点此按钮重新检查已安装的插件。
        """
        self._refresh_plugin_lists()

    def _on_plugin_install(self) -> None:
        root = self._project_root()
        if root is None:
            return
        spec = self.plugin_spec_edit.text().strip()
        if not spec:
            self._warn("请输入或选择插件包：npm 包名（可带版本）、本地源码目录或 .tgz 压缩包。")
            return
        # 安装前必拍快照，这是“回滚到安装前状态”的依据
        profile = self._profile()
        snap = pm.take_snapshot(profile, spec)
        self._append_log(f"[插件] 已拍安装前快照: {snap.stamp}\n")
        cmd = f"pnpm dsh plugin --profile web add {pm.shell_quote(spec)}"
        self._run_chain(
            "安装插件",
            [_Step(f"安装插件 {spec}", "cmd", ["/c", cmd], root)],
            on_success=self._refresh_plugin_lists,
        )

    def _on_plugin_uninstall(self, restart: bool) -> None:
        item = self.plugin_list.currentItem()
        if item is None:
            self._warn("请先在列表中选择要卸载的插件。")
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        self._do_remove(name, restart)

    def _on_plugin_remove_latest(self) -> None:
        latest = pm.latest_plugin(self._profile())
        if not latest:
            self._warn("未安装任何第三方插件，没有可卸载的插件。")
            return
        self._do_remove(latest, restart=True)

    def _do_remove(self, name: str, restart: bool) -> None:
        """卸载指定插件（可选随后重启 Web 服务）的完整链条。"""
        root = self._project_root()
        if root is None:
            return
        suffix = "，并重启 Web 服务" if restart else ""
        if not self._confirm("确认卸载", f"将卸载插件 {name}{suffix}，确定？"):
            return
        # 恢复链条前置：先停掉当前服务/任务（进程还在时端口也被它占着）
        self._stop_service_quiet()
        cmd = f"pnpm dsh plugin --profile web remove {name}"
        steps = [_Step(f"卸载插件 {name}", "cmd", ["/c", cmd], root)]
        if restart:
            steps.append(self._service_step(root))
        self._run_chain(
            "卸载插件并重试" if restart else "卸载插件",
            steps,
            on_success=self._refresh_plugin_lists,
        )

    def _on_rollback(self, use_latest: bool) -> None:
        """回滚到某份安装前快照（use_latest=False 时取列表选中项）并重启。"""
        profile = self._profile()
        snaps = pm.list_snapshots(profile)
        if not snaps:
            self._warn("没有可用的安装前快照：只有经本启动器“安装”产生的快照可回滚。")
            return
        if use_latest:
            target = snaps[0]
        else:
            item = self.snap_list.currentItem()
            if item is None:
                self._warn("请先在列表中选择要回滚到的快照。")
                return
            target = item.data(Qt.ItemDataRole.UserRole)
        root = self._project_root()
        if root is None:
            return
        detail = f"{target.taken_at:%Y-%m-%d %H:%M} · 安装 {target.installed} 之前"
        if not self._confirm(
            "确认回滚",
            f"将 web profile 还原到安装前状态（{detail}），并重启 Web 服务？\n\n"
            "profile 目录的 package.json / pnpm-lock.yaml / pnpm-workspace.yaml "
            "会被快照覆盖，随后重建依赖并验证配置组合。",
        ):
            return
        self._stop_service_quiet()
        restored, deleted = pm.restore_snapshot(profile, target)
        self._append_log(
            f"[回滚] 还原: {', '.join(restored) or '(无)'}；删除: {', '.join(deleted) or '(无)'}\n"
        )
        steps = [
            _Step("重建 profile 依赖 (pnpm install)", "cmd", ["/c", "pnpm install"], profile),
            _Step("验证配置组合 (--dump-config)", "cmd", ["/c", "pnpm dsh --profile web --dump-config"], root),
            self._service_step(root),
        ]
        self._run_chain("回滚到安装前状态并重试", steps, on_success=self._refresh_plugin_lists)

    # ---- 通用：任务链 ----

    def _run_chain(
        self,
        name: str,
        steps: list[_Step],
        on_success: Callable[[], None] | None = None,
    ) -> None:
        """启动一条任务链：顺序执行各步，任一步失败即中止后续步骤。"""
        if self.process is not None:
            self._warn("已有任务正在运行，请先停止。")
            return
        if not steps:
            return
        self._chain = {"name": name, "steps": steps, "index": 0, "on_success": on_success}
        self._start_step(steps[0])

    def _start_step(self, step: _Step) -> None:
        chain = self._chain
        self._append_log(f"\n===== [{chain['name']}] {step.label} =====\n")
        self.status_label.setText(f"运行中: {chain['name']}")
        if step.service:
            self.is_serving = True
        proc = QProcess(self)
        proc.setWorkingDirectory(str(step.cwd))
        proc.setProcessChannelMode(QProcess.MergedChannels)  # 合并 stdout/stderr
        proc.readyReadStandardOutput.connect(self._on_ready_read)
        proc.finished.connect(lambda code, status, p=proc, s=step: self._on_step_finished(p, s, code))
        proc.errorOccurred.connect(self._on_process_error)
        self.process = proc
        self._refresh_button_states()
        proc.start(step.program, step.args)

    def _on_step_finished(self, proc: QProcess, step: _Step, code: int) -> None:
        if proc is not self.process:
            return  # 陈旧进程（停止按钮或恢复链条杀掉的），其信号晚到，忽略
        if step.service:
            # 服务步结束（正常退出或被杀）：链条结束
            self._finish_chain(code)
            return
        if code != 0:
            self._append_log(f"\n===== [{self._chain['name']}] 步骤失败（退出码 {code}），中止后续步骤 =====\n")
            self._finish_chain(code)
            return
        self._chain["index"] += 1
        steps = self._chain["steps"]
        if self._chain["index"] < len(steps):
            self._start_step(steps[self._chain["index"]])
        else:
            self._finish_chain(0)

    def _finish_chain(self, code: int) -> None:
        chain = self._chain
        name = chain["name"] if chain else "任务"
        self._append_log(f"\n===== [{name}] 结束，退出码 {code} =====\n")
        if code == 0 and chain is not None and chain["on_success"] is not None:
            chain["on_success"]()
        self._chain = None
        self._reset_to_idle()

    def _stop_service_quiet(self) -> None:
        """恢复链条前置：停掉当前任务/服务并立即清空进程引用，不等待退出。

        旧进程的 finished 信号会晚到，由 _on_step_finished 的身份检查过滤。
        """
        if self.process is None:
            return
        pid = int(self.process.processId())
        if pid > 0:
            kill_process_tree(pid)
        self.process.kill()
        self.process = None
        self.is_serving = False

    def _service_step(self, root: Path) -> _Step:
        """构造“启动 Web 服务”步：先清端口，再按“启动后打开 Web”开关拼命令。

        dsh web 默认会自己打开浏览器；未勾选“启动后打开 Web”时传 --no-open。
        """
        port = self.port_spin.value()
        freed = free_port(port)
        if freed:
            self._append_log(
                f"[启动] 端口 {port} 被占用，已清理进程: {', '.join(map(str, freed))}\n"
            )
        command = f"pnpm dsh web --port {port}"
        if not self.open_web_check.isChecked():
            command += " --no-open"
        if self.no_auth_check.isChecked():
            command += " --no-auth"
        return _Step(f"启动 Web 服务 (端口 {port})", "cmd", ["/c", command], root, service=True)

    def _on_ready_read(self) -> None:
        if self.process is None:
            return
        data = self.process.readAllStandardOutput()
        text = bytes(data).decode("utf-8", errors="replace")
        self._append_log(text)

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        # 启动失败时 finished 信号不一定会发，必须在这里复位状态，
        # 否则界面会永久卡在“运行中”，按钮全灰、关窗口误报“服务仍在运行”。
        if error == QProcess.FailedToStart and self.process is not None:
            self._append_log("\n[错误] 进程启动失败，请检查 pnpm 是否已安装并在 PATH 中。\n")
            self._finish_chain(1)

    def _reset_to_idle(self) -> None:
        """把界面复位到空闲状态：清空当前进程引用、刷新按钮。"""
        self.status_label.setText("空闲")
        self.process = None
        self.is_serving = False
        self._refresh_button_states()

    # ---- 插件列表与按钮状态 ----

    def _refresh_plugin_lists(self) -> None:
        """重读 profile 与快照目录，刷新两个列表及其缓存。"""
        profile = self._profile()
        self.plugin_list.clear()
        for name, spec in pm.installed_plugins(profile):
            item = QListWidgetItem(f"{name}  ({spec})")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.plugin_list.addItem(item)
        self.snap_list.clear()
        snaps = pm.list_snapshots(profile)
        for snap in snaps:
            item = QListWidgetItem(f"{snap.taken_at:%Y-%m-%d %H:%M}  ·  安装 {snap.installed} 之前")
            item.setData(Qt.ItemDataRole.UserRole, snap)
            self.snap_list.addItem(item)
        self._latest_plugin_name = pm.latest_plugin(profile)
        self._snapshot_count = len(snaps)
        self._refresh_button_states()

    def _refresh_button_states(self) -> None:
        """按“单任务互斥”规则刷新按钮可用状态（含插件页签）。"""
        running = self.process is not None
        has_project = bool(self.config.project_root)
        # 运行中时，除“停止”外全部置灰
        self.install_btn.setEnabled(not running and has_project)
        self.build_btn.setEnabled(not running and has_project)
        self.start_btn.setEnabled(not running and has_project)
        self.stop_btn.setEnabled(running)
        self.browse_btn.setEnabled(not running)
        # 插件页签
        self.plugin_refresh_btn.setEnabled(not running)
        self.plugin_install_btn.setEnabled(not running and has_project)
        self.plugin_browse_dir_btn.setEnabled(not running)
        self.plugin_browse_pkg_btn.setEnabled(not running)
        plugin_selected = self.plugin_list.currentItem() is not None
        self.plugin_uninstall_btn.setEnabled(not running and has_project and plugin_selected)
        self.plugin_uninstall_restart_btn.setEnabled(not running and has_project and plugin_selected)
        self.plugin_remove_latest_btn.setEnabled(
            not running and has_project and self._latest_plugin_name is not None
        )
        snap_selected = self.snap_list.currentItem() is not None
        self.snap_rollback_btn.setEnabled(not running and has_project and snap_selected)
        self.snap_rollback_latest_btn.setEnabled(
            not running and has_project and self._snapshot_count > 0
        )

    # ---- 日志与状态 ----

    def _append_log(self, text: str) -> None:
        self.log_view.moveCursor(QTextCursor.End)
        self.log_view.insertPlainText(text)
        self.log_view.moveCursor(QTextCursor.End)

    # ---- 关闭窗口 ----

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名约定)
        """退出即停：关窗口前无条件停掉本启动器启动的任务/服务，绝不留后台孤儿进程。

        有任务在跑时先确认退出意愿；确认后一并终止进程树。
        """
        if self.process is None:
            event.accept()
            return
        reply = QMessageBox.question(
            self,
            "确认退出",
            "有任务/服务仍在运行，退出将一并停止。确定退出吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            event.ignore()
            return
        # 无论如何，退出前停掉当前进程树，释放端口
        pid = int(self.process.processId())
        if pid > 0:
            kill_process_tree(pid)
        self.process.kill()
        self.process.waitForFinished(3000)
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_DontShowIconsInMenus, False)
    window = LauncherWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
