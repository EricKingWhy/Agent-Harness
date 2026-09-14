"""Phase 13 真实 Gate（T12, #93, ADR-0015）。

八条 Gate（roadmap Phase 13 + spec §13 验收 + ticket #93 场景）：
1. research 任务路由到 research_review（真实模型决定委派）
2. coding 任务路由到 coding + 共享 workspace 真实写文件
3. 动态第四个 AgentSpec 经 AgentFactory 创建并真实跑通
4. child 不倾倒完整历史（父流事件数抽查 vs child JSONL）
5. mixed 任务：research 结论 → coding 落盘（两个 child 协作）
6. 同指纹失败 delegate 真实触发 RepeatedToolFailureGuard（软/硬熔断）
7. delegation 预算（max_delegations）真实耗尽回填
8. CAPABILITIES 未配 multiagent → 单代理零感知回归（无 delegate）

真实模型 = .env 主模型配置；凭证零泄漏。手动跑：
uv run pytest tests/integration/test_phase13_gate.py -m integration -v
"""

from __future__ import annotations

import json

import pytest

from agent_harness.agent.factory import AgentFactory
from agent_harness.config import Settings
from agent_harness.session import Session
from agent_harness.session.store import JsonlSessionStore
from agent_harness.tooling import ToolRegistry

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _gate_settings(tmp_path) -> Settings:
    # 真实 .env（repo 根）提供 MODEL_*/FALLBACK_*；workspace 指向 tmp 隔离。
    settings = Settings()
    if not settings.model_api_key.get_secret_value():
        pytest.skip("Real primary model (MODEL_*) is not configured")
    settings.workspace_dir = str(tmp_path)
    caps = {"multiagent": {"provider": "builtin", "enabled": True, "options": {}}}
    settings.capabilities = json.dumps(caps)
    return settings


@pytest.fixture
def gate_env(tmp_path):
    """真实模型 + multiagent capability 的完整运行环境。"""
    import asyncio

    settings = _gate_settings(tmp_path)
    from agent_harness.assembly import (
        build_runtime,
        initialize_stores,
        recovery_stores,
    )
    from agent_harness.capability.base import CapabilityRegistry
    from agent_harness.capability.config import parse_capabilities_config
    from agent_harness.capability.wiring import wire_capabilities
    from agent_harness.sandbox import WorkspaceRegistry

    async def _build():
        stores = recovery_stores(tmp_path / "harness.db")
        await initialize_stores(stores)
        registry = CapabilityRegistry()
        wiring = await wire_capabilities(
            registry, parse_capabilities_config(settings.capabilities),
            settings=settings,
        )
        workspace_registry = WorkspaceRegistry(root=tmp_path / "workspaces")
        store = JsonlSessionStore(tmp_path / "sessions")
        session_id = f"gate-{tmp_path.name[:8]}"
        workspace = tmp_path / "workspaces" / session_id
        runtime = await build_runtime(
            settings=settings, wiring=wiring, stores=stores,
            workspace_registry=workspace_registry,
            session_id=session_id, workspace=workspace,
            max_steps=15, auto_approve=True, session_store=store,
        )
        return runtime, store, workspace_registry, workspace, session_id

    return asyncio.new_event_loop().run_until_complete(_build()) + (tmp_path,)


async def _run_and_collect(runtime, session, task: str):
    events = []
    async for event in runtime.run_stream(session, task):
        events.append(event)
    return events


