"""Runtime 装配单一入口（批次 A / 候选 1+4）。

build_runtime 是 web 与 CLI 共享的深 factory：一个 interface 回答
"一个 Run 被装配了什么"。此前 web/_build_runtime 内联 70 行、cli 第二套
削弱装配（无 Ledger/Checkpoint/工具）——耐久性语义分叉且测试只能按名
patch 私有符号。CapabilityWiring.aclose 把关闭知识从 web 层收拢回创建者。
"""

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessageChunk
from pydantic import BaseModel

from agent_harness.assembly import (
    RecoveryStores,
    assemble_wiring,
    build_runtime,
    initialize_stores,
    recovery_stores,
)
from agent_harness.capability.wiring import CapabilityWiring
from agent_harness.config import Settings
from agent_harness.sandbox import WorkspaceRegistry
from agent_harness.storage import OnStableBoundary
from agent_harness.tooling import Tool, ToolResult, ToolSideEffect
from agent_harness.tooling.contract import PermissionPolicy, ToolPermission
from agent_harness.tooling.reconcile import ReconcileHint


def _settings(tmp_path) -> Settings:
    return Settings(_env_file=None, workspace_dir=str(tmp_path),
                    model_api_key="sk-test")


class ScriptedModelFactory:
    """astream 可用的替身模型（factory 只需 runtime 可构造，不真正调用）。"""

    def bind_tools(self, tools, **kwargs):
        return self

    async def astream(self, messages, **kwargs):
        yield AIMessageChunk(content="ok")


class _ProbeArgs(BaseModel):
    text: str = ""


class ProbeCapabilityTool(Tool):
    """capability 贡献的工具替身（进统一 ToolRegistry 验证零旁路）。"""

    @property
    def name(self) -> str:
        return "capability_probe"

    @property
    def description(self) -> str:
        return "probe"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _ProbeArgs

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.READ_ONLY

    @property
    def permission(self) -> ToolPermission:
        return ToolPermission.READ_ONLY

    @property
    def timeout_seconds(self) -> float:
        return 5.0

    @property
    def reconcile_hint(self) -> ReconcileHint:
        return ReconcileHint(verifiable=False)

    async def execute(self, args: BaseModel) -> ToolResult:
        return ToolResult.success("probe")


def _stores(tmp_path) -> RecoveryStores:
    return recovery_stores(tmp_path / "harness.db")


@pytest.mark.asyncio
async def test_build_runtime_wires_full_stack(tmp_path):
    """factory 产出与旧 web._build_runtime 等价的全栈接线：coding 工具 +
    Ledger + Checkpoint + SessionMeta + workspace 映射 + 审批直通。"""
    settings = _settings(tmp_path)
    _, wiring = await assemble_wiring(settings)
    stores = _stores(tmp_path)
    await initialize_stores(stores)
    workspace_registry = WorkspaceRegistry(root=tmp_path, backend="local")

    with patch("agent_harness.assembly.create_chat_model",
               return_value=ScriptedModelFactory()):
        runtime = await build_runtime(
            settings=settings, wiring=wiring, stores=stores,
            workspace_registry=workspace_registry,
            session_id="sess-assembly",
            workspace=tmp_path / "workspaces" / "sess-assembly",
            max_steps=10,
            permission_mode=PermissionPolicy.WORKSPACE_WRITE,
        )

    # coding 工具在册（CLI 不再是削弱装配——与 web 同一 stack）
    assert "bash" in [tool.name for tool in runtime.registry.list()]
    # Ledger / Meta 是传入实例（不变量 #13：统一记账）；Checkpoint 策略挂 store
    assert runtime.executor._operation_ledger is stores.operation_ledger
    assert runtime._session_meta_store is stores.session_meta_store
    assert isinstance(runtime._checkpoint_policy, OnStableBoundary)
    assert runtime._checkpoint_policy._store is stores.checkpoint_store
    # workspace 映射持久化：恢复时可还原 sandbox
    assert workspace_registry.exists("sess-assembly")
    # 无 approval_callback 注入 → assembly 默认 auto-approve callback
    assert runtime.executor._approval_callback is not None


