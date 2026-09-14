# 集成提示词：类型诚实化（#147）+ 停顿提示（#148）+ `加载更早` 覆盖锁

> 面向**集成 AI**。分支：`feat/frontend`（worktree `D:\intelligence-agent-frontend`）。
> **未 push、未 merge**——按 §13.3 由集成方在 `D:\intelligence-agent` 的 `main` 上做最终集成与验证。

## 1. 改了什么（3 个 commit）

| commit | 类型 | 内容 |
| --- | --- | --- |
| `ec2a961` | fix | **BUG-010 / #147**：`AgentEvent.step_id` / `run_id` 由必填放宽为可选——类型不再对「键缺失」撒谎 |
| `9517e5d` | feat | **FE-01 / #148**：停顿提示（顶栏展示层旁注，不新增 SessionEvent） |
| `051aff6` | test | e2e：`加载更早 N 条` 真实点击锁（唯一零自动化覆盖的控件） |

两次文档提交：`docs/FRONTEND_ISSUES_LOG.md`（第七轮：阈值测量 + 真机时间线 + 过程自查）、
`docs/SDD_TICKET_TRACKER.md`（第七轮条目）。

**改动文件清单**（`git diff main...feat/frontend` 可复核）：
`web/src/types.ts`、`web/src/lib/eventKind.ts`、`web/src/lib/eventKind.test.ts`、
`web/src/lib/runState.ts`、`web/src/lib/runState.test.ts`、`web/src/components/TopBar.tsx`、
`web/src/components/TopBar.test.tsx`（新）、`web/src/components/StepDetail.test.tsx`、
`web/src/styles/app.css`、`web/e2e/o-wait-hint.spec.ts`（新）、
`web/e2e/p-earlier-window.spec.ts`（新）、`docs/*`。

**未改**：后端任何文件（两个后端 worktree 在改动期间均 clean）、`web/src/generated/event-types.ts`、
`web/src/types.ts` 的事件枚举、`web/src/hooks/useSession.ts`、`web/src/App.tsx`、
所有超时/重连常量（`RECONNECT_STALL_MS` / `MAX_RECONNECT_ATTEMPTS`）、后端 60s idle / 600s total。

## 2. 为什么符合 Spec

- **#147**：后端 `SessionEvent.to_dict`（历史事件路径）省略值为 `None` 的字段，所以「无归属」
  在 wire 上是**键缺失**而非 `null`；SSE 路径相反（`web/serialization.py::_envelope` 恒写键、
  无归属显式 `null`，实测 59/59 帧都有键）。两条路径喂同一个 `AgentEvent`，故类型的正确形状是
  超集「可能缺失」。冻结规格本就声明 `run_id?` / `step_id?` 可选
  （`03_SESSION_EVENT_MODEL.md`、`03_RUNTIME_EVENT_CONTRACT.md`）——**原来的必填声明才是偏离规格**。
  本改动只动前端类型与两处测试字面量，运行时行为零变化；未改后端序列化器（保持「GET 省略 null
  以压缩行」的既有契约），也未在 `eventValidate` 做归一化。
- **#148**：等待态是**展示层状态、不是会话事实**——不新增事件类型（不变量 #4：Event ≠ Diagnostic Log）、
  不落库、刷新即消失（不变量 #22：Web UI 不维护第二套不可对账真相）。三方对照（本项目 / deepseek
  harness / ZCode）显示两份参照实现也都只把「等待/重连」留在客户端。
- **超时默认值一律不改**：本项目 idle 60s / total 600s 已是三方里最激进的（dsh 300s、ZCode 600s），
  而实测首事件延迟 p50 4.6s / max 61.0s，下调会开始误杀合法的慢首 token。

## 3. 验证怎么做（集成后请重跑）

```bash
cd D:/intelligence-agent-frontend/web
npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build
```

**注意**：同一 worktree 里**不要并行跑两个 playwright**——本轮实测两个进程写同一个
`test-results/` 会互相覆盖并报 `ENOENT ... .playwright-artifacts-*`，导致假失败（见第 6 节）。

本分支末次实跑：tsc 0 · vitest **519 passed**（29 文件）· oxlint **0 errors**（37 warnings，
均为既有类型）/ playwright **126 passed** · vite build ✓。

**集成侧还需确认的两点**（前端分支上无法验证）：
1. `git merge` 后 `main` 上的 e2e 数量与前端分支一致（126），且没有与 main 新 spec 的端口/夹具冲突。
2. 后端 `main` 的 `/api/sessions/<id>/events` 与 `/stream` 的键形状未变（本票依赖「GET 省略键、
   SSE 恒写键」这一对事实；若后端改了序列化策略，`#147` 的类型契约要重新评估）。

## 4. 真机证据（AC7）

