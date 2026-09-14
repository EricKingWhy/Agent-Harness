# 集成 AI 执行提示词 —— B1 集成入 main

> **发件方**：前端 AI（worktree `D:\intelligence-agent-frontend`，分支 `feat/frontend-d`）
> **收件方**：集成 AI（Git Integrator）
> **日期**：2026-09-08
> **任务**：把后端 B1（Ticket B1：Context/Agent/Reasoning 四档契约清单端点）从 `feat/backend-d` 集成入 `main`

---

## 1. 待集成分支

| 项 | 值 |
| --- | --- |
| 后端 worktree | `D:\intelligence-agent-backend` |
| 分支 | `feat/backend-d` |
| Base commit | `431f75b`（origin/main） |
| HEAD commit | `f8e4113`（本地，未 push origin） |
| Commit count | 2 |

### Commit 清单

1. `f742cb7` — `feat(web): Ticket B1 — Context/Agent/Reasoning 四档契约清单端点`
   - 新增三个只读 GET 端点：`/api/reasoning-efforts`、`/api/agent-profiles`、`/api/context-providers`
   - 对齐既有 `/api/permission-modes` 模式（Reuse First §6）
   - 单一事实源重构：CreateSessionRequest validator 从硬编码字面量改为引用模块级常量 dict
   - 测试：9 条（3 端点 × 3 case：正常返回 / schema 锁定 / id 集合匹配 validator）
   - 文件变更：`src/agent_harness/web/app.py`（+99/-4）、`tests/web/test_web_phase5_staged_endpoints.py`（+138，新建）、`docs/integration/BACKEND_D_HANDOFF.md`（+165，新建）

2. `f8e4113` — `docs(integration): B1 集成提示词 + 前端 F1 执行手册`
   - 前端 F1 执行手册（`D:\intelligence-agent-backend\docs\integration\FRONTEND_PROMPT_B1.md`）
   - B1 集成交接单（`docs/integration/BACKEND_D_HANDOFF.md`）

---

## 2. 集成前只读检查清单

请按 §14.2 Worktree Rules 先确认：

- [ ] `git -C D:\intelligence-agent-backend worktree list --porcelain` — 确认 worktree 路径与分支映射
- [ ] `git -C D:\intelligence-agent-backend status --short` — 确认 working tree clean
- [ ] `git -C D:\intelligence-agent-backend branch --show-current` — 确认当前分支 = `feat/backend-d`
- [ ] `git -C D:\intelligence-agent-backend log --oneline feat/backend-d -5` — 确认 HEAD = `f8e4113`
- [ ] `git -C D:\intelligence-agent-backend merge-base feat/backend-d origin/main` — 确认 base = `431f75b`

拓扑核验：

```bash
git -C D:\intelligence-agent-backend fetch origin --prune
git -C D:\intelligence-agent-backend log --oneline origin/main -3
git -C D:\intelligence-agent-backend merge-base feat/backend-d origin/main
git -C D:\intelligence-agent-backend rev-list --count origin/main..feat/backend-d  # 应为 2
```

---

## 3. 冲突预测

### 3.1 与 main 的冲突风险：极低

B1 改动集中在后端 `src/agent_harness/web/app.py` 和测试文件。main HEAD = `70f2671`（F2 ModelPicker Combobox 升级），改动在前端 `web/src/components/ModelPicker.tsx`，两者完全不重叠。

### 3.2 具体文件分析

| 文件 | 变更类型 | 冲突风险 |
| --- | --- | --- |
| `src/agent_harness/web/app.py` | 修改（+99/-4） | 无——main 未改此文件 |
| `tests/web/test_web_phase5_staged_endpoints.py` | 新建 | 无——新文件 |
| `docs/integration/BACKEND_D_HANDOFF.md` | 新建 | 无——新文件 |
| `docs/integration/FRONTEND_PROMPT_B1.md` | 新建 | 无——新文件 |

### 3.3 Windows 大小写路径碰撞

F2 集成时已处置过 SDD 目录大小写碰撞（方案 A 对齐到规范 PascalCase 路径）。B1 不涉及 SDD 目录变更，无碰撞风险。

---

## 4. 集成方向

按 §14.6 Merge Direction「先回后正」：

```text
origin/main (70f2671)
    ↓
feat/backend-d ← 在这里解决 Conflict、Test、Review
    ↓
main           ← feature branch 稳定后再合入
```

### 4.1 集成步骤

1. **在 `feat/backend-d` 上 merge `origin/main`**（先回后正）：
   ```bash
   git -C D:\intelligence-agent-backend fetch origin --prune
   git -C D:\intelligence-agent-backend merge origin/main
   ```
   - 如果有 conflict，逐文件分析（§14.7），不要机械 ours/theirs
   - 预期：无 conflict（B1 与 F2 改动不重叠）

2. **验证**（在 `feat/backend-d` 上）：
   ```bash
   cd D:\intelligence-agent-backend
   uv run pytest tests/web/ -v          # B1 新增 9 条 + 既有 web 测试
   uv run ruff check src/ tests/         # ruff clean
   ```

3. **merge `feat/backend-d` 到 `main`**（在 `D:\intelligence-agent` 或指定集成 worktree）：
   ```bash
   git -C D:\intelligence-agent checkout main
   git -C D:\intelligence-agent merge feat/backend-d
   ```

4. **在 main 上验证**：
   ```bash
   cd D:\intelligence-agent
   uv run pytest tests/web/ -v
   uv run ruff check src/ tests/
   ```

5. **更新 `docs/PHASE_STATUS.md`**：记录 B1 集成入 main。

6. **push main**（需用户单独批准，§14.4）：
   ```bash
   git -C D:\intelligence-agent push origin main
   ```

---

## 5. 验收标准

- [ ] `feat/backend-d` merge `origin/main` 无 conflict（或有 conflict 已正确解决）
- [ ] B1 新增 9 条测试全绿
- [ ] 既有 web 测试套件全绿（无回归）
- [ ] ruff clean
- [ ] main 上 `GET /api/reasoning-efforts`、`GET /api/agent-profiles`、`GET /api/context-providers` 三个端点可访问
- [ ] `docs/PHASE_STATUS.md` 更新

---

## 6. 集成后通知

集成完成后，请通知前端 AI：

1. main HEAD = ?（新 main 的 commit hash）
2. 三个 B1 端点已在 main 上就绪
3. 前端 AI 可从新 main 开 `feat/frontend-e` 分支做 F1

---

## 7. 参考

- `D:\intelligence-agent-backend\docs\integration\BACKEND_D_HANDOFF.md` — B1 集成交接单
- `D:\intelligence-agent-backend\docs\integration\FRONTEND_PROMPT_B1.md` — 前端 F1 执行手册
- `D:\intelligence-agent\docs\integration\HANDOFF_REMAINING_TICKETS.md` — 遗留项交接单
- AGENTS.md §14 Git Workflow / Merge Safety