@pytest.mark.asyncio
async def test_build_runtime_wires_capability_tools_and_manual_approval(tmp_path):
    """wiring.tools 进 ToolRegistry（统一 Executor 路径，不变量 #7）、
    wiring.context_providers 进 ContextBuilder；manual 模式危险操作默认拒绝。"""
    settings = _settings(tmp_path)
    provider_sentinel = object()
    wiring = CapabilityWiring(context_providers=[provider_sentinel],
                              tools=[ProbeCapabilityTool()])
    stores = _stores(tmp_path)
    await initialize_stores(stores)

    # manual 模式：注入 deny callback（旧 auto_approve=false 行为由调用方构造）
    async def _deny(_req):
        from agent_harness.tooling.approval import ApprovalResponse
        return ApprovalResponse(approved=False, reason="manual approval not yet wired")

    with patch("agent_harness.assembly.create_chat_model",
               return_value=ScriptedModelFactory()):
        runtime = await build_runtime(
            settings=settings, wiring=wiring, stores=stores,
            workspace_registry=WorkspaceRegistry(root=tmp_path, backend="local"),
            session_id="s", workspace=tmp_path / "w",
            max_steps=5,
            permission_mode=PermissionPolicy.WORKSPACE_WRITE,
            approval_callback=_deny,
        )

    assert "capability_probe" in [tool.name for tool in runtime.registry.list()]
    assert runtime._context_builder.context_providers == [provider_sentinel]
    response = await runtime.executor._approval_callback(object())
    assert response.approved is False


@pytest.mark.asyncio
async def test_build_runtime_wires_model_fallback(tmp_path):
    """Model Fallback 装配（T5, #80, ADR-0014 决策 14/16）：config.fallback
    存在 → 两级模型入 Runtime；未配 → fallback 保持 None（单级）。"""
    _, wiring = await assemble_wiring(_settings(tmp_path))
    stores = _stores(tmp_path)
    await initialize_stores(stores)
    created = []

    def fake_create(config, *, reasoning_effort=None, **kw):
        model = ScriptedModelFactory()
        created.append((config, model))
        return model

    # 未配 fallback：单级
    with patch("agent_harness.assembly.create_chat_model", side_effect=fake_create):
        runtime = await build_runtime(
            settings=_settings(tmp_path), wiring=wiring, stores=stores,
            workspace_registry=WorkspaceRegistry(root=tmp_path, backend="local"),
            session_id="s1", workspace=tmp_path / "w1",
            max_steps=5,
            permission_mode=PermissionPolicy.WORKSPACE_WRITE,
        )
    assert runtime._fallback_model is None
    assert runtime._primary_model_name == "deepseek-chat"

    created.clear()
    fb_settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path), model_api_key="sk-test",
        fallback_model_provider="senseaudio",
        fallback_model_name="deepseek-v4-flash-0731",
        fallback_model_api_key="sk-fb",
    )
    with patch("agent_harness.assembly.create_chat_model", side_effect=fake_create):
        runtime = await build_runtime(
            settings=fb_settings, wiring=wiring, stores=stores,
            workspace_registry=WorkspaceRegistry(root=tmp_path, backend="local"),
            session_id="s2", workspace=tmp_path / "w2",
            max_steps=5,
            permission_mode=PermissionPolicy.WORKSPACE_WRITE,
        )
    # 两次构造：第 1 次 primary、第 2 次 fallback；配置链一致
    assert len(created) == 2
    primary_config, _ = created[0]
    fallback_config, _ = created[1]
    assert primary_config.provider == "deepseek"
    assert fallback_config is primary_config.fallback
    assert fallback_config.provider == "senseaudio"
    assert runtime._fallback_model is not None
    assert runtime._fallback_model is not runtime.model
    assert runtime._fallback_model_name == "deepseek-v4-flash-0731"
    assert runtime._primary_model_name == "deepseek-chat"


@pytest.mark.asyncio
async def test_assemble_wiring_empty_config_is_inert(tmp_path):
    """CAPABILITIES 为空 → 零工具、零 provider、零生命周期对象（默认 opt-in）。"""
    _, wiring = await assemble_wiring(_settings(tmp_path))
    assert wiring.tools == []
    assert wiring.context_providers == []
    assert wiring.lifecycle == []
    assert wiring.memory is None
    assert wiring.memory_writer is None


