"""SKILL.md 发现与解析（spec 09 §2，Pi PORT DESIGN，ADR-0011 Q1/Q2/Q4）。

渐进披露的物理前提：发现阶段只读 frontmatter（name + description），
正文通过 load_body() 按需读取。解析失败显式进 errors 列表，不静默跳过。

路径边界：目录扫描发现的 SKILL.md 经 resolve 后必须仍落在被扫描目录内
（防 symlink 指向目录外）；手动指定的路径是用户显式声明，本身即授权。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

#: 发现阶段单文件读取上限（stat 尺寸拦截，先于任何 read；单位是字节）。
#: SKILL.md 是被扫描目录里的自由文件（模型 workspace-write 可写），无上限时
#: 超大文件会在 wiring 期打爆内存——tool 层的 64K 正文截断发生在完整读盘之后，
#: 拦不住读入阶段。
SKILL_FILE_MAX_BYTES = 1_000_000


@dataclass(frozen=True, slots=True)
class SkillCatalogEntry:
    """目录条目：name + description(+when_to_use) + 来源路径 + frontmatter 其余字段；正文延迟读取。"""

    name: str
    description: str
    source_path: Path
    meta: dict[str, Any] = field(default_factory=dict)
    when_to_use: str = ""  # 可选（ADR-0011 grill 记录：用户批准的扩展字段）
    # 目录扫描来源的包含根（手动路径为 None：用户显式声明本身即授权）。
    # load_body 读盘时用它重验证边界——发现时的一次性校验是 TOCTOU：
    # 模型可通过 workspace-write 工具在 wiring 之后把 skill 目录换成
    # 指向目录外的 junction/symlink，把任意宿主文件读进 Context。
    scanned_root: Path | None = None

    def load_body(self) -> str:
        """按需读取 SKILL.md 正文（frontmatter 之后的部分）——每次读盘，不缓存。"""
        if self.scanned_root is not None and not resolve_within(self.source_path, self.scanned_root):
            raise OSError(
                f"{self.source_path}: resolves outside scanned skill directory "
                f"{self.scanned_root} (boundary changed after discovery, refusing to read)"
            )
        # 尺寸上限在 load 侧同样生效：发现后文件可被 workspace-write 换成超大内容，
        # "读入阶段有界"必须覆盖模型触发的加载路径（与发现同一威胁模型）。
        if self.source_path.stat().st_size > SKILL_FILE_MAX_BYTES:
            raise OSError(f"{self.source_path}: too large (> {SKILL_FILE_MAX_BYTES} bytes)")
        # utf-8-sig：Windows 记事本等默认写 BOM，残留 \ufeff 会让首行 '---' 校验失败。
        # 非 UTF-8 字节抛 UnicodeDecodeError（ValueError 子类）——让调用方明确看到
        # 读盘失败，而不是吞回空字符串（吞空会让 load_skill 工具返回空内容）。
        text = self.source_path.read_text(encoding="utf-8-sig")
        return _split_frontmatter(text)[1].strip()


@dataclass
class SkillCatalog:
    """发现结果：条目 + 显式错误 + 冲突标注（不静默）。"""

    entries: list[SkillCatalogEntry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """切 `---` 围栏 frontmatter；返回 (frontmatter_text | None, body)。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1:])
    return None, text