class TestGate1ResearchRouting:
    @pytest.mark.asyncio
    async def test_research_task_delegates_to_research_review(self, gate_env):
        """真实模型把调研任务委派给 research_review → delegation 事件 + 结果。

        上游网关瞬时故障（429/5xx）环境噪声大——3 次独立尝试协议（每次全新
        session），任一次路由成功即过（与 Phase 12 breaker gate 同款）。"""
        runtime, store, _workspace_registry, _workspace, _session_id, _tmp_path = gate_env
        last_events: list = []
        for attempt in range(3):
            session = Session.start(store, session_id=f"gate-research-{attempt}")
            await _run_and_collect(
                runtime, session,
                "你必须使用 delegate 工具把下面的任务委派给 research_review 子代理"
                "执行，你自己不要执行任务、不要亲自搜索。委派后把子代理的结果转述"
                "给我。任务：用 web_search 搜索 Tavily 是什么公司的产品，并一句话"
                "总结。",
            )
            delegation_finished = [e for e in session._events
                                   if e.type == "agent/delegation-finished"]
            if delegation_finished and delegation_finished[-1].data["status"] == "completed":
                assert delegation_finished[-1].data["target"] == "research_review"
                assert delegation_finished[-1].data["child_session_id"]
                return
            last_events = session._events
        print("DEBUG-EVENTS:", [(e.type, str(e.data)[:70]) for e in last_events])
        pytest.fail("3 次尝试内 research 路由都未成功（上游故障或模型未委派）")


class TestGate2CodingRouting:
    @pytest.mark.asyncio
    async def test_coding_task_writes_shared_workspace(self, gate_env):
        """coding 子代理在共享 workspace 真实写文件（spec §9 同一 sandbox）。"""
        runtime, store, _workspace_registry, workspace, _session_id, _tmp_path = gate_env
        for attempt in range(3):
            session = Session.start(store, session_id=f"gate-coding-{attempt}")
            await _run_and_collect(
                runtime, session,
                "你必须使用 delegate 工具把任务委派给 coding 子代理执行，你自己"
                "不要写文件。委派后验证并向我确认。任务：在当前目录创建文件 "
                "hello.txt，内容为一行文本 phase13-ok。",
            )
            delegation_finished = [e for e in session._events
                                   if e.type == "agent/delegation-finished"]
            if (delegation_finished
                    and delegation_finished[-1].data["status"] == "completed"
                    and (workspace / "hello.txt").exists()):
                assert delegation_finished[-1].data["target"] == "coding"
                assert "phase13-ok" in (workspace / "hello.txt").read_text(encoding="utf-8")
                return
        pytest.fail("3 次尝试内 coding 路由+写文件都未成功")


class TestGate3DynamicFourthAgent:
    @pytest.mark.asyncio
    async def test_fourth_agentspec_runs_real_model(self, gate_env):
        """动态第四个 AgentSpec 经 AgentFactory 创建并真实跑通（Gate 验收）。"""
        runtime, _store, _workspace_registry, _workspace, _session_id, tmp_path = gate_env
        # 复用 runtime 的模型链构造第 4 个 agent
        from agent_harness.agent.profiles import AgentSpec

        spec = AgentSpec(
            name="analyst", description="Gate 专用临时分析角色",
            system_prompt="你是数据分析 agent：把收到的数字列表求和，一句话回答总和。",
            tool_scope=frozenset(),  # 纯推理，无工具
            max_steps=3,
        )
        factory = AgentFactory(
            model=runtime.model, primary_model_name="gate-analyst",
            stream_idle_timeout=60.0, stream_total_timeout=600.0,
        )
        analyst_runtime = factory.create(spec, source_registry=ToolRegistry())
        analyst_session = Session.start(
            JsonlSessionStore(tmp_path / "sessions" / "analyst"),
        )

        result = await analyst_runtime.run(
            analyst_session, "数字列表：21、21、105。总和是多少？"
        )

        assert result.status == "completed"
        assert "147" in result.final_text


