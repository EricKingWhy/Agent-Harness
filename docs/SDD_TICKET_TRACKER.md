# SDD Ticket Tracker

> **持久化活文档** — 跨 context window 追踪 SDD 循环进度。
> 每次进入新 context window 时，先读本文件恢复状态。

---

## 流程切换 + 批次记录（v2 批量审查循环）

> **自愈条款**：不确定当前在循环哪一步 / 不记得 fixed point 或批次边界 / 上下文刚被压缩过
> → **第一动作**：重读 `docs/SDD_WORKFLOW_PROTOCOL.md` + 本文件，禁止凭记忆猜流程继续施工。

| 项 | 值 |
| --- | --- |
| 协议版本 | `docs/SDD_WORKFLOW_PROTOCOL.md` **v2**（批量审查循环） |
| 切换日期 | 2026-09-12 |
| 切换生效 commit | `4a9f2dc`（切换时点）→ 旧循环遗留的 #158 于 `28c35e7` 收尾；首批批量审查 fixed point = **`28c35e7`** |
| 旧循环已完成票据 | 一律承认有效，**不补审、不重跑**（旧版每票 review 视为已覆盖） |
| 切换时的在途票据 | #158（MEM-3）：按旧规则把当前一步收尾（修复 + 测试全绿 + commit），落盘后即切 v2，**不为它开新 review** |

### 批次台账

| 批次 | 本批 tickets | fixed point（累计 diff 起点） | 审查结论 | 修复 commit（下一批 fixed point） |
| --- | --- | --- | --- | --- |
| B-1 | 待定（下一票 = #160 MEM-5 前端记忆管理 UI） | **`28c35e7`**（#158 收尾 commit——切换时的在途票据，其旧版两轴 review 已完成并修复，**不计入本批审查范围**；本批从 `28c35e7` 之后的新 ticket 起算） | 未审 | — |
| B-2 | **#169 WS-6 后端半 + #170 WS-7 后端半**（同一张 PRD/ADR 的两个端点，依赖链自然收批） | **`80d49e1`**（merge main → feat/backend，本批第一行代码之前） | **已审**：Spec 轴 `NEEDS-FIX`（1×P1 + 5×P3）+ Standards 轴 `NEEDS-FIX`（3×P2 + 3×P3）→ 全部处置（修 / 文档化 / 有据不改） | **`9c158c9`**（下一批 fixed point） |

**批次边界规则（v2 §1.2）**：每攒满 2–3 个 ticket（或遇到依赖链断点）即收批；收批时对
`git diff <fixed point>..HEAD` 跑一次两轴 `/code-review`（Standards + Spec，两个独立只读子代理）。

#### B-2 交付与审查记录（2026-09-12，后端 worktree）

| 项 | 值 |
| --- | --- |
| Tickets | #169（WS-6 会话 `cwd` 契约 + 自动入组 / `sessions_attached`）、#170（WS-7 `GET /api/host/dirs` 只读目录列举）——**跨端票，只做完后端半，均未关单** |
| Commits | `50e96a4`（ADR-0027/0028 + PRD + CONTEXT 正名）、`561b553`（WS-6）、`21c0b06`（WS-7）、`9c158c9`（B-2 审查收口） |
| 门禁 | ruff **clean**；全量 pytest **2109 passed / 10 skipped / 42 deselected / 0 failed** |
| 真机 | 真 uvicorn（隔离 `WORKSPACE_DIR`，未触碰真 `harness.db`）：WS-6 cwd=真实目录 → `read` 工具以**相对路径**读到真实文件并逐字复述；校验矩阵 4+2 条 detail 逐字一致；软删除→重注册 `sessions_attached=2`、幂等重放 0、目录/文件原样。WS-7 根模式真实盘符、一层列举（无文件/无嵌套/排序）、501→500+truncated、3 条错误 + NUL、跨源 403 / localhost 200 |
| Spec 轴 findings | **P1** 三处形态闸用 `PureWindowsPath(...).is_absolute()` → POSIX 上拒掉一切合法绝对路径（#170 AC1 明文要求 POSIX）→ 抽 `is_absolute_path` 平台分支并共用。**P3** 空白 `cwd` 语义自相矛盾 / 矩阵外分支未登记 → PRD 补记 + 测试钉住；403 文案静默变更 → PRD 记明；`max_length` 造出矩阵外 list 形状 detail → 去掉；ADR-0028 D1 与 PRD 对条目 `path` 措辞冲突 → 改 ADR；`started.cwd` 的 realpath 断言与 symlink 条目 `path` 断言属**假绿** → 补强 |
| Standards 轴 findings | **P2** `attach_matching_sessions` 用过滤视图重写账本会**永久**删掉 header 暂时读不到的成员（会话静默变 Ungrouped）→ 改为"读到且不匹配才剪，读不到保留"+ 回归锁 + 变异验证（改回旧行为 → 1 failed，sha256 还原）。**P2** host_dirs 只抓 `PermissionError` → 其余 OSError（TOCTOU/断连盘）冒 500 → `os.stat` + errno 分派。**P2** 根模式在事件循环上跑同步 I/O（3.11 fallback 26 次 `exists`）→ 同样卸载 worker。**P3** NUL 未拒（POSIX 上 `realpath` 抛 `ValueError` → 500）→ 两处补闸；`exists`/`isdir` 吞权限错误 → 改 `os.stat`；测试缺口（N>1 归入、边界截断、NUL）→ 补 |
| 有据不改（已记录理由） | ① `MAX_ENTRIES` 全量物化后才截断：截断契约本身要求"排序后的前缀"，改 `scandir` 早停会破坏确定性；要限内存只能改契约（分页），收益不抵代价。② `PureWindowsPath` 判 `C:\x`：Windows 侧与既有口径一致，单方收紧会造两套形态语义。③ `ROOTS_PROVIDER` 模块级可替换 seam：可接受的测试 seam，不引入 DI 容器 |
| 残留 / 交接 | 前端半（#169 AC9–AC14、#170 AC8–AC13）未做 → 两票**保持 OPEN**；下一批 fixed point = `9c158c9`；集成提示词 `docs/INTEGRATION_PROMPT_WS6_WS7_DIR_ROOTED_SESSION.md` |

## 当前状态

| 项 | 值 |
| --- | --- |
| Worktree | `D:\intelligence-agent-frontend` |
| Branch | `feat/frontend` |
| 协议版本 | `docs/SDD_WORKFLOW_PROTOCOL.md` **v2**（批量审查循环；v1 的「每票一次 /code-review」已作废） |
| 后端交接手册 | 本轮：`D:\intelligence-agent-backend\docs\HANDOFF_FRONTEND_RECOVER_FORK_SCROLL.md`（A/B/C/D） |
| 集成交接提示词 | 本轮：`docs/integration/FRONTEND_SESSION_HARD_DELETE_INTEGRATION_PROMPT.md`（#172 前端半，**集成 AI 的唯一入口**，§0 是可执行摘要）；上一批（**已入 main `593dcda`**）：`docs/integration/FRONTEND_REFRESH_PERSIST_INTEGRATION_PROMPT.md` |
| 本批交接手册 | `docs/HANDOFF_APPROVAL_CARD_COVERAGE.md`（做了什么 + 8 个坑点 + 未决项 + 复核命令） |
| 下一批提示词 | `docs/PROMPT_FRONTEND_NEXT_BATCH.md`（可直接复制给前端 Agent：OBS-015 修复为主） |

**禁止推送远程**（AGENTS.md §13.2/§14.4）：本地 commit 已完成，push 归集成 AI。

---

## 集成回执核验（2026-09-13，前端 worktree）

收到 `D:\intelligence-agent\docs\INTEGRATION_REPORT_WS6_WS7_UI_POLISH.md`（Integrator 回执）。前端侧核验结果：

| 项 | 结论 |
| --- | --- |
| 合入确认 | UI Polish 六票 + WS-6/WS-7 前端半（B-2）已全部进 `origin/main` = `593dcda`；本分支已 `git merge origin/main --ff-only` 同步（领先/落后均 0） |
| tracker 终态 | main 上 U-1/U-2/U-3/B-2 四行齐备 + B-2 整节——按回执 §5.2 **不再动它** |
| 门禁复跑（前端 worktree，同步后的树上实跑） | tsc 0 · vitest **628 passed**（35 文件；首轮 1 例假红复跑消失，两轮全绿）· oxlint 38w/0e · playwright **216 passed**（`--workers=2`；一次 215→复跑 216，与回执数字一致）· vite build ✓ |
| 回执 §5.4 答案落地 | **审批倒计时不做**：`tool/approval-requested` 无超时字段，硬编码 300s 违反不变量 #22 + 用户决策 D4 → UIP-DEFER 关闭（回执已记录）；「渲染超时拒绝 reason」为加性小改进，待立票 |
| 本 worktree 下批工作项（待产品/用户拍板后立票） | ① §4.1 permission_mode 语义 gap（改档只影响新会话）——等产品决策加端点还是 UI 提示；② 渲染「审批超时按 fail-closed 拒绝」的 `permission/resolved` reason（加性零契约变更）；③ 回执 §5.5 的 5173 复用坑继续有效：跑 playwright 前确认 5173 是哪个 worktree 的 dev server |

---

## 第十三轮（2026-09-13）：会话硬删 #172 前端半（跨端票的前端半）

**本批 commit**：`57dd028`（`feat/frontend`；父 `11ff129` = 本批 fixed point）。
**前置**：后端半在 `feat/backend`（`4109b08` + docs `92135a5`），**尚未入 `main`**。本半按用户
2026-09-13 的分工（「你先做你的，做完了我再让前端 ai 动手，这样就不会冲突」）动手；两端串行，
合并顺序见本轮集成提示词 §2（**后端半先进 `main`，再合前端半**，§14.9 一次一支）。

**背景**：后端给了 `DELETE /api/sessions/{id}`（硬删，无墓碑 / 无回收站），界面上却没有任何入口。
ADR-0029 的 Consequences 逐字写着「误删不可逆，且没有任何技术兜底。风险全部由**入口层**的显式
确认承担」——所以本票的实质不是"能删掉"，而是"删之前说清、删之后收敛干净"。

| 交付 | 位置 |
| --- | --- |
| 契约层：`SessionDeleted`（`deleted: true` 字面量）+ `deleteSession` + `SessionError(status)` + `describeSessionError` | `src/types.ts` / `src/lib/api.ts` |
| 回执文案纯函数（`events` 缺数时不报数） | `src/lib/sessionDelete.ts`（+4 例） |
| 收敛：`removeSession`（成功 / 404 → 重拉 + 必要时 `selectSession(null)`；409 → 列表原样） | `src/hooks/useSession.ts` |
| 入口：会话行 kebab 末尾「删除会话…」（两分支共用；**不**对 live 行禁用——忙不忙只有后端知道） | `src/components/SessionList.tsx` |
| 确认面：不可恢复措辞 + 会话标识（标题 + id 片段）+ 回执留在浮层 | `src/components/DeleteSessionDialog.tsx` |
| 样式：复用 `.project-dialog` 家族 + 身份块 3 条规则（零新 token，§15 不触发） | `src/styles/app.css` |
| 单测 +11（状态码映射 / 回执透传 / 404 不归 `NotFoundError` / 回执文案 4 分支） | `src/lib/api.test.ts` / `src/lib/sessionDelete.test.ts` |
| e2e +8（4 用例 × 2 视口） | `e2e/w-session-delete.spec.ts` + `e2e/fixtures.ts`（**有状态** DELETE mock） |

**门禁（实跑）**：tsc 0 · vitest **639 passed**（36 文件；+11）· oxlint **38w/0e**（基线未动）·
playwright **224 passed**（`--workers=2`；+8）· vite build ✓。

**两轴 review（双 Explore subagent）**：Spec 轴 **0 P1/P2** + 4×P3；Standards 轴 **0 P1/P2** + 7×P3。
第二轮 delta 复核：4 项修复全部 VERIFIED、3 项 decline 全部 SAFE。处置：

| # | 轴 | finding | 处置 |
| --- | --- | --- | --- |
| 1 | S | mock 注释声称后端「日志为空也是 404」但代码没实现（mock 与真机语义相反是本仓明确的缺陷类） | 修：`events === 0` 早返回 404 且**什么都不删**（对齐 `service.py` 守卫②） |
| 2 | S | 强制 404 分支只摘会话行、不摘项目账本 → rail 会渲染一条「n 条会话日志缺失」的**假缺失** | 修：抽出 `detachFromLedgers`，成功与 404 两分支共用 |
| 3 | S | `events` 缺失（0）时回执会写「已删除 0 条事件记录」——一句可能为假的话，还与「不可恢复」同句 | 修：0 当「回执没给数」→ 不报数；+2 断言（0×0 与 0×2 两形态） |
| 4 | S | `.mono` 在本仓**没有独立规则**（只有 `.project-input.mono`），挂在元素上是空类名 | 修：`.project-dialog-target-id` 直接写 `font-family: var(--font-mono)`（token 只在暗色 `:root` 定义、亮色不重定义字体 → §15 不触发） |
| 5 | S | e2e 注释把回执断言说过头（mock 两处同源，区分不了「读响应」与「偷读行」） | 修注释：写明真实保证链（`DeleteSessionTarget` 不含事件数 + `api.test.ts` 透传断言） |
| 6 | B | 404 也触发收敛，而票面只要求「成功后的收敛」 | **有据不改**：404 = 本地这行已过期（后端刻意不伪装成"又删了一次"），不收敛会让用户对着幽灵行反复重试；且 404 绝不显示成功回执 |
| 7 | B | `detached_from_projects === 0` 写成「它不在任何项目里」而非字面「从 0 个项目解除」 | **有据不改**：信息未丢，字面写法反而像故障腔；单测钉住这个刻意选择 |
| 8 | B | `refreshSessions` 无代际守卫（慢的旧 GET 可能把删掉的行带回来） | **有据不改**：既有属性、窗口窄，本次未触碰该函数（§8 Scope Lock：只登记不顺手修） |

**变异验证**（逐条断→红→还原→绿，`grep -c MUTATION` = 0）：回执 `deleted` 改读 body → 单测 1 红；
回执 `detached=0` 分支拆除 → 1 红；`events=0` 报数 → 1 红；成功不收敛 / 404 不收敛 / 无条件清视图
→ e2e 各 1 红（且 409 用例保持绿）；错误文案换成自编句 → 409 与 404 两用例红；不可恢复措辞与
按钮名拆除 → 4 用例红。

**关单**：#172 **不关**（跨端票只完成前端半，§14.12）。**未 push、未 merge**（集成 AI 执行）。

#### 关单补记（2026-09-13，用户明确许可）：#172 **已关**

上一行「不关」是写它当时的处置（前端半刚完成、两端都还没入 `main`）。两端齐备后按 §14.12 + 用户
「同步 → 重跑门禁 → 通过就关」的许可关单，**核实过实际状态**（非凭进度文档）：

| 项 | 事实 |
| --- | --- |
| 后端半入 main | `4109b08` / `92135a5` ← `d6c5fff merge: feat/backend → main` |
| 前端半入 main | `57dd028` / `5d56038` ← `f6c9d65 merge(frontend): 第十一轮 …（含 #172 前端半）→ main` |
| 前端内容核对 | 逐文件比对：`sessionDelete.ts` / `sessionDelete.test.ts` / `useSession.ts` / 集成提示词**逐字未改**；其余文件差异全是纯新增（0 删除）；关键标记（`onDeleteSession` 接线 / `删除会话…` / `不可恢复` + `永久删除（不可恢复）` / `convergeAfterDelete` / `sessionDeletedMessage`）逐个在 `main` 上 grep 到 |
| 真机验收 | `c6426395`：「#172 硬删全链路通过」——DELETE 200 精确回执、列表/对话区/Inspector/localStorage 全收敛、三路径+四表清空、审计只带 id 与计数、刷新前后 body 哈希一致 |
| 同轮发现的 2 条入口问题 | `8e8f0ab` 修复 + 补回归锁：SID-01 窄视口 ≤820px 删除入口 **`display:none` 不可达**（同规则还误伤行上绿点）；SID-02 确认面初焦落在「关闭(X)」→ 改落「取消」。两者已由 `w-session-delete.spec.ts` 新增 2 例覆盖 |
| 本次在合并后的树上实跑门禁 | 先 `git merge origin/main`（**零冲突**）→ HEAD `1d6f481`；合并后 `web/**` 与 `origin/main` 逐字一致（唯一差异是并行会话未推送的 `web/PRODUCT.md`）。tsc 0 · vitest **659 passed** · oxlint 41w/0e（**本票链路文件零警告**；38→41 的增量来自同期并入的其他工作）· `w-session-delete` **12 passed**（6 例 × 2 视口）· vite build ✓ |
| 关单 | `gh issue close 172 --reason completed`（CLOSED 2026-09-13T16:02:58Z，附完整证据 comment） |

**本轮学到的运维坑（值得写下来，别只留在报告里）**：跑 e2e 前 5173 上同时挂着**两个** vite——
`127.0.0.1:5173` 是本 worktree 的、`[::1]:5173` 是 **main worktree** 的（`netstat` 里是两行，
很容易只看到一行就以为"只有一个、是本树的"）。Playwright 探的是 `http://localhost:5173`，
Windows 上优先解析 IPv6 → `reuseExistingServer` 会**静默复用 main 的 server**，跑出来的绿是
**别人的树**的绿。判据：两个都清掉，让 playwright 的 webServer 自己从本 worktree 起。

**登记未做（留给各自的票）**：Memory/Artifact 不级联（ADR-0029 D6）；`resume_and_launch` 改写
cwd 会话映射的坑（ADR-0029 D2 记录未修）；`refreshSessions` 无代际守卫；会话域 409/404 detail
仍为英文（既有房风格，本票按票面"原样展示"）。#171（归档）是另一刀。

**未 push**：本次只做本地 `merge` + 门禁 + 关单 comment；`feat/frontend` → `main` 的 push 归集成 AI
（注意本分支上还压着一个并行会话未推送的 `4fd7e41 docs(panel)`）。

---

## ⚠️ 流程切换 + 批次记录（v2 批量审查循环，2026-09-12）

**自愈条款（先读这段）**：任何时候你发现自己（a）不确定当前在循环哪一步，（b）不记得批量审查的
fixed point 或批次边界，（c）上下文刚被压缩 / 摘要过 —— **第一动作 = 立即重读
`docs/SDD_WORKFLOW_PROTOCOL.md` + 本文件恢复状态；禁止凭记忆猜测流程继续施工。**

| 项 | 值 |
| --- | --- |
| 协议版本 | `docs/SDD_WORKFLOW_PROTOCOL.md` **v2**（本 worktree 已同步为 v2；v1 作废） |
| 切换日期 | 2026-09-12（切换动作发生在后端 worktree；v2 协议文件随本批同步到本 worktree） |
| 本 worktree 的批次起点 | `637bc89`（`feat/frontend` HEAD）= **B-1 的 fixed point** |
| 过渡条款 | 该点之前已完成并 commit 的前端批次**一律承认有效**（旧循环的每票 / 每批 review 视为已覆盖），不补审、不重跑 |

### 批次台账

| 批次 | 本批 tickets | fixed point | 审查结论 | 修复 commit |
| --- | --- | --- | --- | --- |
| B-1 | #160（MEM-5 前端半） | `637bc89` | 两轴各一 subagent；Spec 6 + Standards 7 findings → 9 修 / 2 说明不改 / 1 只登记（详见第十二轮「批次审查」） | `45227dc` |
| **U-1** | **UI-01（P0 审批卡重塑）+ UI-02（P1 排版地板+对比度）** | **`cd107a2`**（批次 0 文档 commit） | Spec 10 + Standards 14 findings → 全部处置（2 P1 修 + 3 P2 修 + 9 P3 修 + 8 说明不改/登记，见下方处置表） | `236049f` |
| **U-2** | **UI-03（Inspector run 分组）+ UI-04（信任裂缝）+ UI-05（Rail 空态）** | **`236049f`**（U-1 修复 commit） | Spec 3P1/3P2/3P3 + Standards 1P1/5P2/6P3 → 全部处置（含 **Rules of Hooks 崩溃**、空态自相矛盾、交错 run 序数、断言假绿） | `e543ae1` |
| **U-3** | **UI-06（minor 打磨）+ 收尾（删临时脚本 / 集成提示词）** | **`e543ae1`**（U-2 修复 commit） | 4 项处置（e2e 真实渲染断言升级 + 2 处变异红→绿） | 本批尾 commit |
| **B-2** | **#169（WS-6 前端半：项目内新建任务 / cwd）+ #170（WS-7 前端半：新建项目内嵌目录浏览器）** | **`522602d`**（= 本分支 base。注意它**正是 U-2 的功能 commit**，U-2 的审查修复还没落在它上面——见 §B-2 的集成顺序） | 两轴各一 subagent；**零 P0/P1**，5 条 P2 + 6 条测试缺口 → 全部处置 | `51fc68c` |
| **W-1** | **#172（会话硬删前端半：不可逆确认 + 删除后收敛）** | **`11ff129`**（集成回执核验 commit） | 两轴各一 subagent；**零 P0/P1/P2**（Spec 4×P3 + Standards 7×P3）→ 修 4 / 有据不改 3；第二轮 delta 复核 4 项修复全 VERIFIED、3 项 decline 全 SAFE | **`57dd028`**（本批） |

### B-2：WS-6/WS-7 前端半（#169 / #170，隔离 worktree）

**为什么是隔离 worktree**：`D:\intelligence-agent-frontend` 当时有并行会话在编辑（10 个文件 2–4 分钟前刚改过，
另有未跟踪审计脚本）。按 `AGENTS.md` §13.1「并行 AI 会话不能使用同一个 Worktree」+ §11「修改前先检查
git diff，避免覆盖其他 Agent 未提交工作」，本批在
**worktree `D:\intelligence-agent-frontend-ws6` / branch `feat/frontend-ws6-ws7`（base `522602d`）** 施工。

| 项 | 值 |
| --- | --- |
| 契约事实源 | `D:\intelligence-agent-backend\docs\PRD_WS6_WS7_DIR_ROOTED_SESSION_AND_DIR_PICKER.md` §4.3/§4.5（后端半在 `feat/backend`：`561b553`/`21c0b06`/`9c158c9`）+ ADR-0027/0028 |
| 功能 commit | `f3849ac`（14 files, +1378） |
| 审查修复 commit | `51fc68c`（5 files, +100/−23） |
| 涉及 AC | #169 AC9–AC14（前端半）；#170 AC8–AC13（前端半） |

**交付**：
- #169：项目行 kebab 第一项「在此项目中新建任务」+ 空项目占位区替换为该入口按钮；确认面（路径逐字
  「Agent 将直接读写该目录：<路径>」+ 权限档三选 + 任务输入空禁用）；提交复用 `submitTask` **同一条**
  SSE 接线（选中会话、跟随流），payload 带 `cwd`；**默认档不发 `permission_mode`**（后端语义：显式传非
  danger 档 → 切交互式审批）；失败留在确认面可重试（`submitTask` 新增 `{ ownError }`，该路径不写全局
  横幅、422 不套用「未知模型」旧语义，`api.startSessionErrorDetail` 让后端 detail 原文出场）。
- #170：`api.getHostDirs`（形状窄化 + `ProjectError` 保 detail 原文）+ `hooks/useDirectoryListing`
  （请求代号作废迟到响应；`onChange` 走 ref 防首跳重放）+ `components/DirectoryBrowser`
  （路径条回车跳转 / 向上 / 一层子目录 / 选择此目录 / 截断提示 / 403·404·422 就地显示 detail）
  + 内嵌「新建项目」对话框 + 双向同步。

