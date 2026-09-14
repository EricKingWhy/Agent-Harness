# 集成提示词：MEM-5 #160 —— 前端记忆管理 UI（跨端票的前端半）

> **给集成 AI**：本文件是这一批的**唯一入口**，§0 是可执行摘要。
> 本批**不推送远程**（AGENTS.md §13.2/§14.4）——push 由你执行。
> 本批是**跨端票的前端半**：#160 **不关单**，用 comment 记录（见 §5）。

---

## 0. 可执行摘要

| 项 | 值 |
| --- | --- |
| Worktree | `D:\intelligence-agent-frontend` |
| 分支 | `feat/frontend` |
| 本批 commit | 功能 `5eb4fed` → 文档回填 `decc7be` → **批次审查修复 `45227dc`（当前 HEAD）**；fixed point = `637bc89` |
| 后端依赖 | **已就绪且已关单**：MEM-4 #159（`feat/backend`，`GET /api/memories` + `DELETE /api/memories/{id}`）。本批**没有**任何后端改动——无需等后端 |
| 集成动作 | ① 把 `feat/frontend` 合入本地 `main`（§14.9：一次只合一条分支；后端已先行完成）② 真机跑一遍 §3 的 5 步 ③ `main` 上跑 §4 门禁 ④ 关 #160（comment **已发**在 issue 上，见 §5）⑤ push |
| 最终全量 review | v2 §1.3 的处置见 `docs/SDD_TICKET_TRACKER.md`「批次台账 → 最终全量 review」：本分支相对 `main` 落后且 `main` 侧全是后端文件，唯一未审增量 `637bc89..HEAD` 已由 B-1 覆盖——**是否再跑 `main...HEAD` 留给集成 AI 决策** |
| 冲突预判 | 本批只动 `web/**` + 两个 docs 文件；与后端 `src/**`/`tests/**` 无交集。**唯一需注意**：`docs/SDD_WORKFLOW_PROTOCOL.md` 本批把它同步成了 v2（与 `feat/backend` 侧**逐字节相同**）——若 `feat/backend` 已合入 `main`，该文件在第二次 merge 时是 identical-change，**不构成冲突**；`docs/SDD_TICKET_TRACKER.md` 两侧都追加了各自章节，**可能冲突**（按 §14.7 分析，两边内容可同时保留：后端记后端批次、前端记前端批次） |
| 关单 | **#160 已关**（reason=completed，2026-09-12 用户指示「完成了就关闭」；AC 证据与核实 comment 已发在 issue 上，见 §5）。你只剩 §0 的 ①②③⑤ |

---

## 1. 这批做了什么

用户诉求（issue #160）：用户能**看见**系统记住了什么，并能把它**删掉**。
只有 API 的"用户入口"等于没有——看不见就无从判断该删哪条。

| 层 | 交付 | 文件 |
| --- | --- | --- |
| 契约 | `MemoryScope` / `MemorySummary` / `MemoryDeleted`（逐字段对齐后端 `web/memory.py`） | `web/src/types.ts` |
| API | `listMemories(limit, offset)` / `deleteMemory(id)` / `MemoryError` / `isMemoryDisabled` / `describeMemoryError` / 窄化 `parseMemory` | `web/src/lib/api.ts` |
| 纯逻辑 | `scopeLabel` / `formatMemoryTime`（解析失败**原样返回**，不伪造）/ `hasMoreAfter` / `withoutIds` | `web/src/lib/memory.ts` |
| 数据 | `useMemories`：打开即拉取（不缓存旧列表）/ offset 分页 + 按 id 去重追加 / 乐观删除 + **两个结局都重拉权威** / 503 与真故障分流 | `web/src/hooks/useMemories.ts` |
| UI | `MemoryPanel`：列表（content + scope chip + 创建时间 + 长正文展开）+ 行内二次确认 + 降级/空/错误/分页四态 | `web/src/components/MemoryPanel.tsx` |
| 入口 | 顶栏 Brain 按钮（`aria-label="记忆管理"`）+ 命令面板「管理记忆」 | `web/src/components/TopBar.tsx` / `web/src/App.tsx` |
| 样式 | 浮层材质与项目浮层共用选择器；记忆专属规则纯新增 | `web/src/styles/app.css` |

### 1.1 三条**故意的**设计选择（评审时请重点看这里）

