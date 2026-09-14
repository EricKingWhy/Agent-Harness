# 前端集成交接提示词 —— 刷新一致性 + 控制面清点 + 审批卡覆盖（本批）

> 本文件是**集成 AI 的唯一入口**：§0 是要执行的动作，§8.x 是证据与移交细节。
> 上一批的分支级细节见 `docs/HANDOFF_APPROVAL_CARD_COVERAGE.md`（交接手册）与 `docs/FRONTEND_ISSUES_LOG.md`（问题台账）。

---

## 0. 集成执行摘要（先读这一节）

### 0.1 实测拓扑（2026-09-11，`git fetch origin --prune` 之后）

| 项 | 值 |
| --- | --- |
| 分支 | `feat/frontend` @ `e215ec8` |
| 本地 `main` | `ebb2d68`（**滞后**） |
| `origin/main` | `7a55de4` |
| merge-base | `ebb2d68` |
| feat/frontend 领先本地 main | **28 个 commit** |
| feat/frontend 落后 origin/main | **23 个 commit** |
| 本批新增 commit（本次交付） | `35cd0a1`（控制面清点 + 401 缝）· `8ed86f0`（瞬态三键）· `1a75c3a`（tracker）· `c9dcf2a`（审批卡 + 联调车道）· `e215ec8`（tracker） |

### 0.2 按「先回后正」执行（AGENTS.md §14.6，勿在 main 上解冲突）

```bash
# ① 反向合入（在 feature 分支上解冲突、跑门禁）
cd D:/intelligence-agent-frontend      # 即本 worktree
git fetch origin --prune
git merge origin/main        # ← 需用户批准
# ② 门禁复跑（§0.4）
# ③ 正向合入：feat/frontend → main（先本地，验证后再 push；push 需用户单独批准）
```

### 0.3 冲突预判：**只读实测=零冲突**（已在合并结果上核验产物）

```
git merge-tree --write-tree feat/frontend origin/main
→ exit 0（clean，无冲突文件名输出）
```

> 该命令的 tree hash 随分支 tip 变化（每次加 commit 都会变），故只记「exit 0 / 无冲突文件」这个结论；**合并前请自己重跑一次**，别引用旧 hash。

已在 **合并后的 tree** 上逐项核验（只读，未落盘）：

| 检查 | 结果 |
| --- | --- |
| `web/e2e/n-approval-card.spec.ts` / `web/e2e-live/approval-live.spec.ts` / `web/playwright.live.config.ts` | 均在合并结果中（OK） |
| `docs/HANDOFF_APPROVAL_CARD_COVERAGE.md` / `docs/PROMPT_FRONTEND_NEXT_BATCH.md` | 均在合并结果中（OK） |
| `web/e2e/fixtures.ts` 的 `onApprovePost` | 2 处命中（接口字段 + 路由分支），**存活** |
| `web/vitest.config.ts` 的 `e2e-live/**` 排除 | 2 处命中，**存活** |
| `web/src/lib/projection.ts` 的 `projectPermissionResolved` | 2 处命中，**存活** |
| `web/src/components/ApprovalCard.tsx` 的两个按钮 | 均有，**未受 main 影响**（main 对此文件 0 次改动） |

**20 个文件两侧都动过**（`docs/*` 与 `web/{e2e,src}`）；逐项查证后确认大部分是**先前已集成进 main 的前端 commit 的重复包含**（同一 commit 同时在两侧），故文本与语义风险都低。`origin/main` 本批的实际新内容集中在**后端**（`reasoning_effort` 线格式 P0 修复、`step_id` session 级递增 P0 修复、架构深化收尾、`.gitattributes` 钉 CRLF）与 `docs/PHASE_STATUS.md`。

> ⚠ 若在 main 上遇到 `docs/PHASE_STATUS.md` 的「两侧各自追加」冲突，按 §14.7 **两条都保留**（这是既有惯例，见 `origin/main` 的 `7a55de4` / `4fd5716` 提交信息）。

### 0.4 合并后必须复跑（§14.10 门禁）

```bash
cd web
npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build
```

期望：tsc exit 0 · vitest **497 passed**（28 文件）· oxlint **35 warnings / 0 errors**（基线不得升高）· playwright **112 passed** · vite build ✓。

`--workers=2` 是硬要求（4 worker 有资源竞争型抖动）。**联调车道（`e2e-live/`）不在门禁内**，不要因为把它扫进来而误判失败——`playwright.config.ts` 的 `testDir` 是 `./e2e`、`vitest.config.ts` 的 `exclude` 含 `e2e-live/**`，两侧都已核验。

### 0.5 本批风险画像：**未改任何生产源码**

```
git diff --name-only 35cd0a1^..e215ec8 -- web/src/ | grep -v "\.test\."   # → 空
```

本批只动了 **测试、测试配置、文档**（13 个文件：4 个新 spec/配置、`fixtures.ts` 加一个 mock 钩子、`vitest.config.ts` 加一行排除、`api.test.ts` 加 3 例、6 份文档）。**没有 UI 行为变化**，因此集成后不需要重新做视觉/交互验收；但 §0.4 的门禁必须实跑。

### 0.6 需要集成 AI 做的事

1. **合入本批**（§0.2 先回后正 + §0.4 门禁 + 本地 main 验证后再 push，push 需用户批准）。
2. **转交后端**：`OBS-008 ~ OBS-014`（含根因文件行号）——见 **§8.7** 与 `docs/FRONTEND_ISSUES_LOG.md`。要点：`sandbox/local.py:166-167` 用 `errors="replace"` 把 cmd.exe 的 GBK 输出按 UTF-8 解码 → **乱码被固化进 append-only JSONL**（有原始字节级铁证）；`local.py:161` 的 `shell=True` 使 `bash` 工具在 Windows 实为 cmd.exe；bash 工具 10s 硬超时且 `retryable:false`；provider 退化重复。
3. **转交产品决策**：**OBS-015**（`ApprovalCard.tsx:26-33` 的 `catch` 对任何错误都翻「已批准/已拒绝」，与注释相反 → 审批 POST 失败时是乐观假象）。另：是否把交互式审批做成默认档位（现在需用户显式选权限档位才会出现审批卡）。
4. **纠正一条已过时的登记**：审批卡此前登记为「产品不可达」——**已证伪**（`session/service.py:348` 的 `permission_mode_explicit` 才是门）。若其他文档/issue 里有该旧结论，请一并订正。

