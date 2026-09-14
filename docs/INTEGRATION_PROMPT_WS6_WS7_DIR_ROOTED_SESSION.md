# 集成提示词 — WS-6 / WS-7：目录会话 + 宿主目录选择器（#169 / #170，**两端已齐备**）

> **给集成 AI 的可执行摘要**：本批的**后端半**在 `D:\intelligence-agent-backend`（分支 `feat/backend`），
> **前端半**在**隔离 worktree** `D:\intelligence-agent-frontend-ws6`（分支 `feat/frontend-ws6-ws7`，
> base = `feat/frontend` 的 `522602d`）——之所以另开隔离 worktree，是因为 `D:\intelligence-agent-frontend`
> 当时有并行会话在编辑（见该 worktree `docs/SDD_TICKET_TRACKER.md` §B-2 首段）。
> 两端各自门禁 + 真机均已通过，两张 issue 已按 §14.12 关闭（关单 comment 写明分支/commit/集成待办）。
> 请按 §0 顺序操作；§6 是合入后的验证清单；§7 是未决项。
> 来源文档：`docs/PRD_WS6_WS7_DIR_ROOTED_SESSION_AND_DIR_PICKER.md`（契约矩阵）、
> `docs/adr/0027-session-cwd-arbitrary-directory.md`、`docs/adr/0028-host-directory-listing-endpoint.md`、
> 根目录 `CONTEXT.md`（Workspace / Project / Directory-rooted Session 正名）。
> 进度单一事实源：`docs/SDD_TICKET_TRACKER.md` 的「B-2」批次记录（后端）；前端的 B-2 记录在
> 隔离 worktree 的 `docs/SDD_TICKET_TRACKER.md`（两份 B-2 是本批的两半，不要在 main 上弄混）。

---

## 0. 一句话与操作顺序

本批让**会话可以落在任意已存在的真实目录**（`POST /api/sessions { cwd }`，自动注册为项目并归组），
并新增一个**只读的宿主目录列举端点**（`GET /api/host/dirs`）驱动前端的目录选择器——
UI 上体现为项目行/空项目的「在此项目中新建任务」入口 + 确认面，以及「新建项目」里内嵌的目录浏览器。

```text
1) feat/backend → main（先合后端，§14.9 一次只合一条分支）
2) main → 启动完整项目 + 全量 pytest（§2 后端门禁）
3) 前端分支的落点（推荐顺序，§14.6「先回后正」）：
   a) 先在 D:\intelligence-agent-frontend 结束在途的 U-2/U-3（它们与本批文件重叠，见 §0.1）
   b) 在该 worktree 里把 feat/frontend-ws6-ws7 合进 feat/frontend 并解决冲突 / 重跑前端门禁
      （本批 base `522602d` 就是 U-2 的功能 commit，U-2 的审查修复尚未落在它上面）
   c) feat/frontend → main
4) main → 启动完整项目（真 .env）跑一遍真机（§6 清单最后一项）
5) 更新 docs/PHASE_STATUS.md（合入后的进度单一事实源）
```

**一个不要做**：不要在 main 上直接解前端冲突（§14.8：复杂业务冲突回 feature worktree 解）。

### 0.1 前端合并的**预期冲突面**（提前知道，别慌）

| 文件 | 本批（feat/frontend-ws6-ws7）动了 | feat/frontend 在途（U-2/U-3）动了 | 预期 |
| --- | --- | --- | --- |
| `web/src/styles/app.css` | 新增 hunk 在 ~1004（`.project-error` 选择器列表）/ ~1025 / ~1108+（WS-6/WS-7 样式块） | hunk 在 642 / 656（`rail-empty-btn`）/ 2843 / 2862（`.tl-run-header`、`.detail-tab-count`） | 不同区域，预计**干净合并** |
| `web/src/components/SessionList.tsx` | 项目行 kebab 首项、空项目占位区、新对话框挂载 | Rail **真空态**（`showEmpty` 分支）文案/按钮 | 不同区块，预计干净；若冲突，两边逻辑**都要保留** |
| 其余 | 新文件（`DirectoryBrowser` / `StartTaskInProjectDialog` / `useDirectoryListing` / 2 个 spec）+ `api.ts` / `types.ts` / `fixtures.ts` / `useSession.ts` / `App.tsx` | 未触碰（U 批次只动 UI 表现层） | 无冲突 |

