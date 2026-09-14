# 前端 → 后端 / 集成 AI：`feat/frontend` 集成交接

> 日期：2026-09-09 ｜ Worktree：`D:\intelligence-agent-frontend` ｜ 分支：`feat/frontend`
> （批次主体至 `4b588af`；本交接文档为其后一个 docs commit，分支尖端以 `git log --oneline -1` 为准）
> 对应后端手册：`docs/HANDOFF_FRONTEND_TECH_DEBT.md`（最新版）
> 集成规则：`AGENTS.md` §13 / §14

---

## 0. 结论（TL;DR）

- **本批无新增 bug**，五道门禁全绿（§5）。
- **变更路径与 main 侧零交集**，预判无冲突（§1.3）。
- 有 **3 项存量已知问题**（2 项已存在于 `main`、1 项待契约决策），**均不阻塞集成**，逐条见 §7。
- 本分支 **未 merge、未 push**；按 §14.4，集成动作需用户明确批准，由集成 AI / Git Integrator 执行。

---

## 1. Git 拓扑

### 1.1 分支状态

| 项 | 值 |
| --- | --- |
| Worktree | `D:\intelligence-agent-frontend` |
| Branch | `feat/frontend` |
| 分支尖端 | 批次主体 `4b588af` + 本交接文档 1 个 docs commit（不在此处写死自身 hash，避免 amend 自引用） |
| `main` | `3a662a9`（`Merge branch 'main' into feat/backend`，即 `feat/backend` 已合入本地 main） |
| merge-base(`HEAD`, `main`) | `46990fb` |
| ahead / behind | **10 / 8** |
| 变更规模 | 批次主体（`main...4b588af`）：20 files changed, +671 / −151；另加本交接文档 1 file |

### 1.2 提交清单（`main..HEAD`，10 个）

