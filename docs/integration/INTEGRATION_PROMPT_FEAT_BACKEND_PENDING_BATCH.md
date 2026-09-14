# 集成提示词：`feat/backend` 在途批次 → `main`（单分支合入手册）

> **收件人**：Git Integrator（AGENTS.md §14 授权的集成角色）
> **写于**：2026-09-12（后端 Agent，工作区 `D:\intelligence-agent-backend`）
> **授权链**：用户明确指示「交给集成 AI 先合并 main」。
> **红线**：永不 force-push / rebase / reset --hard；`.env` 的**值**不进任何输出、文档或提交（只提示"需要在 main worktree 配置哪些键"）；每次合并动作前先用 `git worktree list --porcelain` 复核 worktree↔branch 映射（§14.2）；冲突后立即停止自动解决并逐文件分析（§14.7）；**merge 与 push 都需要用户单独明确批准**（§14.11——用户批准了「交给集成」，不等于批准了 push）。

---

## 0. 一句话摘要

`feat/backend`（tip 见 `git log -1`；本手册所在 commit 即批次末笔）在**真实** `origin/main`（`bf81346`，本次已 fetch）之上还有 **12 个 commit** 未合：**运行时失败可读化修复**（2 个代码 commit）+ **记忆抽取 review 收口**（1 个代码 commit，**内容已在 main**）+ **prompt-registry 设计文档**（ADR-0023 / PRD / CONTEXT）+ **研究与前向进度文档**。

实测（`git merge-tree`，只读）：**零源码冲突**，只有 **2 个文档冲突**且都有确定的解决规则（§4）。本分支门禁实测：**1618 passed / 10 skipped / 39 deselected / 0 failed**、`ruff` All checks passed、`git diff --check` clean。

本批次**不包含** prompt-registry 的代码实现——#161–#168 是设计票，尚未动工，**保持 OPEN**。

---

## 1. 拓扑与前置检查（§14.2，合入前必须复核）

```bash
# 1) 两个仓库是独立对象库（各自 .git，非共享 worktree）——先确认这一点
git -C D:/intelligence-agent rev-parse --git-common-dir      # 期望：.git（D:/intelligence-agent 自己的）
git -C D:/intelligence-agent-backend rev-parse --git-common-dir  # 期望：.git

# 2) 复核分支映射（不要凭目录名猜分支）
git -C D:/intelligence-agent branch --show-current           # 期望：main
git -C D:/intelligence-agent-backend branch --show-current   # 期望：feat/backend
git -C D:/intelligence-agent-backend status --short          # 期望：clean

# 3) 核实 tip 与领先/落后（数字应与本单一致；不一致先停下来报告）
git -C D:/intelligence-agent-backend log --oneline -1                    # 期望：本手册所属 commit（含 docs(integration) 字样）
git -C D:/intelligence-agent fetch origin --prune
git -C D:/intelligence-agent log --oneline -1 origin/main                # 期望：bf81346
git -C D:/intelligence-agent-backend rev-list --count origin/main..feat/backend   # 期望：12
git -C D:/intelligence-agent-backend rev-list --count feat/backend..origin/main   # 期望：35
```

### 1.1 必须先传对象（否则 main 侧"看不见"这 12 个 commit）

`D:\intelligence-agent` 与 `D:\intelligence-agent-backend` 是**独立 clone**，对象库不相通（历史先例见 `docs/integration/MERGE_EXECUTION_ORDER.md` §1.1）。两种传法，**任选其一**：

```bash
# 方式 A：本地路径 fetch（不必 push GitHub）
git -C D:/intelligence-agent fetch D:/intelligence-agent-backend feat/backend:refs/remotes/local/feat-backend

# 方式 B：先 push feature 分支再 fetch（需用户单独批准 push）
```

传完后自检**对象已到位**：

```bash
BACKEND_TIP=$(git -C D:/intelligence-agent-backend rev-parse feat/backend)
git -C D:/intelligence-agent cat-file -t "$BACKEND_TIP"        # 期望：commit
git -C D:/intelligence-agent merge-base HEAD "$BACKEND_TIP"    # 期望：ee2977e
```

### 1.2 merge 方向（§14.6「先回后正」）

```text
origin/main (bf81346) ──→ feat/backend   ← 在这里解决冲突、跑测试
                              ↓
                            main         ← 稳定后再合
```

**优先把 `origin/main` merge 进 `feat/backend`**（在 backend worktree 里解决冲突），验证通过后再 `feat/backend → main`。若用户希望直接合入 `main`，也可在 `main` 上执行——但一旦出现本单未预测到的冲突，按 §14.8 立即 `git merge --abort`，回到 backend 侧解决。

