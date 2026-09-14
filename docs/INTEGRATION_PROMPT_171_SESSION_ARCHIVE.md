# 集成提示词 —— 会话归档 #171（**两端均已完成**，等待合入 `main`）

> 生成时间：2026-09-14 · 后端 `feat/backend` `9e4adc0` + `2b4e677` · 前端 `feat/frontend` `7d6ebb7` + `07d02cd`
> 关联：#171（跨端票，**两端齐备 ⇒ 可关单**）、ADR-0004 R5 Q18、#172（硬删，另一刀，两者并存不重叠）

---

## 0. 一句话状态

两端都完成、各自门禁全绿、两轴 code-review 收敛。**归档 = 可逆的列表可见性标记**：
只写 `session_meta.archived`，事件日志 / 项目账本 / checkpoint 一个字不动。
本文件是集成 AI 的**唯一入口**，§1 是可执行摘要。

---

## 1. 给集成 AI（合并 + 验收）

### 1.1 事实

| 项 | 后端 | 前端 |
| --- | --- | --- |
| 分支 / commit | `feat/backend` → `9e4adc0`（实现）+ `2b4e677`（detail 逐字锁） | `feat/frontend` → `7d6ebb7`（实现）+ `07d02cd`（tracker 记录） |
| 改动规模 | 6 文件，+611 / −16（`9e4adc0`）+ 1 文件 +19 / −4（`2b4e677`，测试加固） | 14 文件，+862 / −15（`7d6ebb7`，代码+测试）+ 2 文件 +93 / −3（`07d02cd`，文档） |
| 四/五门禁 | `ruff check src/ tests/` clean；全量 pytest **2260 passed / 2 skipped / 42 deselected / 0 failed** | `tsc -b` 干净；vitest **827 passed / 49 files**；oxlint **0 error / 44 warnings**（本票新增 0）；playwright **322 passed**（`--workers=2`，8.4m）；`vite build` 绿 |
| 两轴 code-review | Standards + Spec；findings 全部处理或据证否决 | 同上（9 项；含一项**本票引入的跨端回归**，见 §1.3） |
| 关单 | **可关**（两端齐备，§14.12） | 同 |

改动面（前端）：

```
web/src/types.ts                  SessionSummary.archived（必填）+ SessionArchived 回执
web/src/lib/api.ts                listSessions({includeArchived}) / archiveSession / unarchiveSession + 回执防御
web/src/lib/projects.ts           buildRailModel(..., {includeArchived})：被过滤的行不算 missing
web/src/lib/railArchive.ts（新）  localStorage ahi.showArchived（异常回默认）
web/src/components/SessionList.tsx  kebab 归档项 + 开关 + 徽标 + 就地报错 + 空态真话
web/src/hooks/useSession.ts       setArchived（不动视野）+ refreshSessions 返回是否成功
web/src/App.tsx                   handleSetArchived（失败原因回侧栏，不走流级横幅）
web/src/styles/app.css            徽标 + 开关按下态
web/e2e/archived.spec.ts（新）     6 条 × 2 视口
web/e2e/fixtures.ts               归档 mock（有状态/幂等/409 仅归档方向）+ include_archived 过滤 + sessionsListFailAfter
web/e2e/l-auth-banner.spec.ts     修 glob（本票引入的回归，见 §1.3）
web/src/lib/{api,projects}.test.ts、railArchive.test.ts  单测
docs/E2E_SCENARIO_MAP.md、SDD_TICKET_TRACKER.md           文档
```

### 1.2 合并顺序（§13.3 / §14.6「先回后正」）

```bash
git -C D:/intelligence-agent-backend fetch origin --prune
git -C D:/intelligence-agent-backend merge origin/main          # 先同步，冲突在此解决
# feat/backend 跑到全绿
git -C D:/intelligence-agent-frontend fetch origin --prune
git -C D:/intelligence-agent-frontend merge origin/main         # 前端同样先回
git -C D:/intelligence-agent  merge feat/backend                # 再合入本地 main
git -C D:/intelligence-agent  merge feat/frontend               # 一次一分支（§14.9）
# main 上启动完整项目 + 全量测试 + 真机验收（§4），最后才 push origin main
```

### 1.3 可预期冲突面 / 已知陷阱

1. **`docs/PHASE_STATUS.md`** —— 两端都会追加本票记录，冲突时**两侧都要保留**。
2. **前端 `l-auth-banner.spec.ts` 的路由 glob** —— 本票在列表请求上加了
   `?include_archived=true`，而 Playwright 的 glob 是**整串**匹配：`**/api/sessions`
   配不上带查询串的 URL，于是那条 401 用例走 200 分支、横幅永不出现。已在 `7d6ebb7`
   里改成 `**/api/sessions*`。**若前端 merge 丢了这个字符，e2e 会红在 401 横幅上**
   （看起来与归档毫无关系，别误判为 flake）。
3. **后端 `SessionSummary.archived` 是必填**：老前端（不带该字段的 mock/夹具）会解析出
   `undefined`。本仓前端已同步为必填；若 `main` 上还有其他构造 `SessionSummary` 的地方
   （测试/工具），需要一并补 `archived`。

### 1.4 真机验收（§4，`main` 上做一次）

