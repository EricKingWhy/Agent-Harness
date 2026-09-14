# 交接手册：修复 step_id 跨 run 重复导致多轮对话内容覆盖

> ⚠️ **状态：已完成（2026-09-10）**。请勿再按本文档 §4/§5 的代码示例施工——
> 「把 `steps` 初值改成 `max(已有 step_id)`」这一步是**错的**（`steps` 同时是
> run 内轮次计数，max_steps 与 AgentRunResult.steps 都依赖它从 0 起算）。
> 实际实现与证据见 `docs/TICKET_STEP_ID_COLLISION_MULTI_TURN.md` 文末「实施记录」。
> 本文档保留作为诊断过程记录。

> **给执行 AI 的说明**：本文档是自包含的——你不需要此前对话的上下文。请完整阅读后按
> §5 提示词执行。诊断详情见同目录 `docs/TICKET_STEP_ID_COLLISION_MULTI_TURN.md`。

## 1. 问题是什么

用户做了两轮对话（先问 A，再问 B），结果：

1. **第一轮的回答消失了**
2. **第二轮的回答出现在第一轮消息的下方**（而不是第二轮消息的下方）

截图实测，**必现**，只要有两轮对话就触发。

## 2. 根因（一句话）

后端 `step_id` 是 per-run 的局部计数器（每次 `_drive()` 都从 `steps=0` 开始），而前端
把它当作 session 级全局 turn 标识。第二轮 run 的模型事件再次携带 `step_id=1`，与第一轮
冲突，前端 `withTurnAt(state, 1)` 把第二轮的模型输出折叠进第一个 turn，同时
`projectModelStarted` 执行 `turn.model = { text: '' }` 清空了第一轮的回答。

## 3. 关键代码位置（已验证的行号）

### 后端（修复目标）

| 文件 | 行号 | 当前代码 | 问题 |
|------|------|----------|------|
| `src/agent_harness/agent/runtime.py` | **484** | `steps = 0` | `_drive()` 局部变量，每个 run 都从 0 开始 |
| `src/agent_harness/agent/runtime.py` | **518** | `run_id, turn_index = session.begin_run(...)` | `turn_index` 已经是 session 级递增（1, 2, 3...），**但没用于 step_id** |
| `src/agent_harness/agent/runtime.py` | **613** | `data={"step": steps + 1}, step_id=steps + 1` | model/started 事件的 step_id |
| `src/agent_harness/agent/runtime.py` | **758** | `step_id=steps + 1` | model/completed 事件的 step_id |

**注意**：runtime.py 中 step_id 的使用有很多处（tool_call、tool_result、text_delta、
reasoning 等，见 `grep -n step_id runtime.py` 的 15 处命中），它们都用 `steps` 或
`steps + 1`。**修复时只需改变 `steps` 的初始值**，所有下游自动跟随。

### 后端（已有的解决方案素材）

| 文件 | 行号 | 代码 | 价值 |
|------|------|------|------|
| `src/agent_harness/session/session.py` | `begin_run()` | `turn_index = sum(1 for e in self._events if e.type == RUN_STARTED) + 1` | **已有的 session 级递增计数器模式**，可以直接复用这个思路算 step 基数 |

### 前端（不需要改，但要知道为什么）

| 文件 | 行号 | 函数 | 行为 |
|------|------|------|------|
| `web/src/lib/projection.ts` | **1010** | `resolveStep()` | 优先取 `data.step`，其次 `event.step_id`，用来定位 turn |
| `web/src/lib/projection.ts` | **84** | `withTurnAt()` | `findIndex(t => t.step_id === step)` 定位 turn，找不到才新建 |
| `web/src/lib/projection.ts` | **240** | `projectModelStarted()` | 命中已存在 turn 时 `turn.model = { text: '' }` 清空 |

## 4. 推荐修复方案（方案 A：后端一处改动）

### 4.1 核心改动

