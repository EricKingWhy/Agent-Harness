# Architecture Review — intelligence-agent-frontend/web/src

> 日期：2026-09-10 ｜ 范围：`web/src/` 全部模块
> 方法：扫描最近 diff（main...HEAD）触及的文件，对照 pi-mono 和 deepseek-harness 的设计模式
> 目标：企业级——性能、速度、鲁棒性、可用性

---

## 参考代码库的设计模式

### pi-mono (`/tmp/pi-mono`)

| 模式 | 文件 | 启示 |
| --- | --- | --- |
| `EventStream<T, R>` | `packages/ai/src/utils/event-stream.ts` | 通用 async iterable：push/end/result 三方法，生产者/消费者清晰分离 |
| `Lane` 状态机 | `packages/agent/src/harness/runtime/lane.ts` | 操作生命周期封装在 Lane 内，不散落在 hook refs |
| `drive/` 子目录 | `packages/agent/src/harness/runtime/drive/` | 每个 drive 阶段是独立文件（checkpoint/generation/reconcile/recovery），不是巨型 switch |
| Result 类型 | `packages/agent/src/harness/result.ts` | `Closed`/`HarnessClosed`/`InvalidMessage` 等——错误是值，不是异常 |

### deepseek-harness (`D:\intelligence-agent-backend`)

| 模式 | 文件 | 启示 |
| --- | --- | --- |
| `BlockStreamer` | `src/agent_harness/agent/streaming.py` | 流式块记账：窗口合帧 + reasoning 块状态机，clock 注入可测 |
| append vs yield 分离 | `streaming.py` 注释 | 只 append 不 yield（持久化与流式广播分离） |
| 单一归一化点 | `src/agent_harness/web/app.py` | 后端在 service 层做归一化，不在每个端点重复 |

---

## Candidate #1: useSession.ts — attachLiveStream 是不可测试的巨石

**强度：Strong**

**文件：** `web/src/hooks/useSession.ts` (~lines 389-620)

**问题：**

`attachLiveStream` 闭包将以下职责捆绑在 230 行嵌套闭包中：

1. 重连状态机（指数退避 + 额度上限）
2. 提交合并（coalescerRef + visibilitychange flush）
3. 停摆检测（stallCheckRef + RECONNECT_STALL_MS）
4. 截断重建（parseTruncated + after_seq 续传）
5. seq-gap 处理（isSeqGap + scheduleReconnect）

共享 10+ refs：`sseRef`、`coalescerRef`、`stallCheckRef`、`liveSidRef`、`streamGenRef`、`terminalSeenRef`、`reconnectAttemptRef`、`lastAppliedSeqRef`、`reconnectProgressBase`、`conversationRef`。

纯决策函数（`decideStreamEnd`、`decideCancel`、`isSeqGap`、`reconnectDelayMs`、`parseTruncated`）已提取用于测试，但**调用它们的编排逻辑**——连接 refs、定时器、异步 fetch 和 gen 检查——是真正 bug 隐藏的地方，且通过当前 hook 接口完全不可测试。

**删除测试：** 删除 attachLiveStream 会**集中复杂度**——所有重连/合并/停摆逻辑无处可去。这是深化的信号。

**解决方案（参考 pi-mono Lane + EventStream）：**

```
现状：
useSession (800+ lines)
├─ attachLiveStream (230 lines)
│  ├─ reconnection state machine
│  ├─ commit coalescing
│  ├─ stall detection
│  └─ seq-gap handling
├─ 10+ shared refs (mutable, cross-effect)
└─ untestable orchestration

目标：
useSession (400 lines)
├─ StreamOrchestrator (injectable, testable)
│  ├─ reconnection logic (decideStreamEnd)
│  ├─ coalescing/stall (stallCheckRef)
│  └─ seq-gap handling (isSeqGap)
├─ conversation ref only
└─ orchestrator unit-testable via DI
```

将 attachLiveStream 的编排逻辑提取为独立的 `StreamOrchestrator` 类：

