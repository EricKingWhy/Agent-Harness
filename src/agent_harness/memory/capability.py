"""Core 依赖的 Memory 原语；身份由可信上下文提供。

# 生命周期契约（#156 MEM-1；后续三票——解禁 LangMem / 冲突消解 / 遗忘入口——共用）

- `store`：新建一条记忆，id 由实现生成。
- `update`：**按 id 覆盖写（upsert by id）**，同 namespace 内 last-write-wins；id 不存在
  时按新记忆写入（与 `store` 的区别只是 id 由调用方给定）。这一层只提供**机制**：
  "该不该更新、更新哪一条"是冲突消解（#158）的策略，不要写进本层。
- `forget`：**硬删**（记录行与向量都真的消失，不留墓碑）。id 不存在 → `False`（幂等，
  "忘了又忘"不是错误）；存在但**该行的 namespace 不能由当前上下文解析成调用方有权操作的
  那一个** → `PermissionError`（#159 起统一口径：属于别的 tenant/user/scope、SESSION 行绑到
  别的 session、SESSION 行完全没有绑定、scope 未实现，都是这一种；静默 False 会让调用方以为
  删掉了）。读路径刻意不同款：`get` 把它伪装成 `KeyError`（不泄露存在性），`delete`/`forget`
  如实拒绝，入口层据此给 403 而不是 500。**仅当这条记忆确实存在时**才做归属/绑定校验，
  不存在的 id 一律幂等 `False`。
- 索引是**异步**跟进的：`store`/`update`/`forget` 只保证权威记录与 outbox 意图落盘，
  向量索引由 relay 收敛（失败保留意图、下轮重试，见 `record_store` 与 `outbox_relay`）。
  调用方不得假设"方法返回 ⟹ 检索已更新"。
- `list_entries`：按 namespace **分页列出**（`offset` 之后取 `limit` 条，按创建时间倒序）。
  与 `search` 的区别是它**不经过 embedding**：读的是权威记录，所以"列出来的就是全部"，
  而不是"语义上最像的那几条"。遗忘入口的用户 API 用它（#159）。
  刻意**不叫 `list`**：在 `Protocol` 类体里定义一个叫 `list` 的方法会把内建名 `list` 遮蔽掉，
  同一类体里后续的 `list[MemoryEntry]` 注解会在运行时炸成 "'function' object is not
  subscriptable"（本票实现时真踩过）。
- 并发与版本：见 `record_store` 模块文档（内容 last-write-wins；outbox `revision` 是
  索引同步的乐观令牌）。

# 冲突消解（retrieve-before-write，#158 MEM-3）

- `consolidate`：**#158 的写入入口**——写入前先检索本 namespace 的既有记忆，把它们与本次候选
  一起交给 **provider** 决策（insert / update / delete / no-op），决策结果一律落 #156 的机制
  （`store`/`update`/`forget` 走的同一条记录 + outbox 路径）。**策略属 provider**（不变量 #18）：
  Core 不内置"同 key 覆盖 / importance 比较"之类的冲突启发式。
  **调用方的写入契约就是这个方法**——`store` 是 provider 侧的原语（manager/工具用它落盘），
  它不带"不丢写"保证：决策/检索失败时会抛异常，候选会丢。只有 `consolidate` 保证
  "返回 ⟹ 已落盘"。
- **只有一条路径**：检索发生在 provider 内部（LangMem 的 manager 自己按 provider 的方式检索），
  Core 侧不再另做一次 `recall` 注入——两套检索并存迟早对不上账。
- **注入有界**（provider 的责任，实现见 `consolidation.py`）：既有记忆注进 prompt 的条数与
  每条字符数都有上界，与 `extractor._clip_events` 同一思路。
- **不丢写**：决策或检索阶段任何失败都**降级为一条无条件写入**，并把脱敏原因放进
  `MemoryWriteOutcome.degraded_reason`（调用方据此落 `memory/degraded`）。因此
  `consolidate` 返回即代表"已有记忆落盘"；不写的情况只有两种：降级写入自己也失败，或
  调用方的**外层**预算先把这次写入取消掉（`CancelledError` 越过降级边界——所以 writeback
  会按外层剩余时间给每次调用一个更小的 `budget_seconds`，让"预算不足"表现为降级而不是取消，
  见 `writeback._FALLBACK_RESERVE_SECONDS`）。
- **预算是调用方的**：`budget_seconds` 是可选上限（None = provider 自己的默认值）；provider
  取 `min(给定值, 自己的默认值)`，不因为调用方给了大预算就无限等下去。
"""

from dataclasses import dataclass
from typing import Protocol

from agent_harness.memory.types import MemoryEntry, MemoryScope


@dataclass(frozen=True, slots=True)
class MemoryWriteOutcome:
    """一次"检索后写入"的结果（#158）。

    - `id`：**一定**有一条记忆落盘——候选不会因为决策/检索失败而丢失。
    - `degraded_reason`：`None` = 决策路径跑通（provider 已按其策略消解过冲突）；
      非 `None` = 策略没能跑、已降级为无条件写入。原因**只含阶段 + 异常类型名**
      （脱敏：原始异常消息可能含用户数据或密钥，不得进日志/事件流）。
    """

    id: str
    degraded_reason: str | None = None


#: 没配决策模型时的降级原因。这是**配置事实**（生产装配总是传模型），
#: 不是运行期故障——但仍如实报告，避免"看起来消解了、其实只做了插入"。
NO_DECISION_MODEL = "no_decision_model"


class MemoryCapability(Protocol):
    async def store(self, scope: MemoryScope, content: str, metadata: dict, *,
                    budget_seconds: float | None = None) -> str: ...
    async def consolidate(self, scope: MemoryScope, content: str, metadata: dict, *,
                          budget_seconds: float | None = None) -> MemoryWriteOutcome: ...
    async def update(self, memory_id: str, scope: MemoryScope, content: str, metadata: dict) -> str: ...
    async def forget(self, memory_id: str) -> bool: ...
    async def list_entries(self, scope: MemoryScope, limit: int,
                           offset: int = 0) -> list[MemoryEntry]: ...
    async def recall(self, scope: MemoryScope, query: str, limit: int) -> list[MemoryEntry]: ...
    async def search(self, scope: MemoryScope, query: str, limit: int) -> list[MemoryEntry]: ...