---

## 1. 交付了什么

| Ticket | 端 | Commits | 内容 |
| --- | --- | --- | --- |
| #169 WS-6 | 后端 | `50e96a4`（文档）→ `561b553`（实现）→ 收口 `9c158c9` | `POST /api/sessions` 新增可选 `cwd`（与 `workspace` 互斥）；合法 `cwd` → 会话 root 与 `session/started.data.cwd` = realpath；自动注册项目（title = 目录末段名）+ 归组（幂等）；`POST /api/projects` 响应新增 `sessions_attached` 并补齐 cwd 匹配的既有会话（软删除 → 重注册闭环） |
| #169 WS-6 | 前端 | `f3849ac` → 收口 `51fc68c` | 项目行 kebab 第一项「在此项目中新建任务」+ 空项目占位区替换为该入口按钮；确认面（Radix Dialog）：路径明示行逐字 + 权限档三选（默认 workspace-write）+ 任务输入（空禁用）；提交复用 `submitTask` 同一条 SSE 接线（选中会话、跟随流），payload 带 `cwd`；失败留在确认面可重试（`submitTask` 新增 `{ ownError }`；`api.startSessionErrorDetail`） |
| #170 WS-7 | 后端 | `21c0b06` → 收口 `9c158c9` | 新模块 `src/agent_harness/web/host_dirs.py` + `GET /api/host/dirs`：`path` 缺省 → 盘符/根列表（可注入 `ROOTS_PROVIDER`）；给定 `path` → 一层直接子目录（仅目录、depth=1、按名排序、`parent` 供向上、盘根 `parent=null`）；错误矩阵 422/404/422/403 不冒 500；条目上限 500 + `truncated`；symlink 照列一个条目不展开 |
| #170 WS-7 | 前端 | `f3849ac` → 收口 `51fc68c` | `api.getHostDirs`（形状窄化 + `ProjectError` 保 detail 原文）+ `hooks/useDirectoryListing`（列目录状态机，请求代号作废迟到响应）+ `components/DirectoryBrowser`（路径条回车跳转 / 向上 / 一层子目录 / 「选择此目录」+ 回执 / 截断提示 / 403·404·422 就地显示 detail）+ 内嵌「新建项目」对话框 + 双向同步 |
| 收口 | 后端 | `9c158c9` | B-2 批次两轴审查 findings 的最小修复（跨平台绝对路径 / OSError 不冒 500 / 账本剪枝保命 / NUL / 文档一致性）+ 测试补强 + 变异验证 |
| 收口 | 前端 | `51fc68c` | 批次两轴审查 findings 的最小修复（导航后路径条"说谎" / 空串回车语义 / 回执残留 / 键盘焦点 / 死类）+ 6 条测试缺口补强 + mock 保真度修正（带 cwd 会话的 durable log = 刚流出的帧） |

后端变更文件（供 diff 复核）：
`src/agent_harness/sandbox/paths.py`（新 `is_absolute_path`）、
`src/agent_harness/session/{errors,projects,service}.py`、
`src/agent_harness/web/{app,domain_errors,projects,host_dirs}.py`、
`src/agent_harness/workspace/index.py`、
`tests/web/{test_web_session_cwd,test_host_dirs_api,test_domain_error_mapping}.py`、
`tests/workspace/test_workspace_index.py`、`tests/sandbox/test_paths.py`。

前端变更文件：`web/src/{App.tsx,types.ts}`、`web/src/lib/{api.ts,api.test.ts}`、
`web/src/hooks/{useSession.ts,useDirectoryListing.ts}`、
`web/src/components/{SessionList.tsx,ProjectDialogs.tsx,DirectoryBrowser.tsx,StartTaskInProjectDialog.tsx}`、
`web/src/styles/app.css`、`web/e2e/{fixtures.ts,u-project-task.spec.ts,v-dir-browser.spec.ts}`。

