# Fix Phase Scope — 修复任务报告（grill 定稿）

> **状态**：FINAL — 2026-09-09 经 grill-me 访谈逐项定稿（用户决议见 §3）→ to-spec 生成 PRD → to-tickets 拆票 → implement → code-review
>
> **依据**：`docs/integration/FULL_CODEBASE_AUDIT.md` / `REQUIREMENT_IMPLEMENTATION_AUDIT.md` / `BRANCH_TOPOLOGY_AUDIT.md` 三份审计报告
>
> **基线**：main `89631f1`（2026-09-09，前端 UX 修复 + 字典中文化已合入并推送 origin/main）
>
> **本稿只定范围与路径，不含实现。**

---

## 1. 修复候选项（按证据确凿度分层）

### Tier 1 — 证据确凿的 bug，无规格歧义

| ID | 问题 | 位置 | 修复 | 回归测试 |
|---|---|---|---|---|
| **P0-001** | `send_message` launched 分支调用 `AgentEvent.to_dict()`——方法不存在，首帧即 `AttributeError`，续聊 SSE 流 crash。前端续聊接线（`275d76b`）合入后从"潜伏"变"必现" | `src/agent_harness/web/app.py:1189` | 改用 `_event_to_sse_dict(ev, session_id)`，与 create/resume 端点同形（1 行） | 真实 server + ScriptedModel 驱动：创建会话跑到终态 → POST /messages 走 launched 分支 → 断言 SSE 帧完整且信封字段同形（现有 `test_web_multiturn.py` 只测了 404/422，launched 分支零覆盖——这正是 bug 逃逸原因） |
| **FE-04 / P2-001** | `useSession.ts` 两处 catch（submitTask ~633 / sendFollowUp ~674）缺 gen guard：请求在途时用户切换会话 → 迟到的失败无条件 `streamGenRef.current += 1` + 改写 mode → clobber 当前视图 | `web/src/hooks/useSession.ts` 两处 catch | catch 开头加 `if (streamGenRef.current !== gen) return;`（与 onEvent/onStreamEnd 既有守护模式一致，共 2 行） | Playwright e2e 竞态测试：延迟失败的 mock 路由 + 窗口内切换会话 + 断言视图不被清掉。需给 `fixtures.ts` 加 `eventsBySession` 支持（现 fixtures 所有 session 共用一个 events 数组，无法区分两个会话） |

P0-001 附注：`app.py:713/1147` 的 `e.to_dict()` 是 `SessionEvent`（有该方法），安全；唯一 bug 在 1189。

### Tier 1b — 顺路清理（是否纳入待定）

| ID | 问题 | 位置 | 修复 |
|---|---|---|---|
| **P2-003** | B2 双实现冲突遗留 dead code：`ContextProviderEntry` dataclass + `register_context_provider()`（ADR-0021 机制）assembly.py 从不使用 | `src/agent_harness/capability/wiring.py:36-71` | 删除 dead code（独立 commit，与 P0-001 分开） |

### Tier 2 — 前端功能 Gap（需要规格决策，不是简单 bug，建议拆独立 tickets）

| ID | 问题 | 阻塞点 |
|---|---|---|
| **P1-002** | `ApprovalCard` 组件存在但从未被任何组件 import/渲染；`projection.ts` 无 approval 事件分支 → 交互式审批在前端断路（#136/#37 前端部分） | **规格冲突待裁决**（见 §3-Q4）：冻结 spec 11 说 inline Approval Card；本地未跟踪 `docs/PRD_ENTERPRISE_MULTI_TURN_SESSION.md` 说 modal + `/approvals/{call_id}` |
| **P1-003** | 后端有 `/api/ws` WebSocket mux，前端零 WebSocket 消费代码 → WS 推送的审批请求/queue 事件无人接收 | 依赖 P1-002 的 UI 决策 |

### Tier 3 — 架构 deepening（独立 ticket，不在本轮 Fix 范围）

`_drive` god method（~706 行）、`web/app.py` god module（~1269 行）、SSE 序列化已随 P0-001 统一、wiring shim 去重、collect_result_fields leaky abstraction、sqlite 三 store 共文件。详见 `%TEMP%/architecture-review-audit.html` 与 `FULL_CODEBASE_AUDIT.md` §12。**每项独立 ticket，遵守 §8 Scope Lock，不在修 bug 时顺手做。**

---

## 2. 修复的分支路径（执行拓扑）

