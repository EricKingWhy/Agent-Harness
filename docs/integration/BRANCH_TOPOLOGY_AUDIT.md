# Branch Topology Audit

> **审计性质**：只读法证审计 / 仓库完整性 + 分支拓扑 + 丢失工作排查
>
> **基线 SHA**：`83056c884b69aacf9563399cb486d390a1d32e18`
>
> **审计时间**：2026-09-08 ~ 2026-09-09
>
> **执行者**：ZCode（Secondary Agent）

---

## 1. Audit Baseline

| 项目 | 值 |
|---|---|
| Local main HEAD | `83056c8` |
| origin/main tracking ref | `83056c8` |
| Actual remote main (ls-remote) | `83056c8` |
| Current branch | `main` |
| Dirty tracked files | 2 (`contract.py`, `app.py`) |
| Untracked files | 10+ (docs, evaluation, test-results) |
| Stash count | 5 |
| Worktree count | 7 |
| Local branch count | 23 |

**Local ↔ Remote 一致性**：`local main = origin/main = ls-remote origin/main` → **一致，无 divergence**。

---

## 2. Worktree 全量盘点

| Worktree | Branch | HEAD | Dirty | Untracked | Stash | Ahead main | Behind main | Last commit | Classification |
|---|---|---|---|---|---|---:|---:|---|---|
| `D:\intelligence-agent` | `main` | `83056c8` | Yes (2 files) | Yes (10+) | 5 | 0 | 0 | 2026-09-08 21:05 | ACTIVE (dirty) |
| `D:\intelligence-agent-backend` | `feat/backend` | `69e11ea` | No | Yes (5 docs) | 5 | 2 | 1 | 2026-09-08 22:11 | ACTIVE (untracked docs) |
| `D:\intelligence-agent-frontend` | `fix/frontend-ux-issues` | `83056c8` | Yes (7 files) | Yes (3 docs) | 5 | 0 | 0 | 2026-09-08 21:46 | DIRTY_REQUIRES_REVIEW |
| `D:\intelligence-agent-phase14` | `feat/phase14` | `a751a7b` | No | No | 5 | 0 | 173 | 2026-09-07 | MERGED_BUT_STALE |
| `D:\intelligence-agent-phase15` | `feat/phase15` | `0abd0b8` | No | No | 5 | 0 | 132 | 2026-09-07 | MERGED_BUT_STALE |
| `D:\intelligence-agent-phase16` | `feat/phase16` | `6a99b52` | No | No | 5 | 0 | 93 | 2026-09-07 | MERGED_BUT_STALE |
| `D:\intelligence-agent-runtime` | `feat/runtime-context-providers-422` | `b3a6056` | No | Yes (2 docs) | 5 | 0 | 4 | 2026-09-08 20:14 | MERGED_BUT_STALE |

### 关键发现

1. **`D:\intelligence-agent` (main) dirty**：2 个 tracked 文件有未提交修改：
   - `src/agent_harness/tooling/contract.py` — PermissionPolicy 描述文本从英文改为中文
   - `src/agent_harness/web/app.py` — REASONING_EFFORT_DESCRIPTIONS / AGENT_PROFILE_DESCRIPTIONS / CONTEXT_PROVIDER_DESCRIPTIONS 从英文改为中文

2. **`D:\intelligence-agent-frontend` dirty**：7 个文件有未提交修改（`fixtures.ts`, `App.tsx`, `ContextProviderPicker.tsx`, `ControlPicker.tsx`, `ModelPicker.tsx`, `useSession.ts`, `api.ts`）。这是前端 UX 修复的活跃工作区。

3. **Phase 14/15/16 worktrees stale**：这三个 worktree 的分支都已合入 main，worktree 本身已不再活跃使用。可以安全删除 worktree（不删分支）。

4. **Runtime worktree**：`feat/runtime-context-providers-422` 已合入 main 但 behind 4 commits。有 2 个 untracked docs。

---

## 3. Branch Integration Truth

### 已集成分支（is-ancestor = YES）

| Branch | Merge-base | Behind main | Status |
|---|---|---:|---|
| `feat/frontend` | `30a46e9` | 151 | MERGED |
| `feat/multiturn` | `dcc255e` | 15 | MERGED |
| `feat/phase14` | `a751a7b` | 173 | MERGED |
| `feat/phase15` | `0abd0b8` | 132 | MERGED |
| `feat/phase16` | `6a99b52` | 93 | MERGED |
| `feat/runtime-context-providers-422` | `b3a6056` | 4 | MERGED |
| `fix/frontend-ux-issues` | `83056c8` | 0 | = main HEAD |
| `fix/identity-tests` | `b198703` | — | MERGED |

