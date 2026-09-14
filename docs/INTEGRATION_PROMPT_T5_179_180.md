# 集成提示词：#178（spec T5）+ #179/#180（前端决策票）→ `main`

> 生成者：backend agent（worktree `D:\intelligence-agent-backend`，分支 `feat/backend`）。
> 生成时间：2026-09-13。
> **本提示词写给集成 AI。** 本次要合两条分支的成果：`feat/backend`（#178，1 个 commit）
> 与 `feat/frontend`（#179/#180，2 个 commit）。**合并与 push 都需要用户明确批准**（AGENTS.md §14.4）。

---

## 0. 先读这条：`origin/main` 现在落后两条分支

上一轮集成（`d6c5fff`，2026-09-13 17:04）把 `feat/backend` 合进了 main，**并 push 了**
（那次 prompt §1 写过"`git push` 不在本次范围"）。此后两条分支又各自前进了：

| 分支 | 相对 `origin/main`（`d6c5fff`，实测） | 说明 |
| --- | --- | --- |
| `feat/backend` | **6 ahead / 32 behind**（+ 本 docs 提交 = 7） | spec #173 T1–T4（`4a261c2` `d134c21` `b43f1b1` `88fbd46`）+ `2e3dd16`（收口台账）+ 本轮 #178（`60c8d05`）+ 本提示词 |
| `feat/frontend` | **11 ahead / 11 behind** | 第十一轮 6 个（`47b2644` `65c8b7b` `2c5adbd` `59673ef` `8e8f0ab` `08f8ebf`）+ 本轮 2 个（`4fe1ab8` `42d9ff0`）+ #172 前端半 3 个（`11ff129` `57dd028` `5d56038`） |

也就是说：**main 现在既没有 spec 事件表对齐（T1–T4），也没有第十一轮的全部前端修复，
也没有本轮 #178/#179/#180。** 本轮要一次把它们补齐。

> ⚠️ **别在没 fetch 的 clone 上做冲突分析**：`D:\intelligence-agent-frontend` 这个 clone 的
> `origin/main` 曾长期停在旧 ref（上一轮是 `593dcda`）。先 `git fetch origin --prune`，
> 否则你会在过期基线上判断"差哪些"。

---

## 1. 本轮要合的两批 commit

### 1.1 `feat/backend`（spec #178 + 状态文档）

| commit | 内容 |
| --- | --- |
| `60c8d05` | #178 T5 路线 B：`scripts/gen_event_vocabulary.py` + `docs/EVENT_VOCABULARY.md`（生成物）+ `tests/test_event_vocabulary_generated.py`（4 条守卫）+ spec 03 §3 改为契约源指向链 |
| 待提交 | `docs/FRONTEND_ISSUES_LOG.md`（DOC-01 收口）+ `docs/PHASE_STATUS.md`（两条记录）+ 本提示词 |

### 1.2 `feat/frontend`（#179 + #180）

| commit | 内容 |
| --- | --- |
| `4fe1ab8` | #179 窄屏项目级操作恢复可达（`.rail-project-head` 不再整块收起，槽位交换语义）+ #180 Split/Preview 收敛为诚实占位（disabled + aria-disabled + title，删掉 `workspaceMode` 与 `.workspace-scaffold*`）+ `u-project-task` 权限档断言订正 |
| `42d9ff0` | 前端在途台账（第十四轮）+ 上一轮"226 e2e 全绿"的口径订正 |

---

## 2. 合并顺序（§14.6 先回后正、§14.9 一次一条）

```text
1) git fetch origin --prune
2) feat/backend：git merge origin/main（先回）→ 解决冲突 → 门禁 → 通知用户
3) feat/frontend：重新 fetch 后再 git merge origin/main（先回）→ 解决冲突 → 门禁 → 通知用户
4) 两条分支都稳定后：按 feat/backend → feat/frontend 顺序合进本地 main
5) 在 D:\intelligence-agent 跑完整门禁 → 用户批准后才 push
```

**冲突预判（先看，别现场猜）**：

- `docs/PHASE_STATUS.md`、`docs/FRONTEND_ISSUES_LOG.md`：**两侧都改过**（第十一轮已发生过一次
  拆分：main 侧拆成「（前端侧）/（后端侧）」+ 头注）。这两处是**追加式**记录，冲突时两边的
  段落都要保留——不要用 ours/theirs 机械取舍。
- `goal/.../spec/03_SESSION_EVENT_MODEL.md`：只有 backend 改（`feat/frontend` 没动 spec）。
- `web/**`：`feat/backend` 里有一份**旧的前端快照**（此前测得落后 main 54 个文件）；
  合并时若 main 侧的 `web/` 更新，**以 main 侧为准**，别让旧快照覆盖前端成果。
- `docs/SDD_TICKET_TRACKER.md`：只在 frontend worktree 存在。

---

## 3. 四条必须真机/真跑验证的点（别只看 diff）