---

## 1. 本批改了什么

用户要求：「检查页面刷新后会话内容还在不在——刷新后的会话必须和刷新前一致」。实测发现两处缺口，均已修复并用真实浏览器 + 真实后端取证。

| 缺陷 | 症状 | 根因 | 修复 |
| --- | --- | --- | --- |
| **BUG-005** 刷新丢失选中会话 | F5 后回到空态：8 轮 → 0 轮、正文 4102 字符 → 0；会话列表 67 条还在，只是没人记得用户选的是哪条 | `useSession` 的 `mode` 初始态恒为 `idle`，会话选择**没有任何持久化**（全仓只有 theme / density / apiToken 三处 localStorage） | 新增 `lib/sessionRestore.ts`：`ahi.selectedSession` 键 + `readStoredSessionId` / `writeStoredSessionId`（storage 不可用静默降级）。`mode` 改为**惰性初始化**；持久化挂在 `mode` 上（`idle` ⇒ 删键） |
| **BUG-006** 流式中刷新后停在假快照 | run 仍在服务端跑（ADR-0016 detached-run），刷新后的 UI 只显示一次历史快照，后续事件**再也进不来**，看起来像已完成 | `viewing` 分支只 `GET /events` 取一次就收工，没有任何「接回实时流」的通路 | 历史装载后若 `hasUnterminatedRun(events)` → `resumeLiveStream(sid, maxEventSeq(events))` → `GET /stream?after_seq=N`（后端 T4 #97 的重放+续流契约），不重不漏 |
| **OBS-007** 中断的会话谎报绿色「已完成」+ 过期中断横幅不消 | 会话 `c63ce4d3` 同一屏既有绿色对勾「已完成 · 2,583 tok」，又有「上次运行在首个步骤开始前中断」横幅——两句都在说「最近一次运行」的结局，却互相矛盾 | ① `projectRunStarted` 从不清 `run_interrupted`，该标记一旦置上就挂到会话生命结束（横幅只看它，于是永久显示）；② `projectRunInterrupted` 走 `finalizeRun(state, 'completed')`（冻结决策 69：中断 ≠ 失败，而 `finalizeRun` 只有两档）→ 脉冲报「已完成」 | 见 §8：新增第四态脉冲 `interrupted`（`已中断` / 中性色 / `CircleSlash`）+ 新 run 开始即清标记。**两处必须同改**，只改一处会比原来更错 |

### 文件清单

| 文件 | 变更 |
| --- | --- |
| `web/src/lib/sessionRestore.ts` | **新增**（无 React 依赖）：storage 读写 + `maxEventSeq` + `nextResumeAttempt` + `forgetResumeAttempt`（+ `ResumeAttempts` 类型） |
| `web/src/lib/sessionRestore.test.ts` | **新增** 12 例 |
| `web/src/lib/api.ts` | 新增 `NotFoundError`；`getSessionEvents` 遇 404 抛它（区别于真故障） |
| `web/src/lib/api.test.ts` | +3 例（404/500/200 三态归类） |
| `web/src/hooks/useSession.ts` | 主改动：惰性 `mode`、持久化 effect、`resumeLiveStream`、`attachLiveStream` 的 `opts.resume` + 零帧兜底、`selectSession` 的重新武装 |
| `web/e2e/k-refresh-restore.spec.ts` | **新增** 5 用例（× 2 视口 = 10 例） |
| `web/src/lib/runState.ts` | OBS-007：新增第四态 `interrupted`（`PULSE_TABLE` 行 + `deriveRunPulse` 的行前返回，连带恒真守卫 `run_status === 'completed'`）+ `coarsenPulseState` 同步映射 |
| `web/src/lib/runState.test.ts` | OBS-007：+3 例（含 Inspector 「已中断」标签断言、不变量被破坏时「更晚终态赢」的退化语义） |
| `web/src/lib/projection.ts` | OBS-007：`projectRunStarted` 清空 `run_interrupted`（语义收窄为「**最近一个** run 以中断收口」） |
| `web/src/lib/projection.test.ts` | OBS-007：+1 例（新 run 开始即清标记） |
| `web/src/styles/app.css` | OBS-007：`.run-pulse.pulse-interrupted`——复用既有中性 token（`--text-secondary` / `--color-hover` / `--border-subtle`），**未新增 `:root` 变量，§15 不涉及** |
| `web/src/lib/commands.ts` + `web/src/App.tsx` | BUG-007（详见 §4）：`CommandItem.keywords` 别名 + 11 条静态命令 label 中文化 |
| `docs/FRONTEND_ISSUES_LOG.md` | BUG-005/006/007 + OBS-008/009 + 第二轮 66 行巡检表 + 审查处置 |
| `docs/SDD_TICKET_TRACKER.md` | 本批进度 |

---

## 2. 真机取证（这是本批最需要集成 AI 知道的部分）

**BUG-006 决定性取证**（真实后端 `127.0.0.1:8000` + 真实浏览器 CDP 驱动）：

1. 新会话提交一个 ~30s 任务（三次 `sleep`），5s 后确认 run **确在途**（脉冲「思考中 · 15s」，事件仅到 `run/started`）。
2. **此刻 F5**。刷新后 3s：选中行已恢复、用户消息在、**无重连横幅、无空态**；Inspector 已渲染事件 0–6。
3. **网络层铁证**：`GET /api/sessions/affd6084-…/stream?after_seq=2 [200]`。
   刷新时 `/events` 快照只到 **seq 2** → `maxEventSeq` = 2 → 以 `after_seq=2` 接流；**事件 3–6 是经这条流重放+续送达的**，不是历史快照。
