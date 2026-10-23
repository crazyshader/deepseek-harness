"""进程树与端口清理工具（Windows）。

启动器需要两种“可靠终止”能力：
1. 杀掉自己启动的 pnpm→node→dsh 整棵进程树（停止按钮、关窗口）；
2. 启动前探测目标端口，无论占用者是谁都清理掉，保证端口可用（幂等启动）。

均通过系统命令实现，不引入第三方依赖，便于 PyInstaller 打包。
"""

from __future__ import annotations

import codecs
import locale
import os
import shutil
import subprocess

# 无窗口执行子命令，避免打包成 --windowed 后弹出黑框。
# 公开给同项目其他模块复用，避免这个魔数在多处重写。
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def decode_output(data: bytes) -> str:
    """解码子进程输出：先按 UTF-8，失败再按系统 ANSI/OEM 代码页（中文系统为 GBK）。"""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for enc in (_ansi_encoding(), "gbk"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _ansi_encoding() -> str:
    """系统 ANSI 代码页（中文系统为 GBK），取不到时回退 gbk。"""
    # UTF-8 模式（Python 3.15 起默认）下 getpreferredencoding 恒为 utf-8，
    # 需用 getencoding（3.11+）取真实 ANSI 代码页
    getter = getattr(locale, "getencoding", None)
    enc = getter() if getter else locale.getpreferredencoding(False)
    try:
        codecs.lookup(enc)
        return enc
    except LookupError:
        return "gbk"


class StreamDecoder:
    """子进程输出的增量解码器：先按 UTF-8，遇到非法序列后整条流改按 ANSI 代码页。

    增量解码会缓存块尾不完整的多字节字符，避免字符被读取块边界切断而乱字。
    每个子进程使用一个独立实例。
    """

    def __init__(self) -> None:
        self._utf8 = codecs.getincrementaldecoder("utf-8")()
        self._fallback = None

    def feed(self, data: bytes) -> str:
        if self._fallback is None:
            pending = self._utf8.getstate()[0]
            try:
                return self._utf8.decode(data)
            except UnicodeDecodeError:
                # 连同上一块缓存的残余字节一起改按 ANSI 代码页解码
                self._fallback = codecs.getincrementaldecoder(_ansi_encoding())(errors="replace")
                data = pending + data
        return self._fallback.decode(data)


def ensure_pnpm_path() -> tuple[str | None, str, bool]:
    """确保子进程能找到 pnpm。

    返回 (需要加到 PATH 最前的目录或 None, 提示信息, 是否可用)。
    顺序：PATH 中已有 -> npm/PNPM_HOME 常见目录 -> corepack 垫片（写入启动器配置目录，无副作用于全局）。
    不用 `corepack pnpm` 改写命令，因为脚本内部还会嵌套调用 pnpm。
    """
    if shutil.which("pnpm"):
        return None, "", True
    # 常见全局安装目录可能不在 GUI 进程的 PATH 中
    candidates = [os.environ.get("PNPM_HOME"), os.path.join(os.environ.get("APPDATA", ""), "npm")]
    for d in candidates:
        if d and os.path.isfile(os.path.join(d, "pnpm.cmd")):
            return d, f"[提示] 已将 {d} 加入 PATH 以找到 pnpm。\n", True
    corepack = shutil.which("corepack")  # Windows 下解析为 corepack.cmd 的完整路径
    if not corepack:
        return None, (
            "[错误] 未找到 pnpm，也未找到 corepack。请安装 Node.js（含 corepack）后执行 "
            "`corepack enable`，或执行 `npm i -g pnpm`。\n"
        ), False
    shim = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "dsh-launcher", "pnpm-shim")
    if os.path.isfile(os.path.join(shim, "pnpm.cmd")):
        return shim, "", True
    try:
        os.makedirs(shim, exist_ok=True)
        result = subprocess.run(
            [corepack, "enable", "--install-directory", shim],
            creationflags=NO_WINDOW,
            capture_output=True,
            timeout=30,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"[错误] 未找到 pnpm，通过 corepack 启用失败: {exc}\n", False
    if result.returncode != 0 or not os.path.isfile(os.path.join(shim, "pnpm.cmd")):
        out = decode_output((result.stdout or b"") + (result.stderr or b""))
        return None, f"[错误] 未找到 pnpm，`corepack enable` 失败:\n{out}\n", False
    return shim, f"[提示] 未找到 pnpm，已通过 corepack 启用（垫片目录 {shim}）。\n", True


def kill_process_tree(pid: int) -> None:
    """杀掉指定 PID 及其所有子进程。

    用 taskkill /T（连子进程）/F（强制），可靠终掉
    pnpm→node→dsh 整条链，端口随之释放。进程已退出时静默忽略。
    """
    if pid <= 0:
        return
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        creationflags=NO_WINDOW,
        capture_output=True,
    )


def find_pids_on_port(port: int) -> list[int]:
    """返回正在监听/占用指定端口的进程 PID 列表。

    解析 netstat 输出，只取处于 LISTENING 状态的行，避免把
    临时的客户端连接也算进来。
    """
    result = subprocess.run(
        ["netstat", "-ano", "-p", "TCP"],
        creationflags=NO_WINDOW,
        capture_output=True,
    )
    pids: set[int] = set()
    needle = f":{port}"
    # netstat 按系统 OEM 代码页（中文系统为 GBK）输出表头，用 UTF-8 解码会抛
    # UnicodeDecodeError 并导致 stdout 为 None；这里取字节并容错解码，
    # 数据行只含 ASCII，不受影响。
    stdout = (result.stdout or b"").decode("utf-8", errors="replace")
    for line in stdout.splitlines():
        parts = line.split()
        # 形如: TCP  0.0.0.0:3080  0.0.0.0:0  LISTENING  12345
        if len(parts) < 5:
            continue
        if parts[3] != "LISTENING":
            continue
        local_addr = parts[1]
        # 匹配本地地址的端口段，防止 :30800 这类误命中
        if local_addr.endswith(needle):
            try:
                pids.add(int(parts[4]))
            except ValueError:
                continue
    return list(pids)


def free_port(port: int) -> list[int]:
    """清理占用指定端口的所有进程，返回被清理的 PID 列表。

    用于启动前的幂等清理：无论占用者是本启动器上次启的、
    还是外部（quick-start.bat 等）启的，一律杀掉整棵树。
    """
    pids = find_pids_on_port(port)
    for pid in pids:
        kill_process_tree(pid)
    return pids
