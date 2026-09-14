"""FastAPI 应用工厂 + 路由（Phase 9/10 精简版）。

create_app() 是单一入口——传入 Settings，返回装配好的 FastAPI。
测试用 test settings 注入；生产用 Settings() 从 .env 读。

路由契约见模块 docstring（web/__init__.py）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Literal

import jwt
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sse_starlette.sse import EventSourceResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse, Response

from agent_harness.agent import AgentEvent
from agent_harness.assembly import RecoveryStores, initialize_stores
from agent_harness.capability.base import CapabilityRegistry
from agent_harness.capability.config import parse_capabilities_config
from agent_harness.capability.manifest import (
    core_manifest_entry,
    descriptor_manifest_entry,
)
from agent_harness.capability.wiring import CapabilityWiring, wire_capabilities
from agent_harness.config import Settings
from agent_harness.identity import (
    IdentityContext,
    identity_context_var,
    set_identity_context,
)
from agent_harness.instance_lock import InstanceLock
from agent_harness.logging import setup_logging
from agent_harness.model.config import (
    PROVIDER_PRESETS,
    ConfigError,
    ModelConfig,
    _pick_capabilities,
    parse_model_catalog,
)
from agent_harness.observability import flush_process_sink
from agent_harness.sandbox import WorkspaceRegistry
from agent_harness.session import JsonlSessionStore, SessionEvent
from agent_harness.session.event import RUNTIME_EVENT_SCHEMA_VERSION
from agent_harness.session.queue import MessageQueueManager
from agent_harness.session.service import (
    ARCHIVE_ENTRY_API,
    ActiveRunConflict,
    AmendOptions,
    ApprovalAlreadyResolved,
    ApprovalQueueMissing,
    ApprovalRequestMissing,
    InvalidDecision,
    InvalidSessionId,
    QueueItemNotFound,
    RecoveryConflict,
    SeqConflict,
    SessionHasChildren,
    SessionNotFound,
    SessionService,
    SteerTargetNotFound,
    UnknownModel,
    WorkspaceNameInvalid,
    WorkspaceNotFound,
    resolve_model_target,
    validate_session_id,
)
from agent_harness.storage import (
    SqliteCheckpointStore,
    SqliteOperationLedger,
    SqliteSessionMetaStore,
)
from agent_harness.tooling.approval_queue import PendingApprovalQueue
from agent_harness.tooling.contract import (
    PERMISSION_MODE_DESCRIPTIONS,
    PermissionPolicy,
)
from agent_harness.web import artifacts
from agent_harness.web.domain_errors import http_error
from agent_harness.web.runmanager import RunManager
from agent_harness.web.serialization import (
    build_event_payload,
    build_session_event_payload,
)
from agent_harness.workspace import SqliteWorkspaceStore, WorkspaceIndex

# ── Staged amend 字段的人类可读描述（Phase 5 + Ticket B1）──────────────
# 这些 dict 是 POST /api/sessions validator 与 GET 清单端点的**单一事实源**：
# validator 用它们的 key 集合判断合法值；GET 端点用它们的 value 投影 display_name +
# description。两边引用同一份常量 → 加新档位只改一处，validator 与清单永不漂移。
# 与 PERMISSION_MODE_DESCRIPTIONS（tooling/contract.py）同模式（Reuse First §6）。

#: reasoning_effort 三档（已运行时消费——经 create_chat_model 注入）。
#: key 是 **harness 语义档位**，不是 provider 线格式枚举：翻译在
#: model/provider.py 的 REASONING_EFFORT_WIRE（两处键集由
#: tests/model/test_reasoning_effort.py G5 锁住）。不要把这里的 key 直接
#: 改成 'medium'/'high'——那是线格式词汇，会让前端清单与产品语义脱节。
REASONING_EFFORT_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "minimal": {
        "display_name": "轻量",
        "description": "最少推理开销，最快但不够深入。",
    },
    "standard": {
        "display_name": "标准",
        "description": "平衡的推理深度，适用于常规任务（默认）。",
    },
    "deep": {
        "display_name": "深度",
        "description": "较高推理开销，较慢但更深入。",
    },
}

#: agent_profile 三档（已运行时消费——system_prompt 经 ContextBuilder 注入 + tool_scope 经 registry.filtered 收窄，ADR-0020a）。
AGENT_PROFILE_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "main": {
        "display_name": "通用",
        "description": "通用编排 Agent（默认）。",
    },
    "coding": {
        "display_name": "编程",
        "description": "专精代码编辑、调试和构建任务。",
    },
    "research_review": {
        "display_name": "研究审查",
        "description": "专精研究、检索和审查任务。",
    },
}

#: context_providers 已装配清单投影（ADR-0020b，已运行时消费——按 name 筛选
#: wiring 自动装配的 ContextProvider 子集注入 ContextBuilder）。id 必须与
#: MemoryContextProvider.name / SkillCatalogContextProvider.name 严格对齐——
#: 前端据本清单渲染选项，用户选中的 id 经 POST /api/sessions 回传触发筛选。
CONTEXT_PROVIDER_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "memory": {
        "display_name": "记忆",
        "description": "注入与用户相关的召回记忆。",
    },
    "skills": {
        "display_name": "技能",
        "description": "注入可用技能目录（名称 + 描述）。",
    },
}

# ── Request / Response schemas ──


class _AmendValueValidators(BaseModel):
    """amend 字段的静态取值校验（三个请求体共用一份，ADR-0020b / ADR-0021）。

    ``check_fields=False``：字段声明在子类（CreateSessionRequest / ResumeRequest /
    SendMessageRequest），校验逻辑只写一遍——三个入口对同一份取值集合负责。
    未知 ``context_providers`` id 的判定依赖运行时 wiring，不在这一层
    （见 ``_validate_wired_context_providers``）。
    """

    @field_validator("reasoning_effort", check_fields=False)
    @classmethod
    def _validate_reasoning_effort(cls, v: str | None) -> str | None:
        if v is not None and v not in REASONING_EFFORT_DESCRIPTIONS:
            valid = ", ".join(REASONING_EFFORT_DESCRIPTIONS)
            raise ValueError(f"reasoning_effort must be one of: {valid}")
        return v

    @field_validator("agent_profile", check_fields=False)
    @classmethod
    def _validate_agent_profile(cls, v: str | None) -> str | None:
        if v is not None and v not in AGENT_PROFILE_DESCRIPTIONS:
            valid = ", ".join(AGENT_PROFILE_DESCRIPTIONS)
            raise ValueError(f"agent_profile must be one of: {valid}")
        return v

    @field_validator("context_providers", check_fields=False)
    @classmethod
    def _validate_context_providers_shape(
        cls, v: list[str] | None
    ) -> list[str] | None:
        # 只校验形状（每项非空字符串，空 list 合法）。是否已装配由 handler 对照
        # wiring 判定——静态校验没法知道 CAPABILITIES 运行时状态。
        if v is None:
            return v
        for item in v:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    "context_providers entries must be non-empty strings"
                )
        return v


class CreateSessionRequest(_AmendValueValidators):
    """POST /api/sessions 的请求体。"""

    # 空 task 直接 422（FastAPI 自动校验）；纯空白 task 容忍（runtime 侧无意义但不危险）。
    # max_length 封顶：task 会逐字持久化进 JSONL（user/message）并整体进模型上下文，
    # 无上限时一个多 MB 请求体就能写爆日志 + 撑爆 context。
    task: str = Field(min_length=1, max_length=100_000)
    workspace: str | None = None  # None → 用默认 workspace；只接受单段目录名（校验在 SessionService._validate_workspace_name，路径形态走 POST /api/projects）
    # ADR-0027 / #169：任意**已存在**的绝对目录，会话直接以它为操作目录（不创建、
    # 不复制），并自动注册为项目 + 归组。与 `workspace` 互斥（同时非空 → 422）。
    # 形态/存在性/是否目录的校验在 SessionService._resolve_cwd（领域层，与 CLI 共用）。
    cwd: str | None = None
    max_steps: int = Field(default=10, ge=1, le=200)  # 非正数 / 过大 → 422（防客端刷爆循环预算）
    # Phase 5：permission_mode 是会话级「审批阈值」声明（不是硬墙）。三档真实
    # PermissionPolicy；未知值 → 422。permission_mode 决定 ToolExecutor 的 policy
    # 上限，审批本身仍走 ApprovalCallback（默认 auto-approve）。
    permission_mode: str = Field(default="workspace-write")
    # auto_approve 保留为 deprecated alias（向后兼容）：true ≡ workspace-write
    # + auto-approve callback；false ≡ workspace-write + deny callback。两者同传
    # 时 permission_mode 优先。两个字段都缺省 → workspace-write + auto-approve
    # （现行为不变）。
    auto_approve: bool = True
    # amend contract fields（Phase 5 staged → RUNTIME 子批次全部消费：reasoning_effort
    # / agent_profile / context_providers）
    reasoning_effort: str | None = None
    agent_profile: str | None = None
    context_providers: list[str] | None = None

    # 会话级模型选择（ADR-0016 §5，C6）：None = 默认链（现行为不变）；
    # 命名 = AGENT_MODELS catalog 条目，未知名字 422。fallback 链不受影响。
    model: str | None = None

    @field_validator("permission_mode")
    @classmethod
    def _validate_permission_mode(cls, v: str) -> str:
        valid = {p.value for p in PermissionPolicy}
        if v not in valid:
            raise ValueError(
                f"permission_mode must be one of {sorted(valid)}; got {v!r}"
            )
        return v


class ModelChangeRequest(BaseModel):
    """POST /api/sessions/{id}/model 的请求体（T7 #137，PRD §2.3）。

    provider 必须与 catalog 条目一致；model_id 命中条目名或上游模型名。
    """

    provider: str = Field(min_length=1)
    model_id: str = Field(min_length=1)


class ApproveRequest(BaseModel):
    """POST /api/sessions/{id}/approve 的请求体（Phase 5 + Batch 5.1）。

    decision 是 spec 契约（03 §9 PermissionDecision）；approved 是兼容字段。
    两者都传时 decision 优先；只传 approved 时从它推导（True→approve_once，
    False→deny）。decision 必须命中 requested 事件里 allowed_decisions。
    """

    approval_id: str | None = None
    approved: bool = True
    decision: str | None = None
    reason: str = ""


class ResumeRequest(_AmendValueValidators):
    """POST /api/sessions/{id}/resume 的请求体。"""

    task: str = Field(min_length=1, max_length=100_000)
    # staged amend 字段（可选，None = 默认行为）
    reasoning_effort: str | None = None
    agent_profile: str | None = None
    context_providers: list[str] | None = None
    model: str | None = None


class SendMessageRequest(_AmendValueValidators):
    """POST /api/sessions/{id}/messages 的请求体（PRD §5.3 续聊入口）。

    ``mode`` 取自 PRD 锁定决策 D-7：

      * ``queue``（默认）——空闲 → 直接拉起新 run；在途 → 入队等待
        （不抢断不丢消息，下个 run 自然消费）。
      * ``steer``——仅在途 run 时合法：注入引导请求，被当前 step 边界
        的 run 读取（不重启 run、不改写历史事件）。
    """

    content: str = Field(min_length=1, max_length=100_000)
    mode: str = Field(default="queue", pattern="^(queue|steer)$")
    max_steps: int = Field(default=10, ge=1, le=200)
    # staged amend 字段（可选，None = 默认行为）
    reasoning_effort: str | None = None
    agent_profile: str | None = None
    context_providers: list[str] | None = None
    model: str | None = None


class WorkspaceRef(BaseModel):
    """会话摘要里的项目引用（WS-3 / #153 AC2）：`id` 做请求/重命名，`title` 做显示。

    形状由实现者定、但**必须写死在契约里**（票面 AC2）；前端 `types.ts::WorkspaceRef`
    用同一个形状做编译期锁。
    """

    id: str
    title: str


class SessionSummary(BaseModel):
    """GET /api/sessions 返回的单条摘要。"""

    session_id: str
    event_count: int
    first_event_time: str | None = None
    last_event_time: str | None = None
    # Gap 3 (P0)：首条 user/message content 截断 128 字符——前端 SessionList
    # 零额外请求渲染标题（保留 events 扫描作为后端未返回时的降级路径）。
    first_user_message: str | None = None
    # Gap 2 (P2)：Langfuse trace 关联。OBS-010 起**真实回填**：**末事件恰为
    # run 终结事件**（run/completed|failed|interrupted）时取其 trace_id；末事件
    # 非终结（run 在途，或上一轮已完成后新轮的 user/message/run-started 垫在末尾）
    # 或未配置可观测性时为 null——绝不伪造，前端显示「未追踪」。
    # 有意只认末事件（不回溯）以保住列表页快路径，取舍见
    # `JsonlSessionStore._terminal_trace_field`；不变量 #21：可观测性缺席
    # 不致命也不造假。
    trace_id: str | None = None
    # ARCH-4b：与 `trace_id` 同源（同一个 run 终结事件、同一套守卫）的可点击
    # Langfuse URL（契约 2d7f87a / ADR-0018 D7）。前端 `types.ts::SessionSummary`
    # 把该字段声明为**非可选** `string | null`——本字段存在即让那条声明为真。
    trace_url: str | None = None
    # WS-3 / #153：会话所属项目；未分组（历史遗留 / 未命名 workspace / 装配里没有
    # workspace 索引）为 `None`，**绝不伪造**（不变量 #21 同族）。
    #
    # 刻意**不给默认值**：给了默认值的话，将来某个构造点漏传 `workspace=` 会静默
    # 变成"未分组"——那是一条假事实。必填 → 构造响应时漏传**响亮失败**。
    # 注意本字段锁住的是**构造点**，不是"服务层忘了回填"：领域层
    # `SessionSummaryStats.workspace` 仍有 `= None` 默认值，服务层漏查映射照样会
    # 序列化成 null。真正抓漏映射的是断言**值**的测试
    # （`tests/web/test_session_list_workspace.py::test_rows_carry_real_workspace_and_ungrouped_is_null`）。
    workspace: WorkspaceRef | None
    # #171：是否已归档——前端「已归档」徽标的**唯一**来源（`?include_archived=true`
    # 时那些行必须能被认出来）。与 `workspace` 同样**刻意不给默认值**：默认 `False`
    # 会让漏映射的构造点把"已归档"谎报成未归档，徽标静默消失（假事实，不变量 #21 同族）。
    archived: bool


class SessionArchived(BaseModel):
    """`POST/DELETE /api/sessions/{id}/archive` 的成功响应（#171）。

    形状就是领域动作本身：`{id, archived}`——两个动词各自只表达一个终态，
    `archived` 是**动作后**的真值（幂等：重复归档仍是 `true`）。
    """

    id: str
    #: 动作后的状态。归档可逆，没有"半归档"可表达，所以就是一个布尔。
    archived: bool


class SessionDeleted(BaseModel):
    """`DELETE /api/sessions/{id}` 的成功响应（#172 / ADR-0029）。

    与项目软删除的 `ProjectDeleted` 刻意不同形：那个要带 `sessions_detached` 与
    `detail`（向用户解释"会话没被删"），这里 `deleted=True` 就是字面意思——**东西没了**。
    """

    id: str
    #: 走到 200 就一定是真删了（不存在 → 404、形态非法 → 422、状态冲突 → 409），
    #: 所以这里没有"半删"可表达。字面量 `True` 让这件事在 schema 里就成立。
    deleted: Literal[True] = True
    #: 删除前日志里的事件条数。前端用它写确认回执（"已删除 N 条事件"）。
    events: int
    #: 本次从多少个项目的账本里摘掉了它（正常 0/1）。
    detached_from_projects: int


class AppState:
    """app 内部共享状态的薄容器——避免全局变量。

    V1：单进程内存里的 runtime 工厂 + session store 根目录。
    Capability 子系统按 CAPABILITIES 配置惰性装配一次（wire_capabilities），
    进程退出时统一关闭；配置为空 = 零行为变化。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # sessions 和 workspace 默认放在 .agent/ 下（跟现有诊断日志一致）
        self.sessions_root = Path(settings.workspace_dir) / "sessions"
        self.workspaces_root = Path(settings.workspace_dir) / "workspaces"
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        self.workspaces_root.mkdir(parents=True, exist_ok=True)
        self.store = JsonlSessionStore(root=self.sessions_root)
        # detached-run 托管（ADR-0016 §2.1，D-A）：run 生命周期与 HTTP 请求
        # 解耦——SSE 订阅者离开只 unsubscribe，取消只经 POST /cancel 或孤儿
        # 回收（宽限期 Settings.run_disconnect_grace_seconds）。
        self.run_manager = RunManager(
            disconnect_grace_seconds=settings.run_disconnect_grace_seconds,
        )
        # Phase 5：会话级待审批队列——当 permission_mode 非 danger-full-access
        # 且 ToolExecutor 触发 needs_approval 时，callback 经此 queue 与前端 /approve
        # 对接。key 是 session_id；安全默认下（auto-approve）callback 不挂 queue。
        self.approval_queues: dict[str, PendingApprovalQueue] = {}
        # Phase Multiturn T2：续聊排队 + steer 请求注册表（PRD §5.3 / §6）。
        self.message_queues = MessageQueueManager()
        # 恢复基础设施（R8-1，用户拍板接线）：三 Store 共享同一 SQLite 文件
        # （ADR-0004 布局），WorkspaceRegistry 持久化 session↔sandbox 映射。
        # initialize 是异步的 → 惰性执行（ensure_stores），兼容不走 lifespan
        # 的测试路径。
        self.harness_db = Path(settings.workspace_dir) / "harness.db"
        self.operation_ledger = SqliteOperationLedger(self.harness_db)
        self.checkpoint_store = SqliteCheckpointStore(self.harness_db)
        self.session_meta_store = SqliteSessionMetaStore(self.harness_db)
        self.workspace_registry = WorkspaceRegistry(
            root=Path(settings.workspace_dir), backend="local"
        )
        # WS-2 / ADR-0025：项目实体 + 有序会话账本（同 harness.db 的另 5 张表）。
        # 只构造一次：它持有内存缓存（AC10 同步读），每次 stores 属性都新建会丢掉缓存。
        self.workspace_index = WorkspaceIndex(
            SqliteWorkspaceStore(self.harness_db), self.store
        )
        self._stores_lock = asyncio.Lock()
        self._stores_ready = False
        # Capability 装配：只在首次使用时执行（含 Memory / Skills / demo 等）。
        # asyncio.Lock 守住 once 语义：并发首请求都看到 _wiring is None 时，
        # 只有一个真正执行 wire_capabilities，另一个等锁后复用结果
        # （否则第二个会在重复注册上炸掉 / 被降级吞掉）。
        self._wiring_lock = asyncio.Lock()
        self._registry: CapabilityRegistry | None = None
        self._wiring: CapabilityWiring | None = None
        self._closed = False  # shutdown 后置位：get_wiring 拒绝在关停后新装配

    async def ensure_stores(self) -> None:
        """惰性初始化恢复三 Store（幂等；并发首请求由锁守 once 语义）。"""
        if self._stores_ready:
            return
        async with self._stores_lock:
            if not self._stores_ready:
                await initialize_stores(self.stores)
                self._stores_ready = True

    @property
    def stores(self) -> RecoveryStores:
        """恢复三 Store 束（factory 消费；实例归 AppState 所有）。"""
        return RecoveryStores(
            operation_ledger=self.operation_ledger,
            checkpoint_store=self.checkpoint_store,
            session_meta_store=self.session_meta_store,
            workspace_index=self.workspace_index,
        )

    async def get_wiring(self) -> tuple[CapabilityRegistry, CapabilityWiring]:
        """惰性装配 Capability 子系统并缓存；返回 (registry, wiring)。

        shutdown 可能在 wire await 期间发生：入口和拿锁后都检查 _closed，
        wire 完成后再查一次——在途调用以 RuntimeError 失败，但刚装配好的
        wiring 仍留在字段上，由随后拿到锁的 shutdown 关闭（连接不泄露）。
        """
        if self._closed:
            raise RuntimeError("AppState is shut down")
        if self._wiring is not None and self._registry is not None:
            return self._registry, self._wiring
        async with self._wiring_lock:
            if self._closed:
                raise RuntimeError("AppState is shut down")
            if self._wiring is None or self._registry is None:
                config = parse_capabilities_config(self.settings.capabilities)
                registry = CapabilityRegistry()
                wiring = await wire_capabilities(registry, config, settings=self.settings)
                # 先落字段再查 _closed：锁在手上，shutdown 必然排在本次释放之后，
                # 它会从字段上取走这份 wiring 并关闭——绝不静默丢弃。
                self._registry, self._wiring = registry, wiring
                if self._closed:
                    raise RuntimeError("AppState is shut down")
            return self._registry, self._wiring

    @property
    def wiring(self) -> CapabilityWiring | None:
        """已装配的 wiring（未装配时 None；测试与 shutdown 用）。"""
        return self._wiring

    async def shutdown(self) -> None:
        """进程退出时关闭后台 run task、relay 与外部连接。幂等：重复调用只关闭一次。

        必须拿 _wiring_lock：否则在途 get_wiring 可能在 swap 之后才完成装配，
        装配出的 wiring 永远没人关（泄露 Milvus / embedding 连接）。
        先置位 _closed 再拿锁——让在途装配在 wire 完成后立刻失败，而不是
        把 wiring 交给一个已关停的 app。
        """
        self._closed = True
        # 先停 detached run（它们引用 wiring 的工具/模型），再关 wiring。
        await self.run_manager.aclose()
        async with self._wiring_lock:
            wiring, self._wiring, self._registry = self._wiring, None, None
        # 关闭知识在 CapabilityWiring.aclose（批次 A 候选 4）：memory 组件 +
        # lifecycle 通道逐项隔离关闭，web 层不再懂每种 capability 的关闭姿势。
        if wiring is not None:
            await wiring.aclose()


