# TICKET: step_id 跨 run 重复导致多轮对话内容覆盖

**状态**: FIXED（2026-09-10 修复完成，待提交；实现见文末「实施记录」）
**严重级别**: P0（核心功能阻断——多轮对话必现）
**发现日期**: 2026-09-10
**报告人**: 用户（截图实测）

## 症状

两轮对话场景：
1. **第一轮回答消失**——第二轮发起后，第一轮的模型回答文本被清空
2. **第二轮回答错位**——第二轮的模型回答出现在第一轮用户消息下方，而非第二轮用户消息下方

## 根因

**后端 `step_id` 是 per-run 的局部计数器（每次 `_drive()` 从 0 开始），而前端 `resolveStep` / `withTurnAt` 把 `step_id` 当作 session 级全局 turn 标识。第二轮 run 的模型事件再次携带 `step_id=1`，与第一轮冲突，导致所有模型输出被折叠进第一个 turn。**

## 证据链

### 1. 后端：step_id 是 per-run 局部变量

**文件**: `src/agent_harness/agent/runtime.py`

```python
# 第 484 行 — _drive() 方法体内
steps = 0  # ← 每次调用都从 0 开始，不跨 run 累加

# 第 518 行
run_id, turn_index = session.begin_run(agent_id=self._agent_id)
# turn_index 是 session 级别的轮次计数器（已存在！）
# 但没有用于 step_id 计算

# 第 610-613 行 — model/started 事件
yield AgentEvent(
    type=MODEL_STARTED,
    data={"step": steps + 1},      # = 1（每个 run 的第一次模型调用）
    run_id=run_id, step_id=steps + 1,
)

# 第 754-758 行 — model/completed 事件
model_event = session.append(
    MODEL_COMPLETED, model_data,
    run_id=run_id,
    step_id=steps + 1,             # = 1
)
```

**关键事实**：第一轮 run 和第二轮 follow-up run 的模型事件**都携带 `step_id=1`**。

### 2. 后端：begin_run 已有 session 级 turn_index

**文件**: `src/agent_harness/session/session.py`

```python
def begin_run(self, *, agent_id: str = "default") -> tuple[str, int]:
    run_id = str(uuid4())
    turn_index = sum(1 for e in self._events if e.type == RUN_STARTED) + 1
    # ← turn_index 已经是 session 级别的递增计数器
    # 第一轮 = 1, 第二轮 = 2, ...
    # 但目前只用于 Langfuse metadata，未传递给 step_id
    self.append(RUN_STARTED, {"turn_index": turn_index}, ...)
    return run_id, turn_index
```

### 3. 前端：resolveStep 用 step_id 定位 turn

**文件**: `web/src/lib/projection.ts`

```typescript
// 第 1010-1016 行
function resolveStep(event: AgentEvent, state: ConversationState): number {
  const fromData = (event.data.step as number | undefined) ?? null;
  if (fromData != null) return fromData;       // model/started 的 data.step=1 → 返回 1
  if (event.step_id != null) return event.step_id;  // model/completed 的 step_id=1 → 返回 1
  if (state.active_step_id != null) return state.active_step_id;
  return state.turns.length + 1;               // user/message 无 step_id → turns.length+1
}
```

### 4. 前端：withTurnAt 按 step_id 查找 turn

**文件**: `web/src/lib/projection.ts`

```typescript
// 第 84-107 行
function withTurnAt(state: ConversationState, step: number, fn: (turn: Turn) => void): void {
  // 快路径：最后一个 turn 的 step_id === step？
  // 慢路径：findIndex(t => t.step_id === step) ← 第一轮 turn(step_id=1) 被命中
  // 找不到才新建
}
```

### 5. 前端：projectModelStarted 清空目标 turn

**文件**: `web/src/lib/projection.ts`

```typescript
// 第 228-246 行
function projectModelStarted(state: ConversationState, event: AgentEvent): void {
  const step = resolveStep(event, state);  // 第二轮 = 1
  state.active_step_id = step;
  withTurnAt(state, step, (turn) => {      // 定位到 turn(1) ← 错误
    // ...
    if (!isEmptyHead) {
      turn.model = { text: '', status: 'streaming' };  // ← 第一轮回答被清空！
    }
    turn.status = 'streaming';
  });
}
```

## Bug 触发时序

| 时序 | 事件 | step_id | resolveStep | 目标 Turn | 结果 |
|------|------|---------|-------------|-----------|------|
| 1 | `user/message` "你好" | null | turns.length+1 = **1** | 新建 turn(1) | 第一轮用户消息入 turn 1 |
| 2 | `model/started` | 1 | **1** | turn(1) | 第一轮模型开始 |
| 3 | `model/completed` | 1 | **1** | turn(1) | 第一轮回答入 turn 1 ✓ |
| 4 | `run/completed` | — | — | — | turn 1 完成 |
| 5 | `user/message` "我是谁" | null | turns.length+1 = **2** | 新建 turn(2) | 第二轮用户消息入 turn 2 |
| 6 | **`model/started`** | **1** | **1** | **turn(1)** ← 错误 | **第一轮文本被清空** |
| 7 | `text/delta` × N | 1 | **1** | turn(1) | 第二轮文本追加到 turn 1 |
| 8 | `model/completed` | 1 | **1** | turn(1) | 第二轮回答写入 turn 1 |