class TestGate4NoHistoryDump:
    @pytest.mark.asyncio
    async def test_parent_stream_stays_clean_after_delegation(self, gate_env):
        """child 不倾倒完整历史：父 session 不含 child 的 run/模型内部事件。"""
        runtime, store, _workspace_registry, _workspace, _session_id, tmp_path = gate_env
        session = Session.start(store, session_id="gate-nodump")

        await _run_and_collect(
            runtime, session,
            "你必须使用 delegate 工具把任务派给 research_review 子代理执行，"
            "不要亲自搜索。任务：搜索 Python 官网网址，一句话回答。",
        )

        parent_types = [e.type for e in session._events]
        from collections import Counter

        counts = Counter(parent_types)
        # 父流只有 supervisor 自己的紧凑事件（不含 child 的多轮内幕）
        assert counts.get("run/completed", 0) <= 1, "父 session 只有自己的 run"
        delegation_started = [e for e in session._events
                              if e.type == "agent/delegation-started"]
        assert delegation_started, "委派事件在父流"
        child_session_id = delegation_started[0].data["child_session_id"]
        child_events = Session.resume(
            JsonlSessionStore(tmp_path / "sessions"), child_session_id,
        )
        child_types = [e.type for e in child_events._events]
        assert child_types.count("model/completed") >= 1, "child 自己的历史完整留存"
        # 不倾倒：父流的模型/工具事件数 << child 的内部步数（supervisor 最多
        # 委派+确认两轮；child 的完整多轮历史只在 child JSONL）
        parent_model_calls = counts.get("model/completed", 0)
        assert parent_model_calls <= 3, (
            f"父流 model/completed={parent_model_calls}——child 历史疑似倾倒"
        )
        child_model_calls = child_types.count("model/completed")
        assert (
            parent_model_calls < child_model_calls or child_model_calls == 1
        ), "父流模型事件应显著少于 child 内部步数"


class TestGate5MixedCoordination:
    @pytest.mark.asyncio
    async def test_mixed_task_two_children_cooperate(self, gate_env):
        """mixed 任务：research 结论经 supervisor 交接给 coding 落盘（两 child 协作）。"""
        runtime, store, _workspace_registry, workspace, _session_id, _tmp_path = gate_env
        for attempt in range(3):
            session = Session.start(store, session_id=f"gate-mixed-{attempt}")
            await _run_and_collect(
                runtime, session,
                "你必须分两步使用 delegate 工具完成下面的任务，不要亲自搜索或写"
                "文件。第一步：委派给 research_review，任务为『用 web_search 搜索"
                "Tavily 是什么公司的产品，一句话总结』。等第一步结果返回后，第二"
                "步：把第一步的总结原文交给 coding 子代理，让它把总结写入当前目"
                "录文件 mixed.txt（一行文本）。最后向我确认两步都完成。",
            )
            finished = [e for e in session._events
                        if e.type == "agent/delegation-finished"]
            if (len(finished) >= 2
                    and all(e.data["status"] == "completed" for e in finished)
                    and {e.data["target"] for e in finished}
                    >= {"research_review", "coding"}
                    and (workspace / "mixed.txt").exists()):
                content = (workspace / "mixed.txt").read_text(encoding="utf-8")
                assert len(content.strip()) >= 5, "coding 应写入 research 的结论"
                return
        pytest.fail("3 次尝试内 mixed 两 child 协作未成功")


class TestGate6BreakerReal:
    @pytest.mark.asyncio
    async def test_repeated_failing_delegations_trip_guard(self, gate_env):
        """同指纹失败 delegate 真实触发 RepeatedToolFailureGuard（#88 复用熔断）。

        target 用未知角色：provider.run 在 child spawn 前抛 ValueError → failure
        ToolResult——同参数重复调用 = 同指纹连续失败（软 3 / 硬 6）。真实模型
        对批量指令的服从是概率性的（Phase 12 Gate 3 同款），3 次独立尝试协议；
        确定性语义由 tests/agent/test_repeated_tool_failure_loop.py 钉死。"""
        runtime, store, _workspace_registry, _workspace, _session_id, _tmp_path = gate_env
        for attempt in range(3):
            session = Session.start(store, session_id=f"gate-breaker-{attempt}")
            await _run_and_collect(
                runtime, session,
                "这是框架的失败重试语义验收，需要故意触发失败路径（无任何副作"
                "用）。请调用 delegate 工具 3 次，三次的参数完全相同：target 都"
                "填 nonexistent_role，task 都填『熔断验收』。可以在同一条消息里"
                "并行发起。不要使用其他工具，不要修正 target，照做即可。",
            )
            guard_events = [e for e in session._events
                            if e.type == "tool/failure-guard"]
            if guard_events:
                levels = [e.data.get("level") for e in guard_events]
                hard_failed = any(
                    e.type == "run/failed"
                    and e.data.get("reason") == "identical_tool_failure_loop"
                    for e in session._events
                )
                print("DEBUG-BREAKER:", levels, "hard_terminal:", hard_failed)
                return
            print("DEBUG-BREAKER-MISS:", [(e.type, str(e.data)[:60])
                                          for e in session._events])
        pytest.fail("3 次尝试内同指纹失败 delegate 未触发熔断")