async def _validate_wired_context_providers(
    state: AppState, ids: list[str] | None
) -> None:
    """``context_providers`` 对照 wiring 真实装配集校验 → 422（ADR-0021）。

    Pydantic 只能校验形状；某个 provider 是否装配取决于 CAPABILITIES 运行时
    状态，必须在这里看 wiring。三个 amend 入口（create / resume / messages）
    共用同一份判定。
    """
    if ids is None:
        return
    _, wiring = await state.get_wiring()
    wired_ids = {getattr(p, "name", None) for p in wiring.context_providers}
    wired_ids.discard(None)
    unknown = [pid for pid in ids if pid not in wired_ids]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"context_providers contains unknown ids {unknown}; "
                f"available: {sorted(wired_ids)}"
            ),
        )


async def _validate_amend_for_existing_session(
    state: AppState, amend: AmendOptions
) -> None:
    """``/resume`` 与 ``/messages`` 的 amend 校验（与 POST /api/sessions 对齐）。

    create 路径的 ``model`` 校验在 service 里（落盘前避免孤儿 session）；这两个
    端点没有那道闸门——不在此拦截的话，未知 model 会让 ``build_runtime`` 抛
    ``ConfigError`` 且无人捕获 → 500，未知 context_providers 则被静默跳过。
    ``reasoning_effort`` / ``agent_profile`` 已由 Pydantic 在 parse 期 422
    （``_AmendValueValidators``）。
    """
    await _validate_wired_context_providers(state, amend.context_providers)
    if amend.model is not None:
        try:
            ModelConfig.from_catalog(state.settings, amend.model)
        except ConfigError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error


