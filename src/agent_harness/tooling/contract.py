"""Tool Contract：Tool 的身份、Schema、执行入口与策略元数据。

为什么用 ABC（抽象基类）而不是 Pydantic BaseModel：
- Tool 有【行为】（execute 方法），不只是数据。Pydantic 模型装不下抽象方法。
- Tool 是"接口契约"，子类填实现；ABC 表达这层意图最直接。
- 对比 ToolResult：ToolResult 是纯数据 + 序列化，所以用 Pydantic。

为什么 execute 收的是【已校验的 Pydantic 实例】而不是 dict：
- 主链是 args_schema.model_validate(args) → execute(validated_args)。
- 校验发生在执行前（Task 2 实现），所以 execute 拿到的必定是合法实例，
  无需在 execute 内再判一次参数。
- 今天（Task 1）execute 只是"被定义"，Executor 还不会调它。
"""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel

from agent_harness.tooling.reconcile import ReconcileHint
from agent_harness.tooling.result import ToolResult


@dataclass(frozen=True, slots=True)
class ToolCall:
    """一次模型工具调用的值对象：id / name / args 的唯一形状。

    LangChain AIMessage.tool_calls 是 list[dict]；在 ToolExecutor 边界一次性
    归一化成本对象，之后所有消费者（批次调度/审批/Ledger/runtime 回填）读
    类型化字段，不再各自做 tc.get("id", "") 防御式拆包。缺键/None 归一为
    "" / {}（部分本地模型会这么吐）。
    """

    id: str
    name: str
    args: dict[str, Any]

    @classmethod
    def normalize(cls, tool_call: ToolCall | dict[str, Any]) -> ToolCall:
        if isinstance(tool_call, ToolCall):
            return tool_call
        raw_id = tool_call.get("id") or ""
        # 缺 id / 空串 id 不能让它坍缩成 ""——下游 Ledger 以 tool_call_id 为主键、
        # ToolMessage 协议要求与 assistant 严格配对，空串会引发互相覆盖和配对错位。
        # 降级为带前缀的唯一占位（uuid4 保证跨次唯一，非幂等：normalize 处于
        # Runtime 入站边界，只跑一次，不重放；若未来需要对账幂等 id，应改内容哈希）。
        if not raw_id:
            raw_id = f"gen_{uuid.uuid4().hex[:12]}"
        return cls(
            id=raw_id,
            name=tool_call.get("name") or "",
            args=tool_call.get("args") or {},
        )

    @classmethod
    def normalize_all(cls, tool_calls: Iterable[ToolCall | dict[str, Any]]) -> list[ToolCall]:
        """批量归一化 + id 去重：重复的非空 id 与缺 id 同样破坏下游
        （Ledger 主键冲突、_validate_tool_blocks 拒绝投影 → session 永久
        无法压缩）。保留首个原 id，其余合成 gen_ 唯一占位（与缺 id 同策略）。"""
        normalized: list[ToolCall] = []
        seen: set[str] = set()
        for tc in tool_calls:
            call = cls.normalize(tc)
            if call.id in seen:
                call = ToolCall(
                    id=f"gen_{uuid.uuid4().hex[:12]}", name=call.name, args=call.args,
                )
            seen.add(call.id)
            normalized.append(call)
        return normalized


class ToolSideEffect(str, Enum):
    """Tool 副作用分类。

    为什么是 str Enum：JSON 序列化与日志可读性，与 ErrorCode 同理。

    为什么只两类，不做 READ/WRITE/DELETE 细分：
    - 批次调度的可解释规则只依赖"是否改变外部状态"这一条。
    - 更细的读写冲突分析属复杂 DAG，Day04 明确不做（V1 Backlog）。
    """

    READ_ONLY = "READ_ONLY"  # 不改外部状态 → 批次可并发（Task 4）
    MUTATING = "MUTATING"  # 改外部状态 → 整批串行（Task 4）


class PermissionPolicy(str, Enum):
    """Session 级权限策略——Agent 在这个 Session 里的最大权限边界。

    05_SANDBOX_CODING_TOOLS.md §6 的三层 Permission Policy（参考 DeepSeek Harness）。
    与 ToolSideEffect 正交：side_effect 驱动调度（并发/串行），
    PermissionPolicy 驱动授权（允许/审批/拒绝）。
    """

    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    DANGER_FULL_ACCESS = "danger-full-access"


#: 各权限模式的可读描述（SDD 03 §10，Phase 2 加法）：用于 GET /api/permission-modes
#: 端点向前端暴露「后端能真实执行的 mode 列表」+ 人类可读说明。如实描述，
#: 不假装交互式审批已就绪（那是 Phase 5）。display_name 给 UI 标签，description 给 tooltip。
PERMISSION_MODE_DESCRIPTIONS: dict[PermissionPolicy, dict[str, str]] = {
    PermissionPolicy.READ_ONLY: {
        "display_name": "只读",
        "description": "可读文件和运行只读工具，不可写入。",
    },
    PermissionPolicy.WORKSPACE_WRITE: {
        "display_name": "工作区写入",
        "description": "可读写工作区内文件；高危工具仍需审批。",
    },
    PermissionPolicy.DANGER_FULL_ACCESS: {
        "display_name": "完全访问",
        "description": "所有工具无需审批，含网络/系统副作用。仅在可信环境使用。",
    },
}


