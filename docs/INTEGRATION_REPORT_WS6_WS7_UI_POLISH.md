# 集成报告（给前端 / 后端 AI）：WS-6/WS-7 + UI Polish 六票已合入 main 并推送

> **写于**：2026-09-13（Git Integrator）
> **模板用途**：这是「联合集成完成」的通用回执格式。前端 / 后端 AI 收到本文件后，只需核对自己关心的部分（各自的门禁数字、契约、遗留项），不需要重新验证集成结果。
> **本次集成范围**：三条源分支（`feat/backend` 7 commits、`feat/frontend` 8 commits、`feat/frontend-ws6-ws7` 8 commits）→ 两次进 main → push。**全程零源码冲突**，最终 main = `593dcda`（本地与 origin/main 完全同步）。

---

## 0. 一句话结论

WS-6（#169）/ WS-7（#170）后端半 + 前端半、UI Polish 六票（UI-01..06 + U-1/U-2/U-3 三轮批量审查）**全部合入 main，全部门禁绿，真机验收全过，已 push**。两个 worktree 现在都可以基于最新 main 开始下一批工作（先 `git fetch origin && git merge origin/main` 或按你们各自的同步习惯）。

---

## 1. 合并序列（实际执行的顺序）

| # | 动作 | commit |
| --- | --- | --- |
| 1 | `feat/frontend-ws6-ws7` → `feat/frontend`（在前端 worktree 内合并） | `45ba84c` |
| 2 | `feat/backend` → main（后端先合，§14.9） | `dcb3841` |
| 3 | `feat/frontend`（含 B′）→ main | `d362ff1` |
| 4 | PHASE_STATUS 回填两条集成记录 | `593dcda` |
| 5 | `git push origin main` | `cc5eee4..593dcda` |

**唯一需要解冲突的地方**是步骤 1 的 `docs/SDD_TICKET_TRACKER.md`（两边在同一张批次台账表上各插了一行）——按手册规则解决：保留 `feat/frontend` 侧 U-2/U-3 审查版行、删 B′ 过期"未审"副本、追加 B-2 台账行 + 完整保留 B-2 整节。这个解法已经在 main 上落地，**前端 AI 下次 fetch 后 tracker 里 U-1/U-2/U-3/B-2 四行齐备，不需要再动它**。

---

## 2. 门禁数字（全部在合并后的树上实跑，不是引用分支数字）

### 后端（D:\intelligence-agent，main）

- `ruff check src/ tests/`：All checks passed
- 全量 `pytest -q`：**2117 passed / 2 skipped / 42 deselected / 0 failed**
- 已知 flaky `test_disconnect_leaves_run_running_and_cancel_stops_it` 本轮绿（没触发）

### 前端（feat/frontend 合并后与 main 各跑一轮，数字一致）

- `npx tsc -b`：0 error
- `npx vitest run`：**628 passed**（35 文件）
- `npx oxlint`：38 warnings / 0 errors（基线持平）
- `npx playwright test --workers=2`：**216 passed / 0 failed**
- `npx vite build`：✓

### 手册预测兑现（证明两批 UI 改动没有打架）

B′ 在旧 base（`522602d`，不含 U-2 审查修复）上测出的 3 个既有用例失败里，`g-visual-qa:82` 与 `r-project-groups:295` 在合并后**如期转绿**——它们正是 UI-03 / UI-05 在途修复的目标。合并这棵树之后测试全绿，说明 B 侧修复与 B′ 侧改动在语义上兼容。

---

## 3. 真机验收结论（真 .env + 真模型 glm-4.5-air + 真浏览器，全部通过）

### WS-6（#169）六项全过

1. 注册真实目录（`.scratch/ws6-accept`）→ 侧栏出现项目。
2. 项目行 kebab 第一项 = 「在此项目中新建任务」；空项目占位区出现「在此项目中新建任务 →」。
3. 确认面逐字显示 `Agent 将直接读写该目录：D:\intelligence-agent\.scratch\ws6-accept`，权限档默认「工作区写入」（picker `.sel` 类取证）。
4. 任务「用 read 工具以相对路径读取 hello.txt」→ `tool/call read {"path":"hello.txt"}` 成功、回答逐字复述 `REAL-MARKER-WS6-7731`——**相对路径能读到 = cwd 真的换过去了**。
5. 全程零审批卡（29 个事件无 `approval-requested`，默认档不发 `permission_mode`）。
6. 目录改名 → 提交 → 422 后端原文「提交失败：目录不存在：D:\…」**留在确认面**（不弹全局横幅、对话框不关、任务内容保留）；目录改回后同一按钮重试成功并落组。

### WS-7（#170）五项全过

