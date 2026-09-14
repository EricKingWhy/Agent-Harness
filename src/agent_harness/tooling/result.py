"""ToolResult：Tool 执行结果的统一结构化语义。

为什么独立成 result.py：
- Contract（contract.py）只定义"Tool 是什么"，不该同时背负结果语义；
- 后续 Executor（Task 2/3）、ToolMessage 回填、JSONL 日志、测试断言都要引用
  同一种结果形状，集中在一处修改入口更清晰。

为什么用 Pydantic 而不是 dataclass（对比 Day3 的 AgentRunResult 是 dataclass）：
- AgentRunResult 是 Runtime 内部用、从不序列化出进程 → dataclass 够用；
- ToolResult 要跨 ToolMessage 边界、要 model_dump_json() 给模型/日志/测试，
  必须序列化稳定、字段类型可验 → Pydantic。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ErrorCode(str, Enum):
    """Tool 执行域的错误词汇表。

    今天（Task 1）只是冻结"有哪些码"，不实现产生这些码的执行逻辑
    （那是 Task 2 的 Exception Mapping 和 Task 3 的 Timeout 分类）。
    但 ToolResult 现在就要有稳定语义，所以码先定下来。

    为什么是 str Enum：JSON 序列化时直接输出字符串值
    （"INVALID_ARGUMENT"），日志和模型都好读；又保留枚举的类型安全。
    """

    INVALID_ARGUMENT = "INVALID_ARGUMENT"  # 参数校验失败 → 不重试，回模型自纠错
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"  # 未知工具名 → 不重试，回模型
    TIMEOUT = "TIMEOUT"  # 超时 → 默认可重试；MUTATING 工具由 Executor 置 False（副作用未知）
    TRANSIENT_ERROR = "TRANSIENT_ERROR"  # 暂时性错误 → 可重试（Task 3）
    PERMISSION_DENIED = "PERMISSION_DENIED"  # 权限拒绝 → 不重试
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"  # 工具内部异常 → 默认不重试
    CANCELLED = "CANCELLED"  # 批次前序失败或外部取消 → 不重试


class ToolResult(BaseModel):
    """一次 Tool 执行的统一结果。

    字段语义：
    - ok：成功/失败的总开关。成功时 data 有结构化数据；失败时 error_code 说明原因。
    - message：人和模型都可读的自然语言。模型靠它纠错；但它不能作为 Runtime 判断
      error_code/retryable 的依据——那两个字段才是确定性判断的根。
    - data：成功时的结构化 payload（如 {"sum": 7.0}）。失败时通常为 None。
    - error_code：失败时的分类码。ok=True 时必须为 None（构造时强制）。
    - retryable：是否值得重试。今天只有语义位，真正消费它在 Task 3。
    - metadata：附加执行元数据（duration_ms / attempt 等，Task 3 填）。
    - artifact_ref：大输出引用（Module 9 Context/Artifact 预留位，今天不用）。

    不变量（构造时强制，见 _check_invariants）：
      - ok=True  时 error_code 必须为 None
      - ok=False 时 error_code 必须非 None
    这就是"不依赖错误字符串猜 error_code/retryable"的根——语义不可能错。
    """

    ok: bool
    message: str
    data: dict[str, Any] | None = None
    error_code: ErrorCode | None = None
    retryable: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    artifact_ref: str | None = None
    # 工具产生的延迟会话事件 (event_type, data)：executor 在 tool/call 之后
    # 落盘（delegation 事件同款通道，overflow 是既有生产者）。exclude=True：
    # 这是 durable 事件通道，不是模型可见内容——model_dump_json（回灌给模型
    # 的 tool result content）不携带。
    pending_events: list[tuple[str, dict[str, Any]]] = Field(
        default_factory=list, exclude=True,
    )

    @model_validator(mode="after")
    def _check_invariants(self) -> ToolResult:
        if self.ok and self.error_code is not None:
            raise ValueError("ok=True 时不允许设置 error_code（成功不应携带错误码）")
        if not self.ok and self.error_code is None:
            raise ValueError("ok=False 时必须设置 error_code（失败必须有分类码）")
        return self

    @classmethod
    def success(
        cls,
        message: str,
        data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        pending_events: list[tuple[str, dict[str, Any]]] | None = None,
    ) -> ToolResult:
        """构造一个成功结果。error_code 强制为 None、retryable 强制为 False。"""
        return cls(ok=True, message=message, data=data, metadata=metadata or {},
                   pending_events=pending_events or [])

    @classmethod
    def failure(
        cls,
        message: str,
        error_code: ErrorCode,
        retryable: bool = False,
        metadata: dict[str, Any] | None = None,
        pending_events: list[tuple[str, dict[str, Any]]] | None = None,
    ) -> ToolResult:
        """构造一个失败结果。error_code 必填；retryable 默认 False（确定性错误不重试）。"""
        return cls(
            ok=False,
            message=message,
            error_code=error_code,
            retryable=retryable,
            pending_events=pending_events or [],
            metadata=metadata or {},
        )