class ToolPermission(str, Enum):
    """单个 Tool 的授权级别——这个工具需要什么级别的权限才能执行。

    与 PermissionPolicy 对齐但不完全相同：Tool 声明自己需要什么级别，
    ToolExecutor 检查 Session 的 PermissionPolicy 是否覆盖该级别。
    """

    READ_ONLY = "read-only"  # 读操作：read/grep/glob/git_status/git_diff
    WORKSPACE_WRITE = "workspace-write"  # workspace 内写：write/edit/apply_patch
    DANGER = "danger"  # 高风险：bash（可配网络/系统副作用）


class Tool(ABC):
    """Tool Contract：模型 Schema 与 Runtime Tool 的共同来源。

    子类必须实现：name / description / args_schema / execute。
    可选覆写：timeout_seconds / side_effect（有安全默认值）。
    """

    #: SubAgent 委派标记（ADR-0018 D5）：True 的工具在 Langfuse 侧用 ``agent``
    #: 型观测 + 具体目标命名（绝不用 tool/span 隐藏 SubAgent 结构），且其执行
    #: 期间设置嵌套 trace 绑定——child run 的观测挂到同一 trace 下。
    is_subagent_dispatch: bool = False

    # —— 必填字段（身份 + Schema + 行为） ——
    @property
    @abstractmethod
    def name(self) -> str:
        """Tool 的稳定标识。Runtime 按它查找；模型按它发起 tool_call。"""

    @property
    @abstractmethod
    def description(self) -> str:
        """给模型看的行为说明。

        【行为控制】不是装饰：它影响模型【何时】选这个 Tool、【怎么】填参数。
        应写清三要素：做什么、什么时候用、参数含义。今天学会写清即可。
        """

    @property
    @abstractmethod
    def args_schema(self) -> type[BaseModel]:
        """Tool 参数的 Pydantic 类（注意是类本身，不是实例）。

        【单一事实源根】：
        - Registry 用 args_schema.model_json_schema() 导出给模型的 JSON Schema；
        - Executor 用 args_schema.model_validate(args) 校验模型回的参数；
        - 同一个类两边复用，避免"模型按 A 参数调用、执行端期待 B 参数"的漂移。
        """

    @abstractmethod
    async def execute(self, args: BaseModel) -> ToolResult:
        """执行 Tool，返回结构化 ToolResult。

        参数是【已校验】的 Pydantic 实例（由 Executor 在 Task 2 先 validate），
        所以本方法内不再判参数合法性——拿到即合法。

        本方法只负责"做这件事"并把结果包成 ToolResult；
        重试、超时、分类、调度都不在这里（Executor 的职责）。
        """

    # —— 可选元数据（有安全默认值，子类按需覆写） ——
    @property
    def timeout_seconds(self) -> float:
        """执行超时上限。默认 10s；Task 3 的 Executor 用它做 timeout 边界。"""
        return 10.0

    @property
    def side_effect(self) -> ToolSideEffect:
        """副作用分类。默认 READ_ONLY（安全默认，避免误并发执行 mutating 工具）。"""
        return ToolSideEffect.READ_ONLY

    @property
    def permission(self) -> ToolPermission:
        """授权级别。默认 WORKSPACE_WRITE（安全偏高，避免新工具默认 DANGER）。

        与 side_effect 正交：side_effect 驱动批次调度（并发/串行），
        permission 驱动授权关卡（ToolExecutor 的 approval gate）。
        """
        return ToolPermission.WORKSPACE_WRITE

    @property
    def reconcile_hint(self) -> ReconcileHint:
        """崩溃恢复时的可验证性提示。默认 unverifiable（安全默认即 NEED_RECONCILE）。

        hint 只是给 ReconcileCallback 的建议数据——Runtime 永不据此自动验证
        或自动重跑（不变量 #14）。副作用可事后核验的工具（read/write/edit/
        glob/grep/git_status/git_diff）覆写；bash 保持默认（各命令副作用彼此
        不同，不允许统一假装可验证）。
        """
        return ReconcileHint(verifiable=False)

    @property
    def prompt_guidance(self) -> str | None:
        """该工具希望进入 agent **system prompt** 的使用指引（ADR-0023 D11）。

        与 `description` 的分工：
        - `description` 进 tool JSON Schema，回答"这个工具是什么、参数怎么填"；
        - `prompt_guidance` 进 system prompt，回答"什么时候该用/不该用它、
          与其他工具如何取舍、有什么预算或限制"。

        默认 None = 不贡献任何文本（多数工具不需要）。本字段**不是**
        abstractmethod：既有工具实现一律无需改动。

        【约束】本字段是**静态自然语言**，不得包含 `{{}}` 模板占位符——注册表的
        变量声明是模块级的（`_DECLARED_VARIABLES`），工具 guidance 无处声明变量，
        含 `{{x}}` 会在注册期抛 `undefined_variable`。需要动态内容时，用 property
        动态生成**整段**文本（如 bash.py 按 sandbox shell 生成 description 那样）。
        """
        return None

    def args_identity(self, args: dict[str, object]) -> str:
        """Return the stable identity persisted for one Operation's arguments."""
        return json.dumps(args, sort_keys=True, ensure_ascii=False)