4. **零交互前进**：此后不碰页面等 16s，事件 **3 → 54** 条，末条 `53 run/completed`，脉冲「已完成 · 15,306 tok」。静态快照不可能自增。
5. **与后端真值对账**：服务端 54 条 / seq 0–53 / **重复 0、空洞 0**；UI 显示 54 条 / 末条 53 → 「无缝无重复」在 UI 侧成立。

**BUG-005 取证**：刷新前后逐项对照——选中行、`.turn` 轮次（8）、正文指纹 `-271347586` / 4102 字符、「已完成 · 4,339 tok」脉冲、右栏 Inspector 全部一致；且是**零点击**（不点任何东西）。

**回归锁**（`e2e/k-refresh-restore.spec.ts`，12 例全绿）：
- 刷新后零点击恢复选中 + 内容（含 `page.reload()` 后复验）；
- **写入路径**：从空态出发、真实点击会话行 → 断言键被写下 → **不重新播种**刷新 → 仍恢复。这条是第二轮审查补的：其余用例用 `addInitScript` 播种，而 `addInitScript` 每次导航（含 reload）都会重跑，所以只能证明**读**路径——删掉持久化 effect 它们依然全绿。补测后做过**变异验证**：临时停用写入 effect → 该用例在两个视口都变红（`Expected: "e2e-session-0001" / Received: null`），已还原；
- 接流游标恰为 `after_seq=4`，且**刷新后**才产生的标记文本由接流送达（首屏流给不同标记，只有真正接流才能通过断言）；
- 零帧空流（run 已在刷新窗口内收口）→ 静默停在历史 + **只发一次请求**（死循环断点）；
- 陈旧 id 404 → 清键 + 静默回空态；
- **子会话 id**（非首行真实点击 → 写键 → 不播种刷新）同样恢复——见 §8.6。

---

## 3. 需要集成 AI 注意的行为变化

1. **新增 localStorage 键 `ahi.selectedSession`**。刷新后 UI 会恢复上次选中的会话（含分叉 child、委派 child、`打开子会话` 的目标）。显式点「新建会话」会删键，不会复活旧会话。
2. **刷新后可能自动发起一条 `GET /stream?after_seq=N`**（仅当该会话最后一个 run 无终态）。对已收口的会话不会发（或发一条立即 200+空 body 的，静默回落 viewing，不报错、不弹重连横幅）。
3. **`getSessionEvents` 的 404 现在是 `NotFoundError`**（新增导出），与 500 等真故障区分——UI 对前者静默回空态，对后者照旧显示错误横幅。`useChildConversation.ts` 把它当普通 `Error` 读 `.message`，仅文案更友好，无回归。
4. 无 CSS / 主题改动（§15 不涉及）；无新依赖。

---

## 4. 未修 / 遗留（明确披露，勿误判为完成）

| 项 | 级别 | 说明 |
| --- | --- | --- |
| ~~BUG-007 命令面板 label 全英文~~ | P2 | **已修（本批追加）**：11 条静态命令 label 改中文（与工具栏口径一致），英文原词进新增的 `keywords` 别名继续可搜。判定为缺陷而非产品决定——面板 `hint` 早就是中文（`右栏`/`定位`/`输入框`），属本地化做了一半。回归锁：`i-keyboard.spec.ts` 改为英文查询+中文条目，`commands.test.ts` +3 例 |
| 零帧回落全静默 | P3 | 若后端某天在 run 活着时返回 200+空 body（契约破坏），用户会盯着半截会话且无信号。按**已实测契约**（空闲会话 → 立即 200+空 body；活着的 run 不会零帧 EOF）这不构成缺陷；加延迟复查会在回调里引入新重入面，收益不抵复杂度。风险已登记 |
| OBS-008 `glm-5.3-flash` model/failed | 后端 | 工具成功后 `model/failed: "model call failed: RuntimeError"` → `run/failed`。**非前端**，与既有 OBS-001 同族（同一模型）。建议后端把原始异常落进日志/JSONL |
| OBS-009 bash 工具 10s 上限 | 后端 | `sleep 10` 贴边越界 → `TIMEOUT`，且 `retryable:false`。前端渲染忠实（工具失败 ≠ run 失败，模型自行改用 `sleep 1` 后收口成功）。建议后端确认超时上限与 `retryable` 语义 |
| ~~OBS-006 审批卡不可达~~ **已证伪并闭合** | 前端覆盖（原误判） | 原记「硬编码 `auto_approve: true` → UI 不可达」**是错的**：审批卡由 `tool/approval-requested` 事件驱动（`projection.ts:514`），真正的门是 `session/service.py:348` 的 `permission_mode_explicit`——**显式选权限档位即开启交互式审批**，与 `auto_approve` 无关。已用真实后端 + 真实模型真机点击「批准」「拒绝」两键，JSONL 持久化 `permission/resolved`（decision=approve_once / deny）；回归锁 `web/e2e/n-approval-card.spec.ts`。详见登记簿 OBS-006 订正条 |
| **OBS-015 审批卡 `catch` 把任何错误当已决** | **P2（前端，预存在，需产品决策）** | `ApprovalCard.tsx:26-33`：注释写「其它错误保持 pending」，代码却对**任何**错误都 `setDecision(已批准/已拒绝)`。后果：审批 POST 真失败时用户看到「已批准」的**乐观假象**，run 实际仍卡在等审批（300s 才 fail-closed）——对安全相关交互，这个方向的假象比「无响应」更危险。**证据**：把 `/approve` 恒返回 404，UI 照样显示已批准。**本轮未改代码**（§8 Scope Lock），建议区分「409/404 已幂等」与「其它错误 → 保持 pending + 提示重试」；修时应补「POST 500 → 卡片保持 pending」用例（当前只覆盖成功路径）。详见登记簿 OBS-015 |
| `test-results/.last-run.json` | 卫生 | 工作区根目录的 Playwright 残留（**Sep 9，非本批产生**），未纳入提交。`web/.gitignore` 已忽略 `web/test-results`，根目录这份是历史遗留 |

---

## 5. 代码审查

第一轮（两轴：Standards + Spec/不变量）**6 findings，无 P0 / 无 P1**（3×P2 + 3×P3）：