```typescript
// web/src/lib/stream-orchestrator.ts
class StreamOrchestrator {
  constructor(
    private deps: {
      fetchStream: (sid: string, afterSeq: number) => Promise<Response>;
      scheduleTimer: (fn: () => void, ms: number) => TimerHandle;
      clock: () => number;
    }
  ) {}

  async attach(sid: string, gen: number, conv: ConversationState): Promise<void> {
    // 重连状态机、合并、停摆逻辑集中在此
  }

  cancel(): void { /* ... */ }
}
```

**收益：**
- 编排逻辑可通过构造函数注入进行单元测试
- refs 封装在 orchestrator 内部
- useSession 缩小到可读规模
- 重连/停摆/合并的 bug 可通过纯函数测试复现

**风险：**
- 这是最大的重构，涉及核心流式路径
- 需要完整的 e2e 回归来验证行为不变
- pi-mono 的 Lane 是 TypeScript 原生设计；我们的 useSession 是 React hook，迁移路径不同

---

## Candidate #2: projection.ts — 并行 switch，1000 行 god-file

**强度：Worth exploring**

**文件：** `web/src/lib/projection.ts`（applyEvent ~500 lines + summarizeEvent parallel switch）

**问题：**

`applyEvent` 是对事件类型的 500 行 switch。`summarizeEvent`（line 931）是对同一类型词汇表的**第二个并行 switch**。添加事件类型需要更新两个 switch 加上 `default`/unknown 处理——已知 bug 磁体。

copy-on-write 机制（`withTurnAt`、`cloneTurn`、`replaceTurnAt`）与事件特定分支交错在整个 switch cases 中。

**删除测试：** 将 applyEvent 拆分为 per-type handler 函数**不会集中复杂度**——它会把 COW 逻辑分散到各文件，同时 dispatch 无处移动。摩擦在于 switch 本身，而非其位置。

**解决方案（参考 pi-mono drive/ 子目录的 per-phase 文件模式）：**

```
现状：
applyEvent() {
  switch(type) {
    case USER_MESSAGE: ... // 20+ lines
    case MODEL_COMPLETED: ... // 30+ lines
    // 20+ cases
  }
}
summarizeEvent() { /* parallel switch */ }

目标：
const handlers = {
  [EventType.USER_MESSAGE]: projectUserMessage,
  [EventType.MODEL_COMPLETED]: projectModelCompleted,
  // one entry per type
};
applyEvent(state, event) {
  return handlers[event.type]?.(state, event);
}
```

将每个事件类型的投影逻辑提取为独立的 handler 函数（如 `projectUserMessage`、`projectModelCompleted`），注册到一个 `EventHandlers` map 中。`summarizeEvent` 同理。COW 机制保持集中。

**收益：**
- 新增事件类型只需添加一个 handler 函数并注册
- 两个并行 switch 收敛为单一注册表
- COW 逻辑不再分散在每个 case 中
- 投入产出比最高：不改变外部行为，但显著降低未来添加事件类型的认知负荷和出错概率

**风险：**
- 低：handler 注册表是成熟模式，pi-mono 的 drive/ 子目录也用了类似结构
- 需要确保 COW 语义在提取后不变（有专项测试锁定）

---

## Candidate #3: App.tsx — 重复的 amend-payload 构造

**强度：Worth exploring**

**文件：** `web/src/App.tsx`（handleSubmit lines 266-313）

**问题：**

`handleSubmit` 构造 amend payload **两次**：一次为 `sendMessage`（continue path, lines 274-285），一次为 `submitTask`（create path, lines 288-299）。两者展开相同的 4 个可选字段，语义完全相同。新增 amend 字段需要同时修改两个分支。

此外，8 个 `useState` 调用管理 4 个并行控制目录（permission-modes、agent-profiles、reasoning-efforts、context-providers），模式几乎相同。

**解决方案：**

