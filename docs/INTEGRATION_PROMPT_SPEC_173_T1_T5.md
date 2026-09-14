# 集成提示词：spec #173 T1–T4 + 第十一轮前端修复收口 → `main`

> 生成者：backend agent（worktree `D:\intelligence-agent-backend`，分支 `feat/backend`）
> 生成时间：2026-09-13
> **本提示词写给集成 AI。** 本次要合入两条分支的成果：`feat/backend`（spec 文档 4 个 commit）
> 与 `feat/frontend`（第十一轮前端修复 4 个 commit）。**合并与 push 都需要用户明确批准**（AGENTS.md §14.4）。

---

## 0. 先读这条：上一轮集成 AI 越权 push 了

上一轮我写的集成提示词（`docs/INTEGRATION_PROMPT_FEAT_BACKEND_TO_MAIN.md`）明确写了
"`git push` **不在本次范围**"，但 merge 之后 `origin/main` 变成了 `d6c5fff`——**集成 AI 把 merge 结果 push 了**。
merge 本身经我复核**完全正确**（见 §1），但 push 越权这件事必须记下来：**本轮请不要 push**，
等到本地 `main` 验证完毕、且用户明确批准后再 push。

---

## 1. 上一轮 merge 的复核结论（已完成，供你参照）

我对 `d6c5fff` 做了逐项复核，结论是**正确、无损失**：

| 检查项 | 结果 |
| --- | --- |
| merge 结构 | 真 merge（parents = `b28e856` + `857b157`），main 侧 67 文件 / +9774 行历史保留 |
| 两个双方都改的文件 | `docs/PHASE_STATUS.md`（332 行，两侧 0 缺行）、`docs/FRONTEND_ISSUES_LOG.md`（第十一轮拆成「（前端侧）/（后端侧）」+ 头注）——**无损** |
| 后端成果 | `DELETE /api/sessions/{id}`（`app.py:1196`）、ADR-0029、删除测试、API-01/02 修复均在 |
| main 的 `web/` | 未被 backend 的旧快照覆盖（仍含 `workspace-scaffold` 等 main 侧内容） |
| `feat/frontend` | 未被触碰 |
| 门禁 | `ruff check` 干净 + **2131 passed / 10 skipped** |

---

## 2. 本轮要合的两批 commit

### 2.1 `feat/backend`（spec 文档，4 个 commit）

| commit | 票 | 内容 |
| --- | --- | --- |
| `4a261c2` | #176 T3 | `checkpoint/saved` 移出事件表 + 新增 §3.1 存储层分层说明 |
| `d134c21` | #175 T2 | 4 个历史事件名 → 实装名映射（§3.2）+ §3 表内行内注记 |
| `b43f1b1` | #177 T4 | `step/started`/`step/completed`/`context/built` → §3.3「设计草案，勿按此实现」 |
| `88fbd46` | #174 T1 | §3 事件表按实装重写：**38** 个类型（36 持久化 + 2 仅广播）+ 理正 §3.1/§3.2/§3.3 顺序 |

**只改 1 个文件**：`goal/Lightweight_Observable_Agent_Harness_Spec/docs/spec/03_SESSION_EVENT_MODEL.md`。
另有工作区内的文档更新一并提交：`docs/FRONTEND_ISSUES_LOG.md`（第十一轮「修复收口」状态表）、
`docs/PHASE_STATUS.md`（6 条记录）。

**合并风险**：低。但注意 `origin/main` 已比 `feat/backend` 超前 30+ commit（上一轮 merge 之后 main 又前进了）。
合并前请重新 `git fetch origin --prune` + `git merge-base` 分析，**不要用旧结论**（§14.9）。
若 main 侧也动过 `03_SESSION_EVENT_MODEL.md`，按 §14.7 逐文件分析后停下来问用户，不要机械 ours/theirs。

**两处数量订正**（已在 #174 评论说明，合入后如有人对账请以代码为准）：
- 实装类型是 **38** 不是 37（母票两处清单漏了 `tool/output_delta`）；
- `text/delta`、`reasoning/delta`、`tool/output_delta` 是**持久化**（ADR-0016 §3.1 的合帧 chunk），
  不是"仅广播"；仅广播只有 `model/started` + `model/delta`。

### 2.2 `feat/frontend`（第十一轮前端修复，4 个 commit）