### 未集成分支（ahead > 0）

| Branch | Ahead | Behind | Commit | Description |
|---|---:|---:|---|---|
| `feat/backend` | 2 | 1 | `69e11ea` | 架构扫描交接文档（2 commits：原版 + 重写版） |

**`feat/backend` 分析**：
- 2 个 ahead commits 都是纯文档（`docs/integration/CODEX_IMPROVE_CODEBASE_HANDOFF.md`）
- 无代码变更
- 这些文档是给 Codex 的架构扫描交接单，不是需要集成的功能代码

---

## 4. Stash 审计

| Stash | Branch context | Files | Assessment |
|---|---|---|---|
| `stash@{0}` | On main | (empty - pre-multiturn-merge orphan move) | 清理用 stash，可丢弃 |
| `stash@{1}` | On fix/identity-tests | `web/__init__.py`, `web/app.py` (29+/8-) | T-IDENTITY 工作残留，已合入 main |
| `stash@{2}` | WIP on feat/multiturn | 12 files (248+/17-) | Multiturn WIP，已通过正式 commit 合入 |
| `stash@{3}` | On feat/multiturn | (empty) | 空 stash |
| `stash@{4}` | On feat/backend | `agent/runtime.py`, `storage/__init__.py`, `storage/sqlite.py` (290+/3-) | Backend 保护性 stash，内容已通过正式 commit 合入 |

**结论**：所有 stash 内容都已被正式 commit 取代。理论上可以安全 `drop` 全部，但需用户确认。

---

## 5. Orphan / Dangling Commit 审计

### `git fsck --full --no-reflogs --unreachable` 结果

发现 **102 个 unreachable objects**，包括：

1. **Stash-related commits/trees**：对应 stash@{0}~{4} 的内部对象
2. **Amended commit orphans**：`0efab3e` 被 amend 后旧 SHA 变 unreachable
3. **Cherry-pick/rebase orphans**：历史 rebase 操作遗留的 dangling commits

### 关键 orphan commits

| SHA | Type | Content | Recovery candidate? |
|---|---|---|---|
| `51c0f833` | commit | `f463e5c refactor(tooling): centralize pending operation creation (#31)` | NO — 已被后续重构取代 |
| `9581e454` | commit | `index on feat/backend: f4f0544...` | NO — stash 索引 commit |
| `1c42e16c` | commit | `WIP on feat/multiturn: 63a437b...` | NO — stash WIP commit |
| `c642ebb2` | commit | `index on feat/frontend-a11y-rescue...` | NO — stash 索引 commit |
| `34035272` | commit | `index on fix/identity-tests: 4225af4...` | NO — stash 索引 commit |

**结论**：没有发现有价值的丢失工作。所有 unreachable commits 要么是 stash 内部对象，要么是被 amend/rebase 取代的旧版本。

---

## 6. High-Risk Merge Analysis

### 最近 merge commits

| Merge SHA | Type | Risk |
|---|---|---|
| `8ef88bc` | Merge origin/main into feat/backend | LOW — fast-forward merge |
| `b3a6056` | merge(main) → feat/runtime-context-providers-422 | MEDIUM — §14.6 先回后正第一步 |
| `c4e4731` | merge(backend) → main | HIGH — B2 双实现语义冲突 |
| `d7750fa` | merge(multiturn) → main | HIGH — 5 文件 15 conflict hunks |
| `78ee0f6` | merge(web) → ContextProviderPicker | LOW — 干净分叉 |
| `20116b1` | merge(frontend-e) → F1 Phase 2b | LOW — 干净分叉 |

### B2 双实现冲突（ADR-0020b vs ADR-0021）

**事件**：两个并行 AI 会话各自独立实现了 `context_providers` 运行时消费。
- Main 走 ADR-0020b（provider 类属性 `name: str` + `_select_context_providers()` 纯函数）
- feat/backend 走 ADR-0021（`ContextProviderEntry` dataclass + `register_context_provider()`）

**解决方式**：混合方案——保留 main 的 ADR-0020b 机制，加入 feat/backend 的 handler 层 422 校验。

**现状验证**：
- `assembly.py` 使用 `_select_context_providers(wiring.context_providers, context_providers)` ✓
- `wiring.py` 中保留了 ADR-0021 的 `ContextProviderEntry` dataclass + `register_context_provider()` — **dead code**
- `web/app.py` 的 `_validate_context_providers` 使用 `getattr(p, "name", None)` 动态投影 ✓

---

## 7. Retirement Candidates

### 可建议退休的 worktree