1. **乐观删除 + 无条件对账**（AC3 的字面要求是"立即反映 + 失败回滚"，不变量 #22 要求"不维护第二套真相"）。
   实现：点确认 → 先把该行藏起来（`hiddenIds`）→ `DELETE` → **无论成功失败都重拉权威列表**：
   - 成功 → 该行由后端的缺席消失（本地集合只是让它在往返期间先不可见）；
   - 失败 → 重拉让该行回来（这就是 AC3 说的"回滚"）+ 错误留在**那一行**的确认条里。
   所以列表的**静止态**永远等于最近一次后端响应。e2e 用"关掉面板再打开 / 整页刷新"证明它不是本地隐藏。
2. **503 是配置状态，不是故障**：`isMemoryDisabled` 把它分流到独立降级态（「记忆未启用」+ 后端原文 +
   `CAPABILITIES` 指引 + **不给重试按钮**），与「读取失败（错误条 + 重试）」「真的没有（空态）」三分。
   不变量 #21 的落地。
3. **`created_at` 零解析**：`types.ts` 保持后端 ISO 原值（`<time datetime>` 原样透传），
   只在展示层 `formatMemoryTime` 本地化；解析失败**原样返回字符串**（显示 `Invalid Date` 或补当前时间
   都是在"记忆是何时记的"上撒谎）。

### 1.2 e2e 逮到并修掉的一个真 product bug（AC4）

列表读取失败且当前 0 行时，分支链漏了 `loadError === null` → 面板**同时**显示
「还没有记忆」与错误条（= 把"读不到"伪装成"没有"，AC4 明令禁止）。
已修为互斥三态；`e2e/s-memories.spec.ts` 的 500 用例（`.memory-empty` count 必须 0）
就是钉它的锁——**首版两视口都红**，不是事后补的测试。

---

## 2. 契约同步点（与后端逐字段）

| 前端 | 后端（`src/agent_harness/web/memory.py`） |
| --- | --- |
| `MemorySummary {id, content, scope, metadata, created_at}` | `MemorySummary`（`public_metadata` 已剥 provider 内部载荷） |
| `MemoryDeleted {id, deleted}` | `MemoryDeleted` |
| `GET /api/memories?limit=50&offset=0` → 数组（按 `created_at` 倒序） | `list_memories`（`limit` 1..200 由后端夹） |
| `DELETE /api/memories/{id}` → 200 `{id, deleted:true}` / **404** 不存在 / **403** 不属于当前入口（含 SESSION 行）/ **503** 未装配 | `forget_memory`（含 `record_forget` 审计：`memory forget via api: forgotten`） |
| 编译期锁：`api.test.ts` 的 `CANONICAL_MEMORY: MemorySummary` 类型注解 fixture（ARCH-4b 套路）——**只锁前端侧漂移**（`types.ts` 加必填字段 → fixture 缺键 → `tsc -b` 红）；它**锁不住后端加字段** | 后端侧权威锁（断言**值**，抓"键在但值是 null"）：`tests/web/test_memory_api.py` |

**错误 detail 的真实原文**（e2e mock 与单测都用它们，不是编的）：
403 `Memory belongs to a different namespace`（`sqlite_record_store.py:195` 的 `PermissionError` →
`domain_errors.py::memory_http_error` 用 `str(exc)` 直通）、404 `记忆不存在：<id>`（`memory/errors.py`）。

**实测核对的 503 文案**（e2e mock 里那句不是编的）：
`memory capability 未启用：请在 CAPABILITIES 中配置 memory。`

---

## 3. 真机验收（已跑过一遍，集成后请复跑 —— 5 步）

前置：后端 `D:\intelligence-agent-backend`（真 `.env`，`CAPABILITIES` 含 `memory`）起 uvicorn :8000；
前端 `D:\intelligence-agent-frontend\web` 起 `npx vite --port 5173`。

1. **列表**：点顶栏 Brain 图标 → 面板列出后端 `GET /api/memories` 的内容
   （若库里为空，先跑 `.scratch/seed_real_memories.py` 种 3 条；脚本走生产装配，见 §6）。
2. **二次确认**：点某行「删除」→ 行内出现「这是硬删除，**删除不可恢复**——没有回收站…」+
   取消 / 确认删除；点取消 → 行还在（**不发** DELETE）。
3. **删除成功 + 后端权威**：再点删除 → 确认 → 行消失；
   `curl http://127.0.0.1:8000/api/memories` 复查该条不在；后端日志出现 `memory forget via api: forgotten`；
   **整页刷新（F5）后重开面板** → 该条依然不在。
4. **失败回滚**：杀掉后端 → 点确认删除 → 该行**回到列表** + 该行确认条出现错误 + 面板错误条 + 重试；
   重启后端 → 点「重试」→ 列表恢复一致。