@pytest.mark.asyncio
async def test_initialize_stores_is_idempotent(tmp_path):
    stores = recovery_stores(tmp_path / "harness.db")
    await initialize_stores(stores)
    await initialize_stores(stores)  # 二次调用不得抛错（幂等）


def test_recovery_stores_bundle_holds_three_stores(tmp_path: Path):
    stores = recovery_stores(tmp_path / "harness.db")
    assert stores.operation_ledger is not None
    assert stores.checkpoint_store is not None
    assert stores.session_meta_store is not None


# ── #192：artifact 外置写入必须与"写得出/读得回"成对 ──────────────────────


async def _runtime_with(tmp_path, settings: Settings, session_id: str = "sess-art"):
    """按给定 settings 装配 runtime（替身模型，不发起真实调用）。"""
    _, wiring = await assemble_wiring(settings)
    stores = _stores(tmp_path)
    await initialize_stores(stores)
    with patch("agent_harness.assembly.create_chat_model",
               return_value=ScriptedModelFactory()):
        return await build_runtime(
            settings=settings, wiring=wiring, stores=stores,
            workspace_registry=WorkspaceRegistry(root=tmp_path, backend="local"),
            session_id=session_id,
            workspace=tmp_path / "workspaces" / session_id,
            max_steps=10,
            permission_mode=PermissionPolicy.WORKSPACE_WRITE,
        )


def _tool_names(runtime) -> set[str]:
    return {tool.name for tool in runtime.registry.list()}


def _marker(handler) -> str:
    """从溢出摘要里取出读回提示点名的工具名（#186 AC4：前端按同一段文字提取 id）。

    直接驱动摘要生成而不是读私有属性：这条要守的是**那段文字**，不是手里那个字段。
    """
    summary = handler._summarize("\n".join(f"line {i}" for i in range(50)), "0" * 16)
    match = re.search(r"use (\w+)\(", summary)
    assert match is not None, f"摘要里没有读回提示：{summary!r}"
    return match.group(1)


@pytest.mark.asyncio
async def test_local_store_is_the_default_externalizer(tmp_path):
    """什么都没配 → Local 兜底：既**写得出**（有 overflow handler），也**读得回**
    （read_artifact 在册）。#192 之前这两件事都不成立——未配对象存储的部署
    既不外置，也没有可读的 store。"""
    from agent_harness.storage.local_artifact import LocalArtifactStore
    from agent_harness.tooling.overflow import ArtifactOverflowHandler

    settings = Settings(_env_file=None, workspace_dir=str(tmp_path),
                        model_api_key="sk-test",
                        artifact_dir=str(tmp_path / "artifacts"))
    runtime = await _runtime_with(tmp_path, settings)

    handler = runtime.executor._overflow_handler
    assert isinstance(handler, ArtifactOverflowHandler)
    assert isinstance(handler._store, LocalArtifactStore)
    assert "read_artifact" in _tool_names(runtime)
    # #186 AC4：摘要里的读回提示必须点名**这个部署真的注册了**的那个工具。
    # 前端按同一段文字提取 artifact_id，名字错了 UI 就永远看不到归档内容。
    assert _marker(handler) == "read_artifact"


@pytest.mark.asyncio
async def test_minio_config_gets_a_writer_too(tmp_path, monkeypatch):
    """配了 minio_* → 读工具与写入者都到位（#192 修的半截接线）。

    此前该分支只注册 `ReadArtifactTool`：模型有个读不存在的产物的工具，
    而没有任何东西会把产物写进去——与 `config.py` "MinIO 用于 tool result 外置"
    的注释直接矛盾。
    """
    from agent_harness.storage.minio_artifact import MinioArtifactStore
    from agent_harness.tooling.overflow import ArtifactOverflowHandler

    monkeypatch.setattr(
        MinioArtifactStore, "__init__", lambda self, settings, *, session_id: None
    )
    settings = Settings(_env_file=None, workspace_dir=str(tmp_path),
                        model_api_key="sk-test",
                        minio_endpoint="https://minio.invalid",
                        minio_bucket="b", minio_access_key="k", minio_secret_key="s")
    runtime = await _runtime_with(tmp_path, settings)

    handler = runtime.executor._overflow_handler
    assert isinstance(handler, ArtifactOverflowHandler)
    assert isinstance(handler._store, MinioArtifactStore)
    assert "read_artifact" in _tool_names(runtime)
    assert _marker(handler) == "read_artifact"