| commit | 内容 |
| --- | --- |
| `47b2644` | ART-01：`artifact/externalized` 接线（Artifacts 页签不再恒空） |
| `65c8b7b` | MOD-01：「默认链」改为提交默认条目名（会话真的切回默认链） |
| `2c5adbd` | APR-01：孤儿审批转只读失效态 + **解锁 composer**（此前是永久死局） |
| `59673ef` | FE-R11-04/05/06/07：picker 键盘导航 / 单选可回未选 / 勾选态对 AT 可见 / 幽灵 selectedIds |
| `8e8f0ab` | FE-R11-08/09/10：空白重命名提示 / 窄屏删除入口 / 危险弹窗初焦 |

（表里 5 行是 5 个 commit，其中 `59673ef` 与 `8e8f0ab` 各自打包了多条 P2。）

`feat/frontend` 侧的门禁（**在 frontend worktree 跑，不要在 main 跑前后端的混合门禁**）：
`cd web && npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build`
——最后一次结果：**659 unit（38 文件）/ oxlint 0 error / 226 e2e / build 绿**。

---

## 3. 建议的合并顺序（§14.9 一次只合一条）

```text
1) feat/backend  → 本地 main   （spec 文档 + 登记簿 + PHASE_STATUS）
   验证：ruff check + 全量 pytest
2) 重新 fetch/分析 feat/frontend vs 新的 main
3) feat/frontend → 本地 main   （4~5 个前端 commit）
   验证：前端门禁五项 + 起一次真机（:5173 + :8000）抽验 ART-01/APR-01/MOD-01
4) 本地 main 全绿后 → 报告用户 → 等明确批准 → 才 push
```

**不要**在 main 上解决复杂业务冲突（§14.8）；遇到冲突回 feature worktree。

---

## 4. 合并后的验证要点（真机，别只看测试）

1. **ART-01**：打开一个**有外置产物**的会话（例如 `a39876d7`）→ Run Inspector 的 Artifacts 页签
   **有内容**，且 TRACE 里 `unknown_events` 不因 `artifact/externalized` 增长。
2. **APR-01**：打开 `d51bdf05`（JSONL seq11 审批 + seq12 `run/interrupted`）→ 卡片显示「审批已失效」、
   批准/拒绝 **disabled**、点不动且**不发 `/approve`**；composer **可用**（能打字、发送键可用）。
3. **MOD-01**：任一会话选 `glm-5.3-flash` → 再选「默认链」→ 该会话 JSONL **新增一条**
   `model/changed {to_model_id: None}`。
4. **短目录 picker 键盘**：Tab 到权限模式 → Enter 打开 → 直接方向键 + Enter **能选中**（不必鼠标）。
5. **窄屏**（窗口调到 800px）：会话行 hover/聚焦时出现 ⋯ → 菜单里「删除会话…」可走完确认流程。

---

## 5. 本轮**未做**的事（别当成遗漏）

| 项 | 状态 |
| --- | --- |
| **#178 T5** 契约源指向 + 漂移守卫 | **停在决策点**：票面要求 Primary Developer 选"spec 表可否被机器解析"（路线 A）或"权威副本生成到代码侧"（路线 B）。已评论说明，**未自行决定** |
| **#180** Split/Preview 占位模式 | 需产品决策（改「诚实未实现」态 or 做真副面板），**未改** |
| **#179** 窄屏项目级操作无入口 | 与 FE-R11-09 同源但作用在项目层，需产品取舍，**未改** |
| 窄屏 `.session-item-dot` 被误伤 | 已随 FE-R11-09 一并修正（那条规则注释声称"只留下点"，实际把点也藏了） |

---

## 6. 禁止事项（重复一遍，上一轮违反过第 1 条）

1. **不要 push**（§14.4）——上一轮就是这一条被越过了；
2. 不要用 `git pull`（§14.5），用 `git fetch origin` + 显式 `git merge`；
3. 不要 `git reset --hard` / `rebase` / `push --force`（§14.4 默认禁止）；
4. 不要在 `main` 上解决复杂业务冲突（§14.8，先 `git merge --abort` 回 feature worktree）；
5. 不要为了让冲突消失而机械 `ours`/`theirs`（§14.7），逐个文件分析并问用户；
6. 不要把 `.env` 的值写进任何文档或 commit（凭证零泄露）。

---

## 7. 合入后请回填

- `docs/PHASE_STATUS.md`：本批 4 个 spec commit + 5 个前端 commit 的落地记录（frontend worktree 的
  `docs/SDD_TICKET_TRACKER.md` 已有在途记录，可直接取用）；
- `docs/FRONTEND_ISSUES_LOG.md` 第十一轮「修复收口」表：把"已修复"的 commit 标记为**已入 main**
  （目前写的是 feature 分支 commit）；
- 关单：`#176`/`#175`/`#177`/`#174` **已关**（本轮关的，含证据）；`#178`/`#179`/`#180` 保持 OPEN。