### 1.3 集成 AI 自己备案的前置条件——逐条核对（`fdc3075`）

集成 AI 已在 main 的 `docs/PHASE_STATUS.md`（2026-09-11 条目）写下"下次合并 feat/backend 的注意事项"四条。逐条现状：

| # | 备案要求 | 现状 |
| --- | --- | --- |
| ① | 等 backend worktree **收工且 clean**（当时有 3 个未提交文件，会话在施工） | ✅ **已满足**：`feat/backend` `git status` clean（tip 见 `git log -1`） |
| ② | `docs/PHASE_STATUS.md` 同位追加冲突 → **去重只保留一份**，不机械 ours/theirs | ✅ 已写成可机械执行的规则（§4.1，含三条 grep 自检） |
| ③ | `git log` 中将同时可见**两族哈希**，属预期不是回归 | ✅ 已登记（§2 组 B、§9.2） |
| ④ | `feat/FixBUG` 为遗留引用，**不再合并、暂不删除**（删除需 §14.4 批准） | ✅ 本单不处置该分支（§9.2） |

> 关于 ②：备案说的是"**去重**"，本单原本草稿写的"多条全保留"是错的——两者已统一为 §4.1 的表格式规则（重复条目去重、分支独有 2 条必须补录、main 的集成记录必须保留）。以 §4.1 为准。

---

## 2. 批次清单（12 个 commit，旧 → 新）

### 组 A —— 运行时失败可读化（**真正的代码改动，main 没有**）

| commit | 内容 |
| --- | --- |
| `41cc5de` | `fix(runtime)`: provider 内容审查拒绝（阿里云百炼 `data_inspection_failed`）时，`run/failed` / `model/failed` 从裸类型名 `BadRequestError` 升级为**已分类 reason + 固定可读中文文案**。新增 `_classify_provider_failure()` + 常量 `CONTENT_MODERATION_REASON` / `CONTENT_MODERATION_MESSAGE`；`Session.end_run` 增加 failed 语义的 `message: str \| None` 参数（缺省不落键） |
| `9fe4dd9` | `fix(runtime)`: code-review 修复——分类前先判 `terminal.model_call_open`（模型调用在途窗口），**顶层异常臂同时兜底工具/执行器异常**，工具阶段含错误码的文本不得被误标为内容审查 |

受影响文件：`src/agent_harness/agent/runtime.py`、`src/agent_harness/session/session.py`、`docs/BACKEND_CONTRACT_STREAMING_UI.md`、`tests/agent/test_runtime_failure_paths.py`、`tests/agent/test_run_finalizer.py`。

### 组 B —— 记忆抽取降级 review 收口（**内容已经在 main，合入应为零差异**）

| commit | 内容 |
| --- | --- |
| `9a9b467` | `fix(memory)`: `_repair_json` 从"全局替换"改为**字符串感知扫描**（宁可回退不可静默篡改）；`heuristic_unavailable` 归因修正；降级事件补 `run_id` |

> ⚠️ **这一组需要合并后显式核验**：main 已通过 `merge(backend) BUG-012 ...`（`9f9d33e`）+ `merge(backend) BUG-012 review 收口`（`e3623ae`）把**等价内容**合进去了（来自 `feat/FixBUG` 的 `e675480`）。本次实测 `origin/main` 与 `feat/backend` 在 `src/agent_harness/memory/` 上**零差异**。
>
> 合并后请执行：
> ```bash
> git -C D:/intelligence-agent diff --stat HEAD -- src/agent_harness/memory/
> # 期望：空输出（本组是内容 no-op，只是 SHA 不同）
> ```
> **若出现差异 → 立即停下来报告**，不要自行判断哪边赢（可能是"同名不同语义"的收口版本）。

### 组 C —— prompt-registry 设计（**纯文档，无源码**）

| commit | 内容 |
| --- | --- |
| `3c7263e` | `docs`: ADR-0023（Proposed）+ PRD_PROMPT_REGISTRY + CONTEXT.md 术语表（8 条）；grilling 收敛 20 项决策，8 票 #161–#168 |
| `5d83dc6` | `docs`: 集成提示词同步 review 修复（`docs/integration/INTEGRATION_PROMPT_MODERATION_MESSAGE.md` 的 2 commit 清单 + 合同登记 + 对象库拓扑提醒） |
| `81833e7` | `docs`: 8 张 ticket 细化到"无歧义可执行"粒度，并回改 PRD/ADR 的 5 处实现期设计缺口（`*` 通配边界 / T3 接线点 / 自检规则 / 新增 `Target.FRAGMENT` / `DEFAULT_REGISTRY` 不读环境） |

