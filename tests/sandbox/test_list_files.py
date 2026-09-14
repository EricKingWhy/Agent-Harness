"""Sandbox.list_files 契约测试：LocalSubprocessSandbox 后端的文件枚举行为。

测试缝 1（见 spec）：直接调 Sandbox 方法，断言返回值形状。
DockerSandbox 的 list_files 集成测试在 test_docker_sandbox.py（@integration + skipif）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_harness.sandbox import LocalSubprocessSandbox


@pytest.fixture
def sandbox(tmp_path: Path) -> LocalSubprocessSandbox:
    return LocalSubprocessSandbox(workspace_root=tmp_path)


class TestListFilesBasic:
    def test_empty_workspace_returns_empty_list(self, sandbox: LocalSubprocessSandbox):
        """workspace 无文件 → 空列表。"""
        assert sandbox.list_files("*") == []

    def test_star_returns_all_files(self, sandbox: LocalSubprocessSandbox):
        """pattern="*" 返回 workspace 内所有文件。"""
        sandbox.write_text("a.py", "x")
        sandbox.write_text("b.txt", "y")
        sandbox.write_text("sub/c.py", "z")

        result = sandbox.list_files("*")

        # 顶层文件被列出；子目录里的文件也被列出（* 匹配单段也匹配 dir/file）
        assert "a.py" in result
        assert "b.txt" in result
        assert "sub/c.py" in result

    def test_empty_pattern_equivalent_to_star(self, sandbox: LocalSubprocessSandbox):
        """pattern="" 等价于 "*"——返回所有文件。"""
        sandbox.write_text("a.py", "x")
        sandbox.write_text("b.txt", "y")

        assert sorted(sandbox.list_files("")) == sorted(sandbox.list_files("*"))


class TestListFilesGlob:
    def test_extension_filter(self, sandbox: LocalSubprocessSandbox):
        """*.py 只返回 .py 文件。"""
        sandbox.write_text("a.py", "x")
        sandbox.write_text("b.txt", "y")
        sandbox.write_text("c.py", "z")

        result = sandbox.list_files("*.py")

        assert "a.py" in result
        assert "c.py" in result
        assert all(not p.endswith(".txt") for p in result)

    def test_double_star_recursive(self, sandbox: LocalSubprocessSandbox):
        """**/*.py 匹配嵌套子目录里的 .py 文件。"""
        sandbox.write_text("top.py", "x")
        sandbox.write_text("pkg/mod.py", "y")
        sandbox.write_text("pkg/sub/deep.py", "z")
        sandbox.write_text("pkg/sub/notes.txt", "w")

        result = sandbox.list_files("**/*.py")

        assert "top.py" in result
        assert "pkg/mod.py" in result
        assert "pkg/sub/deep.py" in result
        assert all(not p.endswith(".txt") for p in result)

    def test_prefix_glob(self, sandbox: LocalSubprocessSandbox):
        """test_*.py 匹配 test_ 开头的 .py 文件。"""
        sandbox.write_text("test_foo.py", "x")
        sandbox.write_text("test_bar.py", "y")
        sandbox.write_text("main.py", "z")

        result = sandbox.list_files("test_*.py")

        assert sorted(result) == ["test_bar.py", "test_foo.py"]


class TestListFilesProperties:
    def test_only_files_not_directories(self, sandbox: LocalSubprocessSandbox):
        """只返回文件，不返回目录本身。"""
        sandbox.write_text("pkg/mod.py", "x")

        result = sandbox.list_files("*")

        # "pkg" 是目录，不应出现在结果里
        assert "pkg" not in result
        assert "pkg/mod.py" in result

    def test_results_are_sorted(self, sandbox: LocalSubprocessSandbox):
        """结果按路径排序。"""
        sandbox.write_text("zeta.py", "x")
        sandbox.write_text("alpha.py", "y")
        sandbox.write_text("mid.py", "z")

        result = sandbox.list_files("*.py")

        assert result == ["alpha.py", "mid.py", "zeta.py"]

    def test_paths_are_posix_style(self, sandbox: LocalSubprocessSandbox):
        """路径用正斜杠（POSIX 风格），即使在 Windows 上。"""
        sandbox.write_text("sub/dir/file.py", "x")

        result = sandbox.list_files("**/*.py")

        assert result == ["sub/dir/file.py"]
        assert all("\\" not in p for p in result)