真实后端 + 真实模型（Reasoning Effort=Deep），250ms 采样器：首 token 等 31s 的 run 上，
提示在**空闲 30s** 出现（`已 30s 没有新进展，仍在等待模型`）并逐秒递增；**提示秒数(30) <
同屏脉冲秒数(31)**，现场证明「锚空闲而非流龄」。客户端 give-up 时提示让位给断线横幅
（`连接中断（connection stalled）：重试 3 次未成功` → `正在重连…`），重连成功后提示带累计
空闲秒数回来（`已 101s`）。完整时间线：`docs/FRONTEND_ISSUES_LOG.md` 第七轮。

阈值依据（可复现）：同一文档「停顿提示阈值」小节，n=13，min 0.8s / p50 4.6s / max 61.0s，
>30s 占 2/13。

## 5. 残余风险（5 条）

1. **`step_id` 的模板字符串写法仍能编译**：`if (e.step_id !== null) \`step ${e.step_id}\`` 是
   BUG-008 的原始写法，类型放宽后它**仍然通过 tsc**（模板字符串接受 `undefined`）。本票让类型
   如实描述线格式并让 `run_id`（`.slice()`）被强制处理，但**不是**该模式的全覆盖防线。
   可选加固（需另开票评估）：oxlint `no-restricted-syntax` 或统一访问器 `stepOf(e)`。
2. **`AgentEvent.data` 是同一类过度承诺**（票外观察，未改）：`to_dict` 在 `data` 为空时省略该键，
   而类型声明必填；目前被 `eventValidate` 的归一化兜住，故未爆发。
3. **停顿提示的可达窗口与前端自己的重连 give-up 重叠**：提示在空闲 30s 出现，而客户端
   `RECONNECT_STALL_MS(10s) × MAX_RECONNECT_ATTEMPTS(3)` 约在 30–40s 走 give-up
   （`streaming=false` → 提示让位给断线横幅）。即真实停顿里提示的窗口约 10s；这是**有意的
   升级顺序**（旁注 → 断线横幅 → 恢复入口）。**用户决定（2026-09-11）：不需要改**，按现状保留。
4. **同屏两个计时数字语义不同**：脉冲 `思考中 · Ns` 是**流龄**且重连成功后重置，提示的秒数是
   **跨重连累计的空闲**（真机见到 26s vs 101s）。这是脉冲既有语义、非本票引入；最小消除办法是
   提示可见时隐藏脉冲秒数，但那会动到 #148 AC 要求保留的既有计时显示。**用户决定
   （2026-09-11）：保留计时显示，不改。**
5. **e2e 的时钟是虚拟的**：`o-wait-hint.spec.ts` 用 `page.clock` 快进（浏览器/渲染/断言都是真的，
   只有时钟被替换）。真实的 30s 等待由第 4 节的真机观测覆盖，不靠这条 e2e。

## 6. 过程自查（供集成方避坑）

- 门禁的 playwright 与另外两次 ad-hoc e2e **并发**跑 → 两个进程写同一个 `test-results/` →
  `ENOENT ... .playwright-artifacts-*` → 门禁假失败 4 例（3 例是无关用例）。清并发 +
  `rm -rf test-results` 后重跑全绿。**结论：e2e 串行跑。**
- 一条 e2e 曾**因错误原因通过**（「工具执行中不提示」用有限响应体 mock）：mock 的流立刻结束 →
  重连额度十几秒内耗尽走 give-up → `streaming` 先变 false → 有/无提示两个变体都不显示。
  已删除该用例，相位门改在纯函数单测锁（变异后 2 处红），原因写进了 spec 头注释。
- 本轮的 grill 四问用户未作答，按推荐项执行并在 issue / commit 里标注为「未获确认的默认」。

## 7. 建议的 `docs/PHASE_STATUS.md` 条目（由集成方在 merge 后追加）

```markdown
- 2026-09-11：**前端第七轮 — 类型诚实化（#147）+ 停顿提示（#148）+ `加载更早` 覆盖锁**。
  commits `ec2a961` / `9517e5d` / `051aff6`（feat/frontend）。
  测试：前端门禁 tsc 0 · vitest 519 passed（29 文件）· oxlint 0 errors · playwright 126 passed
  · vite build ✓；后端本轮零改动。
  关单：#147、#148 已关闭（证据见 issue comment）。集成提示词：
  `docs/INTEGRATION_PROMPT_TYPE_HONESTY_AND_WAIT_HINT.md`。
  残留：`step_id` 模板字符串写法仍可通过 tsc（见提示词第 5 节，唯一未闭合项）；停顿提示与
  重连 give-up 的窗口重叠、同屏两个计时数字语义不同**均已由用户确认按现状保留**。
```
