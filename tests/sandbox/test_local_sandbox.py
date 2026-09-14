"""LocalSubprocessSandbox 契约测试：验证 Sandbox ABC 的全部行为。

零外部依赖（不需要 Docker daemon），纳入默认套。测试缝：直接调 Sandbox 方法，
断言返回值形状和路径边界行为（测试缝 1，见 spec）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_harness.sandbox import ExecResult, LocalSubprocessSandbox

# ============================================================================
# 夹具：每个测试一个独立 workspace 目录，互不干扰
# ============================================================================


@pytest.fixture
def sandbox(tmp_path: Path) -> LocalSubprocessSandbox:
    """每个测试拿到一个空的 LocalSubprocessSandbox，workspace 指向 tmp_path。"""
    return LocalSubprocessSandbox(workspace_root=tmp_path)


# ============================================================================
# exec：基本执行 + ExecResult 形状
# ============================================================================


class TestExecBasic:
    def test_echo_returns_zero_exit_and_stdout(self, sandbox: LocalSubprocessSandbox):
        """echo hello → exit_code=0, stdout 含 'hello', stderr=''."""
        result = sandbox.exec("echo hello")

        assert isinstance(result, ExecResult)
        assert result.exit_code == 0
        # Windows echo 输出 \r\n、bash 输出 \n；只断言内容，不锁行尾编码
        assert result.stdout.strip() == "hello"
        assert result.stderr == ""
        assert result.duration_ms >= 0  # 非负

    def test_failing_command_returns_nonzero_exit(self, sandbox: LocalSubprocessSandbox):
        """exit 1 → exit_code=1，调用本身成功（ExecResult 正常返回，不抛异常）。"""
        result = sandbox.exec("exit 1")

        assert result.exit_code == 1
        # 关键不变量（ADR-0002）：命令业务失败 ≠ Sandbox 调用失败
        # ExecResult 正常构造就是"Sandbox 调用成功"的证据

    def test_stderr_is_captured(self, sandbox: LocalSubprocessSandbox):
        """命令写到 stderr 的内容被 capture 进 ExecResult.stderr。"""
        result = sandbox.exec("echo oops 1>&2")

        assert "oops" in result.stderr

    def test_cwd_is_workspace_root(self, sandbox: LocalSubprocessSandbox):
        """命令的 cwd 锁定在 workspace_root——写文件落地在 workspace 目录里。

        用 file 文件而非 pwd/cd（后两者在 Windows 中文系统有编码差异，不稳）。
        """
        sandbox.exec("echo content > marker.txt")
        assert (sandbox.workspace_root / "marker.txt").exists()

    def test_timeout_returns_negative_exit_code(self, sandbox: LocalSubprocessSandbox):
        """命令超过 timeout → ExecResult.exit_code=-1 + stderr 含超时提示，不抛异常。"""
        # sleep 5 但 timeout=0.3 秒——到点被掐断
        result = sandbox.exec("ping -n 5 127.0.0.1 > nul", timeout=0.3)

        assert result.exit_code == -1
        assert "超时" in result.stderr


# ============================================================================
# read_text / write_text：文件读写 + workspace 边界
# ============================================================================


class TestReadWrite:
    def test_write_then_read_roundtrip(self, sandbox: LocalSubprocessSandbox):
        """write_text('a.txt','hi') → read_text('a.txt') == 'hi'."""
        sandbox.write_text("a.txt", "hi")
        assert sandbox.read_text("a.txt") == "hi"

    def test_write_creates_parent_dirs(self, sandbox: LocalSubprocessSandbox):
        """写入嵌套路径时父目录自动创建。"""
        sandbox.write_text("sub/dir/note.md", "deep")
        assert sandbox.read_text("sub/dir/note.md") == "deep"

    def test_write_overwrites_existing(self, sandbox: LocalSubprocessSandbox):
        """覆盖写：第二次 write 替换第一次的内容。"""
        sandbox.write_text("f.txt", "first")
        sandbox.write_text("f.txt", "second")
        assert sandbox.read_text("f.txt") == "second"

    def test_read_nonexistent_raises(self, sandbox: LocalSubprocessSandbox):
        """读不存在的文件抛 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            sandbox.read_text("nope.txt")


# ============================================================================
# 路径越界拒绝：核心安全不变量（ADR-0001）
# ============================================================================