**最终 UI 状态**：
- Turn 1: `user="你好"` + `model.text="第二轮回答"`（第一轮回答被覆盖）
- Turn 2: `user="我是谁"` + `model=null`（第二轮回答缺失）

## 受影响的所有路径

1. **流式路径**（`sendFollowUp`）：续聊时新 run 的事件在已有 conversation 上叠加，step_id 冲突直接覆盖
2. **历史重建路径**（`projectHistory`）：刷新页面时 `getSessionEvents` 全量重放，两个 run 的 step_id=1 事件互相覆盖
3. **live→viewing 迁移**：流结束后触发历史重读，同样出错

## 修复方案

### 方案 A（推荐）：后端 step_id 改为 session 级全局递增

**改动点**：`runtime.py` 的 `_drive()` 方法

```python
# 当前（第 484 行）
steps = 0

# 修复后
# 从 session 已有事件中推导出 step 基数偏移
run_id, turn_index = session.begin_run(agent_id=self._agent_id)
# turn_index 已是 session 级别计数器（1-based）
# 将 steps 初始值设为前序 run 的总 step 数
steps = sum(1 for e in session._events if e.type == MODEL_COMPLETED) if turn_index > 1 else 0
```

或更简洁：让 `begin_run` 返回 base_step：

```python
# session.py begin_run
base_step = sum(1 for e in self._events if e.step_id is not None and e.step_id > 0)
return run_id, turn_index, base_step
```

然后 `_drive` 中 `step_id = base_step + steps + 1`。

**优点**：
- 一处改动解决问题
- `begin_run` 已有 `turn_index` 的同类计算模式
- 前端零改动
- 持久化历史自然兼容（旧数据的 step_id 仍 per-run，但 projectHistory 按顺序 replay 时各 run 独立计数，只需确保新事件不再冲突）

**风险**：
- 需要验证是否有其他消费者依赖 step_id 从 1 开始的假设
- 旧 session 历史回放仍会出错（已有错误数据），但新 session 不再产生

### 方案 B（兜底）：前端 resolveStep 引入 run_id 维度

**改动点**：`projection.ts` 的 `resolveStep` 和 `withTurnAt`

将 turn 的唯一标识从 `step_id: number` 改为 `step_key: { run_id: string, step: number }`。

**优点**：不触碰后端
**缺点**：
- 改动面大（ConversationState / Turn / 所有 projection 函数）
- `withTurnAt` 的热路径优化（last turn 快速判断）需要适配
- 历史数据中部分事件可能不带 run_id

### 方案 C（最小改动，仅缓解）：projectModelStarted 不清空已有文本

```typescript
function projectModelStarted(state: ConversationState, event: AgentEvent): void {
  const step = resolveStep(event, state);
  state.active_step_id = step;
  withTurnAt(state, step, (turn) => {
    touchTurn(turn, event);
    // 仅当 turn 的 model 还没有内容时才初始化
    if (turn.model.text === '' && turn.model.status !== 'streaming') {
      turn.model = { text: '', status: 'streaming' };
      // ...
    }
    turn.status = 'streaming';
  });
}
```

**效果**：缓解"第一轮回答消失"，但不解决"第二轮回答错位"——第二轮回答仍会追加到 turn 1 而非 turn 2。不推荐单独使用。

## 验证方法

### 回归测试（方案 A）

```python
# tests/agent/test_runtime_multi_turn_step_id.py
async def test_step_id_increments_across_runs():
    """两轮对话中，第二轮的 model 事件 step_id 必须大于第一轮。"""
    runtime = build_test_runtime()
    session = Session.start(...)

    # 第一轮
    events_r1 = [e async for e in runtime._drive(session, "你好")]
    model_events_r1 = [e for e in events_r1 if e.type == MODEL_COMPLETED]
    assert model_events_r1[0].step_id == 1

    # 第二轮
    events_r2 = [e async for e in runtime._drive(session, "我是谁")]
    model_events_r2 = [e for e in events_r2 if e.type == MODEL_COMPLETED]
    assert model_events_r2[0].step_id > model_events_r1[0].step_id  # 关键断言
```

### 前端投影测试

```typescript
// web/src/lib/__tests__/projection.test.ts
it('does not overwrite turn 1 model text when turn 2 model events arrive', () => {
  const state = initConversation('test');
  // 第一轮
  applyEvent(state, { type: 'user/message', data: { content: '你好' } });
  applyEvent(state, { type: 'model/started', data: { step: 1 }, step_id: 1 });
  applyEvent(state, { type: 'model/completed', data: { content: '你好啊' }, step_id: 1 });
  applyEvent(state, { type: 'run/completed' });

  // 第二轮
  applyEvent(state, { type: 'user/message', data: { content: '我是谁' } });
  applyEvent(state, { type: 'model/started', data: { step: 1 }, step_id: 1 }); // 如果后端未修

  expect(state.turns[0].model.text).toBe('你好啊');  // 第一轮文本不被覆盖
  expect(state.turns[1].model?.text).toBeDefined();   // 第二轮有模型输出
});
```