5. **降级契约**（可选，需另起实例）：
   `CAPABILITIES={} WORKSPACE_DIR=<tmp> python -m uvicorn agent_harness.web.app:create_prod_app --port 8001`
   → `GET /api/memories` 回 **503** + 上述原文。前端 503 渲染由 e2e 锁定（`memoryDisabled` 分支）。

**验收后请还原环境**：种子记忆是**假事实**，验证完请经界面删掉（否则真模型会把它当真的召回）；
停掉临时 uvicorn（残留进程会占 `.agent/workspace/.instance.lock`，那是已知会把
`test_web_lifespan_flushes_on_shutdown` 打红的坑）。

---

## 4. 门禁（本批实跑结果 + 合并后复跑命令）

```bash
cd web && npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build
```

| 门禁 | 本批结果 |
| --- | --- |
| `npx tsc -b` | 0 error |
| `npx vitest run` | **587 passed**（31 文件；本批 +26：api 11 + memory 10 + timeout 4 + 既有基线） |
| `npx oxlint` | **0 error**（38 warnings：37 既有 + 1 条本批与既有同类的 `set-state-in-effect`） |
| `npx playwright test --workers=2` | **162 passed**（本批 +18 = 9 用例 × 2 视口） |
| `npx vite build` | OK（仅既有 chunk-size 提示） |

---

## 5. #160 的 comment 与关单

**已关单**（2026-09-12，用户指示「完成了就关闭」；两端齐备后 §14.12 的「只完成一端不关单」前提不再成立）。
两条 comment 已发在 issue 上：① 完整 AC 逐条证据；② 关单核实（分支/commit/门禁/真机/移交项）。
下面保留**当时的**草稿作历史记录——集成 AI 无需再操作关单：

```text
前端半已在 feat/frontend 完成（commit `5eb4fed` 功能 + `45227dc` 批次审查修复，fixed point `637bc89`），未 push。后端半 MEM-4 #159 已关单。

AC 逐条：
1. 列表视图（content + scope + 创建时间 + 分页"加载更多"）：✅ MemoryPanel + useMemories（offset 分页，
   后端 limit/offset 切片；e2e 55 条 fixture 验证首屏 50 → 加载更多 offset=50 → "已全部加载"）
2. 单条删除必须二次确认且写明"删除不可恢复"：✅ 行内确认条原文含该字样（真机点击复核）
3. 删除后立即反映且与后端权威一致（不得只做本地隐藏）+ 失败回滚：✅ 乐观删除 + 两个结局都重拉权威；
   e2e 用"关掉再打开"、真机用"整页刷新"证明；失败路径真机用杀后端复现（行回来 + 报错）
4. 空态与降级：✅ 三分（503"记忆未启用"不给重试 / 读取失败错误条+重试 / 真空态"还没有记忆"）；
   真机核对 503 原文与 mock 逐字一致；e2e 锁定"500 时不得显示空态"
5. 契约同步：✅ types.ts + api.test.ts 的 CANONICAL_MEMORY 类型注解 fixture（ARCH-4b）
6. e2e 回归锁（--workers=2）：✅ 9 用例 × 2 视口 = 18 例（列表+翻页/展开/二次确认+后端权威/403 失败回滚/
   404 已别处删除仍需报错/503 降级/真空态/500 重试/命令面板入口）
7. 门禁：✅ tsc 0 · vitest 587 · oxlint 0 error（38w）· playwright 162 · vite build OK

剩余项：合入 main（由集成 AI 执行，见 docs/integration/FRONTEND_MEM5_INTEGRATION_PROMPT.md）。
按 §14.12 本票不自行关闭。
```

---

## 6. 残留 / 未决（只登记，不顺手做）