1. **事件词汇守卫真的在跑**：`uv run pytest tests/test_event_vocabulary_generated.py -q` → 4 passed；
   然后故意改坏产物（往 `docs/EVENT_VOCABULARY.md` 塞一行假事件）确认它变红，再还原。
2. **spec §3 与生成物一致**：`docs/EVENT_VOCABULARY.md` 头部合计行 = 36 持久化 + 2 仅广播 = 38；
   `src/agent_harness/session/event.py` 的 `EVENT_TYPES` / `STREAM_ONLY_TYPES` 大小相符。
3. **窄屏项目级操作**：真机把窗口拖到 ≤820px（或用 devtools 设备模拟），确认
   ①项目行显示文件夹图标；②hover/聚焦时换成 ⋯；③菜单三项与宽屏一致；
   ④重命名输入框可用（不是被压成几十像素）。**顺带确认触摸设备这一档**：目前 ⋯ 依赖
   hover/focus-within，触摸可能拿不到（已开 **#181**，本轮未修）。
4. **Split/Preview 不可再选**：真机点两个预留位——不应有任何状态变化、不应出现"未来升级点"
   提示条；`title` 与无障碍名字里都有说明。

---

## 4. 未交付 / 已知边界（别当成回归）

- **#181**（新开）：≤820px **触摸设备**上 ⋯ 可能仍不可达（无 hover；iOS 上 `button` 默认不聚焦）。
  会话级与项目级同款问题，等产品裁决（建议 `@media (hover: none)` 下常显 ⋯）。
- **#173 母票**仍未关：T1–T4、T5 都已交付关单，母票本身的收尾由用户决定。
- **#172** 仍 OPEN：后端半在前一轮已进 main，前端半（`57dd028`）随本轮一起合。
- **#171**（会话归档）未开工，与本轮无关。
- 已知**偶发**（非本票引入）：`tests/sandbox/test_exec_hardening.py::test_local_exec_timeout_kills_grandchild_tree`
  在**并发跑前端 e2e** 时会因时序抖动失败；无并发负载复跑 2135 passed / 0 failed。
  集成时若撞上，先确认是单独跑必过、再判定为抖动。

---

## 5. 本轮门禁基线（供你比对）

| 侧 | 命令 | 结果 |
| --- | --- | --- |
| backend | `uv run ruff check .` | All checks passed |
| backend | `uv run pytest -q`（**无并发**） | **2135 passed / 10 skipped / 42 deselected / 0 failed** |
| frontend | `npx tsc -b` | 干净 |
| frontend | `npx vitest run` | **659 passed（38 文件）** |
| frontend | `npx oxlint` | 0 error |
| frontend | `npx playwright test --workers=2` | **240 passed** |
| frontend | `npx vite build` | 绿 |

---

## 6. 六条禁令（沿用上一轮，务必逐条遵守）

1. **不要 push**——`git push` / PR 都要用户显式批准（§14.4）；本提示词不构成批准。
2. **不要在 `main` 上解决复杂冲突**——复杂就 `git merge --abort`，回 feature worktree 解决（§14.8）。
3. **不要机械 ours/theirs**——冲突逐文件分析语义，`PHASE_STATUS`/`FRONTEND_ISSUES_LOG` 两侧都要留（§14.7）。
4. **不要用 `git pull`**——`git fetch origin --prune` + 显式 `git merge`（§14.5）。
5. **不要删除任何分支 / worktree / 不要 `reset --hard` / `rebase`**（§14.4）。
6. **不要顺手改代码**——发现规格冲突或范围外问题，报告并停下来（§8）。

---

## 7. 集成期追加修复：OBS-10.1 断连用例假红（**仅测试，无生产代码变更**）

集成时 `main` 后端全量门禁的**唯一红点**就是 OBS-10.1 这条
（`tests/test_web_api.py::test_disconnect_leaves_run_running_and_cancel_stops_it`）。
根因早已登记（冷装配：Milvus 冷 connect 2.01s + langmem 冷 import 1.32s + 其余装配撑破 5s 预算），
处置方向也已写明（**计时块之外预热，不要放宽超时**）；本轮把该修法落地：

- 改动文件：`tests/test_web_api.py`（**只有测试**，`src/` 零变更）。
- 做法：`_DisconnectingASGI` 增 `budget_s` 参数（默认 5.0 不变，测量请求仍用 5s）；
  测量前先发一次**预热请求**（`_ImmediateRuntime` + `budget_s=60`）付掉一次性冷装配。
- 证据：预热 6.546s（冷）→ 测量 0.005s；全新冷进程连跑 **4/4 passed**（修复前同条件 4/4 failed）；
  全量 **2135 passed / 0 failed**（修复前 `2134 passed / 1 failed`）。
- 对集成的影响：**只有测试稳定性**，不改任何运行语义。你重新跑门禁时应直接绿。