| # | 级别 | 处置 |
| --- | --- | --- |
| 1 | P2 | **已修**——resume-404 分支的 `writeStoredSessionId(null)` 是死写（后面 `setMode(viewing)` 会让持久化 effect 把 id 写回去）。删除，并把「真已删除」交给紧随其后的历史重跑（404 → `NotFoundError` → 清键 + 回 idle，那次落得住） |
| 2 | P2 | **已修**——`resumeAttemptedRef: Set<string>` 只按 sid 记账，会连**正当的再次恢复**一起禁掉（A 接流成功 → 续聊 → 切 B 再切回 A 且 run 在跑 → 被拒 → 冻结）。改为按 **(sid, 游标)** 记账的 `nextResumeAttempt` 纯函数：死循环断点仍在（零帧不带来新事件 → 游标不变 → 拦下），有新事件时游标变大 → 允许再接 |
| 3 | P2 | **已修**——新增 8 例 e2e + 5 例 `nextResumeAttempt` 单测 + 3 例 `NotFoundError` 单测 |
| 4 | P3 | **接受的取舍**（零帧静默），理由见 §4 |
| 5 | P3 | **不改 + 补注释**（`scheduleReconnect` 404 同一 tick 内自愈，单独清是死写） |
| 6 | P3 | **已修**（多余空行） |

审查确认正确的部分（覆盖凭据）：死循环断点充分、StrictMode 双调用已被 `cancelled` 守卫挡住、游标数学不重不漏、`framesSeen` 计数位置正确、`terminalSeenRef` 每流重置、`streamGenRef` 代际守卫两路复检、不变量 #22 未破坏（复用同一 `projectHistory` 与唯一 `ConversationState`）。

第二轮审查结论：见本文件 §6（本轮追加）。

---

## 6. 第二轮审查结论

第二轮（对修复后的 diff 复审）**6 项一审 findings 全部 RESOLVED**（其中 #3 从 PARTIALLY 补齐为 RESOLVED，见下）；**新发现 4 项（1×P2 + 3×P3），无 P0/P1**。

| 新 # | 级别 | 内容 | 处置 |
| --- | --- | --- | --- |
| A | P2 | **BUG-005 的写入路径零自动化覆盖**——所有 e2e 都用 `addInitScript` 播种，而它在每次导航（含 reload）都重跑，于是只能证明读路径；删掉持久化 effect 全套仍绿 | **已修**：新增「真实点击 → 断言写键 → 不重新播种刷新」用例，并做**变异验证**确认它真的会红（见 §2） |
| B | P3 | `useSession.ts:288` 注释声称 ref 在 render 期赋值，与实现（effect 内）矛盾，会诱导后人改回去 | **已修**：改为「在 effect 里镜像」并注明「曾据此改过一次，别改回去」 |
| C | P3 | 失败尝试在 `await` **之前**就记账，会吃掉该游标的一次自动重试 | **不改 + 补注释说明理由**：这正是刻意的——失败路径同样 `setMode(live)`→`setMode(viewing)`，mode 每变一次历史 effect 就重跑，若失败不记账会变成**无上限重试**（每轮两条请求）。代价是失败后不自动重试（错误横幅已告知），用户重点一次该会话行即经 `selectSession → forgetResumeAttempt` 重新武装 |
| D | P3 | 本交接文档在定稿前已过期（测试数 9 vs 12、缺 `forgetResumeAttempt`） | **已修**：本文件即修正后版本 |

**第二轮额外确认（作为「无 P0/P1」的依据）**：`NotFoundError` 三个调用点①历史 effect 已处理②`doTruncatedRebuild` 走重连自愈③`useChildConversation` 仅读 `.message`（文案更友好，无回归）；`tsconfig` 目标 `es2023` 故 `class extends Error` 原型链完好，`toBeInstanceOf` 可靠；`maxEventSeq` 返回 `-1` 不会与 `hasUnterminatedRun` 同时成立（`run/started` 必带数字 seq），首帧不会被误判为 gap；`resumeAttemptedRef` 只按「本页会话内选中过的不同会话数」增长，刷新即清，非泄漏；§8 Scope Lock 与 §15 CSS 规则均未被触碰。

**第二轮后的门禁**：tsc ✓ · vitest **490 passed**· oxlint **35w 0e** · playwright **96 passed**（+2 例写入路径）· vite build ✓。

---

## 7. 建议的合并顺序与验证

`feat/frontend` 落在 `web/**` 与 `docs/**`，与后端 `src/**` / `tests/**` 无交集。合并前按 §14.10 走：

```bash
git -C D:/intelligence-agent fetch origin
git -C D:/intelligence-agent diff --stat main...feat/frontend
git -C D:/intelligence-agent merge feat/frontend      # 需用户批准
```

合并后建议在 `D:\intelligence-agent` 起真实前后端，手工复验两条：

1. 选中一个真实会话 → **F5** → 会话与内容应完全一致（零点击）。
2. 提交一个 ≥20s 的任务 → 流式中 **F5** → 应看到「思考中/执行工具」继续前进，直到终态；**不应**出现「连接中断，正在重连…」或停在半截。

`docs/PHASE_STATUS.md` 按本分支协议未改（前端进度记 `docs/SDD_TICKET_TRACKER.md`），merge 后由集成 AI 追加一条。

---

## 8. 追加批次：OBS-007 中断脉冲 / 过期横幅一致性

### 8.1 为什么必须两处一起改

| 只改一处 | 后果 |
| --- | --- |
| 只加第四态「已中断」，不清标记 | 「中断后成功重跑」的会话（如 `c63ce4d3`）永远显示「已中断」——**比修复前更错**（现在至少说「已完成」） |
| 只清标记，不加第四态 | 「被中断且此后再没跑过」的会话仍谎报绿色「已完成」，与残留的横幅继续打架 |

修复后语义：`run_interrupted` = **最近一个 run 以中断收口**（新 run 开始即清空），因此脉冲行前判断它比 `run_status` 更能说明真相。

### 8.2 真机复验（真实浏览器 + 真实后端）

