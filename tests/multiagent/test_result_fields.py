"""SubAgentResult 完整字段收集（Phase 13 T4, #85, ADR-0015 决策 12）。

「绝不伪造」：每个字段都有真实来源——
- citations：child tool/result（retrieve_knowledge / web_search）payload 里的命中；
- artifacts：child 的 artifact/created 事件；
- changed_files：child tool/call（write/edit/apply_patch）的 path 参数推导；
- unresolved：child 最终回答的「未解决」自报段（轻解析，缺失 = 空数组）。
无来源的字段省略而非补零。tests 字段 DEFER。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from agent_harness.agent.factory import AgentFactory
from agent_harness.multiagent.provider import (
    InProcessSubagentProvider,
    collect_result_fields,
)
from agent_harness.multiagent.tools import DelegateTool
from agent_harness.sandbox import WorkspaceRegistry
from agent_harness.session.store import JsonlSessionStore
from agent_harness.tooling import ToolRegistry
from tests.scripted_model import ScriptedModel


def _ev(seq: int, etype: str, data: dict) -> object:
    from agent_harness.session.event import SessionEvent

    return SessionEvent(seq=seq, type=etype, session_id="s",
                        time="2026-09-06T00:00:00", data=data)


def _tool_call(seq: int, call_id: str, name: str, args: dict) -> object:
    return _ev(seq, "tool/call", {"tool_call_id": call_id, "tool_name": name,
                                  "args": args})


def _tool_result(seq: int, call_id: str, tool_name: str, payload: dict) -> object:
    content = json.dumps({"ok": True, "message": "m", "data": {"output": json.dumps(payload, ensure_ascii=False)}}, ensure_ascii=False)
    return _ev(seq, "tool/result", {"tool_call_id": call_id, "content": content,
                                    "tool_name": tool_name})


class TestCollectResultFields:
    def test_citations_from_retrieve_and_web_results(self):
        events = [
            _tool_call(1, "c1", "retrieve_knowledge", {"query": "q"}),
            _tool_result(2, "c1", "retrieve_knowledge", {
                "hits": [{"citation": "kb:doc#0", "content": "x", "score": 0.9}],
                "is_sufficient": True,
            }),
            _tool_call(3, "c2", "web_search", {"query": "w"}),
            _tool_result(4, "c2", "web_search", {
                "hits": [{"citation": "web:https://a", "content": "y", "score": 0.8}],
            }),
        ]
        fields = collect_result_fields(events)
        assert fields["citations"] == ["kb:doc#0", "web:https://a"]

    def test_changed_files_from_write_tools(self):
        events = [
            _tool_call(1, "c1", "write", {"path": "src/a.py", "content": "x"}),
            _tool_call(2, "c2", "edit", {"path": "src/a.py"}),
            _tool_call(3, "c3", "apply_patch", {"patch": "*** a.py"}),
            _tool_call(4, "c4", "bash", {"command": "ls"}),
        ]
        fields = collect_result_fields(events)
        assert fields["changed_files"] == ["src/a.py"]  # 去重；bash 不计
        # apply_patch 的路径在 patch 文本里（V1 从 path 参数推导，patch 文本不解析）

    def test_artifacts_from_events(self):
        events = [
            _ev(1, "artifact/created", {"artifact_id": "art-1", "path": "big.txt"}),
        ]
        fields = collect_result_fields(events)
        assert fields["artifacts"] == ["art-1"]

    def test_unresolved_section_parsed(self):
        summary = (
            "完成了主要工作。\n\n未解决事项：\n- 性能未验证\n- 边界情况待确认\n"
        )
        fields = collect_result_fields([], summary=summary)
        assert fields["unresolved"] == ["性能未验证", "边界情况待确认"]

    def test_no_unresolved_section_is_empty(self):
        fields = collect_result_fields([], summary="一切顺利")
        assert fields["unresolved"] == []

    def test_empty_sources_omit_fields(self):
        fields = collect_result_fields([], summary="done")
        assert "citations" not in fields
        assert "artifacts" not in fields
        assert "changed_files" not in fields


class TestResultFieldsEndToEnd:
    @pytest.mark.asyncio
    async def test_changed_files_flow_through_delegate(self, tmp_path):
        from pydantic import BaseModel as _BM

        class _WriteArgs(_BM):
            path: str = ""
            content: str = ""

        from agent_harness.tooling import Tool, ToolPermission, ToolSideEffect
        from agent_harness.tooling.reconcile import ReconcileHint

        class _WriteTool(Tool):
            @property
            def name(self) -> str:
                return "write"

            @property
            def description(self) -> str:
                return "write"

            @property
            def args_schema(self) -> type:
                return _WriteArgs

            @property
            def side_effect(self) -> ToolSideEffect:
                return ToolSideEffect.MUTATING

            @property
            def permission(self) -> ToolPermission:
                return ToolPermission.WORKSPACE_WRITE

            @property
            def timeout_seconds(self) -> float:
                return 10.0

            @property
            def reconcile_hint(self) -> ReconcileHint:
                return ReconcileHint(verifiable=True)

            async def execute(self, args: _WriteArgs):
                from agent_harness.tooling import ToolResult

                return ToolResult.success(message="written")

        store = JsonlSessionStore(tmp_path / "sessions")
        workspace_registry = WorkspaceRegistry(root=tmp_path / "workspaces")
        workspace_registry.create("p1", workspace_root=tmp_path / "ws")
        provider = InProcessSubagentProvider()
        tool = DelegateTool(provider)
        source_registry = ToolRegistry()
        source_registry.register(_WriteTool())
        source_registry.register(tool)


        child_model = ScriptedModel([
            AIMessage(content="", tool_calls=[{
                "id": "call_0001", "name": "write",
                "args": {"path": "src/new.py", "content": "x=1"},
            }]),
            AIMessage(content="写完了。"),
        ])
        provider.activate(
            factory=AgentFactory(model=child_model, primary_model_name="m"),
            source_registry=source_registry,
            session_store=store, workspace_registry=workspace_registry,
            parent_session_id="p1",
        )

        result = await tool.execute(type("_A", (), {
            "target": "coding", "task": "写文件", "constraints": [],
        })())

        payload = json.loads(result.data["output"])
        assert payload["changed_files"] == ["src/new.py"]


class TestSummaryOverflow:
    """#86：大产物治理——store 已配 = 全文交父侧 artifact 管线；
    未配 = 截断 + child session 指针（不丢数据：全文在 child JSONL）。"""

    def _tool(self, tmp_path: Path, summary: str, overflow_configured: bool):
        store = JsonlSessionStore(tmp_path / "sessions")
        workspace_registry = WorkspaceRegistry(root=tmp_path / "workspaces")
        workspace_registry.create("p1", workspace_root=tmp_path / "ws")
        provider = InProcessSubagentProvider()
        tool = DelegateTool(provider)
        source_registry = ToolRegistry()
        source_registry.register(tool)
        provider.activate(
            factory=AgentFactory(
                model=ScriptedModel([AIMessage(content=summary)]),
                primary_model_name="m",
            ),
            source_registry=source_registry,
            session_store=store, workspace_registry=workspace_registry,
            parent_session_id="p1",
            summary_limit=200,
            overflow_configured=overflow_configured,
        )
        return tool, provider

    @pytest.mark.asyncio
    async def test_no_store_truncates_with_child_pointer(self, tmp_path):
        tool, provider = self._tool(tmp_path, "长" * 500, overflow_configured=False)
        result = await tool.execute(type("_A", (), {
            "target": "coding", "task": "x", "constraints": [],
        })())
        payload = json.loads(result.data["output"])
        assert len(payload["summary"]) < 500, "未配 store：截断控制上下文成本"
        assert "child session" in payload["summary"] or \
            payload["summary"].endswith("…"), "截断必须带指向信息"
        # 全文在 child JSONL（不丢数据）
        child = provider.last_child_sessions[-1]
        full = next(e for e in child._events if e.type == "run/completed")
        assert "长" * 100 in (full.data.get("final_text") or "")

    @pytest.mark.asyncio
    async def test_store_configured_passes_full_to_artifact_pipeline(self, tmp_path):
        """store 已配：provider 不截断——全文交父侧 overflow handler 落 artifact
        （tool result 携带 artifact_ref，supervisor 按需读）。"""
        tool, _ = self._tool(tmp_path, "长" * 500, overflow_configured=True)
        result = await tool.execute(type("_A", (), {
            "target": "coding", "task": "x", "constraints": [],
        })())
        payload = json.loads(result.data["output"])
        assert len(payload["summary"]) == 500, "全文交由父侧 artifact 管线"

    @pytest.mark.asyncio
    async def test_small_summary_untouched(self, tmp_path):
        tool, _ = self._tool(tmp_path, "短摘要", overflow_configured=False)
        result = await tool.execute(type("_A", (), {
            "target": "coding", "task": "x", "constraints": [],
        })())
        payload = json.loads(result.data["output"])
        assert payload["summary"] == "短摘要"