def parse_skill_markdown(path: Path) -> tuple[SkillCatalogEntry | None, list[str]]:
    """解析单个 SKILL.md；失败返回 (None, errors)，绝不抛出中断发现流程。"""
    errors: list[str] = []
    try:
        # 尺寸上限先于 read（stat 一次 vs 全量读入）：读入阶段就有界。
        if path.stat().st_size > SKILL_FILE_MAX_BYTES:
            return None, [f"{path}: too large (> {SKILL_FILE_MAX_BYTES} bytes)"]
        # utf-8-sig：兼容 BOM 前缀（Windows 记事本默认），无 BOM 时行为与 utf-8 一致。
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        # UnicodeDecodeError 是 ValueError 子类，不是 OSError——非 UTF-8（GBK/Latin-1
        # 等）字节会从这里抛；捕获它才不违背"解析失败进 errors，绝不中断扫描"的契约。
        return None, [f"{path}: unreadable ({type(error).__name__})"]
    frontmatter, _body = _split_frontmatter(text)
    if frontmatter is None:
        return None, [f"{path}: missing '---' frontmatter fence"]
    try:
        meta = yaml.safe_load(frontmatter)
    except yaml.YAMLError as error:
        return None, [f"{path}: invalid YAML frontmatter ({type(error).__name__})"]
    if not isinstance(meta, dict):
        return None, [f"{path}: frontmatter must be a mapping"]
    meta = dict(meta)
    name = meta.pop("name", None)
    description = meta.pop("description", None)
    when_to_use = meta.pop("when_to_use", None)
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{path}: frontmatter requires non-empty 'name'")
    if not isinstance(description, str) or not description.strip():
        errors.append(f"{path}: frontmatter requires non-empty 'description'")
    if errors:
        return None, errors
    when_to_use = when_to_use.strip() if isinstance(when_to_use, str) and when_to_use.strip() else ""
    return SkillCatalogEntry(name=name.strip(), description=description.strip(),
                             source_path=path, meta=meta, when_to_use=when_to_use), []


def resolve_within(candidate: Path, root: Path) -> bool:
    """resolve 后必须仍在 root 内（含相等）——目录扫描的 symlink 逃逸防线。"""
    resolved = candidate.resolve()
    root = root.resolve()
    return resolved == root or root in resolved.parents


class SkillDiscovery:
    """扫描 skill 目录（只一层 `skills/<name>/SKILL.md`）+ 手动指定路径。"""

    def __init__(self, directories: list[Path], manual_paths: list[Path] | None = None) -> None:
        self._directories = [Path(d) for d in directories]
        self._manual_paths = [Path(p) for p in (manual_paths or [])]

    def discover(self) -> SkillCatalog:
        catalog = SkillCatalog()
        seen: dict[str, Path] = {}

        def _consider(path: Path, origin: str, root: Path | None) -> None:
            entry, errors = parse_skill_markdown(path)
            catalog.errors.extend(f"[{origin}] {e}" for e in errors)
            if entry is None:
                return
            if root is not None and not resolve_within(path, root):
                catalog.errors.append(
                    f"[{origin}] {path}: resolves outside scanned skill directory {root}"
                )
                return
            if root is not None:
                # 携带包含根，供 load_body 读盘时重验证（TOCTOU 防线）。
                entry = replace(entry, scanned_root=root)
            if entry.name in seen:
                # 同名先到先得，冲突显式可见（spec 08 §5 精神：不允许静默忽略）。
                catalog.conflicts.append(
                    f"skill '{entry.name}' from {path} shadowed by {seen[entry.name]}"
                )
                return
            seen[entry.name] = path
            catalog.entries.append(entry)

        for directory in self._directories:
            if not directory.exists():
                continue  # 目录不存在 → 空 catalog，不是错误（OPTIONAL 语义）
            if not directory.is_dir():
                catalog.errors.append(f"[directory] {directory}: not a directory")
                continue
            try:
                skill_dirs = sorted(directory.iterdir())
            except OSError as error:
                # 目录级 IO 错误（权限/死挂载）只损失该目录：与逐条解析失败同一
                # 容错契约，绝不中断整个扫描（否则一个坏目录让所有技能消失）。
                catalog.errors.append(f"[directory] {directory}: unreadable ({error})")
                continue
            for skill_dir in skill_dirs:
                skill_file = skill_dir / "SKILL.md"
                if skill_dir.is_dir() and skill_file.is_file():
                    _consider(skill_file, "directory", directory)

        for manual in self._manual_paths:
            if manual.is_file():
                _consider(manual, "manual", None)
            else:
                catalog.errors.append(f"[manual] {manual}: not a file")
        return catalog