```
P0-001（后端） → D:\intelligence-agent-backend（feat/backend，已同步 main @3715bf2）修 + commit（§13.2 允许自行 commit）
                  集成时：验证门 → merge→main → push GitHub（届时单独请批）
FE-04（前端） → D:\intelligence-agent-frontend（feat/frontend，已快进 main @89631f1）修 + commit
                  集成时同上
```

事实核验（2026-09-09 更新）：
- feat/backend 已反向 merge origin/main（`3715bf2`，零冲突），修复基于最新 main 基线
- fix/frontend-ux-issues 的全部修复已在 main 中；前端 worktree 已切到 feat/frontend 并快进到 `89631f1`
- `useSession.ts` / `app.py` 修复区域与 main 最新内容一致，无并行改动冲突风险

---

## 3. grill 定稿决议（2026-09-09 用户逐项裁决）

**前置声明**：后端开发今后只在 `feat/backend` 分支做，前端只在 `feat/frontend` 分支做，双分支协作；每个分支干完活由集成 AI 合并到 main 并推送 GitHub。

- **Q1 范围 = B**：本轮修 Tier 1（P0-001 + FE-04）+ Tier 1b（P2-003 dead code，独立 commit）。Tier 2（审批 UI + WS）不进本轮，待 Q4 裁决后拆独立 tickets。
- **Q2 修复路径 = A**：直接在 feat/backend 修。执行时与 Q5 合并——先把分支同步到最新 main 再修（实际执行：feat/backend 反向 merge origin/main 零冲突 → `3715bf2`；见 §6 执行记录）。
- **Q3 测试形态 = A**：FE-04 修 + e2e 竞态回归测试（fixtures 扩展按 session 区分 + 延迟失败 mock），红→绿验证。
- **Q4 审批 UI 规格 = A**：spec 11 inline Approval Card 为权威；本地未跟踪 `PRD_ENTERPRISE_MULTI_TURN_SESSION.md` 视为草稿，不作为 Tier 2 拆票依据。Tier 2 未来拆票时以 spec 11 + 后端既有契约（`POST /api/sessions/{id}/approve` + `approval_id`）为准。
- **Q5 分支清理 = 部分批准**：**不能全批准。保留 `feat/backend` 与 `feat/frontend`，并把两者拉到最新**。分支工作流定稿：feature 分支干活 → 集成 AI 合并到 main → 推送 GitHub。可删清单（worktrees phase14/15/16/runtime、已验证合入的 18+1 个本地分支、stashes、远端分支）**待用户逐项批准后执行**，见 §4。
- **Q6 feat/backend 2 个文档 commit = B**：保留在 feat/backend 不动，不主动集成，随未来分支活动自然处置。

### Q5 执行记录（已执行部分）

| 动作 | 结果 |
|---|---|
| feat/backend 反向 merge origin/main | `3715bf2`，零冲突（merge-tree 预检 0 冲突），现含全部 main 内容 + 原有 2 个文档 commit |
| feat/frontend 快进 | worktree 已从 `fix/frontend-ux-issues` 切换到 `feat/frontend`，`--ff-only` 快进到 `89631f1`（feat/frontend 是 main 祖先，纯快进，无 reset） |
| `fix/frontend-ux-issues` 分支 | 内容已全进 main，**分支删除待用户批准**（Q5 遗留决策项） |

---

## 4. 分支清理清单（2026-09-09 复核后的决策表）

### 4.1 可安全删除（内容已确认在 main）

**Worktrees**（全部 clean、分支已合入、stale）：

| Worktree | Branch | Behind main | 备注 |
|---|---|---:|---|
| `D:\intelligence-agent-phase14` | feat/phase14 | 178 | clean |
| `D:\intelligence-agent-phase15` | feat/phase15 | 137 | clean |
| `D:\intelligence-agent-phase16` | feat/phase16 | 98 | clean |
| `D:\intelligence-agent-runtime` | feat/runtime-context-providers-422 | 9 | clean，仅 2 个 untracked 协调 docs |

**本地分支**（全部 `merge-base --is-ancestor` = YES，ahead=0）：

```
feat/backend-c  feat/backend-d  feat/frontend  feat/frontend-B
feat/frontend-a11y-rescue  feat/frontend-context-providers  feat/frontend-d
feat/frontend-e  feat/frontend-f1-fixes  feat/multiturn
feat/phase14  feat/phase15  feat/phase16
feat/runtime-agent-profile  feat/runtime-context-providers
feat/runtime-context-providers-422  feat/runtime-reasoning-effort
fix/identity-tests
```

