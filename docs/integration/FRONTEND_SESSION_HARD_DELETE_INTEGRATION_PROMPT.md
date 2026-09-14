# 集成提示词 —— 会话硬删 #172 **前端半**（后端半待先入 `main`）

> 生成时间：2026-09-13 · 分支 `feat/frontend` · commit `57dd028`
> 关联：#172（跨端票，**不要关单**）、ADR-0029、后端半的对侧提示词
> `D:\intelligence-agent-backend\docs\INTEGRATION_PROMPT_SESSION_HARD_DELETE.md`

---

## 0. 一句话状态

`#172` 的前端半已完成并通过门禁，落在 `feat/frontend` = `57dd028`（父 `11ff129`）。
**合并顺序有硬约束**：后端半在 `feat/backend`（`4109b08` + docs `92135a5`），**目前还没进 `main`**
（`main` = `b28e856`）——必须**先后端、再前端**（AGENTS.md §14.9「一次一支」）。两端都进 `main`
并通过真机验收后，才轮到决定关单。

---

## 1. 事实

| 项 | 值 |
| --- | --- |
| 分支 / commit | `feat/frontend` → `57dd028`（父 `11ff129`） |
| 改动规模 | 12 文件，+821 / −4 |
| **改动面** | **全部在 `web/**`**（外加本文件所在目录的文档） |
| 门禁 | `tsc -b` 0 · vitest **639 passed**（36 文件，+11）· oxlint **38w/0e**（基线未动）· playwright **224 passed**（`--workers=2`，+8）· `vite build` ✓ |
| 两轴 code-review | Spec 轴 **0 P1/P2** + 4×P3；Standards 轴 **0 P1/P2** + 7×P3 → 修 4 / 有据不改 3；第二轮 delta 复核全部 VERIFIED / SAFE |
| 变异验证 | 每条新断言逐条"断→红→还原→绿"，`grep -c MUTATION` = 0 |
| 关单 | **否** —— §14.12 跨端票，且前端半尚未入 `main` |

改动文件：

```
web/src/types.ts                          SessionDeleted（deleted: true 字面量）
web/src/lib/api.ts                        deleteSession + SessionError + describeSessionError
web/src/lib/sessionDelete.ts              回执文案纯函数（新增）
web/src/lib/api.test.ts                   +7 例（状态码映射 / 回执透传 / 404 不归 NotFoundError …）
web/src/lib/sessionDelete.test.ts         +4 例（回执 4 分支）（新增）
web/src/hooks/useSession.ts               removeSession + convergeAfterDelete
web/src/components/DeleteSessionDialog.tsx 不可逆确认浮层（新增）
web/src/components/SessionList.tsx        行菜单「删除会话…」+ 浮层接线
web/src/App.tsx                           传 onDeleteSession={removeSession}
web/src/styles/app.css                    身份块 3 条规则（复用既有 token）
web/e2e/fixtures.ts                       有状态 DELETE mock（新增分支）
web/e2e/w-session-delete.spec.ts          4 用例（新增）
```

---

## 2. 合并顺序（**先后端、再前端**）

后端半的对侧提示词 §2 已写明前端"等后端半合入 `main` 后再动手"。前端已动手（用户 2026-09-13
的分工：后端先做完、前端再做），但**代码没有碰任何后端文件**，所以合并顺序仍必须遵守 §14.9：
`main` 上一次只集成一支，且后端入 `main` 后前端要**重新 fetch / diff / merge-base**（§14.9 末段）。

```bash
# ① 后端半先进 main（在 D:/intelligence-agent-backend 全绿后）
git -C D:/intelligence-agent-backend fetch origin --prune
git -C D:/intelligence-agent-backend merge origin/main          # 先回后正，冲突在此解决
git -C D:/intelligence-agent              merge feat/backend
#    → 在 main 上跑后端全量 pytest，按后端提示词 §4 做真机验收 1–10

# ② 再合前端半
git -C D:/intelligence-agent-frontend fetch origin --prune
git -C D:/intelligence-agent-frontend merge origin/main         # 同步刚入 main 的后端半
cd D:/intelligence-agent-frontend/web && \
  npx tsc -b && npx vitest run && npx oxlint \
  && npx playwright test --workers=2 && npx vite build          # 在 feat/frontend 上先跑全绿
git -C D:/intelligence-agent merge feat/frontend
#    → main 上启动完整项目（真后端 + 真浏览器），按 §4 复验
git -C D:/intelligence-agent push origin main
```

### 2.1 可预期冲突面

