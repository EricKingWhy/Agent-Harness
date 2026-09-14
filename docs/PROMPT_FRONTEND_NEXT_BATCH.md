# 前端下一批提示词（可直接复制给前端 Agent）

> 用法：把下面 `---` 之间的整段复制给在前端 worktree（`D:\intelligence-agent-frontend` / `feat/frontend`）工作的 Agent。
> 本文件随进度更新；**权威进度**仍是 `docs/SDD_TICKET_TRACKER.md`。

---

## 任务：修复 OBS-015（审批卡错误处理）+ 收尾覆盖缺口

工作目录：`D:\intelligence-agent-frontend`，分支 `feat/frontend`。遵守 `AGENTS.md`：**不许 push**，只做本地 commit；不许顺手重构（§8 Scope Lock）；遇到规格冲突停下来报告。

### 背景（先读，别跳过）

上一批把「45 个按钮逐个点击」收口到 45/45，并证伪了两个「不可达」误判。过程中发现一个前端缺陷 **OBS-015**，登记但未修（当时按 Scope Lock 只报告）。本批处理它。

`docs/FRONTEND_ISSUES_LOG.md` 的 **OBS-015** 条 + `docs/HANDOFF_APPROVAL_CARD_COVERAGE.md` §6/§7 是本批的必读材料。

### 任务 1：修 OBS-015 —— 审批卡把「任何错误」都当成已决（P2）

**现状**（`web/src/components/ApprovalCard.tsx` 的 `decide`）：

```ts
} catch {
  // 409 = already resolved (idempotent success); other errors leave card pending
  setDecision(approved ? 'approved' : 'denied');
}
```

注释说「其它错误保持 pending」，**代码却对任何错误都翻成已批准/已拒绝**。后果：审批 POST 真失败（网络抖动 / 500 / 404）时，用户看到「已批准」的**乐观假象**，而 run 实际仍卡在等审批（后端 300s 才 fail-closed 拒绝）。对安全相关交互，这个方向的假象比「无响应」更危险。

**要做的事**：

1. 区分两类错误：
   - **幂等已决**（HTTP 409 `ApprovalAlreadyResolved`）→ 视为成功，翻「已批准/已拒绝」（保留现有意图）。
     > ⚠️ **2026-09-11 订正：原文此处还写了「以及……404」，该前提是错的。**
     > 后端 404 有四个来源（session 不存在 / 审批队列缺失 / `approval_id` 不在队列 / 事件过期，
     > `web/app.py:1157-1166`），**无法**与「已解析且已出队」区分。把 404 当成功会重新引入
     > OBS-015 本身的安全假象（决策其实没生效，UI 却显示「已批准」）。
     > **404 必须与其它非 2xx 同级：保持 pending + 提示重试。** 真已决由 `permission/resolved`
     > 投影事件把卡片移出待决队列来兜底（已由 `web/e2e/n-approval-card.spec.ts` 锁定）。
   - **其它错误**（网络失败 / 5xx / 4xx 非幂等）→ **保持 pending**，并给用户可见的错误提示 + 可重试（按钮重新可用）。
2. 需要 `api.ts` 的错误类型支撑：现在 `postApproval` 走 `apiFetch`，已有 `NotFoundError`（404）。确认 409 会被归成什么（读 `lib/api.ts` 的 `apiFetch`），必要时补一个能区分「已决」与「真失败」的判别，**不要**用一个宽泛的 `catch` 抹平。
3. 文案：失败提示要让用户知道「这次审批**没有**生效」，并提示重试。中英文口径跟随现有 UI（全中文）。
4. **回归锁**（必须，且必须能证明有效）：
   - 新增/扩展 e2e（建议放 `web/e2e/n-approval-card.spec.ts`，它已有 4 个用例的成熟结构）：**POST 500 → 卡片保持「需要审批」+ 按钮仍可用 + 出现错误提示**。
   - 把「POST 404/409 → 视为已决」也补成显式用例。
   - 对每个新断言做**变异验证**：把对应实现改坏，确认测试**变红**，再还原。变异脚本请在改文件时用 `newline=''`（见下方坑点）。
5. 如果发现「保持 pending」会与既有 `useSession` / 流式状态机冲突（例如 `permission/resolved` 事件已经到达但本地还是 pending），**停下来报告**，不要硬改。

**验收标准**：