**特例（已做语义验证）**：
- `feat/frontend-c`：ahead=2 但 `git cherry main feat/frontend-c` 两个 patch 全部 `-`（已经 a11y-rescue cherry-pick 进 main；`app.css` reduced-motion 5 处 + `composer-control-row-benchmark.md` 均在 main）→ **可安全删除**
- `EricKingWhy/pilotfish`：MERGED（behind 368）→ 大概率可删，但属于用户自建分支，**需用户点名确认**

**删除顺序约束**：分支被 worktree checkout 时不可删 → 先删 worktree 再删对应分支（phase14/15/16、runtime 四组）。

### 4.2 不确定 / 需要用户点名决策

| 项 | 状态 | 决议（2026-09-09 grill） |
|---|---|---|
| `fix/frontend-ux-issues` 分支 | worktree 已切到 `feat/frontend`；本分支内容已全合入 main（behind 3，纯 docs 差距） | 分支本体删除**待用户单独批准**（列入待批清单） |
| `feat/backend` 分支 | 后端开发主力分支（用户指定保留），已同步到最新 main（`3715bf2`） | **保留**，ahead 2 文档 commit 按 Q6=B 不主动集成 |
| `feat/frontend` 分支 | 前端开发主力分支（用户指定保留），已快进到最新 main | **保留** |
| 5 个 stash | 内容均已被正式 commit 取代（高置信）：@0/@3 为空或孤儿搬运；@1/@2/@4 对应 T-IDENTITY / multiturn / Phase4 工作均已合入 | drop 需批准；drop 前对 @{4}（290 行 runtime/storage 改动）做一次内容 diff 终验 |
| 远端分支（origin/feat/backend-c、origin/feat/frontend、origin/feat/frontend-B、origin/feat/backend） | 本地对应分支已合入或为主力分支 | 删除需单独批准；建议本地清理验证一段时间后再删 |
| untracked 文档（main worktree 8 个 + backend worktree 5 个 + frontend worktree 2 个） | PRD / RESEARCH / TICKET / 交接单等过程文档 | 按 §13.1.5 公共资产应 commit 进版本控制；是否 commit 需统一口径（待批） |
| `evaluation/smoke_sessions/`、`test-results/` | 运行时产物，untracked | 建议 gitignore，不 commit（待批） |

### 4.2b 待用户批准的删除清单（本轮未执行，逐项等批）

1. **4 个 worktree**：`D:\intelligence-agent-phase14` / `-phase15` / `-phase16` / `-runtime`（全部 clean、分支已合入 main）
2. **19 个本地分支**：`feat/backend-c`、`feat/backend-d`、`feat/frontend`（旧指针已被快进覆盖，无需删）、`feat/frontend-B`、`feat/frontend-a11y-rescue`、`feat/frontend-c`（git cherry 验证等价）、`feat/frontend-context-providers`、`feat/frontend-d`、`feat/frontend-e`、`feat/frontend-f1-fixes`、`feat/multiturn`、`feat/phase14`、`feat/phase15`、`feat/phase16`、`feat/runtime-agent-profile`、`feat/runtime-context-providers`、`feat/runtime-context-providers-422`、`feat/runtime-reasoning-effort`、`fix/identity-tests`、`fix/frontend-ux-issues`
3. **`EricKingWhy/pilotfish`**（已合入 behind 368；用户未点名，默认保留待问）
4. **5 个 stash**（@{4} 终验后 drop）
5. **远端 3 个 stale 分支**（建议延后）

### 4.3 绝对不能删

`D:\intelligence-agent`（main）、`D:\intelligence-agent-backend`（feat/backend，后端主力）、`D:\intelligence-agent-frontend` 的 worktree 本体、所有 stash（drop 前逐个确认）。

---

## 5. 验收标准草案（每张 ticket 的 Gate）

- P0-001：新回归测试红→绿；`pytest tests/web/` 全绿；全量 pytest 不回归；ruff clean；`git diff --check` clean
- FE-04：新 e2e 竞态测试红→绿；vitest 372+ 全绿；tsc / oxlint / build 全绿
- P2-003：删除后全量 pytest 不回归（确认无隐藏引用）；ruff clean
- 集成进 main 时：§14.10 完整验证门 + 用户逐项批准 merge/push
