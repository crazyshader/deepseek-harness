"""启动器配置的持久化。

配置存到用户目录下（%APPDATA%\\dsh-launcher\\config.json），
记住项目根目录、端口、以及“启动后打开 Web”开关，避免每次启动重新选。
"""

from __future__ import annotations

import json
import os
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


@dataclass
class LauncherConfig:
    """启动器的持久化配置。

    project_root 为空表示还没选过项目目录，首次运行时需要让用户选择。
    """

    project_root: str = ""
    port: int = DEFAULT_PORT
    open_web_after_start: bool = True

    @staticmethod
    def load() -> "LauncherConfig":
        """从磁盘读取配置；文件不存在或损坏时返回默认配置。"""
        path = _config_path()
        if not path.is_file():
            return LauncherConfig()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # 配置损坏不应阻断启动器，回落到默认值
            return LauncherConfig()
        return LauncherConfig(
            project_root=str(data.get("project_root", "")),
            port=int(data.get("port", DEFAULT_PORT)),
            open_web_after_start=bool(data.get("open_web_after_start", True)),
        )

    def save(self) -> None:
        """把配置写回磁盘，必要时创建目录。"""
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