**门禁（实跑）**：`tsc` ✅ · `vitest` **626 passed**（+7：cwd/permission_mode 缺省不发键 + getHostDirs
形状与错误矩阵）· `oxlint` **0 errors**（38 warnings 全为既有，新文件零新增）· `playwright --workers=2`
**208 passed / 6 failed**（本轮修复后 207 passed / 7 failed，见下）· `vite build` ✅。

**e2e 的 6 条失败 = 3 个既有用例 ×2 视口**（已在 pristine 基线 `git stash` 掉本批全部改动后、同一隔离端口
复现）：`g-visual-qa:82`（UI-03 时间线 run 分组头）、`p-earlier-window:32`（加载更早）、
`r-project-groups:295`（UI-05 真空态文案）——属 `feat/frontend` 在途工作（U-2/U-3），**不是本批引入**。
另有 1 条偶发：`k-refresh-restore:159` 单视口失败，隔离复跑 **3/3 全绿（每次 12 passed）**，
属仓库已登记的 SSE 时序类抖动（本 diff 不触碰 refresh/reconnect 路径）。

**⚠️ 5173 复用坑（写给后续所有人）**：`playwright.config.ts` 是 `5173 + reuseExistingServer: !CI`，
它会**静默复用**任何已监听 5173 的 dev server。本机并行 worktree 有会话在跑时，e2e 跑的是**别人的代码**
（本轮实测踩到：本票新增的菜单项"不存在"）。本批所有 e2e 证据用**临时隔离端口配置**产出
（10 行：`baseURL` + `webServer.command = npm run dev -- --port 5273 --strictPort` + `reuseExistingServer: false`），
该配置**跑完即删、未入库**。集成方若发现 5173 被占用，同一手法换端口再跑即可。

**真机验收**（真 uvicorn `feat/backend` + 真模型 `glm-4.5-air` + 真浏览器；`WORKSPACE_DIR` 指向隔离临时
目录，未触碰仓库真 `harness.db`；临时服务与目录已清理）：
- #169：kebab 第一项与空项目入口都点通；确认面逐字显示真实路径、默认档显示"工作区写入"；任务
  「用 read 工具以相对路径读取 hello.txt」→ 事件 `tool/call read {"path":"hello.txt"}` 成功并逐字复述
  `REAL-MARKER-7731`（**相对路径能读到 = cwd 真的生效**）；会话落在项目分组下；**全程无审批卡**
  （证明默认档确实没发 `permission_mode`）；把项目目录改名 → 提交 → 浮层内就地显示
  `提交失败：目录不存在：D:\...`（后端 422 原文、不弹全局横幅、不关对话框），目录改回后同一按钮
  **重试成功**并落组。
- #170：真盘符根列表（`C:\` / `D:\`，根模式两个按钮禁用）；`D:\` 一层 67 个真实子目录（仅目录、按名排序）；
  进入路径后**两个输入框同步回填**；手改输入框回车反向跳转；「选择此目录」回执 + 注册成功。

**批次两轴审查（fixed point `522602d`，两个独立只读 subagent）**：**零 P0/P1**。处置：
1. 路径条"说谎"（两轴各自独立发现，最有价值的一条）：导航只清 `editing` 一处，导致"条上写 A、下面列 B"
   → 新增唯一导航出口 `nav()` 统一清 `editing` + 「已选择」回执。
2. 条上回车空串无动作，但占位文案承诺「留空 = 盘符/根」→ 空串 = 列根（与表单侧同语义）。
3. 「选择此目录」回执在导航后仍挂着 → `nav` 清回执。
4. 键盘焦点在进入子目录后掉回 `<body>`（条目卸载）→ 列表/向上触发的导航把焦点收进浏览器容器
   （`tabIndex=-1`，不卸载），路径条回车触发时不收焦点。
5. 死类 `project-dialog-task`（无 CSS、无选择器引用）→ 删除（§9.3）。
6. 测试缺口 6 条全补：逐字文案改**连续串**断言、三档都在、AC11「选中 + 跟随流」、AC12 错误改
   `toHaveText` 整串、WS-7 补浏览器**自己**路径条回车 + 条上打字后改走点子目录的回归锁 + 422 就地显示；
   顺带修正 mock 保真度：带 cwd 建会话的 durable log（`GET /events`）= 刚流出的那些帧（此前回 `[]`，
   run 收尾后的回读会把流的结论清空 → "回答真的渲染出来了"这条断言测不到东西）。

**未决 / 交后续（Scope Lock，只登记）**：
① 浏览器路径条在"输入了不存在的路径"报错后回到原目录（用户输入不保留）——上面表单的路径输入框保留原文，
主要动作不受影响，已在组件头注释说明；若要保留，需要 post-render 的输入态管理（超出本票最小改动预算）。
② 真机侧没有自然构造 `403`（Windows 需要 ACL 拒绝目录，会改系统状态）——该渲染由 e2e 的 `hostDirsErrors`
拦截口覆盖（伪造的是真后端会回的那句话）；后端 403 矩阵已在其真机验收里 curl 逐条验过。
③ `D:\intelligence-agent` 的 `main` 集成时，本分支 base 是 U-2 功能 commit，而 U-2/U-3 的修复尚在
`feat/frontend` 未提交工作中 → **文件重叠面**：`app.css`（我方 hunk 在 ~1004/1025/1108+；对方在
642/656/2843/2862）、`SessionList.tsx`（我方动项目行 kebab + 空项目占位；对方动 Rail 真空态）——预计
可干净合并，但**必须真跑一遍**再判定。

**UI Polish 批次总纲**：需求事实源 = `docs/UI_POLISH_PRD.md`（含用户 2026-09-12 grill-me 决策记录 D1-D6，不可违约）；逐票施工规格 = `docs/UI_POLISH_TICKETS.md`；视觉规范基准 = 根目录 `DESIGN.md`（本批新增，含 `.impeccable/design.json` sidecar）。评审出处：impeccable critique 24/40（快照 `.impeccable/critique/2026-09-12T14-05-30Z__web-src.md`）。

### UI Polish 批次（2026-09-12 启动）：设计优化六票

**批次 0（规范固化）交付**：`DESIGN.md` + `.impeccable/design.json` + `docs/UI_POLISH_PRD.md` + `docs/UI_POLISH_TICKETS.md` + 本节登记。审查工具脚本 `web/audit-screenshots.mjs` / `web/audit-dom-evidence.mjs` 为**未入库临时产物**（UI-02 固化对比度回归锁后删除）。

**执行顺序**（依赖关系见 PRD §3）：UI-01 → UI-02 →（批量审查 U-1）→ UI-03 → UI-04 → UI-05 →（批量审查 U-2）→ UI-06 →（批量审查 U-3）→ 收尾。

**每票状态**（完成一票追加一行）：

| Ticket | 状态 | Commit | 备注 |
| --- | --- | --- | --- |
| 批次 0 规范固化 | done | `cd107a2` | DESIGN.md/PRD/TICKETS/tracker 登记 |
| UI-01 | done | `1ae3bf2` | 审批卡重塑：结构化参数+diff 复用+焦点/aria+快捷键+composer 锁定+材质违例修复 |
| UI-02 | done | `1ae3bf2` | token 三改（暗 tertiary 0.52 / 亮 **0.63 实测修正**）+28 处 10px 升档+tl-type 去 accent+对比度回归锁 |

#### U-1 批量两轴审查（fixed point `cd107a2` → `1ae3bf2`，双 Explore subagent）

**Spec 轴 10 finding（0P0/0P1/3P2/7P3）+ Standards 轴 14 finding（2P1/3P2/9P3）**，合并去重后逐条处置：

| # | 级 | finding | 处置 |
| --- | --- | --- | --- |
| 1 | **P1** | **多卡并存快捷键双发**：每张 pending 卡各挂 document keydown → 一次 Ctrl+Enter 向 N 个 approval_id 各发一 POST = 批量批准（两轴共认，本批最重） | **修**：keydown effect 加 `autoFocus` 门控（仅第一张 pending 卡挂监听，决后第二张升为 index 0 自然接管）；+双卡 e2e 回归锁（Ctrl+Enter 只 POST ap-1，第二张保持 pending）；变异验证：去掉门控 → 双卡用例红（2 failed）→ 还原绿 |
| 2 | **P1** | **三处新 UI 亮色 AA 不达标**：`.approval-chip`(~2.8:1)/`.approval-deny .approval-kbd`(~2.5:1)/`.composer-locked-hint`(~3.2:1) 沿用 warning/danger-on-tint 配方 | **修**：三处改 ink 调和——chip/hint 用 `color-mix(warning 45%, text-primary)`，deny kbd 用专属 `color-mix(destructive 60%, text-primary)` + 16% 淡染底；t-contrast 新增第 5 组断言（三选择器 × 两主题 ≥4.5） |
| 3 | P2 | `.tl-type` 回归断言弱（not.toBe 两个硬编码字面量，改任意其它颜色恒绿）且只测暗色 | **修**：改等值断言（== 探针解析的 `--color-muted-foreground` 计算值）+ 补亮色主题 |
| 4 | P2 | t-contrast parse() 未知颜色格式静默回退白底 → 可能假绿（本次 4.1226 假象的根因之一：`color(srgb …)` 未解析） | **修**：未知格式一律 throw（oklab + color(srgb) 两分支显式解析，注释声明 CSS Color 4 语义）；「无不透明祖先底」同样 throw |
| 5 | P2 | measure 局限未声明（backdrop-filter/opacity 不建模）+ 暗色 canvas 硬编码 fallback | **修**：文件头补「已知测量局限」注释；fallback 全部改 throw；placeholder 的 `18 *` 硬编码改显式 throw |
| 6 | P2 | tracker 缺规格要求的记录物（10px 分类表 / accent 审计清单 / 变异验证台账 / approval-tool 覆盖标注 / commit hash 占位未填） | **修**：本节下方补三张台账 |
| 7 | P3 | Composer `import { modKey }` 落在文件末尾 | **修**：移至顶部 import 区（`../types` 之后） |
| 8 | P3 | classifyPreviewArgs 空串被消费但渲染真值丢弃 → 信息静默消失 + 空容器 | **修**：分类器只消费非空字符串（空串留 rest 走 JSON 兜底）；+回归用例 |
| 9 | P3 | 原型链键（constructor/hasOwnProperty/__proto__）行为未锁 | **修**（用例）：+JSON.parse 形状回归用例（分类器本身安全，spread 落自有属性） |
| 10 | P3 | Composer 锁定提示文案与触发条件偏离 ticket 字面（`!streaming` 条件 + 文案多前缀） | **修**：收敛为 ticket 文案（`等待审批决策后再继续` / placeholder `等待审批决策…`）；`showLock` 派生变量消除三处重复；顶部 doc 注释补审批锁语义 |
| 11 | P3 | waitForTimeout(300) 裸魔数 | **修**：常量 `NO_SECOND_REQUEST_WAIT_MS` + 注释（对齐 q-model-dedupe 惯例） |
| 12 | P3 | approved/denied 死规则 `box-shadow:none`（基态辉光已删） | **修**：删除 |
| 13 | P3 | commit message「e2e +18」与静态 +9 口径矛盾 | **订正记录**：+18 是 Playwright **实例数**（视口矩阵 ×2），+9 是 test 函数数；两个口径都对，tracker 以实例数为准（与历史门禁数字同口径） |
| 14 | P3 | PRD 写 oxlint 基线 35w，实测自 B-1 起为 38w | **订正**：PRD §4.2 改 38w（本批新文件 0 warning，基线不增） |
| 15 | P3 | UI-02 ticket「涉及文件」把 audit 脚本标（删除）与 PRD §8.5「全部完成后删」冲突 | **修**：ticket 措辞改为「按 PRD §8.5 全部 ticket 完成后统一删除」 |
| 16 | P3 | platform iPad 桌面 UA 语义未锁 | **修**（用例）：+iPad 桌面 UA → ⌘ 用例 |
| 17 | P3 | focus-visible 挂载聚焦启发式多数场景不点亮 | 不改（防御性规则无害；要常亮需用 ：focus，引入非键盘 outline，取舍留档） |
| 18 | P3 | aria id 内插 approval_id（空格/引号会失效） | 不改（后端 id 形如 ap-1；如需防护属后端契约议题，登记 issues log） |
| 19 | P3 | chip/kbd 魔数 line-height（18px/16px） | 不改（与周边 badge 体系一致性属审美重构，§8） |
| 20 | P3 | classifyPreviewArgs 每渲染重跑 | 不改（成本极小；ApprovalCard 不在流式热路径高频区） |
| 21 | P3 | `.rail-section-count`(12px) 大于所属标题(10px micro-label) 的观感 | 不改（micro-label 是「面板眉标」语义不是标题层级；g-visual-qa 已过） |
| 22 | P3 | 同帧双 keydown 理论双 POST（busy 闭包竞态） | 不改（人手触发概率极低；根治需请求在途同步标志，登记 issues log 备查） |
| 23 | P3 | `.approval-desc` margin-top 4px / `.approval-path` canvas-mix 底 与 ticket 字面差异 | 不改（flex gap 承担间距 / 视觉等价，登记即处置） |
| 24 | P3 | AC#5 渲染级断言缺（old/new→DiffBlock、command→cmd 块只有分类级单测） | 部分修：t-contrast 的审批 fixture 覆盖 path/content 渲染；DiffBlock 分支由既有 `.diff-block` 组件测试与 ToolCard 路径间接覆盖，补渲染级断言 defer 到 UI-03 批次一并做（登记） |

**修复后门禁（实跑）**：tsc 0 · vitest **604 passed**（34 文件，+3：空串/原型键/iPad）· oxlint 38w/0e · playwright **188 passed**（--workers=2；t-contrast 5→8 test、n-approval 11→12 test，×2 视口）· vite build ✓。

#### UI-02 台账（规格要求的记录物）

**10px 分类表（30 处）**：28 处改 `var(--text-xs)`——`.rail-section-count` / `.rail-project-count` / `.rail-project-missing` / `.rail-drop-tail` / `.project-pick-path` / `.memory-scope` / `.memory-degraded-hint code` / `.system-notice-badge` / `.notice-strip-badge` / `.deleg-child-label` / `.deleg-overflow-chip` / `.child-ev-row .detail-key` / `.act-inspect-chip` / `.act-args-compact` / `.act-raw-label` / `[data-density='compact'] .act-args` / `.slice-line-chip` / `.composer-esc-hint kbd` / `.tl-tooltip` / `.json-count` / `.json-more` / `.io-raw-label` / `.palette-item-hint` / `.palette-footer span` / `.reasoning-source` / `.tool-out-chip` / `.md-code-wrap-btn` / `.model-picker-item-meta`；**2 处保留**（合法 micro-label：大写+0.08em 字距）——`.rail-section-label`(530) / `.model-picker-group-label`(4659)。豁免 0 处（预算 ≤5 未用满）。

**accent 文字审计（26 个 `color: var(--accent/--color-accent)` 站点）**：**整改 2**——`.tl-type`（时间线事件类型名→muted-foreground）、`.diff-archived-hint code`（非交互行内代码→muted-foreground）；另有 `.approval-tool code` 已由 UI-01 覆盖（accent-secondary→text-primary，**单次修改无重复**，UI-02 C.2 条款据此跳过）。**保留 24**（交互/状态）：appbar-toggle-active、run-pulse-thinking、rail-project-toggle:hover、rail-drop-tail.active、project-pick-pending（状态）、memory-scope.scope-user（scope 语义 chip）、msg-avatar-model（delegation 签名）、fork-btn:hover、model-kind-thinking、run-badge-running/thinking、detail-tab.sel、detail-terminal-row:hover、workspace-mode.sel、read-continue-code（可点继续阅读）、reasoning-icon（live 呼吸）、composer-model:hover、composer-control:hover、model-picker sel/check/checkbox、detail-section-title svg（面板标识，边界项登记备查）、workspace-scaffold-tag（诚实占位标记，边界项登记备查）。

**变异验证台账（本批 5 处，全部红→绿闭环）**：① 键盘监听删除（MUTATION-A：onKey 清空）→ Ctrl+Enter/Ctrl+Backspace 4 实例红；② composer 锁定通道拆除（textarea 回 `disabled={streaming}`，MUTATION-B）→ 锁定用例红——**首版变异假绿已订正**：原 fixture 无 run/completed，streaming 恒 true 掩盖审批锁，补终态帧后变异才红；③ 暗 tertiary 0.42 回退 → [dark] 对比度 4 failed；④ tl-type 回染 accent → 2 failed；⑤ 键盘门控拆除（MUTATION-C：去 autoFocus 条件）→ 双卡用例红。

**测试有效性备注**：t-contrast 排查中发现并修复两个测量层假信号——Playwright test 上下文 `colorScheme` 默认 light（[dark] 用例必须 localStorage 显式引导主题）；同一 color-mix 在该 Chromium 两条计算路径输出 oklab / color(srgb) 两种格式（解析器双分支 + 未知格式 throw）。

| UI-03 | done | `522602d`（U-2 批量） | Inspector run 分组头 + 全会话序号 + tab 计数 + 头标对齐。**与票面偏离（已记录）**：五个 Inspector 图标是「视图 tab」不是「事件 kind 过滤器」，票面意图以 tab 计数徽标实现（`.detail-tab-count`）；时间线 kind 过滤 chips 按票面 Out-of-scope 不做 |
| UI-04 | done | `522602d`（U-2 批量） | projection 三摘要（forked/审批请求/审批已决）+ formatShortDuration（<50ms 不造 1ms 假精度）+ ReasoningBlock <1s 措辞（0 秒→<1s，中断于 <1s） |
| UI-05 | done | `522602d`（U-2 批量） | Rail 真空态文字按钮（新建项目/新建会话）+ 空态文案带行动链接（注册项目目录 →） |
| UI-06 | done | 本批尾 commit | Composer 平台键位 UI-01 已覆盖（标注跳过）；CJK 间距「切换到 Raw」+ 主题 hint 去箭头（i-keyboard 新 e2e 锁）；run-badge padding 2px→3px 向 .run-pulse 收敛；Split/Preview 与半截 ID 明确不做（登记） |

#### U-2 批量两轴审查（fixed point `236049f` → `522602d`，双 Explore subagent）

**Spec 轴 3P1/3P2/3P3 + Standards 轴 1P1/5P2/6P3**，合并去重后全部处置（修复 commit `e543ae1`）：

| # | 级 | finding | 处置 |
| --- | --- | --- | --- |
| 1 | **P1** | **Rules of Hooks 违例**：runIdList useMemo 挂在 StepDetail 三个 early-return 之后 → 从事件详情分支切回 run 级时 hook 数不一致 → **点开会话整页崩溃**（'Rendered more hooks than during the previous render'，真浏览器复现；e2e 的 g-visual-qa/p-earlier-window 全量假红即此） | 修：useMemo 上提到组件顶部（conversation 可空守卫 `?? []`）；变异=把 hook 移回原位即崩，真机探针复验 tabs 恢复 |
| 2 | **P1** | g-visual-qa 新 e2e：T0 在 ROW2 之后声明 → TDZ ReferenceError（e2e 不进 tsconfig，tsc 抓不到）；同用例计数断言 3 事件实为 4（session/started 归入 r1 组） | 修：声明上提 + 断言 3→4 事件 |
| 3 | **P1** | ReasoningBlock：中断 ≥1s 被改成「持续了 N 秒」→ 中断语义塌缩成 completed（票面只要求修 N===0） | 修：恢复「中断于 N 秒」≥1s 分支；SSR 用例回改并加 18 秒断言 |
| 4 | P2 | SessionList 空态文案挂 `!showEmpty` → **真·空态（sessions=0 且 projects=0）时文案整段被吞**，与同屏文字按钮自相矛盾（正是 UI-05 要消灭的断点；两轴各命中一次） | 修：只留 `!projectsError`（502 错误态仍只显错误条，真机探针双验证：空态=文案+链接渲染，502=仅错误条） |
| 5 | P2 | timelineGroups：交错 run_id（r1,r2,r1）组序数按组序 1/2/3 编，与 countRuns 的「2 runs」矛盾（首现顺序票面定义） | 修：ordinalOfRun Map 按首现编号（回段仍叫 Run 1）；变异（ordinal 常数 1）→ 4 红 |
| 6 | P2 | formatDuration 重构丢了负值 clamp（时钟倒挂显 '-5ms'）；formatShortDuration 无 Number.isFinite 守卫 | 修：双口径守卫（负值→'' / formatDuration→null，调用方不渲染行）；+用例；变异（守卫移除）→ 1 红 |
| 7 | P2 | StepDetail.test 分组计数断言 `>3</span>` 实际命中 tl-seq 行（假绿，计数断了也绿） | 修：改打 `.tl-run-count` 上的 '4 事件'（regex 锚定组头） |
| 8 | P2 | rail-empty 文字按钮 ~20px 高，低于 ticket 规格 28px（PRD 命中区下限 32px 列为「明确不动」清单的边界） | 修：min-height 28px（ticket 字面值） |
| 9 | P2 | routeApi 无 projects 键的空态形状风险 | 探针验证通过，不改 |
| 10 | P3 | .tl-run-header role="separator"（内容承载元素非法 ARIA） | 修：移除 |
| 11 | P3 | window-bar 后首个组头双分隔线（:first-child 不生效） | 修：`.timeline-window-bar + .tl-run-header` 兄弟选择器 |
| 12 | P3 | groupEventsByRun/tabCounts 每渲染重跑 + title 内联重建 distinct-run 集（两套遍历同数据） | 修：runGroups/runIdList useMemo（events 引用不变即跳过）；title 复用 runIdList |
| 13 | P3 | detail-run-id 类名不再含 run id；.detail-tab-count line-height 16px 魔数；format.test import 空格 | 修：类名保留（e2e 依赖账未列改名成本，注释注明语义）；line-height 1.2+padding；import 修 |
| 14 | P3 | **detail-tab 无 aria-label**：计数徽标成为 tab 唯一文本内容后，窄面板 icon-only 下 getByRole(tab,'Timeline') 变 name '4' → p-earlier-window e2e 假红（UI-03 引入的回归，g-visual-qa 同理） | 修：tab 加 aria-label（徽标 aria-hidden）；194/194 全绿 |

**修复后门禁（实跑）**：tsc 0 · vitest **622 passed** · oxlint 38w/0e · playwright **194 passed**（--workers=2）· vite build ✓。变异：MUTATION-D（ordinal 常数）4 红 / MUTATION-E'（format 守卫移除）1 红 / MUTATION-F'（空态分支拆除）e2e 2 红，均还原。

#### U-3 批量审查（fixed point `e543ae1` → 本批尾）

范围：UI-06（CJK 间距 / hint 箭头 / run-badge 收敛）+ 收尾（删 3 个未入库临时脚本）。**处置**：

| # | finding | 处置 |
| --- | --- | --- |
| 1 | commands.test 新断言是内联 fixture（App.tsx 改坏它不红） | 升级为 e2e 真实渲染断言（i-keyboard 新用例：查询「切换到」断言 `.palette-item-label` 文本 = 「切换到 紧凑」/「切换到 Raw」；「切换主题」断言 hint 无箭头）；单测保留作为形状文档 |
| 2 | e2e 上下文默认 light 主题，主题 hint 期望值写成 '亮色'（实为 '暗色'） | 修：断言 '暗色'（目标档位），注释说明 |
| 3 | 变异验证 | ① hint 回灌箭头 → 2 红；② label 去空格 → 6 红；均还原（grep 0 残留） |
| 4 | run-badge padding 2px→3px 与 .run-pulse 同族（字重/字号/radius 已一致） | 修（computed 值对齐） |