| Worktree | Reason | Recommendation |
|---|---|---|
| `D:\intelligence-agent-phase14` | 分支已合入 main，behind 173 commits | 删除 worktree（保留分支） |
| `D:\intelligence-agent-phase15` | 分支已合入 main，behind 132 commits | 删除 worktree（保留分支） |
| `D:\intelligence-agent-phase16` | 分支已合入 main，behind 93 commits | 删除 worktree（保留分支） |
| `D:\intelligence-agent-runtime` | 分支已合入 main，behind 4 commits | 删除 worktree（保留分支） |

### 可建议退休的分支

| Branch | Reason | Recommendation |
|---|---|---|
| `feat/phase14` | 已合入 main，behind 173 | 删除分支 |
| `feat/phase15` | 已合入 main，behind 132 | 删除分支 |
| `feat/phase16` | 已合入 main，behind 93 | 删除分支 |
| `feat/runtime-context-providers-422` | 已合入 main，behind 4 | 删除分支 |
| `feat/multiturn` | 已合入 main，behind 15 | 删除分支 |
| `feat/frontend` | 已合入 main，behind 151 | 删除分支 |
| `fix/identity-tests` | 已合入 main | 删除分支 |
| `EricKingWhy/pilotfish` | 旧 pilotfish 分支 | 用户确认后删除 |

### 绝对不能删的

| Item | Reason |
|---|---|
| `D:\intelligence-agent` (main) | 最终集成 worktree |
| `D:\intelligence-agent-backend` (feat/backend) | 活跃后端开发 worktree |
| `D:\intelligence-agent-frontend` (fix/frontend-ux-issues) | 活跃前端开发 worktree |
| All stashes | 需用户确认后才能 drop |

---

## 8. Dirty / Untracked 工作盘点

### `D:\intelligence-agent` (main) — P0 优先

**Dirty tracked files**（未提交修改）：

1. `src/agent_harness/tooling/contract.py`：
   - `PermissionPolicy` 的 `PERMISSION_MODE_DESCRIPTIONS` 从英文改为中文
   - display_name: "Read-only" → "只读", "Workspace write" → "工作区写入", "Danger full access" → "完全访问"

2. `src/agent_harness/web/app.py`：
   - `REASONING_EFFORT_DESCRIPTIONS` 从英文改为中文
   - `AGENT_PROFILE_DESCRIPTIONS` 从英文改为中文
   - `CONTEXT_PROVIDER_DESCRIPTIONS` 从英文改为中文

**评估**：这些是 UI 显示文案的本地化修改。修改本身合理（前端展示中文更友好），但处于未提交状态。需要决定：commit 还是 discard。

**Untracked files**：

1. `docs/INTEGRATION_PROMPT_PY312_READTEXT.md` — PY312 兼容性修复的集成提示词
2. `docs/PRD_ENTERPRISE_MULTI_TURN_SESSION.md` — 企业多轮会话 PRD
3. `docs/RESEARCH_DEEPSEEK_HARNESS_WEB.md` — DeepSeek Harness Web 研究
4. `docs/RESEARCH_OHMY_PI_DSH_COMPACTION.md` — oh-my-pi DSH Compaction 研究
5. `docs/RESEARCH_PI_DSH_MEMORY.md` — Pi DSH Memory 研究
6. `docs/RESEARCH_PI_SESSION_ARCHITECTURE.md` — Pi Session Architecture 研究
7. `docs/integration/TICKET_B2_F3_CONTEXT_PROVIDERS.md` — B2 F3 Context Providers ticket
8. `docs/integration/TICKET_B2_MIXIN_HANDLER_422.md` — B2 MixIn Handler 422 ticket
9. `evaluation/smoke_sessions/` — 冒烟测试会话数据
10. `test-results/` — 测试结果

### `D:\intelligence-agent-frontend` — P1 优先

**Dirty tracked files**（7 个）：
- `web/e2e/fixtures.ts`
- `web/src/App.tsx`
- `web/src/components/ContextProviderPicker.tsx`
- `web/src/components/ControlPicker.tsx`
- `web/src/components/ModelPicker.tsx`
- `web/src/hooks/useSession.ts`
- `web/src/lib/api.ts`

**评估**：这是前端 UX 修复的活跃工作。`useSession.ts` 和 `api.ts` 的修改可能包含 FE-04 race condition 的修复。需要确认这些修改是否完整、是否需要集成。

---

## 9. Semantic Overwrite 检查

### 检查方法

搜索历史中的 same Issue / same ticket / same function / same endpoint / same event / same DTO。

### 发现