| 会话 | run 序列 | 修复前 | 修复后 |
| --- | --- | --- | --- |
| `c63ce4d3` | 中断 → **完成** | 绿色「已完成」+ 中断横幅（已过期） | 脉冲「已完成 · 2,583 tok」，**横幅消失**；Timeline 仍保留 `运行中断` 行（历史事实不删） |
| `f181c5ce` | 中断 → **失败** | 「失败」+ 中断横幅（已过期） | 脉冲「失败」，**横幅消失**；Timeline 仍保留「第 3 步中断」 |

两例的**恢复入口不受影响**（`canRecover` 由 `isRecoverableRun(events)` 判定，与标记无关）。

### 8.3 覆盖边界（请勿误读为已目视确认）

「`已中断` 脉冲」这一态在**当前真实语料里不可达**——两个含 `run/interrupted` 的会话都被后续 run 取代了，没有「中断且从未重跑」的真实会话。故该态**仅由单测锁定**（`runState.test.ts` 3 例 + `projection.test.ts` 1 例），未在真机上目视确认。其中两例做**变异验证**：抹掉 `coarsenPulseState` 的中断映射、或去掉 `run_status === 'completed'` 守卫 → 对应断言立刻变红，随后还原。

### 8.4 本批审查结论（第三轮：OBS-007 修复）

**0 个可复现 bug（P0/P1/P2 全无），4 项 P3。** 审阅者独立确认：不存在 `run_status === 'running'` 与 `run_interrupted` 同时为真的可达状态；重放确定（无时间/随机依赖）；`run_interrupted` 全仓无其他消费者；`coarsenPulseState` 穷尽性由编译器保证（实测触发 TS2366）。

| # | 处置 |
| --- | --- |
| 1 P3 `coarsenPulseState` 的「已中断」映射无断言 | **已修**：补 `expect(deriveRunSummary(s).label).toBe('已中断')`（与脉冲是两条独立映射）+ 变异验证 |
| 2 P3 无测试把 `pulse-interrupted` 类名与 CSS 选择器绑起来 | **登记为已知覆盖缺口，不改**：JS/CSS 分界的固有限制，仓库无「测试读 CSS」先例；当前视觉表现不受影响（`.run-pulse` 基类已是同款中性 token） |
| 3 P3 提前返回同时覆盖 `failed`/`cancelled`，优先级仅靠口头不变量 | **已修（显式化）**：条件补成 `run_interrupted && run_status === 'completed'`——真实数据下恒真，故对全部合法日志行为**逐字节不变**；破坏不变量时退化为「更晚的终态赢」。新增一例锁住该退化语义 |
| 4 P3 后续发消息 RTT 内短暂显示「已中断」+ 图标风格 | **不改**：瞬时态比修复前的绿色「已完成」更接近真相；图标纯审美，换图标零收益（§9.3） |

### 8.5 门禁（本批最终实跑，含第三、四轮）

tsc ✓ · vitest **497 passed**（28 文件）· oxlint **35 warnings / 0 errors**（基线未变）· playwright **112 passed**（104 + 审批卡 8；瞬态三键 4 例见第四轮）· vite build ✓。真机联调车道（`web/e2e-live/` + `playwright.live.config.ts`）不计入主车道门禁。

> 第四轮新增 `m-stream-affordances.spec.ts`（2 用例 × 2 视口），把此前唯一没点过的三个按钮（`tool-out-wrap-btn` / `tool-out-jump` / `reasoning-jump`）用 mock 流钉住窗口后**真实点击**；独立审查结论 approve（0 P0/P1/P2、6 项 P3 全修），并按加固后版本重跑三处变异均红。

> 第三轮的审查（针对 `l-auth-banner.spec.ts`）发现并已修一项 **P2**：我原注释声称 `api.test.ts` 覆盖 401 分类，**实则全 `src` 测试树零个 401 引用**（该缝无单测）。已补齐 3 例（401→`UnauthorizedError`、`onUnauthorized` 广播 detail、body 非 JSON 的回退文案）——故 vitest 由 494 升至 497。同一轮还把一处**说反的真实行为**订正：横幅关闭**并非**永久忽略，任何新 401 都会让它回来（e2e 已按真实行为断言，并做变异验证）。

---

## 8.6 追加真机验证：子会话（委派 / 分叉 child）刷新一致性

§3.1 曾声称「刷新后恢复选中会话（**含分叉 child、委派 child、`打开子会话` 的目标**）」，当时**只有推断、无证据**（回归锁 5 例全用普通会话 id）。本轮用真实浏览器 + 真实后端补齐，方法为「刷新前/后取正文指纹（长度 + 全文哈希 + 轮数 + 脉冲）逐字节对比、零点击」：

| 场景 | 入口 | 刷新前后 | 结论 |
| --- | --- | --- | --- |
| 委派 child `2515a128` | 列表点击该行 | hash `818904662` / 4710 字符 / 2 轮 /「已完成 · 4,635 tok」 | **逐字节相同** |
| 委派 child `2515a128` | 父节点**「打开子会话」按钮** | 同上（键被写为 child id） | **逐字节相同**（两条入口收敛） |
| 分叉 child `1fdac9b9`（410 事件） | 列表点击该行 | hash `-815616722` / 12,887 字符 / 8 轮 /「失败 · 28,357 tok」/ Inspector「共 410 条」 | **逐字节相同** |

**有意保留的边界（勿当缺陷）**：右栏委派**钻取**（`Inspect 子会话`）刷新后退回默认 run 焦点。Inspector 属**视图状态**，与 `inspectorOpen` 一样按冻结决策「仅本会话内，不持久化」；会话选中与正文全部恢复，只有右栏子面板焦点不恢复。

**新增回归锁 + 审查**：`k-refresh-restore.spec.ts` 增 1 例（×2 视口）。首版用 `addInitScript` 播种，**变异验证时发现它只覆盖读路径**（把写入按 `-child` 过滤后依然全绿），遂改为真实点击写入路径并让事件按 session id 返回不同正文；改后同一变异在两个视口都红（`Expected: "e2e-session-0001-child" / Received: null`）。对该用例的独立审查：**0 个 P0/P1/P2**，5 项 P3 全为「注释/标题超出实际断言」类，**已全部处置**（准确表述 + 按 id 区分事件 + 移除恒真断言 + 行定位改 `title` 属性前缀）。

