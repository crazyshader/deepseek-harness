"""用 PyInstaller 把启动器打包成单文件 exe。

用法（在 dsh-launcher 目录下）:
    python build.py

产物: dist/dsh-launcher.exe

打包为 --windowed（无控制台窗口）、--onefile（单个 exe），
双击即用，无需目标机器安装 Python。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# 打包产物路径
_OUTPUT_EXE = Path(__file__).parent / "dist" / "dsh-launcher.exe"


def main() -> int:
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name",
        "dsh-launcher",
        # config.py 与 proc_utils.py 是同目录模块，PyInstaller 会自动打包
        "main.py",
    ]
    # 记录打包前的修改时间，用于判断产物是否被真正重新生成
    before_mtime = _OUTPUT_EXE.stat().st_mtime if _OUTPUT_EXE.is_file() else 0.0

    print("运行:", " ".join(args))
    code = subprocess.call(args)

    # 成功判据：exe 存在，且「退出码为 0」或「修改时间已更新」二者之一成立。
    # 两个条件都需要，因为两种正常情形各只满足其中一个：
    #   - 缓存命中：PyInstaller 判定产物已是最新，不重写文件，mtime 不变但退出码 0；
    #   - 清理阶段偶发非 0 退出码：退出码不足为凭，但 exe 确实被重新写出。
    # 只有「退出码非 0 且 mtime 未更新」才是真失败——旧产物被占用没能覆盖。
    if _OUTPUT_EXE.is_file() and (code == 0 or _OUTPUT_EXE.stat().st_mtime > before_mtime):
        print(f"打包成功: {_OUTPUT_EXE}")
        return 0
    if _OUTPUT_EXE.is_file() and before_mtime > 0:
        print(f"打包失败: 产物未更新，可能被占用（旧 exe 仍在运行？）: {_OUTPUT_EXE}")
        return 1
    print(f"打包失败: 未生成 {_OUTPUT_EXE}，PyInstaller 退出码 {code}")
    return code or 1


if __name__ == "__main__":
    raise SystemExit(main())
