"""启动器配置的持久化。

配置存到用户目录下（%APPDATA%\\dsh-launcher\\config.json），
记住项目根目录、端口、以及“启动后打开 Web”开关，避免每次启动重新选。
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# 默认端口，与 quick-start.bat 保持一致
DEFAULT_PORT = 3080


def _config_dir() -> Path:
    """返回配置目录，优先用 %APPDATA%，回落到用户主目录。"""
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "dsh-launcher"
    return Path.home() / ".dsh-launcher"


def _config_path() -> Path:
    return _config_dir() / "config.json"


def canonical_path(raw: str) -> str:
    """返回磁盘上的真实大小写路径；空串或目录不存在时原样返回。

    Windows 路径不区分大小写，但 tsc、rolldown 会把 E:\\AI 与 e:\\ai 当成两个文件，
    所以保存和使用项目目录前都要规整成磁盘上的写法。
    """
    if not raw or not Path(raw).exists():
        return raw
    return str(Path(raw).resolve())


def detect_project_root() -> str:
    """按启动器自身位置推断项目根；找不到返回空串。

    源码运行时启动器在 <项目>/dsh-launcher/ 下；打包成 exe 后可能在
    <项目>/dsh-launcher/dist/ 或直接放在项目根，所以向上找几层。
    """
    start = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    for candidate in (start, *list(start.parents)[:3]):
        if (candidate / "package.json").is_file() and (candidate / "packages").is_dir():
            return str(candidate)
    return ""


@dataclass
class LauncherConfig:
    """启动器的持久化配置。

    project_root 为空表示还没选过项目目录，首次运行时需要让用户选择。
    """

    project_root: str = ""
    port: int = DEFAULT_PORT
    open_web_after_start: bool = True
    no_auth: bool = False

    @staticmethod
    def load() -> "LauncherConfig":
        """从磁盘读取配置；文件不存在或损坏时返回默认配置。"""
        path = _config_path()
        if not path.is_file():
            return LauncherConfig(project_root=detect_project_root())
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # 配置损坏不应阻断启动器，回落到默认值
            return LauncherConfig()
        saved = canonical_path(str(data.get("project_root", "")))
        # 目录被移动或重新下载后，保存的路径会失效，此时改用启动器所在项目
        if not (saved and (Path(saved) / "package.json").is_file()):
            saved = detect_project_root()
        return LauncherConfig(
            project_root=saved,
            port=int(data.get("port", DEFAULT_PORT)),
            open_web_after_start=bool(data.get("open_web_after_start", True)),
            no_auth=bool(data.get("no_auth", False)),
        )

    def save(self) -> None:
        """把配置写回磁盘，必要时创建目录。"""
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