**U-3 尾门禁（实跑）**：tsc 0 · vitest **623 passed** · oxlint 38w/0e · playwright **196 passed**（--workers=2）· vite build ✓。临时审计脚本（web/audit-screenshots.mjs / audit-dom-evidence.mjs / dbg2.mjs）已删除。

### 最终全量 review（v2 §1.3）的处置——**已披露的偏离**

v2 §1.3 要求「全部 ticket 完成后对整条分支跑一次最终全量 /code-review，fixed point = main」。
本 worktree 的处置与理由如下（**不是静默跳过，是显式记录**）：

1. 本分支相对 `main` **落后 13 个 commit / ahead 14**（见 `docs/integration/BRANCH_TOPOLOGY_AUDIT.md`），
   且 `main` 侧的变更全在 `src/**`、`tests/**`（后端），与 `web/**` 无交集。以 `main` 为 fixed point
   的 diff 里，绝大多数是**别人的代码**，对前端审查没有信息量。
2. 本分支**切换 v2 之前**的 13 个前端 commit，已在各自轮次做过两轴 review（见本文件各「批次」小节 +
   `docs/FRONTEND_ISSUES_LOG.md` 各轮）。用户 2026-09-12 的过渡条款明确：「旧版循环下已完成并 commit
   的 tickets 一律承认有效，不再补审、不重跑」。
3. 因此**唯一未被审过的增量 = `637bc89..HEAD`**，已由 B-1 审查覆盖（新版本循环的 fixed point 语义）。

结论：本 worktree 认为 v2 §1.3 的**目的**（"切换后新增的代码全被审过"）已达成；字面执行
`main...HEAD` 只会重审已承认有效的内容。**留给集成 AI 决策**：若仍要跑，建议在 `main` 合入本分支后
再跑（那时 fixed point = 合并前的 main，diff 才等于本分支的真实增量）。

> 为什么单票成批：v2 §1.2 允许「遇到依赖链断点等自然分界提前收批」。#160 是 MEM-5 跨端票的
> 前端半、也是本轮唯一剩余票（MEM 链末端）→ 自然断点，单票即收批；
> 本批 diff = `637bc89..<#160 commit>`。
>
> 协议文件 §4「剩余 Ticket 清单」是旧内容（FE-T7/T8/T9 早已 done）——本轮**不动它**：
> 该文件跨 worktree 共用，保持与 feat/backend 侧逐字节一致可避免制造无谓的 merge 冲突。

### 最近一批：BUG-011 前端半——模型项双击不再发第二个 `POST /model`（2026-09-11）

| 项 | 值 |
| --- | --- |
| 本批 commit | `71e605b`（代码）+ `949d4ad`/`f06cfbd`（docs） |
| 门禁 | tsc ✓ / vitest **519 passed**（29 文件）/ oxlint **37w 0e**（基线持平）/ playwright **130 passed**（`--workers=2`）/ vite build ✓ |
| 触发 | 真机报障「续聊失败：Send failed: 404」，会话 `dd983104`（根因在后端，本批只做前端触发面 + 回归锁） |
| 交付 | ① `ModelPicker.tsx`：新增 `commitSelection`（默认链 + 目录项两处 `onSelect` 统一入口），**弹层已关（`!open`）即丢弃选中**——第一次选中后浮层进入 `--dur-out`(150ms) 退出动画，节点仍在 DOM 可命中，第二次 click 由此丢弃；② `e2e/fixtures.ts`：`onModelPost` 注入点 + 缺省 200 处理器（计数/延迟响应）；③ 新增 `e2e/q-model-dedupe.spec.ts`（3 条锁 × 2 视口）。 |
| 变异验证 | 去掉 `!open` 守卫 → 两例全红，失败信息即原始 bug 指纹（`Expected: 1 / Received: 2`；另一例 `Received length: 3` 且三个 payload 完全相同）。已还原。 |
| 取舍（实测驱动） | 最初设想在 `useSession.changeModel` 加「同目标在途复用 Promise」。探针实测该层**永不生效**：`dblclick()`（一次手势两下点击）与 `page.mouse.click` ×2 都是两次 click 之间 React 已提交 `open=false`，第二个请求到不了 hook——删掉该层前后探针结果完全相同（`dblclick=1` / `mouseclick_x2=1`）。故**只留入口一层**（等价于计划里的「弹层关闭后立即 `pointer-events:none`」），hook 恢复直通、仅留注释指明真正 seam，防止后人加错层。 |
| 跨端配对 | 后端半在 `D:\intelligence-agent-backend` `feat/backend`：`4b8eee4`（① `store.append_event` 每会话写锁 + seq 单调性守卫；② `SeqConflict → 409` 独立语义 + `change_model` 有界重试 3 次；删除 `except ValueError → SessionNotFound` 一刀切；`tests/web/test_web_seq_conflict.py` 4 例）。**后端门禁**：ruff ✓ / pytest **1596 passed**。**集成必须先后端后前端**（AGENTS.md §14.9），后端 seq 守卫是安全网，前端去重是堵源头。 |
| code-review | 两轴（Standards + Spec）各派 subagent：Spec 轴指出「永久 applied 幂等缓存超出计划且不可失效（外部改过模型后无法再选回）+ 依赖响应回显请求值」→ 已删除该设计；Standards 轴指出「测试无法证明第二次点击真的落到节点上（可能因节点已消失而假绿）」→ 已由变异验证补齐该证据并写进 spec 文件头。 |
| 未决/边界 | 跨进程并发写（多进程共享同一 JSONL）无文件锁——后端 `store.py` 文档已如实标注；历史遗留的损坏日志不自愈（读时 409）。 |

### 上一批：ARCH-4b 前端——SessionSummary.trace_url 契约锁 + e2e mock 同步（2026-09-11）

| 项 | 值 |
| --- | --- |
| 本批 commit | `4c38c69` |
| 门禁 | tsc ✓ / vitest **504 passed**（28 文件，+2）/ oxlint **35w 0e**（基线持平）/ playwright **118 passed**（`--workers=2`）/ vite build ✓ |
| 交付 | **类型声明零改动**（`types.ts` 本就正确声明 `trace_url: string \| null`）。① `src/lib/api.test.ts` 新增 `listSessions` 契约块：`trace_url` 原样透传（URL）+ 未追踪保持 null（不伪造，不变量 #21）；canonical fixture 用 `SessionSummary` **类型注解**锁**编译期**一致性——类型新增必填字段 → fixture 缺键 → `tsc -b` 红；fixture 多出未声明键 → 多余属性检查红。② `e2e/*.spec.ts`（6 文件 10 行）会话行 mock 补 `trace_url: null`——旧 mock 照抄了「后端不返回该键」的坏形状，会让前端永远看不到它。 |
| 变异验证 | 从 canonical fixture 删掉必填 `trace_url` → `tsc -b` 报 **TS2741** `Property 'trace_url' is missing ... but required in type 'SessionSummary'` 红（已还原）。 |
| 跨端配对 | 后端半在 `D:\intelligence-agent-backend` `feat/backend`：`a0f86a4`（`store.py` 的 `_terminal_trace_field` 两键共用守卫 + `web/app.py` 映射；`session/service.py` 零改动）。**后端侧权威锁**（断言**值**，能抓「键在但值是 null」的漏映射）：`tests/test_web_api.py::test_list_sessions_carries_terminal_trace_url`。 |
| code-review | 两轴：Standards 轴无 hard violation（采纳 `Literal` 键加固，不采纳 NamedTuple 返回对）；Spec 轴 AC1/2/3/5 满足、零 scope creep，指出 AC#3 值断言缺口已由后端补上。 |

### 上一批：OBS-016 前端同步——超长单行标记文案（2026-09-11）

| 项 | 值 |
| --- | --- |
| 本批 commit | `1fac807` |
| 门禁 | tsc ✓ / vitest **502 passed**（28 文件）/ oxlint **35w 0e**（基线持平）/ playwright **118 passed**（`--workers=2`）/ vite build ✓ |
| 交付 | 纯跨端同步，**解析逻辑零改动**（`LINE_TRUNCATED_RE` 的 `[^\]]*` 本就吞尾部）。① `web/src/lib/toolShapes.test.ts`：新增「新文案（OBS-016）」用例；原用例改标「旧文案（历史会话已落盘）」并**保留**——历史 JSONL 事件仍是旧文案，两种都要能解。② `docs/HANDOFF_FRONTEND_SYNC.md` §1.3：订正为「形状契约 + 措辞可变 + 历史文案兼容」。 |
| 变异验证 | 把 `LINE_TRUNCATED_RE` 改成仅匹配旧文案（追加 `\. Use bash`）→「新文案」用例变红、「旧文案」用例仍绿（已还原）。证明新增用例非空转，且旧用例仍锁住向后兼容。 |
| 跨端配对 | 后端半在 `D:\intelligence-agent-backend` `feat/backend`：`aa29562`（`read.py` 正文改点名真实工具标识符 bash/grep）。本 clone 是独立 clone，`web/` 与 `docs/HANDOFF_FRONTEND_SYNC.md` 相对 `origin/main` **零漂移**，故本批**未做 merge**（`feat/frontend` @`274afcf` 是 `origin/main` @`63db650` 的严格祖先，如需同步可 ff）。 |
| code-review | 本批为测试/文档同步，无解析逻辑改动；后端半的两轴 review 已发现并修复初版「the shell tool」指向不存在工具的问题。 |

### 上一批：OBS-015 修复——审批卡区分幂等已决(409)与真失败(5xx)（2026-09-11）

| 项 | 值 |
| --- | --- |
| 本批 commit | `cb0e008` |
| 门禁 | tsc ✓ / vitest **501 passed**（28 文件）/ oxlint **35w 0e**（基线持平）/ playwright **116 passed**（`--workers=2`）/ vite build ✓ |
| 交付 | ① `api.ts` 新增 `AlreadyResolvedError`；`postApproval` 在 HTTP 409 时抛它，其它非 ok 抛普通 `Error`。② `ApprovalCard.tsx` 修复 catch：`AlreadyResolvedError`(409) → 幂等成功翻卡片；其它错误 → 保持 pending + 显示可见错误(`role="alert"`) + 按钮重新可用可重试。③ 回归锁 `e2e/n-approval-card.spec.ts` +2 用例 ×2 视口 = 4 例。④ `.approval-error` CSS 规则（danger 淡染底 + 左侧 2px 实条）。⑤ 单测 `api.test.ts` +4 例（200 ok / 409 AlreadyResolvedError / 500 plain Error / 422 plain Error）。 |
| 变异验证 | 两处全部生效：① 还原 ApprovalCard 旧行为（任何错误都翻卡片）→ POST 500 用例变红（`Expected: "需要审批" / Received: "已批准"`）。② 禁用 AlreadyResolvedError 分支 → POST 409 用例变红（卡片不再翻「已批准」）。 |
| code-review | Standards 轴 0 hard violations、2 minor smells（均 acceptable）。Spec 轴发现 4 项：① 404 幂等语义未处理 → 经核实后端契约 404 = approval 不存在（不是「已解析」），409 才是幂等已决，当前代码正确。② 失败文案需更明确 → 已在 error message 中体现。③ `.approval-error` 无 CSS → 已补。④ tracker 未更新 → 本批更新。 |

#### 补记（2026-09-11 收尾）：404 语义订正 + 注释与代码对齐 + 404 fail-safe 锁

OBS-015 的既有 code-review 已判出「404 ≠ 幂等已决，当前代码正确」，但**只改了 tracker**，遗留了三处与代码矛盾的载体。本次收尾（**零产品行为改动**）：

| 项 | 内容 |
| --- | --- |
| 订正 1 | `web/src/lib/api.ts` 的 `postApproval` docstring 原写「404 with "already resolved" detail = same semantics → AlreadyResolvedError」，与代码（只有 409 抛 `AlreadyResolvedError`）相反，且会把「决策没生效」误显示成「已批准」。已按后端真实语义改写：404 的四个来源（session 不存在 / 审批队列缺失 / `approval_id` 不在队列 / 事件过期，`web/app.py:1157-1166`）无法与「已解析且已出队」区分 → 必须保持 pending；真已决由 `permission/resolved` 投影事件兜底。 |
| 订正 2 | `docs/PROMPT_FRONTEND_NEXT_BATCH.md` 原把「409/404 幂等语义走已决」写进任务步骤与验收标准（**该前提本身是错的**，会诱导后人实现 404-as-success）。已加 2026-09-11 订正块：保留原文 + 明确 **404 不走已决**。 |
| 新增锁 | `web/e2e/n-approval-card.spec.ts` +1 用例 ×2 视口：**POST 404 → 保持「需要审批」+ 错误文案含 404 + 按钮仍可重试**（此前该路径零覆盖）。 |
| 变异验证 | 注入「旧提示词推荐的错误实现」（`if (404) throw AlreadyResolvedError`）→ 新 404 用例**两视口变红**（2 failed / 12 passed）→ 还原后全绿。证明新锁非空洞。 |
| 未改 | `docs/FRONTEND_ISSUES_LOG.md` 的 OBS-015 条（证据记录，按 HANDOFF §8 不重写）；`ApprovalCard.tsx` / `api.ts` 的运行时行为零改动。 |
| 门禁 | tsc ✓ / vitest **501 passed**（28 文件）/ oxlint **35w 0e**（基线持平）/ playwright **118 passed**（`--workers=2`，116 + 新 404 用例 2）/ vite build ✓ |

### 上一批：瞬态三键 + 401 缝 + 审批卡两键（覆盖账目收口到 45/45，2026-09-11）

| 项 | 值 |
| --- | --- |
| 本批 commit | `35cd0a1`（401 缝单测 + `l-auth-banner.spec.ts`）、`8ed86f0`（瞬态三键 `m-stream-affordances.spec.ts`）、`c9dcf2a`（审批卡 `n-approval-card.spec.ts` + 联调车道） |
| 门禁 | tsc ✓ / vitest **497 passed**（28 文件）/ oxlint **35w 0e**（基线持平）/ playwright **112 passed**（`--workers=2`；104 + 审批卡 8）/ vite build ✓ |
| 交付 | ① 三个瞬态按钮（`tool-out-wrap-btn` / `tool-out-jump` / `reasoning-jump`）用 mock 流钉住窗口后**真实点击**；② 401 缝补 3 例单测 + 横幅 e2e；③ 审批卡「批准」「拒绝」**真机点击**（真实后端 + 真实模型） |
| 覆盖账目 | **45/45 全部已被点击**：38 真机 + 3 mock 流 + 1 mock 401 + 1 e2e 内激活 + **2 审批卡真机点击**（原记「产品不可达」已证伪） |
| 原「残余不可达」 | ~~审批卡「批准」「拒绝」：`auto_approve` 硬编码 → 永不渲染~~ **已证伪**：门是 `session/service.py:348` 的 `permission_mode_explicit`（显式选权限档位即开启交互式审批），与 `auto_approve` 无关。两键已真机点击，后端 JSONL 落库 `permission/resolved`（由测试自身轮询断言）；回归锁 `web/e2e/n-approval-card.spec.ts`；真机脚本走独立联调车道 `web/e2e-live/` + `playwright.live.config.ts` |
| 新登记问题 | **OBS-015（P2，前端，预存在，需产品决策）**：`ApprovalCard.tsx:26-33` 的 `catch` 对任何错误都翻成「已批准/已拒绝」，与注释「其它错误保持 pending」相反 → 审批 POST 失败时是乐观假象。本轮未改代码（§8） |
| 审查 | 两轮独立审查。`m-stream-affordances` **approve**（0 P0/P1/P2、6 项 P3 全修）；审批卡一轮发现 **2 项 P2**（URL 会话 id 未断言、联调车道分不清「后端已决」与「乐观 UI」）**均已修 + 变异验证**，P3 三项处置 |
| 自曝缺陷 | 新建联调车道时 `vitest.config.ts` 的 `exclude` 漏了 `e2e-live/**` → 单测车道被 Playwright 用例污染而变红；已修，并写入 HANDOFF §6 警示 |
| 关单 | 不适用（缺陷/覆盖批次，非 ticket 交付） |

### 最近一批：刷新一致性 BUG-005 / BUG-006 + 第二轮逐按钮巡检（2026-09-11）

| 项 | 值 |
| --- | --- |
| 起始 commit | `cf8f3a7` |
| 本批 commit | `138b056`（+ 后续小提交回填本 hash） |
| 门禁 | tsc ✓ / vitest **490 passed**（28 文件）/ oxlint **35w 0e**（基线持平）/ playwright **96 passed**（86 → +10）/ vite build ✓ |
| 交付 | BUG-005 刷新恢复选中会话；BUG-006 流式中刷新 → `?after_seq=` 接回流继续收事件；新增 `lib/sessionRestore.ts`(+test)、`api.ts` `NotFoundError`、`e2e/k-refresh-restore.spec.ts` |
| 真机验证 | BUG-006 **决定性取证**：真实后端 run 在途时 F5 → `GET /stream?after_seq=2 [200]`，零交互下事件 3 → 54 条直到 `run/completed`；与后端真值 54 条 / 0 重复 / 0 空洞。BUG-005 刷新前后正文指纹 `-271347586` / 4102 字符逐项一致 |
| 巡检 | 第二轮 66 行逐按钮表（密度/主题/Inspector 收起/Workspace/四选择器/五 Tab/命令面板/委派节点/分叉/令牌弹窗/preset chip/发送禁用/停止/请求量）全部通过 |
| 新发现 | BUG-007（命令面板 label 全英文，中文查询零命中）——**已修复**（label 本地化 + `keywords` 别名，英文仍可搜）；OBS-008（`glm-5.3-flash` `model/failed: RuntimeError`）、OBS-009（bash 工具 10s 超时且 `retryable:false`）均为**后端/provider**问题，前端渲染忠实 |
| 审查 | 第一轮 6 findings（3×P2 + 3×P3）：4 修 + 2 说明理由不改；第二轮见集成提示词 |
| 关单 | 不适用（缺陷修复批次，非 ticket 交付） |

### 上一批：恢复/分叉/滚动 三缺陷 + 真实浏览器逐按钮巡检（2026-09-11）

| 项 | 值 |
| --- | --- |
| 起始 commit | `8469a34`（另一 Agent 的 BUG-001 修复） |
| 本批 commit | `32356f4`（缺陷修复 + 巡检）、`0d6b82d`（架构扫描低风险项） |
| 门禁 | tsc ✓ / vitest **472 passed**（27 文件）/ oxlint **35w 0e** / playwright **86 passed** / vite build ✓ |
| 交付 | 交接手册 A/B/C/D；额外 BUG-004（Copy Run ID）+ 分叉 30s 超时反馈 |
| 真机验证 | A/B/D 三项在真实浏览器 + 真实后端复验（回执见 `FRONTEND_ISSUES_LOG.md` OBS-003/OBS-004）；43 行逐按钮巡检表 |
| 遗留 | OBS-007（中断会话绿色「已完成」脉冲与中断横幅矛盾，**预存在、故意未修**，§8）；覆盖缺口清单见集成提示词 §4 |
| 关单 | 不适用（缺陷修复批次，非 ticket 交付） |
| 架构扫描 | `/improve-codebase-architecture` 已完成。已修：候选 3（Inspector Run 摘要收归 `runState`，`0d6b82d`）+ 候选 4 字段级文档。**未做（按扫描结论 + §8）**：候选 1 `StreamOrchestrator`（最热路径，需监督 + 测试先行）、候选 2 `useFollowLatest`（代码库已显式推迟，ADR-0016）。报告：`%TEMP%rchitecture-review-20260911-0345.html` |

---

## Ticket 状态总览

| Ticket | 描述 | 状态 | Commit |
| --- | --- | --- | --- |
| FE-T7 | 会话级模型切换 + Fork UI（#137） | `done` | `71c01dd` + review 修复 `c6e6fab` |
| FE-T8 | 崩溃恢复 UI — run/interrupted + 409 守卫（#138） | `done` | `c137a23` |
| FE-T9 | 轮次标签（turn_index 显示）（#139） | `done` | `d2bfbc8`（类型/投影层）+ `cddea36`（UI 层） |
| 前置 | 重新生成 event-types（MODEL_CHANGED + RUN_INTERRUPTED） | `done` | `6012414` |
| 深化 C4 | api 层成为唯一归一化点 | `done` | `9b2234f` |
| 深化 C3 | Composer 档位 → 提交字段的单一构造器 | `done` | `9b2234f` |
| 深化 C2 | projection 事件语义注册表（编译期穷尽） | `done` | `f481ea5` |
| 深化 C1 | StreamOrchestrator 流式编排深化 | **`partial`** | `ae341e2`（第一刀） |
| 深化 review 修复 | 字段表编译期锁 + 时间参数集中 + 记录修订 | `done` | `2735422` |
| 深化 C5 | ConversationState 拆分 | `rejected` | —（YAGNI + 参考实现反证，见 `docs/ARCHITECTURE_REVIEW.md`） |

### 全部完成后的步骤

| 步骤 | 状态 |
| --- | --- |
| /improve-codebase-architecture | `done` → `docs/ARCHITECTURE_REVIEW.md`（`3e71b33`） |
| 深化批次实施 | `partial`（C1 剩余部分见下） |
| 写集成 AI 交接提示词 | `done`（`25917c1` 初版 → 本轮补深化批次 + 拓扑重测 + AGENTS.md 冲突预判） |

---

## 门禁基线（本轮全绿）

| 门禁 | 结果 |
| --- | --- |
| `npx tsc -b` | 0 error |
| `npx vitest run` | 408 passed / 27 files |
| `npx oxlint` | 0 error / 35 warning（全部既有，非本批引入） |
| `npx playwright test --workers=2` | 46 passed |
| `npx vite build` | OK（仅既有 chunk-size 提示） |

---

## 已完成批次：FE-T7 / T8 / T9（#137–#139）

### FE-T7 会话级模型切换 + Fork UI

- API：`changeSessionModel(sessionId, provider, modelId)` → `POST /api/sessions/{id}/model`；
  `forkSession(sessionId, fromSeq)` → `POST /api/sessions/{id}/forks`。
- 投影：`model/changed` → 更新 `conversation.model`。
- UI：ModelPicker 走 POST 并以**响应回传的规范 model_id**更新本地状态（不回显请求值）；
  用户消息上的「分叉」入口（`Conversation.tsx` + `.fork-btn`）。
- review 修复（`c6e6fab`）：CSS 变量改正、响应 model_id 采用、移除越出 T8 范围的改动。

### FE-T8 崩溃恢复 UI

- 投影：`run/interrupted` → `finalizeRun` + `ConversationState.run_interrupted`
  `{ step_id, interrupted_seq, reason }`。
- `sendFollowUp` 捕获 **409**：解析 detail，抛「存在需要人工裁决的高风险操作」，
  **不伪造结果继续**（后端硬拒绝，不变量 #14）。
- UI：中断横幅（`.interrupt-banner`）。

### FE-T9 轮次标签

- **数据层（`d2bfbc8`）**：`run/started` 提取 `data.turn_index`（后端 `session.begin_run`
  定义为「该 session 第几个 run，1-based」，每次 run 各自携带）→
  `ConversationState.turn_index`（会话级，供 Langfuse/turn 元数据）。
- **UI 层（`cddea36`）**：`Turn.turn_index`（per-turn 事实）→ `TurnView` 显示「第 N 轮」。
  ⚠️ 修正：原计划复用会话级 `state.turn_index` 传入 `TurnView`，但该字段被最新 run
  覆盖 → 所有历史轮次会显示同一个数字。改为把 RUN_STARTED 的值落到**当轮 turn** 上。

