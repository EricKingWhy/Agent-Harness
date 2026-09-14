# 集成提示词：feat/backend → main（`reasoning_effort` P0 修复）

> 面向集成 AI。本分支为 `feat/backend` @ `D:\intelligence-agent-backend`。
> 本 Agent 已本地 commit，**未 push**（AGENTS.md §13.2 / §14.4）。

---

## 1. 一句话

修复一个 P0：**用户在会话里把「思考深度」选成「标准」或「深度」后，每一次 run 都在第一次模型调用就 400 失败、零输出**。根因是后端把产品词汇（`standard` / `deep`）当 provider 线格式字面量直接发出去。已翻译 + 加防呆，1 个 commit。

---

## 2. commit 与改动面

| commit | 内容 |
| --- | --- |
| `4219cbc` | `fix(model): reasoning_effort 语义档位翻译为 provider 线格式枚举`（主修复） |
| `10e34ce` | `fix(model): code-review 双轴跟进——结构化日志 + 文案/文档对齐` |
| `7f543e9` | `docs: 集成提示词 + 前端三缺陷交接单` |
| `5cc54dc` | `docs(phase-status): record reasoning_effort P0 fix`（§16.5 字段补齐） |

```
src/agent_harness/model/provider.py              | 线格式枚举 + 翻译表 + 结构化告警
src/agent_harness/web/app.py                     | 目录注释 + GET 端点 docstring + deep 档描述
tests/model/test_reasoning_effort.py             | 重写为 6 条契约（G1/G1b/G2/G3/G4/G4b/G5）
docs/goal/GOAL_RUNTIME_REASONING_EFFORT.md       | 勘误块（作废的透传假设）
docs/PHASE_STATUS.md                             | 2026-09-11 条目
docs/INTEGRATION_PROMPT_REASONING_EFFORT_FIX.md  | 本文件
docs/HANDOFF_FRONTEND_RECOVER_FORK_SCROLL.md     | 前端交接单
```

base：`5c7d85b`（merge：origin/main 架构深化 code-review 集成 + 前端 T9 集成记录）。

---

## 3. 根因（有生产日志实证）

**症状**（用户报告）：在会话里发消息「啥也没有」。

**证据链**：

1. 真实会话 `D:\intelligence-agent\.agent\workspace\sessions\f181c5ce-7c84-43f9-b249-efa606293268\events.jsonl`：
   - `seq=28 model/changed` → `{"to_provider":"qwen","to_model_id":"qwen3.8-27b"}`
   - `seq=30 user/message` → `"我是王浩宇"`
   - `seq=32 model/failed` → `{"message":"model call failed: BadRequestError"}`
   - `seq=33 run/failed` → 零输出，run 立刻收口
2. `D:\intelligence-agent\.agent\logs\agent.jsonl`，2026-09-08 ~ 09-11 反复出现：
   ```
   event_type=task_failed  outcome=error  error_type=BadRequestError
   'reasoning_effort' must be one of: 'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'
   ... input: 'deep'
   ```
3. 代码定位：`web/app.py` 的 `REASONING_EFFORT_DESCRIPTIONS` 定义三档 `minimal | standard | deep`（**产品词汇**，前端显示 轻量 / 标准 / 深度），`model/provider.py:create_chat_model` 把它**原样**塞进 `ChatOpenAI(reasoning_effort=...)` → 进请求体。只有 `minimal` 恰好同名合法；`standard` / `deep` 是非法字面量。
4. 原设计假设被证伪：`docs/goal/GOAL_RUNTIME_REASONING_EFFORT.md` §5 风险表写「不支持的字段会被 Provider 静默忽略（OpenAI SDK `extra_body` 语义）」。实测端点**严格校验该字段取值枚举并硬 400**。
5. 影响面：`reasoning_effort` 经 amend 在每次续聊时透传（`web/src/lib/amend.ts`），所以一旦选了非法档位，**该会话后续每一条消息都失败**。

---

## 4. 修复内容