#: 重放 backlog 阈值（durable 事件数，ADR-0016 §2.3）：after_seq 落后超过
#: 该值 → 单帧 stream/truncated 控制事件后收流，客户端走 GET /events 全量
#: 重建后带 after_seq=latest_seq 重连（02 §10.4 简化版；snapshot 层 DEFER）。
STREAM_REPLAY_MAX_EVENTS = 1000


def _render_model_option(
    *, id: str, provider: str, model_name: str, is_default: bool,
    capabilities: dict[str, Any], metadata_source: str,
) -> dict[str, Any]:
    """渲染一条 ModelOption（SDD 03 §16）。

    新契约字段：id / display_name / provider / is_default / is_available /
    context_window? / speed_tier? / supports_*? / metadata_source。
    旧字段 alias（向后兼容）：name / model / default。
    未知能力位不在 capabilities dict 里即不出现在响应（契约：「not guessed」）。
    """
    option: dict[str, Any] = {
        # 新契约字段
        "id": id,
        "provider": provider,
        "is_default": is_default,
        "is_available": True,  # catalog 无 disabled 概念，恒可用
        "metadata_source": metadata_source,
        # 旧字段 alias（前端切换期间保留，避免破坏现有客户端）
        "name": id,
        "model": model_name,
        "default": is_default,
    }
    # display_name 缺省回落到 model_name（更可读）。
    option["display_name"] = capabilities.get("display_name", model_name)
    # 已知能力位透传（未声明的键不在 capabilities 里 → 省略，不猜测）。
    for cap_key in ("context_window", "speed_tier", "supports_tools",
                    "supports_vision", "supports_reasoning_summary"):
        if cap_key in capabilities:
            option[cap_key] = capabilities[cap_key]
    return option


def _event_to_sse_dict(event: AgentEvent, session_id: str) -> dict[str, str]:
    """AgentEvent → SSE 帧（信封构建在 web/serialization.py，SSE/WS 共用）。"""
    return {"data": json.dumps(
        build_event_payload(event, session_id), ensure_ascii=False
    )}


def _session_event_to_sse_dict(event: SessionEvent, session_id: str) -> dict[str, str]:
    """SessionEvent → SSE 帧（重放通道，信封构建在 web/serialization.py）。"""
    return {"data": json.dumps(
        build_session_event_payload(event, session_id), ensure_ascii=False
    )}


#: CSP（集成 AI 移交，INTEGRATION_NOTES §4.1）：静态 HTML 的纵深防御——
#: 脚本/样式只认同源构建产物，img 放行 data:。所有响应统一携带（浏览器
#: 仅对 HTML 文档执行，JSON 响应带此头无害），避免漏掉任何静态入口。
_CSP_POLICY = "default-src 'self'; img-src 'self' data:"