```bash
# 后端
cd D:/intelligence-agent && .venv/Scripts/python.exe -m pytest -q
# 前端
cd web && npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build
```

真机手工确认清单（mock 覆盖不到的部分）：

- `POST /api/sessions/{sid}/archive` → 200 `{"id":"<sid>","archived":true}`；重复调用仍 200；
- 再 `GET /api/sessions` → 该会话**不在**；`GET /api/sessions?include_archived=true` → 在，且 `archived: true`；
- 归档一个**在途 run** 的会话 → 409，detail = `session '<sid>' has a run in flight; archive it after it finishes`（**取消归档在同一状态下必须 200**）；
- 归档后 `GET /events`、`/lineage`、`/resume`、`/fork` 全部照旧（事件数不变）；
- 审计：结构化日志出现 `session_archive`，字段只有 `session_id` / `archived` / `entry_point`——**不含**会话内容；
- UI：kebab →「归档」→ 行消失（**无**确认弹窗）；顶部图标开关 → 行重现且带「已归档」徽标、菜单项变「取消归档」；刷新后开关状态保留（`ahi.showArchived`）。

**关于抖动（实测记录，避免误判）**：本票验证过程中，首次全量 e2e 里有 `u-project-task.spec.ts`（AC11/AC12）2 例与 `o-wait-hint.spec.ts` 1 例失败；**隔离复跑与最终全量（322/322 passed, EXIT=0）全绿**，判定为时序抖动，与本票改动无关。若在 `main` 上再遇到，先隔离复跑该文件再定性（§16.6 已把 `--workers=2` 固定进配置正是为减少这类抖动）。真正与本票有关的那一例是 `l-auth-banner`（见 §1.3 第 2 条），它**每次必红**、不是抖动。

---

## 2. 契约（两端逐字对齐，别再改）

| 面 | 契约 |
| --- | --- |
| 归档 / 取消 | `POST` / `DELETE /api/sessions/{session_id}/archive` → 200 `{id, archived}`（幂等，值 = **动作后**真值） |
| 列表 | `GET /api/sessions?include_archived=<bool>`；**默认 `false` = 不返回已归档**；非布尔 → 422 |
| 行字段 | `SessionSummary.archived: boolean`（**必填**；`session_meta` 无行 = `false`） |
| 项目视图 | 同口径（默认隐藏）；归档**不改**项目成员关系（`workspace_sessions` 一个字不动） |
| 错误 | 404（不存在）/ 409（**仅归档方向**，在途 run）/ 422（id 形态非法，**先于** 404）/ 403（非信任来源） |
| 审计 | `session_archive`（`logging.EVENT_TYPES`，**不是** SessionEvent；只带 id 与动作） |

---

## 3. 三条"看起来冗余、其实不能改"的设计（请勿在集成时顺手简化）

1. **前端总是请求全量（`include_archived=true`），可见性过滤在投影层。**
   若改成"开关驱动请求"，切换要等 round-trip、两次响应之间是两套真相（不变量 #22），
   而且归档的项目成员会从载荷里消失 → 只能被算成 `missing` → 界面对一条日志好端端
   躺在磁盘上的会话说「会话日志缺失」。后端默认（不带参数不返回）**保持不变**是
   给其他客户端的默认，不是矛盾。
2. **归档不动视野**（`setArchived` 不 `selectSession(null)`）。硬删才需要收敛视图
   （东西没了）；归档只改列表可见性，事件 / lineage / resume 都还在（AC5），把用户从
   正在读的内容里踢出去是在为一个可逆的标记付不可逆的代价。
3. **`missing`（「n 条会话日志缺失」）只在"载荷里真的没有这个 id"时 +1。**
   被开关过滤掉的行**不是**缺失。这条有 e2e 双向对照（一个真缺失的账本 id + 一个归档行）
   与单测双断言；把两者合并会立刻变红。

---

## 4. 如实登记的四条残余（不阻塞合入）

1. **窄屏 / 触摸档看不到归档失败的报错**：`@media (max-width: 820px)` 里 `.rail-error`
   是 `display: none`（WS-5 的既有降级）。#181 让 ⋯ 在触摸档可达之后，窄屏用户**能**
   触发归档却看不到失败原因。真修要先定案窄屏槽位/降级模型（与 #181 残余 ①② 同批）。
2. **AC11 的可选「轻量提示 + 撤销」未实现**：票面是"**可**"，不是必须；撤销入口 =
   菜单里的「取消归档」。
3. **跨仓文案同源靠两侧各自断言**：404/409 的 detail 原句由后端 `2b4e677` 与前端 e2e
   fixture 各锁一份（无单一来源）；任一侧改词，另一侧会红。
4. **`/stream` 未在归档态下被 e2e 覆盖**：后端 AC5 已有契约测试，且 stream 读日志不读
   `session_meta`；属联调车道可补项。

---

## 5. 关单（§14.12）

两端齐备、各自门禁通过 ⇒ **可以关单**。关单 comment 请写明：
后端 `feat/backend 9e4adc0`（+`2b4e677`）、前端 `feat/frontend 7d6ebb7`（+`07d02cd`）、
两侧门禁数字、以及本节四条残余。