### 组 D —— 研究与前向进度文档

| commit | 内容 |
| --- | --- |
| `9d0f0c4` | 研究：记忆可插拔 Gap / 项目→多会话 / 跨进程 workspace 独占锁 |
| `92f2682` | 研究：落定 seam A / 单实例锁 / 项目→多会话决策与票号 |
| `46400b8` | 研究：§7 记忆生命周期决策（update / delete / forget / 冲突消解）+ 票 #156–#160 |
| `c65efc2` | PHASE_STATUS 登记 + BUG-012 集成提示词 |
| `4e71d49` | PHASE_STATUS 记录 code-review 修复与 flaky 判定 |

---

## 3. 契约变化（全部加性，无破坏）

1. `run/failed.data.reason` 新增枚举值 **`"provider_content_moderation"`**。既有：`cancelled` / `orphaned` / `identical_tool_failure_loop` / `context_window_exceeded`。**已登记进合同文档** `docs/BACKEND_CONTRACT_STREAMING_UI.md` §4。
2. `run/failed.data.message` 与 `model/failed.data.message`：已分类故障新增固定可读文案（中文）；未分类错误**字节级行为不变**（不落这两个键，有回归锁）。
3. 前端**无破坏**：`web/src/lib/runState.ts` 只特判 `reason === 'cancelled'`，未知 reason 自然落入 failed 分支。后续可选前端票是"把该 message 渲染出来"，本批未动前端。
4. 脱敏不变量不松动：事件只带本项目常量；provider 回显原文仍只进结构化日志。测试断言 `inappropriate` / `chatcmpl-*` 不出现在任何持久化事件 data。

---

## 4. 冲突预测与解决规则（**实测 `git merge-tree`，非推测**）

```bash
git -C D:/intelligence-agent-backend merge-tree --write-tree --name-only origin/main feat/backend
# 实测输出：exit=1，冲突文件恰好两个
#   docs/PHASE_STATUS.md                                    → CONFLICT (content)
#   docs/RESEARCH_PROJECT_MULTISESSION_AND_MEMORY_PLUGGABILITY.md → CONFLICT (add/add)
```

### 4.1 `docs/PHASE_STATUS.md`（content 冲突，两边都追加）

> **本规则已与集成 AI 在 main 上备案的处置对齐**（`fdc3075` 的 2026-09-11「集成决策备案：分支异常与历史双份哈希处置（方案 A）」条目，其中第 ② 条明确要求本文件的冲突**去重、只保留一份**）。本节把"哪些去重、哪些必须补"写到可机械执行。

两侧条目实测结构（行号取自各自版本）：

| 条目 | main 侧 | 分支侧 | 处置 |
| --- | --- | --- | --- |
| 集成 AI 的集成记录（`集成记录：BUG-012 记忆抽取降级修复…`） | 有（`L51`） | **无** | **必须保留 main 的** |
| `BUG-012 修复 + 记忆写入装配 + Milvus 正式集合（feat/backend…）` | 有（`L288`） | 有（`L276`），**内容相同** | **去重：只保留一份**（双哈希副本 `ba28769` ↔ `c65efc2`） |
| `fix(runtime)：data_inspection_failed 升级为可读失败消息…` | **无** | 有（`L277`） | **必须补录**（分支独有，来自 `41cc5de`） |
| `code-review 修复：内容审查分类限定模型调用在途窗口…` | **无** | 有（`L278`） | **必须补录**（分支独有，来自 `9fe4dd9`） |

**机械执行步骤**：

1. 取 **main 侧版本为底**（它含集成 AI 的集成记录，分支没有）。
2. 把分支侧独有的 **2 条**（`data_inspection_failed` 可读失败消息、code-review 在途窗口）插入 **2026-09-11 段内、紧跟 BUG-012 条目之后**，保持该段其余内容不动。
3. **不要**再插入分支侧的 BUG-012 条目——它已在 main 上存在且内容相同。

**解决后的自检**：

```bash
cd D:/intelligence-agent
grep -c "集成记录：BUG-012 记忆抽取降级修复" docs/PHASE_STATUS.md   # 期望：1（集成 AI 的登记仍在）
grep -c "data_inspection_failed" docs/PHASE_STATUS.md               # 期望：≥1（分支新条目已补录）
grep -c "BUG-012 修复 + 记忆写入装配" docs/PHASE_STATUS.md           # 期望：1（未重复）
```

**不要**用 `ours` / `theirs` 整体覆盖：任一方向的整体覆盖都会丢掉上表里必须保留的条目（要么丢 main 的集成记录，要么丢分支的 2 条新登记）。

