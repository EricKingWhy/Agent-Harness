"""Phase 14 真实 Gate（T9, #115, ADR-0017）。

五条 Gate（roadmap Phase 14 验收对照），生产装配形态（每会话一个 runtime——
web/CLI 同款；工具实例构造期绑定该会话 sandbox）：
1. fork 全链：真实两轮会话 → fork → child 独立 runtime 真实续跑（seed 快照可见）
2. tail summary：真实 LLM 对被放弃路线生成摘要，session/forked.tail_summary 在场
3. copy-on-fork 隔离：child 拿到 fork 点 workspace 快照，双向隔离
4. sessions --tree：真实 fork 边的 lineage 树渲染
5. replay 冻结契约：真实历史回放 + 零副作用

真实模型 = .env 主模型链（含智谱 fallback）；凭证零泄漏。手动跑：
uv run pytest tests/integration/test_phase14_gate.py -m integration -v
"""

from __future__ import annotations

import json

import pytest

from agent_harness.cli import replay_command, sessions_command
from agent_harness.config import Settings
from agent_harness.session import Session
from agent_harness.session.event import (
    SESSION_FORKED,
    TOOL_RESULT,
    USER_MESSAGE,
)
from agent_harness.session.fork import TailSummarizer, fork_session
from agent_harness.session.store import JsonlSessionStore
from agent_harness.storage.sqlite import SqliteSessionMetaStore

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _gate_settings(tmp_path) -> Settings:
    settings = Settings()
    if not settings.model_api_key.get_secret_value():
        pytest.skip("Real primary model (MODEL_*) is not configured")
    settings.workspace_dir = str(tmp_path)
    settings.capabilities = json.dumps({})  # 纯单代理：fork/replay 不依赖插件
    return settings


@pytest.fixture
def gate_env(tmp_path):
    """真实模型 + 共享基建（stores/registry/store）；runtime 按会话逐个构建。"""
    import asyncio

    settings = _gate_settings(tmp_path)
    from agent_harness.assembly import (
        assemble_wiring,
        initialize_stores,
        recovery_stores,
    )
    from agent_harness.sandbox import WorkspaceRegistry

    async def _build():
        stores = recovery_stores(tmp_path / "harness.db")
        await initialize_stores(stores)
        _, wiring = await assemble_wiring(settings)
        registry = WorkspaceRegistry(root=tmp_path, backend="local")
        store = JsonlSessionStore(tmp_path / "sessions")
        return settings, wiring, stores, registry, store

    return asyncio.new_event_loop().run_until_complete(_build()) + (tmp_path,)


async def _new_runtime(gate_env, session_id: str):
    """生产形态：每个会话一个 runtime（工具实例绑定该会话的 workspace）。"""
    from agent_harness.assembly import build_runtime

    settings, wiring, stores, registry, store, tmp_path = gate_env
    return await build_runtime(
        settings=settings, wiring=wiring, stores=stores,
        workspace_registry=registry,
        session_id=session_id,
        workspace=tmp_path / "workspaces" / session_id,
        max_steps=10, auto_approve=True, session_store=store,
    )


async def _run_and_collect(runtime, session, task: str):
    events = []
    async for event in runtime.run_stream(session, task):
        events.append(event)
    return events


def _real_summarizer(settings: Settings) -> TailSummarizer:
    from agent_harness.model.config import ModelConfig
    from agent_harness.model.provider import create_chat_model

    return TailSummarizer(create_chat_model(ModelConfig.from_settings(settings)))


class TestGate1ForkFullChain:
    @pytest.mark.asyncio
    async def test_real_fork_then_child_resume(self, gate_env):
        """真实两轮会话 fork → child 独立 runtime 续跑，seed 快照（文件）可见。"""
        _, _, _, registry, store, tmp_path = gate_env
        meta_store = SqliteSessionMetaStore(tmp_path / "harness.db")
        await meta_store.initialize()
        for attempt in range(3):
            parent_id = f"g1-{attempt}"
            parent_runtime = await _new_runtime(gate_env, parent_id)
            session = Session.start(
                store, session_id=parent_id, workspace_registry=registry
            )
            await _run_and_collect(
                parent_runtime, session,
                "用 bash 工具在当前目录创建文件 marker.txt，内容为一行文本 "
                "phase14-seed。完成后确认。",
            )
            await _run_and_collect(
                parent_runtime, session, "1+1等于几？直接回答，不要用工具"
            )
            anchor = [e for e in session.events if e.type == USER_MESSAGE][-1].seq
            child = await fork_session(
                store, meta_store, parent_id,
                boundary_user_message_seq=anchor,
                child_session_id=f"g1-child-{attempt}",
                workspace_registry=registry,
            )
            child_runtime = await _new_runtime(gate_env, child.session_id)
            resumed = await _run_and_collect(
                child_runtime, child,
                "用 bash 工具查看当前目录 marker.txt 的内容，把内容原样告诉我。",
            )
            terminal = [e for e in resumed if e.type == "run/completed"]
            if terminal:
                final_text = terminal[-1].data.get("final_text", "")
                assert "phase14-seed" in final_text, (
                    "child 应能看到 fork 点快照里的文件内容"
                )
                # 父文件零改动（§7）：无 forked 等任何追加
                parent_after = store.read_events(parent_id)
                assert not any(e.type == SESSION_FORKED for e in parent_after)
                return
        pytest.fail("3 次尝试内 fork→child resume 未走通（上游故障或模型未配合）")


