"""T3：SKILL.md 解析 + SkillDiscovery（spec 09 §2，ADR-0011 Q1/Q2/Q4）。"""

from __future__ import annotations

from pathlib import Path

from agent_harness.skills.discovery import (
    SKILL_FILE_MAX_BYTES,
    SkillDiscovery,
    parse_skill_markdown,
)


def _write_skill(root: Path, name: str, frontmatter: str, body: str = "正文内容") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")
    return skill_file


VALID_FM = 'name: pdf-export\ndescription: "导出 PDF 报告"'


def _fm(name: str, description: str = "示例技能") -> str:
    return f'name: {name}\ndescription: "{description}"'


class TestParseSkillMarkdown:
    def test_valid_frontmatter_and_body(self, tmp_path):
        path = _write_skill(tmp_path, "pdf-export", VALID_FM, "步骤一：选择文件")
        entry, errors = parse_skill_markdown(path)
        assert errors == []
        assert entry.name == "pdf-export"
        assert entry.description == "导出 PDF 报告"
        assert entry.source_path == path
        # 渐进披露的物理前提：发现阶段不读正文——body 延迟加载。
        assert entry.load_body() == "步骤一：选择文件"

    def test_missing_name_or_description_is_error_not_crash(self, tmp_path):
        (tmp_path / "broken").mkdir()
        (tmp_path / "broken" / "SKILL.md").write_text("---\nname: broken\n---\nbody", encoding="utf-8")
        entry, errors = parse_skill_markdown(tmp_path / "broken" / "SKILL.md")
        assert entry is None
        assert errors and "description" in errors[0]

    def test_no_frontmatter_is_error(self, tmp_path):
        (tmp_path / "plain").mkdir()
        (tmp_path / "plain" / "SKILL.md").write_text("无 frontmatter 内容", encoding="utf-8")
        entry, errors = parse_skill_markdown(tmp_path / "plain" / "SKILL.md")
        assert entry is None and errors

    def test_unknown_frontmatter_fields_preserved(self, tmp_path):
        path = _write_skill(tmp_path, "x", VALID_FM + "\nversion: 2")
        entry, errors = parse_skill_markdown(path)
        assert errors == []
        assert entry.meta.get("version") == 2

    def test_body_lazily_read_each_call(self, tmp_path):
        path = _write_skill(tmp_path, "lazy", VALID_FM, "v1")
        entry, _ = parse_skill_markdown(path)
        path.write_text(path.read_text(encoding="utf-8").replace("v1", "v2"), encoding="utf-8")
        assert entry.load_body() == "v2"

    def test_utf8_bom_is_stripped(self, tmp_path):
        """Windows 记事本默认写 BOM：按 utf-8 读会残留 \\ufeff，首行 '---' 校验失败 → 技能全灭。"""
        skill_dir = tmp_path / "bom"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_bytes(
            b"\xef\xbb\xbf" + "---\nname: bom-skill\ndescription: 带 BOM\n---\n\nBOM 正文\n".encode(),
        )
        entry, errors = parse_skill_markdown(skill_file)
        assert errors == []
        assert entry.name == "bom-skill"
        assert entry.description == "带 BOM"
        assert entry.load_body() == "BOM 正文"

    def test_crlf_line_endings_frontmatter_ok(self, tmp_path):
        """CRLF（Windows 换行）：splitlines 已能处理——pin 该行为防回归。"""
        skill_dir = tmp_path / "crlf"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_bytes(
            "---\r\nname: crlf-skill\r\ndescription: CRLF 换行\r\n---\r\n\r\nCRLF 正文\r\n".encode(),
        )
        entry, errors = parse_skill_markdown(skill_file)
        assert errors == []
        assert entry.name == "crlf-skill"
        assert entry.load_body() == "CRLF 正文"


class TestSkillDiscovery:
    def test_scans_global_then_project_single_level(self, tmp_path):
        global_dir, project_dir = tmp_path / "global", tmp_path / "project"
        _write_skill(global_dir, "alpha", _fm("alpha", "A"))
        _write_skill(project_dir, "beta", _fm("beta", "B"))
        discovery = SkillDiscovery(directories=[global_dir, project_dir])
        catalog = discovery.discover()
        assert [e.name for e in catalog.entries] == ["alpha", "beta"]
        assert catalog.errors == []

    def test_duplicate_name_first_wins_and_conflict_visible(self, tmp_path):
        first, second = tmp_path / "a", tmp_path / "b"
        _write_skill(first, "dup", _fm("dup", "first"))
        _write_skill(second, "dup", _fm("dup", "second"))
        discovery = SkillDiscovery(directories=[first, second])
        catalog = discovery.discover()
        assert [e.description for e in catalog.entries] == ["first"]
        assert any("dup" in c for c in catalog.conflicts)

    def test_missing_directory_is_empty_catalog_not_error(self, tmp_path):
        catalog = SkillDiscovery(directories=[tmp_path / "ghost"]).discover()
        assert catalog.entries == [] and catalog.errors == []

    def test_manual_paths_are_included(self, tmp_path):
        skill = _write_skill(tmp_path / "anywhere", "manual", _fm("manual", "手动指定"))
        catalog = SkillDiscovery(directories=[], manual_paths=[skill]).discover()
        assert [e.name for e in catalog.entries] == ["manual"]

    def test_manual_missing_file_is_error(self, tmp_path):
        catalog = SkillDiscovery(directories=[], manual_paths=[tmp_path / "ghost.md"]).discover()
        assert catalog.entries == [] and catalog.errors

    def test_resolve_within_rejects_escape(self, tmp_path):
        """symlink/相对路径逃逸防线的纯函数测试（跨平台不依赖 symlink 权限）。"""
        from agent_harness.skills.discovery import resolve_within

        root = tmp_path / "root"
        root.mkdir()
        assert resolve_within(root / "a" / "SKILL.md", root) is True
        assert resolve_within(root, root) is True
        assert resolve_within(tmp_path / "outside" / "SKILL.md", root) is False
        assert resolve_within(root.parent / "SKILL.md", root) is False

    def test_nested_directories_ignored(self, tmp_path):
        deep = tmp_path / "skills" / "nested" / "deeper"
        deep.mkdir(parents=True)
        (deep / "SKILL.md").write_text("---\nname: deep\ndescription: x\n---\n", encoding="utf-8")
        catalog = SkillDiscovery(directories=[tmp_path / "skills"]).discover()
        assert catalog.entries == []