1. **`docs/SDD_TICKET_TRACKER.md`** —— 两端都会追加。本 side 本轮加了 `W-1` 批次行 +
   「第十三轮」整节；后端 side 若也动了这张表，**冲突时两侧都要保留**（§14.7：不许机械
   `ours/theirs`，也不许删别人的行）。
2. **`docs/PHASE_STATUS.md`** —— 同上，两侧追加都保留。
3. **`web/**`** —— 后端半**未触碰**任何前端文件（其后端提示词 §1.3 第 3 条明示），
   所以这一面**理论上零冲突**。若真出现 `web/**` 冲突，说明另一支也改了前端 →
   **停下来问用户**（§14.7）。
4. `docs/INTEGRATION_PROMPT_*.md` / `docs/adr/0029-*.md` —— 多为新增文件；同名重复按 §14.7 处理。

---

## 3. 前端半做了什么（集成后要能看见的行为）

| 入口 | 行为 |
| --- | --- |
| 会话行 kebab 菜单 | 末尾（两分支共用）多一项「删除会话…」；**不**对正在流式的行禁用（忙不闲由后端 409 说话） |
| 确认浮层 | 写明「硬删除，**不可恢复**」「没有回收站、没有撤销」+ 会话标识（标题 + id 前 12 位）；确认按钮是「永久删除（不可恢复）」而不是「删除」 |
| 首次点击 | 只开浮层，**不发请求**；「取消」= 零请求零变化 |
| 成功 | 浮层内回执：「已永久删除 N 条事件记录（不可恢复），并从 M 个项目里解除。」；关掉后行消失、项目计数跟着掉；**若删的正是当前打开的会话** → 对话区清空 + 记住的会话 id 清掉（刷新不会被拉回死会话） |
| 409（在途 run / 挂起审批 / fork 父会话） | 后端 `detail` **原文**贴在浮层里（三种原因状态码相同，只能靠 detail 区分；fork 那条自带子会话数量，不翻译）；**列表保持原样** |
| 404（会话本就不在了 / 第二次删除） | 如实显示 `detail`，并按「本地这行已过期」收敛掉那一行（不显示成功回执） |

---

## 4. 合并后必跑

1. 前端门禁（§2 的 ② 已包含）：`tsc -b` / `vitest run` / `oxlint` / `playwright test --workers=2` / `vite build`。
   - **5173 复用坑（后端提示词 §2.3 同款，实测有效）**：`reuseExistingServer: !CI` 会静默复用
     别的 worktree 的 dev server。跑之前先确认 5173 上是谁的进程。
2. 后端半的契约测试（确认它确实进了 `main`）：
   `pytest tests/web/test_session_delete_api.py tests/storage/test_session_meta_lineage.py`（31 passed）。
3. **真机验收**：按后端提示词 §4 的 10 步跑（后端负责删得干净/404/409/403/审计），前端侧重点看：
   - 删当前打开的会话 → 对话区清空、**F5 后不会被拉回**那个会话；
   - 删项目里的会话 → 项目计数与 `GET /api/projects` 一致；
   - 有 fork 子会话的会话 → 浮层里出现后端那句 `... fork parent of 2 session(s) ...` 且列表不变。
   - **不要对着默认真实 workspace 删会话**（那里是用户的真实数据）；用临时目录或先备份 `harness.db`。

---

## 5. 已知边界（本票非目标，前端**没有**顺手补）

- Memory / Artifact **不级联**（ADR-0029 D6）；无回收站 / undo / 墓碑 / TTL；不做批量删除。
- `permission_mode` 语义 gap（改档只影响新会话）与本票无关，仍待产品拍板。
- 前端侧**登记不改**的一项：`useSession.refreshSessions` 没有代际守卫，理论上一个"删之前发出、
  删之后才返回"的 `GET /api/sessions` 可能把已删的行短暂带回来。属既有属性、窗口窄，
  按 §8 Scope Lock 不在本票顺手修——若集成或后续票要动，建议新立一票。

---

## 6. 关单纪律

- **#172 现在不关**：跨端票，且前端半未入 `main`（后端提示词 §5 同一处置）。
- 后端半的事实已 comment 在 #172 上；前端半的事实（commit `57dd028` + 门禁数字 + 两轴审查结论）
  也应以 comment 记录。
- **两端齐备、各自门禁通过、且都合入 `main` 并真机验收后**，才按 §14.12 关单。
- 本 worktree **未 push、未 merge**（§13.2/§14.4）；push 与合并归集成 AI。