- `model/provider.py`
  - 新增 `WIRE_REASONING_EFFORTS`：provider 线格式合法枚举 `{none, minimal, low, medium, high, xhigh, max}`（单一事实源）。
  - 新增 `REASONING_EFFORT_WIRE` 翻译表：`minimal→minimal` / `standard→medium` / `deep→high`。`deep` 取 `high` 而非 `xhigh`/`max`：后两档只有部分端点支持，`high` 在「深度推理」里兼容面最广（想更激进只改一行，见 §7 未决项）。
  - `create_chat_model` 只注入翻译后的合法字面量；查不到、或翻译结果不在合法枚举内 → **不注入 + 一条 warn**（fail-open，不抛错）。
  - 纠正 docstring 里「不支持的 Provider 静默忽略」的错误断言。
- `web/app.py`：目录常量的注释标明 key 是 harness 语义档位，不要改成 `medium`/`high` 这类线格式词汇。
- `tests/model/test_reasoning_effort.py`：重写为 6 条契约（G1/G1b/G2/G3/G4/G4b/G5）。其中 G1 原断言 `reasoning_effort == "deep"` **正是 bug 的固化**——这就是先红后绿的那条红。

**为什么是后端责任（而不是前端）**：前端只照 `GET /api/reasoning-efforts` 渲染选项、把选中 id 原样回传，行为正确。违约方是后端把产品词汇当线格式词汇发出（不变量 #22：不维护第二套真相）。前端**零改动**。

---

## 5. 验证门（在 feat/backend 实测）

```
ruff check .                     → All checks passed!
pytest -q                        → 1506 passed, 9 skipped, 39 deselected, 0 failed  (122s)
pytest tests/model/test_reasoning_effort.py tests/test_assembly_reasoning_effort.py
                                 → 9 passed
```

基线 1503 passed（含 main 最新 `0cdbcc9` step_id 修复）→ 1506（+3）。

运行时实证（三个档位真实发出的字面量）：

```
minimal   -> 'minimal'   合法
standard  -> 'medium'    合法
deep      -> 'high'      合法
None      -> 不注入
'bogus'   -> 不注入 + warn
```

`create_chat_model` 的全部 4 处调用点均已核（`assembly.py` primary/fallback、`cli.py` health check、`capability/factories.py` memory extractor）——翻译只在 provider 单点（不变量 #7）。

---

## 6. 集成步骤（§14.6 先回后正）

### 6.1 实测拓扑（2026-09-11，合并前请重新核验——§14.9/§14.10）

| 位置 | ref | sha |
| --- | --- | --- |
| 后端 worktree `D:\intelligence-agent-backend` | `feat/backend` | **请现读** `git -C D:/intelligence-agent-backend rev-parse --short feat/backend`（本文件自身的 commit 会让 tip 递增，故不在此硬编码） |
| 后端 worktree | `origin/main` | `d5a1a27` |
| 主仓 `D:\intelligence-agent` | `main`（本地） | `bb756a0` |
| 主仓 | `origin/main` | `d5a1a27` |

本分支自 `5c7d85b` 起的全部 commit（用 `git log --oneline 5c7d85b..FETCH_HEAD` 复核）：`4219cbc`（主修复）→ `7f543e9` → `10e34ce` → `5cc54dc` → `dfeb485` → `618fd12` → tip。

两个关键事实（**都影响本次合并动作，请勿凭直觉跳过核验**）：

1. **后端分支的 merge-base 就是 `origin/main`（`d5a1a27`）**——`origin/main` 是 `feat/backend` 的直接祖先（behind = 0，ahead = 8）。所以 §14.6 的「先回后正」**反向回并无事可做**，直接正向 `--no-ff` merge 即可。
2. **主仓本地 `main`（`bb756a0`）领先 `origin/main` 4 个 commit 且尚未 push**，内容是 step_id P0 修复的集成（`0cdbcc9` / `a76efce` / `4fd5716` / `bb756a0`）。**合并目标是本地 `main`，不是 `origin/main`**。另注意：`0cdbcc9` 与 `a76efce` 本来就已经在后端分支的历史里（后端分支从含它们的 `5c7d85b` 起），所以真正 main-only 的只有 merge commit `4fd5716` 与 PHASE_STATUS 记录 `bb756a0`。

