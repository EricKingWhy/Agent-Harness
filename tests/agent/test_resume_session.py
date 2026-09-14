"""Ticket D — Resume 集成测试：验证进程重启后能从 SessionEvent 恢复完整对话。

不需要真实 LLM——用 ScriptedModel 模拟"前半段已跑完、后半段新进程继续"的场景。
验证 Phase 1 Gate：简单对话重启后可恢复历史。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from agent_harness.agent import AgentRuntime
from agent_harness.agent.types import STATUS_COMPLETED
from agent_harness.session import JsonlSessionStore, Session
from agent_harness.tooling import Tool, ToolExecutor, ToolRegistry, ToolResult
from tests.scripted_model import ScriptedModel


class _NoopArgs(BaseModel):
    pass


class EchoTool(Tool):
    """简单回显工具——用于验证 resume 后工具链仍可正常工作。"""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "回显输入文本。"

    @property
    def args_schema(self):
        return _NoopArgs

    async def execute(self, args) -> ToolResult:
        return ToolResult.success(message="echo", data={})


def _runtime(model: ScriptedModel) -> AgentRuntime:
    reg = ToolRegistry()
    reg.register(EchoTool())
    return AgentRuntime(model=model, registry=reg, executor=ToolExecutor(reg))


class TestResumeScenario:
    """模拟进程崩溃与恢复：第一段跑完后用 Session.resume 加载历史，第二段继续。"""

    @pytest.mark.asyncio
    async def test_resume_preserves_full_history(self, tmp_path: Path):
        """Phase 1 Gate 核心验证：重启后 derive_messages 能还原完整消息链。"""

        # ── 第一段：模拟一次完整的对话（已跑完、已持久化到 JSONL）──
        store = JsonlSessionStore(root=tmp_path)
        session = Session.start(store)

        # 手动写入一段对话事件（模拟 Runtime 已跑过的效果）
        session.append("user/message", {"content": "你好"})
        session.append("model/completed", {"content": "你好！我是助手"})
        session.append("user/message", {"content": "帮我算个事"})
        session.append(
            "model/completed",
            {
                "content": "好的",
                "tool_calls": [{"id": "tc1", "name": "echo", "args": {}}],
            },
        )
        session.append("tool/call", {"tool_call_id": "tc1", "tool_name": "echo", "args": {}})
        session.append("tool/result", {"tool_call_id": "tc1", "content": "echo done"})
        session.append("model/completed", {"content": "已完成"})

        sid = session.session_id

        # ── 第二段：新进程，用 resume 加载历史 ──
        restored = Session.resume(store, sid)

        messages = restored.derive_messages()
        # 4 条消息：user + ai + user + ai(tool_calls) + tool + ai = 6
        # 但 derive_messages 不投影 session/started 和 session/resumed 事件
        assert len(messages) == 6

        # 验证消息顺序和内容完整
        assert messages[0].content == "你好"  # HumanMessage
        assert messages[1].content == "你好！我是助手"  # AIMessage
        assert messages[2].content == "帮我算个事"  # HumanMessage
        assert messages[3].tool_calls[0]["id"] == "tc1"  # AIMessage with tool_calls
        assert messages[4].tool_call_id == "tc1"  # ToolMessage
        assert messages[4].content == "echo done"
        assert messages[5].content == "已完成"  # final AIMessage

    @pytest.mark.asyncio
    async def test_resume_then_continue_with_runtime(self, tmp_path: Path):
        """恢复历史后，用新 Runtime 继续跑——验证 AgentLoop 能从恢复的事件驱动。"""

        # ── 第一段：跑一个完整对话（无工具） ──
        store = JsonlSessionStore(root=tmp_path)
        session1 = Session.start(store)
        runtime1 = _runtime(ScriptedModel([AIMessage(content="你好，我是助手")]))
        result1 = await runtime1.run(session1, "你好")
        assert result1.status == STATUS_COMPLETED
        sid = session1.session_id

        # ── 第二段：resume 后继续 ──
        session2 = Session.resume(store, sid)
        # resume 时事件链包含：session/started, user/message, model/completed, run/completed, session/resumed
        # derive_messages 应返回之前的 HumanMessage + AIMessage
        messages_before = session2.derive_messages()
        assert len(messages_before) == 2  # 原始对话
        assert messages_before[0].content == "你好"
        assert messages_before[1].content == "你好，我是助手"

        # 用恢复的 session 再跑一轮新对话
        runtime2 = _runtime(ScriptedModel([AIMessage(content="我记得你说过你好")]))
        result2 = await runtime2.run(session2, "你还记得我刚才说了什么吗？")

        assert result2.status == STATUS_COMPLETED
        assert result2.steps == 1

        # 验证第二轮跑完后，历史包含两段对话
        messages_after = session2.derive_messages()
        # 2（第一段）+ 1（第二段 user）+ 1（第二段 ai）= 4
        assert len(messages_after) == 4
        assert messages_after[0].content == "你好"
        assert messages_after[2].content == "你还记得我刚才说了什么吗？"
        assert messages_after[3].content == "我记得你说过你好"

    @pytest.mark.asyncio
    async def test_resume_disk_persistence_across_store_instances(self, tmp_path: Path):
        """完全模拟进程重启：新建一个 Store 实例读取同一个磁盘目录。"""

        # 第一段
        store1 = JsonlSessionStore(root=tmp_path)
        session1 = Session.start(store1)
        session1.append("user/message", {"content": " persisted message "})
        session1.append("model/completed", {"content": " reply "})
        sid = session1.session_id

        # 第二段：完全新的 Store 实例（模拟新进程）
        store2 = JsonlSessionStore(root=tmp_path)
        session2 = Session.resume(store2, sid)

        messages = session2.derive_messages()
        assert len(messages) == 2
        assert messages[0].content == " persisted message "
        assert messages[1].content == " reply "