在 `runtime.py` 的 `_drive()` 中，将 `steps = 0`（第 484 行）改为基于 session 已有
事件的 step 偏移量：

```python
# 当前（第 484 行）：
steps = 0

# 修复后：
# step_id 必须在 session 级别唯一，否则前端 resolveStep 会把不同 run 的
# 模型事件折叠进同一个 turn（第一轮回答被第二轮覆盖）。
# 计算已有最大 step_id 作为本轮的起始偏移。
steps = 0  # 会在 begin_run 后立即调整，见下
```

但 `steps` 在 `begin_run`（第 518 行）之前就初始化了，而计算偏移需要读 session 事件。
两种实现路径：

#### 路径 1（推荐）：在 `begin_run` 后调整 steps

```python
# 第 484 行保持不变
steps = 0

# ... 第 518 行 begin_run 之后：
run_id, turn_index = session.begin_run(agent_id=self._agent_id)

# ── step_id session 级唯一性：续聊（turn_index > 1）时接续前序 run 的步号 ──
# 否则第二轮的 model/* 事件再次携带 step_id=1，前端 withTurnAt 会把它
# 折叠进第一轮的 turn——第一轮回答被清空，第二轮回答错位。
if turn_index > 1:
    steps = max(
        (e.step_id for e in session._events if e.step_id is not None),
        default=0,
    )
```

#### 路径 2：让 `begin_run` 返回 base_step

修改 `session.py` 的 `begin_run` 返回三元组：

```python
def begin_run(self, *, agent_id: str = "default") -> tuple[str, int, int]:
    run_id = str(uuid4())
    turn_index = sum(1 for e in self._events if e.type == RUN_STARTED) + 1
    base_step = max((e.step_id for e in self._events if e.step_id is not None), default=0)
    self.append(RUN_STARTED, {"turn_index": turn_index},
                run_id=run_id, agent_id=agent_id)
    return run_id, turn_index, base_step
```

然后 `_drive` 中：

```python
run_id, turn_index, base_step = session.begin_run(agent_id=self._agent_id)
steps = base_step  # 接续前序 run 的最大 step_id
```

**路径 2 的注意**：`begin_run` 的返回值类型从 `tuple[str, int]` 变成
`tuple[str, int, int]`，需要全局搜索所有 `begin_run` 的调用处更新解包。
建议先 `grep -rn "begin_run" src/ tests/` 确认影响面。

### 4.2 为什么不动前端

- 前端 `resolveStep` 和 `withTurnAt` 的设计假设是「step_id 在 session 级唯一」
  （代码注释 `projection.ts:87` 明确写了 `turn.step_id 唯一（resolveStep 单调递增
  设计不变量）`）
- 这个假设本身是合理的——问题出在后端没满足这个假设
- 动前端需要改 `ConversationState`、`Turn`、所有 projection 函数，改动面大且
  影响性能热路径（`withTurnAt` 的 last-turn 快速判断）

### 4.3 前端已有测试的坑

`web/src/lib/projection.test.ts` 里有大量测试用 `step_id: 1` 做第一轮、
`step_id: 2` 做第二轮（因为它们是独立构造的，不经过后端）。**这些测试不受影响**
——它们测试的是「给定正确的 step_id，前端行为是否正确」。你需要加的新测试是
**后端真的产生了正确的 step_id**。

## 5. 执行提示词

将以下提示词复制给执行 AI：

---

