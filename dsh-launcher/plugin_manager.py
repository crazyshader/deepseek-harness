"""web profile 插件管理：profile 定位、插件列表、安装前快照与还原。

启动器「插件」页签的逻辑层：纯文件操作 + JSON 读写，不依赖 GUI，
便于单独验证。插件的安装/卸载本身交给 `dsh plugin --profile web add|remove`
（它转发 pnpm 并维护 bundles 层列表）；本模块负责三件事：

1. 列出 profile 已装的第三方插件（依赖型 bundle，按安装顺序）；
2. 安装前快照 profile 的 manifest 文件（不拷 node_modules——manifest
   还原后用 `pnpm install` 重建；不碰 cordis.patch.yml——用户的自有层）；
3. 把 profile 还原到某份快照记录的完整状态。
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# 启动器启动的就是 web profile（pnpm dsh web），插件管理只针对它。
PROFILE_NAME = "web"

# profile 的 manifest 文件：插件 add/remove（pnpm）只写这几个文件。
# 快照/还原只针对它们；node_modules 由 pnpm install 重建，
# cordis.patch.yml（用户自有层）永不触碰。
MANIFEST_FILES: tuple[str, ...] = ("package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml")

# 保留的安装前快照份数，超出时删除最旧的。
MAX_SNAPSHOTS = 5


def dsh_home() -> Path:
    """返回 DSH home 目录：优先 DSH_HOME 环境变量，缺省 ~/.dsh。"""
    env = os.environ.get("DSH_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".dsh"


def web_profile_dir() -> Path:
    """返回 web profile 的目录（不要求已存在）。"""
    return dsh_home() / "profiles" / PROFILE_NAME


def snapshot_root(profile: Path | None = None) -> Path:
    """返回快照存放目录。

    放在 profiles/ 之下、profile 目录之外（隐藏目录，不与任何
    profile 名冲突），避免快照被 profile 内的操作波及。
    """
    profile = profile or web_profile_dir()
    return profile.parent / ".dsh-plugin-snapshots" / PROFILE_NAME


@dataclass(frozen=True)
class Snapshot:
    """一份安装前快照。"""

    stamp: str  # 目录名，形如 20260831-203345
    directory: Path
    installed: str  # 拍快照时正在安装的插件（展示为“安装 X 之前”）
    taken_at: datetime


def profile_manifest(profile: Path) -> dict:
    """读取 profile 的 package.json；缺失或损坏时返回空 dict。

    损坏的 manifest 正是恢复场景之一，读取绝不能抛异常。
    """
    path = profile / "package.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def installed_plugins(profile: Path) -> list[tuple[str, str]]:
    """列出 profile 已装的第三方插件（依赖型 bundle），按安装顺序。

    返回 (包名, 依赖 spec) 对。dsh-base / dsh-web-app 等模板 bundle
    不在 dependencies 列表里，自然被排除——它们不可卸载。
    """
    data = profile_manifest(profile)
    deps = data.get("dependencies") or {}
    bundles = ((data.get("dsh") or {}).get("profile") or {}).get("bundles") or []
    return [(name, deps[name]) for name in bundles if name in deps]


def latest_plugin(profile: Path) -> str | None:
    """返回最近安装的第三方插件名（bundles 列表最后一个依赖型条目）。"""
    plugins = installed_plugins(profile)
    return plugins[-1][0] if plugins else None


def take_snapshot(profile: Path, installing: str) -> Snapshot:
    """安装前快照：把 profile 下存在的 manifest 文件拷入带时间戳的目录。

    每次 GUI 安装前调用一次；自动清理超出 MAX_SNAPSHOTS 的最旧快照。
    """
    root = snapshot_root(profile)
    root.mkdir(parents=True, exist_ok=True)
    taken_at = datetime.now()
    stamp = taken_at.strftime("%Y%m%d-%H%M%S")
    base = stamp
    counter = 0
    while (root / stamp).exists():
        counter += 1
        stamp = f"{base}-{counter}"
    snap_dir = root / stamp
    snap_dir.mkdir()
    for name in MANIFEST_FILES:
        src = profile / name
        if src.is_file():
            shutil.copy2(src, snap_dir / name)
    meta = {"installed": installing, "taken_at": taken_at.isoformat(timespec="seconds")}
    (snap_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _prune_snapshots(root)
    return Snapshot(stamp=stamp, directory=snap_dir, installed=installing, taken_at=taken_at)


def list_snapshots(profile: Path | None = None) -> list[Snapshot]:
    """返回全部快照，最新在前；损坏的条目跳过。"""
    root = snapshot_root(profile)
    if not root.is_dir():
        return []
    snaps: list[Snapshot] = []
    for child in root.iterdir():
        meta_path = child / "meta.json"
        if not child.is_dir() or not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            taken_at = datetime.fromisoformat(str(meta.get("taken_at", "")))
            installed = str(meta.get("installed", "?"))
        except (json.JSONDecodeError, OSError, ValueError):
            continue
        snaps.append(Snapshot(stamp=child.name, directory=child, installed=installed, taken_at=taken_at))
    snaps.sort(key=lambda s: s.stamp, reverse=True)
    return snaps


def restore_snapshot(profile: Path, snap: Snapshot) -> tuple[list[str], list[str]]:
    """把 profile 还原到快照记录的状态。

    快照里有的文件覆盖回 profile；profile 里存在但快照未记录的
    manifest 文件删除，确保完整回到安装前（例如回滚掉 git 源插件
    时一并清掉它写入的 pnpm-workspace.yaml）。
    返回 (还原的文件列表, 删除的文件列表)。
    """
    profile.mkdir(parents=True, exist_ok=True)
    restored: list[str] = []
    deleted: list[str] = []
    for name in MANIFEST_FILES:
        src = snap.directory / name
        dst = profile / name
        if src.is_file():
            shutil.copy2(src, dst)
            restored.append(name)
        elif dst.is_file():
            dst.unlink()
            deleted.append(name)
    return restored, deleted


def _prune_snapshots(root: Path) -> None:
    """删除超出 MAX_SNAPSHOTS 的最旧快照目录。"""
    entries = sorted(
        (c for c in root.iterdir() if c.is_dir()),
        key=lambda c: c.name,
        reverse=True,
    )
    for stale in entries[MAX_SNAPSHOTS:]:
        shutil.rmtree(stale, ignore_errors=True)


def shell_quote(arg: str) -> str:
    """为 `cmd /c` 命令串加引号：含空白的参数用双引号包住，否则原样。"""
    if any(ch.isspace() for ch in arg):
        return f'"{arg}"'
    return arg