---

## 深化批次（架构评审 → 实施）

评审产物：`docs/ARCHITECTURE_REVIEW.md`（5 个候选 + 「选择的最佳路径」+ 「交付状态」+ 「已披露的行为变化」）。

**执行顺序（先低风险后深水）**：C4 → C3 → C2 → C1；C5 已否决。

### C4 + C3（`9b2234f`，一个 SDD 循环覆盖两个 candidate——偏离「每 candidate 一轮」，已记录）

- 新增 `lib/amend.ts`：`toAmendFields` / `toCreateControls`——Composer 档位（camelCase）
  → 契约字段名的**单一映射点**；明确**不做**空值丢弃（丢弃归 api 层）。
- `lib/api.ts`：`startSession` 成为与 `sendMessage` 同款的「有值才带键」执行点；
  空值 / 空数组不发键 = 后端默认。
- 新增 `lib/amend.test.ts`（5 例）锁字段集边界与「映射层不判空」契约。

### C2（`f481ea5`）事件语义注册表

- `applyEvent` 与 `summarizeEvent` 两个并行 switch 收敛为
  `EVENT_SEMANTICS: Record<EventTypeValue, EventSemantics>`（`{ apply, summarize }`）。
- **穷尽性经实验证伪**：注入 `FUTURE_THING` → `tsc` 报 TS2741；
  还原后 `git diff --stat` 干净。生成物新增事件类型而忘记登记 → 编译失败。
- 词汇表内但前端零处理的 7 个类型（`artifact/externalized`、`context/compaction_start|end`、
  `message/queued`、`queue/cancelled`、`steer/requested|applied`）**显式登记**为
  `unhandledProjection`（保持既有兜底行为进 `unknown_events`），使缺口可见而非静默。

### C1（`ae341e2`）第一刀——`ReconnectController`

- 新增 `lib/reconnect.ts`：**无 React / 无定时器 / 无 I/O** 的重连策略状态机。
  调用方拿 `decision` + `delayMs` 后自行调度（参考 deepseek-harness `BlockStreamer`
  的 injectable clock、pi-mono `lane.ts` 把 operation 生命周期从编排循环剥出）。
- 契约原语一并迁入 `decideStreamEnd` / `reconnectDelayMs` / `MAX_RECONNECT_ATTEMPTS`；
  时间常量 `RECONNECT_STALL_MS` / `RECONNECT_BANNER_DELAY_MS` 在 review 修复 `2735422` 随迁
  （评审「速度」目标：退避 / 停摆阈值 / banner 延迟集中为一处）。`useSession.ts` 以 re-export
  保持既有导入路径不破。
- 行为逐点对齐旧闭包：准入即占单飞并递增额度；`observeProgress` 只在 seq **严格超过**
  重连起点游标时复位额度（重放旧帧不是真进展，否则额度永不耗尽 → `give-up` 不可达 →
  悬空 run 无限重连）；`release` 放单飞但不动额度；`hold` 是 truncated 全量重建的占位；
  `reset` 是流的生命周期边界。
- 新增 `lib/reconnect.test.ts`（19 例）锁此前无测试的状态迁移。

---

## 剩余工作

### 1. C1 深水部分：`StreamOrchestrator`（未做，风险最高，需完整回归）

`attachLiveStream` 仍是约 200 行嵌套闭包，以下四类降级路径与合帧提交仍在 hook 内：

| 路径 | 现状位置 |
| --- | --- |
| 合帧批量提交（性能正向路径） | `coalescer` / `coalescerRef` |
| 停摆心跳 + visibilitychange | `stallCheckRef` / `stallCheck` |
| truncated 全量重建 | `doTruncatedRebuild` |
| seq-gap 分流 | `onEvent` 内 `isSeqGap` 分支 |

目标形状（评审「主路径」）：`lib/stream-orchestrator.ts`，构造注入
`fetchStream` / `scheduleTimer` / `clock`，内部按 pi-mono `drive/` 的状态分派
拆成 recovery / rebuild / stall 子模块；生产（SSE 解析）与消费（投影应用）分离
（pi-mono `EventStream<T,R>`）。

**为何本轮不做**：该段处于每帧热路径与全部降级路径的交汇处，无监督长会话收尾阶段
风险过高。先剥出重连策略状态机并锁单测，是后续提取的安全网前置条件。

### 2. 已登记待定项（不在本批范围）

- `session/forked`：已知类型但 Timeline 摘要仍落「未知事件」文案（pre-existing，
  文案变更未经确认）。C2 注册表按等价迁移保留，已登记。
- 上述 7 个未接线类型：需产品确认是否显示。
- `api.ts` 中 `START_SESSION_FIELDS` 与 `SEND_MESSAGE_FIELDS` 的 amend 四项各自登记
  （编译期各自穷尽，但同一字段集两处书写）——是否抽公共表待定，当前按
  「简单优先」保留显式重复。

### 3. 集成交接提示词（已更新）

`docs/integration/FRONTEND_INTEGRATION_PROMPT.md` 已重写：14 个 commit 清单、
新 HEAD `d5a8dca`、深化批次新增模块、两处已披露行为变化、C1 未完成范围，
以及**重测后的拓扑与冲突预判**。

#### ⚠ 拓扑已变，冲突预判与初版相反

初版写「ahead/behind 6/0，预期 merge 干净」。重测：merge-base `5c07fff`，
`main` `c5149ad`，**14 / 13**（main 在 merge-base 后又前进 13 个 commit）。

`git merge-tree --write-tree --name-only main HEAD` → **`AGENTS.md` 必然冲突**：
两侧都在 §15 之后追加同号 §16（`main` 版是后端/Primary 口径，本分支版是前端口径）。
按 §14.7 已给出 9 项分析与推荐统一语义（保留 main 版为唯一 §16，前端内容折叠为
`## 16.6 前端 worktree 补充`）——**留给集成 AI + 用户决策，本分支不自行解决**。

`web/src/generated/event-types.ts` 两侧都改过但**逐字节相同**，auto-merge 零差异。
其余 `main` 侧变更全在 `src/**` / `tests/**` / `docs/**`，与 `web/**` 无交集。

#### 已识别但未做的协议项

`main` 的 AGENTS.md §16.4 要求「每个 ticket 完成后更新 `docs/PHASE_STATUS.md`」。
本分支按前端协议记在 `docs/SDD_TICKET_TRACKER.md`，**未写 PHASE_STATUS.md**——该文件既有
条目均为「合入 main 后回填」，故在交接触提示词 §6 提供了建议条目文本，由集成 AI 在
merge 后追加。这是本批的协议偏离，记录在案。

---

## 4. 真机验收批次（2026-09-11）：逐按钮巡检 + 刷新一致性

用户要求「用真实浏览器把每个功能按钮都点一遍，问题实时写进文档，并检查刷新后会话是否与刷新前一致」。本批不新增 ticket，交付物是**问题登记簿 + 修复 + 回归锁**。

- 登记簿（单一事实源）：`docs/FRONTEND_ISSUES_LOG.md`——含 74 行逐按钮巡检表、BUG-005/006/007、OBS-007～010、前后端归因、三轮 code-review 处置。
- 交接提示词：`docs/integration/FRONTEND_REFRESH_PERSIST_INTEGRATION_PROMPT.md`（§1 改了什么 / §2 真机取证 / §8 OBS-007）。

| commit | 内容 |
| --- | --- |
| `138b056` | BUG-005 刷新恢复选中会话 + BUG-006 在途 run 接回流（`after_seq=N` 重放+续流） |
| `21fb004` | 文档回填 138b056 |
| `03d6a70` | BUG-007 命令面板本地化 + 可搜索英文别名 |
| `b4181ad` | OBS-007 中断脉冲第四态 + 清 `run_interrupted` 标记（含审查 P3 处置） |

**已修**：BUG-005、BUG-006、BUG-007、OBS-007。
**判定为后端/非前端**（仅记录，未改）：OBS-008（`glm-5.3-flash` 工具成功后 `model/failed`）、OBS-009（bash 工具 10s 超时上限与 `retryable` 语义）、OBS-010（`GET /api/sessions` 的 `trace_id` 恒为 `null`，但会话详情事件里的 `trace_id` 正常，故 UI 的 Trace 命令实际可用——**原登记曾误判为「命令不出现」，已订正**）。
**已知覆盖缺口**：~~OBS-006 审批卡不可达（`auto_approve` 硬编码）~~ **已证伪并闭合（第五轮真机点击）**；`已中断` 脉冲态真实语料不可达（仅单测）；`pulse-interrupted` 类名字符串与 CSS 选择器无测试绑定。

**子会话刷新一致性（追加真机验证）**：委派 child `2515a128`（列表点击 / 「打开子会话」两条入口）与分叉 child `1fdac9b9`（410 事件）刷新前后正文指纹**逐字节相同**（日志见登记簿对应章节）。新增回归锁 1 例（×2 视口）——首版播种式被变异验证证伪（只覆盖读路径），已改为真实点击写入路径 + 按 id 区分事件。

**第三轮控制面清点（可核对方法）**：从源码枚举全部 **45 个 `<button>`**（17 文件）逐个核对。初版**关键词比对**不可靠（两个方向都会错：`保存`/`清除` 命中的是无关散文 → 令牌弹窗两键实际没点过却判 OK；`滚动到最新`/`恢复会话` 其实有覆盖却判缺失），**故改为逐个真机点击**。最终 **45 = 38 点过 + 1 补 e2e + 3 按设计不可达 + 3 瞬态窗口不可达**：

- **38 个真机点击通过**（本轮新验含：Inspector 5 tab、加载更早 200→410、时间线行跳转、终端行→工具焦点、io-tabs ×4、JSON 展开、返回父会话、代码块换行、**推理块展开**、**Inspect chip**、**Inspector 工具行**、**令牌保存/清除**、空态示例 chip）；
- `auth-banner-close` 本地不可达（后端仅配 `jwt_secret` 时 401）→ 新增 `web/e2e/l-auth-banner.spec.ts`（含变异验证）；
- **按设计不可达 3**：审批卡「批准」「拒绝」（`auto_approve` 硬编码，OBS-006）、`ContextProviderPicker`（本部署后端目录为空 → 正确不渲染）；
- **瞬态窗口 3 已在第四轮补齐**：`tool-out-wrap-btn`、`tool-out-jump`、`reasoning-jump` 原需「流式中 + 用户上滚」才渲染（cmd 缓冲输出使尾窗仅存毫秒级），已用 **mock 流钉住窗口**（不发 `tool/result` / `reasoning/completed` → 投影状态恒为 running/streaming）后**真实点击**并逐一变异验证，见 `web/e2e/m-stream-affordances.spec.ts`。

**最终覆盖账目（第五轮后）**：**45/45 全部已被点击**，其中审批卡「批准」「拒绝」为**真机点击**（真实后端 + 真实模型）。原记的「2 产品不可达」是**误判**并被证伪——审批卡由 `tool/approval-requested` 事件驱动（`projection.ts:514`），门在 `session/service.py:348`（`permission_mode_explicit`），与 `auto_approve` 无关；显式选「只读」后任何 workspace-write 工具都会触发。真机证据 + 回归锁见登记簿 OBS-006 订正条。**不再有「未验证」按钮。**

**新发现的后端问题（含根因行号，需后端修复）**：OBS-011 子进程输出按 UTF-8 解码而 cmd.exe 输出 GBK → **乱码固化进 JSONL**（`sandbox/local.py:166-167`，铁证：原始字节中 U+FFFD 与侥幸合法的 GBK 双字节混杂）；OBS-012 `bash` 工具在 Windows 实为 cmd.exe（`shell=True`，`local.py:161`）→ bash 语法 41ms 失败；OBS-013 provider 退化重复（2,868 delta / 186,507 字符的同句循环，3.5 分钟无工具调用，另见多次 `model/fallback … InternalServerError`）；OBS-014 bash 工具 10.0s 硬超时且 `retryable:false`。

**本批最终门禁（实跑）**：tsc ✓ · vitest **497 passed**（28 文件）· oxlint **35 warnings / 0 errors** · playwright **112 passed**（`--workers=2`：瞬态三键 4 例 + 审批卡 8 例）· vite build ✓。联调车道（`e2e-live/`）用例不计入主车道（已核验计数 0）。
**第四轮新 spec 的独立审查**：0 个 P0/P1/P2，6 项 P3 **全部已修**（头注释挂载条件、合成滚动划界、显式 `aria-expanded`、数值化可滚动断言、`toHaveCSS` 断生效样式、作废指针），并按修改后版本**重跑三处变异**（均红）。详见登记簿「第四轮收尾」。

**本轮审查（`l-auth-banner.spec.ts`）**：0 个 P0/P1，1 项 **P2** + 4 项 P3，**全部已处置**。P2 是**注释谎报覆盖**——我写「`api.test.ts` 测 401 分类」，实则全 `src` 测试树零个 401 引用（该缝当时**无单测**）。已把谎报改成事实：`api.test.ts` 新增 3 例（401→`UnauthorizedError`、广播 detail、**body 非 JSON 的回退文案**）。P3 中一项揭示了**真实行为被我注释说反**：关闭**不是**永久忽略（`App.tsx:148` 每次广播都会重新显示），故 e2e 改为走「配置令牌」真实路径断言**横幅重新出现**（变异验证：删掉 `refreshSessions()` → 两视口都红）。


---

## 第六轮（2026-09-11）：真实浏览器全量验收 + BUG-008

**环境前提（本轮结论必须带这条读）**：:8000 = **`feat/backend` worktree 的后端**（其 `.env` 的
`CAPABILITIES` **只启用 `websearch`**），5173 = 前端 dev server。前几轮跑的是 **main worktree 的后端**
（`.env` 里 `websearch` + **`multiagent`** 都开），所以两轮看到的语料与能力集**本来就不同**。

**刷新一致性复验（新增证据）**：会话 `3b35b83d`（35 事件·中断态）在 balanced 与 detailed 两档下，
刷新前后 `document.body.innerText` 指纹**逐字节相同**（`2235:1645848761` / `2309:2105849635`），
按钮指纹（74 键 `2032:3401835054`）、滚动位、tab 选中态、`ahi.selectedSession` 全部一致。
**视图状态**（tab / 滚动 / 折叠）刷新不保留——与既有冻结边界（Inspector 属视图状态、DSH 语义）一致，
**非缺陷**；本轮为「内容一致 + 视图状态不保留」补了并存的实测证据。

**BUG-008（已修，commit `365fbee`）**：后端序列化省略值为 null 的字段 → 无步号事件的 `step_id`
是**键缺失**（`'step_id' in e === false`），而三处消费点用严格 `!== null`：
- `StepDetail.tsx::formatEventTooltip` → hover 浮层渲染字面量 `step undefined`
- `StepDetail.tsx` 事件详情 Overview → 空值 `step` 幽灵行
- `eventKind.ts::streamKeyFromEvent` → 伪造 key `step:undefined`（违背它自己的「无 step → null」契约）
三处统一改宽松 `!= null`（与 `projection.ts::resolveStep` 既有口径一致）；明确否决「改后端」与
「在 `eventValidate` 归一化」。两文件各补「键缺失」红灯用例（TDD 先红后绿）。
**真机复验**：无 step 行浮层只剩时间戳、带 step 行仍显 `step 1`；幽灵行消失；跳转 pulse 正/负对照 1 / 0。