---

## 2. 门禁证据（两端都已实跑）

**后端**：

```bash
cd D:\intelligence-agent-backend
.venv/Scripts/python.exe -m ruff check src/ tests/      # All checks passed
.venv/Scripts/python.exe -m pytest -q                   # 2109 passed / 10 skipped / 42 deselected / 0 failed
```

**前端**（`--workers=2`；**必须用隔离端口跑，见下**）：

```bash
cd D:\intelligence-agent-frontend-ws6\web
npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build
# tsc ✅ · vitest 626 passed ✅ · oxlint 0 errors（38 warnings 全为既有）✅ · vite build ✅
# playwright：208 passed / 6 failed（+1 单视口偶发，见下）
```

**前端已知既有失败（非本批引入，不要当成回归）**：3 个用例 ×2 视口 ——
`g-visual-qa:82`（UI-03 时间线 run 分组头）、`p-earlier-window:32`（加载更早）、
`r-project-groups:295`（UI-05 真空态文案）。已在 pristine 基线（`git stash` 掉本批全部改动）
同一隔离端口复现；属 `feat/frontend` 在途的 U-2/U-3 工作。

**前端已登记偶发**：`k-refresh-restore:159`（SSE 时序类，同后端那条 `test_disconnect_…` 家族）。
它在一次全量里单视口失败，隔离复跑 **3/3 全绿（每次 12 passed）**；本批 diff 不触碰 refresh/reconnect 路径。

**后端已知既有 flaky（非本批引入）**：
`tests/test_web_api.py::test_disconnect_leaves_run_running_and_cancel_stops_it`
（SSE 断连时序竞争，5s 预算随机器负载偶发悬挂；已用 `git stash` 在 pristine HEAD 复现；OBS-9.3 与
`PHASE_STATUS` #152/#154 已三次登记）。它在本批最后一次全量中**通过**。

> **⚠️ 5173 复用坑（前端 e2e，务必知道）**：`web/playwright.config.ts` 是
> `5173 + reuseExistingServer: !CI`，它会把**任何**已监听 5173 的 dev server 当成自己的。
> 本机并行 worktree 有会话在跑时，e2e 会静默跑**别人的代码**（本批实测踩到：新增的菜单项"不存在"）。
> 本批证据用临时隔离端口配置产出（10 行：`baseURL` + `webServer.command = npm run dev -- --port 5273
> --strictPort` + `reuseExistingServer: false`），该配置**未入库**。集成方若发现 5173 被占用，
> 同一手法换端口再跑；反之若 5173 空着，直接用 §16.6 的原命令即可。

**真机证据**（真 uvicorn `feat/backend` + 真模型 `glm-4.5-air` + 真浏览器；`WORKSPACE_DIR` 指向隔离临时
目录，未触碰仓库真 `harness.db`；临时服务与目录已清理）：
- 后端 WS-6：`cwd=D:\_b2real\proj` 建会话 → 模型用 `read` 工具以**相对路径** `hello.txt` 读到真实文件并逐字复述
  （相对路径能成功 = cwd 真的换过去了）；`started.cwd=D:\_b2real\proj`；项目自动注册 `title=proj` 且会话归组；
  校验矩阵 6 条 detail 逐字一致；软删除 → 重注册 `sessions_attached=2`、幂等重放 `0`，目录与文件原样。