1. **B2 context_providers 双实现**（已知）：
   - ADR-0020b（main）vs ADR-0021（feat/backend）
   - 解决：混合方案，ADR-0021 的 `ContextProviderEntry` 成为 dead code

2. **Compaction bracket 升级**（T4 #134）：
   - 从单 `CONTEXT_COMPACTED` 升级为 `COMPACTION_START` + `CONTEXT_COMPACTED` + `COMPACTION_END`
   - 这是有意的设计升级，不是 semantic overwrite

3. **RUNTIME 三字段消费**（T5 #135）：
   - reasoning_effort / agent_profile / context_providers 从 staged no-op 提升为运行时真实消费
   - 这是有意的能力提升，不是 semantic overwrite

**结论**：没有发现新的 semantic overwrite。B2 双实现是已知的、已解决的冲突。

---

## 10. GitHub Governance

### Repository

| Item | Value |
|---|---|
| Repo name | `intelligence-agent` |
| Owner | `EricKingWhy` |
| Visibility | PUBLIC |
| Default branch | `main` |

### Branch Protection

```
Branch not protected (HTTP 404)
```

**main 分支没有保护**。任何人（或有 push 权限的人）可以直接 push 到 main，也可以 force push。

### CI/CD

- 没有 `.github/workflows/` 目录
- 没有 GitHub Actions 配置
- 唯一的 CI 是本地的 `pytest` + `ruff` + `tsc` + `oxlint` + `vitest` + `playwright`

### CODEOWNERS

没有 `CODEOWNERS` 文件。

### Open Issues

11 个 open issues（#35, #37, #131-#139），全部标记为 `ready-for-agent` 或 `phase-multiturn`。

### Open PRs

没有 open PRs。

### Tags

4 个 tags：`checkpoint-day-01`, `checkpoint-day-02`, `checkpoint-day-03`, `v1.0.0`

### Remote Branches

6 个 remote branches：`origin/main`, `origin/feat/backend`, `origin/feat/backend-c`, `origin/feat/frontend`, `origin/feat/frontend-B`

---

## 11. 未来三分支工作流评估

### 目标拓扑

```
D:\intelligence-agent          → main（最终集成 + 完整验证）
D:\intelligence-agent-backend  → feat/backend（后端开发）
D:\intelligence-agent-frontend → feat/frontend（前端开发）
```

### 评估

#### 30.1 Branch lifecycle

**当前问题**：
- 分支长期存活，accumulate history
- merge 后分支不删除，造成 confusion
- 多个 phase 分支同时存在

**建议**：
- 每个 feature 完成后立即 merge 到 main 并删除 feature branch
- 不要在 feature branch 上做 long-running 开发
- 使用 `git log --oneline` 定期检查分支状态

#### 30.2 Scope boundary

**建议规则**：

```
Frontend Agent:
  Allowed: web/**, frontend docs/tests/contracts consumption
  Forbidden: src/** changes

Backend Agent:
  Allowed: src/**, backend tests, backend docs
  Forbidden: web/** changes

Shared contract changes:
  Must be coordinated via explicit handoff doc
```

#### 30.3 Main ownership

**建议**：
- Feature agents cannot directly write to main
- Only Integrator writes to main
- Add branch protection rule: require PR review before merge

#### 30.4 Integration Gate

**建议流程**：

```
feature branch targeted gate
  ↓
merge to local main
  ↓
full backend + frontend + contract gate
  ↓
push origin/main
```

**额外建议**：
- 添加 GitHub CI（至少跑 `pytest` + `tsc` + `lint`）
- 添加 branch protection（require PR, require CI pass, no force push）
- 添加 CODEOWNERS（指定 Integrator 为 required reviewer）

---

## 12. Cross-Validation: Codex vs ZCode

| Finding | Codex | ZCode | Final |
|---|---|---|---|
| main dirty with localized text | not reported | discovered | NEW |
| Frontend worktree dirty (7 files) | not reported | discovered | NEW |
| Phase 14/15/16 worktrees stale | reported | verified | CONFIRMED |
| Runtime worktree merged but stale | reported | verified | CONFIRMED |
| Stash contents already merged | not checked | verified | NEW |
| No valuable orphan/dangling commits | not checked | verified | NEW |
| B2 double implementation (ADR-0020b vs ADR-0021) | reported | verified | CONFIRMED |
| ADR-0021 ContextProviderEntry is dead code | not reported | discovered | NEW |
| GitHub: no branch protection | reported | verified | CONFIRMED |
| GitHub: no CI/CD | reported | verified | CONFIRMED |
| GitHub: no CODEOWNERS | not reported | discovered | NEW |