提取 `buildAmendPayload(selectedModel, selectedAgentProfile, ...)` 纯函数，两个路径共用。将 4 个并行控制目录的状态管理提取为 `useControlCatalogs` hook。

```typescript
// web/src/lib/amend-payload.ts
export function buildAmendPayload(opts: {
  model?: string;
  agentProfile?: string;
  reasoningEffort?: string;
  contextProviders?: string[];
}): Record<string, unknown> {
  return {
    ...(opts.model ? { model: opts.model } : {}),
    ...(opts.agentProfile ? { agent_profile: opts.agentProfile } : {}),
    ...(opts.reasoningEffort ? { reasoning_effort: opts.reasoningEffort } : {}),
    ...(opts.contextProviders && opts.contextProviders.length > 0
      ? { context_providers: opts.contextProviders }
      : {}),
  };
}
```

**收益：**
- amend 字段变更只改一处
- 控制目录的 fetch/store/validate 模式集中化
- App.tsx 缩小

---

## Candidate #4: api.ts vs App.tsx — amend 字段双重归一化

**强度：Speculative**

**文件：** `web/src/lib/api.ts`（sendMessage lines 190-209）、`web/src/App.tsx`

**问题：**

`api.ts` 的 `sendMessage` 在 `JSON.stringify` 内部做自己的「有值才带」归一化。`App.tsx` 在调用前**也**条件展开。这种双层归一化令人困惑——调用方无法判断哪层拥有契约。

**解决方案：**

选择单一归一化点。建议 `api.ts` 的 `sendMessage` 作为唯一归一化点（它已经是兜底），`App.tsx` 只传原始值。

**收益：**
- 契约所有权清晰
- 调用方代码简化
- 减少重复逻辑

**风险：**
- 低：只是去掉一层冗余检查
- 但需要确认所有调用方都传原始值（不是预处理过的）

---

## Candidate #5: types.ts — ConversationState 是 god object

**强度：Speculative**

**文件：** `web/src/types.ts`（ConversationState line 281）

**问题：**

`ConversationState` 有 15+ 字段，混合了：

- run 级聚合（`usage_total`、`cost_usd`）
- trace 元数据（`trace_id`、`trace_url`）
- 中断状态（`run_interrupted`）
- 幂等簿记（`seenSeqs`——一个公开暴露的可变 `Set`）
- 渲染提示（`active_step_id`、`turn_index`）

每个消费者必须部分理解这个扁平 bag。没有模块边界分离「run 产生了什么」和「可观测性元数据」以及「幂等内部」。

**解决方案：**

将 `ConversationState` 拆分为：

- `RunState`（turns、tools、activities、run_status、run_cancelled）
- `ObservabilityState`（trace_id、usage_total、cost_usd、trace_url、model）
- `IdempotencyInternals`（seenSeqs——不再公开暴露）

但这可能过度工程化——当前 flat 结构在投影层是合理的。

**收益：**
- 消费者只需导入相关子结构
- seenSeqs 不再公开暴露

**风险：**
- 高：拆分后投影逻辑变得更复杂
- 可能违反 YAGNI——当前结构虽然不完美但能工作
- pi-mono 的 Session 也是扁平结构，说明这不是真正的摩擦点

---

## 选择的最佳路径（企业级标准）

**标准**：性能 / 速度 / 鲁棒性 / 可用性，四者都要高。参考 pi-mono 与 deepseek-harness 的设计。

### 主路径：Candidate #1 — StreamOrchestrator（流式编排深化）

四条企业级标准逐条对照：

| 标准 | Candidate #1 的贡献 |
| --- | --- |
| **性能** | 合帧批量提交（coalescer）在编排层——这是每 delta 都走的路径；封装后可独立基准与优化 |
| **速度** | 重连/停流的时间参数（退避、停摆阈值、banner 延迟）集中为一处可调常量，而非散落在闭包 |
| **鲁棒性** | 重连状态机从「不可测试的嵌套闭包」变为「可注入依赖的模块」——正确性可被测试锁定，这是鲁棒性的前提 |
| **可用性** | 断线/停摆/截断/seq-gap 四条降级路径是 UI 在网络故障下存活的关键；集中后不会因一次改动互相踩 |