- 后端 WS-7：根模式返回真实 `C:\` / `D:\`（`path=null`、`parent=null`）；一层列举排除文件与嵌套、按名排序、
  `parent` 正确；501 个目录 → `truncated=true` 且 500 条（排序后前缀）；非绝对 422 / 不存在 404 / 是文件 422 /
  含 NUL 422 逐字一致；跨源 `Origin` → 403、`localhost` → 200。
- 前端 WS-6（经真实浏览器点完整链路）：kebab 第一项与空项目入口都点通；确认面逐字显示真实路径、默认档显示
  "工作区写入"；任务「用 read 工具以相对路径读取 hello.txt」→ 事件 `tool/call read {"path":"hello.txt"}` 成功
  并逐字复述 `REAL-MARKER-7731`；会话落在项目分组下；**全程无审批卡**（= 默认档确实没发 `permission_mode`）；
  把项目目录改名 → 提交 → 浮层内就地显示 `提交失败：目录不存在：D:\_ws6real_fe\demo-proj`（后端 422 原文、
  不弹全局横幅、不关对话框），目录改回后同一按钮**重试成功**并落组。
- 前端 WS-7：真盘符根列表（根模式两个按钮禁用）；`D:\` 一层 67 个真实子目录（仅目录、按名排序）；
  进入路径后**两个输入框同步回填**；手改输入框回车反向跳转；「选择此目录」回执 + 注册成功。

---

## 3. 后端 API 契约（前端消费的形状）

### 3.1 `POST /api/sessions`（新增 `cwd`）

```jsonc
{ "task": "…", "cwd": "D:\\repos\\my-project", "max_steps": 5 }   // workspace 与 cwd 互斥
```

- `workspace`（旧，单段目录名）与 `cwd`（新，**已存在**的绝对目录）**只能二选一** → 同时非空 422
  `workspace 与 cwd 只能二选一`。
- `cwd` 非绝对 → 422 `cwd 必须是绝对路径：'<原值>'`；不存在 → 422 `目录不存在：<规范路径>`（**不代创建**）；
  是文件 → 422 `不是目录：<规范路径>`；含 NUL → 422 `cwd 含非法字符（NUL）：'<原值>'`。
- 成功：SSE 流照旧（**注意 `session/started` 不在 create 的 SSE 流里**——它在订阅建立前已落盘；
  前端要拿 cwd 走 `GET /api/sessions/{id}/events`，这也是重连时的同一条路）。

### 3.2 `POST /api/projects` 响应新增字段

```jsonc
{ "id": "…", "path": "D:\\repos\\my-project", "title": "my-project", "status": "ok",
  "session_ids": ["…"], "created_at": "…", "updated_at": "…",
  "sessions_attached": 2 }   // 本次调用**新**归入的会话数（幂等重放 → 0）
```

注册（含幂等命中既有项目）后，所有 `header cwd == 项目路径` 的既有会话会被补进账本——
`DELETE /api/projects/{id}`（软删除）→ 重新注册即可恢复分组。

### 3.3 `GET /api/host/dirs`

```jsonc
// ?path 缺省 → 根模式
{ "path": null, "parent": null, "truncated": false,
  "entries": [ { "name": "C:\\", "path": "C:\\" }, { "name": "D:\\", "path": "D:\\" } ] }

// ?path=D:\repos → 一层直接子目录（仅目录；按 name 大小写不敏感排序；盘根 parent=null）
{ "path": "D:\\repos", "parent": "D:\\", "truncated": false,
  "entries": [ { "name": "alpha", "path": "D:\\repos\\alpha" } ] }
