"""C1/C2（用户拍板）：exec 协作取消 + 环境变量白名单。"""

import os
import subprocess
import threading
import time
from unittest.mock import patch

import pytest

from agent_harness.sandbox.local import LocalSubprocessSandbox


def _long_command() -> str:
    """跨平台的长命令（本仓两种测试宿主：win32 cmd / POSIX sh）。"""
    if os.name == "nt":
        return "ping -n 30 127.0.0.1 >nul"
    return "sleep 30"


def test_cancel_event_kills_process_tree(tmp_path):
    """cancel_event 置位后 exec 必须迅速返回（进程树被击杀），而不是等满命令时长。

    这是 C1 的执行层闭环：此前 asyncio 超时/断连只取消 await，bash 子进程
    继续跑满 sandbox 自身 60s 上限并持续改 workspace。
    """
    sandbox = LocalSubprocessSandbox(workspace_root=tmp_path)
    result_holder: list = []
    cancel_event = threading.Event()
    thread = threading.Thread(
        target=lambda: result_holder.append(
            sandbox.exec(_long_command(), cancel_event=cancel_event)
        )
    )
    thread.start()
    time.sleep(0.5)
    cancel_event.set()
    thread.join(timeout=5)
    assert not thread.is_alive(), "取消后 exec 线程 5s 内未结束——进程树未被击杀"
    assert len(result_holder) == 1
    assert result_holder[0].cancelled is True
    assert "取消" in result_holder[0].stderr


def test_unsignalled_exec_completes_normally(tmp_path):
    """不传 cancel_event（或未置位）：原有语义不变（git 等零轮询开销路径）。"""
    sandbox = LocalSubprocessSandbox(workspace_root=tmp_path)
    result = sandbox.exec("echo hello")
    assert result.exit_code == 0
    assert result.cancelled is False


def test_env_filtering_hides_non_allowlisted_variables(tmp_path, monkeypatch):
    """C2：子进程 env 只含白名单项——部署机 export 的密钥不再对 bash 可见。"""
    monkeypatch.setenv("AGENT_SECRET_PROBE", "super-secret-value")
    sandbox = LocalSubprocessSandbox(workspace_root=tmp_path)

    captured: dict = {}
    real_popen = subprocess.Popen

    def recording_popen(command, **kwargs):
        captured["env"] = kwargs.get("env")
        return real_popen(command, **kwargs)

    with patch("agent_harness.sandbox.local.subprocess.Popen", recording_popen):
        sandbox.exec("echo hi")

    env = captured["env"]
    assert env is not None, "exec 必须显式传 env（继承全量 = 泄漏面）"
    assert "AGENT_SECRET_PROBE" not in env
    assert "PATH" in env, "白名单过滤不能破坏命令可执行性"


def test_passthrough_env_escape_hatch(tmp_path, monkeypatch):
    """passthrough_env=True 显式继承全量环境（本地调试逃生门）。"""
    monkeypatch.setenv("AGENT_SECRET_PROBE", "x")
    sandbox = LocalSubprocessSandbox(workspace_root=tmp_path, passthrough_env=True)
    captured: dict = {}
    real_popen = subprocess.Popen

    def recording_popen(command, **kwargs):
        captured["env"] = kwargs.get("env")
        return real_popen(command, **kwargs)

    with patch("agent_harness.sandbox.local.subprocess.Popen", recording_popen):
        sandbox.exec("echo hi")
    assert captured["env"] is None  # None = 继承父进程全量 env


@pytest.mark.asyncio
async def test_bash_tool_signals_cancel_event_on_timeout(tmp_path):
    """bash 工具在 asyncio 超时触发时必须置位 cancel_event（执行层闭环）。"""

    from agent_harness.tooling import (
        ErrorCode,
        PermissionPolicy,
        ToolExecutor,
        ToolRegistry,
    )
    from agent_harness.tools import BashTool

    class SlowSandbox(LocalSubprocessSandbox):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.seen_cancel = None

        def exec(self, command, *, timeout=None, cancel_event=None, on_output=None):
            self.seen_cancel = cancel_event
            time.sleep(0.5)  # 超过工具 timeout，触发 asyncio 超时取消
            return super().exec("echo hi", timeout=timeout, cancel_event=cancel_event)

    sandbox = SlowSandbox(workspace_root=tmp_path)
    class _TimedBash(BashTool):
        @property
        def timeout_seconds(self) -> float:
            return 0.05

    registry2 = ToolRegistry()
    registry2.register(_TimedBash(sandbox))
    executor2 = ToolExecutor(registry2, policy=PermissionPolicy.DANGER_FULL_ACCESS)

    execution = await executor2.execute({"id": "c1", "name": "bash", "args": {"command": "slow"}})
    assert execution.result.error_code == ErrorCode.TIMEOUT
    assert sandbox.seen_cancel is not None and sandbox.seen_cancel.is_set(), (
        "超时后未通知 sandbox 击杀进程"
    )