# ── 非 UTF-8 编码的 SKILL.md 不应中断整个扫描流程 ──


def test_non_utf8_skill_file_is_error_not_crash(tmp_path):
    """GBK/Latin-1 编码的 SKILL.md 必须进 errors 列表，不抛 UnicodeDecodeError。

    read_text(encoding="utf-8-sig") 遇到非 UTF-8 字节抛 UnicodeDecodeError
    （ValueError 子类，不是 OSError）；原有 except OSError 兜不住——整个
    discover() 会向上抛，扫描中断。这是模块 docstring 明确承诺的反契约：
    "解析失败进 errors 列表，绝不抛出中断发现流程"。
    """
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    # 写一个合法 UTF-8 的兄弟技能（验证扫描继续推进）
    good_dir = skills_dir / "good"
    good_dir.mkdir()
    good_dir.joinpath("SKILL.md").write_text(
        f"---\n{_fm('good', '好技能')}\n---\n正文\n", encoding="utf-8"
    )
    # 写一个 GBK 编码的坏技能（中文用 GBK 编码）
    bad_dir = skills_dir / "bad"
    bad_dir.mkdir()
    (bad_dir / "SKILL.md").write_bytes(
        ("---\nname: bad\ndescription: 坏技能\n---\n正文\n").encode("gbk")
    )

    catalog = SkillDiscovery(directories=[skills_dir]).discover()

    # 扫描不抛、坏文件进 errors、好文件照常被发现。
    assert [e.name for e in catalog.entries] == ["good"]
    assert any("bad" in err or "unreadable" in err for err in catalog.errors)


def test_parse_skill_markdown_non_utf8_returns_error_not_raises(tmp_path):
    """parse_skill_markdown 单文件级也对非 UTF-8 容错。"""
    path = tmp_path / "gbk.md"
    path.write_bytes(("---\nname: x\ndescription: 中文\n---\n").encode("gbk"))
    entry, errors = parse_skill_markdown(path)
    assert entry is None
    assert errors and "unreadable" in errors[0]


# ── Round 7 加固：发现读取有界性 + 目录级 IO 容错 ──


def test_oversized_skill_file_rejected_with_catalog_error(tmp_path):
    """超大 SKILL.md 不整读进内存：发现阶段 stat 上限拦截，进 errors 可观察。

    SKILL.md 是被扫描目录里的自由文件（模型 workspace-write 可写），无上限时
    一个多 MB 文件就能在 wiring 期把进程内存打爆；64K 正文截断发生在完整读盘
    之后，拦不住读入阶段。
    """
    skills_dir = tmp_path / "skills"
    big = skills_dir / "big"
    big.mkdir(parents=True)
    (big / "SKILL.md").write_text("x" * (SKILL_FILE_MAX_BYTES + 1), encoding="utf-8")
    ok = skills_dir / "ok"
    ok.mkdir()
    (ok / "SKILL.md").write_text("---\nname: ok\ndescription: d\n---\nbody",
                                 encoding="utf-8")

    catalog = SkillDiscovery([skills_dir]).discover()
    assert [e.name for e in catalog.entries] == ["ok"]  # 其它技能不受影响
    assert any("too large" in e for e in catalog.errors)


def test_unreadable_directory_degrades_to_error_not_abort(tmp_path):
    """目录级 IO 错误（权限/死挂载）只损失该目录，不中断整个发现流程。

    此前 iterdir() 的 OSError 直接抛出、被 wire_capabilities 当整体失败降级
    ——一个坏目录让全局+项目+手动路径的全部技能消失，违背"解析失败进
    errors，绝不中断扫描"的逐条容错契约。
    """
    from unittest import mock

    # 两个被扫描目录：bad_dir 的 iterdir 抛 OSError（权限/死挂载），good_dir 正常。
    bad_dir = tmp_path / "bad_dir"
    bad_dir.mkdir()
    good_dir = tmp_path / "good_dir"
    good_dir.mkdir()
    good = good_dir / "good"
    good.mkdir()
    (good / "SKILL.md").write_text("---\nname: good\ndescription: d\n---\nbody",
                                   encoding="utf-8")

    discovery = SkillDiscovery([bad_dir, good_dir])
    real_iterdir = Path.iterdir

    def selective_iterdir(self):
        if self == bad_dir:
            raise PermissionError(13, "Permission denied")
        return real_iterdir(self)

    with mock.patch.object(Path, "iterdir", selective_iterdir):
        catalog = discovery.discover()

    assert [e.name for e in catalog.entries] == ["good"]
    assert any("bad_dir" in e for e in catalog.errors)
