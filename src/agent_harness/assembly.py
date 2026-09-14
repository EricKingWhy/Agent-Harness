"""Runtime 装配的单一入口（批次 A / 架构候选 1+4）。

"一个 Run 被装配了什么"此前没有单一答案：web/_build_runtime 内联 70 行、
cli 第二套削弱装配（无 Ledger/Checkpoint/工具）——耐久性语义分叉，且测试
只能按名 patch 私有符号。本 module 是 web 与 CLI 共享的深 factory：
- initialize_stores：恢复三 Store（Ledger / Checkpoint / SessionMeta）幂等初始化
- assemble_wiring：CAPABILITIES env → CapabilityWiring（工具/provider/生命周期）
- build_runtime：model + coding 工具 + capability 工具 + artifact 溢出 +
  Executor(Ledger/审批) + Checkpoint 策略 + ContextBuilder —— 全栈接线一处可读

web 与 CLI 是它的两个 adapter（两个 adapter = 真实 seam）；capability 的
发现与降级仍归 wire_capabilities（ADR-0010 不动），本层只消费其产物。
"""

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from agent_harness.agent import AgentRuntime

logger = logging.getLogger(__name__)
from agent_harness.capability.base import CapabilityRegistry
from agent_harness.capability.config import parse_capabilities_config
from agent_harness.capability.wiring import CapabilityWiring, wire_capabilities
from agent_harness.config import Settings
from agent_harness.context.builder import ContextBuilder
from agent_harness.model.concurrency import ModelCallGate
from agent_harness.model.config import ModelConfig
from agent_harness.model.provider import create_chat_model
from agent_harness.multiagent.tools import DelegateTool
from agent_harness.observability import get_observability_sink
from agent_harness.prompt import (
    DEFAULT_REGISTRY,
    build_registry,
    compose_agent_prompt,
    join_guidance,
    parse_persona_config,
    tool_guidance_sections,
)
from agent_harness.sandbox import WorkspaceRegistry
from agent_harness.session.store import JsonlSessionStore
from agent_harness.storage import (
    OnStableBoundary,
    SqliteCheckpointStore,
    SqliteOperationLedger,
    SqliteSessionMetaStore,
)
from agent_harness.storage.artifact_select import select_artifact_store
from agent_harness.tooling import ToolExecutor, ToolRegistry
from agent_harness.tooling.approval import ApprovalCallback, ApprovalResponse
from agent_harness.tooling.contract import PermissionPolicy
from agent_harness.tooling.overflow import ArtifactOverflowHandler
from agent_harness.tools import (
    ApplyPatchTool,
    BashTool,
    EditTool,
    GitDiffTool,
    GitStatusTool,
    GlobTool,
    GrepTool,
    ReadTool,
    WriteTool,
)
from agent_harness.workspace import SqliteWorkspaceStore, WorkspaceIndex
from agent_harness.workspace.index import SessionHeaders


@dataclass
class RecoveryStores:
    """恢复子系统三 Store（同一 SQLite 文件，ADR-0004 布局）。

    AppState 与 CLI 各自构造实例、共享生命周期所有权；factory 只消费。

    `workspace_index` 是 ADR-0025 的 Workspace 实体 + 有序会话账本（WS-2 / #152），
    同库不同表。它是**可选**成员：它需要会话 header 来源，而大量单测只调
    `recovery_stores(path)` 不接会话存储——那些场景不需要项目索引，保持 `None`。"""

    operation_ledger: SqliteOperationLedger
    checkpoint_store: SqliteCheckpointStore
    session_meta_store: SqliteSessionMetaStore
    workspace_index: WorkspaceIndex | None = None


def recovery_stores(
    database_path: str | Path, *, workspace_headers: SessionHeaders | None = None
) -> RecoveryStores:
    """构造恢复 Store 束（同一 harness.db；未初始化——initialize_stores 幂等初始化）。

    `workspace_headers` 给定时才装配 `workspace_index`（见 `RecoveryStores` 说明）。
    """
    path = Path(database_path)
    return RecoveryStores(
        operation_ledger=SqliteOperationLedger(path),
        checkpoint_store=SqliteCheckpointStore(path),
        session_meta_store=SqliteSessionMetaStore(path),
        workspace_index=(
            WorkspaceIndex(SqliteWorkspaceStore(path), workspace_headers)
            if workspace_headers is not None
            else None
        ),
    )