**本轮新增真机通过**：事件详情 io-tabs ×4 + `复制 JSON`/`复制 JSON`/`复制 Raw`（剪贴板 165/165/490 字，
均为 JSON）；工具详情 4 tabs（默认 Output）+ `复制 JSON`(32)/`复制输出`(85)/**两个 `复制 Raw`**(446 call,
685 result)；Timeline hover 浮层；**全局 Esc 取消**（fetch 记录器捕获 `POST …/cancel`，脉冲 `已取消`
中性通道，非红色失败）；代码块 `自动换行`↔`不换行` 往返 + `复制代码`（22 字与渲染正文**逐字相等**）；
中断会话的工具详情**零伪造**（无 tool/result 时不渲染 Output tab、Raw 只 1 个复制键）。

**本轮不可达（配置/语料原因，非产品缺陷）**：委派/子会话 5 项、`加载更早 N 条`、Trace 三件套、
四个 picker 搜索框、Context picker。其中委派 5 项与 `加载更早` **已在其他轮次真机点过**（第二轮
第 38/61 项；第三轮「加载更早 200→410」用的是 410 事件的 fork child `1fdac9b9`，属 main 后端语料）。
**真正的产品不可达只有 Trace 三件套**（需 Langfuse 启用）。详见登记簿 OBS-016。

**两条过程自查（值得记住）**：① **图标按钮必须按 `aria-label` 定位**——`CopyButton` 的 `innerText`
为空，按可见文本 `^复制` 找会得出「按钮不存在」的**误报**；② **门禁链路 `| tail` 会吞掉退出码**——
本轮一次 `1 failed` 被掩盖成「成功」，改用 `set -o pipefail` 后复跑 5 次全绿（那次失败**不可复现**，
已如实登记，不计为通过）。

**门禁（实跑）**：tsc 0 · vitest **507 passed / 0 failed**（28 文件）· oxlint **35 warnings / 0 errors**
· playwright **118 passed**（`--workers=2`）· vite build 0。

**观察（后端/provider，本轮未改）**：真实 run 中默认链 `deepseek-v4-flash-0731` **停顿 50s+ 且 token
零增长**，随后**模型回退按设计生效**（不变量 #9），由 `glm-4.5-air` 完成（时间线 `model/completed
glm-4.5-air · 6907 tok` → `run/completed 13873 tok`）。停顿期间 UI 全程只显示诚实的 `思考中 · Ns`
（不伪造进度、不假报错），但**没有任何「正在等待模型/即将回退」的中间态提示，且阈值偏长**——
建议后端更早发 fallback 事件（前端已有渲染通道）。

---

## 第七轮（2026-09-11）：类型诚实化（#147）+ 停顿提示（#148）+ `加载更早` 覆盖锁

| commit | 内容 |
| --- | --- |
| `ec2a961` | BUG-010/#147：`AgentEvent.step_id`/`run_id` 放宽为可选——类型不再对「键缺失」撒谎 |
| `9517e5d` | FE-01/#148：停顿提示（展示层旁注，不新增 SessionEvent） |
| `051aff6` | e2e：`加载更早 N 条` 真实点击锁（唯一零自动化覆盖的控件） |

**grill 轮的四个决策用户未作答** → 按各题推荐项执行（放宽类型 / `step_id`+`run_id` 同票 /
前端本地观察式 / 超时默认一律不改），已在 issue 正文与 commit message 里标注为
「未获用户确认的默认值」，用户可事后否决。

**门禁（末次实跑）**：tsc 0 · vitest **519 passed**（29 文件）· oxlint **0 errors**（37 warnings）
· playwright **126 passed**（`--workers=2`）· vite build ✓。

**真机证据**：真实后端 + 真实模型（Reasoning Effort=Deep）在一次 31s 首 token 等待上验证
停顿提示（出现时机、秒数语义、give-up 让位、重连后累计），完整时间线见
`docs/FRONTEND_ISSUES_LOG.md` 第七轮。

**关单**：#147、#148 均已关闭（comment 内含 AC 逐条证据与残留观察）。**未 push**。

**过程自查（值得记住）**：门禁的 playwright 与我另外两次 ad-hoc e2e **并发**跑，两个进程
写同一个 `test-results/` → `ENOENT ... .playwright-artifacts-*` → 门禁假失败 4 例
（其中 3 例是无关用例）。清掉并发、`rm -rf test-results` 后重跑全绿。**同一 worktree 里
不要并行跑两个 playwright。**

**集成提示词**：`docs/INTEGRATION_PROMPT_TYPE_HONESTY_AND_WAIT_HINT.md`。

## 第八轮（2026-09-12）：WS-5 #155 项目分组 UI（跨端票的前端半）

**背景**：用户诉求「一个项目下多个会话，和 zcode 一样」。后端 #152/#153/#154（feat/backend）
已交付 Workspace 实体、列表 `workspace` 契约与 9 个项目 CRUD 端点；本票做**可见性**。

| 交付 | 位置 |
| --- | --- |
| 契约层：`Project` / `ProjectStatus` / `ProjectDeleted` + 7 个端点 + `ProjectError` | `src/types.ts` / `src/lib/api.ts` |
| 纯函数：分组投影 `buildRailModel` + 重排锚点 `moveAnchor` / `dropAnchor` | `src/lib/projects.ts` |
| 数据与动作：`useProjects`（写后重拉，不维护影子名单） | `src/hooks/useProjects.ts` |
| 侧栏改版：项目块（折叠/行内重命名/菜单）+ 行（点选/菜单/拖拽）+ 未分组区 | `src/components/SessionList.tsx` |
| 三个浮层：新建 / 删除确认（明示只解除分组）/ 加入项目 + 行内重命名 | `src/components/ProjectDialogs.tsx` |
| 样式：层级导轨、菜单、拖放落点、错误条、浮层 | `src/styles/app.css`（纯新增 562 行） |
| e2e：6 用例 × 2 视口 + 有状态项目 mock | `e2e/r-project-groups.spec.ts` / `e2e/fixtures.ts` |
| 真机：无 mock 的真后端流程 + 基线逐字段比对 | `e2e-live/project-groups-live.spec.ts` |

**门禁（末次实跑，最终 revision）**：tsc 0 · vitest **561 passed**（30 文件）· oxlint
**0 errors**（37 warnings，均为既有规则；本票 10 个文件 0 warning）· playwright
**144 passed**（`--workers=2`，本票新增 14 例）· vite build ✓。

**两轴 code-review 后修复（commit `8db0e5f`，零 finding 后才收）**：独立 Spec / Standards
两轴 review 的发现里，有两条是**会在真机或流式下真实发生**的，值得记住：

- **mock 与真机语义相反**：e2e 的 attach 推队尾，真实后端写的是 `[session_id, *kept]`
  （**前插**，`workspace/index.py` + `tests/web/test_projects_api.py` 都锁着）。也就是说
  这条 AC4 用例在**真机后端下必然失败**——围栏里的绿灯不能证明契约一致，只能证明
  "前端与我的假后端一致"。已把 mock 与断言都改成前插。
- **memo 被内联箭头破功**：`onRetryProjects` 每次渲染新建 → 流式期间整片 Session Rail
  跟着每个 delta 重渲染（本仓库明文规则，`handleSelect` 一列同样处理）。已 useCallback。

其余修复：`SessionSummary.workspace` 从"只在注释里被消费"变成真的消费（项目不在列表里
时未分组行带 `staleProject` 注解，AC6 的字面要求）；Pydantic **422 的 detail 是数组**，
只认字符串会把"path must be an absolute path"降级成"注册项目失败（422）"；`useProjects`
补乱序响应守卫与 in-flight 合并；拖拽落点只在来源项目内亮；Enter 提交补 pending 守卫；
删掉 rail/选择列表上不成立的 `role=list`、折叠时的悬空 `aria-controls`、`<p>` 里塞 `<ul>`
的非法 HTML；空项目提示去掉一条**不可达**的引导（单段 workspace 建不出项目内会话）；
mock 的 order 端点补自锚点 no-op（缺它会插错位置）；新增 409 用例（cwd 不一致 → 后端原因
就地显示、归属不变）；AC3 断言改为打在**后端原始串**（`WinError 3` + 路径）上以证明透传。
`playwright.config.ts` 固定 `workers: 2`（§16.6 硬要求，避免"门禁绿、本地红"）。
`gui-test-screenshots/` 进 `.gitignore`（真机截图是本地证据，不进版本库）。

**真机**：真 uvicorn 8000 + 真 `.env`/`harness.db` + 真浏览器 5173，无 mock；注册/改名/attach/
detach/重排/软删除全走通，**结束时会话归属与项目账本与开测前逐字段相等**（状态已还原）。
截图 `web/gui-test-screenshots/ws5/`（本地留存、未入库：运行时产物，与既有各轮一致）。

**视觉检查逮到 1 个 e2e 抓不到的 bug**：`.rail-menu` 复用 `palette-in` 关键帧（含
`translateX(-50%)`）→ 菜单永久左移半宽；Playwright 点真实位置所以全绿，人眼一看就歪。
已改为独立 `rail-menu-in`（opacity + scale，配 Radix 的 transform-origin 变量）。

**关单**：#155 **不关**（跨端票：后端半在 feat/backend 尚未合入 main；按 §14.12 以 comment
记录已完成部分与剩余项）。

**未做 / 交后续票**（详见 `docs/FRONTEND_ISSUES_LOG.md` 第十轮）：
①`POST /api/sessions` 仍只接受单段 workspace 名 → **任意目录的项目拿不到"新建会话"入口**
（用户原始诉求的最后一块缺口，需后端契约变更）；
②注册项目不批量回溯 attach（契约不暴露会话 cwd，前端无法判定，不猜）；
③项目端点之外的 CORS `*`（后端既有）；
④窄屏 56px 折叠轨看不见会话行（既有规则，本票只追加了项目 chrome 到同一 hide 列表）。


---

## 第十二轮（2026-09-12）：MEM-5 #160 前端记忆管理 UI（跨端票的前端半）

**本批 commit**：`5eb4fed`（`feat/frontend`；父 commit `637bc89` = B-1 的 fixed point）。

**背景**：MEM-4（#159，后端半，已关单）给了用户侧两个入口（`GET /api/memories` 列表 +
`DELETE /api/memories/{id}` 硬删），但没有界面。用户看不到记忆库里有什么，也就无从判断该删哪条
——所以「用户入口」若只有 API 就等于没有（issue #160 的原话）。

| 交付 | 位置 |
| --- | --- |
| 契约层：`MemoryScope` / `MemorySummary` / `MemoryDeleted` + 2 个端点 + `MemoryError` / `isMemoryDisabled` / `describeMemoryError` + 窄化 `parseMemory` | `src/types.ts` / `src/lib/api.ts` |
| 纯展示逻辑：`scopeLabel` / `formatMemoryTime`（解析失败原样返回，不伪造）/ `hasMoreAfter` / `withoutIds` | `src/lib/memory.ts`（+ `memory.test.ts` 7 例） |
| 数据与动作：`useMemories`（打开时拉取 / 分页 / 乐观删除 + 两结局都重拉权威 / 503 降级与错误分流） | `src/hooks/useMemories.ts` |
| 浮层：列表（content + scope + 创建时间 + 长正文展开）+ 行内二次确认（「删除不可恢复」）+ 降级 / 空 / 错误 / 分页四态 | `src/components/MemoryPanel.tsx` |
| 入口 ×2：顶栏 Brain 按钮 + 命令面板「管理记忆」 | `src/components/TopBar.tsx` / `src/App.tsx` |
| 样式：浮层材质与项目浮层共用 + 记忆专属 26 条规则（纯新增） | `src/styles/app.css` |
| 契约测试：canonical fixture **类型注解**（ARCH-4b）+ 11 例（分页参数 / 畸形行剔除 / 404·403·503 分流 / 回执缺字段） | `src/lib/api.test.ts` |
| e2e：7 用例 × 2 视口 = **16 例**（列表渲染与翻页 / 长正文展开 / 二次确认 + 后端权威 / 失败回滚 / 503 降级 / 真空态 / 500 错误重试 / 命令面板入口） | `e2e/s-memories.spec.ts` + `e2e/fixtures.ts`（**有状态** memory mock） |

**门禁（实跑）**：`npx tsc -b` ✅ · `npx vitest run` **580 passed**（31 文件，+19）·
`npx oxlint` **0 errors**（38 warnings：37 既有 + 1 条本票与既有同类的 `set-state-in-effect`）·
`npx playwright test --workers=2` **160 passed**（+16 例）· `npx vite build` ✅。

**e2e 逮到的真 bug（值得记住）**：列表读取失败（500/网络）时，`visible.length === 0` 分支先命中
→ 面板会**同时**显示「还没有记忆」与错误条——正是 AC4 禁止的「把读不到伪装成没有」。
首版实现的判空顺序漏了 `loadError === null` 这一项；`s-memories.spec.ts` 的 500 用例
（`.memory-empty` 必须 count 0）把它钉死。修复：空态只在「确实读到空列表」时渲染，
「0 行 + 读取失败」只留错误条 + 重试。

**真机验收（真 .env / 真模型 / 真 Zilliz / 真 sqlite / 真浏览器）**：

| 步骤 | 结果 |
| --- | --- |
| 种子数据 | `.scratch/seed_real_memories.py`（后端 worktree，**不入库**）：走生产同一条 `build_builtin_memory_components` + `capability.consolidate()` 写入 3 条真实记忆。**实测 3 条都 `degraded=consolidation_failed: VectorStoreError`** —— 当时 Zilliz/embedding 不健康，按 #158 的「不丢写」设计降级成无条件 insert（记录行照样落盘，所以列表有内容） |
| 列表 | 真 `GET /api/memories` 返回 3 行；浏览器点开面板渲染 content / `用户` chip / 本地化时间 |
| 二次确认 | 真实点击：行内出现「这是硬删除，**删除不可恢复**——没有回收站，删掉后模型不会再想起这条。」+ 取消 / 确认删除 |
| 删除成功 | 真实点击确认 → 行消失；`curl` 复查后端只剩 2 行；后端日志 `memory forget via api: forgotten`（MEM-4 的结构化审计）；**整页刷新后再打开面板**该条依然不在（证明不是本地隐藏） |
| 删除失败回滚 | **杀掉真后端**后在界面上点确认删除 → 行**回到列表**（回滚）+ 该行确认条显示「删除记忆失败（502）」+ 面板错误条「加载记忆失败（502）」+ 重试；重启后端点「重试」→ 列表恢复一致（2 行） |
| 真空态 | 经界面把两条种子记忆都真删掉 → 面板显示「还没有记忆」（**不是**降级态、无错误条）；`curl` 复查后端 0 行 |
| 降级契约 | 另起一个 `CAPABILITIES={}` 的实例（:8001）：真 `GET`/`DELETE /api/memories` 都回 **503** + `memory capability 未启用：请在 CAPABILITIES 中配置 memory。` —— 与 e2e mock 里那句**逐字一致**（mock 的降级文案不是编的） |
| 视觉 | 暗 / 亮两色 + 行内确认条各截图复核：scope chip、时间、危险色确认条、按钮对比度在亮色下均可读（新增样式全部复用既有 token，无 §15 双份同步问题） |
| 环境还原 | 种子记忆**已全部经界面删掉**（真记忆库里不留假事实——否则模型会把「用户使用 Windows 11」当真的召回）；两个 dev server 已停（避免残留 uvicorn 占 `.instance.lock`，那是已知会打红 `test_web_lifespan_flushes_on_shutdown` 的坑） |

**关单**：#160 **不关**（见 integration prompt §5 / issue comment）：按票面「跨端 ticket 的前端半」
+ §14.12，用 comment 记录已完成部分与剩余项（剩余 = 合入 `main`，由集成 AI 执行）。
本 worktree 与 #155 同一处置。

### 批次审查（B-1，v2 §1.2；fixed point `637bc89`）

两轴（Spec + Standards）各派一个 read-only subagent，各审 `git diff 637bc89...decc7be` 全量
（16 文件 / +1780 行）。**Spec 轴 6 finding + Standards 轴 7 finding**，逐条处置：

| # | 轴 | finding | 处置 |
| --- | --- | --- | --- |
| 1 | 两轴一致 | **重拉的 `limit` 会越过后端硬上界**：`Math.max(rows.length, 50)` 在加载 >200 条后送 `limit=250` → 后端 422 → **删除失败的回滚重拉与"重试"永久失败**（AC3 直接破） | 修：`lib/memory.ts` 新增 `MEMORY_MAX_LIMIT=200` + `refetchLimit(loaded)`（`min(max(loaded,50),200)`），hook 三处调用点改用它；+3 单测（0/3/50 → 50；120 → 120；250/10000 → 200）。已登记的代价：>200 条时重拉只带回前 200，需再点"加载更多"（比永久失败诚实） |
| 2 | Spec | **404 删除失败被界面吞掉**：`deleteError` 按行 id 渲染，而 404（这条已被别处删掉）后重拉里那一行不在 → 错误无处渲染（AC3「失败要报错」不成立） | 修：`MemoryPanel` 增面板级错误条（同一错误唯一来源：行在 → 行内；行不在 → 面板级 + 「知道了」）；e2e 新增 `memoryVanishedIds` 接缝 + 1 用例 ×2 视口锁住 |
| 3 | Standards | **e2e 的 403 detail 是我编的中文**，真后端是 `PermissionError("Memory belongs to a different namespace")`（`sqlite_record_store.py:195` → `str(exc)` 直通）；AC3 的失败用例因此是自我实现 | 修：mock 与断言都改成真后端原文；404 同样照抄 `记忆不存在：<id>`；`api.test.ts` 两处 detail 也换真实原文（顺带当契约文档）。**这就是 #155 轮「mock 语义与真机相反」同一类坑** |
| 4 | Spec | **DELETE 挂死无超时**：行已乐观隐藏、确认条两按钮都 disabled → 行"点了删除就消失"，界面再也点不动（AC3 的失败路径缺失） | 修：新增 `lib/timeout.ts`（`withTimeout`，App.tsx 原先的私有实现迁入共用，fork 行为不变）+ `DELETE_TIMEOUT_MS=30s`；超时走与失败**相同**的回滚/对账路径；+4 单测（含"落地后清定时器"）。语义提醒写在模块头：超时 ≠ 对端没执行 |
| 5 | Spec | ARCH-4b 的说法**过强**（fixture 只能锁前端类型，锁不住后端加字段） | 修文档：集成提示词 §2 改写为「前端侧漂移 → tsc 红；后端侧权威锁 = `tests/web/test_memory_api.py`」 |
| 6 | Spec | AC4 的"检索不可用"在后端契约里**没有独立状态**（列表读权威记录；检索故障会走 500） | 只登记不改代码：503 = 未装配（降级态）；5xx = 读取失败（错误条 + 重试 = 事实上的"暂不可用"）。AC4 的两个词组分别由这两条通道承担 |
| 7 | Standards | `MemoriesState.rows` 导出但无消费方 | 修：去掉该导出（只留 `visible`），并在接口注释里写明为何不导出原始列表 |
| 8 | Standards | `remove` 未复用 `useProjects` 的 `after()` 包装，且未说明 | 修：加注释说明语义不同（`after` = 跑写 → 重拉 → 抛错；这里要"乐观隐藏 → 两个结局都重拉 → 失败先取消隐藏再抛"），**不**硬套 |
| 9 | Standards | `.project-dialog-*` 类名被记忆面板复用（Mysterious Name） | **不改**：改名要连带动 ProjectDialogs + app.css + 既有 e2e 选择器，属跨模块审美重构（§8 Scope Lock），已在 app.css 注明共用材质 |
| 10 | Standards | `describeMemoryError` 与 `describeProjectError` 同形（Duplicated Code） | **不改**：注释已声明刻意分开（两个能力各自演进，共用会让一侧语义渗到另一侧）；属判断项 |
| 11 | Standards | 协议 v2 §1.1 与 `AGENTS.md` §16.1（每票 review）并存矛盾 | **不改 AGENTS.md**（跨 worktree 共用文件，改了徒增 §16 那条已知冲突面）；以用户 2026-09-12 指令为最高优先级，v2 覆盖 §16.1，本工作树以本文件 + 协议文件为准 |
| 12 | Standards | `tsc` / `oxlint` 基线核对 | 实测：tsc 0；oxlint 38 warnings / 0 errors，**新增 1 条**（`useMemories.ts:99` 的 `set-state-in-effect`，与既有 37 条同类；挂载即拉取不可避免） |

**修复后门禁（实跑）**：tsc ✅ · vitest **587 passed**（+7：refetchLimit 3 + withTimeout 4）·
oxlint 0 errors（38 warnings）· playwright **162 passed**（+2：404 用例 ×2 视口）· vite build ✅。
**修复后真机复验**（真后端 + 真 Zilliz + 真浏览器）：种 3 条 → 经界面真删 1 条 → 后端 `curl` 剩 2 条
（DELETE 已走新的 `withTimeout` 包装，零错误条）→ 再删 2 条 → 后端 0 条 + 面板显示「还没有记忆」；
dev server 已停、真记忆库已清空（不留假事实）。

**未做 / 交后续**（Scope Lock，只登记不顺手做）：
① 记忆**编辑** UI（票面非目标；后端入口本票也没有）；② 批量清空 / 回收站 / 恢复（非目标）；
③ 冲突可视化（LLM 决策只体现在最终条目上，非目标）；④ 记忆条目的**检索/搜索**（本票只做分页列表，
用户要的是"看得见 + 删得掉"）；⑤ 真机侧没法自然构造 `403`（需要一条 SESSION scope 记忆，而 HTTP
入口只列 USER 行）——该路径由 e2e 的 `memoryDeniedIds` 拦截口覆盖（伪造的是**真后端会回的那句话**）。

---

## 关单补记（2026-09-12，用户指示「完成了就关闭」）

| 票 | 处置 | 证据 |
| --- | --- | --- |
| #160（MEM-5 前端半） | **已关**（reason=completed） | comment：完整 AC 证据（上一条）+ 关单核实（分支/commit/门禁/真机/移交项）；后端半 #159 已关并随 `165fe9d` 入 `main` |
| #155（WS-5 前端半） | **已关**（reason=completed） | comment：AC1–AC8 逐条证据 + commit 链（`f015a60`→`8db0e5f`→`637bc89`/`dca3ede`）+ 4 条 scope 外剩余项登记；后端半 #153/#154 已关并入 `main` |

核实要点：`main` 已由集成方合入后端批次（`165fe9d`）并回合 `feat/frontend`（`2b51914`，**未动 `web/**`**，
故本文件上方的门禁数字对合并后 HEAD 仍有效）；仓库 **OPEN issue 归零**。
移交集成 AI：`feat/frontend` → `main` 合并 + push + `docs/PHASE_STATUS.md` 回填。
此前各节写的「本票不关单」是当时的 §14.12 处置（跨端票只完成一端），随两端齐备 + 用户指示而更新，
历史小节按「当时事实」保留不改。

---

## 第十一轮验收修复（2026-09-13，前端侧 · 在途记录）

> 来源：`docs/FRONTEND_ISSUES_LOG.md` 第十一轮（后端 AI 在验收车道真机逐控件点击后提出的前端项）。
> 本轮**没有 GitHub ticket**（finding 记在登记簿），故进度记在这里；合入 `main` 后由集成 AI 回填
> `docs/PHASE_STATUS.md`。分支 `feat/frontend`。

| 修复 | commit | 内容 | 回归锁 |
| --- | --- | --- | --- |
| **ART-01**（P1） | `47b2644` | `artifact/externalized` 接线到 Artifacts 页签（此前只接了 spec 里的 `artifact/created` → 生产路径上页签恒空且给错误结论） | `projection.test.ts` 两条 + 真机 |
| **MOD-01**（P1） | `65c8b7b` | 选「默认链」改为提交默认条目名（新增 `lib/modelSelection.ts`）；真机 `fb3619c6` 写出 `seq9 {to=None}` | `modelSelection.test.ts` 5 条 + 真机 |
| **APR-01**（P1） | `2c5adbd` | 孤儿审批（run 终结仍 pending）转只读失效态 + **解锁 composer**；404 → `ApprovalGoneError`（不再当可重试错误） | `projection.test.ts` 5 条 / `api.test.ts` 2 条 / `ApprovalCard.test.tsx` 4 条 / e2e 2 条 + 真机 |
| **FE-R11-04**（P2） | `59673ef` | 短目录搜索框隐藏时把初焦交给 listbox（cmdk 的方向键承接者在 `[cmdk-root]` 内）；新增 `lib/pickerFocus.ts` | e2e「短目录键盘导航（不手动聚焦 listbox）」**变异验证过** |
| **FE-R11-05**（P2） | `59673ef` | 单选 ControlPicker 首项「默认（未选）」（提交 `null`） | e2e 往返 + `pickControl` 下标顺延 |
| **FE-R11-06**（P2） | `59673ef` | 勾选态从 `aria-hidden` 的 ☑ 移到 `role="option"` 的 `aria-checked` + listbox `aria-multiselectable` | e2e 断言 true/false 往返 |
| **FE-R11-07**（P2） | `59673ef` | `selectedIds ∩ entries` 后再计数与 toggle（幽灵项） | 单测 2 条 |
| **FE-R11-08**（P2） | `8e8f0ab` | 空白重命名就地拦截（提示 + 保留编辑态 + `aria-invalid`） | e2e AC4 三段 |
| **FE-R11-09**（P2） | `8e8f0ab` | 窄屏 ≤820px 删除入口恢复（槽位共享：会话点 ↔ ⋯，⋯ 绝对定位不挤可点面积）；顺带修正被同一规则误伤的 `.session-item-dot` | e2e 800px 视口全流程 + 槽位切换断言 |
| **FE-R11-10**（P2） | `8e8f0ab` | 删除确认弹窗初焦从「关闭(X)」改为「取消」 | e2e 焦点断言 + 零 DELETE |
| **测试基建** | `59673ef` | `pickControl` 退出动画竞态（Escape 后不等卸载再 open → 选中静默失效） | helper 内注释 + 探针复现记录 |

**门禁**（每次 commit 前跑，最后一次：`feat/frontend` HEAD `8e8f0ab`）：
`npx tsc -b` 干净 / `npx vitest run` **659 passed（38 文件）** / `npx oxlint` 0 error /
`npx playwright test --workers=2` **226 passed** / `npx vite build` 绿。

**未修（需产品决策，已开 issue）**：
- **#180** Split/Preview 占位模式（现状可点但只插提示条）——收敛为「诚实未实现」态还是做真副面板；
- **#179** 窄屏 ≤820px 项目级操作（重命名/删除项目/新建会话）无入口（与 FE-R11-09 同源但作用在项目层）。

**交给集成 AI**：`feat/frontend` → `main` 的合并与 push（本 worktree 只做本地 commit，不 push）；
成功后回填 `docs/PHASE_STATUS.md`。合并顺序：先 `feat/backend`（含 spec #173 T1–T4 的 4 个 commit），
再 `feat/frontend`（本表 4 个 commit）——详见 `docs/INTEGRATION_PROMPT_SPEC_173_T1_T5.md`（backend worktree）。

---

## 第十四轮：#179 / #180（2026-09-13，前端侧 · 在途记录）

> 来源：backend agent 在第十一轮真机验收里开的两张**决策票**（#179/#180）。用户 2026-09-13 裁决：
> #180 走**路线 A（诚实占位）**；#179 走票面**选项 1（项目行保留槽位）**。

| 票 | commit | 内容 | 回归锁 |
| --- | --- | --- | --- |
| **#179**（P1） | `4fe1ab8` | ≤820px 不再收起 `.rail-project-head`——项目级操作（重命名/删除项目/在此项目中新建任务）恢复入口。沿用会话行槽位交换语义（文件夹图标 ↔ ⋯）；标题/计数/箭头收起，项目名进 `.rail-project-toggle` 的 `aria-label`（`display:none` 会把它从可访问性树摘掉）；行内重命名在编辑态向右溢出（否则 56px 轨里只剩 ~40px，能开不能用） | `r-project-groups.spec.ts` 新增窄屏 describe（800×900）：⋯ 可达 + 菜单项与宽屏逐字一致 + 删除确认面；重命名 **PATCH 后刷新重取仍在** + 量输入框宽度 >100px |
| **#180**（P1） | `4fe1ab8` | Split/Preview 从"可点但只插提示条"收敛为**诚实占位**：`disabled` + `aria-disabled` + `title`，说明文本同时进 accessible name；删掉 `workspaceMode` 状态、`.workspace-scaffold*` 样式与分支；Chat 成唯一可选（`aria-pressed`）模式 | 新增 `workspace-modes.spec.ts`：disabled/aria-disabled/title/说明文本、`force` 点击不选中、无 `.workspace-scaffold` 残留、恰好一个 `sel` |

**门禁**（`feat/frontend` HEAD `4fe1ab8`，含新增 3 条 e2e）：
`npx tsc -b` 干净 / `npx vitest run` **659 passed（38 文件）** / `npx oxlint` 0 error /
`npx playwright test --workers=2` **240 passed** / `npx vite build` 绿。

**⚠ 订正上一节的"226 e2e 全绿"**：那条是 `59673ef` **之前**的跑分，之后没有重跑全量，所以
`8e8f0ab` 的全量 e2e **实际是红的**——`u-project-task.spec.ts:114` 仍断言权限档 `toHaveCount(3)`，
而同一批 commit 给单选 picker 加了首项「默认（未选）」（=1+3=4）。本轮全量跑把它暴露出来，已改为
逐档断言三档都存在（保留 AC10②「三档都真的可选」的本意）。教训：**改了共享控件就要重跑全量**，
只跑"受影响的那几个 spec"会漏掉按数量断言的下游用例。

**同时修正的测试脆弱写法**：`r-project-groups.spec.ts` 里对行内重命名的 Enter 改用
`page.keyboard.press`。行内输入的 Enter 处理器会立刻提交并**卸载自己**，而 `locator.press` 在
keydown 之后还要对同一元素补发 keyup——元素已不在就会重新解析定位符并等到 30s 超时（失败快照里
改名其实已经成功）。该失败在全量并行下偶发（单独重跑 6/6 通过），属测试写法问题，非产品缺陷。

**新发现（已开票，未修）**：
- **#181**：窄屏的 ⋯ 依赖 `hover` / `focus-within` 让位——**触摸设备**（无 hover、iOS 上
  `button` 默认不聚焦）可能仍然拿不到菜单。会话级（FE-R11-09）与项目级（#179）同款问题，
  已开票等产品裁决（推荐 `@media (hover: none)` 下常显 ⋯）。
  → **已修**：第二十三轮（按推荐方案 1 落地，纯 CSS + 触摸 e2e 锁）。

**两轴 code-review（Standards + Spec）结论**：Standards 轴 1 条硬 finding（spec §3 仍写死
"38 = 36 + 2" 与仅广播名单，与"不再手工维护枚举"的前提自相矛盾）→ 已改为"以生成物为准"并写明
本文件 MUST NOT 写死名字/数量；另 2 条 judgement call（行格式写入端/读取端重复、生成器校验
理由未写明）→ 已抽 `format_row()` + 加往返测试 + 补注释。Spec 轴 1 条（#173 AC6 的状态文档
未随交付更新）→ 已同步登记簿/PHASE_STATUS。

**交给集成 AI**：`feat/frontend` → `main` 的合并与 push（本 worktree 只做本地 commit）。

## 第十五轮：#182（2026-09-13，前端侧 · 在途记录）

**交付**：`9320e72`（`feat/frontend`，本地 commit，**未合入 main、未 push**）。票面
`docs/WORKSPACE_PANEL_TICKETS.md` § #182；母 PRD `docs/WORKSPACE_PANEL_PRD.md` §2/§3.2。

**做了什么**：中心列从"固定模式条"换成**能力声明显隐**的 tab 集（`GET /api/capabilities`
此前前端**零消费**）。Split / Preview（#180 的 disabled 诚实占位）按 Brief 与
BENCHMARK_SYNTHESIS 的取舍删除。

| 文件 | 内容 |
| --- | --- |
| `web/src/lib/capabilities.ts`（新） | 声明键 → 可见名的**唯一登记处**；解析；显隐派生；tab 集派生；方向键目标键 |
| `web/src/components/WorkspaceTabs.tsx`（新） | `role="tablist"` + roving tabindex，键盘只接回纯函数 |
| `web/src/App.tsx` | 删模式条残留；加能力拉取（失败降级）；每个可见面一个稳定 id 的 tabpanel |
| `web/src/styles/app.css` | `.workspace-mode*` → `.workspace-tab*`；`.workspace-panel[hidden]` 显式覆盖 |
| `web/src/lib/api.ts` | `getCapabilities()` |
| `web/e2e/fixtures.ts` | capabilities mock + 错误注入 + `onCapabilitiesGet` 计数口 |
| `web/e2e/workspace-modes.spec.ts` | 改写为守卫（7 条用例 × 2 视口） |

**门禁（全绿）**：`tsc -b` 0；`vitest` **690 passed**（+31：能力语义 27 + tab 条 ARIA 4）；
`oxlint` 0 error（41 warnings 全为既有）；`playwright --workers=2` **252 passed**；
`vite build` 0。

**两轴 code-review 的处置（4 项实修 + 1 项保留并说明）**：

| finding | 处置 |
| --- | --- |
| **P1** AC6 无端到端证明：三种 mock 都塌成 `['Chat']`，"压根没调端点"也会照绿 | 加 `onCapabilitiesGet` 计数断言（≥1 且不再增长=无请求循环）；AC6 的完整口径（声明为真 → 出现）**如实记为待 #189/#190**，并写进两张票面 |
| **P2** 每个 tab 的 `aria-controls` 会悬空（单 panel 换 id），单测还把悬空引用钉死 | 改成一个面一个**稳定 id** 的 tabpanel（非激活 `hidden`，不卸载），`aria-controls` 全部可解析 |
| **P2** 注释称"只改 `implemented: true` 即可"，照做会得到空白面板 | 注释与票面均写明：**必须同时**接 `App.tsx` 的面板渲染 |
| **P3** 解析了不消费的 `display_name` | 从 DTO 删掉（只留 `surfaces` + `id`） |
| **P3** `centerTabs` 的 `registry` 参数只被单测用到 | **保留**并说明：它是纯函数的入参，单测用它验证"实现落地后同一函数即渲染"这条规则；生产调用不传（默认值即真实登记表）。§8 的担忧是"为未来造抽象"，这里换来的是规则可测 |

**顺带订正的两处文档矛盾**：票面与 PRD 的"建议顺序"原写 `#185 → #190 → … → #182 → …`，
与两处依赖图（#189 / #190 依赖 #182 的骨架）矛盾——已订正为
`#185 → #182 → #190 → #184 → #183 → #189 → #186` 并写明理由（先做内容面会把 tab 条写两遍，
或写出一个挂不上去的面板）。

**发现的既有测试现象（未修，非本票引入）**：无。

**交给集成 AI**：`feat/frontend` → `main` 的合并与 push（本 worktree 只做本地 commit）。
集成提示词见 `docs/INTEGRATION_PROMPT_PANEL_182.md`。

## 第十六轮：#190（2026-09-14，前端侧 · 在途记录）

**交付**：`8605668`（`feat/frontend`，本地 commit，**未合入 main、未 push**）。票面
`docs/WORKSPACE_PANEL_TICKETS.md` § #190；母 PRD `docs/WORKSPACE_PANEL_PRD.md` §3.5。
依赖 #182 的骨架已就位，故本轮把「输出」面接上。

**做了什么**：中心列新增第二个面「输出」（能力 `terminal` 显隐）。**不叫 Terminal**——
本项目没有 PTY（`sandbox/local.py` 是一次性 `subprocess.Popen`），叫 Terminal 等于承诺一个
不存在的输入能力；只读输出的业界先例都叫 Console / Logs（Replit 把 Console 只读与 Shell
可输入拆成两个东西），故命名「输出」并在面内明示能力边界。

| 文件 | 内容 |
| --- | --- |
| `web/src/lib/commandOutput.ts`（新） | `isCommand` / `commandResult` / `commandOutputs` / `commandOutputText`——"什么算一次命令"的唯一答案 |
| `web/src/lib/commandOutput.test.ts`（新） | 10 条：判定、结果优先于活块、空串不成块、stdout+stderr 合并 |
| `web/src/components/ToolOutputStream.tsx`（新） | 从 `ToolCard.tsx` **原样搬移**；新增 `showCaret` / `expandable` 两个开关 |
| `web/src/components/OutputPanel.tsx`（新） | 只读说明（**两个分支都有**）+ 按工具调用分组 + 就地展开 + `等待输出…` |
| `web/src/lib/projection.ts` | `allTools` 单一走法（Inspector 与「输出」面共用） |
| `web/src/components/StepDetail.tsx` | `TerminalTab` 改用 `isCommand` / `commandResult`（**渲染零变化**） |
| `web/src/lib/capabilities.ts` | `terminal.implemented = true`（与 `App.tsx` 的渲染成对） |
| `web/src/App.tsx` | `tab.key === 'terminal'` → `<OutputPanel tools={tools} />` |
| `web/e2e/x-output-panel.spec.ts`（新） | 7 条 × 2 视口；#182 骨架期守卫按票面注释**翻转** |

**门禁（全绿）**：`tsc -b` 0；`vitest` **701 passed**（+11：#190 命令聚合 10 + 登记表 1）；
`oxlint` 0 error（41 warnings 全为既有，新文件零 warning）；`playwright --workers=2`
**266 passed**（+14）；`vite build` 0。

**两轴 code-review 的处置（1×P1 + 5×P2/P3 全修）**：

| finding | 处置 |
| --- | --- |
| **P1** 运行中的命令会画出 `.stream-caret`，正撞 AC5"不得出现光标" | `ToolOutputStream` 加 `showCaret` 开关，「输出」面传 `false`；新增专门用例断言 `.stream-caret` 计数为 0 |
| **P2** 运行中且尚无输出时写"这次命令没有输出。"（假事实） | 改 `等待输出…`，并加用例反断言不出现"没有输出" |
| **P2** 我曾另写一份并行读取器，偏离 AC2"复用既有聚合逻辑" | 抽出 `isCommand` / `commandResult`，`TerminalTab` 反向改用它们（一条走法） |
| **P2** AC3 只做了截断、没有"就地折叠" | `expandable`：工具条出现「展开全部（共 N 字符）/ 收起」，e2e 用头尾标记证明"展开前头部不在 DOM" |
| **P2** 嵌套滚动条（面板 + 输出体各滚一次） | CSS 覆盖：`.output-list` 独占滚动，`.tool-out-body` 取消 200px 上限 |
| **P3** 同一段输出两个复制按钮；空态缺只读说明；终端样式图标 | 删头部复制键；只读说明提到两个分支之前；`TerminalSquare` → `ScrollText` |

**AC 逐条对照**：AC1 ✅面内明示 / AC2 ✅分组+复制（**复用**既有逻辑，反向收敛为单一实现）/
AC3 ✅就地展开（与 #186 同策略：就地、不新开导航面、单一渲染器）/ AC4 ✅能力为假不渲染 /
AC5 ✅e2e 断言无输入类元素、无"运行"键、无光标 / AC6 ✅7 条用例 / AC7 ✅`TerminalTab`
渲染逐字未变（它此前只渲染 stdout、漏 stderr，属**既有**缺口，AC7 明令不动故本票不改）。

**顺带**：修了我自己在本轮引入的一处孤立注释（`bashResult` 删除后其文档注释悬在
`TerminalTab` 上）；并订正了一次 commit message——初版写成"TerminalTab 补上 stderr"，
与 AC7 事实不符，已 amend（未 push，故安全）。

**发现的既有测试现象（未修，非本票引入）**：Inspector 的 `TerminalTab` 只读
`result.stdout`、不显示 `stderr`；「输出」面经 `ToolOutputStream` 是通道保真的。两处差异
本身是 AC7 的必然结果，但"同一个概念两处看到的不一样"值得单独记一笔（建议在 #183 里决定
是否对齐）。

**交给集成 AI**：`feat/frontend` → `main` 的合并与 push（本 worktree 只做本地 commit）。
集成提示词见 `docs/INTEGRATION_PROMPT_PANEL_190.md`。

## 第十七轮：#184（2026-09-14，前端侧 · 在途记录）

**交付**：`3a57924`（`feat/frontend`，本地 commit，**未合入 main、未 push**）。票面
`docs/WORKSPACE_PANEL_TICKETS.md` § #184；母 PRD §3.6。票面 2026-09-14 修订后本票**只剩
PERMISSION 段**（原"ARTIFACTS run 级段"已取消——Artifacts 由清单 tab 承担）。

**做了什么**：Inspector 从"5 段 + CHECKPOINT 诚实占位"补上没有的 PERMISSION 段。
**零新 API**——全部来自事件流投影。

**关键判断（权限档从哪来）**：`permission_mode` 不在任何 SessionEvent 里，也没有 GET
接口（后端只在 `POST /sessions` 收它用于构造 PermissionPolicy，`SendMessage` 不带它 ⇒
档位在会话创建时定死）。所以"这个 run 选了哪一档"前端**根本无从得知**；唯一带运行时证据
的是审批请求里的 `policy`。结论：整个会话无审批事件就显示 `—` + 说明原因，
**不拿 composer 里"下次运行的选择"冒充会话事实**（那是另一个语义，画上去就是假事实）。

| 文件 | 内容 |
| --- | --- |
| `web/src/types.ts` | `approval_decisions`（裁决留痕）+ `permission_policy`（逐事件折叠） |
| `web/src/lib/projection.ts` | 决议留痕（幂等）+ 权限档折叠；`pending_approvals` 队列语义不变 |
| `web/src/lib/permission.ts`（新） | 段内措辞与语义色档（`decisionLabel` / `verdictTone` / `permissionView`） |
| `web/src/components/StepDetail.tsx` | `PermissionSection`（MODEL 与 CHECKPOINT 之间）+ `onJumpToApproval` |
| `web/src/components/Conversation.tsx` | 审批卡加 `data-approval-key` 落点；jump 查询多一个命名空间 |
| `web/src/App.tsx` | `jumpToApproval`（key 前缀 `approval:`，与 `tool:`/`step:`/`delegation:` 不相交） |
| `web/src/styles/app.css` | `.detail-permission-*` + `.permission-verdict-allow/-deny` |
| `web/e2e/x-permission-section.spec.ts`（新） | 3 条 × 2 视口 |

**门禁（全绿）**：`tsc -b` 0；`vitest` **717 passed**（+16：投影 7 + 措辞 9）；
`oxlint` 0 error（41 warnings 全为既有，新文件零 warning）；`playwright --workers=2`
**272 passed**（+6）；`vite build` 0。

**自审（两轴）修掉的三处，都在本票新代码里**：

| finding | 处置 |
| --- | --- |
| **P2** 只读行复用 `.detail-tool-row-static`，但同特异度下后出现的 `.detail-permission-row` 的 `cursor: pointer` 会胜出 → 静态行显示成**假按钮**（正是本批一直在守的诚实规则） | 改专属 `.detail-permission-row-static`，并把"必须排在其后"的顺序原因写进 CSS 注释 |
| **P2** 缺失/未知决策会被涂成**绿色**（绿 = 已批准，是一条断言） | 新增 `verdictTone`，只有真的 `approve*` 涂绿，未知/缺失一律 neutral；加单测 |
| **P3** 我加了一层纯透传的 `derivePermission`（只是把三个字段抄一遍） | 删掉，`permissionView` 直接读投影状态 |

**AC 逐条**：1 ✅（三段齐）／2 ✅（零待审批说「无待审批」，段不消失）／3 ✅（**未**新增
ARTIFACTS run 级段，CHECKPOINT 保持诚实占位）／4 ✅（`—` + 原因，不填 0）／5 ✅（投影与措辞
单测 16 条 + e2e 3 条，e2e 含"点待审批行 → 滚到审批卡并 pulse"）／6 ✅（未改 POST /approve）。

**顺带发现（未修，非本票引入，已升级为待用户决策项）**：**artifact 写入侧从未接上**。
生产里唯一的外置写入者是 `ArtifactOverflowHandler`，而它在 `assembly.py` 只在
`artifact_store_*`（S3）分支被创建（`minio_*` 分支只注册**读**工具 `ReadArtifactTool`，
没有写入者），这与 `config.py:69-72` 自己的注释（"MinIO 用于 tool result 外置"）**相反**。
且 `D:\intelligence-agent`（用户实际运行的那份）`.env` 里 ARTIFACT/MINIO/S3 键**一个都没有**
⇒ `overflow_handler=None` ⇒ 什么都不外置。后果：#185 的读取接口在真机上只会回 503，
#186「artifact 内容可见」落地后也会**看不到内容**。规格 06 §3 写明默认 Provider 是
"Local filesystem：开发/小型部署"，而 `storage/` 下**没有** Local 实现——这是规格 Gap，
不是新需求。**已报告用户等待决策，未擅自实现**（§8/§9.1）。

**交给集成 AI**：`feat/frontend` → `main` 的合并与 push。集成提示词见
`docs/INTEGRATION_PROMPT_PANEL_184.md`。

---

## 第十八轮：#183（2026-09-14，前端侧 · 在途记录）

**交付**：`6426a55`（`feat/frontend`，本地 commit，**未合入 main、未 push**）。票面
`docs/WORKSPACE_PANEL_TICKETS.md` § #183；母 PRD §3.0（Linear/Notion/VS Code 三条
peek 范式）、§3.1（键位表）、§3.7。

**做了什么**：Inspector 从"清单**或**详情"变成"清单**+**详情"。此前 `focus` 非 run 时
组件在最上面早退成"只有详情"，Timeline 清单整个消失——而 Timeline 好用的原因正是
"清单与详情同框"。这是本票唯一的**结构性**改动，其余都是它的配套（键位、钉住、整页、
拖宽）。

| 文件 | 内容 |
| --- | --- |
| `web/src/lib/inspectorPanel.ts`（新） | 纯逻辑：拖宽夹取 / ↑↓ 边界 / Space 阈值 / Esc 三层 / 行身份（eventKey·toolKey） |
| `web/src/components/StepDetail.tsx` | 去早退分支 → `.detail-body` 清单+peek 双滚动区；面板键位；头部三键 + 拖宽手柄；行 `aria-current`；Timeline 按需扩窗；Output 段改走 `ToolOutputStream` |
| `web/src/App.tsx` | 面板视图状态（pinned/expanded/width/peekOpen）+ `onPanelAction` 单入口；栅格 `--inspector-w`；整页 class；命令面板整页项；未钉住切会话收起 |
| `web/src/styles/app.css` | `.detail-resizer` / `.detail-ctrl` / `.detail-peek(-head/-body)` / `.timeline-row.sel` / `.detail-terminal-row.sel` / `.inspector-fullpage` |
| `web/e2e/y-inspector-peek.spec.ts`（新） | 7 条 × 2 视口 |
| `web/src/components/StepDetail.peek.test.tsx`（新） | 结构契约 13 条（同框 / 关闭不卸载 / aria / 单一渲染器） |

**AC 逐条**：1 ✅（点一行即预览；↑↓ 移动选中，详情跟随且清单不消失，只有一行
`aria-current`；两端不环绕）／2 ✅（Esc 关预览但面板与清单都在、DOM 里仍在；Space 快按
保持打开、按住 450ms 松手关闭）／3 ✅（点击即选中即预览，键盘只是加速）／4 ✅（钉住 →
切会话不收起；未钉住 → 离开会话才收起，首次进入不算离开；不持久化，刷新回 false）／
5 ✅（面板按钮 + 命令面板两个入口；Esc 先退回整页）／6 ✅（320→480 夹取、中心列 ≥360、
刷新回 320）／7 ✅（三键 `aria-label` + `aria-pressed`；拖宽手柄 `separator` + 左右键
16px/Shift 64px）／8 ✅（e2e 7 条覆盖 ↑↓/Esc/Space/钉住跨会话/整页往返/拖宽不持久化/
键盘可达）／9 ✅（Inspector 工具 Output 段改走中心列同一个 `ToolOutputStream`；
ChangesTab 的 `.diff-cols` 收敛属 #186 AC3，本票不动）。

**门禁（全绿）**：`tsc -b` 0；`vitest` **749 passed**（+32：inspectorPanel 19 +
peek 结构 13）；`oxlint` 0 error（**44** warnings = 基线，新文件零 warning、新代码
零 warning）；`playwright --workers=2` **286 passed**（+14 = 7 条 × 2 视口）；`vite build` 0。

**三处设计决定（记录理由，避免"看起来能用"）**：

| 决定 | 理由 |
| --- | --- |
| **钉住 = 面板跨会话保持展开**（未钉住时"离开正在看的会话"才收起面板，首次进入不算离开） | AC4 的"钉住后切换会话/选中不自动收起"只有这条读法能让 pin 有可测的差异；另两种读法都会自相矛盾——"peek 跨会话存活"会拿 A 会话的事件站在 B 会话里（违反 #22），"选中即收起面板"直接违反 AC1/AC3。首次进入必须豁免，否则"点开第一个会话"会把手动打开的面板关掉 |
| **Esc 三层（整页 → 预览 → 收起面板）** | 一层都不分层会撞 AC1/AC5：整页时 Esc 若直接收起面板，"退回"就只剩按钮一条路；有预览时 Esc 若要收起面板，用户"关掉这层"的意图会被解释成"关掉整个面板"。面板内的 Esc `stopPropagation`，面板外仍归全局"中断流式"（既有行为不变，e2e 未回归） |
| **拖宽 `available` 用实测的「中心列 + 面板」宽度**，不在 CSS 里给中心列兜 min-width | rail 在 <820px 变 56px，用常量算上限会在断点上算错；而给中心列加 `minmax(360px,1fr)` 在空间不够时会让栅格溢出，`.app-regions` 是 `overflow:hidden` ⇒ 直接裁掉（比压窄更糟） |

**自审（两轴）修掉的三处，都在本票新代码里**：

| finding | 处置 |
| --- | --- |
| **P1**（e2e 抓到）`.detail-peek` 的 `display:flex` **盖过** UA 的 `[hidden]{display:none}` ⇒ 预览"关掉"后照常占位显示 | 补 `.detail-peek[hidden]{display:none}`，并在注释里指向同款老账 `.workspace-panel[hidden]` |
| **P2** 窄面板（<360px，**默认 320 就在此区间**）隐藏 `.detail-ctrl-label` 后，三键的可访问名会变成空（icon 是 `aria-hidden`） | 三键补显式 `aria-label`（名说"是什么"、`aria-pressed` 说状态） |
| **P2** `ToolEventSections` 的默认段用 `useState` 初值 ⇒ 选中项移动时旧段不存在 → 预览空白（AC1 的"实时跟随"当场破功） | 渲染期收窄（同 #182 `resolveActiveTab` 口径）；另修 Timeline 扩窗从 effect-setState 改为渲染期派生（消掉 `react(set-state-in-effect)`） |

**顺带发现（未修，非本票引入，留痕）**：`tabCounts.terminal` 用 `t.name === 'bash'`，
而 `TerminalTab` 的行用 `lib/commandOutput.isCommand`——两处判据不同（注释却写着"逐字
一致"），badge 计数与列表行数在非 bash 命令工具上会对不上。**不在本票范围**（#183 只
要求"清单里能移动选中"，本票的 `listTargets` 用的是**行自己**的判据 `isCommand`，与
所见一致），交后续票据或用户决定。

**交给集成 AI**：`feat/frontend` → `main` 的合并与 push。集成提示词见
`docs/INTEGRATION_PROMPT_PANEL_183.md`。

---

## 第十九轮：#189（2026-09-14，前端侧 · 在途记录）

**交付**：`3e9b150`（`feat/frontend`，本地 commit，**未合入 main、未 push**）。票面
`docs/WORKSPACE_PANEL_TICKETS.md` § #189。

**做了什么**：把中心列的「文件/改动」面从"声明了但渲染不出来"补成真的能看。既有能力
接口一直把 `changes` 声明为 true，但登记表里 `implemented: false`（骨架期刻意压住），
因为中心列没有对应内容。本票补数据投影 + 面板 + CSS，并把登记表翻到 `true`。

| 文件 | 内容 |
| --- | --- |
| `web/src/lib/changedFiles.ts`（新） | 纯逻辑：写工具白名单 / net 行差 / 归档或截断 → `null` / 按 path 聚合 |
| `web/src/components/ChangesPanel.tsx`（新） | 左清单 + 右逐次改动（每次一个 `DiffBlock`）；只读；空态文案 |
| `web/src/lib/capabilities.ts` | `changes` → `implemented: true`（成对标记注释） |
| `web/src/App.tsx` | `tab.key === 'changes'` → `<ChangesPanel tools={tools} />` |
| `web/src/styles/app.css` | `.changes-*`（两栏 grid / 选中态 / 统计徽章 / 窄容器堆叠） |
| `web/e2e/z-changes-panel.spec.ts`（新） | 3 条 × 2 视口 |
| `web/src/components/ChangesPanel.test.tsx`（新） | 10 条（含 AC4 只读断言） |
| `web/src/lib/changedFiles.test.ts`（新） | 19 条 |

**AC 逐条**：1 ✅（只列本会话真的改过的文件；工具名白名单与后端 `_WRITE_TOOL_NAMES`
对齐）／2 ✅（同一文件多次改动聚合成一行，右侧按时间序全部列出）／3 ✅（点文件名 →
右侧显示各次改动，每次一个 `DiffBlock`，复用既有唯一 diff 渲染器，不新写）／4 ✅（无
`<input>`/`<textarea>`/`contenteditable`，无保存/应用/撤销按钮，SSR 测试断言）／5 ✅
（内容归档 → 统计渲染 `—` 并给 title 说明，不给假数字）／6 ✅（无改动 → 空态文案逐字
「本次会话未改动任何文件。」）／7 ✅（清单行 `aria-current`，键盘可达）／8 ✅（e2e 3 条
× 2 视口：两次改动一行 + 点选切换 + 归档 `—` + 空态）。

**门禁（全绿）**：`tsc -b` 0；`vitest` **778 passed**（+29：changedFiles 19 +
ChangesPanel 10）；`oxlint` 0 error（**44** warnings = 基线，新文件零 warning）；`playwright
--workers=2` **292 passed**（+6 = 3 条 × 2 视口）；`vite build` OK。

**三处口径决定（记录理由，避免"看起来能用"）**：

| 决定 | 理由 |
| --- | --- |
| **统计口径是 net（首版 before → 末版 after 的行多重集差），不是各次相加** | 改 3 行再加回 3 行显示 `±0`，而不是 `+3/-3`。相加口径会把"改完又改回"渲染成"改动很大"，是假热度；用户看这个面想知道的是"这个文件现在跟原版差多少" |
| **归档 / 截断时 `added/removed` 为 `null`，UI 渲染 `—` + title** | 内容已经不在事件里（转 artifact 或超 50KB 截断），任何数字都是编的。宁可说"不可得" |
| **没有 path 的改动计入 `unattributed` 并在脚注提示** | 静默丢弃会让"列出的文件"与实际改动不符；计数 + 脚注是唯一诚实的做法 |

**实现过程中被测试抓到的一个真缺陷（已修）**：`tool/call` 投影读的是 `data.tool_name`
而不是 `data.name`（后端事件字段就是 `tool_name`）。我的 e2e fixture 一开始写了 `name`，
结果工具名解析成 `unknown` → 不进写工具白名单 → **0 行文件、测试全绿**（因为断言写的是
"空态"）。修 fixture 后才真正跑通。顺手把 `y-inspector-peek.spec.ts` 里同一个字段也
改正（那条用例不依赖工具名，所以没暴露）。教训：e2e fixture 的字段名写错会"静默降级成
另一种合法状态"。

**登记表翻转的连带修复**：`capabilities.test.ts` 原有一条骨架期守卫断言"`changes` 声明
为真也不渲染"。`changes` 落地后这条守卫失去对象，改为**注入一个未实现的 `artifacts`
面**来继续覆盖同一条规则（"声明为真但无实现 → 不渲染"），另两条强行 `implemented: true`
的用例简化成直接用真实 `SURFACES`。`workspace-modes` AC4/AC6 的期望 tab 集同步更新。

**顺带发现（未修，非本票引入，留痕）**：见第十八轮末尾 `tabCounts.terminal` 用
`t.name === 'bash'` 与 `lib/commandOutput.isCommand` 判据不一致的问题——**本票也没修**
（Scope Lock），但本票在 `ChangesPanel` 侧统一走 `lib/changedFiles` 的单一判据，没有
复制第二份。

**交给集成 AI**：`feat/frontend` → `main` 的合并与 push。集成提示词见
`docs/INTEGRATION_PROMPT_PANEL_189.md`。

---

## 批 2 审查：#183 + #189（fixed point `2ae4e38`，2026-09-14）

两轴独立审（Standards = 仓库规范 §7/§8/§9/§15/§16.6 + Fowler smell 基线；Spec = #183/#189
票面 + PRD §3.0/§3.1/§3.3/§3.4 + 本 tracker 的 AC 自述当成**待核实的声明**），
累计 diff 19 文件 / +2556 −123。**修复 commit `868e05e`**（本批审查状态推进到这里）。

### 两轴收敛到同一处

两个轴**各自独立**指出：Inspector 的 `ChangesTab` 仍内联 `.diff-cols`，与中心列的
`DiffBlock` 是同一份 before/after 的两套渲染。这不只是重复——Spec 轴同时算出它的**后果**：
那套内联渲染**认不出归档态**，会把 marker 摘要当文件正文显示出来，即"显示了一段并不存在
的文件内容"。这是本轮唯一一条**用户可见的错误数据**，因此即使它形式上属 #186 AC3
（本批的下一票），也在本批直接修掉：AC9 是 #183 自己的验收项，不能带着"部分满足"关批。

### findings 与处置

| # | finding | 轴 | 处置 |
| --- | --- | --- | --- |
| 1 | `ChangesTab` 内联 `.diff-cols`，与 `DiffBlock` 双重渲染；且认不出归档态（**显示假内容**） | 两轴 | **已修** → 改为调用 `DiffBlock`；+4 条 SSR 用例（含"marker 原文不得出现在正文"） |
| 2 | `./src/a.ts` 与 `src/a.ts` 落成两行，违反 AC2"不得一个文件多行" | Spec | **已修** → 折前导 `./`（可证等价）；大小写/分隔符**刻意不折**并写明理由；+2 条用例（折 / 不折各一） |
| 3 | `changedFiles` 重载：数组形态只有测试在用，注释声称的理由（"最常见调用点"）不成立 | Standards（Speculative Generality） | **已修** → 单一返回形状 + 调用点与 7 处测试同步 |
| 4 | `ChangesPanel` 同一脚注 JSX 写了两份 | Standards（Duplicated Code） | **已修** → `UnattributedFootnote` |
| 5 | `App.tsx` 的 `default: return cur` 在闭合联合上不可达 | Standards | **已修** → 删除；tsc 确认穷尽性成立 |
| 6 | `ChangesPanel.test` 只查"没有 `+N`"，伪造的 `-M` 不会被抓到 | Standards（测试不过硬） | **已修** → 提取统计徽标的可见文本逐个断言；**不**拿整页 HTML 匹配 `-\d`（属性值会命中，那测的是标记） |
| 7 | e2e AC6 号称覆盖 `CENTER_MIN_W`，但默认视口下永远到不了那条分支 | Standards + Spec | **已修（改断言落点，不假造覆盖）** → 见下"结构性发现" |
| 8 | `apply_patch` 零覆盖：漏掉它会让这类改动整类从面板消失 | Standards | **已修** → 新增逐名断言三个写工具都在集合里 |
| 9 | `--inspector-w` 的 CSS 回退值 `320px` 与 `INSPECTOR_MIN_W` 可漂移 | Standards | **不改**，理由见下 |
| 10 | 写工具集合与后端 `_WRITE_TOOL_NAMES` 跨语言复制，没有测试能抓漂移 | Standards | **不改**（本 worktree 读不到后端源码）；已核对两端当前一致，记为已知风险 |
| 11 | 非 chunks 的纯文本输出回退仍是自己的 `<pre>`，比中心列少了 grep 截断尾巴的标记 | Spec（AC9 partial） | **不改**，转 #186（需把 `TruncationAwarePre` 从 ToolCard 抽出） |

### 两条**必须纠正的自述**（原 tracker 把它们记成 ✅，与事实不符）

1. **#183 AC9 不是"已完成"**，而是"diff 与 chunks 输出已收敛，纯文本回退未收敛"。
   第 1 条已修（diff 侧现在真的是单一渲染器），第 11 条仍未收敛——它**不是本批引入**
   （`!hasChunks` 回退是既有代码，本批只加了 `hasChunks` 分支），但 AC9 的文字没有
   限定范围，所以记 ✅ 是overclaim。
2. **#189 AC5 的"归档 → 统计不可得"在生产里走不通**。投影把
   `archived`/`artifactId` 设在 `parseArtifactMarker` 成功之后，而前端正则抓的是
   `use inspect_artifact\(([^)]+)\)`，后端 `tooling/overflow.py:118` 发的却是
   `use read_artifact({artifact_id})`——**两端对不上**。所以 `archived` 永远是 false，
   `DiffBlock` 的归档占位与 #189 的 `—` 统计都是**死路径**，e2e 用合成 fixture 才走通
   （那条用例测的是前端自己的正则，不是端到端）。这正是 **#186 AC4**，已列为
   Ticket D 的**首要**修复项（它同时决定 #186 AC2 的"就地展开"能不能被触发）。

### 结构性发现（因此第 7 条不能靠 e2e 覆盖）

三栏栅格只在 **≥1201px** 生效，那里 `available = viewport − 240 ≥ 961`，
`available − CENTER_MIN_W` 恒 > 480 ⇒ **`CENTER_MIN_W` 在当前布局下永不生效**，
上限恒为 `INSPECTOR_MAX_W`。`<1200px` 的折叠分支把面板列写死成 280px，所以 e2e
**构造不出**"上限真的咬住"的宽度。结论：该保护是**防御性**夹取（换 rail 宽度、加第四栏、
或提高 `INSPECTOR_MAX_W` 时才会生效），**只由单元测试**覆盖
（`clampInspectorWidth(480, 700) === 340`）。已在 `inspectorPanel.ts` 写明，并提醒
改布局的人；e2e 的注释也改成只声称它真正锁住的东西（接线：拖拽确实走到夹取、中心列没被挤没）。

### 未改的三条与理由（不是遗漏）

- **第 9 条**（CSS 回退值）：`var(--inspector-w, 320px)` 的回退值在任何渲染路径上都被
  `App.tsx` 的内联 `--inspector-w` 覆盖，即它本身不可达；为它加测试要绕开"CSS 不进
  vitest"这件事，收益低于成本。真正的漂移保护是注释（已有）。
- **第 10 条**：前端 worktree 里没有后端源码，e2e 又全程 mock API ⇒ 端内没有能
  "抓漂移"的测试位置。当前两端逐字一致已人工核对。**若后端改这三个名字，前端会静默
  少文件**——这条风险建议在集成时由集成 AI 复核一次。
- **第 11 条**：转 #186。抽 `TruncationAwarePre` 是动一个本批未触碰的文件，
  且属 #186 明写的"单一渲染器"范围，放在本批做会把 diff 扩到票据之外。

### 门禁（全绿）

```
cd web
npx tsc -b                            # 0
npx vitest run                        # 785 passed（+7）
npx oxlint                            # 0 error / 44 warnings（= 基线）
npx playwright test --workers=2       # 292 passed
npx vite build                        # 0
```

**抖动留痕**：修复后首次全量 e2e 有 1 条失败（`r-project-groups.spec.ts` AC4 项目内重排）。
单独跑该 spec **22/22 通过**，全量重跑 **292 passed**。判为已知的 `--workers=2`
资源竞争型抖动（本批改动只碰 Inspector 的 Changes 面 / 中心列「文件/改动」面，与该 spec
的项目分组无关）。**未**顺手改该 spec（Scope Lock）。

### 本批状态

- 批 2 审查**结束于 `868e05e`**（修复 commit）——下一批的 fixed point。
- 修复触及 `ChangesTab` 的渲染契约与 `changedFiles` 的聚合语义，按流程做**增量复查**
  （只复查上轮 findings）+ **变异验证**（不只看"修完是绿的"）：把 `ChangesTab` 换回
  内联 `.diff-cols`、把聚合键换回原始路径后，新增用例**4 条转红**
  （路径折叠 1 条 + ChangesTab 3 条），恢复修复即 44/44 转绿——第 1/2 条确实被新用例
  锁住，不是"看起来覆盖了"。其余 diff 逐行自查。
- 仍未修/转为下一票的：第 9/10/11 条 + 上表两条自述纠正中列出的跨端 marker 缺陷（#186）。

---

## 第二十轮：#186（2026-09-14，跨端：后端 `d925899` + 前端在途记录）

**交付**：后端 `d925899`（`feat/backend`）+ 前端两个 commit（`feat/frontend`，均**未合入
main、未 push**）。票面 `docs/WORKSPACE_PANEL_TICKETS.md` #186；依赖 #185（已 CLOSED，
路由在 `feat/backend`，**尚未在 main 上**——见下"集成顺序"）。

**为什么这票是跨端的**：AC4 说"统一 marker 文案（两端同步）"。查下来这不是文案偏好，
而是一处**两端都对不上**的真实缺陷（详见下）。

### AC 逐条

| AC | 状态 | 证据 |
| --- | --- | --- |
| 1. Artifacts 清单保留并可读；三态如实，失败显示后端 detail 原文 | ✅ | `ArtifactViewer.tsx`（加载/拿不到/拿到）；503 与 404 **分开说**（`api.ts` 的 `ArtifactContentError.kind`）；SSR 11 条 + e2e 4 条（含真网络 503/404） |
| 2. 被截断处就地展开，与清单同一渲染器 | ✅ | 归档 diff → `DiffBlock` 内的 `ArtifactViewer`；命令输出外置 → 工具卡 L2 的同一个 `ArtifactViewer`（判据是投影的 `tool.artifact`，不在视图里解析 marker）；不新开导航面（e2e 断言无 dialog/浮层） |
| 3. diff 收敛为唯一渲染器 | ✅ | **已在批 2 完成**（`868e05e`），本票不再动 |
| 4. marker 两端同步 + 加测试 | ✅ | 见下"跨端缺陷" |
| 5. types.ts 补齐内容字段（含**元数据可空**） | ✅ | `ArtifactSlice`/`ArtifactSliceLine` 新增；`ArtifactRef` 三个元数据字段改为**可空**并停止填默认值 |
| 6. 测试（含 e2e 至少一条"外置 diff → 就地展开 → 可见"） | ✅ | e2e `z-artifact-content.spec.ts` 5 条 × 2 视口；SSR `ArtifactViewer` 11 条 + `DiffBlock` 4 条 + `ToolCard` 4 条 |
| 7. 内容面板不得成为第二真相 | ✅ | 内容按需取、只存"这次请求的状态"，**不写回** `ConversationState`；切换会话/artifact 即重取 |

### 跨端缺陷（AC4 的实质）：marker 两端的工具名对不上

后端外置摘要在 `tooling/overflow.py` 里写死 `use read_artifact(<id>)`，前端
`toolShapes.ts` 却只认 `use inspect_artifact\(...\)`。**两端都对不上**，后果不是显示难看，
而是：

```
parseArtifactMarker → null ⇒ diff.archived / artifactId 永不置上
⇒ DiffBlock 的归档占位、#189 面板的"统计不可得"在生产里全是死路径
```

（这套 UI 此前只在 e2e 里活着——因为 fixture 用的是前端自己那个拼法。）

**根因不止"文案不一致"**：读回工具是**与 store 成对**的，配对表在
`storage/artifact_select.py`：

```
S3    → inspect_artifact
MinIO → read_artifact
Local → read_artifact     （Local 是 spec 06 §3 的默认 Provider）
```

所以"统一成一个名字"是**错的**——S3 部署上摘要会指向一个没注册的工具名。正确做法是
**让摘要点名它自己那个部署配对的工具**，前端两个名字都认、并把名字原样带下去：

- 后端 `d925899`：`ArtifactOverflowHandler` 收 `read_tool_name`，`assembly` 从选择器
  **实例化出的那个工具**上取 `.name`（不在 assembly 再写字面量，否则配对知识有了第二处）。
- 前端第一段：`parseArtifactMarker` 返回 `{artifactId, toolName}` 且两个名字都认；
  `toolName` 经 projection → `tool.diff.artifactTool` → `changedFiles` → `DiffBlock`
  一路透传；`DiffBlock` 的提示与复制按钮用 marker 里的名字（前端不知道、也不该猜这个
  部署用哪个 store）。

回归守卫：`tests/test_assembly.py` 三个 Provider 分支各断言摘要点名的工具名（S3 那条是
本缺陷的守卫）；**变异验证**——把 marker 改回写死 `read_artifact`，S3 用例即失败。

### 内容可见（AC1/AC2）的取舍

| 决定 | 理由 |
| --- | --- |
| 拆成 `ArtifactContentView`（纯渲染）+ `ArtifactViewer`（取数） | 本仓组件测试是 SSR（无 jsdom）⇒ 异步取数在测试里不会 resolve。拆开后三态可逐条断言，取数交给 e2e 走真网络 |
| 只在**展开后**才请求 | 未展开就请求 = 替用户读了他没要的东西（且会让清单渲染 N 个请求） |
| 归档 diff 处**抑制**通用 `tool.artifact` 渲染 | 归档 diff 的 `tool.diff` 与 `tool.artifact` 指向**同一个** artifact；两处都渲染会出现两个同名同效的按钮（e2e 的 strict mode 先抓到了它） |
| 工具卡的展开判据用投影的 `tool.artifact`，不解析 marker | 标记长什么样是后端的事；用投影 = 一份真相（AC7），且同时覆盖命令输出与通用结果两条外置路径，不必各写一遍 |
| 元数据缺失显示"未知"而不是默认值 | #185 AC4 明令"缺失即 null/省略，不得伪造成空串或默认值"；编一个 `0 B`/`application/octet-stream` 是在替后端撒谎（AC5 的"元数据可空"）

### 门禁（全绿）

```
# 后端
ruff check src tests                  # All checks passed
pytest -q                             # 2203 passed / 10 skipped / 42 deselected

# 前端（cd web）
npx tsc -b                            # 0
npx vitest run                        # 809 passed
npx oxlint                            # 0 error / 44 warnings（= 基线）
npx playwright test --workers=2       # 302 passed
npx vite build                        # 0
```

### 集成顺序（重要）

`#185` 的内容路由**只在 `feat/backend` 上，main 上还没有**（main 的最新日志自己写着
"backend 在途 #185 不并入"）。所以集成必须：

```
feat/backend  → main   （#185 路由 + #192 外置链路 + d925899 的 marker 配对）
feat/frontend → main   （#186 的消费侧）
```

**顺序反了的话，前端的"查看内容"会 404**——不是前端 bug，是端点还没进 main。

### 未做 / 转交

- **归档 diff 的"就地展开"在 URI 上是"会话级"**：`ArtifactViewer` 只按
  `(session_id, artifact_id)` 取，这是 #185 路由的契约，没有别的取法。
- `tabCounts.terminal` 与 `TerminalTab` 行判据不一致（第十八轮留痕）、`--color-warning`
  这类 legacy 别名在旧代码里的用法——**都不是本票引入**，未动（Scope Lock）。
- 真机联调未做（本 worktree 无可用后端进程）；e2e 全程 mock，`#185` 的真实响应形状
  以 `web/app.py:1229-1330` 的 `ArtifactSlice.model_dump()` 为准。

**交给集成 AI**：按上面的顺序合并与 push。集成提示词见
`docs/INTEGRATION_PROMPT_PANEL_186.md`。

---

## 第二十一轮：总门禁（前端对 `main` 全量两轴审查 · 2026-09-14，前端侧 · 在途记录）

**范围**：`git diff 00d7f95...HEAD`（= 本批 19 个 commit、**52 文件 / +7498 −457**），
覆盖 #182 / #183 / #184 / #189 / #190 / #186。两轴（Standards + Spec）各派一个
read-only subagent **独立**审全量 diff（不是只看我改过的地方）。

**修复 commit**：`09afbe5`（代码）+ 本文件与提示词（文档）。

### 结论摘要

交付内容在单元/e2e 层面是实的（AC 逐条可证），但本轮查出**一条 P0 属"用户看不到"**：

| # | 轴 | 严重度 | finding | 处置 |
| --- | --- | --- | --- | --- |
| 1 | Spec（两轴交叉验证） | **P0** | **中心列两个新面在真实部署里不可达**：`centerTabs` 要求"声明为 true **且**已实现"，实现侧两半都在（`implemented:true` + `App.tsx` 面板），但**声明侧永远不为 true**——`web/app.py:918-927` 对未声明 `surfaces` 的 descriptor 一律给 `changes/terminal/artifacts = false`，而 `capability/wiring.py` 里 7 个 descriptor（memory/skills/mcp/knowledge/multiagent/websearch/ticker）**没有一个填 `surfaces`**，`ProviderConfig` 是 strict 无该字段 ⇒ 配置也填不进。`workspace-modes` / `x-output-panel` / `z-changes-panel` 能看到是因为 e2e **注入了 `changes/terminal: true`**——后端发不出这种载荷 | **不按代码缺陷修**（见下"为什么不改代码"），改为：订正 `INTEGRATION_PROMPT_PANEL_189.md` 的错述 + 开票 **#193** 跟踪声明侧 |
| 2 | Standards | P1 | **Inspector「Output」段取数反转**：只要留过流式块就用 `tool.output`，无视已到达的 `result`（>512 块还可能被投影合并/重排）⇒ 同一个 bash 调用在 Inspector 与中心列/「输出」面显示**不同文本**。`#190 AC7`（"不得改变 Inspector 侧既有行为"）与 `#183 AC9`（同一数据一个渲染器）都在这条上 | **修**（`09afbe5`）：命令走 `lib/commandOutput.ts` 的终态优先级；**只在有流式块时纠正**（无块时保留原"结果树"，那里还有 `exit_code`/`cancelled`）。变异验证：还原 → 用例红 |
| 3 | Standards | P2 | `parseArtifactSlice` 注释说"缺字段抛错"，实现给 `total_lines/returned_lines` 填 **0** ⇒ 形状不符时渲染"共 0 行"的**假空产物** | **修**：两者改为必须在场；+3 单测（含变异验证） |
| 4 | Standards | P2 | `ArtifactViewer.retry()` 丢弃 `load()` 的清理函数 ⇒ 存活标记恒 true，重试在飞时卸载仍 setState | **修**：改 ref，且臂化/释放在同一 effect（**单独一个"仅卸载置 false"的 effect 会被 `StrictMode` 的模拟卸载永久关掉**——`main.tsx:13` 确是 StrictMode，故按此形状写） |
| 5 | Standards/Spec | P2 | `tabCounts.terminal` 用字面量 `t.name === 'bash'`，`TerminalTab`/`listTargets` 用 `isCommand`（今天同形，但"什么算一次命令"有两个答案，撞 #190 AC2） | **修**：收敛为 `isCommand` |
| 6 | Standards | P2 | `ChildSessionView` 又写了一遍 `turns.flatMap((t) => t.tools)`，而 `allTools` 正是本轮为此建的单走法 | **修**：改 `allTools(conversation)` |
| 7 | Standards | P2 | 新增 CSS 用 legacy `--color-*` 别名（20 处），`index.css:150` 明写"新代码别用" | **修**：换回原始 token。别名一对一映射、两主题都有定义 ⇒ **视觉零变化** |
| 8 | Spec | P2 | "Inspector 纯文本段仍与自己一套 `<pre>` 渲染"（#183 AC9 的残余） | **部分修**：命令路径已收敛（第 2 条）；**非命令工具的 JsonTree vs `TruncationAwarePre` 的呈现差异保留**并在此登记为 AC9 残余（详见下） |
| 9 | Spec | P2 | `workspace-modes` AC6 / `fixtures.ts` 注释过期（"今天没有任何非 Chat 面实现"） | **修**：`fixtures.ts` 注释重写为"真实后端默认仍为 false，见 #193"；#182 AC6 的骨架期口径保留（当时事实） |
| 10 | Spec | P2 | `z-changes-panel.spec.ts:120` 用 S3 marker（`inspect_artifact`），而默认 Provider 是 Local（`read_artifact`） | **不修**：核对该用例**没有**声称"默认部署"；两种拼写都有覆盖，且 `z-artifact-content.spec.ts` AC4 专门断言 `read_artifact` 被认出、`inspect_artifact` 不出现 |
| 11 | Spec | P2 | Artifacts **Inspector tab** 不走能力声明（与中心列的闸门不对称） | **不修**：该 tab 是既有面（#182 只给中心列上闸门），且 #184 AC3 / #186 AC1 都以"该 tab 恒在"为前提。属登记项，不属本批缺陷 |

### 为什么不按代码缺陷修 P0（决策记录）

三条路都评估过：

1. **前端把 `changes`/`terminal` 默认翻 true**——会推翻用户已批准的语义（PRD §3.2 / Q4：
   "tab 集 = chat + **当前能力声明为 true** 的面"），并让 `workspace-modes.spec.ts:42`
   那条"后端真实默认响应 → 只有 Chat"的**刻意断言**失去意义。属产品决策，不擅自改。
2. **后端给某个 capability descriptor 填 `surfaces`**——7 个 descriptor 分别是
   memory/skills/mcp/knowledge/multiagent/websearch/ticker，**没有任何一个**产出
   `changes`/`terminal`（那两个面由**内置工具** bash/write/edit/apply_patch/git diff 产出）。
   挂在插件上等于如实性倒退（不变量 #21）。
3. **开票 + 订正文档**——`PHASE_STATUS.md` 2026-09-07 已把"capability surfaces 装配"
   记为**延后到 Phase 6** 的既有计划项；补声明属该阶段工作，不属本批（§8 Scope Lock
   不提前做未来 Phase）。故：订正错述 + 开 **#193**（含两个候选方向与验收建议）。

**票面 AC 与"用户可见"的区分**：#182 AC6 / #189 AC8 / #190 AC6 要求的是
"声明为真 → 出现"（已逐条满足，e2e 用显式声明钉住），本批**没有** AC 要求
"默认配置下用户可见"。所以这是**声明侧的缺口**，不是本批实现缺陷——但它决定了
交付物是否被真实用户看到，必须显式记账（先前 `INTEGRATION_PROMPT_PANEL_189.md` 写
"此前能力接口声明为 true 但被登记表压住"，**与事实相反**，已订正）。

### AC9 残余（如实登记，不改）

`#183 AC9` 要求"同一数据不得两份独立渲染"。本批收敛了 **diff 路径**（全走 `DiffBlock`）
与**命令输出路径**（全走 `ToolOutputStream` + `commandOutputs`）。残余：**非命令工具**的
Output 段，Inspector 用 `JsonTree` / `<pre>{truncateForDisplay(...)}</pre>`，中心列
`GenericBlock` 用 `TruncationAwarePre(truncateForDisplay(stringifyForDisplay(result)))`。
保留理由：① 底层格式化已共用（`truncateForDisplay` 同一份），差异是**呈现形态**
（树 vs 文本）；② `TruncationAwarePre` 的诉求（高亮 grep 的截断后缀）只对文本结果有意义；
③ Inspector 的 Output 段是"语义入口"、JsonTree 更贴它的角色；④ 改它要动已被本轮审过的
面，收益是形态统一、风险是回归——不值得在总门禁这一轮做。若产品要统一，单独开票。

### 门禁（全绿，`09afbe5`）

| 项 | 结果 |
| --- | --- |
| `npx tsc -b` | 干净 |
| `npx vitest run` | **813 passed / 48 files**（+3：本次新增的解析用例） |
| `npx oxlint` | **0 error** / 44 warnings（全部既有类别：e2e 未用导入、`set-state-in-effect`、`only-export-components`、`refs`） |
| `npx playwright test --workers=2` | **302 passed**（5.9m） |
| `npx vite build` | 绿（仅 chunk >500kB 的既有提示） |

**门禁抓到的回归（值得记）**：第 2 条修复的第一版把**所有**命令的输出段都换成
`ToolOutputStream`，`StepDetail.test.tsx`「有 result 时默认 Output 选中」当场红——
bash 的 `exit_code` 不再渲染（那棵结果树才有）。这正是总门禁要有全量单测的理由：
新用例（AC9）绿、旧用例（exit_code 可见）红，两者共同把形状钉成"只在有流式块时纠正"。

### 关单与移交

- #183 / #186 / #189：**代码完成、门禁全绿，但未合入 main**。按 §14.12 关单 comment
  写明分支（`feat/frontend`）与 commit（`09afbe5` / 本文件 commit），并注明集成由
  集成 AI 执行；#189 的 comment 必须同时指向 **#193**（声明侧，未完成前用户看不到该面）。
- **#193 保持 OPEN**（后端声明侧，本批不做）。
- 移交集成 AI：先 `feat/backend` → `main`（#185 的路由只在那条分支，否则前端"查看完整
  内容"404），再 `feat/frontend` → `main`，然后按集成提示词冒烟。
  提示词：`docs/INTEGRATION_PROMPT_PANEL_FINAL_GATE.md`。

## 第二十二轮：#193（2026-09-14，跨端：后端 `21f5427` + 前端在途记录）

票：#193「GET /api/capabilities 未声明 changes/terminal：中心列两个新面在真实部署里不可达」。
上一轮把它标为「保持 OPEN（后端声明侧）」——本轮后端做完了，前端这一半是**跟着改载荷口径**。

### 后端那一半（`feat/backend`，commit `21f5427`，本仓看不到）

新增 `capability/manifest.py`：条目形状与保守默认收敛到唯一一份 `manifest_entry()`，
并补一条 `id="core"` / `provider="builtin"` 的条目由端点**恒发且排在最前**——
`changes`/`terminal` = true（产它们的 `write`/`edit`/`apply_patch`/`bash` 在
`assembly.build_runtime` 里无条件注册），`artifacts` = false（要部署配了 store 才读得到），
`actions` 如实（permissions/stop/resume = true 对应三个真路由，retry = false）。
票面方向 2（给插件 descriptor 填 `surfaces`）被否：那两个面不由任何插件产出，挂上去是假话。

### 前端改了什么（8 文件，+142 / -55；**运行时代码零行为改动**）

1. **e2e 改吃真实默认载荷**（`fixtures.ts` 新增 `CORE_CAPABILITY`，逐值镜像后端的
   `manifest.py`；`routeApi` 的 capabilities 缺省从 `[]` 改为 `[CORE_CAPABILITY]`）：
   - `workspace-modes.spec.ts` AC2/AC3 → 「真实默认 → `['Chat','文件/改动','输出']`」；
     新增 `capabilities: []` 一条覆盖"目录真的为空"（老后端 / 降级路径）；
     AC4 用真实默认 + 调用计数证明端点确实被消费；
     新增并集语义用例（core + 插件全 false → 三面仍在）。
   - `x-output-panel.spec.ts` / `z-changes-panel.spec.ts`：去掉注入，走真实默认。
   - AC6 的**逐面独立矩阵**保留：故意不含 core，否则 `changes`/`terminal` 无法互不牵连地验。
2. **`m-stream-affordances.spec.ts` 的严重模式冲突**（本票在前端唯一一处真会被卡住的修）：
   `ToolOutputStream` 是对话卡与「输出」面共用的那一个渲染器（#190 AC9），#193 之后
   「输出」面在默认载荷下真的存在了，而它带同一个工具的一份输出（`App.tsx` 的 `hidden`
   面板，不卸载）⇒ 裸类名 `.tool-out-body` / `.tool-out-wrap-btn` / `.tool-out-jump`
   同时命中两处（strict mode 报两个元素），而藏起来那份 `scrollHeight === 0`，
   "容器必须可滚动"的前置断言会**假失败**。三条 locator 按面板 id 收窄到
   `#workspace-panel-chat`（本用例要验的就是对话里那张工具卡）。
   顺带订正 `ToolCard.tsx:301` 那条 #190 之后已过期的行号引用。
3. **注释/文档订正**：`capabilities.ts` / `api.ts` / `capabilities.test.ts` 里指向后端的
   **行号引用**被本票重写端点时作废 ⇒ 改成函数名/模块名（跨仓行号必漂移，本仓既有惯例就是
   `web/app.py::SessionSummary` 这种写法）。`CORE_CAPABILITY` 的漂移说明改成如实口径。

### 双轴 code-review（findings 全部处理）

- **Standards ①** `x-output-panel.spec.ts` 一处**孤儿 JSDoc**：它描述的"不注入声明"那组用例
  已被删掉，注释现在贴在 `DISABLED` 上方、与自己正下方那条自相矛盾 ⇒ 合并重写。
- **Standards ②** 三处 e2e 注释自称"**端到端证明**"是过头话：Playwright 拦了
  `/api/capabilities`，**请求不出网**，它证不了"后端真发 core"⇒ 改为如实口径（锁的是
  **前端消费侧**；后端那一半由 `tests/web/test_web_phase2_endpoints.py::TestCapabilities`
  真走 HTTP 端点锁）。
- **Standards ③** 后端 `app.py` 的"条目形状只定义一次"是**跨仓**口吻 ⇒ 后端侧收窄为
  "后端一份 + 前端镜像"，并点名两端各自的守卫测试（后端那半已同步改）。
- **Spec ④（AC2 部分达成，记为残余）**："用真后端形状的载荷"只能做到**逐值镜像**——
  跨仓无共享来源，**后端改值前端测试不会红**。`fixtures.ts` 已把这条链"为什么断、由谁守"
  写清楚；集成提示词把它列为"合并后按真实端点人工对齐"的必做项。
- **Spec ⑤（AC4 语义已被并集改变，不当作退化）**：core 恒在 + 前端取并集 ⇒ 插件写
  `changes: false` 不再能让面消失。那是"这个插件不产出"而非"会话产不出"。闸门仍由
  **不含 core 的载荷**证明（`capabilities: []` → 只剩 Chat；AC6 逐面矩阵）。正确读法已写进
  后端 `ACCEPTANCE_LANE_ENV.md` §2，避免验收方照旧票面文字误判。
- **Spec ⑥**：声明是**部署级**不是 profile 级（端点无 session 上下文，读不到 `tool_scope`；
  某 profile 收窄掉 `bash` 时「输出」面仍出现空态而非消失）⇒ 有意取舍 + 另开票，已记文档。

### 门禁（前端，串行跑；后端全量 pytest 不与其并发——已知资源竞争型抖动）

| 命令 | 结果 |
| --- | --- |
| `npx tsc -b` | 干净 |
| `npx oxlint` | **0 error** / 44 warnings（全部既有类别） |
| `npx vitest run` | **813 passed / 48 files** |
| `npx playwright test --workers=2` | **306 passed**（6.1m；修 2 条 strict-mode 冲突前是 304 passed / 2 failed） |
| `npx vite build` | 绿 |

### 关单与移交

- **#193 前后端都完成** ⇒ 按 §14.12 关单：comment 写明两端分支（`feat/backend` /
  `feat/frontend`）与 commit（`21f5427` / `127ecc3`），注明合并由集成 AI 执行。
- **本批（#193）的集成提示词是后端那份**：
  `D:\intelligence-agent-backend\docs\INTEGRATION_PROMPT_193_CAPABILITY_SURFACES.md`
  （跨端，含合并顺序、真端点验收、两条必须传下去的口径、风险 1 的同类隐患提示）。
- 上一轮（#183 / #186 / #189）的提示词 `docs/INTEGRATION_PROMPT_PANEL_FINAL_GATE.md` 仍然有效，
  但它里面"#193 未完成 ⇒ 两个面用户看不到"的告警**在本票合并后作废**。

## 第二十三轮：#181（2026-09-14，前端侧 · 在途记录）

票：#181「[窄屏+触摸] ⋯ 菜单依赖 hover/focus-within：≤820px 触摸设备上会话级与项目级
操作可能仍不可达」。来源是第十一轮修复的两轴 review residual（FE-R11-09 / #179 的
触摸盲区）。**纯前端、纯 CSS**，无 JS 改动。

**交付**：`5f3a18e`（`feat/frontend`，本地 commit，**未合入 main、未 push**）。

### 做了什么

`@media (max-width: 820px) and (hover: none)`（issue 推荐方案 1）：⋯ 常显，装饰性的
会话点 / 文件夹图标退到背景。鼠标档（`hover: hover`）与 >820px **零变化**。
让位用 `opacity: 0` 而非 `display: none`——`.session-item-dot` 是行里唯一的在流内容，
抽掉它这一行连同可点面积一起塌（既有注释记录过 "24px → 9px"）。

两个**状态**信号在触摸档修复前本来是**可见**的（绿点 / 黄三角），跟着槽位一起消失
就是一次信息丢失 ⇒ 改挂在 ⋯ 的颜色上（`:has()` 取同一行里的状态类）：
`session-item-dot-live` → `--success`；`rail-project-warn` → `--warning`。
刻意**不**复用 `breathe`（会把槽里唯一的入口周期性淡到 .55，与"提升可发现性"抵消）。

| 文件 | 内容 |
| --- | --- |
| `web/src/styles/app.css` | 新增 `@media (max-width: 820px) and (hover: none)` 块（+40，含取舍与代价的注释） |
| `web/e2e/touch-rail.spec.ts`（新） | 2 条 × 2 视口；`hasTouch + isMobile` 触摸上下文 |
| `web/e2e/fixtures.ts` | `rowOf` 收敛到共享处（w-session-delete 同步改用，不再各留一份） |
| `docs/E2E_SCENARIO_MAP.md` | 计数校准（见下）+ 新场景行 |

### 门禁（全绿，串行跑）

| 命令 | 结果 |
| --- | --- |
| `npx tsc -b` | 干净 |
| `npx vitest run` | **813 passed / 48 files** |
| `npx oxlint` | **0 error / 44 warnings**（全为既有类别，本票新增 0） |
| `npx playwright test --workers=2` | **310 passed**（8.2m；上一轮 306 ⇒ +4 = 新 spec 2 条 × 2 视口） |
| `npx vite build` | 绿 |

### 测试强度（变异验证，不是"看起来绿"）

| 变异 | 结果 |
| --- | --- |
| 把新 `@media` 块改成永不匹配（= 修复前） | 两条用例**都红** |
| 只删两条 `:has()` 状态色规则 | 状态信号那条红 |
| 让位改 `opacity: 0` → `display: none` | "点必须仍在布局里"那条红 |

修复前首次跑就是红的（`opacity` expected "1" / received "0"）——这正是选这个断言的
理由：Playwright 的可见性判据**不看 `opacity`**，`opacity: 0` 的元素 `tap()` 照样命中，
所以"点得到"从来不是缺口，"看不见"才是（AC1 的"触发"按**可见性**验）。

### 两轴 code-review 的处置（1 项硬 + 6 项 judgement，全部落地）

| finding | 处置 |
| --- | --- |
| **硬**：`E2E_SCENARIO_MAP.md` 的计数与场景表未随测试增删更新（该文件自己写了这条规矩） | 校准为命令输出的口径（vitest 813/48、playwright 310 = 155×2 / 36 spec），补新场景行，并把漂移史续到"第五次" |
| **硬**：本票完成未记 tracker | 本轮（本段）+ 关单 comment + 集成提示词 |
| **judgement**：`rowOf` 从 `w-session-delete` 复制而来（本仓 fixtures 顶部写明"多个 spec 共用同一份，避免各自复制后静默漂移"） | 收敛到 `fixtures.ts`，两处 spec 共用 |
| **judgement**：`style()` 的联合类型里有没人用的 `backgroundColor` | 删掉；顺带把两个 helper 命名改实（`computedStyle` / `resolveToken`） |
| **judgement**：新块与 820 块重复声明同一批选择器（未来改动要改两处） | **保留**（两块编码的是**不同状态**：hover 驱动的交换 vs 无 hover 的常显），但补一句"本块只管谁在槽里，定位与节奏仍归上面那块" |
| **judgement**：e2e 文件没有字母前缀，违反 `E2E_SCENARIO_MAP.md` 的命名注意 | **不成立**：该文件的"命名注意"说的是**字母前缀=增量序号**（与场景字母 A–I 不是一套），且仓内已有 8 个无前缀 spec（`workspace-modes` / `context-providers` / `continuation` …），本票随既有的一支 |
| **Spec**：状态等价不成立（选中行的点其实是 accent；颜色比实心圆点弱）；`breathe` 加在唯一入口上适得其反 | 见上：只借颜色、去掉呼吸；取舍与"不是等价替换"如实写进 CSS 注释与集成提示词 §3 |

### 如实划下的三条残余（都在集成提示词 §3/§4 传下去）

1. **身份可辨认性变弱**：触摸档两层只剩同一个 ⋯ 芯片，"这是会话还是项目"比"点 vs
   文件夹"更难分辨——issue 收尾要求确认的正是这一点；按方案 1 落地，未自行改槽位模型
   （issue 写明这类改动要一次性定案）。
2. **宽屏触摸（≥820px）与"主指针是鼠标 + 有触摸屏"的设备**仍够不到 ⋯：AC1 字面就是
   `(max-width: 820px) and (hover: none)`，本票没动；`(hover: none)` 只看**主指针**。
3. **窄屏行只有 29px 宽、⋯ 芯片 20px 压住中央** ⇒ "点行中央选会话"不可用。这是**修复前
   就有**的既成事实（`elementFromPoint` 实测：`opacity: 0` 的 ⋯ 照样接收指针事件，
   所以修复前点行中央会开一个**看不见**的菜单，反而更怪）；本票只是把它变成看得见的
   入口，没有引入这个重叠。要真修得改槽位模型（行不再收缩成内容宽），建议与 ① 一起定案。

**交给集成 AI**：`feat/frontend` → `main` 的合并与 push（本 worktree 只做本地 commit）。
集成提示词见 `docs/INTEGRATION_PROMPT_181_TOUCH_RAIL.md`。

---

## 第二十四轮：#171（2026-09-14，跨端：后端 `9e4adc0` + `2b4e677` + 前端在途记录）

票：#171「会话归档：让用户能整理会话列表（归档/取消归档 + 列表过滤）」。跨端票，
后端半先做（票内顺序），前端半即本轮。

**交付**：`7d6ebb7`（`feat/frontend`，本地 commit，**未合入 main、未 push**）。
后端半：`feat/backend` `9e4adc0`（实现）+ `2b4e677`（本票 review 追加的 detail 逐字锁）。

### 一条不能"顺手改"的分层决策（先说，因为它长得像冗余）

**载荷始终要完整一份**（`listSessions({ includeArchived: true })`），可见性过滤只发生在
**投影层**（`buildRailModel` 的 `includeArchived`）；开关**不**重拉列表。

- 若改成"开关驱动请求"（关着就不请求归档行），切换要等一次 round-trip、两次响应之间
  列表是两套真相（不变量 #22），而且**归档的项目成员会从载荷里消失**——`buildRailModel`
  只能把它算成 `missing`，界面就会对一条日志好端端躺在磁盘上的会话说「会话日志缺失」。
- 后端默认（不带参数不返回归档行）**一个字没动**：那是给其他客户端的默认，与"这份 UI
  要自己过滤"不冲突。前端显式请求全量，是把这句话写进请求而不是靠后端猜。

### 做了什么

| 文件 | 内容 |
| --- | --- |
| `web/src/types.ts` | `SessionSummary.archived: boolean`（**必填**，与后端 schema 同形）+ `SessionArchived` 回执 |
| `web/src/lib/api.ts` | `listSessions({includeArchived})`；`archiveSession`(POST) / `unarchiveSession`(DELETE)；回执形状防御（缺 `archived` 布尔就抛，**不拿请求意图补**——那是伪造确认） |
| `web/src/lib/projects.ts` | `buildRailModel(..., {includeArchived})`：**被开关藏起来的行不算 `missing`**（`byId` 建在全量载荷上） |
| `web/src/lib/railArchive.ts`（新） | 「显示已归档」的 localStorage 读写（`ahi.showArchived`，`'1'` 才算开，异常一律回默认——不能在隐私模式里白屏） |
| `web/src/components/SessionList.tsx` | kebab 新增「归档/取消归档」（文案随行真值切换；在项目动作之后、硬删之前）；icon 开关（`aria-pressed`）；「已归档」徽标；失败就地报错；空态提示只说真话 |
| `web/src/hooks/useSession.ts` | `setArchived`（**不动视野**，与硬删的 `convergeAfterDelete` 刻意相反）+ `refreshSessions` 返回是否成功 |
| `web/src/App.tsx` | `handleSetArchived`：失败原因交回侧栏就地显示（不走流级 `error` 横幅） |
| `web/e2e/archived.spec.ts`（新） | 6 条 × 2 视口（见下） |
| `web/e2e/fixtures.ts` | 归档分支（有状态、幂等、409 只在归档方向）+ `GET /api/sessions` 按真语义过滤 `include_archived` + `sessionsListFailAfter` |
| `docs/E2E_SCENARIO_MAP.md` | 计数校准 + 新场景行 |

### 门禁（全绿，串行跑）

| 命令 | 结果 |
| --- | --- |
| `npx tsc -b` | 干净 |
| `npx vitest run` | **827 passed / 49 files** |
| `npx oxlint` | **0 error / 44 warnings**（按文件与 HEAD 逐一比对：改动文件新增 0） |
| `npx playwright test --workers=2` | **322 passed**（8.4m；`--list` 同口径 322 = 161×2 / 37 spec） |
| `npx vite build` | 绿 |
| 后端（`feat/backend`，本仓不可见） | `ruff check` clean；全量 pytest **2260 passed / 2 skipped / 0 failed** |

### 测试强度（变异验证，不是"看起来绿"）

| 变异 | 结果 |
| --- | --- |
| `listSessions()` 漏掉 `includeArchived` | 「默认收起」那条**红**（归档行永不出现——前端本地过滤救不了） |
| 被开关过滤掉的行也算 `missing`（= 本票修掉的假话） | 缺失计数那条**红**（`2 条` vs 期望 `1 条`） |
| 归档后 `selectSession(null)`（= 把视野拽走） | 「不影响正在阅读的会话」那条**红** |

e2e 里"归档行不算缺失"必须带反向对照（账本里放一个**真**不存在的 id）：否则
`missing === 0` 与"根本没算过"同形。

### 两轴 code-review 的处置（Standards 4 + Spec 5，全部落地）

| finding | 处置 |
| --- | --- |
| **Spec（本票真正的跨端回归）**：`l-auth-banner.spec.ts` 的路由 glob `**/api/sessions` 是**整串**匹配，配不上新增的 `?include_archived=true` ⇒ 该用例静默走 200 分支、401 横幅永不出现 | 改 `**/api/sessions*`（`*` = `[^/]*`，只多吃查询串，不会吞 `/api/sessions/{id}/…`），并在注释里写明为什么这个 `*` 不是装饰 |
| **两轴都提**：空态提示在"项目已注册但还没有任何会话"时渲染「0 条都已归档」——把"没有会话"说成"都归档了"；且指向一个**屏幕上不存在**的文案（开关是纯图标） | 加两个守卫（`sessions.length > 0` / `!showArchived`），数字改用**真的**归档条数，文案改指"侧栏顶部的图标"；e2e 补一条（含"项目在但无会话时不出声"） |
| **Spec**：归档写成功但随后列表重拉失败 → 静默（行还是旧状态，用户以为没生效） | `refreshSessions` 返回是否成功；`setArchived` 刷新失败就**抛**（就地说明"已生效但没刷新出来"）；e2e 用 `sessionsListFailAfter` 构造该窗口 |
| **Spec**：两个动词的差别只有 e2e 锁着，单测断不了 POST vs DELETE | 单测改用记 method 的 capture helper，并补"回执是权威"（与请求意图相反时照抄回执）与"缺布尔就抛"两条 |
| **Spec**：前端 e2e fixture 逐字复制后端 404/409 detail，但后端只断状态码 ⇒ 后端改词两侧各自绿着漂开 | 后端追加逐字断言（`2b4e677`）——由后端自己的测试锁，跨仓没有更便宜的单一来源 |
| **Standards**：`readArchiveReceipt` 的 `expected` 参数只进诊断串却像在校验 | 改名 `requestedArchived` + 注释写明"回执是权威、这里不校验相等" |

未采纳（有据）：`.rail-error` 在窄屏被 `display:none` 时不改——属既有的窄屏降级清单
（`.rail-project-missing` 同组），见残余 ①。

### 如实划下的残余

1. **窄屏 / 触摸档的失败报错看不见**：`@media (max-width: 820px)` 里 `.rail-error` 是
   `display: none`（WS-5 的既成降级）。#181 刚把 ⋯ 在触摸档变可达 ⇒ 现在窄屏用户**能**
   触发归档、但失败时看不到那句话。要真修得先定案窄屏的槽位/降级模型（与 #181 残余
   ①② 同一批决策，不在本票内自己拍）。
2. **AC11 的可选「轻量提示 + 撤销」没做**：票面写的是"**可**在成功后给一次轻量提示 +
   撤销"，不是必须；撤销路径存在，入口是菜单里的「取消归档」。
3. **跨仓文案同源靠两侧各自断言**：后端 `2b4e677` 与前端 e2e fixture 各锁一份原句，
   没有单一来源（跨仓的代价，已在两侧注释里指明）。
4. **`/stream` 未在归档态下被 e2e 覆盖**：后端 AC5 已有契约测试（归档后 events /
   resume / fork / lineage 照旧），而 stream 不读 `session_meta`；属联调车道可补项。

**交给集成 AI**：`feat/frontend` → `main` 的合并与 push（本 worktree 只做本地 commit）。
集成提示词见 `docs/INTEGRATION_PROMPT_171_SESSION_ARCHIVE.md`（在 `feat/backend`，与后端半
同一份——跨端票合成一个入口，含合并顺序、契约要点与残余）。
