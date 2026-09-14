"""Knowledge Capability 接线测试（T5，ADR-0013 决策 13 + Phase 8 模式）。

MilvusKnowledgeVectorStore 打桩（config→连接是唯一注入缝）；验证：
- 配置齐全 → 三工具进统一 registry（不变量 #7）、向量 client 挂 lifecycle
- KNOWLEDGE_COLLECTION 未配置 → OPTIONAL_RUNTIME 降级缺席（警告可观察）
- store 初始化失败（环境故障）→ 降级缺席
"""

import json
from typing import ClassVar

import pytest

from agent_harness.capability.base import CapabilityRegistry
from agent_harness.capability.config import parse_capabilities_config
from agent_harness.capability.wiring import wire_capabilities
from agent_harness.config import Settings
from agent_harness.sandbox import WorkspaceRegistry


class StubKnowledgeStore:
    """连接替身：默认健康；记录 aclose（lifecycle 通道验证）。"""

    instances: ClassVar[list["StubKnowledgeStore"]] = []
    fail_initialize: ClassVar[bool] = False

    def __init__(self, settings, embeddings=None):
        self.settings = settings
        self.closed = False
        StubKnowledgeStore.instances.append(self)

    async def initialize(self) -> None:
        if StubKnowledgeStore.fail_initialize:
            raise RuntimeError("milvus unreachable")

    async def aclose(self) -> None:
        self.closed = True

    async def upsert_chunks(self, chunks, identity) -> None:
        return None

    async def delete_source(self, source_id: str, identity) -> int:
        return 0

    async def search(self, query, identity, *, limit, source_id=None):
        return []

    async def get_chunk(self, source_id: str, chunk_index: int, identity):
        return None


@pytest.fixture()
def stub_store(monkeypatch):
    StubKnowledgeStore.instances = []
    StubKnowledgeStore.fail_initialize = False
    monkeypatch.setattr(
        "agent_harness.knowledge.milvus_store.MilvusKnowledgeVectorStore",
        StubKnowledgeStore,
    )
    return StubKnowledgeStore


def _settings(tmp_path, *, knowledge_collection="knowledge-test") -> Settings:
    return Settings(
        _env_file=None, workspace_dir=str(tmp_path), model_api_key="sk-test",
        milvus_uri="https://example.test", milvus_token="test-only",
        knowledge_collection=knowledge_collection,
        capabilities=json.dumps({
            "knowledge": {"provider": "builtin", "enabled": True, "options": {}},
        }),
    )


async def _wire(settings: Settings):
    registry = CapabilityRegistry()
    return await wire_capabilities(
        registry, parse_capabilities_config(settings.capabilities),
        settings=settings,
    )


@pytest.mark.asyncio
async def test_knowledge_wiring_registers_three_tools(tmp_path, stub_store):
    wiring = await _wire(_settings(tmp_path))
    names = sorted(tool.name for tool in wiring.tools)
    assert names == ["ingest_document", "read_knowledge_source", "retrieve_knowledge"]
    assert wiring.lifecycle, "向量 client 必须挂 lifecycle（shutdown 可关）"
    await wiring.lifecycle[0].aclose()
    assert stub_store.instances[0].closed


@pytest.mark.asyncio
async def test_knowledge_absent_when_collection_unconfigured(tmp_path, stub_store, caplog):
    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path), model_api_key="sk-test",
        capabilities=json.dumps({
            "knowledge": {"provider": "builtin", "enabled": True, "options": {}},
        }),
    )
    wiring = await _wire(settings)
    assert wiring.tools == []
    assert not stub_store.instances, "未配置 collection 时不得构造 store"
    assert any("KNOWLEDGE_COLLECTION" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_knowledge_degrades_when_store_init_fails(tmp_path, stub_store):
    StubKnowledgeStore.fail_initialize = True
    wiring = await _wire(_settings(tmp_path))
    assert wiring.tools == [], "环境故障按 OPTIONAL_RUNTIME 降级缺席"
    assert wiring.lifecycle == [], "初始化失败不得把半成品挂进 lifecycle"


# ── Gate 1 同款结构测试：knowledge 工具经统一 runtime（Ledger + 事件镜像）──


@pytest.mark.asyncio
async def test_knowledge_ingest_tool_through_unified_runtime(tmp_path, stub_store, monkeypatch):
    """knowledge 工具与 coding/MCP 工具同一条执行链：Ledger 记账 +
    SessionEvent 镜像（不变量 #7 的 Phase 11 落地证据）。"""
    from langchain_core.messages import AIMessage

    from agent_harness.agent import AgentRuntime
    from agent_harness.memory.types import memory_session_var
    from agent_harness.storage import OperationState, SqliteOperationLedger
    from agent_harness.tooling import ToolExecutor, ToolRegistry
    from tests.conftest import make_session
    from tests.scripted_model import ScriptedModel

    settings = _settings(tmp_path)
    wiring = await _wire(settings)
    ledger = SqliteOperationLedger(tmp_path / "ledger.db")
    await ledger.initialize()

    tool_registry = ToolRegistry()
    for tool in wiring.tools:
        tool_registry.register(tool)
    runtime = AgentRuntime(
        ScriptedModel([
            AIMessage(content="", tool_calls=[{
                "name": "ingest_document",
                "args": {"text": "语料正文", "source_name": "gate-doc"},
                "id": "call-1", "type": "tool_call",
            }]),
            AIMessage(content="已入库。"),
        ]),
        tool_registry,
        ToolExecutor(tool_registry, operation_ledger=ledger),
    )
    session = make_session(tmp_path / "sessions")
    workspace_registry = WorkspaceRegistry(root=tmp_path)
    workspace_registry.create(session.session_id, workspace_root=tmp_path / "ws")

    token = memory_session_var.set(session.session_id)
    try:
        result = await runtime.run(session, "把这份文档收进语料库")
    finally:
        memory_session_var.reset(token)

    assert result.status == "completed"
    types = [e.type for e in session.events]
    assert "tool/call" in types and "tool/result" in types
    tool_calls = [e for e in session.events if e.type == "tool/call"]
    assert tool_calls[0].data["tool_name"] == "ingest_document"
    operation = await ledger.get(session.session_id, "call-1")
    assert operation.state == OperationState.SUCCEEDED