async def initialize_stores(stores: RecoveryStores) -> None:
    """Store 束幂等初始化（并发首请求由调用方的 once 语义守护）。

    `workspace_index.initialize()` 顺带完成首次 bootstrap（AC14–16）——那一步需要
    读会话 header，所以只在装了 index 的进程里发生。
    """
    await stores.operation_ledger.initialize()
    await stores.checkpoint_store.initialize()
    await stores.session_meta_store.initialize()
    if stores.workspace_index is not None:
        await stores.workspace_index.initialize()


async def assemble_wiring(
    settings: Settings,
) -> tuple[CapabilityRegistry, CapabilityWiring]:
    """CAPABILITIES env → 显式装配（capability 发现/降级归 wire_capabilities）。"""
    registry = CapabilityRegistry()
    wiring = await wire_capabilities(
        registry, parse_capabilities_config(settings.capabilities), settings=settings
    )
    return registry, wiring


def _select_context_providers(
    wired: list[Any], requested: list[str] | None,
) -> list[Any]:
    """会话级 context_providers 筛选（ADR-0020b）。

    - ``requested is None`` → 返回全量 wired（默认行为，向后兼容）；
    - ``requested == []`` → 返回空（用户显式选零 provider，区别于 None 的默认全量）；
    - ``requested`` 非空 → 仅保留 ``name ∈ requested`` 的 provider；
      未知名字 fail-open 跳过（与 OPTIONAL_RUNTIME 降级原则一致——会话请求不能
      因为一个未装配的 provider 名字而拖垮 Core，不变量 #21）。

    未声明 ``name`` 属性的 provider（未来情况）经 ``getattr`` 容错为 None，
    不会被任何请求名字命中——fail-open 不报错。
    """
    if requested is None:
        return list(wired)
    wanted = set(requested)
    return [p for p in wired if getattr(p, "name", None) in wanted]