**参考设计（哪里不明白就抄）**：

- **pi-mono** `packages/agent/src/harness/runtime/lane.ts` + `drive/`：把一次 run 的生命周期拆成 `checkpoint` / `generation` / `reconcile` / `recovery` / `tools` 等**独立文件**，由一个 `driveOperation` 循环按状态分派。这正是 attachLiveStream 该有的形状——现在是 230 行嵌套闭包，没有分派边界。
- **pi-mono** `packages/ai/src/utils/event-stream.ts`：`EventStream<T, R>` 把**生产者**（`push` / `end`）与**消费者**（`asyncIterator` / `result`）分离，终态用 `isComplete` 谓词判定。attachLiveStream 目前生产与消费交织，抄这个分离。
- **deepseek-harness** `src/agent_harness/agent/streaming.py` 的 `BlockStreamer`：**clock 经构造函数注入**（`clock=time.monotonic`），窗口常量经模块属性读取使测试可归零。这是「时间相关逻辑可测试」的标准做法，直接抄。

### 配套路径：Candidate #2 — 事件语义注册表（编译期穷尽性）

Candidate #1 解决运行时的编排鲁棒性；Candidate #2 解决**契约漂移**的鲁棒性：现在 `applyEvent` 与 `summarizeEvent` 是两个并行 switch，且注册表**不穷尽**——生成物新增事件类型时，两个 switch 都不会报错，只会静默落到 `unknown_events`。

改为 `Record<EventTypeValue, EventSemantics>` 后，`event-types.ts` 一旦新增类型，`tsc` 立即失败直到注册。这把「记得改两处」从人的纪律变成编译器的强制——正是防漂移。

> 附带发现（本批不修，仅登记）：`ARTIFACT_EXTERNALIZED`、`COMPACTION_START`、`COMPACTION_END`、`MESSAGE_QUEUED`、`QUEUE_CANCELLED`、`STEER_REQUESTED`、`STEER_APPLIED` 这 7 个类型虽在生成词汇表中，但前端零处理——目前静默进 `unknown_events`。穷尽注册表会**显式登记**它们（保持既有兜底行为不变），使这个缺口可见。

### 执行顺序（先低风险后深水）

```
1. Candidate #4  — api 层成为唯一归一化点（小、安全）
2. Candidate #3  — Composer 档位 → 提交字段的单一构造器（小、安全）
3. Candidate #2  — 事件语义注册表（中，编译期保障）
4. Candidate #1  — StreamOrchestrator（深，企业级核心）
```

前两条是清理，把 amend 字段的归属理顺，为 #1 减少干扰面。

### 明确不做：Candidate #5（ConversationState 拆分）

**理由：YAGNI + 参考实现反证。** pi-mono 的 `Session` 同样是扁平会话状态，deepseek-harness 的事件模型也是扁平 `SessionEvent`——两者都没有把「运行产物 / 可观测元数据 / 幂等簿记」拆成独立对象。拆分会把 COW 投影逻辑打散到多个结构之间，增加复杂度而不增加能力。**记录为已评估、已否决**，避免未来的架构评审重复提议。

---

## 实施约束

1. **每个 candidate 都走 SDD 循环**：/implement → /code-review → 修复 → /code-review
2. **不改变外部行为**：所有重构必须是行为保持的（例外须在「已披露的行为变化」登记）
3. **门禁全绿**：tsc + vitest + oxlint + playwright + build
4. **不推送到远程**：本地 commit 可以，push 不行
5. **参考但不照抄**：pi-mono 和 deepseek-harness 的设计模式是参考，不是模板——我们的上下文不同

---

## 附录：pi-mono EventStream 模式（供 Candidate #1 参考）

pi-mono 的 `EventStream<T, R>` 是一个通用 async iterable：