### 6.2 为什么本文件不能给出 merge-tree 预判

两个 repo 是**独立对象库**：后端 worktree 里 `git cat-file -t bb756a0` → `fatal: Not a valid object name`。所以任何在本次合并之前算出的 `merge-tree` 结果都不覆盖本地 main 的那 4 个 commit，**没有参考价值**。请先 fetch，再在主仓现算。

### 6.3 步骤

```bash
# ── 主仓 D:\intelligence-agent，先核验工作区 clean ──
git status --porcelain                    # 应为空

# 1) 把后端对象拉进主仓（两侧独立对象库，必须 fetch）
git fetch D:/intelligence-agent-backend feat/backend

# 2) 现算拓扑（不要用本文件的数字代替这一步）
git rev-parse --short FETCH_HEAD main origin/main
git merge-base --is-ancestor origin/main feat/backend && echo "反向回并无事可做"
git rev-list --left-right --count main...feat/backend
git merge-tree --write-tree main feat/backend     # 唯一冲突预判见 6.4

# 3) 正向合并（需用户明确批准，§14.4）
git merge --no-ff feat/backend

# 4) 合并后门禁
git diff --check
ruff check src/ tests/
pytest -q                                         # 预期 1506 passed / 9 skipped / 39 deselected / 0 failed
```

### 6.4 预期冲突：`docs/PHASE_STATUS.md` 一处（同位追加）

依据（可自行复核）：本地 main 独有的 4 个 commit 触及的文件里，与本分支 5 个 commit 触及的文件**只有 `docs/PHASE_STATUS.md` 相交**——

```bash
# 在后端 worktree 验：main-only 提交的文件清单
cd D:/intelligence-agent && git diff --name-only origin/main..main
#   → PHASE_STATUS.md + step_id 的 runtime/session/tests/docs（与本分支零交集）
# 本分支触及：model/provider.py / web/app.py / tests/model/test_reasoning_effort.py
#            / docs/PHASE_STATUS.md / docs/goal/GOAL_RUNTIME_REASONING_EFFORT.md
#            / 本文件 / HANDOFF_FRONTEND_RECOVER_FORK_SCROLL.md
```

两边都是在「## 更新日志」**同一位置追加**（最新在上），因此会冲突。按 **§14.7 逐条保留、两边语义都成立**：本分支的 2026-09-11 条目 + main 的 step_id 集成条目**全部保留**（不是 ours/theirs 二选一）。上一轮 `5c7d85b` 处理过完全同型的冲突（「PHASE_STATUS 同位追加冲突按 §14.7 三条全保留」），可照抄那个判定口径。

其余文件预期**零冲突**：`model/provider.py` 由本分支独占；`web/app.py` 本分支只改了注释与一处描述字符串；tests 与两个新 docs 本分支独占。

### 6.5 合并后需用户单独批准的动作

- `git push`（§14.4）——合并后本地 main 会领先 `origin/main`（合并前已领先 4，本次再合入本分支相对 `origin/main` 的 8 个 commit，其中 `0cdbcc9`/`a76efce` main 已有，另加一个 merge commit）。确切数字请在合并后读 `git rev-list --left-right --count origin/main...main`，**不要沿用估算值**。**push 需用户单独明确批准**，不要因为已批准 merge 就默认批准 push（§14.11）。
- `docs/INTEGRATION_PROMPT_STEP_ID_FIX.md` 目前仍是**未跟踪文件**（step_id 修复那次遗留的集成提示词，未入库）。AGENTS.md §13.1 要求 docs 入库——请确认是否随本次一并 `git add`。**这是本次唯一遗留的未跟踪文件**（其余 4 份历史提示词已由 `5c7d85b` 带入）。

---

## 7. 未决项 / 需要产品决策

