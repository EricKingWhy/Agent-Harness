"""ContextBuilder token 估算增量 memo（perf-fix 1+2，diagnosing-bugs 实证）。

剖析实证：每步对全部历史消息做两次 model_dump_json + 全文 BPE 编码占循环
开销 88%（O(N²)）。修复后每条消息终身只编码一次（事件落盘即冻结）。

契约：
- memo 总量与朴素全量估算严格相等（阈值语义不变）；
- 增量性：已估算过的消息不再进入 tiktoken（只估新投影消息）；
- 投影与事件失去一一对应（dangling 合成注入）时整体回退全量估算；
- build 内只做一次全量级估算（_with_providers 复用 memo 总量）。
"""

import pytest

from agent_harness.context import builder as builder_module
from agent_harness.context.builder import ContextBuilder
from agent_harness.context.tokens import estimate_message_tokens
from agent_harness.session import MODEL_COMPLETED, TOOL_RESULT, USER_MESSAGE
from tests.conftest import make_session
from tests.scripted_model import ScriptedModel


def _append_tool_step(session, i: int, output_kb: int) -> None:
    """追加一步 user→model(tool_call)→tool/result(big) 事件。"""
    filler = "x" * (output_kb * 1024)
    session.append(USER_MESSAGE, {"content": f"第 {i} 步：读取文件"})
    session.append(MODEL_COMPLETED, {
        "content": "",
        "tool_calls": [{"id": f"call_{i:05d}", "name": "read",
                        "args": {"path": f"src/mod_{i}.py"}}],
    })
    session.append(TOOL_RESULT, {
        "tool_call_id": f"call_{i:05d}",
        "content": f"def f_{i}():\n    {filler}",
    })


class TestTokenMemoCorrectness:
    @pytest.mark.asyncio
    async def test_memo_total_equals_naive_estimate(self, tmp_path):
        """memo 总量必须与朴素 estimate_message_tokens 严格相等。"""
        session = make_session(tmp_path)
        for i in range(8):
            _append_tool_step(session, i, output_kb=2)
        builder = ContextBuilder(ScriptedModel([]))

        messages = await builder.build(session)

        assert builder._token_estimate_total == estimate_message_tokens(messages)

    @pytest.mark.asyncio
    async def test_second_build_estimates_only_new_messages(self, tmp_path, monkeypatch):
        """增量性：第二次 build 只对新投影消息调用 tiktoken，旧消息命中 memo。"""
        session = make_session(tmp_path)
        _append_tool_step(session, 0, output_kb=2)
        _append_tool_step(session, 1, output_kb=2)
        builder = ContextBuilder(ScriptedModel([]))

        calls = {"n": 0}
        real_estimate = builder_module.estimate_tokens

        def counting_estimate(text: str) -> int:
            calls["n"] += 1
            return real_estimate(text)

        monkeypatch.setattr(builder_module, "estimate_tokens", counting_estimate)

        await builder.build(session)
        first_round = calls["n"]
        assert first_round == 6  # 每个投影事件恰好编码一次

        _append_tool_step(session, 2, output_kb=2)
        await builder.build(session)
        assert calls["n"] == first_round + 3  # 只编码 3 条新消息

        # 无新事件的重复 build：零新增编码
        await builder.build(session)
        assert calls["n"] == first_round + 3


class TestTokenMemoFallback:
    @pytest.mark.asyncio
    async def test_dangling_synthesis_falls_back_to_full_estimate(self, tmp_path):
        """投影出现事件无法对应的消息（dangling 合成 ToolMessage）→
        放弃增量、整体重估，总量仍然正确。"""
        from agent_harness.session.derive import DANGLING_TOOL_CONTENT

        session = make_session(tmp_path)
        session.append(USER_MESSAGE, {"content": "读取文件"})
        session.append(MODEL_COMPLETED, {
            "content": "",
            "tool_calls": [{"id": "dangling-1", "name": "read", "args": {}}],
        })
        # 故意不追加 tool/result → derive_messages 注入合成 ToolMessage
        builder = ContextBuilder(ScriptedModel([]))

        messages = await builder.build(session)

        # 2 个投影事件 + 1 条合成 ToolMessage = 3 条消息
        assert len(messages) == 3
        assert messages[-1].content == DANGLING_TOOL_CONTENT
        # 计数失配 → 走 fallback：本会话 memo 清空，总量 = 朴素全量估算
        assert not any(key[0] == session.session_id for key in builder._token_memo)
        assert builder._token_estimate_total == estimate_message_tokens(messages)

    @pytest.mark.asyncio
    async def test_memo_survives_across_builds_after_fallback(self, tmp_path, monkeypatch):
        """fallback 清掉本会话 memo → 对应恢复后的下一轮全量重建一次，
        再之后恢复增量（无新事件零编码）。"""
        session = make_session(tmp_path)
        session.append(USER_MESSAGE, {"content": "读取文件"})
        session.append(MODEL_COMPLETED, {
            "content": "",
            "tool_calls": [{"id": "dangling-1", "name": "read", "args": {}}],
        })
        builder = ContextBuilder(ScriptedModel([]))
        await builder.build(session)  # fallback 路径

        calls = {"n": 0}
        real_estimate = builder_module.estimate_tokens

        def counting_estimate(text: str) -> int:
            calls["n"] += 1
            return real_estimate(text)

        monkeypatch.setattr(builder_module, "estimate_tokens", counting_estimate)

        session.append(TOOL_RESULT, {"tool_call_id": "dangling-1", "content": "结果"})
        await builder.build(session)
        # dangling 已由真实 tool/result 解决 → 一一对应恢复；
        # 但 memo 在 fallback 时已清空 → 本轮全量重建（3 条各一次）
        assert calls["n"] == 3
        # 再来一次无新事件的 build：零新增编码（增量已恢复）
        await builder.build(session)
        assert calls["n"] == 3


class TestSingleEstimationPass:
    @pytest.mark.asyncio
    async def test_provider_budget_reuses_memo_total(self, tmp_path, monkeypatch):
        """_with_providers 不再重复全量估算：provider 预算用 memo 总量。"""
        session = make_session(tmp_path)
        _append_tool_step(session, 0, output_kb=2)
        builder = ContextBuilder(ScriptedModel([]))

        calls = {"n": 0}
        real_estimate = builder_module.estimate_tokens

        def counting_estimate(text: str) -> int:
            calls["n"] += 1
            return real_estimate(text)

        monkeypatch.setattr(builder_module, "estimate_tokens", counting_estimate)
        await builder.build(session)

        assert calls["n"] == 3  # 3 条投影消息各一次（旧实现要 6 次）
