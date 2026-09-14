"""遗忘的审计痕迹：只走结构化日志，**不进** `SessionEvent`（#159 AC8）。

为什么不是 SessionEvent（ADR-0026 已定，不在本票重新讨论）：
- 记忆是 Capability 不是会话真相（不变量 #16）；
- 往 append-only 会话日志里塞记忆内容变更会制造第二套真相（不变量 #22）；
- `memory/degraded` 是**降级观测**（"抽取/写回/检索失败"），不是记忆内容变更，不构成反例。

所以在 memory 侧留痕：一条结构化日志事件 `memory_forget`。工具入口与用户 API 入口
**共用这一个 helper**——两个入口各写一份审计格式，迟早会漂移成对不上账的两套记录。
"""

import logging

from agent_harness.identity import get_identity_context
from agent_harness.logging import log_event

logger = logging.getLogger(__name__)

#: 审计里的入口标识（谁发起的遗忘）。
ENTRY_TOOL = "tool"
ENTRY_API = "api"

#: 审计结果的三态。两个入口**共用**这三个常量，免得各写一套字面量而漂移出两套对不上账的
#: 记录；取值本身是对外可见的日志字段，所以测试按字符串断言。
OUTCOME_FORGOTTEN = "forgotten"
OUTCOME_ABSENT = "absent"
OUTCOME_DENIED = "denied"


def record_forget(*, entry_point: str, memory_id: str, outcome: str) -> None:
    """记一条遗忘审计（结构化日志）。

    `outcome` 三态：`forgotten`（真的删掉了）/ `absent`（这条不存在，幂等无操作）/
    `denied`（存在但不属于当前身份）。三态都要留痕——"模型说要忘、其实什么都没发生"
    正是最需要能查出来的情况。

    **只带 id 与身份，不带记忆内容**：审计要回答"谁在什么时候动了哪条"，记忆正文是用户
    数据，进日志只是多余的泄露面。
    """
    identity = get_identity_context()
    log_event(
        logger,
        "memory_forget",
        f"memory forget via {entry_point}: {outcome}",
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        memory_id=memory_id,
        entry_point=entry_point,
        outcome=outcome,
    )