```typescript
class EventStream<T, R = T> implements AsyncIterable<T> {
  private queue: T[] = [];
  private waiting: ((value: IteratorResult<T>) => void)[] = [];
  private done = false;

  push(event: T): void { /* deliver to waiting consumer or queue */ }
  end(result?: R): void { /* mark done, notify all waiters */ }
  result(): Promise<R> { /* final result promise */ }

  async *[Symbol.asyncIterator](): AsyncIterator<T> { /* consume queue or wait */ }
}
```

关键设计点：

- **生产者/消费者分离**：push 是生产者接口，asyncIterator 是消费者接口
- **背压自然**：queue 无上限但消费者 drain 速度决定 push 是否阻塞
- **终态明确**：done 标志 + end() 方法，不会有「流结束了但消费者不知道」的问题
- **result promise**：最终结果可以独立于迭代获取

这个模式可以启发我们重构 attachLiveStream：将流的生产（SSE 解析）和消费（projection 应用）分离到独立的 StreamOrchestrator 中。

---

## 交付状态（本批实际落地）

| Candidate | commit | 状态 |
| --- | --- | --- |
| #4 api 层唯一归一化点 | `9b2234f` | 交付 |
| #3 Composer 档位单一构造器 | `9b2234f` | 交付（与 #4 同批：一个 SDD 循环覆盖两个 candidate，偏离约束 #1，记录在案） |
| #2 事件语义注册表 | `f481ea5` | 交付；穷尽性经实验证伪（注入 `FUTURE_THING` → tsc TS2741） |
| #1 StreamOrchestrator | `ae341e2` | **部分交付**：仅第一刀（重连策略状态机 + 时间参数集中）。完整编排提取未做，范围见下 |
| #5 ConversationState 拆分 | — | 明确不做（YAGNI + 参考实现反证） |

### C1 未完成部分（后续 ticket 范围）

`attachLiveStream` 仍是约 200 行嵌套闭包：`coalescer`（合帧提交，性能正向路径）、
`stallCheck`（停摆心跳）、`doTruncatedRebuild`（全量重建）、seq-gap 分流仍在 hook 内，
且生产（SSE 解析）与消费（投影应用）仍交织。按本文件「主路径」的参考设计，目标形状是
`lib/stream-orchestrator.ts`：构造注入 `fetchStream` / `scheduleTimer` / `clock`
（抄 deepseek-harness `BlockStreamer`），内部按 pi-mono `drive/` 的状态分派拆成
recovery / rebuild / stall 子模块。

本轮不做，因为该段处于每帧热路径与全部降级路径的交汇处，在无监督的长会话收尾阶段风险过高。
先剥出重连策略状态机并锁上单测，是让后续提取有安全网的前置条件。

### 已披露的行为变化（「不改变外部行为」的例外）

1. **Timeline 摘要**（`f481ea5`）：`run/interrupted` 由「未知事件 · …」变为
   「第 N 步中断」（`step_id` 缺失时「运行中断」），`model/changed` 由「未知事件 · …」变为
   「模型 → X」（`to_model_id` 缺失时「模型已切换」）。旧行为把**已处理**的事件类型渲染成
   「未知事件」，与 projection 内「未知兜底只留给真正未知类型（UnknownSurfaceNode 协议）」的
   既定注释自相矛盾——按契约修正而非保持。`session/forked` 保持旧文案（同属已知类型，
   但文案变更未经确认，登记待定）。
2. **create 请求体**（`9b2234f`）：`context_providers: []` 不再发键（此前会发）。这是
   「有值才带键」的既定语义（见 `api.ts` 注释与 `SendMessagePayload` 的已知 Gap）；
   后端区分 None / []，前端选择器无法表达「零个」。

### 交付时新增的防漂移装置

`api.ts` 的 `BodyFields<T>` 字段表取代手写请求体：payload 类型新增字段而未登记 → tsc 失败。
此前的手写白名单会**静默**丢弃新字段（请求照发、后端拿不到），是本轮 review 发现并修掉的失效模式。