| 项 | 说明 |
| --- | --- |
| 记忆**编辑** UI | 票面非目标；后端 MEM-4 也没有 update 入口 |
| 批量清空 / 回收站 / 恢复 | 票面非目标（用户已选硬删） |
| 冲突可视化 | 票面非目标（LLM 决策只体现在最终条目上） |
| 记忆搜索 | 本票只做分页列表；"看得见 + 删得掉"是 AC 的全部 |
| 真机 403 路径 | HTTP 入口只列 USER 行，SESSION scope 记忆不可达 → 由 e2e 的 `memoryDeniedIds` 拦截口覆盖（伪造的是真后端会回的那句话） |
| 种子脚本 | `.scratch/seed_real_memories.py`（后端 worktree，`.scratch/` 不入库）；种的是**假事实**，验收后须删 |
| 实测环境观察 | 种子写入时 Zilliz/embedding 不健康 → 3 条都 `degraded=consolidation_failed: VectorStoreError`（按 #158 设计降级为无条件 insert，记录行照落）——**外部依赖问题，非本票缺陷**，记录在案 |
| 协议文件同步 | 本批把 `docs/SDD_WORKFLOW_PROTOCOL.md` 同步为 v2（与 feat/backend 逐字节相同）；其 §4「剩余 Ticket 清单」仍是旧内容（FE-T7/T8/T9，早已 done）——不在本批范围 |
| `docs/PHASE_STATUS.md` | 按前端协议（§16.6）本 worktree 只记 `docs/SDD_TICKET_TRACKER.md`，**未**写 `PHASE_STATUS.md`——该文件既有条目均为「合入 main 后回填」，请集成 AI 在 merge 后按 tracker 的第十二轮小节追加（这是既有的、已记录的协议偏离） |

---

## 7. 批次审查（B-1，v2 §1.2）—— findings 与修复

两轴独立 subagent 审 `git diff 637bc89...<本批 HEAD>`。**Spec 轴 6 条（3 条真问题）+
Standards 轴 7 条**。按 v2 §1.2 全部"一眼能定位" → 直接最小修复 + 跑测试，不重跑全量 review。

| finding | 为什么是真问题 | 修复 |
| --- | --- | --- |
| 重拉的 `limit` 越过后端硬上界 200（加载 >4 页后送 `limit=250` → **422**） | 删除失败的回滚重拉与"重试"**永久失败**，列表回不到权威状态（AC3 破） | `MEMORY_MAX_LIMIT=200` + `refetchLimit(loaded)`（+3 单测）。已登记代价：>200 条时重拉只带回前 200 条，需再点"加载更多" |
| 404（这条已被别处删掉）的失败被界面**吞掉** | 行内错误条按行 id 渲染，而重拉后那行不在 → 失败无人呈现（AC3「失败要报错」破） | 面板级错误条（行在 → 行内；行不在 → 面板级）+ e2e `memoryVanishedIds` 接缝 + 1 用例 ×2 视口 |
| e2e 的 403 detail 是编的中文，真后端是英文原句 | AC3 的失败用例变成"前端与我的假后端一致"的自我实现（#155 轮同一类坑） | mock / e2e / 单测统一改成真后端原文（见 §2） |
| DELETE 挂死无超时：行已隐藏、按钮全 disabled | 用户看到"点了删除就消失"，且界面再也点不动（本仓库最忌讳的"点了没反应"） | `lib/timeout.ts`（App 的 fork 超时实现迁入共用）+ `DELETE_TIMEOUT_MS=30s`，超时走与失败相同的对账路径；+4 单测 |
| ARCH-4b 的说法过强 | fixture 只锁前端类型 | 本文档 §2 已改写 |
| AC4 的"检索不可用"在后端契约里没有独立状态 | 列表读权威记录；检索故障表现为 5xx，不是 503 | 只登记不改：503 = 未装配（降级态）；5xx = 读取失败（错误条 + 重试 = 事实上的"暂不可用"） |
| `MemoriesState.rows` 无消费方 | Speculative Generality | 去掉导出（只留 `visible`） |
| `remove` 未复用 `useProjects.after()` 且未说明 | 判断项 | 加注释说明语义不同，**不**硬套 |
| `.project-dialog-*` 类名复用（Mysterious Name） | 判断项 | **不改**：连带 ProjectDialogs + app.css + e2e 选择器，属跨模块审美重构（§8） |
| `describeMemoryError` 与 `describeProjectError` 同形 | 判断项 | **不改**：注释已声明刻意分开 |
| v2 §1.1 与 `AGENTS.md` §16.1（每票 review）矛盾 | 文档不一致 | **不改 AGENTS.md**（跨 worktree 共用文件，改了徒增 §16 已知冲突面）；以用户 2026-09-12 指令为最高优先级，v2 覆盖 §16.1 |

**修复后**：tsc ✅ · vitest **587** · oxlint 0 error（38w）· playwright **162** · vite build ✅。
**修复后真机复验**：种 3 条 → 经界面真删 1 条（走新的超时包装）→ 后端剩 2 条 → 再删 2 条 →
后端 0 条 + 面板「还没有记忆」；dev server 停、真记忆库清空。

**新增文件**：`web/src/lib/timeout.ts` + `web/src/lib/timeout.test.ts`（可移植小工具，与
`App.tsx` 的 fork 超时共用——合并时请留意这份 diff 也动了 `App.tsx` 顶部那 10 行）。
