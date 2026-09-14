"""Agent 运行结果与流式事件的最小数据结构。

为什么独立成 types.py：
- runtime.py 只该关心"怎么驱动循环"，不该同时背负数据结构定义；
- 后续 Task（日志、错误回填、max_steps、流式）都要引用同一种结果形状，
  集中在一处修改入口更清晰。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agent_harness.session.event import RUNTIME_EVENT_SCHEMA_VERSION

if TYPE_CHECKING:
    from agent_harness.session import SessionEvent

# 运行状态用字符串常量表达，而不是 Enum：
# - 字段少、分支简单，Enum 是过度抽象（违背 Day 3 "简洁优先"）；
# - 字符串在日志和断言里一眼能读，Debug 更直接。
# 正常完成
STATUS_COMPLETED = "completed"
# 不收敛兜底：模型反复请求工具直到 max_steps（Task 2 完整验证，Task 1 只留结构）
STATUS_MAX_STEPS_EXCEEDED = "max_steps_exceeded"
STATUS_CONTEXT_WINDOW_EXCEEDED = "context_window_exceeded"
# 同错熔断硬终止（ADR-0014 #69）：模型连续 N 次同指纹失败工具调用后，
# AgentRuntime 强制 end_run(failed)，防止步数/token 烧穿。
STATUS_IDENTICAL_TOOL_FAILURE_LOOP = "identical_tool_failure_loop"
# 模型调用 / 执行器异常的兜底失败态：run 以 run/failed 终结，final_text 恒为空串
# （绝不伪造最终回答）。这是 AgentRunResult 的内部状态值，不是事件 schema。
STATUS_FAILED = "failed"


@dataclass
class AgentRunResult:
    """一次 AgentRuntime.run() 的最终结果。

    字段语义：
    - status: 正常结束用 completed；模型一直不收敛、撞到 max_steps 用 max_steps_exceeded。
    - final_text: 最终回答文本。正常完成时来自"没有 tool_calls 的那一轮模型的 content"，
      不是 Runtime 自己拼接的；max_steps_exceeded 时为空串（绝不伪造最终回答）。
    - steps: 模型被调用的轮数（不是工具个数）。一个含多个 tool_call 的响应仍算 1 步，
      避免 max_steps 出现 off-by-one。
    """

    status: str
    final_text: str
    steps: int

    @property
    def completed(self) -> bool:
        """便捷判断：是否模型自然停止（而非撞到 max_steps 兜底）。"""
        return self.status == STATUS_COMPLETED


@dataclass
class AgentEvent:
    """run_stream() 向外 yield 的流式事件信封（Phase 9）。

    定位（spec 11 §1）：AgentEvent 是 Runtime 向外发出的业务事件流，
    供 CLI / SSE / Web UI / Test / Trace 多面消费。与 Diagnostic Log 分层——
    AgentEvent 是可重放的业务事实，Diagnostic Log 是运维调试不可恢复。

    设计：
    - type 复用 SessionEvent 词汇（如 model/completed、tool/call），加上
      纯流式信号（model/started），以及 ADR-0016 起持久化的合帧流式事实
      （model/delta、reasoning/*、tool/output_delta）。
    - seq 对应 SessionEvent 的 seq；纯流式信号（model/started）无 seq = None，
      表示"这条没持久化，刷新后从 model/completed 重建"。
    - data 是事件载荷 dict，形状跟 SessionEvent.data 一致（持久化事件）
      或流式专属（delta 的 {"delta": "..."} 等）。

    前端拿到后能据此区分：有 seq 的已被事实源记录，无 seq 的是 ephemeral 流式信号。
    """

    type: str
    data: dict[str, Any] = field(default_factory=dict)
    seq: int | None = None
    run_id: str | None = None
    step_id: int | None = None
    # 流式块标识（ADR-0016 §3.2）：durable 事件从 SessionEvent.block_id 透传；
    # stream-only 信号（model/started）无块归属，恒 None。
    block_id: str | None = None
    # time：事件真值时间（ISO UTC ms）。durable 事件从 SessionEvent.time 透传，
    # stream-only 信号（model/started）用发送时刻——它们不持久化，
    # 没有事实源时间，发送时刻是最接近的近似（spec 11 §4 / issue #43）。
    time: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="milliseconds"))
    # RuntimeEvent 信封字段（SDD 03 §3，Phase 2 加法）：
    # - schema_version：信封版本，与 SessionEvent 同源常量；
    # - durability：由 is_durable 推导（durable/transient），SSE 渲染时写入帧；
    #   不存为字段，避免与 is_durable 重复真值源；
    # - capability：事件归属 capability id（Phase 6 注入点），运行时恒 None。
    schema_version: str = RUNTIME_EVENT_SCHEMA_VERSION
    capability: str | None = None

    @property
    def is_durable(self) -> bool:
        """是否已被 SessionEvent 事实源记录（有 seq 即是）。"""
        return self.seq is not None

    @property
    def durability(self) -> str:
        """RuntimeEvent 信封 durability 推导（SDD 03 §3）：有 seq = durable。"""
        return "durable" if self.seq is not None else "transient"


def to_agent_event(event: SessionEvent) -> AgentEvent:
    """把一条持久化 SessionEvent 镜像成 AgentEvent（集中映射）。

    这是 runtime / SSE / Web UI 等所有 SessionEvent → AgentEvent 投影的
    唯一构造点：新增字段（如 time 透传、agent_id）只在这里改一次，
    不再在 run_stream 的 11 处手动拼装里逐个漂移（不变量 #4）。

    SessionEvent 永远有 seq ≥ 0，所以映射产物始终 durable；
    纯流式信号（model/started）不经此函数构造——
    它们在 runtime 里直接 new AgentEvent(..., seq=None)。
    """
    return AgentEvent(
        type=event.type,
        data=event.data,
        seq=event.seq,
        run_id=event.run_id,
        step_id=event.step_id,
        block_id=event.block_id,
        time=event.time,
        schema_version=event.schema_version,
        capability=event.capability,
    )