class TestGate2TailSummaryReal:
    @pytest.mark.asyncio
    async def test_real_tail_summary_attached(self, gate_env):
        """真实 LLM 对被放弃路线生成摘要 → session/forked.tail_summary 在场。"""
        settings, _, _, registry, store, tmp_path = gate_env
        meta_store = SqliteSessionMetaStore(tmp_path / "harness.db")
        await meta_store.initialize()
        for attempt in range(3):
            parent_id = f"g2-{attempt}"
            parent_runtime = await _new_runtime(gate_env, parent_id)
            session = Session.start(
                store, session_id=parent_id, workspace_registry=registry
            )
            await _run_and_collect(parent_runtime, session, "1+1等于几？直接回答")
            await _run_and_collect(
                parent_runtime, session,
                "一句话说明：你倾向于用 Python 还是 Go 写并发脚本？只回答选择。",
            )
            anchor = [e for e in session.events if e.type == USER_MESSAGE][-1].seq
            child = await fork_session(
                store, meta_store, parent_id,
                boundary_user_message_seq=anchor,
                child_session_id=f"g2-child-{attempt}",
                summarizer=_real_summarizer(settings),
            )
            forked = [e for e in child.events if e.type == SESSION_FORKED]
            if forked and forked[-1].data.get("tail_summary"):
                assert len(forked[-1].data["tail_summary"]) >= 5
                return
        pytest.fail("3 次尝试内 tail summary 未真实生成")


class TestGate3CopyOnForkIsolation:
    @pytest.mark.asyncio
    async def test_child_workspace_snapshot_isolated(self, gate_env):
        """child 拿到 fork 点快照；双向隔离（child 改不伤父，父后写不进 child）。"""
        _, _, _, registry, store, tmp_path = gate_env
        meta_store = SqliteSessionMetaStore(tmp_path / "harness.db")
        await meta_store.initialize()
        for attempt in range(3):
            parent_id = f"g3-{attempt}"
            parent_runtime = await _new_runtime(gate_env, parent_id)
            session = Session.start(
                store, session_id=parent_id, workspace_registry=registry
            )
            await _run_and_collect(
                parent_runtime, session,
                "用 bash 工具创建文件 iso.txt，内容为 before-fork。完成后确认。",
            )
            anchor = [e for e in session.events if e.type == USER_MESSAGE][-1].seq
            parent_sandbox = registry.get(parent_id)
            if not parent_sandbox.list_files("*"):
                continue  # 父本轮没写成文件（模型未配合），重试
            child = await fork_session(
                store, meta_store, parent_id,
                boundary_user_message_seq=anchor,
                child_session_id=f"g3-child-{attempt}",
                workspace_registry=registry,
            )
            assert child.sandbox is not None
            assert "before-fork" in child.sandbox.read_text("iso.txt")
            # 双向隔离（echo 写入可能带引号/换行——用子串断言语义）
            child.sandbox.write_text("iso.txt", "child-edited")
            assert "before-fork" in parent_sandbox.read_text("iso.txt")
            parent_sandbox.write_text("late.txt", "parent-only")
            assert "late.txt" not in child.sandbox.list_files("*")
            return
        pytest.fail("3 次尝试内父 workspace 未产出 iso.txt（上游故障）")


class TestGate4SessionsTreeReal:
    @pytest.mark.asyncio
    async def test_real_fork_edge_renders_in_tree(self, gate_env):
        """真实 fork 边经 sessions --tree 渲染（[fork @seq] 标注在场）。"""
        _, _, _, _registry, store, tmp_path = gate_env
        meta_store = SqliteSessionMetaStore(tmp_path / "harness.db")
        await meta_store.initialize()
        for attempt in range(3):
            parent_id = f"g4-{attempt}"
            parent_runtime = await _new_runtime(gate_env, parent_id)
            session = Session.start(store, session_id=parent_id)
            await _run_and_collect(parent_runtime, session, "1+1等于几？直接回答")
            anchor = [e for e in session.events if e.type == USER_MESSAGE][-1].seq
            await fork_session(
                store, meta_store, parent_id,
                boundary_user_message_seq=anchor,
                child_session_id=f"g4-child-{attempt}",
            )
            out = await sessions_command(tree=True, workspace_dir=str(tmp_path))
            if f"g4-child-{attempt}" in out and "[fork @" in out:
                assert parent_id in out
                return
        pytest.fail("3 次尝试内 fork 边未进树渲染")


class TestGate5ReplayFrozen:
    @pytest.mark.asyncio
    async def test_replay_real_history_zero_side_effects(self, gate_env):
        """真实历史回放：tool result 冻结可见 + 事件/文件零副作用。"""
        _, _, _, _registry, store, tmp_path = gate_env
        for attempt in range(3):
            parent_id = f"g5-{attempt}"
            parent_runtime = await _new_runtime(gate_env, parent_id)
            session = Session.start(store, session_id=parent_id)
            await _run_and_collect(
                parent_runtime, session,
                "用 bash 工具执行 echo replay-ok 并告诉我输出。",
            )
            tool_results = [e for e in session.events if e.type == TOOL_RESULT]
            if not tool_results:
                continue
            before = [e.to_dict() for e in store.read_events(parent_id)]
            out = await replay_command(
                parent_id, workspace_dir=str(tmp_path)
            )
            assert "replay-ok" in out  # 冻结终态的 tool result 可见
            assert "[工具]" in out and "bash" in out
            after = [e.to_dict() for e in store.read_events(parent_id)]
            assert after == before  # 零副作用：连 resumed 都没追加
            return
        pytest.fail("3 次尝试内父 run 未产生 tool result（上游故障）")
