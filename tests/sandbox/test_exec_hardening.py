"""Sandbox exec 硬化：捕获上限（D4）+ 超时契约（D10）+ event loop 卸载。

诊断依据（Directive B /diagnose）：
- D4：subprocess capture_output 无上限，大输出 OOM 进程——捕获到上限后继续
  排空管道让子进程自然结束，超出部分丢弃并附截断标记。
- D10：DockerSandbox.exec 丢弃 timeout 参数且同步调用阻塞 event loop——
  补上超时语义（线程级等待，超时返回 exit_code=-1），并把 tool 边界的
  sandbox.exec 调用卸载到工作线程。
"""

from __future__ import annotations

import os
import sys
import threading
import time
from unittest.mock import Mock

import pytest

from agent_harness.sandbox import ExecResult, LocalSubprocessSandbox
from agent_harness.tools import BashTool
from agent_harness.tools.bash import _BashArgs


def test_local_exec_caps_captured_output(tmp_path):
    """输出超过捕获上限：子进程正常结束，超限部分丢弃且带截断标记。"""
    (tmp_path / "gen.py").write_text("print('x' * 5000)", encoding="utf-8")
    sandbox = LocalSubprocessSandbox(tmp_path, max_capture_chars=1000)
    result = sandbox.exec(f'"{sys.executable}" gen.py')
    assert result.exit_code == 0
    assert 1000 <= len(result.stdout) < 5000
    assert "截断" in result.stderr or "截断" in result.stdout


def test_local_exec_under_cap_is_untouched(tmp_path):
    """未超上限时输出原样返回，无标记——既有行为不变。"""
    (tmp_path / "gen.py").write_text("print('hello')", encoding="utf-8")
    sandbox = LocalSubprocessSandbox(tmp_path, max_capture_chars=1000)
    result = sandbox.exec(f'"{sys.executable}" gen.py')
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"
    assert "截断" not in result.stdout and "截断" not in result.stderr


# ============================================================================
# 超时击杀范围：整棵进程树，而不只 shell 壳（[HAZARD] 超时杀树泄漏）
# ============================================================================


@pytest.mark.skipif(os.name != "nt", reason="泄漏场景依赖 Windows shell=True(cmd.exe) 与 start 语义")
def test_local_exec_timeout_kills_grandchild_tree(tmp_path):
    """超时后整棵进程树必须死透：孙进程不得在 exec 返回后继续写 workspace。

    shell=True 时 Popen 拿到的只是 cmd.exe 壳；壳里 start 出的孙进程若只被
    process.kill() 漏掉，会在 exec 返回后继续写 marker 文件、占住捕获管道
    （reader join 超时），其 cwd 锁还会让 delete() 的 rmtree 静默失败。
    """
    sandbox = LocalSubprocessSandbox(tmp_path)
    # start /b 拉起脱管的孙进程（ping 约 3 秒后才写 marker），外层 ping 让壳活到超时
    command = (
        'start /b cmd /c "ping -n 4 127.0.0.1 > nul & echo x > leak_marker.txt"'
        " & ping -n 10 127.0.0.1 > nul"
    )
    result = sandbox.exec(command, timeout=1)

    # 超时契约不变：不抛异常，返回 exit_code=-1 + stderr 超时提示
    assert result.exit_code == -1
    assert "超时" in result.stderr

    # 泄漏的孙进程会在 ~3 秒后写出 marker；轮询窗口内绝不允许出现
    marker = sandbox.workspace_root / "leak_marker.txt"
    deadline = time.perf_counter() + 3.0
    while time.perf_counter() < deadline:
        assert not marker.exists(), "超时后孙进程仍存活并写出文件——超时击杀泄漏了进程树"
        time.sleep(0.1)

    # 整树已死：workspace 不再被孙进程 cwd 锁占住，delete() 能真正删干净
    sandbox.delete()
    assert not sandbox.workspace_root.exists()


@pytest.mark.asyncio
async def test_bash_tool_offloads_exec_to_worker_thread(tmp_path):
    """tool 边界把同步 sandbox.exec 卸载到工作线程——event loop 不被长命令冻结。"""
    seen: dict = {}

    class ProbeSandbox(LocalSubprocessSandbox):
        def exec(self, command, *, timeout=None, cancel_event=None, on_output=None):
            seen["thread"] = threading.current_thread()
            return ExecResult(exit_code=0, stdout="", stderr="", duration_ms=0.0)

    tool = BashTool(ProbeSandbox(tmp_path))
    await tool.execute(_BashArgs(command="anything"))
    assert seen["thread"] is not threading.main_thread()


def _docker_sandbox_with_slow_exec(delay: float) -> object:
    """构造跳过 __init__ 的 DockerSandbox：不需要 Docker daemon 即可测 exec 契约。"""
    from agent_harness.sandbox.docker import DockerSandbox

    sandbox = object.__new__(DockerSandbox)
    container = Mock()
    container.reload = Mock()
    container.status = "running"

    def slow_exec_run(*args, **kwargs):
        time.sleep(delay)
        return Mock(exit_code=0, output=(b"done", b""))

    container.exec_run = slow_exec_run
    sandbox._container = container
    return sandbox


def test_docker_exec_honors_timeout():
    """D10：挂起的容器命令在 timeout 到点后返回超时 ExecResult，不再永久阻塞。"""
    sandbox = _docker_sandbox_with_slow_exec(delay=30)
    t0 = time.perf_counter()
    result = sandbox.exec("hang forever", timeout=0.2)
    elapsed = time.perf_counter() - t0
    assert result.exit_code == -1
    assert "超时" in result.stderr
    assert elapsed < 5, "exec 必须在 timeout 附近返回，而不是等容器命令结束"


def test_docker_exec_passes_through_normal_result():
    """正常路径契约不变：exit_code / stdout 解码 / demux。"""
    sandbox = _docker_sandbox_with_slow_exec(delay=0)
    result = sandbox.exec("echo done", timeout=5)
    assert result.exit_code == 0
    assert result.stdout == "done"