---

## 8.7 第三轮：控制面清点（45 个按钮逐个核对）与后端问题移交

### 为什么要做这一轮

前两轮的巡检表是**人工列举**的，无法证明「每个按钮都点过」（用户的硬要求）。本轮改为**可核对的方法**：从源码枚举全部交互控件再逐项对照记录。

- 源码 `<button>` 共 **45 个**（17 个文件）；`onClick` 的非 `<button>` 元素 **0 个** → 按钮即全部点击面。
- 对照结果：初版用**关键词比对**判出「11 项未覆盖」，但复查发现该方法**两个方向都会错**——`保存`/`清除` 命中的是无关散文（登记簿第 160/167 行），于是令牌弹窗的「保存」「清除」实际从未被点过却判为 OK（假阳性）；而 `滚动到最新`（第 19 行有 e2e + 真机证据）、`恢复会话`（第 41 行）其实有覆盖（假阴性）。**故放弃文本比对，改为逐个真机点击。**
- **最终逐标签核对（45 个）**——第四轮补齐瞬态窗口、第五轮补齐审批卡后的**最终账目**：
  - **38** 个「真实后端 + 真实浏览器」点击验证通过；
  - **3** 个（`tool-out-wrap-btn`、`tool-out-jump`、`reasoning-jump`）在第四轮用 **mock 流钉住窗口后真实点击**（不发 `tool/result` / `reasoning/completed` → 投影状态恒为 running/streaming），新增 `web/e2e/m-stream-affordances.spec.ts`，三个按钮各经一次变异验证；
  - **1** 个 `auth-banner-close` 用 **mock 401** 真实点击（`l-auth-banner.spec.ts`，本地无 `jwt_secret` 时它不出现）；
  - **1** 个 `ContextProviderPicker` 触发器在 `picker-search-visibility.spec.ts` 内用 mock 目录激活（本部署后端目录为空，故真机上正确地不渲染）；
  - **2** 个审批卡「批准」「拒绝」：第五轮**真机点击**（真实后端 + 真实模型）——原记「产品不可达」**已证伪**。门是 `session/service.py:348` 的 `permission_mode_explicit`（显式选权限档位即开启交互式审批），不是 `auto_approve`；选「只读」后 `write` 工具触发 `tool/approval-requested`，卡片渲染，两键点击后 JSONL 留下 `permission/resolved`（`approve_once` / `deny`）。回归锁 `web/e2e/n-approval-card.spec.ts`（4 用例 × 2 视口，含 POST 请求体断言，4 处变异验证全红）。

  即 **45/45 全部已被点击**，**无「未验证」按钮遗留**。默认（不选权限档位）不出现审批卡是**正确的产品默认**；是否把交互式审批做成默认档位属产品决策，不在本轮范围。

### 需要集成 AI 转交后端的问题（本轮主产出，均有文件行号）

| # | 级别 | 问题 | 根因（后端） |
| --- | --- | --- | --- |
| **OBS-011** | P2 | 工具输出在 UI **与落盘 JSONL** 中都是乱码（`��ʱ��Ӧ�� i��`、`���� Ping 127.0.0.1 …`）。**乱码发生在落盘之前**，前端只是忠实渲染 | `src/agent_harness/sandbox/local.py:166-167` 用 `encoding="utf-8", errors="replace"` 解 cmd.exe 的 **GBK** 输出；铁证：原始字节里 U+FFFD 与「侥幸合法的 GBK 双字节」混杂（GBK 的「时/应」两字节恰是合法 UTF-8）。同模式见 `sandbox/docker.py:140-141`。**JSONL 是本项目可观测性的单一事实源，乱码一旦落盘不可逆** |
| **OBS-012** | P2 | `bash` 工具在 Windows 上**不是 bash**：`for i in $(seq 1 10); do …; done` 41ms 内 `exit_code=1`，stderr 为 cmd.exe 的「此时不应有 i。」；同会话里 `$(whoami)` 被**原样回显** | `sandbox/local.py:161` `shell=True` → `COMSPEC`（cmd.exe）。工具名与语义不符会诱导模型按 bash 语法写命令并莫名失败（该会话因此 7 次工具调用、2 次失败、4 次 fallback） |
| **OBS-013** | P2 | provider 退化重复：一轮生成 **2,868 个 `text/delta`、186,507 字符**的 `"Let me run the command."` 无限重复，**始终不调用工具**，持续 3.5 分钟（由用户点停止收口）。另有多次 `model/fallback: deepseek-v4-flash-0731 → glm-4.5-air · InternalServerError` | provider/后端。前端表现正确（脉冲「思考中」、文本持续流入、停止可用） |
| **OBS-014** | — | bash 工具 **10.0s 硬超时**且 `retryable:false`（`sleep 30`、`ping -n 45` 失败；`sleep 9`、`ping -n 4` 正常） | 与 OBS-009 同族，此处补实证。与 OBS-013 组合会出现「想跑长命令 → 超时 → 反复重试/退化」的失效链 |

### 本轮新增的测试

`web/e2e/l-auth-banner.spec.ts`（×2 视口）：401 → 引导横幅 → 点「关闭提示」→ 横幅消失且不复现。因该按钮在本地开发**不可达**（后端仅配 `jwt_secret` 时校验令牌，`web/app.py:594` fail-open），故按后端**已冻结的契约形状**（`{"detail":"Missing identity token"}`）在网络层造 401。**变异验证**：把关闭回调改为空实现 → 两视口都红（`Expected: hidden / Received: visible`），随后还原。

### 瞬态窗口：第三轮记为缺口，**第四轮已补齐**