```
你是一个资深后端工程师。请修复一个已诊断清楚的 P0 bug。

## Bug 描述

多轮对话（续聊）时，第一轮的回答会消失，第二轮的回答会错位到第一轮的位置。
根因是后端的 step_id 是 per-run 局部计数器（每次 _drive() 从 steps=0 开始），
而前端把它当作 session 级全局 turn 标识。第二轮 run 的 step_id 又从 1 开始，
与第一轮冲突，导致前端把第二轮模型输出折叠进第一轮的 turn。

## 诊断报告

完整诊断在 `docs/TICKET_STEP_ID_COLLISION_MULTI_TURN.md`，请先读它。

## 你的任务

1. 修复 `src/agent_harness/agent/runtime.py` 的 `_drive()` 方法，让 step_id
   在 session 级别唯一递增（续聊时第二轮的 step_id 从前序 run 的最大 step 继续）。

   推荐方案：在 `begin_run()` 调用后（约第 518 行），将 `steps` 调整为
   session 已有事件的最大 step_id。例如：

   ```python
   run_id, turn_index = session.begin_run(agent_id=self._agent_id)
   if turn_index > 1:
       steps = max(
           (e.step_id for e in session._events if e.step_id is not None),
           default=0,
       )
   ```

   这样后续所有 `steps + 1`（model/started、model/completed、tool_call、
   tool_result、text_delta 等）自动使用全局递增的 step_id。

2. 写一个回归测试 `tests/agent/test_step_id_session_unique.py`：
   - 创建一个 session
   - 跑第一轮 _drive()，收集 model/completed 事件的 step_id
   - 跑第二轮 _drive()（续聊），收集 model/completed 事件的 step_id
   - 断言第二轮的 step_id > 第一轮的 step_id（而非都等于 1）

   参考 `tests/agent/test_phase5_runtime.py` 的测试搭建方式（make_session +
   ScriptedModel 或 run_phase5_scenario）。

3. 跑门禁确认零回归：
   - `ruff check src tests`（需要 All checks passed）
   - `pytest tests/agent/ tests/web/test_web_multiturn.py -q`（核心子集，
     确认续聊路径不回归）

## 约束

- 只改后端 `src/`，不碰前端 `web/`
- 不改测试文件（只新增，不修改既有测试）
- step_id 的语义变了（从 per-run 到 session-global），确认没有其他代码
  依赖「step_id 从 1 开始」的假设——先 `grep -rn "step_id" src/` 确认
- `session._events` 是内部属性，确认访问它不会破坏封装（如果在意，可以
  在 Session 上加一个 `max_step_id` property）
```

---

## 6. 验收标准

- [ ] `tests/agent/test_step_id_session_unique.py` 通过：两轮对话的 step_id 递增
- [ ] `ruff check src tests` 全绿
- [ ] `pytest tests/agent/ tests/web/test_web_multiturn.py -q` 零回归
- [ ] 全量 `pytest tests/ -q` 通过（环境干净时：1485 passed / 9 skipped / 0 failed）
- [ ] 手动验证：启动服务，发两轮对话，确认两轮回答都正确显示

## 7. 风险和注意事项

1. **`session._events` 封装**：直接访问私有属性不优雅。可以在 `Session` 类上加一个
   `@property def max_step_id(self) -> int` 方法。但这属于改进，非必须。

2. **嵌套 delegate run**：`_drive` 可能被嵌套调用（delegate → child run）。此时
   child run 的 `begin_run` 会增加 `turn_index`，但 child 的 step 应该从 parent 的
   当前 step 继续。验证 `tests/agent/test_runtime_llm_attribution.py` 中的嵌套场景
   是否受影响。

3. **旧 session 历史**：已持久化的旧 session 的 step_id 仍是 per-run 的。修复后
   回放这些旧 session 时前端仍会出错。这是已知的技术债，不在本次修复范围（除非
   你想在 `projectHistory` 加兼容层）。

4. **运行测试的环境陷阱**：如果在 WorkBuddy 沙箱里跑 `pytest tests/ -q`，必须
   先 `export PYTHONPATH=`（清空），否则沙箱注入的 sitecustomize.py shim 会在
   全量测试跑到后期触发 `SystemExit(1)`（删除配额耗尽）。详见
   `docs/TICKET_D7_TEST_STUB_DRIFT.md` 和 `scripts/run_tests_clean.sh`。