## 实施记录（2026-09-10，状态 → FIXED，待提交）

### ⚠️ 本文档 §修复方案 里的代码示例已被证伪，实际实现不同

文档原示例是「把 `steps` 的初值改成 `max(已有 step_id)`」。**这会引入新 bug**：
`steps` 在 `_drive()` 里是双重身份——既是 step_id 来源，又是 **run 内轮次计数**：

| 用途 | 位置 |
|------|------|
| `max_steps` 保险丝（`steps + 1 < max_steps` / `steps >= max_steps`） | `runtime.py` L761 / L807 |
| `AgentRunResult.steps`（「本轮轮数」） | L581 / L802 / L822 / L1060 等 |
| 诊断日志 `_log(step=steps)` | 多处 |

改 `steps` 初值会：① 第二轮的 max_steps 预算被前序步数吃掉（多轮后一开局就撞保险丝）；
② `AgentRunResult.steps` 从「本轮轮数」变成「累计轮数」，语义漂移。

### 实际实现：新增 `step_base` 偏移，`steps` 语义不动

- `session.py` 新增两个只读 property（不碰 `_events` 私有属性）：
  - `max_step_id`：已出现的最大 step_id
  - `user_turn_count`：真实用户发言数（排除 `data.injected_by` 的熔断注入消息）
- `runtime.py::_drive`：在 **append 本轮 user 消息之前** 计算
  `step_base = max(session.max_step_id, session.user_turn_count)`；
  所有**事件**的 step_id 一律改为 `step_base + steps` / `step_base + steps + 1`
  （含 `MODEL_STARTED` 的 `data.step`、streamer 的 reasoning/text 块、tool_call/result、
  熔断事件，以及 `_TerminalContext` / `cancelled_terminal` 的步号入参）
- **为什么基数还要看 `user_turn_count`**：前一轮在首个 model 事件之前就终结
  （失败 / 取消 / 上下文超限）时该轮不产出正 step_id，只按 `max_step_id` 会再次
  与首轮 user 消息所占用 turn 撞号——必须与前端 `turns.length + 1` 的分配口径对齐
- **刻意不动**：Langfuse tracer 的 `step`（trace 天然 per-run）、诊断日志
  `_log(step=...)`（Event ≠ Diagnostic Log，日志 step 是「本轮第几轮」）
- **嵌套 delegate 不受影响**：child 用独立 Session（自己从 1 编号），本文件 §风险 2 的
  担心经核实不成立

### 验证证据

- 跨层红/绿对照（真实后端事件流 → 前端 projection 语义复刻，live 流 + 历史重放两条路径）：
  - 修复后：`turn1=你好/你好啊`、`turn2=我是谁/你是王浩宇`
  - 旧 per-run 编号：`turn1=你好/你是王浩宇`（覆盖）、`turn2=我是谁/''` → **原症状精确复现**
- 新增回归测试 `tests/agent/test_step_id_session_unique.py`（5 例）：
  两轮递增 / 多步轮基数 = 首轮最大 step / **空轮（失败·取消）仍推进基数** /
  `AgentRunResult.steps` 未被全局步号污染 / 取消轮后续聊不撞号
- 门禁：`ruff check src tests` = All checks passed；
  `tests/agent/ + tests/web/test_web_multiturn.py` = 162 passed；
  全量净化环境 = **1490 passed / 9 skipped / 0 failed**（基线 1485 + 新增 5）

### 旧会话历史（原「已知技术债」——已处置）

`scripts/migrate_legacy_step_id.py`（一次性、幂等、默认 dry-run、自动备份）把旧 session 的
`step_id` 重编号为 session 级唯一（规则与修复后 runtime 同口径）。已对真实 store
`D:\intelligence-agent\.agent\workspace\sessions` 的 4 个 session 执行完成：

- 备份：`step-id-backup-20260910-153827\`（逐字节原文，可回滚）
- 复核：差异字段仅 `step_id`；`is_collision_free` 前 True → 后 False；二次 dry-run = 0 待迁移；
  用前端投影语义复刻回放，`845a72d4` 被覆盖丢失的回答从 **8 轮 → 0 轮**
- 详见 `docs/MIGRATION_LEGACY_STEP_ID.md`

## 相关文件

| 文件 | 位置 |
|------|------|
| `src/agent_harness/agent/runtime.py` | `step_id` 生成处（L484, L610-613, L754-758） |
| `src/agent_harness/session/session.py` | `begin_run` 的 `turn_index`（已有 session 级计数） |
| `web/src/lib/projection.ts` | `resolveStep`（L1010）, `withTurnAt`（L84）, `projectModelStarted`（L228） |
| `web/src/hooks/useSession.ts` | `sendFollowUp`（L635）, `attachLiveStream`（L372） |