`tool-out-wrap-btn`（自动换行）、`tool-out-jump` 与 `reasoning-jump`（↓ 最新）：三者所在的流式容器要求 `streaming === true` 才会出现 `suspended` 浮标，而本后端 cmd.exe **缓冲输出**（整段输出以**单个终态 delta** 到达、`result` 紧随其后），叠加工具 10s 硬超时，真机上该窗口仅存毫秒级（实证：`echo LINE-1 & ping…` 6.2s 跑完、`output_delta` 仅 1 条；第三轮 6 次真机尝试 1 次模型拒调工具、1 次 3.5 分钟退化循环）。第三轮如实登记为「无法点击」。

**第四轮改为可控复现**：两个容器的 `streaming` 都取自**投影状态**而非 socket——工具是 `tool.status === 'running'`（`ToolCard.tsx:137`），推理是 `block.status === 'streaming'`（`ReasoningBlock.tsx:206`）。故 mock 流里**不发 `tool/result` / `reasoning/completed`**，窗口即常驻；再补足文本量让容器可滚动（`suspended` 的前置条件，测试里显式断言 `scrollable === true`），即可确定性点击。新增 `web/e2e/m-stream-affordances.spec.ts`（2 用例 × 2 视口），三个按钮**各经一次变异验证**：换行 `onClick` 改空实现 → `Expected: "自动换行" / Received: "不换行"`；两个 `jump` 改空实现 → `Expected: 0 / Received: 1`。

**口径**：点击是真实浏览器里的真实鼠标事件，只有**网络**是 fixture——故与前 38 个（真实后端）分开记账，不混为「真机」。

---

## 9. 追加批次：OBS-015 修复——审批卡区分幂等已决(409)与真失败(5xx)

### 9.1 改了什么

| 文件 | 变更 |
| --- | --- |
| `web/src/lib/api.ts` | 新增 `AlreadyResolvedError extends Error`；`postApproval` 在 HTTP 409 时抛它（幂等成功），其它非 ok 抛普通 `Error`（真失败） |
| `web/src/components/ApprovalCard.tsx` | catch 分支改为：`AlreadyResolvedError`(409) → 幂等成功翻卡片；其它错误 → **保持 pending** + 显示可见错误(`role="alert"`) + 按钮重新可用可重试 |
| `web/e2e/n-approval-card.spec.ts` | +2 用例 ×2 视口 = 4 例：POST 500 → 卡片保持「需要审批」+ 按钮仍可用 + 出现错误提示；POST 409 → 幂等成功，卡片翻「已批准」 |
| `web/src/lib/api.test.ts` | +4 例单测：200 ok / 409 AlreadyResolvedError / 500 plain Error / 422 plain Error |
| `web/src/styles/app.css` | 新增 `.approval-error` CSS 规则：danger 淡染底 + 左侧 2px 实条，让用户一眼看到「这次审批没有生效」 |

### 9.2 为什么符合 Spec

**OBS-015 的核心问题**：`ApprovalCard.tsx` 的 `catch` 块对**任何**错误都翻成「已批准/已拒绝」——注释说「其它错误保持 pending」，代码却相反。对安全审批交互，这个方向的假象比「转圈不响应」更危险：用户以为放行了，实际 run 还卡在等审批（后端 300s 才 fail-closed）。

**修复后的语义**：
- **HTTP 409**（`AlreadyResolvedError`）：后端 `PendingApprovalQueue.resolve()` 对同一 approval_id 的第二次决策返回 409。这**不是**错误——用户的意图已经生效，卡片应翻到「已批准/已拒绝」。
- **其它错误**（网络失败 / 5xx / 4xx 非幂等）：决策**没有**到达后端。卡片**保持 pending**，显示可见错误提示（`role="alert"`），按钮重新可用，用户可以重试。

**不变量遵守**：
- §8 Scope Lock：所有编辑追溯到 OBS-015，无顺手重构
- §15 CSS 主题变量：`.approval-error` 复用既有 `--color-destructive` token，未新增 `:root` 变量
- 不变量 #22（Web UI 不维护第二套不可对账 Session 真相）：本修复只改 UI 层错误处理，不触碰会话真相

### 9.3 测了什么

**单元测试**（`api.test.ts` +4 例）：
- 200 → 返回 resolved 结果
- 409 → 抛 `AlreadyResolvedError`（调用方据此翻卡片为幂等成功）
- 500 → 抛普通 `Error`（不是 `AlreadyResolvedError`）
- 422 → 抛普通 `Error`（无效决策，不是幂等成功）

**e2e 回归锁**（`n-approval-card.spec.ts` +2 用例 ×2 视口 = 4 例）：
- POST 500 → 卡片保持「需要审批」+ 按钮仍可用 + 出现错误提示
- POST 409 → 幂等成功，卡片翻「已批准」

**变异验证**两处全部生效：
1. 还原 `ApprovalCard` catch 旧行为（任何错误都翻卡片）→ POST 500 用例变红（`Expected: "需要审批" / Received: "已批准"`）
2. 禁用 `AlreadyResolvedError` 分支（`if (false)`）→ POST 409 用例变红（卡片不再翻「已批准」）

### 9.4 code-review 结果

**Standards 轴**：0 hard violations。2 处 minor smells（dead constructor message；duplicated one-liner），均 acceptable。

**Spec 轴**发现 4 项，全部处置：
1. **404 幂等语义未处理** → 经核实后端契约（`app.py:1135-1175`），404 = approval 不存在（`ApprovalRequestMissing` / `ApprovalQueueMissing`），**不是**「已解析」。409 才是幂等已决（`ApprovalAlreadyResolved`）。当前代码正确，仅修正注释。
2. **失败文案需更明确** → error message 已体现失败原因（`审批失败（500）`），配合 `.approval-error` 的 danger 样式，用户可明确感知「这次审批没有生效」。
3. **`.approval-error` 无 CSS 规则** → 已补（danger 淡染底 + 左侧 2px 实条）。
4. **tracker 未更新** → 已更新 `SDD_TICKET_TRACKER.md`。

### 9.5 门禁

tsc ✓ · vitest **501 passed**（28 文件）· oxlint **35 warnings / 0 errors**（基线持平）· playwright **116 passed**（`--workers=2`）· vite build ✓

### 9.6 还剩什么 / 风险与未决项

