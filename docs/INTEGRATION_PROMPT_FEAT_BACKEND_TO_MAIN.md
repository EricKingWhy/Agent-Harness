# 集成提示词 · feat/backend → main（2026-09-13）

> 收件人：`D:\intelligence-agent`（本地 main）的**集成 AI**。
> 发起人：`D:\intelligence-agent-backend`（feat/backend）。**本分支已就绪，等我方通知前不要碰 feat/frontend。**
> 规则依据：AGENTS.md §14（Git Workflow / Merge Safety）、§13.3（最终合并在 `D:\intelligence-agent` 的 main）。

---

## 1. 要做什么（一句话）

把 `feat/backend` 合进**本地 `main`**。**只合这一条**；`feat/frontend` 现在别动——我正在 frontend worktree 修 3 条 P1（清单见 `docs/INTEGRATION_PROMPT_FRONTEND_FIXES_ROUND11.md`），改完会通知你。

`git push` **不在本次范围**（§14.4：push 要用户明确批准）。

## 2. 现状事实（我实测的，别凭目录名猜）

| 项 | 值 |
| --- | --- |
| 本分支 | `feat/backend`，HEAD `7c3bc12`（6 ahead / 31 behind） |
| 远端基线 | `origin/main` = `b28e856` |
| merge-base | `a126378`（`docs(integration): 联合集成提示词——UI Polish 六票 + WS-6/WS-7 两端合并路由`） |
| 本分支新增/改动 | 26 个文件（后端 `src/agent_harness/**` + 测试 + 文档/ADR） |
| main 侧改动 | 67 个文件，其中 `web/` **54 个文件 +7890 行**（UI Polish / WS-6 / WS-7 那一批） |
| **两侧都改过的文件** | **只有 2 个**：`docs/PHASE_STATUS.md`、`docs/FRONTEND_ISSUES_LOG.md` |

> ⚠️ **别被旧 ref 骗了**：实测 `D:\intelligence-agent-frontend` 那个 clone 里
> `origin/main` 还停在 `593dcda`（比真实远端落后 1 个 commit），因为它**没有 fetch**。
> GitHub 上的 main 已经是 `b28e856`。在任何"main 有多少、差哪些"的判断之前，
> 先 `git fetch origin --prune`，否则你会在一个过期的基线上做冲突分析。

本分支领先 `origin/main` 的 commit（新→旧，**含本文档自身那个 commit**——它的 sha 在写这段时还不存在，
用 `git log --oneline origin/main..feat/backend` 取最新的那个）：

```
<最新>  docs(integration): feat/backend → main 集成提示词（本文档）
7c3bc12 docs(phase-status): 第十一轮真机验收 + API-01/02 修复进度记录
fa91207 docs(integration): 第十一轮前端修复提示词（3×P1 + 8×P2 可执行工单）
164fbc2 fix(API-01/02): 路径类 4xx 文案统一为策展中文（注册项目 ↔ 目录浏览逐字一致）
c6426395 docs(frontend): 第十一轮真机验收——#172 硬删全链路通过 + 刷新一致性逐字节一致 + 3 条发现
92135a5 docs(#172): PHASE_STATUS 记录 + 给集成/前端的会话硬删提示词
4109b08 feat(#172): 会话硬删后端半 DELETE /api/sessions/{id}（ADR-0029）
```

（上表 `ahead/behind` 的计数按本文档提交前测得；实际以 `git rev-list --left-right --count origin/main...feat/backend` 为准。）

### 为什么后端必须先合（这条别反过来）

实测：`origin/main` **既没有** `DELETE /api/sessions/{id}` 端点，**也没有**前端的会话删除对话框（`git grep -l 永久删除 origin/main -- web/src` 零命中）。两边现在自洽。

- 先合后端 → main 只是多一个暂时没人调的新 API，自洽不破。
- 先合前端 → main 上会出现一个**点了必定 404** 的删除按钮。

## 3. 逐文件冲突处理指引（§14.7：不要机械 ours/theirs）

### 3.1 `docs/PHASE_STATUS.md`
两侧都是**追加式进度列表**（单一事实源）。**两侧条目全部保留**，按日期顺序排列。不要为了消冲突丢掉任何一轮记录。

### 3.2 `docs/FRONTEND_ISSUES_LOG.md` —— **已知分叉，需重新编号**
两侧各自维护过这份登记簿（SID-04 已记录）：back 侧 1897+ 行、front 侧约 1780 行，**两侧都有"第九/十/十一轮"但指向不同内容**。合并要求：

1. 两侧各轮**按时间顺序全部保留**（append-only 日志不允许丢轮）；
2. 冲突处**重新编号**并标注来源，例如前端侧那一轮改标成「第十一轮（前端侧）」；
3. 合并后在这份文件顶部留一行说明"本轮已完成两侧轮次归并"，避免后来人再分叉。

### 3.3 如果出现**第 3 个**冲突文件
先例之外的冲突说明我的测量过期了或 main 又前进了。按 §14.8：**`git merge --abort`**，然后回来告诉我，不要临场拼接业务逻辑。