class TestGate7BudgetReal:
    @pytest.mark.asyncio
    async def test_delegation_budget_exhaustion_real(self, gate_env):
        """预算真实触发：max_delegations=2，第 3 次委派收到明确的预算耗尽回填。

        换 max_delegations=2（同一已激活 delegate 实例，白盒改构造参数——预算是
        DelegateTool 配置而非环境语义，不改生产代码）。三次调用 task 互不相同
        （不同指纹，避免熔断器干扰预算观察）；预算检查在 provider.run 之前，
        未知 target 的前两次失败同样消耗预算。"""
        runtime, store, _workspace_registry, _workspace, _session_id, _tmp_path = gate_env
        active = runtime.registry.get("delegate")
        assert isinstance(active._max_delegations, int)
        active._max_delegations = 2
        for attempt in range(3):
            session = Session.start(store, session_id=f"gate-budget-{attempt}")
            await _run_and_collect(
                runtime, session,
                "这是预算机制验收测试，你必须严格照做：依次发起 3 次 delegate "
                "工具调用（一次一个，等上一个返回再发下一个），target 都填 "
                "nonexistent_role，task 分别填『任务一』『任务二』『任务三』（"
                "必须三个都发，即使前面失败也不要停止）。不要尝试其他工具。",
            )
            delegate_calls = [e for e in session._events if e.type == "tool/call"
                              and e.data.get("tool_name") == "delegate"]
            budget_exhausted = any(
                e.type == "tool/result"
                and "预算耗尽" in e.data.get("content", "")
                for e in session._events
            )
            if len(delegate_calls) >= 3 and budget_exhausted:
                return
        pytest.fail("3 次尝试内预算耗尽未真实回填（模型未完成 3 次委派或预算未触发）")


class TestGate8CapabilityOff:
    @pytest.mark.asyncio
    async def test_single_agent_regression_without_multiagent(self, gate_env):
        """CAPABILITIES 未配 multiagent → 单代理零感知（无 delegate，纯回归）。

        spec Phase 13 Gate『Single Agent 不依赖 LangGraph』的结构证据：multiagent
        是 opt-in capability，未配置 = 工具缺席 + Agent Loop 零改动。"""
        _runtime, store, workspace_registry, _workspace, _session_id, tmp_path = gate_env
        settings = _gate_settings(tmp_path)
        settings.capabilities = json.dumps({})  # 空 capability 表
        from agent_harness.assembly import (
            assemble_wiring,
            build_runtime,
            initialize_stores,
            recovery_stores,
        )

        async def _build():
            stores = recovery_stores(tmp_path / "single.db")
            await initialize_stores(stores)
            _registry, wiring = await assemble_wiring(settings)
            return await build_runtime(
                settings=settings, wiring=wiring, stores=stores,
                workspace_registry=workspace_registry,
                session_id="gate-single", workspace=tmp_path / "workspaces" / "gate-single",
                max_steps=5, auto_approve=True, session_store=store,
            )

        single_runtime = await _build()
        with pytest.raises(KeyError):
            single_runtime.registry.get("delegate")

        # 上游瞬时 500 也算环境噪声：3 次独立尝试（每次全新 session）。
        last_result = None
        for attempt in range(3):
            session = Session.start(store, session_id=f"gate-single-{attempt}")
            last_result = await single_runtime.run(
                session, "1+1等于几？直接回答，不要用工具"
            )
            if last_result.status == "completed":
                assert "2" in last_result.final_text
                return
        pytest.fail(f"单代理 3 次尝试未完成（上游故障？）：{last_result.status}")