```

- 前端据 `path === null` 判定"当前在根"（据此禁用「向上」与「选择此目录」）。
- 条目 `path` 是**父目录 + 名字**拼出的链接本身（symlink 不展开；进入时后端按真实目标解析，仍是一层）。
- 错误 detail（**原样显示，不要翻译**）：422 `path 必须是绝对路径` / 404 `目录不存在：<规范路径>` /
  422 `不是目录：<规范路径>` / 403 `无权限访问：<规范路径>` / 422 `path 含非法字符（NUL）` / 422 `路径不可用：<规范路径>`。
- 超过 500 个子目录 → `truncated: true` + 截断后的前 500 条（排序前缀）→ **UI 必须显示"已截断"提示**。
- 闸：`require_trusted_origin`（与项目端点同一份）——本地信任模式下只接受本机 `Origin`。

---

## 4. 两轴审查的结论与处置

**后端（B-2，fixed point `80d49e1`）**：
- **Spec 轴**：`NEEDS-FIX` → 1×P1（跨平台绝对路径判定：三处都用 `PureWindowsPath(...).is_absolute()`，
  POSIX 上拒掉一切合法绝对路径）+ 5×P3（空白 `cwd` 语义、403 文案变更、`max_length` 造出矩阵外 list 形状
  detail、ADR 与 PRD 对条目 `path` 措辞冲突、两处测试假绿）。**全部已修 / 已文档化**。
- **Standards 轴**：`NEEDS-FIX` → 3×P2（`attach_matching_sessions` 剪枝会永久删掉 header 暂时读不到的成员 /
  `host_dirs` 只抓 `PermissionError` 其余 OSError 冒 500 / 根模式在事件循环上跑同步 I/O）+ 3×P3（NUL、
  `exists`/`isdir` 吞权限错误、测试缺口）。**全部已修**，其中账本剪枝一条有**变异验证**
  （改回旧行为 → 新锁 1 failed；源码 sha256 逐字节还原）。
- **有据不改**（审查方也认可）：`MAX_ENTRIES` 全量物化后才截断（截断契约要求"排序后的前缀"）；
  `PureWindowsPath` 在 Windows 侧的既有口径；`ROOTS_PROVIDER` 作为测试 seam。

**前端（B-2，fixed point `522602d`）**：两轴各一独立只读 subagent → **零 P0/P1**，5 条 P2 + 6 条测试缺口，
**全部处置**：
1. 路径条"说谎"（两轴各自独立发现）：导航只清一处本地态 → 条上写 A、下面列 B。修：唯一导航出口 `nav()`。
2. 条上回车空串无动作，但占位文案承诺「留空 = 盘符/根」→ 空串 = 列根（与表单侧同语义）。
3. 「选择此目录」回执在导航后仍挂着 → `nav` 清回执。
4. 键盘焦点在进入子目录后掉回 `<body>`（条目卸载）→ 列表/向上导航把焦点收进浏览器容器
   （`tabIndex=-1`，不卸载），路径条回车触发时不收焦点。
5. 死类 `project-dialog-task`（无 CSS / 无选择器引用）→ 删除（§9.3）。
6. 测试缺口：逐字文案改**连续串**断言、三档都在、AC11「选中 + 跟随流」、AC12 错误改 `toHaveText` 整串、
   WS-7 补浏览器自己路径条回车 + 条上打字后改走点子目录的回归锁 + 422 就地显示；并修正 mock 保真度：
   带 cwd 会话的 durable log（`GET /events`）= 刚流出的那些帧（此前回 `[]`，run 收尾后的回读会把流的结论
   清空 → "回答真的渲染出来了"这条断言测不到东西）。

---

## 5. 前端契约坑点（本批已按此实现；集成方用来**核对**是否被改坏）

1. **默认权限档必须不发 `permission_mode`**（后端语义：显式传非 DANGER 档 = 切**交互式审批**，
   每个工具调用都会弹审批卡）。实现：`StartTaskInProjectDialog` 里默认档 → `null` → `App.tsx` 的
   payload 不含该键 → `api.ts` 的字段表不发键。**e2e 与单测都锁了"缺省不发键"**，
   真机侧的证据是"跑了工具而没有弹审批卡"。
2. **确认面的路径明示必须逐字**：`Agent 将直接读写该目录：<项目规范路径>`（#169 AC10）。e2e 用
   **连续串**断言（拆开断言会让"路径被挪到别处"也通过）。
3. **目录浏览器不要试图取浏览器的真实绝对路径**：`<input webkitdirectory>` 只给 fakepath、
   `showDirectoryPicker()` 句柄没有路径——只能走 `GET /api/host/dirs` 自绘（ADR-0028 Context）。
4. **错误留在原地**：#169 AC12 要求 422 留在确认面可重试；#170 AC9 要求 403/404/422 用后端
   `detail` **原文**（不翻译、不改写）。实现上：确认面错误 = `.project-error`，
   浏览器错误 = `.dir-browser-error`（**两个 class 刻意分开**——共用会让 `.project-dialog .project-error`
   这类既有选择器同时命中两个盒子，也让用户分不清哪条错误属于哪一步）。
5. **项目 `status=missing-dir` 时入口照常出现**，点击后由后端 422 明示（前端不预判）。
6. **手填路径保留为完整后备**：浏览器点选/跳转 → 回填路径输入框；手改输入框回车 → 浏览器跳转。
   （本批把路径输入框的回车从"提交注册"改成"在下方浏览该目录"——先看见目录里有什么再注册；
   注册由「注册项目」按钮明确触发。既有 e2e 用按钮提交，不受影响。）
7. **e2e 用状态 mock**（先例 `e2e/r-project-groups.spec.ts`）：`/api/host/dirs` 有可编程假目录树
   （`ApiMock.hostDirs` / `hostDirsErrors`），带 cwd 建会话的 mock 按真后端语义**真的**改账本与行归属
   （`ApiMock.cwdSessionError` 用来伪造 422 并验证"可重试"）。
8. 前端门禁（§16.6）：
   `cd web && npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build`。

---

## 6. 合入后的验证清单（集成侧）

- [ ] `git diff main...feat/backend` 复核：只含 §1 后端文件 + `docs/`；无 `.env` / secrets / 未相关清理。
- [ ] `git diff main...feat/frontend-ws6-ws7` 复核：只含 §1 前端文件；无临时脚本（隔离端口配置**未入库**）。
- [ ] 本地 `main` 合并后：`ruff check src/ tests/` + 全量 `pytest` → 0 failed（忽略 §2 的既有 flaky）。
- [ ] 前端门禁在 `main` 上重跑一遍（若 5173 被占用，按 §2 的隔离端口手法）。
- [ ] 启动完整项目（真 `.env`）跑一遍真机：① 「新建项目」用目录浏览器点选一个真实目录注册成功；
      ② 项目行「在此项目中新建任务」→ 确认面路径明示 → 任务落到项目真实目录（会话内 `read` 一个
      **只有该目录才有**的相对路径文件）；③ 把该目录改名后重试一次，确认错误留在确认面（AC12）。
- [ ] 两张 issue（#169 / #170）已关；关单 comment 里写的分支/commit 与最终合入的**一致**。
- [ ] 更新 `docs/PHASE_STATUS.md`（合入 `main` 后的进度单一事实源）。

## 7. 未决 / 仅报告（不在本批修）

- 前端目录浏览器：路径条输入不存在的路径报错后，条上回退到原目录（用户输入不保留）；上面表单的
  路径输入框保留原文，主要动作不受影响（组件头注释已说明）。要"保留输入"需要 post-render 的输入态管理，
  判定为超出本票最小改动预算。
- 真机侧没有自然构造 `GET /api/host/dirs` 的 `403`（Windows 需要 ACL 拒绝目录，会改系统状态）；
  该渲染由 e2e 的 `hostDirsErrors` 拦截口覆盖（伪造的是真后端会回的那句话），后端 403 矩阵已 curl 逐条验过。
- `GET /api/host/dirs` 的暴露面 = "这台机器有哪些目录"，与"本地信任模式下 UI 本就可注册任意目录"
  同阶；**若后端不在用户本机部署，本端点必须随部署形态重估**（ADR-0028 Consequences 已记）。
- 存量 `workspaces_root/<uuid>` 会话**不迁移**（ADR-0027 D4）：它们继续 Ungrouped，用户可用既有的
  「加入项目…」手动归组。
- 既有 CORS `*` 漏洞（#154 已列为独立 ticket 候选）与本批的来源闸是两套机制，本批未动。
- 前端 e2e 夹具里共享的 `PERMISSION_MODES`（`auto`/`ask`/`deny`）与真后端三档
  （`read-only`/`workspace-write`/`danger-full-access`）**不一致**（既有漂移，被 control-row 等 spec 使用）。
  本批新 spec 自带真三档、不动旧夹具（§8 Scope Lock）；建议另立小票统一。
