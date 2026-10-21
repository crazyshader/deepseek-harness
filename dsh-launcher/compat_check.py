"""第三方插件与当前 harness 版本的兼容性检查（只读，纯 Python，无外部依赖）。

只核对版本范围声明是否覆盖当前值，不联网、不跑子进程、不实际加载插件——
结果是静态推导，不是运行时实测。peerDependenciesMeta 标记为 optional 的依赖
版本不匹配时判定为“降级”而非“不兼容”，因为这类依赖缺失时插件设计上应能
继续运行（功能可能减少）；非 optional 的不匹配判定为“不兼容”。

范围写法只覆盖本仓插件声明里实际出现过的子集：^、~、比较符
（>= <= > < =）以空格 AND 连接、多个方案用 "||" OR 连接、裸精确版本号。
遇到未覆盖的写法（git 依赖版本表、workspace: 等）返回“无法判断”，
不冒充判断结果。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import plugin_manager as pm

# ---- 极简 semver ----
#
# 额外实现 npm-semver 文档写明的预发布版本“同源三元组”门槛规则：候选版本
# 带预发布标签时，比较符集合（一个 AND 段）里必须存在与它 [major,minor,patch]
# 三元组相同、且同样带预发布标签的比较符，这一段才可能命中；否则整段直接判
# 不满足，不看数值顺序。缺了这条规则，"<0.2.0" 这样的比较符会把
# "0.2.0-rc.2" 误判为满足（预发布版本按数值排序确实小于同号正式版），
# 但 npm 语义上不允许预发布版本无差别地满足未显式声明预发布区间的范围。

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?")


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()

    def core(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)


def parse_version(text: str) -> SemVer | None:
    """解析一个裸版本号（不含范围符号）；解析失败返回 None。"""
    match = _VERSION_RE.match(text.strip())
    if not match:
        return None
    major, minor, patch, pre = match.groups()
    prerelease = tuple(pre.split(".")) if pre else ()
    return SemVer(int(major), int(minor), int(patch), prerelease)


def _pre_key(part: str) -> tuple[int, int, str]:
    """预发布标识符分量的排序键：纯数字分量小于字符串分量（semver 规则）。"""
    if part.isdigit():
        return (0, int(part), "")
    return (1, 0, part)


def compare(a: SemVer, b: SemVer) -> int:
    """比较两个版本：a<b 返回负数，相等返回 0，a>b 返回正数。"""
    if a.core() != b.core():
        return -1 if a.core() < b.core() else 1
    if a.prerelease == b.prerelease:
        return 0
    if not a.prerelease:
        return 1  # 正式版 > 同号预发布版
    if not b.prerelease:
        return -1
    for pa, pb in zip(a.prerelease, b.prerelease):
        ka, kb = _pre_key(pa), _pre_key(pb)
        if ka != kb:
            return -1 if ka < kb else 1
    if len(a.prerelease) != len(b.prerelease):
        return -1 if len(a.prerelease) < len(b.prerelease) else 1
    return 0


@dataclass(frozen=True)
class _Comparator:
    op: str  # '=', '>', '>=', '<', '<='
    version: SemVer


def _expand_token(token: str) -> list[_Comparator]:
    """把范围里的一个记号（如 "^4.0.1"）展开成一个或两个比较符。"""
    token = token.strip()
    if not token:
        return []
    if token.startswith("^"):
        v = parse_version(token[1:])
        if v is None:
            return []
        if v.major > 0:
            upper = SemVer(v.major + 1, 0, 0)
        elif v.minor > 0:
            upper = SemVer(0, v.minor + 1, 0)
        else:
            upper = SemVer(0, 0, v.patch + 1)
        return [_Comparator(">=", v), _Comparator("<", upper)]
    if token.startswith("~"):
        v = parse_version(token[1:])
        if v is None:
            return []
        upper = SemVer(v.major, v.minor + 1, 0)
        return [_Comparator(">=", v), _Comparator("<", upper)]
    for op in (">=", "<=", ">", "<", "="):
        if token.startswith(op):
            v = parse_version(token[len(op):])
            if v is None:
                return []
            return [_Comparator(op, v)]
    v = parse_version(token)
    if v is None:
        return []
    return [_Comparator("=", v)]


def _parse_comparator_set(text: str) -> list[_Comparator]:
    """把一个 AND 段（如 ">=0.1.7-rc.1 <0.2.0"）拆成比较符列表。"""
    comparators: list[_Comparator] = []
    for token in text.strip().split():
        comparators.extend(_expand_token(token))
    return comparators


def _comparator_matches(c: _Comparator, candidate: SemVer) -> bool:
    cmp = compare(candidate, c.version)
    if c.op == "=":
        return cmp == 0
    if c.op == ">":
        return cmp > 0
    if c.op == ">=":
        return cmp >= 0
    if c.op == "<":
        return cmp < 0
    if c.op == "<=":
        return cmp <= 0
    return False


def _set_satisfies(comparators: list[_Comparator], candidate: SemVer) -> bool:
    if not comparators:
        return False
    if candidate.prerelease:
        gate = any(
            c.version.core() == candidate.core() and c.version.prerelease
            for c in comparators
        )
        if not gate:
            return False
    return all(_comparator_matches(c, candidate) for c in comparators)


def satisfies(version: str, range_spec: str) -> bool | None:
    """判断 version 是否落在 range_spec 声明的范围内。

    range_spec 用本模块未覆盖的写法（如 git 依赖、workspace: 等非 semver
    范围）时返回 None；调用方应把 None 展示为“无法判断”，不能当作
    “不兼容”或“兼容”呈现，否则等于编造判断结果。
    """
    candidate = parse_version(version)
    if candidate is None:
        return None
    parsed_any = False
    for branch in range_spec.split("||"):
        comparators = _parse_comparator_set(branch)
        if not comparators:
            continue
        parsed_any = True
        if _set_satisfies(comparators, candidate):
            return True
    return False if parsed_any else None


# ---- 兼容性报告 ----


@dataclass(frozen=True)
class DepFinding:
    """插件对某一个 peer 依赖的声明，与本地实际版本的核对结果。"""

    dep_name: str
    required_range: str
    actual_version: str | None
    optional: bool
    status: str  # "match" | "mismatch" | "unknown" | "not_found"


@dataclass(frozen=True)
class PluginCompat:
    """单个插件的兼容性核对结果。"""

    name: str
    version: str
    enabled: bool  # 是否在 dsh.profile.bundles 里（未启用的插件不影响当前运行）
    findings: list[DepFinding]


@dataclass(frozen=True)
class CompatReport:
    harness_version: str
    plugins: list[PluginCompat]


def _read_json(path: Path) -> dict:
    """读取并解析一个 JSON 文件；缺失、损坏或非对象一律返回空 dict。"""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def harness_package_versions(root: Path) -> dict[str, str]:
    """扫描项目 packages/** 与 vendor/** 下的 package.json，建立包名 -> 版本号映射。

    只读取每个文件的 name/version 两个字段。跳过 node_modules 子树，
    避免把某个包依赖里内嵌的同名包版本误当作 harness 自身版本。
    """
    versions: dict[str, str] = {}
    for base_name in ("packages", "vendor"):
        base = root / base_name
        if not base.is_dir():
            continue
        for pkg_json in base.rglob("package.json"):
            if "node_modules" in pkg_json.parts:
                continue
            data = _read_json(pkg_json)
            name = data.get("name")
            version = data.get("version")
            if isinstance(name, str) and isinstance(version, str):
                versions[name] = version
    return versions


def _root_version(root: Path) -> str:
    version = _read_json(root / "package.json").get("version")
    return str(version) if isinstance(version, str) else "?"


def check_compatibility(root: Path, profile: Path) -> CompatReport:
    """核对 profile 已装第三方插件（含未启用的）与当前 harness 版本的
    peerDependencies 声明。

    只读文件系统，不联网、不跑子进程、不实际加载插件；结果是静态版本范围
    推导，不代表运行时实测。
    """
    harness_versions = harness_package_versions(root)
    manifest = pm.profile_manifest(profile)
    deps: dict = manifest.get("dependencies") or {}
    bundles: list = ((manifest.get("dsh") or {}).get("profile") or {}).get("bundles") or []
    node_modules = profile / "node_modules"

    plugins: list[PluginCompat] = []
    for name in deps:
        pkg_dir = node_modules / name
        pkg_json = _read_json(pkg_dir / "package.json")
        version = str(pkg_json.get("version") or deps[name])
        peer_deps: dict = pkg_json.get("peerDependencies") or {}
        peer_meta: dict = pkg_json.get("peerDependenciesMeta") or {}
        findings: list[DepFinding] = []
        for dep_name, required_range in peer_deps.items():
            optional = bool((peer_meta.get(dep_name) or {}).get("optional"))
            actual = harness_versions.get(dep_name)
            if actual is None:
                findings.append(DepFinding(dep_name, str(required_range), None, optional, "not_found"))
                continue
            result = satisfies(actual, str(required_range))
            if result is None:
                status = "unknown"
            elif result:
                status = "match"
            else:
                status = "mismatch"
            findings.append(DepFinding(dep_name, str(required_range), actual, optional, status))
        plugins.append(PluginCompat(name=name, version=version, enabled=name in bundles, findings=findings))

    plugins.sort(key=lambda p: (not p.enabled, p.name))
    return CompatReport(harness_version=_root_version(root), plugins=plugins)


def _plugin_counts(plugin: PluginCompat) -> tuple[int, int, int]:
    """统计一个插件的 (不兼容项数, 可选降级项数, 无法判断项数)。"""
    hard = degraded = unknown = 0
    for f in plugin.findings:
        if f.status == "match":
            continue
        if f.status in ("not_found", "mismatch"):
            if f.optional:
                degraded += 1
            else:
                hard += 1
        elif f.status == "unknown":
            unknown += 1
    return hard, degraded, unknown


def plugin_verdict(plugin: PluginCompat) -> str:
    """插件级结论：不兼容 > 降级 > 存疑 > 兼容，取最严重的一档。

    公开函数：插件列表 UI 复用同一判定口径展示 [不兼容] 标记，
    与日志里的汇总表必须给出一致的结论，不能各算一套。
    """
    if not plugin.findings:
        return "无声明"
    hard, degraded, unknown = _plugin_counts(plugin)
    if hard > 0:
        return "不兼容"
    if degraded > 0:
        return "降级"
    if unknown > 0:
        return "存疑"
    return "兼容"


def _summary_table(report: CompatReport) -> list[str]:
    """按插件汇总的简表：一行一个插件，结论 + 启用状态 + 问题项数。"""
    rows = [("插件", "版本", "结论", "状态", "问题项")]
    for plugin in report.plugins:
        hard, degraded, unknown = _plugin_counts(plugin)
        problems = f"{hard}不兼容/{degraded}降级/{unknown}存疑" if (hard or degraded or unknown) else "-"
        rows.append((
            plugin.name,
            plugin.version,
            plugin_verdict(plugin),
            "已启用" if plugin.enabled else "未启用",
            problems,
        ))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = []
    for row_index, row in enumerate(rows):
        line = "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
        lines.append(line)
        if row_index == 0:
            lines.append("  ".join("-" * widths[i] for i in range(len(row))))
    return lines


def format_report(report: CompatReport) -> str:
    """把兼容性报告格式化成适合直接打进日志窗的多行文本：逐项详细分析 + 结尾汇总表。"""
    lines = [f"当前 harness 版本: {report.harness_version}"]
    if not report.plugins:
        lines.append("未发现任何第三方插件。")
        return "\n".join(lines)

    for plugin in report.plugins:
        tag = "" if plugin.enabled else "（已装但未启用，不在 bundles 列表）"
        lines.append(f"\n[{plugin.name}] {plugin.version}{tag}")
        if not plugin.findings:
            lines.append("  无 peerDependencies 声明，无法判断。")
            continue
        problems = 0
        for f in plugin.findings:
            if f.status == "match":
                continue
            problems += 1
            if f.status == "not_found":
                marker = "可选" if f.optional else "必需"
                lines.append(f"  ⚠ {f.dep_name} 要求 {f.required_range}，本地未找到该包（{marker}）")
            elif f.status == "mismatch":
                marker = "可选，降级" if f.optional else "不兼容"
                lines.append(
                    f"  {'△' if f.optional else '✗'} {f.dep_name} 要求 {f.required_range}，"
                    f"当前版本 {f.actual_version}（{marker}）"
                )
            elif f.status == "unknown":
                lines.append(f"  ? {f.dep_name} 要求 {f.required_range}（范围写法未覆盖，无法判断）")
        if problems == 0:
            lines.append("  全部匹配。")

    hard_total = sum(_plugin_counts(p)[0] for p in report.plugins)
    degraded_total = sum(_plugin_counts(p)[1] for p in report.plugins)
    unknown_total = sum(_plugin_counts(p)[2] for p in report.plugins)

    lines.append("\n===== 汇总 =====")
    lines.extend(_summary_table(report))
    lines.append(f"\n合计：不兼容 {hard_total} 项，可选降级 {degraded_total} 项，无法判断 {unknown_total} 项。")
    lines.append(
        "（只读静态核对：比对已装插件声明的 peerDependencies 版本范围与本地 "
        "packages/vendor 下的实际版本，不联网、不实际加载插件，不代表运行时实测结果。）"
    )
    return "\n".join(lines)