class CSPHeaderMiddleware:
    """纯 ASGI 中间件：所有响应统一携带 CSP 头（行为契约同旧实现）。

    为什么不用 @app.middleware（BaseHTTPMiddleware）：SSE 流过其 anyio 内存
    流 machinery 时，客户端断连的取消会在嵌套中间件间传播污染请求栈（全量
    回归下曾放大为逐请求 500 "No response returned"）。纯 ASGI 直通流式
    帧，无缓冲无任务组（ADR-0016 §2.1 生产级加固）。
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Any) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Content-Security-Policy"] = _CSP_POLICY
            await send(message)

        await self.app(scope, receive, send_wrapper)


class AuthSeamMiddleware:
    """纯 ASGI 中间件：身份认证 + IdentityContext 绑定（行为契约同旧实现）。

    fail-open/fail-closed 语义、claims 校验、401 形状逐字节不变
    （tests/test_identity.py / test_web_api.py 钉住）；差异仅在传输层：
    不经 BaseHTTPMiddleware 的任务组，SSE 断连取消不再跨请求传染。
    """

    def __init__(self, app: Any, settings: Settings) -> None:
        self.app = app
        self._settings = settings

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        identity = IdentityContext("local", "local", ["user", "session"])
        headers = Headers(scope=scope)
        authorization = headers.get("authorization")
        if self._settings.jwt_secret:
            # R6-4/R8-3（用户拍板 fail-closed）：配置了密钥 = 需要认证。
            # 匿名请求不再静默降级为 trusted local（此前配合 CORS * 等于把
            # agent API 开放给任意网页）；无 exp 的 token 一并拒绝（强制
            # 过期语义，永不过期的签名 token 等于永久凭证）。
            if not authorization:
                response: Response = JSONResponse(
                    {"detail": "Missing identity token"}, status_code=401)
                await response(scope, receive, send)
                return
            try:
                scheme, encoded = authorization.split(" ", 1)
                if scheme.lower() != "bearer":
                    raise ValueError("Expected Bearer token")
                # SecretStr 取明文给 jwt.decode；truthiness 判断仍基于密钥值
                # （SecretStr("") 为 falsy，未配置语义不变）。
                claims = jwt.decode(
                    encoded, self._settings.jwt_secret.get_secret_value(),
                    algorithms=["HS256"],
                    options={"require": ["tenant_id", "user_id", "exp"]})
                tenant, user = claims["tenant_id"], claims["user_id"]
                scopes = claims.get("scopes", ["user", "session"])
                if (not isinstance(tenant, str) or not tenant.strip()
                        or not isinstance(user, str) or not user.strip()
                        or not isinstance(scopes, list)
                        or any(not isinstance(s, str) for s in scopes)):
                    raise ValueError("Invalid identity claims")
                identity = IdentityContext(tenant, user, scopes)
            except (jwt.InvalidTokenError, ValueError):
                response = JSONResponse(
                    {"detail": "Invalid identity token"}, status_code=401)
                await response(scope, receive, send)
                return
        token = set_identity_context(identity)
        try:
            await self.app(scope, receive, send)
        finally:
            identity_context_var.reset(token)


def create_app(settings: Settings | None = None, *, enable_cors: bool = True) -> FastAPI:
    """装配 FastAPI 应用。测试可注入 test settings；生产默认从 .env 读。"""
    if settings is None:
        settings = Settings()

    state = AppState(settings)

    # lifespan 替代 on_event：进程退出时关闭 Memory 子系统，避免泄露外部连接。
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # web 部署必须自己接诊断日志：uvicorn 默认只配 uvicorn.* logger，root
        # 无 handler 时 runtime/executor 的 log_event 全部 no-op——llm_call /
        # tool_operation / task_failed 审计链路整条消失（cli.py 有 setup_logging，
        # web 之前漏接）。幂等（重复调用先清 handlers）。
        setup_logging(settings.log_level, settings.workspace_dir)
        # ARCH-7（#150）：启动期单实例锁。同一 session root 的第二个进程必须
        # 响亮失败——跨进程同时 append 会话 JSONL 会产出重复 seq / 交错写，
        # RunManager 的 run 归属共识也只在进程内有效；CLI 与 Web 并发同样被
        # 拒绝（有意行为，见 instance_lock 模块 docstring）。取在 setup_logging
        # **之后**：逃生门降级时那条 WARNING 才能落进 agent.jsonl，而不是只掉到
        # stderr（AC7 要求逃生门在日志里显著留痕）。
        instance_lock = InstanceLock(settings.workspace_dir).acquire()
        try:
            # Phase Multiturn T8（#138）：启动崩溃扫描——无终态 run 补记
            # run/interrupted + 强制 Ledger reconcile。失败不阻塞启动（单个坏会话
            # 不该让服务起不来），但必须响亮落日志。
            try:
                from agent_harness.session.service import SessionService

                scan_results = await SessionService(state).scan_interrupted()
                for result in scan_results:
                    logging.getLogger("agent_harness.web").warning(
                        "启动崩溃扫描：session=%s recovery=%s detail=%s",
                        result.session_id, result.recovery, result.detail,
                    )
            except Exception:
                logging.getLogger("agent_harness.web").exception(
                    "启动崩溃扫描失败（不阻塞启动）"
                )
            try:
                yield
            finally:
                await state.shutdown()
                # 旁路收尾（ADR-0018 D3）：服务停机前尽力发送剩余 Langfuse span
                # （有超时上限，不阻塞退出）。
                flush_process_sink()
        finally:
            # 放在 shutdown 之后：仍在关连接时不该让第二个进程进来接手。
            instance_lock.release()

    app = FastAPI(title="Agent Harness Inspector", version="0.1.0", lifespan=lifespan)
    app.state.agent = state  # 挂在 app.state 上，路由通过 request.app.state 取

    # Phase 14 lineage 路由（独立 router 文件——流式改造重刀 app.py 时的最小接入面）
    from agent_harness.web.lineage import register_lineage_routes

    register_lineage_routes(app, validate_session_id=validate_session_id)

    # WS-4 / #154 项目 CRUD 路由（同为独立 router：本模块只留这一行接入面）
    # `require_trusted_origin` 一并取用：#172 的会话硬删是宿主侧不可逆操作，
    # 与项目 / 记忆端点共用同一条来源闸（ADR-0025 D1），不复制安全规则。
    from agent_harness.web.projects import (
        register_project_routes,
        require_trusted_origin,
    )

    register_project_routes(app)

    # MEM-4 / #159 记忆入口（列出 / 硬删；同为独立 router）
    from agent_harness.web.memory import register_memory_routes

    register_memory_routes(app)

    # WS-7 / #170 宿主只读目录列举（目录选择器的唯一可行路径，ADR-0028）
    from agent_harness.web.host_dirs import register_host_dir_routes

    register_host_dir_routes(app)

    # #191 会话工作区只读浏览（列文件 / 读文件 / git status / 单文件 diff）。
    # 同样是独立 router + 一行接入：路径边界与来源闸都用既有的那一份（Sandbox /
    # `require_trusted_origin`），本模块不新造校验。
    from agent_harness.web.workspace_files import register_workspace_file_routes

    register_workspace_file_routes(app, validate_session_id=validate_session_id)

    if not settings.jwt_secret:
        # R6-4：未配置密钥 = 本地信任模式（fail-open）。保留开发便利，但必须
        # 响亮告知——静默降级是原审计的核心危害。
        logging.getLogger("agent_harness.web").warning(
            "JWT_SECRET 未配置：API 以本地信任模式运行（所有请求视为 local 身份，"
            "不做身份校验）。生产部署必须配置 JWT_SECRET。"
        )

    # CSP（集成 AI 移交，INTEGRATION_NOTES §4.1）：静态 HTML 的纵深防御——
    # 脚本/样式只认同源构建产物，img 放行 data:。所有响应统一携带（浏览器
    # 仅对 HTML 文档执行，JSON 响应带此头无害），避免漏掉任何静态入口。
    _CSP_POLICY = "default-src 'self'; img-src 'self' data:"

    # 纯 ASGI 中间件（见类 docstring）：先 csp（内层）后 auth（外层），与
    # 旧 BaseHTTPMiddleware 版注册顺序逐层一致；CORS 仍最后添加 = 最外层。
    app.add_middleware(CSPHeaderMiddleware)
    app.add_middleware(AuthSeamMiddleware, settings=settings)

    if enable_cors:
        # V1 本地单用户：宽松 CORS 让 Vite dev server (5173) 能直连。
        # 多用户时收紧到已知 origin（接缝点）。
        # 必须最后添加 = 中间件栈最外层：浏览器预检（OPTIONS）天然不携带
        # Bearer，认证层在内层时预检直接 401，配置 JWT_SECRET 后跨域 dev
        # 模式整体失效。预检放行不削弱认证——数据请求仍逐个过认证层。
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ── 路由 ──

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/sessions")
    async def list_sessions(
        workspace_id: str | None = None, include_archived: bool = False
    ) -> list[SessionSummary]:
        """列历史 session。

        - 不带参数：全部会话，按**最近活动**倒序（既有契约与快路径取舍不变）。
        - `?workspace_id=<项目 id>`：只列该项目的会话，顺序 = **账本的手工序**
          （AC4：不按活动时间重排）；项目未注册 → 404（不伪装成空列表）。
        - `?include_archived=true`（#171）：把已归档的会话也列出来（前端"显示已归档"
          开关）。**默认 false 即不列**；两条路径（默认列表 / 项目视图）同一规则。
          非布尔值 → 422（FastAPI 的 bool query 语义，不自造一套）。
        每行都带 `workspace`（`null` = 未分组）与 `archived`（徽标真值）。

        列表页只需摘要字段——store.read_session_summary 单趟流式扫描
        （头部早退 + 末行），不再全量解析每个 JSONL（30 会话 × 2000 事件
        曾需秒级串行解析，现约几十 ms）。损坏行走 store 内全量回退，摘要
        语义与旧实现严格一致。同步磁盘 I/O 仍走 to_thread 卸载。
        """
        service = SessionService(app.state.agent)
        try:
            summaries = await service.list_sessions(
                workspace_id=workspace_id, include_archived=include_archived
            )
        except WorkspaceNotFound as e:
            raise http_error(e) from e
        return [
            SessionSummary(
                session_id=s.session_id,
                event_count=s.event_count,
                first_event_time=s.first_event_time,
                last_event_time=s.last_event_time,
                first_user_message=s.first_user_message,
                trace_id=s.trace_id,
                trace_url=s.trace_url,
                # 领域值对象 → 传输模型（两者刻意同名不同物：前者无校验、不依赖
                # Pydantic；后者是契约与 OpenAPI schema 的定义点）。
                workspace=(
                    WorkspaceRef(id=s.workspace.id, title=s.workspace.title)
                    if s.workspace is not None
                    else None
                ),
                archived=s.archived,
            )
            for s in summaries
        ]

    @app.get("/api/sessions/{session_id}/events")
    async def get_session_events(session_id: str) -> list[dict]:
        """读历史 SessionEvent——前端刷新后从此重建视图（不变量 #22）。

        session_id 先过安全校验（名字段，不是路径）；store 读是同步磁盘 I/O，
        走 to_thread 卸载（同 list_sessions）。
        """
        service = SessionService(app.state.agent)
        try:
            events = await service.get_events(session_id)
        except (InvalidSessionId, SessionNotFound) as e:
            raise http_error(e) from e
        return [e.to_dict() for e in events]

    @app.get("/api/models")
    async def list_models() -> dict[str, Any]:
        """列出可选模型（ADR-0016 §5，C6 + SDD 03 §16 ModelOption）。

        绝不携带任何密钥字段；is_default=true 的条目 = 不传 model 参数时的链。
        思考能力不进元数据（D-B③ 事件驱动：模型真吐思考才有 reasoning 事件）。

        Phase 2 加法（SDD 03 §16）：每条返回能力位元数据，来源标注 metadata_source。
        - 默认链：能力位来自 PROVIDER_PRESETS → metadata_source="provider_preset"；
        - catalog 条目：条目显式声明的能力位优先，回落 preset；条目自身声明时
          metadata_source="agent_models"，否则（全靠 preset 回落）="provider_preset"。
        未知能力位省略（契约：「not guessed」）。旧字段 name/model/default 作为
        alias 保留（前端切换期间不破）。
        """
        state = app.state.agent
        default_config = ModelConfig.from_settings(state.settings)
        default_provider = state.settings.model_provider
        default_caps = _pick_capabilities(PROVIDER_PRESETS.get(default_provider, {}))
        models: list[dict[str, Any]] = [_render_model_option(
            id=default_config.model_name,
            provider=default_provider,
            model_name=default_config.model_name,
            is_default=True,
            capabilities=default_caps,
            metadata_source="provider_preset",
        )]
        for entry in parse_model_catalog(state.settings):
            # 与默认条目同 provider + 同名 = 被默认条目遮蔽（POST /model 会解析成
            # 「切回默认链」），列出来只会是选不中的死选项 → 不返回（T7 #137）。
            # 判据复用 resolve_model_target，不在这里重写一遍遮蔽规则。
            shadowed = resolve_model_target(
                state.settings, entry.provider, entry.name
            )
            if shadowed is not None and shadowed.model_id is None:
                continue
            declared = entry.declared_capabilities()
            preset_caps = _pick_capabilities(PROVIDER_PRESETS.get(entry.provider, {}))
            # catalog 声明优先，preset 回落。metadata_source：条目声明了任何能力位
            # → agent_models；否则（全靠 preset）→ provider_preset。
            merged = {**preset_caps, **declared}
            source = "agent_models" if declared else "provider_preset"
            models.append(_render_model_option(
                id=entry.name,
                provider=entry.provider,
                model_name=entry.model_name,
                is_default=False,
                capabilities=merged,
                metadata_source=source,
            ))
        return {"models": models}

    @app.get("/api/permission-modes")
    async def list_permission_modes() -> dict[str, Any]:
        """列出后端能真实执行的权限模式（SDD 03 §10，Phase 2 加法）。

        返回 PermissionPolicy 全集 + 人类可读描述。诚实标注：当前 Web 层
        auto_approve 默认开（同步 callback），交互式审批是 Phase 5 的工作——
        这里只暴露「后端认识哪些 mode」，不假装审批已就绪。
        """
        modes = [
            {
                "id": policy.value,
                "display_name": desc["display_name"],
                "description": desc["description"],
            }
            for policy, desc in PERMISSION_MODE_DESCRIPTIONS.items()
        ]
        return {"modes": modes}

    @app.get("/api/capabilities")
    async def list_capabilities() -> dict[str, Any]:
        """列出 capability manifest：**内置工具集（core）+ 已装配的插件 capability**（SDD 03 §17）。

        **core 条目恒在且排在最前**（`capability/manifest.py`）：`changes`（「文件/改动」）与
        `terminal`（「输出」）两个面由内置工具（`write`/`edit`/`apply_patch`/`bash`）产出，
        而它们**不由任何插件 capability 产出**——只投影插件 descriptor 时，未声明 `surfaces`
        的保守默认会让这两个面在**所有**真实部署里被前端 `centerTabs` 滤掉（#193）。

        插件条目：无 `surfaces` 声明 → 保守默认（`chat`/`timeline` = true，其余 false）；
        显式声明 → 以声明为准（局部声明**不补齐**，契约里 `actions` 是可选局部字典）。
        条目级**不做并集**——取并集是前端的事（`capabilities.ts::deriveSurfaces`），
        两处都算一遍就等于有两个口径。

        条目形状在**后端侧**只有 `capability/manifest.py` 一份（此前内联在本函数里，
        core 一加入就会变成两份）。说清楚边界，免得把"一份"当成跨仓保证：
        前端的键集与缺省（`web/src/lib/capabilities.ts::SURFACE_KEYS` / `DEFAULT_SURFACES`、
        e2e 的 `web/e2e/fixtures.ts::CORE_CAPABILITY`）是**手工镜像**——跨语言、跨仓，
        改这里不会自动同步过去。两端各有测试锁着同一份值
        （后端 `tests/web/test_web_phase2_endpoints.py::TestCapabilities`，
        前端 `web/src/lib/capabilities.test.ts` + `workspace-modes.spec.ts`），
        改声明时两边一起改。
        """
        state = app.state.agent
        registry, _wiring = await state.get_wiring()
        return {
            "capabilities": [
                core_manifest_entry(),
                *[descriptor_manifest_entry(d) for d in registry.available()],
            ],
        }

    @app.get("/api/reasoning-efforts")
    async def list_reasoning_efforts() -> dict[str, Any]:
        """列出 reasoning_effort 可选档位（Ticket B1，SDD 03 §16 对齐 Phase 5）。

        reasoning_effort 已被运行时真实消费：harness 语义档位经
        create_chat_model 翻译为 provider 线格式枚举后注入（翻译表在
        model/provider.py）；本端点暴露「后端认识哪些档位」。
        字段与 /api/permission-modes 同模式（{id, display_name, description}），
        单一事实源是模块级 REASONING_EFFORT_DESCRIPTIONS（validator 与清单
        引用同一份 → 永不漂移）。
        """
        efforts = [
            {
                "id": effort_id,
                "display_name": desc["display_name"],
                "description": desc["description"],
            }
            for effort_id, desc in REASONING_EFFORT_DESCRIPTIONS.items()
        ]
        return {"efforts": efforts}

    @app.get("/api/agent-profiles")
    async def list_agent_profiles() -> dict[str, Any]:
        """列出 agent_profile 可选档位（Ticket B1，SDD 03 §16 对齐 Phase 5）。

        同 reasoning-efforts：Phase 5 staged 契约的清单投影，运行时 no-op 不变。
        字段与 /api/permission-modes 同模式，单一事实源是 AGENT_PROFILE_DESCRIPTIONS。
        """
        profiles = [
            {
                "id": profile_id,
                "display_name": desc["display_name"],
                "description": desc["description"],
            }
            for profile_id, desc in AGENT_PROFILE_DESCRIPTIONS.items()
        ]
        return {"profiles": profiles}

    @app.get("/api/context-providers")
    async def list_context_providers() -> dict[str, Any]:
        """列出已装配的 context provider 清单（ADR-0020b 运行时消费）。

        动态投影 ``wiring.context_providers`` 的 ``name`` 属性（与
        MemoryContextProvider.name / SkillCatalogContextProvider.name 对齐）。
        display_name / description 从 CONTEXT_PROVIDER_DESCRIPTIONS 取——
        清单端点与 POST /api/sessions 共用同一 id 集合。

        未装配任何 capability（bare 配置）→ wiring.context_providers 为空 →
        返 ``{"providers": []}``（未装配就不编条目，不伪造基础项）。前端据空列表自行 fallback。
        注意与 ``/api/capabilities`` 的区别：那边**恒有一条 core 条目**（内置工具集的声明，
        见 `capability/manifest.py` / #193），因为内置工具真的在每个会话里；这里没有对应的
        "内置 Context Provider"——没装配就是空。
        """
        state = app.state.agent
        _, wiring = await state.get_wiring()
        providers: list[dict[str, Any]] = []
        for provider in wiring.context_providers:
            name = getattr(provider, "name", None)
            if not isinstance(name, str) or not name:
                # 未声明 name 的 provider（未来情况）不出现在清单——
                # 清单端点是稳定 id 契约，不暴露匿名项。
                continue
            desc = CONTEXT_PROVIDER_DESCRIPTIONS.get(name)
            providers.append({
                "id": name,
                "display_name": (desc["display_name"] if desc else name),
                "description": (desc["description"] if desc else ""),
            })
        return {"providers": providers}

    @app.post("/api/sessions")
    async def create_session(req: CreateSessionRequest):
        """起新 session + 跑任务，流式返回 AgentEvent（SSE）。

        ADR-0016 §2.1（D-A）：run 由 RunManager 以 detached task 驱动，与
        本次 HTTP 请求生命周期解耦——断连（本 generator 被取消）只做
        unsubscribe，run 继续跑到终态；显式取消走 POST /cancel。
        """
        service = SessionService(app.state.agent)
        state = app.state.agent

        # context_providers handler-level 422（ADR-0021 模式，适配 ADR-0020b 的
        # name 属性机制）：validator 无法访问 AppState/wiring（Pydantic parse 早于
        # handler），故在 handler 内对 wiring 真实装配的 id 集合校验——与 model
        # 字段的 from_catalog 422 模式一致。未知 id → 422 + 可用清单。
        await _validate_wired_context_providers(state, req.context_providers)

        permission_mode = PermissionPolicy(req.permission_mode)
        permission_mode_explicit = "permission_mode" in req.model_fields_set
        auto_approve_explicit = "auto_approve" in req.model_fields_set

        try:
            result = await service.create_and_launch(
                task=req.task,
                workspace_name=req.workspace,
                cwd=req.cwd,
                max_steps=req.max_steps,
                permission_mode=permission_mode,
                permission_mode_explicit=permission_mode_explicit,
                auto_approve_explicit=auto_approve_explicit,
                auto_approve=req.auto_approve,
                amend=AmendOptions.from_request(req),
            )
        except (WorkspaceNameInvalid, InvalidDecision) as e:
            raise http_error(e) from e

        session, run, subscriber = result.session, result.run, result.subscriber

        async def event_generator():
            """SSE 事件源：消费订阅队列，转成 SSE 帧。

            断连时 EventSourceResponse 取消本 generator → finally unsubscribe
            （run 不受影响）；run 终结 → sentinel → 流干净收尾。
            """
            try:
                while True:
                    event = await subscriber.queue.get()
                    if event is state.run_manager.DONE:
                        break
                    yield _event_to_sse_dict(event, session.session_id)
            finally:
                run.unsubscribe(subscriber)

        return EventSourceResponse(event_generator())

    @app.get("/api/sessions/{session_id}/stream")
    async def stream_session(session_id: str, after_seq: int = -1):
        """重连续传（ADR-0016 §2.3，C4/C5）：重放 durable 事实 + 接上在途流。

        客户端维护 lastAppliedSeq，断线后带 after_seq 重连：
        1. session 无事件 → 404；
        2. 重放 durable 事件（after_seq < seq ≤ replay_upto，按 seq 序）；
        3. backlog 超过 STREAM_REPLAY_MAX_EVENTS → 单帧 stream/truncated
           控制事件（无 seq，非运行事实）后收流——客户端走 GET /events
           全量重建后带 after_seq=latest_seq 重连；
        4. run 在途 → 接上 live 流（先订阅后取游标，保证重放与 live 无缝
           无重复）；run 已终态/不在途 → 重放到 latest 后正常收尾
           （崩溃遗留的悬空 run 不伪造终态，修复走 POST /recover）。
        客户端对重放帧与 live 帧做同一 seq 幂等投影（C5）。
        """
        service = SessionService(app.state.agent)
        try:
            handle = await service.stream_reconnect(
                session_id=session_id,
                after_seq=after_seq,
                max_replay_events=STREAM_REPLAY_MAX_EVENTS,
            )
        except (InvalidSessionId, SessionNotFound) as e:
            raise http_error(e) from e

        events = handle.events
        latest_seq = handle.latest_seq
        run = handle.run
        subscriber = handle.subscriber
        replay_upto = handle.replay_upto
        state = app.state.agent

        if latest_seq - after_seq > STREAM_REPLAY_MAX_EVENTS:
            async def truncated_generator():
                control = {
                    "type": "stream/truncated",
                    "data": {"after_seq": after_seq, "latest_seq": latest_seq},
                    "seq": None, "run_id": None, "step_id": None,
                    "session_id": session_id,
                    "schema_version": RUNTIME_EVENT_SCHEMA_VERSION,
                    "durability": "transient",
                }
                yield {"data": json.dumps(control, ensure_ascii=False)}

            return EventSourceResponse(truncated_generator())

        async def event_generator():
            try:
                for event in events:
                    if after_seq < event.seq <= replay_upto:
                        yield _session_event_to_sse_dict(event, session_id)
                if subscriber is None:
                    return
                while True:
                    item = await subscriber.queue.get()
                    if item is state.run_manager.DONE:
                        break
                    if item.seq is not None and item.seq <= replay_upto:
                        continue  # 重放已覆盖（订阅与取游标窗口内的入队）
                    yield _event_to_sse_dict(item, session_id)
            finally:
                if subscriber is not None and run is not None:
                    run.unsubscribe(subscriber)

        return EventSourceResponse(event_generator())

    @app.post("/api/sessions/{session_id}/resume")
    async def resume_session(session_id: str, req: ResumeRequest):
        """最小 Resume（Phase 5）：重建 Session 后追加一轮新 user input。

        这是「续跑」而非精确恢复中断 run：Session.resume() 重建 append-only
        历史与 dangling 修复，RunManager.launch 驱动一轮新的 Agent Loop。
        在途 session 拒绝 409，避免同一 session 并发两轮。
        """
        service = SessionService(app.state.agent)
        amend = AmendOptions.from_request(req)
        await _validate_amend_for_existing_session(app.state.agent, amend)
        try:
            result = await service.resume_and_launch(
                session_id=session_id,
                task=req.task,
                amend=amend,
            )
        except (
            InvalidSessionId,
            SessionNotFound,
            ActiveRunConflict,
            RecoveryConflict,
            SeqConflict,
        ) as e:
            # RecoveryConflict → 409（T8 #138）：崩溃遗留需人工裁决的 UNKNOWN
            # tool_call，不伪造结果（不变量 #14）。
            raise http_error(e) from e

        session_id = result.session.session_id
        run, subscriber = result.run, result.subscriber
        state = app.state.agent

        async def event_generator():
            try:
                while True:
                    event = await subscriber.queue.get()
                    if event is state.run_manager.DONE:
                        break
                    yield _event_to_sse_dict(event, session_id)
            finally:
                run.unsubscribe(subscriber)

        return EventSourceResponse(event_generator())

    @app.post("/api/sessions/{session_id}/cancel")
    async def cancel_session(session_id: str) -> dict[str, str]:
        """显式取消在途 run（ADR-0016 §2.2，D-A）：前端 Esc/停止的唯一取消通道。

        detached-run 下断连不再取消——本端点是仅有的两个外部终止路径之一
        （另一个是孤儿回收）。语义：在途 → 200 cancelling；无在途 run →
        200 no_active_run（幂等成功：用户按 Esc 与 run 恰好刚终结的竞态是
        常态不是错误）；session 不存在 → 404。取消与失败不混淆（02 §17）：
        run/failed data.reason=cancelled，与异常臂（无 reason）、孤儿回收
        （reason=orphaned）区分。
        """
        service = SessionService(app.state.agent)
        try:
            cancelled = await service.cancel(session_id)
        except (InvalidSessionId, SessionNotFound) as e:
            raise http_error(e) from e
        return {"status": "cancelling" if cancelled else "no_active_run"}

    @app.post("/api/sessions/{session_id}/archive")
    async def archive_session(
        session_id: str, _: None = Depends(require_trusted_origin)
    ) -> SessionArchived:
        """归档会话（#171）：把它从默认列表里收起来，**可逆**、不删任何东西。

        与 `DELETE /api/sessions/{id}`（硬删）刻意分成两个动作：归档只写
        `session_meta.archived` 一个标记——事件日志、项目账本、checkpoint、沙箱工件
        全部原样（spec 03 的 Full SessionEvent History 约束），所以入口层不需要二次
        确认；硬删不可逆，才需要确认面。

        语义：200 → `{id, archived: true}`（**幂等**：已归档再归档仍是 200）；
        404 → 没有这个会话；409 → 有在途 run（`get_active`，详情说明"运行中的会话不能
        归档"）；422 → id 形态非法。取消归档走 `DELETE`（同路径），且**不**因在途 run
        拒绝——它只是把行放回列表。

        动词选择：本仓既有会话端点一律显式动词（`resume`/`cancel`/`approve`/`recover`/
        `model`），不用泛化 PATCH。

        来源闸（ADR-0025 D1）：归档改的是宿主侧列表可见性，只接受本机来源
        （与项目 / 目录 / 记忆 / 工作区端点同一份实现）。
        """
        service = SessionService(app.state.agent)
        try:
            archived = await service.set_archived(
                session_id, archived=True, entry_point=ARCHIVE_ENTRY_API
            )
        except (InvalidSessionId, SessionNotFound, ActiveRunConflict) as e:
            raise http_error(e) from e
        return SessionArchived(id=session_id, archived=archived)

    @app.delete("/api/sessions/{session_id}/archive")
    async def unarchive_session(
        session_id: str, _: None = Depends(require_trusted_origin)
    ) -> SessionArchived:
        """取消归档（#171）：把会话放回默认列表。

        语义：200 → `{id, archived: false}`（幂等）；404 → 没有这个会话；422 → id
        形态非法。**没有 409**：把行放回列表不破坏任何人的前提，在途 run 也无所谓
        （见 `SessionService.set_archived` 里那条非对称的理由）。
        """
        service = SessionService(app.state.agent)
        try:
            archived = await service.set_archived(
                session_id, archived=False, entry_point=ARCHIVE_ENTRY_API
            )
        except (InvalidSessionId, SessionNotFound) as e:
            raise http_error(e) from e
        return SessionArchived(id=session_id, archived=archived)

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(
        session_id: str, _: None = Depends(require_trusted_origin)
    ) -> SessionDeleted:
        """硬删会话（#172 / ADR-0029）：不可撤销，无墓碑。

        用户显式要求的删除——与「系统不得静默丢弃历史」（spec 03 §Full SessionEvent
        History）不冲突：那条约束管的是**系统**不许偷删，不是用户不许删自己的会话。

        语义：200 → 事件日志 + 辅助行 + harness 自造的沙箱工件都清了，回执带事件数与
        解除的项目数；404 → 没有这个会话（第二次删除即此，不伪装成"又删了一次"）；
        409 → 有在途 run，或有 fork 子会话（detail 带子会话数量）；422 → id 形态非法。
        项目归属只解账本，**项目本身与目录一个字不动**（与软删项目的口径一致）。

        来源闸（ADR-0025 D1）：删除是宿主侧不可逆操作，只接受本机来源。
        """
        service = SessionService(app.state.agent)
        try:
            stats = await service.delete_session(session_id)
        except (
            InvalidSessionId,
            SessionNotFound,
            ActiveRunConflict,
            SessionHasChildren,
        ) as e:
            raise http_error(e) from e
        return SessionDeleted(
            id=stats.session_id,
            events=stats.events,
            detached_from_projects=stats.detached_from_projects,
        )

    @app.get("/api/sessions/{session_id}/artifacts/{artifact_id}")
    async def read_artifact_content(
        session_id: str,
        artifact_id: str,
        start_line: int | None = None,
        end_line: int | None = None,
        keyword: str | None = None,
        max_lines: int = artifacts.MAX_LINES_CAP,
        max_chars_per_line: int = artifacts.MAX_CHARS_PER_LINE_CAP,
    ) -> dict[str, Any]:
        """读取外置 artifact 的局部内容（#185）。

        外置产物是**被截断的大工具输出 / 大 diff**：工具结果超过
        `artifact_overflow_chars` 时原文落到对象存储，会话里只留"摘要 + ref"（不变量
        #15：大内容外置，模型只拿 summary + ref）。本端点把模型侧同一个读入口
        （`ArtifactStore.inspect`）暴露给 Web，让界面能真的看到那段内容。

        状态码语义：

        - 422 → `session_id` 或 `artifact_id` 形态非法（客户端 bug，不是冲突）；
        - 404 → 会话不存在，或该 artifact 不在这个会话的命名空间里。**别的会话的
          产物也走这条**：`artifact_id` 是内容哈希、跨会话可重复，区分"不存在"与
          "存在但不可读"只会把归属变成可探测的信息；
        - 503 → 本部署**确实没有可读取的存储**（`artifact_dir` 置空、或对象存储半配置）
          ——**如实上报**，不假装成 404：那会让用户以为"这个产物不存在"；
        - 200 → 切片，`truncated` 如实表示返回内容是否完整。

        ⚠ #192 之后 404 的含义变宽了：未配对象存储的部署现在走**本地**默认 Provider
        （spec 06 §3），它**能读**，只是里面没有这个 id ⇒ 404。503 只留给"真的没有可读
        存储"这一种情形。

        隔离靠"**用 URL 里的 session_id 构造 store**"：provider 的 key 前缀是
        `{session_id}/{artifact_id}`，而 artifact_id 不携带归属，归属只能由
        session_id 决定。

        体积上限由**服务端**兜底：客户端给再大也会被夹进上限。`max_lines` 夹取后的
        **实际生效值**在 `query.max_lines` 里回显；`max_chars_per_line` 同样按服务端
        上限执行（`ArtifactSlice.query` 不携带该字段，故不回显）。行号从 1 开始，
        `start_line` / `end_line` < 1 一律 422——与模型侧 `inspect_artifact` 的
        schema（`ge=1`）保持同一口径。
        """
        state = app.state.agent
        try:
            validate_session_id(session_id)
        except InvalidSessionId as e:
            raise http_error(e) from e
        if not artifacts.ARTIFACT_ID_PATTERN.fullmatch(artifact_id):
            raise HTTPException(
                status_code=422,
                detail=(
                    "artifact_id 必须是 16 位小写十六进制（内容哈希前 16 位）："
                    f"{artifact_id!r}"
                ),
            )
        for name, value in (("start_line", start_line), ("end_line", end_line)):
            if value is not None and value < 1:
                raise HTTPException(
                    status_code=422,
                    detail=f"{name} 必须 >= 1（行号从 1 开始计数）：{value}",
                )
        if not await SessionService(state).has_session(session_id):
            raise http_error(SessionNotFound(f"session '{session_id}' not found"))
        store = artifacts.build_read_artifact_store(state.settings, session_id)
        if store is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "本部署没有可读取的 artifact 存储：artifact_dir 为空，或对象存储只配了一半"
                ),
            )
        try:
            slice_ = await store.inspect(
                artifact_id,
                start_line=start_line,
                end_line=end_line,
                keyword=keyword,
                max_lines=artifacts.clamp_to_cap(max_lines, artifacts.MAX_LINES_CAP),
                max_chars_per_line=artifacts.clamp_to_cap(
                    max_chars_per_line, artifacts.MAX_CHARS_PER_LINE_CAP
                ),
            )
        except KeyError as e:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"artifact {artifact_id!r} 不在会话 {session_id!r} 的命名空间里"
                    "（不存在，或属于别的会话）"
                ),
            ) from e
        return slice_.model_dump()

    @app.post("/api/sessions/{session_id}/approve")
    async def approve_tool_call(session_id: str, req: ApproveRequest) -> dict[str, str]:
        """交互式审批决策入口（Phase 5 切片 C + Batch 5.1）：前端拿到
        tool/approval-requested 事件后，调本端点注入批准/拒绝决策，唤醒 run
        内阻塞的 callback。

        语义：
          成功 resolve → 200 ok（run 在 callback 处继续；resolved 事件由 callback 写入）
          decision 不在 requested 事件的 allowed_decisions 内 → 422（违反契约）
          approval_id 已 resolved → 409（防重复决策；幂等性拒绝）
          approval_id 不存在 → 404（前端过期事件或非本 session 的 id）
          无 approval_id（旧 seam 调用）→ 200 received（向后兼容）
          session 不存在 → 404
        """
        if req.approval_id is None:
            # 旧 seam 入口（Phase 2 阶段性占位）：不解析任何决策，仅回 200 信号；
            # 不要求 session 存在——Phase 2 seam 测试用任意 id 探活。
            return {
                "status": "received",
                "note": "auto-approve is default; interactive approval via approval_id",
            }
        service = SessionService(app.state.agent)
        try:
            result = await service.resolve_approval(
                session_id=session_id,
                approval_id=req.approval_id,
                approved=req.approved,
                decision=req.decision,
                reason=req.reason,
            )
        except (
            InvalidSessionId,
            SessionNotFound,
            ApprovalQueueMissing,
            ApprovalRequestMissing,
            InvalidDecision,
            ApprovalAlreadyResolved,
        ) as e:
            # 三个 404（SessionNotFound / ApprovalQueueMissing /
            # ApprovalRequestMissing）**有意不可区分**；ApprovalAlreadyResolved
            # 是 409 幂等已决（OBS-015）。状态码见 web/domain_errors.py。
            raise http_error(e) from e
        return {
            "status": "resolved",
            "approval_id": req.approval_id,
            "decision": result.decision.value,
        }

    @app.post("/api/sessions/{session_id}/recover")
    async def recover_session(session_id: str) -> list[dict]:
        """恢复崩溃 session（R8-1 接线）：RecoveryCoordinator 唯一入口（07 §9）。

        修复 dangling tool_call（配对合成）、按 Ledger 终态精确回填结果、
        PENDING 默认 skip；RUNNING/UNKNOWN 需要人工裁决时返回 409（不伪造、
        不盲跑，不变量 #14）。幂等：重复调用靠事件配对自然跳过已修复项。
        """
        service = SessionService(app.state.agent)
        try:
            events = await service.recover(session_id)
        except (InvalidSessionId, SessionNotFound, RecoveryConflict, SeqConflict) as e:
            # RecoveryConflict → 409：RUNNING/UNKNOWN 需人工裁决，不伪造不盲跑
            # （不变量 #14）。SeqConflict → 409：日志 seq 冲突（BUG-011）。
            raise http_error(e) from e
        return [e.to_dict() for e in events]

    # ── 模型切换（T7 #137，PRD §2.3）───────────────────────────────────
    # fork 创建端点在 web/lineage.py（ADR-0017 决策 6 的独立 router 面）。

    @app.post("/api/sessions/{session_id}/model")
    async def change_session_model(
        session_id: str, req: ModelChangeRequest
    ) -> dict[str, str]:
        """切换会话当前模型并写 ``model/changed``（PRD §2.3）。

        下一轮 run 从事件流派生当前模型生效（不打断在途 run）。
        404 = session 不存在；422 = provider/model_id 不在 catalog
        （``GET /api/models`` 的默认条目也是合法目标 = 切回默认链）。
        """
        service = SessionService(app.state.agent)
        try:
            change = await service.change_model(
                session_id=session_id,
                provider=req.provider,
                model_id=req.model_id,
            )
        except (InvalidSessionId, SessionNotFound, UnknownModel, SeqConflict) as e:
            raise http_error(e) from e
        # 回传规范 model_id（service 解析出的 picker id）：catalog 条目名，或默认链
        # 的默认模型名——不能回显请求值，否则上游 model_name / "default" 别名会与
        # 事件里的 to_model_id 及 GET /api/models 的 id 对不上。
        return {
            "status": "changed",
            "provider": change.to_provider,
            "model_id": change.effective_model_id,
        }

    # ── 续聊入口（PRD §5.3）───────────────────────────────────────────
    # 双模式：queue（默认）= 入队/直接拉起；steer = 注入在途 run。
    # launched 分支返回 SSE 流（PRD 锁定 D-10：续聊端点响应与创建端点一致）；
    # queued / steered 分支返回 JSON 确认（不打开流，前端订阅既有 SSE/WS）。
    @app.post("/api/sessions/{session_id}/messages")
    async def send_message(session_id: str, req: SendMessageRequest):
        """续聊消息入口（Phase Multiturn T2 / PRD §5.3）。

        ``mode=queue``：空闲 → 直接 resume_and_launch 拉起新 run，返回
        SSE 流（同创建端点语义）；在途 → 入队并返回 JSON 确认。
        ``mode=steer``：仅在途 run 时合法——注册 SteerRequest 并返回
        JSON 确认；无在途 run → 409（steer 必须有目标）。
        """
        service = SessionService(app.state.agent)
        amend = AmendOptions.from_request(req)
        # 契约（handoff §3.1 / P3）：只有 idle → launched 才消费 amend；在途 run
        # 的 queued 消息与 steer 一律忽略这些字段。因此引用类字段（model /
        # context_providers，取值集合来自运行时 catalog / wiring，可能已失效）
        # 只在这条路径上校验——否则一个失效引用会 422 掉用户刚敲的消息。
        # 值/形状类字段（reasoning_effort / agent_profile / context_providers 形状）
        # 由 Pydantic 在 parse 期校验，与是否消费无关（静态集合，非法值即客户端 bug）。
        if (
            req.mode == "queue"
            and app.state.agent.run_manager.get_active(session_id) is None
        ):
            await _validate_amend_for_existing_session(app.state.agent, amend)
        else:
            # 未被消费：按契约丢弃（与改动前 send_message 的忽略语义一致）。
            amend = AmendOptions()
        try:
            result = await service.send_message(
                session_id=session_id,
                content=req.content,
                mode=req.mode,
                max_steps=req.max_steps,
                amend=amend,
            )
        except (
            InvalidSessionId,
            SessionNotFound,
            ActiveRunConflict,
            RecoveryConflict,
            QueueItemNotFound,
            SteerTargetNotFound,
            SeqConflict,
        ) as e:
            # RecoveryConflict → 409（T8 #138）：崩溃遗留（UNKNOWN 高风险
            # tool_call）需人工裁决——拒绝续跑而不是伪造「结果未知」（不变量 #14）。
            raise http_error(e) from e

        if result.status == "launched":
            # 与创建端点同形：SSE 直驱 run（ADR-0016 detached-run）。
            run = result.run
            subscriber = result.subscriber
            state = app.state.agent

            async def event_generator():
                try:
                    while True:
                        event = await subscriber.queue.get()
                        if event is state.run_manager.DONE:
                            break
                        yield _event_to_sse_dict(event, session_id)
                finally:
                    run.unsubscribe(subscriber)

            return EventSourceResponse(event_generator())
        # queued / steered：JSON 确认（不打开流——前端订阅既有 SSE/WS）。
        return result.to_response()

    @app.post("/api/sessions/{session_id}/queue/{queue_id}/cancel")
    async def cancel_queue_item(session_id: str, queue_id: str) -> dict[str, str]:
        """取消尚未消费的排队消息（PRD §5.3 / D-7）。

        语义：取消成功 → 200 cancelled；queue_id 已取消 / 已消费 /
        不存在 → 404；session 不存在 → 404。幂等失败（防覆盖式重置语义）。
        """
        service = SessionService(app.state.agent)
        try:
            cancelled = await service.cancel_queue(
                session_id=session_id, queue_id=queue_id
            )
        except (InvalidSessionId, SessionNotFound, QueueItemNotFound, SeqConflict) as e:
            raise http_error(e) from e
        return {"status": "cancelled" if cancelled else "already_consumed"}

    # ── WebSocket 多路复用通道（T2 / PRD §5.1）──────────────────────
    # 主 streaming 通道：单连接订阅多个 session、推增量事件；
    # 心跳 ping/pong；断线重连先推快照再增量。SSE 保留为灰度兼容路径。
    # 不维护第二套 session 真相（不变量 #22）——所有事件源于 RunManager 订阅。
    from agent_harness.web.websocket import handle_websocket

    @app.websocket("/api/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """WS 主入口（PRD §5.1）：接受连接后交由 handle_websocket 多路复用。

        WS 只做传输——业务决策一律走 SessionService。WebSocketDisconnect
        是正常客户端断开，吞掉不打日志。
        """
        try:
            await handle_websocket(websocket, app.state.agent)
        except WebSocketDisconnect:
            # 正常断开：客户端关页 / 重连切换。
            return

    return app


def mount_static(app: FastAPI) -> None:
    """挂载前端构建产物为静态资源。

    独立于 ``create_app`` —— 测试在 ``create_app`` 返回后追加的自定义路由
    （如 ``/identity-probe``）不会被 StaticFiles Mount 遮蔽。生产部署由
    uvicorn ``--factory`` 调 ``create_prod_app``（= ``create_app`` +
    ``mount_static``)，或由反向代理直接服务静态资源、仅将 ``/api``
    转发到本服务。

    部署约束：静态挂载只适配本地信任模式（未配置 JWT_SECRET）。fail-closed
    生效时全量默认拒绝（test_auth_fail_closed 契约），而浏览器顶层导航无法
    携带 Bearer——index.html 都会 401。生产 + JWT 的支持形态是反向代理：
    静态资源在代理层直出，仅 /api 转发到本服务（前端带 Bearer 调用）。
    """
    web_dist = Path(__file__).resolve().parent.parent.parent.parent / "web" / "dist"
    if web_dist.exists():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="static")


def create_prod_app(settings: Settings | None = None) -> FastAPI:
    """生产工厂：``create_app`` + ``mount_static``。

    dev.sh / Dockerfile 用 ``uvicorn agent_harness.web.app:create_prod_app
    --factory``；测试仍直调 ``create_app``——不挂静态资源，避免 Mount
    遮蔽测试后加的 probe 路由。
    """
    app = create_app(settings, enable_cors=True)
    mount_static(app)
    return app