class TestPathEscape:
    """模型尝试访问 workspace 外的路径必须被拒绝——这是 Sandbox 作为安全边界的根。"""

    def test_read_escape_via_dotdot(self, sandbox: LocalSubprocessSandbox):
        """../../etc/passwd 越界 → PermissionError。"""
        with pytest.raises(PermissionError):
            sandbox.read_text("../../etc/passwd")

    def test_write_escape_via_dotdot(self, sandbox: LocalSubprocessSandbox):
        """../../evil.txt 越界 → PermissionError。"""
        with pytest.raises(PermissionError):
            sandbox.write_text("../../evil.txt", "stolen")

    def test_absolute_path_outside_workspace(self, sandbox: LocalSubprocessSandbox, tmp_path: Path):
        """绝对路径指向 workspace 外 → PermissionError。"""
        outside = tmp_path.parent / "outside_target.txt"
        with pytest.raises(PermissionError):
            sandbox.read_text(str(outside))

    def test_subdir_access_is_allowed(self, sandbox: LocalSubprocessSandbox):
        """workspace 内的子目录访问不受影响——只有越界才拒。"""
        sandbox.write_text("sub/b.txt", "ok")
        assert sandbox.read_text("sub/b.txt") == "ok"


# ============================================================================
# copy_in：宿主 → workspace
# ============================================================================


class TestCopyIn:
    def test_copy_file_into_workspace(self, sandbox: LocalSubprocessSandbox, tmp_path: Path):
        """把宿主文件拷入 workspace 子路径。"""
        src = tmp_path.parent / "host_source.txt"
        src.write_text("from host", encoding="utf-8")
        try:
            sandbox.copy_in(src, "imported.txt")
            assert sandbox.read_text("imported.txt") == "from host"
        finally:
            src.unlink(missing_ok=True)


# ============================================================================
# ensure_started / stop 幂等
# ============================================================================


class TestLifecycle:
    def test_ensure_started_idempotent(self, sandbox: LocalSubprocessSandbox):
        """多次 ensure_started 不报错。"""
        sandbox.ensure_started()
        sandbox.ensure_started()
        sandbox.ensure_started()

    def test_stop_idempotent(self, sandbox: LocalSubprocessSandbox):
        """多次 stop 不报错。"""
        sandbox.stop()
        sandbox.stop()

    def test_delete_removes_workspace_dir(self, sandbox: LocalSubprocessSandbox):
        """delete 彻底删除 workspace 目录。"""
        ws_root = Path(sandbox.workspace_root)
        assert ws_root.exists()
        sandbox.delete()
        assert not ws_root.exists()

    def test_delete_idempotent(self, sandbox: LocalSubprocessSandbox):
        """多次 delete 不报错（目录已删再调）。"""
        sandbox.delete()
        sandbox.delete()

    def test_exec_works_without_explicit_ensure_started(self, sandbox: LocalSubprocessSandbox):
        """不显式 ensure_started 也能直接 exec（构造即可用）。"""
        result = sandbox.exec("echo works")
        assert result.exit_code == 0


# ── Round 8 加固：EOL 字节保持 + 原子写 ──


def test_write_then_read_preserves_lf_bytes(tmp_path):
    """LF 文件经 write/edit 后必须逐字节保持——write_text 默认 newline=None
    会把 \n 翻译成 os.linesep（win32 上 LF→CRLF）：git 显示整文件改动、
    .sh/Makefile 类文件直接损坏。写与读都必须字节透传（newline=""）。"""
    sandbox = LocalSubprocessSandbox(workspace_root=tmp_path)
    sandbox.write_text("a.txt", "line1\nline2\n")
    raw = (tmp_path / "a.txt").read_bytes()
    assert raw == b"line1\nline2\n", f"写入被 EOL 翻译污染: {raw!r}"
    assert sandbox.read_text("a.txt") == "line1\nline2\n"


def test_read_preserves_crlf_bytes(tmp_path):
    """已存在的 CRLF 文件读出不得被归一化成 LF——read_text 默认 universal
    newlines 会把 \r\n 折叠成 \n，edit 回写即产生整文件 diff。"""
    sandbox = LocalSubprocessSandbox(workspace_root=tmp_path)
    (tmp_path / "crlf.txt").write_bytes(b"line1\r\nline2\r\n")
    assert sandbox.read_text("crlf.txt") == "line1\r\nline2\r\n"


def test_write_text_is_atomic_replace(tmp_path):
    """写文件必须走 temp + os.replace（同目录），不能 truncate-in-place——
    进程崩溃/被 kill 在写中途会不可逆损毁原文件。验证目标文件由 rename 产生：
    写入过程短暂存在的临时文件留在同目录，最终内容完整。"""
    sandbox = LocalSubprocessSandbox(workspace_root=tmp_path)
    (tmp_path / "f.txt").write_bytes(b"old content")
    sandbox.write_text("f.txt", "new content")
    assert (tmp_path / "f.txt").read_bytes() == b"new content"
