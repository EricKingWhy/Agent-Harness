# 集成提示词：#184 补齐 Inspector 的 PERMISSION 段（前端）→ `main`

**一句话**：Inspector 补上此前完全缺失的 **PERMISSION** 段（权限档 / 待审批 / 裁决结果），
数据全部来自事件流投影，**零新 API**。

工作区：`D:\intelligence-agent-frontend`，分支 `feat/frontend`，基线 `dd4b104`（= #190 的
文档 commit）。**只动前端**。

---

## 1. 本轮 commit

| commit | 内容 |
| --- | --- |
| `3a57924` | `feat(panel): #184` 实现 + 测试 + e2e（11 文件，+661 / −21） |
| （随后一条） | `docs(panel): #184` 在途进度登记（`docs/SDD_TICKET_TRACKER.md`）+ 本提示词 |

---

## 2. 改了什么

| 文件 | 改动 |
| --- | --- |
| `web/src/types.ts` | `approval_decisions`（裁决留痕）+ `permission_policy`（逐事件折叠） |
| `web/src/lib/projection.ts` | 决议 → 出队 + 留痕（幂等）；审批请求 → 权限档折叠 |
| `web/src/lib/permission.ts`（新） | 段内**措辞与语义色档**（`decisionLabel` / `verdictTone` / `permissionView`）——本仓无 jsdom，措辞规则靠纯函数单测钉死 |
| `web/src/components/StepDetail.tsx` | `PermissionSection`（排在 MODEL 与 CHECKPOINT 之间）；`onJumpToApproval` 缺省 → 静态行 |
| `web/src/components/Conversation.tsx` | 审批卡外层加 `data-approval-key`（跳转落点） |
| `web/src/App.tsx` | `jumpToApproval`——复用既有 `jumpRequest`（key 前缀 `approval:`） |
| `web/src/styles/app.css` | `.detail-permission-*`、`.detail-permission-row-static`、`.permission-verdict-allow/-deny` |
| `web/e2e/x-permission-section.spec.ts`（新） | 3 条 × 2 视口 |

**新增测试**：`lib/permission.test.ts`（9）、`lib/projection.test.ts`（+7 条审批投影）、
`e2e/x-permission-section.spec.ts`（3 × 2 视口）。

---

## 3. AC 对照（票面 6 条）

| AC | 状态 | 证据 |
| --- | --- | --- |
| 1 权限档 + 待审批 + 裁决结果 | ✅ | `PermissionSection`；e2e 三态各一条 |
| 2 无待审批**如实显示**「无待审批」，不整段消失 | ✅ | 零审批会话的 e2e 断言段仍在且含「无待审批」「尚无裁决」；单测锁死措辞 |
| 3 **不新增** ARTIFACTS run 级段；CHECKPOINT 保持诚实占位 | ✅ | 未新增任何 ARTIFACTS 段；CHECKPOINT 一行未改 |
| 4 不可得数据 → `—`/省略，**不填 0** | ✅ | 无审批事件 → 权限档 `—` **并说明原因**；零计数用「无待审批」而非 `0`；单测覆盖 |
| 5 vitest（投影派生）+ ≥1 条 e2e（有待审批时出现且能进审批面） | ✅ | 投影 7 条 + 措辞 9 条；e2e：点待审批行 → 审批卡被 pulse（反向联动）且可见 |
| 6 不改 `POST /approve` 契约语义 | ✅ | `lib/api.ts` 一行未改 |

---

## 4. 一条需要知道的**设计判断**（权限档的诚实边界）

`permission_mode` **不在任何 SessionEvent 里，也没有 GET 接口**：后端只在
`POST /api/sessions` 收它（`web/app.py:209`）用于构造 `PermissionPolicy`，而续聊的
`SendMessageRequest` 不带它 ⇒ 档位在会话创建时定死。因此 Inspector 无法知道"这个 run
选了哪一档"；唯一带**运行时证据**的是审批请求携带的 `policy`（ToolExecutor 当时实际用的
阈值）。

于是：**整个会话没有审批事件 → 权限档显示 `—` 并说明"本会话无审批事件，生效阈值无从得知"**。
刻意**没有**拿 composer 里"下次运行的选择"来填这一行——那是"下次运行"的语义，画在
"本会话权限档"名下就是假事实。若产品上希望显示"下次运行的档位"，应作为单独一行
（并注明生效时机）另开票，不要改这一行。

---

## 5. 门禁基线（供集成时比对）

- `cd web && npx tsc -b` → 0
- `npx vitest run` → **717 passed**
- `npx oxlint` → **0 error**（41 warnings 全为既有；本票新增文件**零 warning**）
- `npx playwright test --workers=2` → **272 passed**
- `npx vite build` → 0

---

## 6. 未交付 / 已知边界（**别当成回归**）

1. **PERMISSION 段也出现在子会话只读视图**（`StepDetail.tsx` 的 child 面板复用
   `ChatTab`）。那里没有 `onJumpToApproval`，所以待审批行渲染为**静态行**（不画假按钮）
   ——这是既有设计决策（"ChatTab 复用，工具行静态化"）的自然延伸。
2. **`.detail-permission-row-static` 必须排在 `.detail-permission-row` 之后**（CSS 注释
   已写）。同特异度下后者胜，顺序倒过来只读行就会变回 `cursor: pointer` 的假按钮。
3. **artifact 写入侧仍未接上（后端，跨 worktree）**：唯一的外置写入者
   `ArtifactOverflowHandler` 只在 `assembly.py` 的 `artifact_store_*`（S3）分支被创建，
   `minio_*` 分支只注册**读**工具；而 `D:\intelligence-agent` 的 `.env` 里
   ARTIFACT/MINIO/S3 键一个都没有 ⇒ 什么都不外置。后果：#185 的读取接口在真机上只会回
   503，#186「artifact 内容可见」落地后也会看不到内容。**已报告用户等待决策，本轮未动。**

---

## 7. 给集成 AI 的动作（沿用 §14 纪律）

1. `git -C D:\intelligence-agent fetch origin --prune`；`git diff main...feat/frontend` 应只剩
   #182 / #190 / #184 三票的 commit（前两票已关单，提示词见
   `INTEGRATION_PROMPT_PANEL_182.md` / `_190.md`）。
2. **先回后正**：把 `origin/main` 合进 `feat/frontend`，在 feature 分支上解决冲突、跑门禁
   （§5），**再**合 `feat/frontend` → 本地 `main`。
3. 冲突处理遵循 §14.7：逐文件分析，**禁止**机械 `ours`/`theirs`。本票与后端
   `feat/backend` 的 #185 **无文件重叠**，预期无冲突。
4. `git push origin main` **需用户明确批准**后再执行；`feat/frontend` 分支本轮**不需要**推。
5. 关单依据：AC 见 §3；#184 的 issue 由本轮交付方关闭（comment 写明分支/commit 与 §4 的
   权限档边界）。