### 4.2 `docs/RESEARCH_PROJECT_MULTISESSION_AND_MEMORY_PLUGGABILITY.md`（add/add 冲突）

- 两边都新增了同一路径。实测 `git diff --numstat origin/main feat/backend -- <该文件>` = **`104 0`**（104 行新增、**0 行删除**）→ 分支侧是 main 侧的**严格超集**。
- **解决规则：取分支侧版本**（即该文件不存在内容取舍问题，main 侧内容全在分支侧里）。合并后自检：

  ```bash
  git -C D:/intelligence-agent diff --stat HEAD -- docs/RESEARCH_PROJECT_MULTISESSION_AND_MEMORY_PLUGGABILITY.md
  # 期望：空（分支版本已是最终态）
  ```

### 4.3 出现**第三个**冲突 → 停手（§14.7）

本单预测只有 2 个。若出现其他冲突（尤其 `src/**`），说明拓扑已变化（main 又前进了或另有分支合入），**立即停止**：`git merge --abort`，重新 `fetch` + `merge-base` + `merge-tree` 复算，然后向用户报告，**不要**机械用 `ours` / `theirs`。

---

## 5. 误删文件的红线（§14.10「没有误删文件」）

main 上有一批分支**从未有过**的文件（前端文档与 e2e），它们在 tip-to-tip diff 里显示为删除，但**实测分支侧没有任何 `D`（删除）状态**（`git diff --name-status origin/main...feat/backend` 全为 `A`/`M`）：

```text
docs/FRONTEND_ISSUES_LOG.md
docs/ACCEPTANCE_CONTROL_INVENTORY.md
docs/ACCEPTANCE_LANE_ENV.md
docs/INTEGRATION_PROMPT_BUG_008.md
docs/INTEGRATION_PROMPT_TYPE_HONESTY_AND_WAIT_HINT.md
docs/SDD_TICKET_TRACKER.md
web/e2e/*.spec.ts（多个）
web/src/**
```

**合并后必须复核它们仍在**：

```bash
git -C D:/intelligence-agent diff --name-status origin/main...HEAD | grep '^D'
# 期望：只有 docs/PHASE_STATUS.md 一类"正常被合并提交改写"的路径，不含上面这批
```

结论：用**常规 `git merge`**（`--no-ff`，与 main 既有 merge commit 风格一致）即可，**不要**用 `-X ours` / `-X theirs` 整体覆盖策略。

---

## 6. 门禁证据（本分支实测，2026-09-12）

| 项目 | 结果 |
| --- | --- |
| 全量测试（`uv run pytest -q`，在本批次代码末笔 `81833e7`；本手册仅为文档追加，不改变测试结果） | **1618 passed, 10 skipped, 39 deselected, 0 failed**（156.87s） |
| `uv run ruff check src/ tests/` | All checks passed |
| `git diff --check` | clean |
| 冲突预测 | `merge-tree` 实测 2 个文档冲突，零源码冲突 |
| 分支状态 | clean（无未提交改动） |

### 6.1 已知 flaky 史与复跑建议

`docs/integration/INTEGRATION_PROMPT_MODERATION_MESSAGE.md` §门禁证据记录过：并行 AI 会话**共用同一 worktree 实时写文件/并发跑测试**时，`web` 传输层出现过 16/24 个漂移失败（幻影文件名、失败集合逐轮不同）。判定为负载型 flaky，隔离运行全绿。本次单独跑全量为 **0 failed**。

**合并到 main 后请复跑一次全量**：若出现 web 层漂移失败，先确认没有第二个进程在写该 worktree，再隔离复跑取证，不要直接归因于本批。

---

## 7. `.env` 不随代码同步（§13.1.6，**密钥值不得进文档**）

main worktree 的 `.env` 不会被 `feat/backend` 的合并带过去。与本批相关的配置项（**只提示键名，值由用户手工配置**）：

- `LANGFUSE_*`：三个键需在 main worktree 的 `.env` 里补齐（向用户索取，切勿从任何仓库文件抄）。
- `CAPABILITIES`：需含 `"memory": {"provider": "builtin", "enabled": true}` 才会装配 memory。
- `MILVUS_COLLECTION`：应为正式集合名（`agent_memory`），不是 gate 专用集合。

**不配也不影响本批修复生效**（单测覆盖），只是生产不装配 memory / 不上报 Langfuse。**不要**把任何密钥值写进本手册、commit 消息、PHASE_STATUS 或输出。

---

## 8. 关单与进度登记