| commit | 内容 | 契约影响 |
| --- | --- | --- |
| `7e79445` | fix(#35)：主题亮色变量组维护纪律——`index.css` 自警注释 + `AGENTS.md` §15 | 无 |
| `807b7db` | feat(#37)：交互式审批走通——投影层 + `ApprovalCard` 内联渲染 | 消费既有事件，无请求契约变更 |
| `a518d3f` | feat(web)：续聊透传 amend 字段（model / agent_profile / reasoning_effort / context_providers） | **`/messages` 请求体新增 4 个可选字段** |
| `5e5c1e1` | fix(web)：code-review 修复——修正 ADR 误引 + 去重 e2e 目录 + 补 amend 路径测试 | 无 |
| `2be274d` | test(web)：合并 fetch stub helper | 无 |
| `af0a270` | fix(web)：二次 review 修复——Gap 注释引对章节 + amend 类型改 `Omit` + e2e 抽 helper | 无 |
| `88548af` | refactor(web)：e2e `pickControl` 上提 fixtures + `pickFirstModel` 去常量参数 | 无 |
| `3560d92` | fix(web)：续聊 422 改提示「参数无效」+ **修复失败提示被 viewing effect 抹掉** | 422 提示文案变化 |
| `4b588af` | docs：`FRONTEND_DEFER.md` + 回复后端 P1 修复（`FRONTEND_REPLY_P1_FIXED.md`） | 无 |
| 紧随其后 1 个 docs commit | 本交接文档（`FRONTEND_INTEGRATION_HANDOFF.md`） | 无 |

### 1.3 冲突预判：无

对 merge-base 两侧的**变更路径取交集**（`git diff --name-only 46990fb main` ∩ `git diff --name-only 46990fb HEAD`）：

```
（空集）
```

- 后端侧 19 个路径（`src/agent_harness/**`、`tests/web/**`、`docs/**`）。
- 前端侧 20 个路径（`web/**`、`AGENTS.md`、`docs/FRONTEND_DEFER.md`、`docs/integration/FRONTEND_REPLY_P1_FIXED.md`）；加本交接文档共 21 个，仍与后端侧零交集。
- 结论：**预期 merge 干净**。但这只是静态预判，实际以 `git merge` 结果为准；出现冲突立即按 §14.7 停止自动解决。

### 1.4 注意：本分支基于旧 merge-base

`main` 已吸收后端 P1 批次（`b663f75` 等 8 个 commit），本分支尚未 rebase / merge 这些内容。
按 §14.6「先回后正」，建议顺序：

```text
origin/main → feat/frontend（在这里解冲突、跑门禁、复核）
           → main（feat/frontend 稳定后再合入）
```

**不要**先在 `main` 上解复杂冲突（§14.8）；**不要**用 `git pull`（§14.5）。

---

## 2. 文件清单（批次主体 20 files, +671 / −151）

**契约 / API 层**

| 文件 | 改动 |
| --- | --- |
| `web/src/lib/api.ts` | `SendMessagePayload` 增 4 个 amend 字段 + `sendMessage` 兜底归一化（空值/空数组不发键）+ `StartSessionPayload` docstring 更正（T2） |
| `web/src/lib/api.test.ts` | `captureFetch` 吸收 `mockFetchOnce`；新增 amend 路径单测 |

**状态 / 投影**

| 文件 | 改动 |
| --- | --- |
| `web/src/hooks/useSession.ts` | `sendFollowUp` 增 `amend`（`Omit<SendMessagePayload, 'content'\|'mode'\|'max_steps'>`）；422 改抛 `CONTINUE_PARAMS_ERROR_TEXT`；**viewing effect 不再无条件清错误** |
| `web/src/hooks/useSession.test.ts` | 422 文案判定单测 |
| `web/src/lib/projection.ts` / `.test.ts` | #37 审批事件投影 |
| `web/src/types.ts` | #37 审批相关类型 |

**组件 / 样式**

| 文件 | 改动 |
| --- | --- |
| `web/src/App.tsx` | 续聊分支「有值才带」传 amend；修正过期注释 |
| `web/src/components/ApprovalCard.tsx`、`Conversation.tsx` | #37 内联审批卡渲染 |
| `web/src/index.css` | #35 亮色 token 自警注释 |

**e2e / 文档**

| 文件 | 改动 |
| --- | --- |
| `web/e2e/fixtures.ts` | 共享目录（`MODELS` / `PERMISSION_MODES` / …）+ `pickControl` / `pickFirstModel` |
| `web/e2e/continuation.spec.ts` | 新增 5 条：amend 四项 / 部分有值 / `context_providers` 进 payload / queued 不误报 / 422 文案 |
| `web/e2e/{control-row,context-providers,g-visual-qa,model-picker}.spec.ts` | 改用 fixtures 共享目录与 helper |
| `AGENTS.md` | 新增 §15（CSS 主题变量维护纪律） |
| `docs/FRONTEND_DEFER.md` | 新增 F-DEFER-1 待办 |
| `docs/integration/FRONTEND_REPLY_P1_FIXED.md` | 新增：回复后端 P1 修复的 ①②③ |

---

## 3. 契约接触面（请后端复核）

### 3.1 `POST /api/sessions/{sid}/messages` 请求体

新增**可选**字段（与 create 路径同名同义）：

```
model?  agent_profile?  reasoning_effort?  context_providers?
```

- **不带 `permission_mode`**：该字段不在 `/messages` 契约内（与后端 `AmendOptions` 一致）。
- **「有值才带」**：值为 `undefined` / `''` / `[]` 时**不发键**，让后端走默认；`sendMessage` 是兜底归一化点，`App.tsx` 续聊分支另有同款展开，两者不冲突。
- **已知 Gap**：`context_providers: []` 因此**无法表达「显式空集」**（契约把 `null`/缺省定为「全部已接线 Provider」，`[]` 定为「显式零个」；前端选择器初始态就是 `[]`）。见 §7.1。

### 3.2 422 处理

- `sendFollowUp` 收到 422 → 抛 `CONTINUE_PARAMS_ERROR_TEXT = '续聊参数无效（422）：请刷新选项后重试'`。
- **不解析 `detail` 子串**：`detail` 不是契约文本，且形状不统一（Pydantic 数组 vs `HTTPException` 字符串）。四种成因对用户的下一步动作相同。
- create 路径的 `UNKNOWN_MODEL_ERROR_TEXT` 逻辑未改动。
- 若将来要「失效引用类 id → 自动刷新目录」，建议后端给 422 加机器可读 `code` 字段，前端按 code 分支。

### 3.3 明确未动的部分（遵守交接约束）

- SSE 帧形状 / `seq` 投影 / 消费机器（`lib/sse.ts`、`projection` 的流式路径）**零改动**。
- 未迁 WS。

### 3.4 行为修复（本批唯一影响可见行为的状态改动）

`3560d92` 修复：viewing-mode 历史加载 effect 原先**无条件** `setError(null)`，而 `sendFollowUp` catch 是「先 `setMode(viewing)` 再 `setError(...)`」——同批次被抹掉，导致**所有续聊失败、重连 give-up、重连 404 提示此前都是静默的**。修复后只在真正切换会话（或首次加载）时清错误。

> 这是修 bug，不是新增契约；但集成后 UI 会**开始显示**此前被吞掉的错误横幅，属于预期变化。

---

## 4. 门禁证据（本 worktree 实测）

环境：Node + pnpm 工作区，`web/` 为前端包。

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| Type check | `npx tsc -b` | exit 0，无输出 |
| 单元测试 | `npx vitest run` | **25 files / 377 tests passed**（3.77s） |
| Lint | `npx oxlint` | **0 errors / 35 warnings**（83 files，warning 全为既有） |
| e2e | `npx playwright test --workers=2` | **46 passed**（1.1m） |
| 生产构建 | `npx vite build` | ✓ built in 844ms（仅既有 >500kB chunk 提示） |

> e2e 并发说明见 §7.4。

---

## 5. 集成步骤建议（给集成 AI）

```text
1. 前置检查
   git worktree list --porcelain        # 确认 worktree ↔ branch 映射
   git -C D:/intelligence-agent-frontend status --short   # 期望：仅预存 untracked
   git -C D:/intelligence-agent-frontend log --oneline -1

2. 先回后正（§14.6，需用户批准）
   git -C D:/intelligence-agent-frontend fetch origin --prune
   git -C D:/intelligence-agent-frontend merge main
   # 预期无冲突（§1.3）；若冲突 → 立即停止，按 §14.7 逐文件分析后请求批准

3. 在 feat/frontend 上复跑门禁（§4 五条命令）

4. 合入 main（§14.4，需用户批准）
   git -C D:/intelligence-agent merge feat/frontend

5. main 上验证
   复跑门禁 + 在 D:\intelligence-agent 起完整项目做前后端联调

6. push（§14.4，需用户批准）
   git -C D:/intelligence-agent push origin main
```

**禁止**：`git pull`、在 dirty worktree 上 merge、`reset --hard`、`rebase`、`push --force`、未经批准删分支/worktree。

**本分支未 push**，集成 AI 可直接在本地 worktree 取用。

---

## 6. 需要回话的事项

| # | 事项 | 谁定 |
| --- | --- | --- |
| 1 | `context_providers: []` 契约语义（§7.1） | 用户 / 后端定契约，前端再跟 |
| 2 | 是否为 422 增机器可读 `code`（§3.2 建议） | 后端 |
| 3 | 冻结规格 `reasoning_effort` 误引勘误（§7.5） | 后端 |
| 4 | 是否单独批次修 §7.2 / §7.3 两项存量 bug | 用户 |

---

## 7. 已知未修项 / 风险

### 7.1 `context_providers: []` 无法表达「显式零个」— 契约 Gap

- **是否本批引入**：否，是契约表达能力问题，本批只是如实记录在 `api.ts` 注释。
- **影响**：用户无法通过 UI 选择「零个 Provider」（选择器初始态即 `[]`，而 `[]` 不发键 = 全部）。
- **处置**：**需契约决策**（前端改语义 vs 后端把 `[]` 等同缺省）。本批**故意不改**。

### 7.2 `isUnknownModelError` 死路径 — 自动刷新目录从不触发

- **是否本批引入**：否，**已存在于 `main`**（前缀来自 `5ecbdba`，判定/effect 来自 `5d47725`）。
- **根因**：`isUnknownModelError` 是精确相等判定，而 `useSession` catch 把文案包成 `提交失败：${msg}` / `续聊失败：${msg}`，前缀导致永远匹配不上 → `App.tsx` 的「422 → 刷新目录 + 清死选中值」effect 从不执行。
- **影响**：目录变更后需用户手动重选，非阻断。
- **处置**：本批**只报告不改**（§8 Scope Lock）。已在 `FRONTEND_REPLY_P1_FIXED.md` ③-2 告知后端。

### 7.3 `.hidden` 缺 CSS 规则 — 短列表搜索框不隐藏

- **是否本批引入**：否，**已存在于 `main`**（类名来自 `275d76b`，`main` 的 `index.css` 无 `.hidden` 规则）。
- **影响**：模型数 ≤5 时搜索框仍显示（设计意图是隐藏）。
- **处置**：已记 `docs/FRONTEND_DEFER.md` **F-DEFER-1**，本批**不修**。最小修复：`.model-picker-search-wrap.hidden { display: none; }`。

### 7.4 e2e 并发抖动（既有）

4 worker 全量并行时偶发超时（`expect.poll` 5s + 30s test timeout），曾观察到 `context-providers.spec.ts:79` 等与逻辑无关的用例失败；`--workers=2` 稳定 46/46，`continuation.spec.ts --repeat-each=3` 24/24。**判定为资源竞争型抖动，非确定性失败**。集成后复跑请用 `--workers=2` 作为判据。

### 7.5 冻结规格误引（非前端代码）

`reasoning_effort` 的落地引用原写 `(ADR-0018 D7)`（ADR-0018 是 Langfuse 观测），实际落地 commit 为 `79e2860`。前端注释已改；**同一误引仍存在于冻结规格**：

- `docs/spec/Observable_Agent_Workspace_SDD/03_RUNTIME_EVENT_CONTRACT.md:617`
- `08_DECISION_LOG.md:136`

规格冻结，前端不擅改，**建议后端侧勘误**。

---

## 8. 交接状态声明

- 本批在 `feat/frontend` 完成，**未 merge、未 push、未建 PR、未删分支/worktree**（符合 §13.2 / §14.4）。
- 工作树干净，仅存与本次任务无关的预存 untracked 文件（`docs/integration/FEAT_BACKEND_INTEGRATION_PROMPT.md`、`FRONTEND_CONTEXT_PROVIDERS_INTEGRATION_PROMPT.md`、`test-results/`）。
- 是否合并、合并顺序、push 时机，**等用户与集成 AI 决定**。
