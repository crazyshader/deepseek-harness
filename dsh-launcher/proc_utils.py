"""进程树与端口清理工具（Windows）。

启动器需要两种“可靠终止”能力：
1. 杀掉自己启动的 pnpm→node→dsh 整棵进程树（停止按钮、关窗口）；
2. 启动前探测目标端口，无论占用者是谁都清理掉，保证端口可用（幂等启动）。

均通过系统命令实现，不引入第三方依赖，便于 PyInstaller 打包。
"""

from __future__ import annotations

import subprocess

# 无窗口执行子命令，避免打包成 --windowed 后弹出黑框
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def kill_process_tree(pid: int) -> None:
    """杀掉指定 PID 及其所有子进程。

    用 taskkill /T（连子进程）/F（强制），可靠终掉
    pnpm→node→dsh 整条链，端口随之释放。进程已退出时静默忽略。
    """
    if pid <= 0:
        return
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        creationflags=_NO_WINDOW,
        capture_output=True,
    )


def find_pids_on_port(port: int) -> list[int]:
    """返回正在监听/占用指定端口的进程 PID 列表。

    解析 netstat 输出，只取处于 LISTENING 状态的行，避免把
    临时的客户端连接也算进来。
    """
    result = subprocess.run(
        ["netstat", "-ano", "-p", "TCP"],
        creationflags=_NO_WINDOW,
        capture_output=True,
        text=True,
    )
    pids: set[int] = set()
    needle = f":{port}"
    for line in result.stdout.splitlines():
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
