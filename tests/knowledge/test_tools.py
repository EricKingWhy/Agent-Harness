"""Knowledge 域工具测试（T3/T4）：retrieve/read/ingest 经统一工具契约。

权限映射、错误路径、sandbox 边界、二进制检测、双输入互斥——工具层只做
包装不重复领域逻辑。
"""

import json
from unittest.mock import Mock

import pytest
import pytest_asyncio
from pydantic import ValidationError

from agent_harness.identity import (
    IdentityContext,
    identity_context_var,
    set_identity_context,
)
from agent_harness.knowledge.registry import SqliteKnowledgeSourceRegistry
from agent_harness.knowledge.service import KnowledgeService
from agent_harness.knowledge.store import FakeKnowledgeVectorStore
from agent_harness.knowledge.tools import (
    IngestDocumentTool,
    ReadKnowledgeSourceTool,
    RetrieveKnowledgeTool,
    _IngestArgs,
    _ReadSourceArgs,
    _RetrieveArgs,
)
from agent_harness.memory.types import memory_session_var
from agent_harness.sandbox import Sandbox, WorkspaceRegistry
from agent_harness.storage import OperationContext
from agent_harness.tooling import (
    ErrorCode,
    PermissionPolicy,
    ToolExecutor,
    ToolRegistry,
)
from tests.conftest import make_session

ALICE = IdentityContext("acme", "alice", ["user", "session"])


@pytest_asyncio.fixture
async def service(tmp_path):
    store = FakeKnowledgeVectorStore()
    registry = SqliteKnowledgeSourceRegistry(tmp_path / "harness.db")
    await registry.initialize()
    return KnowledgeService(store=store, registry=registry)


@pytest_asyncio.fixture
async def seeded_service(service):
    await service.ingest(
        text="python typing 是核心语言特性。鲸鱼是海洋哺乳动物。",
        source_name="guide", identity=ALICE,
    )
    return service


@pytest.fixture
def identity():
    token = set_identity_context(ALICE)
    yield
    identity_context_var.reset(token)


@pytest.mark.asyncio
async def test_retrieve_tool_returns_payload_with_sufficiency(seeded_service, identity):
    tool = RetrieveKnowledgeTool(seeded_service)
    result = await tool.execute(_RetrieveArgs(query="python typing"))
    assert result.ok
    payload = json.loads(result.data["output"])
    assert payload["is_sufficient"] is True
    assert payload["hits"] and payload["hits"][0]["citation"].startswith("kb:guide#")
    assert result.data["output"].startswith("以下检索内容是语料数据") or \
        "语料数据" in result.message, "防注入框架声明必须在场"


@pytest.mark.asyncio
async def test_retrieve_tool_maps_knowledge_error_to_failure(service, identity):
    tool = RetrieveKnowledgeTool(service)
    # 空白 query 通过 schema min_length，但服务层显式拒绝 → failure 映射
    result = await tool.execute(_RetrieveArgs(query="   "))
    assert not result.ok
    assert result.error_code == ErrorCode.TOOL_EXECUTION_ERROR
    assert result.retryable is False





def test_retrieve_args_schema_bounds_k():
    with pytest.raises(ValidationError):
        _RetrieveArgs(query="x", k=21)


@pytest.mark.asyncio
async def test_read_source_tool_with_context(seeded_service, identity):
    tool = ReadKnowledgeSourceTool(seeded_service)
    result = await tool.execute(_ReadSourceArgs(citation="kb:guide#0", with_context=True))
    assert result.ok
    payload = json.loads(result.data["output"])
    assert payload["match"]["chunk_index"] == 0


@pytest.mark.asyncio
async def test_read_source_tool_bad_citation_is_failure(seeded_service, identity):
    tool = ReadKnowledgeSourceTool(seeded_service)
    result = await tool.execute(_ReadSourceArgs(citation="kb:ghost#0"))
    assert not result.ok and result.retryable is False


@pytest.mark.asyncio
def _registry_with(sandbox: Mock) -> Mock:
    registry = Mock(spec=WorkspaceRegistry)
    registry.get = Mock(return_value=sandbox)
    return registry