async def build_runtime(
    *,
    settings: Settings,
    wiring: CapabilityWiring,
    stores: RecoveryStores,
    workspace_registry: WorkspaceRegistry,
    session_id: str,
    workspace: Path,
    max_steps: int,
    permission_mode: PermissionPolicy = PermissionPolicy.WORKSPACE_WRITE,
    auto_approve: bool | None = None,
    approval_callback: ApprovalCallback | None = None,
    session_store: JsonlSessionStore | None = None,
    model_name: str | None = None,
    reasoning_effort: str | None = None,
    agent_profile: str | None = None,
    context_providers: list[str] | None = None,
) -> AgentRuntime:
    """装配全栈 Runtime：调用方保证 stores 已 initialize、workspace 已就绪。

    模型经 create_chat_model(settings) 构造（测试替身注入点）；sandbox 由
    WorkspaceRegistry 统一创建并持久化映射（恢复时按映射还原）。
    model_name（ADR-0016 §5）：None = 默认链；catalog 名 = 会话级选择
    （未知名字在 web 层已 422，这里 resolve 再响亮失败一次）。

    permission_mode（Phase 5）：会话级 PermissionPolicy 上限（审批阈值，不是
    硬墙——policy 决定哪些工具 needs_approval，审批结果仍由 callback 决定）。
    approval_callback：None → 安全默认（auto-approve 全批），调用方也可注入交互
    式审批 callback（见 web 层 PendingApprovalQueue）。
    """
    # agent_profile 运行时消费（ADR-0020a，RUNTIME 子批次）：查 BUILTIN_PROFILES
    # 拿 AgentSpec——main/None 走原路径（registry 全量、无 system_prompt 注入），
    # coding/research_review 收窄 registry 到 spec.tool_scope + 注入 spec.system_prompt。
    # 未知名字 web 层已 422，这里 KeyError 再响亮失败一次（防御性，不应发生）。
    profile_spec = None
    if agent_profile is not None:
        from agent_harness.agent.profiles import BUILTIN_PROFILES
        profile_spec = BUILTIN_PROFILES[agent_profile]

    # T5 persona（ADR-0023 D10）：env JSON → 前后缀 section。形制与
    # parse_capabilities_config 一致——坏配置装配期响亮失败，不静默降级。
    # DEFAULT_REGISTRY 不读环境（§4.4），所以这里显式按 settings 构建一次。
    persona = parse_persona_config(settings.agent_persona)

    config = (ModelConfig.from_settings(settings) if model_name is None
              else ModelConfig.from_catalog(settings, model_name))
    model = create_chat_model(config, reasoning_effort=reasoning_effort)
    # Model Fallback 两级链（ADR-0014 决策 14/16）：FALLBACK_MODEL_PROVIDER
    # 已配 → 构造 fallback 模型；切换决策在 FallbackPolicy，编排由 Runtime
    # 的 per-run coordinator 负责（见 agent/fallback 接线）。
    fallback_model = None
    if config.fallback is not None:
        fallback_model = create_chat_model(
            config.fallback, reasoning_effort=reasoning_effort,
        )
    # 进程级模型并发闸（#89）：本次 build_runtime 与其派生的所有 child 共享
    # 同一实例（全局在飞模型调用数的语义）。
    model_call_gate = ModelCallGate(settings.model_max_concurrency)

    sandbox = workspace_registry.create(session_id, workspace_root=workspace)
    registry = ToolRegistry()
    for tool_cls in (
        ReadTool, WriteTool, BashTool, EditTool, ApplyPatchTool,
        GlobTool, GrepTool, GitStatusTool, GitDiffTool,
    ):
        registry.register(tool_cls(sandbox))

    # 外置写入与模型侧读取**必须成对**：溢出处理器（唯一写入者）与读回工具指向
    # **同一个** store，否则会出现"东西写进了 A、模型从 B 读"的静默错配。
    # 选择口径（优先级 + 半配置判定）收敛在 `storage/artifact_select.py`，读路径
    # （`web/artifacts.py`）用同一个函数——两处各写一遍 if 级联就等于给漂移留门
    # （#192 批 1 审查发现）。
    overflow_handler = None
    selection = select_artifact_store(settings, session_id)
    if selection is not None:
        read_tool = selection.read_tool(selection.store)
        registry.register(read_tool)
        # 摘要里的读回提示点名**这个**工具（#186 AC4）：S3 配 `inspect_artifact`，
        # MinIO / Local 配 `read_artifact`。名字从选择器**实例化出来的那个工具**上取，
        # 不在这里再填一个字面量——那样等于把"配对关系"这份知识写了第二遍。
        overflow_handler = ArtifactOverflowHandler(
            selection.store,
            settings.artifact_overflow_chars,
            read_tool_name=read_tool.name,
        )

    # Phase 5：permission_mode 是会话级 PermissionPolicy 上限（审批阈值）。
    # approval_callback 由调用方决定：None → 安全默认（全批），注入 → 交互审批。
    # 切片 B：ApprovalCallback 已 async 化（外部 /approve 交互式审批需要 run 暂停）。
    policy = permission_mode
    if auto_approve is False and approval_callback is None:
        async def approval_callback(_req):  # type: ignore[no-redef]
            return ApprovalResponse(approved=False, reason="manual approval not yet wired")
    elif approval_callback is None:
        async def approval_callback(_req):  # type: ignore[no-redef]
            return ApprovalResponse(approved=True, reason="auto-approve")

    for capability_tool in wiring.tools:
        # multiagent 依赖 session_store 建独立 child session——缺席时降级缺席
        # （不注册 delegate，单代理照常），与 optional capability 语义一致。
        if isinstance(capability_tool, DelegateTool) and session_store is None:
            logger.warning(
                "multiagent 已启用但未提供 session_store，delegate 工具降级缺席"
            )
            continue
        registry.register(capability_tool)

    # agent_profile tool_scope 收窄（ADR-0020a）：仅在非 main profile 时过滤——
    # main 的 _MAIN_TOOLS 是全量的超集，filter 等价不过滤，但若未来新增了一个
    # tool_scope 未声明的工具，filter 会隐性收窄它。所以 main/None 走原路径不 filter，
    # 只有 coding/research_review 才收窄。收窄后 registry 流向所有下游：
    # ToolExecutor / AgentRuntime / multiagent activate 的 source_registry。
    if profile_spec is not None and agent_profile != "main":
        registry = registry.filtered(profile_spec.tool_scope)

    # T6 工具 guidance（ADR-0023 D11）：把**收窄后** registry 里各工具自带的
    # `prompt_guidance` 注册成 `tool:<name>` section（order 2000，scope `{"*"}`）。
    # 内容边界由这个 registry 决定——coding 收窄后没有 delegate，所以它的 prompt
    # 拿不到委派说明（工具缺席 → 说明缺席，这是本票的核心性质）。
    prompt_registry = build_registry(
        persona, tool_sections=tool_guidance_sections(registry.list()),
    )

    # multiagent 激活（ADR-0015）：模型链与 registry 已就绪，注入 child 的
    # 全部依赖。executor_factory 闭包捕获父级审批/策略/记账——child 与 parent
    # 同一审批面（决策 11 权限传递）。
    if wiring.multiagent_provider is not None and session_store is not None:
        from agent_harness.agent.factory import AgentFactory

        def _child_executor_factory(child_registry: ToolRegistry) -> ToolExecutor:
            return ToolExecutor(
                child_registry, policy=policy, approval_callback=approval_callback,
                overflow_handler=overflow_handler,
                operation_ledger=stores.operation_ledger,
            )

        wiring.multiagent_provider.activate(
            factory=AgentFactory(
                model=model, fallback_model=fallback_model,
                executor_factory=_child_executor_factory,
                primary_model_name=config.model_name,
                fallback_model_name=(config.fallback.model_name
                                     if config.fallback is not None else "fallback"),
                stream_idle_timeout=settings.model_stream_idle_timeout,
                stream_total_timeout=settings.model_stream_total_timeout,
                model_call_gate=model_call_gate,
                observability_sink=get_observability_sink(settings),
                persona=persona,
                # child 的 guidance 来自它自己收窄后的 registry——这里显式开开关。
                # Factory 默认 False：B2 契约（child.system_prompt == spec.system_prompt）
                # 的成立必须与"工具恰好没有 guidance"无关。
                include_tool_guidance=True,
            ),
            source_registry=registry,
            session_store=session_store,
            workspace_registry=workspace_registry,
            parent_session_id=session_id,
        )

    def _render_runtime_context() -> str:
        """渲染运行时上下文快照（T7 / ADR-0023 D8；BUG-013 瘦身）——每次 build 一次。

        事实来源全部取**当前**值，不缓存：
        - `cwd`：当前进程工作目录；
        - `os`：`platform.system()` + `release()`；
        - `date`：本地日期，只到日（用 `datetime.now()` 会让每次 build 文本都变，
          既毁 prefix cache 又难断言）。

        BUG-013 瘦身：**不再渲染 `model` / `tools`**——工具清单已在 system prompt
        的 tool guidance 区（静态能力），模型名运行时可查；快照紧贴最新用户消息，
        列工具会诱导模型把对话任务误判为工具任务。

        产物落 `meta_user`：快照是 user-role 消息，不是 system-role。
        """
        return DEFAULT_REGISTRY.assemble("runtime:context_snapshot", {
            "cwd": str(Path.cwd()),
            "os": f"{platform.system()} {platform.release()}",
            # 本地日期（用户看到的"今天"），**不**用 UTC：跨时区时 UTC 日期会与
            # 用户的一天错位。DTZ011 要的是 tz-aware，而这里刻意要本地日历日。
            "date": date.today().isoformat(),  # noqa: DTZ011
        }).meta_user_text

    return AgentRuntime(
        model=model,
        registry=registry,
        executor=ToolExecutor(registry, policy=policy, approval_callback=approval_callback,
                              overflow_handler=overflow_handler,
                              operation_ledger=stores.operation_ledger),
        max_steps=max_steps,
        checkpoint_policy=OnStableBoundary(stores.checkpoint_store),
        session_meta_store=stores.session_meta_store,
        context_builder=ContextBuilder(
            model, max_context_tokens=settings.max_context_tokens,
            auto_compact_threshold=settings.auto_compact_threshold,
            hard_guard_threshold=settings.hard_guard_threshold,
            # context_providers 运行时消费（ADR-0020b）：会话请求字段按 name 筛选
            # wiring 自动装配的 provider 子集；None=默认全量，[]=显式零，未知名字 fail-open。
            context_providers=_select_context_providers(
                wiring.context_providers, context_providers,
            ),
            # 有 profile → 走注册表组装：persona（0 / 10200）与工具 guidance（2000）
            # 的 order 由容器排序，persona 为空且无 guidance 时该 scope 只有一条
            # section，T2 保证产物逐字节等于原文（C5/C7 因此保持绿）。
            # 无 profile → 没有可组装的 scope，直接文本包裹（guidance 仍拼进去：
            # 它是"怎么用工具"的操作信息，与身份无关；两者皆空时返回 None，C4 保持）。
            system_prompt=(
                prompt_registry.assemble(f"profile:{agent_profile}").system_text
                if profile_spec is not None
                else compose_agent_prompt(None, persona, join_guidance(registry.list()))
            ),
            # T7：快照**不**拼进 system_prompt（那会破坏 T5/T6 与 C4/C5/C7 的逐字节
            # 契约），而是走独立通道，由 builder 按 meta_user 语义插到当前用户消息前。
            runtime_context_provider=_render_runtime_context,
        ),
        memory_writer=wiring.memory_writer,
        fallback_model=fallback_model,
        stream_idle_timeout=settings.model_stream_idle_timeout,
        stream_total_timeout=settings.model_stream_total_timeout,
        model_call_gate=model_call_gate,
        primary_model_name=config.model_name,
        fallback_model_name=(config.fallback.model_name if config.fallback is not None
                             else "fallback"),
        observability_sink=get_observability_sink(settings),
    )