| 项 | 级别 | 说明 |
| --- | --- | --- |
| 404 与 409 的语义边界 | 低风险 | 后端 404 = approval 不存在（可能是过期事件或跨 session 的 id），409 = 已决。两者都不是「网络失败」。当前代码只在 409 时翻卡片，404 走普通 Error 路径（保持 pending + 报错）。如果后端未来把「已决」改成 404 返回，需要同步调整 `postApproval` 的分类逻辑。 |
| 审批超时 | 产品决策 | 后端 300s fail-closed（默认拒绝）。前端在此期间持续显示 pending 卡片。是否给前端加倒计时提示属产品范围。 |
| 是否默认开启交互式审批 | 产品决策 | 当前需用户显式选权限档位才会出现审批卡。这是正确的产品默认。是否改默认属产品决策。 |

### 9.7 本批 commit

| commit | 内容 |
| --- | --- |
| `cb0e008` | fix(OBS-015): ApprovalCard 区分幂等已决(409)与真失败(5xx) |
| `4580a69` | code-review(OBS-015): 补 .approval-error CSS + 更新 tracker + 修正注释 |

---

## 10. 追加批次：UI Polish 六票（2026-09-12/13）——设计优化批（本文件最新批次）

> 本节取代上文各节的「本批」地位：UI Polish 批次是 2026-09-12 用户 grill-me 决策（D1-D6）后的
> 六票设计优化，需求事实源 = `docs/UI_POLISH_PRD.md`，逐票规格 = `docs/UI_POLISH_TICKETS.md`，
> 视觉规范基准 = 根目录 `DESIGN.md`（+ `.impeccable/design.json` sidecar）。

### 10.1 本批 commit 链

| commit | 内容 |
| --- | --- |
| `cd107a2` | 批次 0：DESIGN.md + design.json + PRD + TICKETS + tracker 登记 |
| `1ae3bf2` | U-1：UI-01 审批卡重塑（结构化参数/DiffBlock 复用/焦点/aria/快捷键/composer 锁定）+ UI-02 排版地板（--text-xs 12px、--text-tertiary 暗 0.52/亮 0.63 实测、28 处 10px 升档、tl-type 去 accent） |
| `236049f` | U-1 双轴 review 修复（多卡快捷键双发 autoFocus 门控、三处亮色 AA 不达标 ink 调和、t-contrast 解析器 throw 化等 24 项处置） |
| `522602d` | U-2：UI-03 Inspector run 分组（timelineGroups 纯函数 + 分组头/序号/tab 计数）+ UI-04 信任裂缝（forked/审批摘要 + formatShortDuration <50ms）+ UI-05 Rail 空态文字按钮 |
| `e543ae1` | U-2 双轴 review 修复（**hooks 崩溃**、空态自相矛盾、交错 run 序数、负时长 clamp、断言假绿、detail-tab aria-label 等） |
| （本批尾） | U-3：UI-06 minor（CJK 间距「切换到 Raw」、主题 hint 去箭头、run-badge 视觉参数向 .run-pulse 收敛）+ 删临时审计脚本 |

### 10.2 集成 AI 必须知道的行为变化

1. **审批卡交互**（UI-01）：Ctrl/Cmd+Enter=批准、Ctrl/Cmd+Backspace=拒绝（仅第一张 pending 卡挂监听）；审批期间 Composer 锁定（placeholder「等待审批决策…」）。
2. **Inspector Timeline**（UI-03）：时间线按 run_id 分组渲染，组头「Run N + 状态徽标 + 事件数」；序数按**首次出现**（全会话范围，尾窗裁剪不重排）；头部「N runs · M 事件」；五个视图 tab 带条目计数徽标。
3. **时长语义**（UI-04）：<50ms 显 `<50ms`（不再造 1ms 假精度）；ReasoningBlock <1s 显「持续 <1s」/「中断于 <1s」（不再有「持续了 0 秒」）。
4. **摘要文案**（UI-04）：`session/forked`→「已分叉」、`tool/approval-requested`→「等待审批 · {tool}」、`permission/resolved`→「审批已决（{decision}）」（不再落「未知事件」）。
5. **Rail 空态**（UI-05）：真空态出文字按钮（新建项目/新会话）+ 空态文案带「注册项目目录 →」行动链接；列表失败仍只显错误条（不矛盾）。
6. **CommandPalette**（UI-06）：密度条目「切换到 Raw」（CJK 半角空格）；主题 hint 无方向箭头。
7. **token 三改**（UI-02）：`--text-xs` 11→12px；`--text-tertiary` 暗 0.42→0.52、亮 0.63（实测 AA）；10px 仅存 2 处合法 micro-label。

### 10.3 门禁（U-3 尾末次实跑）

tsc 0 · vitest **623 passed**（35 文件）· oxlint **38 warnings / 0 errors**（基线持平）·
playwright **196 passed**（`--workers=2`）· vite build ✓。

变异验证台账（本批累计）：U-1 5 处 + U-2 3 处 + U-3 2 处（palette CJK 间距 6 红 / hint 箭头 2 红），全部红→绿闭环后还原。

### 10.4 未修 / 遗留（明确披露）

| 项 | 处置 |
| --- | --- |
| Split/Preview 空架子（评审 Minor ⑤） | 不做——诚实设计（工作区未实现时的诚实占位），登记 issues log |
| 半截 run/session ID（评审 Minor ⑥） | 不做——信息架构取舍（完整 ID 已在分组头 title 与 Overview），登记 issues log |
| 时间线 kind 过滤 chips（UI-03 票面原意） | 以 tab 计数徽标实现（五个图标是视图 tab 不是 kind 过滤器），偏离已记录于 tracker |
| 审批 fail-closed 倒计时（q4-④） | 用户决策 defer——需先核实后端是否发超时时间戳，不硬编码 300s（不变量 #22） |

### 10.5 审查产物

- U-1 双轴：Spec 10 + Standards 14 findings → 24 项处置表（tracker「U-1 批量两轴审查」节）。
- U-2 双轴：Spec 3P1/3P2/3P3 + Standards 1P1/5P2/6P3 → 全部处置（commit `e543ae1` message）。
- U-3 收尾审查：见 tracker 对应小节。