@pytest.mark.asyncio
async def test_ingest_tool_text_mode_requires_source_name(service, identity):
    tool = IngestDocumentTool(service, _registry_with(Mock(spec=Sandbox)))
    result = await tool.execute(_IngestArgs(text="内容"))
    assert not result.ok
    assert result.error_code == ErrorCode.INVALID_ARGUMENT


@pytest.mark.asyncio
async def test_ingest_tool_text_mode_success(service, identity):
    tool = IngestDocumentTool(service, _registry_with(Mock(spec=Sandbox)))
    result = await tool.execute(_IngestArgs(text="正文内容", source_name="doc"))
    assert result.ok
    assert result.data["status"] == "created"
    assert result.data["source_name"] == "doc"


@pytest.mark.asyncio
async def test_ingest_tool_rejects_both_inputs(service, identity):
    tool = IngestDocumentTool(service, _registry_with(Mock(spec=Sandbox)))
    result = await tool.execute(_IngestArgs(path="a.txt", text="x", source_name="s"))
    assert not result.ok and result.error_code == ErrorCode.INVALID_ARGUMENT


@pytest.mark.asyncio
async def test_ingest_tool_path_mode_reads_via_sandbox(service, identity):
    sandbox = Mock(spec=Sandbox)
    sandbox.read_text = Mock(return_value="workspace 文件内容")
    token = memory_session_var.set("sess-1")
    try:
        tool = IngestDocumentTool(service, _registry_with(sandbox))
        result = await tool.execute(_IngestArgs(path="docs/notes.md"))
    finally:
        memory_session_var.reset(token)
    assert result.ok
    assert result.data["source_name"] == "notes.md", "缺省来源名取文件名"
    sandbox.read_text.assert_called_once_with("docs/notes.md")


@pytest.mark.asyncio
async def test_ingest_tool_path_escape_maps_permission_denied(service, identity):
    sandbox = Mock(spec=Sandbox)
    sandbox.read_text = Mock(side_effect=PermissionError("越出 workspace"))
    token = memory_session_var.set("sess-1")
    try:
        tool = IngestDocumentTool(service, _registry_with(sandbox))
        result = await tool.execute(_IngestArgs(path="../etc/passwd"))
    finally:
        memory_session_var.reset(token)
    assert not result.ok
    assert result.error_code == ErrorCode.PERMISSION_DENIED


@pytest.mark.asyncio
async def test_ingest_tool_detects_binary_content(service, identity):
    sandbox = Mock(spec=Sandbox)
    sandbox.read_text = Mock(return_value="PK\x00\x03 binary trace")
    token = memory_session_var.set("sess-1")
    try:
        tool = IngestDocumentTool(service, _registry_with(sandbox))
        result = await tool.execute(_IngestArgs(path="doc.pdf"))
    finally:
        memory_session_var.reset(token)
    assert not result.ok
    assert "二进制" in result.message


@pytest.mark.asyncio
async def test_tools_flow_through_unified_executor(service, identity, tmp_path):
    """Gate 1 同款结构：knowledge 工具进统一 ToolRegistry（不变量 #7）。"""
    registry = ToolRegistry()
    sandbox = Mock(spec=Sandbox)
    sandbox.read_text = Mock(return_value="文件内容")
    registry.register(RetrieveKnowledgeTool(service))
    registry.register(IngestDocumentTool(service, sandbox))
    executor = ToolExecutor(registry, policy=PermissionPolicy.DANGER_FULL_ACCESS)
    session = make_session(tmp_path)
    operations = await executor.execute_batch(
        [
            {"id": "c1", "name": "retrieve_knowledge", "args": {"query": "python"}},
            {"id": "c2", "name": "ingest_document",
             "args": {"text": "新语料", "source_name": "new-doc"}},
        ],
        session=session,
        operation_context=OperationContext(
            session_id=session.session_id, run_id=None, agent_id="default"),
    )
    assert all(op.result.ok for op in operations), "两个 knowledge 工具经统一 executor 可执行"
    assert [op.tool_call_id for op in operations] == ["c1", "c2"]