## 4. 建议的执行序列（§14.5 / §14.6）

1. **先只读核对**（§14.2）：`git -C D:\intelligence-agent worktree list --porcelain`、`git status`、`git branch --show-current`。确认本地 main 干净、且是否需要先 `git merge origin/main` 让本地 main 追上远端。
2. 在 `D:\intelligence-agent` 执行 `git fetch origin --prune`（**不要用 `git pull`**）。
3. `git merge feat/backend`。
4. 只按 §3 的指引解那 2 个文档冲突（append-only，两侧都留）。
5. 冲突全部解决后 `git add` 冲突文件 → 完成 merge commit。
6. 跑 §5 门禁 → 按 §6 报告。

> 这 2 个冲突面都是**纯文档追加**，且指引逐文件给到了，所以在 main 上解是可接受的（§14.6 反对的是在 main 上解**业务**冲突）。
> 若你想严格走"先回后正"（在 `feat/backend` 里先吸收 `origin/main`），**先告诉我**——因为我现在可能正在这个 worktree 里跑命令（§13.1.3：并行会话不共用 worktree）。

## 5. 门禁（合之前 + 合之后都要）

### 5.1 合之前
```bash
git status                     # working tree 干净
git diff --check               # 无 whitespace / conflict-marker 问题
uv run ruff check src/ tests/  # 必须 All checks passed
uv run pytest -q               # 期望 2130 passed / 10 skipped
```

**这里有个坑，必须先处理**：如果验收后端还占着 `:8000`，它持有
`D:\intelligence-agent-backend\.agent\workspace\.instance.lock`，会让
`tests/observability/test_flush_lifecycle.py` 报
「另一个进程已在写同一个 session root，启动被拒绝」——那是**环境冲突，不是回归**。
先停掉占用者再跑：

```bash
PID=$(netstat -ano | grep LISTENING | grep ":8000" | head -1 | awk '{print $NF}'); taskkill //F //PID $PID
```
（我这边已经把 `:8000` 起在 feat/backend 上做验收，跑完门禁如需继续验收请重启它。）

### 5.2 合之后（在 main 上）
```bash
curl -s http://127.0.0.1:8000/api/capabilities   # 期望 count=3: websearch + multiagent + memory
```

`DELETE /api/sessions/{id}` 的探活（**用一个不存在的 id**，期望 404，**不要**拿真实会话试）：
```bash
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE \
  http://127.0.0.1:8000/api/sessions/does-not-exist -H "Origin: http://127.0.0.1:5173"
```
若返回 405 或 404-且-body 是 "Not Found"（无路由），说明端点没合进来。

本次**不需要**跑前端门禁——`web/` 本次一个字节都不改。

## 6. 完成后请报告

1. merge commit 的 sha；
2. 2 个冲突文件**各自是怎么解的**（哪几条轮次保留、有没有重新编号）；
3. 门禁原始输出结论（ruff / pytest 的 passed 数）；
4. §5.2 两条探活的实测结果；
5. 有没有出现 §3.3 说的第 3 个冲突文件。

## 7. 明确禁止（§14.4 / §8）

- ❌ `git push`（`feat/backend`、`main`、任何分支都不推）——等用户明确批准。
- ❌ 合 `feat/frontend`（我正在改，改了会合进半成品）。
- ❌ 用 backend 分支的 `web/` 覆盖任何东西：它比 main 还旧（少 7890 行），比 `feat/frontend` 更旧（缺 `57dd028` 的删除对话框）。**一个字节都不要从这里取前端。**
- ❌ 碰 `.agent/`（真实验收语料：32 个会话 / 2 个项目；其中 `7c681c45`、`7b387279`、`b2dc4504` 是 fork 父会话，`c7fb4d04`、`7cf291d1`、`008aa427` 是委派父会话——都别删）。
- ❌ 顺手重构、清无关代码、扩大范围（§8 Scope Lock）。有疑问先报告。

## 8. 后续（等我通知）

我修完前端那批（`docs/INTEGRATION_PROMPT_FRONTEND_FIXES_ROUND11.md`：3×P1 = Artifacts 页签恒空 / 「默认链」不发请求 / 重启后审批卡残留，8×P2）并跑过前端门禁后通知你。那时按 §14.9 **一次只合一条**，对**新的 main** 重新 `fetch` / `diff` / `merge-base` 分析 `feat/frontend`，跑满前端门禁再合：

```bash
cd web && npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build
```

另有一项**需要 Primary Developer 定案**的事，不在本次合并范围：spec `03_SESSION_EVENT_MODEL.md` §3 事件表与实现已大面积不一致（spec 有实现没有 8 个、实现有 spec 没有 21 个）。已开 **issue #173**（母票）+ **#174–#178**（T1–T5 子票），其中 T5 有一条需主开发者裁决的分叉（spec 是否允许机器解析）。本次合并**不需要**处理这些 issue。
