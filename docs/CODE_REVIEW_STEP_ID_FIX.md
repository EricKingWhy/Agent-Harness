# Code Review：step_id 跨 run 撞号修复

**范围**：`08e238f` → 工作区（未提交）｜分支 `feat/backend`
**评审对象**：`src/agent_harness/agent/runtime.py`（+55/−21）、`src/agent_harness/session/session.py`（+28）、
新增 `tests/agent/test_step_id_session_unique.py`
**方式**：双轴独立子代理并行（Standards 轴 / Spec 轴）+ 人工复核与处置

| 轴 | 硬违规 | 判断题 | 结论 |
|---|---|---|---|
| **Standards**（AGENTS.md §7 不变量 / §9 Karpathy + Fowler 坏味道基线） | **0** | 3 | 通过 |
| **Spec**（ticket + 交接手册 §5 任务与约束） | **0** | 1（口径偏差，已声明） | 通过 |

---

## Standards 轴（子代理报告原文）

**硬违规：无。**

改动符合 §8 Scope Lock（仅新增 2 只读 property + `step_base` 偏移，全部可追溯到 ticket）、
§9.3 Surgical Changes（`step_base + steps` 最小替换）、§9.2 Simplicity（无投机抽象）。

**特别核实点（均通过）：**
- `step_base` 作用域：所有 18 处引用都在 `_drive()`（def@465）内；@991/@1031 把
  `steps=step_base + steps` 作为实参传给 `_TerminalContext`，计算发生在 `_drive` 局部；
  终端方法体只取 `self.steps`，不引用 `step_base`。无悬空引用。
- `steps` run 内语义：`AgentRunResult(steps=steps)`（@581/802/822/978/1060）与 `max_steps`
  保险丝均用原始 `steps`；`failure_terminal/cancelled_terminal` 收 `steps=step_base + steps`
  是正确的——终端体把它当 session 级 `step_id` 用（`interrupt(step=self.steps+1)`、
  `append_model_failed(step=self.steps)`、`step_id=self.steps+1`），非 run 内计数被污染。
- 无混改：`_log(step=0)`（@556）与 `tracer.context_build_started(step=steps)`（@563）未动，
  仍 run 级语义；改动严格限定在事件信封与终端上下文。
- 两 property 读 `self._events`：与既有 `derive_messages(self._events)`、`self.events`
  习惯一致，封装未破坏，无更优只读 API 需改用。
- 测试文件：`make_session`/`ScriptedModel` 复用正确；各用例自建 `session`+`model`，
  无顺序/跨用例依赖。

**判断题（基线坏味道）：**
1. **Duplicated Code（轻）**：`step_base + steps` / `step_base + steps + 1` 重复 ~18 处。
   `+1` 是有意的 model 事件语义偏移，抽公共需编码偏移，按 §9.3 内联为最小改动可接受；
   若想降噪，可在 `_drive` 内加局部辅助 `_ev_step = step_base + steps`。非硬违规。
2. **测试健壮性（轻）**：`test_cancelled_turn...` 依赖 `await asyncio.sleep(0)` 冲刷取消收尾，
   属时序脆弱点，建议改以断言终态事件出现为同步边界。非标准硬违规。
3. 命名（`step_base`/`max_step_id`/`user_turn_count`）均贴合 CONTEXT.md 已定义术语
   Run/Turn/step，**无 Mysterious Name**。

---

## Spec 轴（子代理报告原文）

**(a) 规格要求但缺失/半成品：无。**

三项任务全部完成，验收中可独立验证的两项已复跑通过：
- `tests/agent/test_step_id_session_unique.py`：5 passed（`.venv` 实跑）。
- `ruff check src tests`：All checks passed。
- `pytest tests/agent/ + tests/web/test_web_multiturn.py` 及全量 1485 passed 本次**未独立复跑**；
  但改动仅限事件信封 `step_id` 计算与两个只读 property，局部性高，风险低。

**(b) 越界改动：无。**
- 仅改 `src/`（runtime.py + session.py），未碰 `web/`（`git status` 无 web 文件）。
- 未改任何既有测试（`git diff 08e238f -- tests/` 为空），仅新增测试。
- 新增的 `max_step_id`/`user_turn_count` property 是手册 §5 明确建议的封装改进
  （"可以在 Session 上加一个 property"），非越界。

**(c) 看似实现但有问题的：无。** 关键项已独立核实：
- **症状/根因**：`step_id=step_base+steps`（step_base=max(max_step_id, user_turn_count)），
  第二轮 model 事件 step_id=2 而非 1，撞号消除——对准根因，非表面修补。
- **约束**：未直接访问 `session._events`（改用新增 property）；`grep -rn step_id src/`
  确认无消费者依赖"从 1 开始"（streaming/serialization/executor 均透传，
  interrupt/recovery 仅读取）。