- 非幂等错误下，卡片**不**显示已批准/已拒绝；用户能重试。
- **409** 幂等语义走「已决」；**404 不走**——它保持 pending（见上方 2026-09-11 订正），已由 `web/e2e/n-approval-card.spec.ts` 的 404 用例锁定。
- 新断言有变异验证记录（写在 commit message 或登记簿里）。
- `npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build` 全绿；**oxlint 基线 35 warnings / 0 errors 不得升高**。

### 任务 2：把「审批卡失败路径」写进登记簿

在 `docs/FRONTEND_ISSUES_LOG.md` 的 OBS-015 条里追加「处置结果」（谁修的、怎么修、回归锁在哪、变异验证结果），并把状态从「需产品决策」改成实际结论。若产品方向有变，明确写出。

### 任务 3（可选，先问再动）：`已中断` 脉冲态的真实语料覆盖

`docs/HANDOFF_APPROVAL_CARD_COVERAGE.md` §7 登记：`已中断` 脉冲态（`runState.ts` 第四态）**只有单测覆盖**，没有真实语料；且 `pulse-interrupted` 类名与 CSS 选择器之间**没有测试绑定**（改 CSS 类名不会被任何测试发现）。

若时间允许且不改产品行为，可考虑：
- 补一条「类名 ↔ CSS 选择器」的绑定测试（例如断言样式表里存在该选择器），防未来重命名静默失配。
- 或者：构造一个「中断且从未重跑」的会话 fixture（e2e mock 事件即可，不需要真后端），让脉冲态在 e2e 层可见。

**这一项属于可延后**，若判断有风险就只登记、不动手。

### 明确不在本批范围（别做）

- `StreamOrchestrator`（C1）提取——高风险，需监督与测试先行，**等用户批准**。
- `session/forked` 摘要文案、7 个未接线事件类型是否显示——**需产品确认**。
- 是否把交互式审批做成默认档位——**产品决策**。
- 后端问题（OBS-008～OBS-014）——不在前端范围，已在集成提示词里移交。

### 必须遵守的工程纪律（上一批踩过，别再踩）

1. **新增测试目录 / 改测试配置时，两处一起改**：`playwright.config.ts` 的 `testDir` 与 `vitest.config.ts` 的 `exclude`。只改一侧会让 vitest 去收集 Playwright 的 `test()` 而让单测车道整体变红（上一批真实踩到）。核验：`npx playwright test --list | grep -c <目录>` 应为 0。
2. **用脚本改文件一律 `newline=''`**：Python 文本模式会把 LF 写成 CRLF，而 `git diff` / `git hash-object` 因 `autocrlf=input` 看不出来（会留下幽灵 `M`）。核验：`git ls-files --eol <file>` 应为 `i/lf w/lf`。修复：`git show ":<path>" > t && mv -f t "<path>"`。
3. **别宣布「不可达」**：先把渲染条件追到源码行，再问「这个状态分支能不能用 fixture 造出来」。本批已有两次误判（三个瞬态按钮、审批卡），都是把「我没找到路径」当成「路径不存在」。
4. **「UI 变了」不等于「后端真的写了」**：涉及写入生效的断言，要落到 durable 真相（后端事件 / JSONL / 副作用）。
5. **每个新断言先做变异验证**，确认把实现改坏它能变红。变异脚本要 `assert` 锚点存在并打印标记；变异后先确认 `tsc -b` 通过再信失败结果。
6. **单测车道不得引入 DOM 依赖**：`vitest` 是 node-only（`renderToStaticMarkup`，无 jsdom）→ **不能点按钮**。要点击就写 Playwright e2e。
7. 每完成一项：`/code-review`（两轴：Standards + Spec）→ 修 findings → 再 review 到零 finding → 全量门禁 → 本地 commit → 更新 `docs/SDD_TICKET_TRACKER.md` → 更新集成提示词。

### 本批交付要求

- 本地 commit（**不 push**）。
- 更新 `docs/SDD_TICKET_TRACKER.md`（进度 + 门禁实跑值）。
- 更新 `docs/integration/FRONTEND_REFRESH_PERSIST_INTEGRATION_PROMPT.md`（集成 AI 要读的那份）。
- 交付时说明：改了什么 / 为什么符合 Spec / 测了什么 / 还剩什么 / 风险与未决项。

---