1. 根模式列真实盘符 `C:\` / `D:\`，「向上一级」「选择此目录」禁用。
2. `D:\` 一级 67 个真实子目录、仅目录、按名排序；进入子目录后两个输入框同步回填。
3. 手填框回车 → 浏览器反向跳转。
4. 「选择此目录」→ 回执 → 注册成功。
5. 不存在路径就地显示后端 detail 原文「目录不存在：D:\definitely-does-not-exist-xyz-123」（不翻译成"加载失败"）。

### UI Polish 抽查

- 审批卡结构化参数（工具名 + danger/workspace-write 策略 chip + `$ echo …` 命令预览）+「批准 Ctrl+⏎ / 拒绝 Ctrl+⌫」提示；Ctrl+⏎ 批准实测生效（pending 卡消、run 续跑）。
- 时间线审批链齐全：`tool/approval-requested 等待审批 · bash` → `permission/resolved 审批已决（approve_once）`。
- 时间线 run 分组跨轮序数正确（Run 1 / Run 2）；ReasoningBlock「持续 <1s」与「持续了 1 秒」两种措辞真机可见。
- 亮色主题 tertiary token 实测应用（`rgba(18,18,24,0.62)`），对比度由 t-contrast e2e 8 断言双主题 ≥4.5:1 锁定；亮色整页截图目测正常。
- `<50ms` 时长样本真机未采到（本轮工具执行 130ms–10.3s），由 formatShortDuration 单测 + e2e 覆盖——**不是缺陷，是样本恰好没落在那个区间**。

---

## 4. ⚠️ 本次发现的重要行为语义（两边的 AI 都需要知道）

### 4.1 `permission_mode` 只在「建会话时」生效

真机实测确认：

- **同会话续发消息**时，composer/对话框里的权限模式选择器**不影响**当前会话——默认档（不发 `permission_mode` 键）= 自动执行，bash 直接跑，无审批卡。
- **新建会话**（composer 显式选档 → 发送 / 新建项目对话框选档）时，选档随 payload 发给后端 → 交互式审批生效（bash 触发审批卡）。
- 后端**没有**「中途改档」的端点（只有 `GET /api/permission-modes` 静态枚举 + 建会话时的 `permission_mode` 参数）。

**给前端的含义**：如果用户预期「改了档位当前会话立刻生效」，这是产品层的 gap，需要产品决策（立票讨论是加端点还是 UI 提示）。**给后端的含义**：如果未来加 `POST /api/sessions/{id}/permission-mode`，记得事件流要有对应投影，前端才能实时反映。

### 4.2 其余旁路观察（非缺陷，登记在案）

- 三轮 run 出现 `model/fallback deepseek-v4-flash-0731 → glm-4.5-air · InternalServerError`，fallback 按设计工作。
- 验收在真实 workspace 产生了数据：项目 `ws6-accept`（指向 `.scratch/ws6-accept`）+ 3 个验收会话，**保留未删**。不需要的话可在 UI 里删项目/会话、删 `.scratch/ws6-accept` 目录。

---

## 5. 给前端 AI 的交接要点

1. **你的 8 个 commit 已全部进 main**（`0d2ef3a..b7fb862` + B′ 的 `f3849ac..f6b53a7` 经 `45ba84c`）。下一个批次请先在 worktree 里 `git fetch origin && git merge origin/main`（或你们的同步习惯），基于 `593dcda` 开工。
2. `docs/SDD_TICKET_TRACKER.md` 在 main 上的最终形态：U-1/U-2/U-3/B-2 四行齐备 + B-2 整节 + UI Polish 章节，**不要重复合并或手工调整它**。
3. §4.1 的 permission_mode 语义 gap：建议立票讨论（「改档只影响新会话」的用户预期问题）。要不要做、怎么做，等产品拍板。
4. 你之前提的两个问题已有答案（联合手册 §5.1）：**审批倒计时不做**——`tool/approval-requested` 不携带任何超时/截止字段，倒计时必须前端硬编码 300s，违反不变量 #22 + 用户决策 D4，UIP-DEFER 关闭。若想把超时拒绝的 `reason`（「审批超时…按 fail-closed 拒绝」）渲染出来，是加性零契约变更的小改进，**建议单独立票**。
5. e2e 的 5173 复用坑仍在：跑 playwright 前确认 5173 上跑的是哪个 worktree 的 dev server。

---

## 6. 给后端 AI 的交接要点

1. **你的 7 个 commit 已全部进 main**（`50e96a4..a126378`）。基于 `593dcda` 开工，先 fetch 同步。
2. `ruff` + 全量 pytest 在 main 上 2117 passed / 0 failed，你的下一批在这个基线上跑门禁。
3. §4.1 的语义 gap 是你们侧的既有设计（`permission_mode` 只进建会话 payload），前端可能立票要改档端点——到时候一起讨论契约。
4. 已知 flaky `test_disconnect_leaves_run_running_and_cancel_stops_it` 本轮绿；若下次全量红了，先隔离复跑再判断（PHASE_STATUS #152/#154 有三次登记）。
5. 遗留未决（均已在 PHASE_STATUS 登记，不阻塞本批）：跨进程文件锁（BUG-011 遗留）、`_RunFinalizer` 无 memory hook、`get_collection_stats` 惰性陈旧、`.env` main worktree 三项（LANGFUSE / CAPABILITIES.memory / MILVUS_COLLECTION）由用户手工配置。
6. **建议立票（不在本次动，Scope Lock）**：`docs/SDD_TICKET_TRACKER.md` 被 backend / frontend 两个 worktree 共用同一路径，是每次集成的唯一冲突源。可以考虑拆分命名空间（如 `SDD_TICKET_TRACKER_BACKEND.md`）或文件内约定「后端章节 / 前端章节」。

---

## 7. 分支 / worktree 清理（需用户批准，两边都不要自行删）

- `feat/frontend-ws6-ws7` 分支与隔离 worktree `D:\intelligence-agent-frontend-ws6` 在合入后已无用途——删除属 §14.4，等用户明确批准。
- `feat/backend` / `feat/frontend` 是长期施工分支，继续保留。

---

## 8. 本次集成的完整证据链

- 集成手册（唯一入口）：`docs/INTEGRATION_PROMPT_UI_POLISH_AND_WS6_WS7_JOINT.md`（backend clone）
- 集成记录两条：`docs/PHASE_STATUS.md` 更新日志顶部 2026-09-13 两条
- 冲突解决规则与真机清单：手册 §2.1 / §4
- 门禁数字与 B′ 转绿预测：手册 §3.2（合并后实测逐条兑现）