| 项 | 说明 | 影响 |
| --- | --- | --- |
| `deep` 的映射落点 | 现落 `high`，且 catalog 里该档描述已同步改成「较高推理开销，较慢但更深入」——**代码与 UI 文案现在一致**。若产品坚持字面「最深入」，需同时改两处：翻译表 `deep` 一行 + catalog 描述，并确认目标端点接受 `xhigh`（追字面值会引入新的 400 风险，这是当初选 `high` 的原因） | 只影响「深度」档的推理强度 |
| `standard` 的映射落点 | 现落 `medium`。语义是「平衡」，中位合理 | 低 |
| 是否按 provider 分档 | 未做。GOAL §7 明确禁止 per-provider 参数映射（如 Qwen 的 `enable_thinking`），本次只做 provider 无关的线格式适配 | 低 |

---

## 7b. code-review 双轴结果（第二轮，独立 sub-agent）

两轴分开跑、不互相污染。**均无硬违规**，共 4 处 finding，已全部在 `10e34ce` 修掉：

| 轴 | finding | 处置 |
| --- | --- | --- |
| Standards | 裸 `logger.warning` 不利于事后检索——本 P0 拖了三天正因为没留下可检索记录 | 改 `log_event` 结构化事件（`component=model_provider` / `outcome=reasoning_effort_not_injected`） |
| Standards | `docs/PHASE_STATUS.md` 条目缺 §16.5 规定的 commit sha / 关单字段 | `5cc54dc` 补齐 |
| Spec | `deep` 档 UI 描述「最多推理开销…最深入」与其映射 `high` 自相矛盾（枚举里还有 `xhigh`/`max`） | 对齐文案（见 §7），不追字面值 |
| Spec | `web/app.py` 的 `GET /api/reasoning-efforts` docstring 仍写「注入 model_kwargs → extra_body」，与翻译后路径不符 | 已改 |
| Spec | 原始设计文档 §1.2/§2.3/§3.1/§5/§6 仍主张原样透传，§5 断言「静默忽略不会报错」被生产证伪 → 作废契约留在唯一的设计记录里 | 加勘误块，保留原文备查 |

两轴均确认：不变量 #7 / #21、§8 Scope Lock 无违反；「前端零改动」结论经独立核验正确；前端交接单里三条缺陷的 file:line 经独立抽查准确（±2 行内）。

> 说明：第一轮我只做了自审（在 diff 上看 Standards/Spec 两个视角），**那不是协议要求的独立两轴**，所以补跑了这一轮。

---

## 8. 与本次一并诊断、但属于**前端**的缺陷（不在本 commit）

用户同一次提问里的另外两个症状是前端缺陷，已写成独立交接单：`docs/HANDOFF_FRONTEND_RECOVER_FORK_SCROLL.md`。

- 「恢复会话」点了没反应 —— `web/src/lib/runState.ts:116` 的 `isRecoverableRun` 不认识 T8 新增的终态 `run/interrupted`，按钮永不消失。
- 「分叉」点了没反应 —— `web/src/components/Conversation.tsx:292` 把 `turn.step_id`（turn 键）当成用户消息 `seq` 传给 `from_seq`；错误又被 `web/src/App.tsx:318-323` 的 `catch {}` 静默吞掉。
- 流式期间滑轮被顶回去 —— `web/src/components/Conversation.tsx:121-132` 每个 delta 重发一次 `scrollIntoView({behavior:'smooth'})`，并重复实现了 `web/src/lib/followLatest.ts` 已有的跟随原语。

**前端不在本 worktree 修改**（AGENTS.md §13.1：前端任务在 `D:\intelligence-agent-frontend` / `feat/frontend`）。

---

## 9. 授权链与状态

- 授权链：用户 `[$diagnosing-bugs]` 报告「发了消息啥也没有」等三个症状；本 Agent 定位根因后按 §16.2（diagnose → 最小修复 → 回归 → code-review）执行。
- 状态：feat/backend 本地提交 `4219cbc`，**待集成 AI 合入 main**；本 Agent 未 push、未 merge（§14.4）。