@pytest.mark.asyncio
async def test_missing_artifact_extra_does_not_break_session_creation(tmp_path, monkeypatch):
    """配了对象存储但**没装 `[artifact]` extra** ⇒ 建会话照常成功（不变量 21）。

    构造 store 时抛的是 `RuntimeError`（可选依赖缺失），不是 `ValueError`。选择器此前
    只兜 `ValueError`，于是它沿 `build_runtime` 冒到建会话 → 每次建会话 500。一个**可选
    的外置优化**把 Core 拖垮，正是这条不变量要防的事，也是选择器存在的理由之一。
    """
    from agent_harness.storage.s3_artifact import S3ArtifactStore

    def _boom(self, settings, *, session_id=None):
        raise RuntimeError("S3ArtifactStore requires pip install 'intelligence-agent[artifact]'")

    monkeypatch.setattr(S3ArtifactStore, "__init__", _boom)
    settings = Settings(_env_file=None, workspace_dir=str(tmp_path),
                        model_api_key="sk-test",
                        artifact_dir=str(tmp_path / "artifacts"),
                        artifact_store_endpoint="https://s3.invalid",
                        artifact_store_bucket="b",
                        artifact_store_access_key="k", artifact_store_secret_key="s")
    runtime = await _runtime_with(tmp_path, settings)

    # 没有写入者（不外置），但 runtime 建起来了、核心工具在册
    assert runtime.executor._overflow_handler is None
    assert "bash" in _tool_names(runtime)
    assert "inspect_artifact" not in _tool_names(runtime)


@pytest.mark.asyncio
async def test_blank_artifact_dir_disables_local_externalization_without_breaking_session(tmp_path):
    """`artifact_dir` 置空 = 显式关掉本地外置：**建会话必须照常成功**（fail-open）。

    外置是大输出的优化，不是 Core 的必需品（不变量 21）。这里没有写入者，
    与 #192 之前"未配存储"的行为一致；若把"关掉"实现成构造期抛错，
    一个可选优化就会让所有会话建不起来。
    """
    settings = Settings(_env_file=None, workspace_dir=str(tmp_path),
                        model_api_key="sk-test", artifact_dir="")
    runtime = await _runtime_with(tmp_path, settings)

    assert runtime.executor._overflow_handler is None
    assert "read_artifact" not in _tool_names(runtime)
    # 核心工具仍在册——关掉外置不影响任何 coding 能力
    assert "bash" in _tool_names(runtime)


@pytest.mark.asyncio
async def test_s3_config_still_wins_over_local(tmp_path, monkeypatch):
    """S3 配置在场时不被 Local 抢走（显式配置优先）；且 S3 分支仍用 inspect_artifact。"""
    from agent_harness.storage.s3_artifact import S3ArtifactStore
    from agent_harness.tooling.overflow import ArtifactOverflowHandler

    monkeypatch.setattr(
        S3ArtifactStore, "__init__", lambda self, settings, *, session_id=None: None
    )
    settings = Settings(_env_file=None, workspace_dir=str(tmp_path),
                        model_api_key="sk-test",
                        artifact_dir=str(tmp_path / "artifacts"),
                        artifact_store_endpoint="https://s3.invalid",
                        artifact_store_bucket="b",
                        artifact_store_access_key="k", artifact_store_secret_key="s")
    runtime = await _runtime_with(tmp_path, settings)

    handler = runtime.executor._overflow_handler
    assert isinstance(handler, ArtifactOverflowHandler)
    assert isinstance(handler._store, S3ArtifactStore)
    assert "inspect_artifact" in _tool_names(runtime)
    # #186 AC4 的回归守卫：marker 曾写死 `read_artifact`，而 S3 部署注册的是
    # `inspect_artifact` ⇒ 提示把模型指向一个没注册的工具名，前端也提取不到 id。
    assert _marker(handler) == "inspect_artifact"