- **本批不关任何 ticket**：组 A 的是既有 issue 的修复（不在本批引入新票）；#161–#168 是 prompt-registry 的**设计票**，实现尚未开始，**保持 OPEN**。
- 合并后按 §16.5 在 `docs/PHASE_STATUS.md` 追加一条集成记录（格式：日期 + 批次名 + commit + 测试数字 + 关单状态）。
- 若集成 AI 认为某既有 issue 可关，**先核实代码/测试实际状态**再关（§14.12），不要凭本手册的措辞关单。

---

## 9. 遗留风险与未决项（如实登记，不掩盖）

1. **prompt-registry 8 票（#161–#168）未实现**——设计（ADR-0023 + PRD + 8 张 ticket）已就绪并随本批进 main，代码未动。实现要在 `feat/backend` 上按 #161 → #168 依赖序做。
2. **`feat/FixBUG` 分支异常**已由集成 AI 处置（见 main 的 PHASE_STATUS 2026-09-11 条目）。该分支现仅领先 main 1 个 commit（45 行研究文档），其内容在 `feat/backend` 上已有同名 commit（`92f2682`）；该分支**无 upstream、从未 push**。是否删除由用户决定，本单不处置。
3. **跨进程文件锁**（BUG-011 遗留）仍未实现。
4. **run 异常/取消不提取记忆**：`_RunFinalizer` 没有 memory hook。
5. **`get_collection_stats` 惰性陈旧**，不可用于对账。
6. 本分支落后 main **35 个 commit**（含前端工作 24 个 `web/` 变更）。合入方向是 feature → main，这些不会被覆盖，但合并后建议用 `git diff --stat origin/main...HEAD` 复核一次"分支真正带进 main 的只有 §2 那 16 个文件"。

---

## 10. 执行清单（给 Integrator 的勾选表）

```text
[ ] 1. 复核 worktree ↔ branch 映射与两侧 clean（§1）
[ ] 2. fetch + 核实 tip / ahead 12 / behind 35（§1）
[ ] 3. 传对象（本地 fetch 或 push 后 fetch）+ cat-file 自检（§1.1）
[ ] 4. origin/main → feat/backend（§14.6 先回后正），只应有 §4 的 2 个文档冲突
[ ] 5. PHASE_STATUS 多条全保留；RESEARCH doc 取分支版本（§4.1 / §4.2）
[ ] 6. 冲突解决后：git diff --check clean；无 '^D' 误删（§5）
[ ] 7. 在 feat/backend 复跑全量 pytest + ruff，零失败
[ ] 8. 无未预测冲突 → feat/backend → main（--no-ff），再复核 diff --name-status
[ ] 9. 在 main 复跑全量 pytest + ruff（§6.1 flaky 复跑纪律）
[ ] 10. PHASE_STATUS 追加集成记录（§8）
[ ] 11. 向用户报告 merge 结果；push 与任何分支删除另行请示（§14.4）
```

---

## 附：本批次涉及的全部文件（16 个）

```text
A  docs/INTEGRATION_PROMPT_BUG012_MEMORY_EXTRACTION.md
A  docs/PRD_PROMPT_REGISTRY.md
A  docs/RESEARCH_PROJECT_MULTISESSION_AND_MEMORY_PLUGGABILITY.md
A  docs/adr/0023-prompt-registry.md
A  docs/integration/INTEGRATION_PROMPT_MODERATION_MESSAGE.md
M  CONTEXT.md
M  docs/BACKEND_CONTRACT_STREAMING_UI.md
M  docs/PHASE_STATUS.md                                   ← 冲突点 1
M  src/agent_harness/agent/runtime.py
M  src/agent_harness/memory/extractor.py                  ← 与 main 等价（组 B，合并后应为空差）
M  src/agent_harness/memory/writeback.py                  ← 同上
M  src/agent_harness/session/session.py
M  tests/agent/test_run_finalizer.py
M  tests/agent/test_runtime_failure_paths.py
M  tests/memory/test_extractor.py                         ← 与 main 等价
M  tests/memory/test_writeback.py                         ← 与 main 等价
```

（`A` = 新增，`M` = 修改；**没有任何 `D`**。）

**再加上本手册这一个 commit**：新增 `docs/integration/INTEGRATION_PROMPT_FEAT_BACKEND_PENDING_BATCH.md`，并刷新 `docs/integration/INTEGRATION_PROMPT_MODERATION_MESSAGE.md` 的 §5 拓扑（原文写的是 `origin/main = 63db650` / 领先 32 / 落后 0，已过期）。两者都是文档，**不引入新冲突**——本批最终为 **13 个 commit / 17 个文件 / 2 个文档冲突**。