- **风险 #2（delegate）**：独立读 `provider.py:220`，`child_session = Session(...)`
  为**全新独立 Session**，父子 step 不共享，手册担心属误报，"不受影响"成立。
- **风险 #1/#3/#4**：封装已加 property（#1 处置）；旧 session 历史 per-run（#3 如实声明为
  已知技术债，明确不在范围）；PYTHONPATH 陷阱（#4）已用 `PYTHONPATH=` 清零复跑通过。

**唯一口径偏差（非缺陷）**：任务①字面为"从前序 run 最大 step 继续"，但空轮（首轮早于首个
model 事件即失败/取消）场景改用 `user_turn_count` 推进基数——必要且合理的偏离，实施记录已说明，
并有 `test_turn_dying_before_model_call_*` / `test_cancelled_turn_*` 两例覆盖。

---

## 处置（评审后动作）

| 发现 | 处置 |
|---|---|
| Standards 判断 2（测试时序脆弱） | **已修**：`aclose()` 后改为「最多 20 个事件循环 tick 内等到 `run/failed` 落地」的有界等待，不再依赖单次 `sleep(0)`；复跑 5 passed |
| Standards 判断 1（`step_base + steps` 重复 18 处） | **不修**：`+1` 是 model 事件的语义偏移，抽公共需再编码偏移量；按 §9.3「只动必须动的」保持内联 |
| Standards 判断 3 | 无需动作 |
| Spec 口径偏差 | 无需动作（已在 ticket 实施记录中声明 + 测试覆盖） |
| Spec 未复跑的整批门禁 | 评审前已由本人执行：`tests/agent/ + tests/web/test_web_multiturn.py` = 162 passed；全量净化环境 = 1490 passed / 9 skipped / 0 failed |

**总结**：Standards 0 硬违规 / 3 判断题（最严重：测试时序脆弱，已修）；
Spec 0 违规 / 1 口径偏差（最严重：无，属已声明的合理偏离）。两轴均通过。

---

## 附 A：旧会话历史（扫描 → 已迁移，处置见 `MIGRATION_LEGACY_STEP_ID.md`）

只读扫描 115 个 session，**4 个**存在跨 run 撞号（均为修复前产生，全在
`D:\intelligence-agent\.agent\workspace\sessions`）：

| session | 轮数 | 撞号轮 | 该轮 step_ids | 已迁移改写行数 |
|---|---|---|---|---|
| `014c0c75-…` | 2 | 第 2 轮 | `[1]` | 85 |
| `516ab5a7-…` | 2 | 第 2 轮 | `[1, 2, 3]` | 72 |
| `845a72d4-…` | 11 | 第 2 轮 | `[1]` | 458 |
| `c89e0822-…` | 4 | 第 2 轮 | `[1]` | 3 |

（单轮 session 不受影响；`D:\intelligence-agent-backend\.agent\workspace\sessions` 与
`_demo_sessions` 下无命中。）已用 `scripts/migrate_legacy_step_id.py` 迁移完成，
备份 `step-id-backup-20260910-153827/`，复核：差异字段仅 `step_id` / 幂等 /
`845a72d4` 的被覆盖回答 8 轮 → 0 轮。

## 附 B：迁移脚本的自评审要点

新增件未走双轴子代理（无对应 spec，本身就是 spec 的实现），改为逐项自评审：

| 风险 | 处置 | 是否有测试 |
|---|---|---|
| 覆盖正在写入的会话 | 规划时记内容哈希，写入前复核；不一致即拒绝 | ✅ `test_apply_refuses_when_file_changed_after_plan` |
| 误改 step_id 以外的字段 | 只重写值真的变化的行，其余逐字节保留；重新序列化沿用 store 的同一口径 | ✅ `test_apply_backs_up_and_changes_only_step_id` |
| 不可回滚 | 写前逐文件复制到备份目录（逐字节原文） | ✅ 同上传断言备份 == 原文 |
| 重复执行放大改动 | 幂等（二次规划零改动）+ 写盘前自校验 | ✅ `test_idempotent_and_collision_free` / CLI 二次运行 |
| 迁移后仍有重叠 | 写盘前 `is_collision_free` 硬校验，失败则一行不写 | ✅ 同一测试 |
| run 边界外的事件被误判 | 无锚点则保守不动并如实计数报警 | ✅ `test_events_outside_run_boundary_are_left_alone` |
| 规则与 runtime 漂移 | 对齐测试：把 runtime 产出退化成旧编号再迁移回来，必须逐值等于原值 | ✅ `TestAlignsWithFixedRuntime` |
| 自校验形同虚设（**测试抓到**） | `is_collision_free` 原先内部先归一化 → 永真；改为直接读原始值 | ✅ `assert is_collision_free(events) is False`（旧数据） |
