# 集成提示词：feat/multiturn → main

> **分支**：`feat/multiturn`
> **Worktree**：（无专用 worktree——分支作为裸 ref 存在；集成时需 checkout 到临时 worktree 或直接在 main worktree merge）
> **起点（merge-base）**：`70f2671`（feat/multiturn 由此分叉）
> **HEAD**：`3915a5a`
> **main HEAD**：`080e1f1`（main 在 merge-base 之后又走了 32 个 commit——含三个 RUNTIME 子批次 + 多个前端批次）
> **改动规模**：45 files changed, +4452/-370（vs merge-base）
> **合并难度**：⚠️ **高**——5 个文件有 content conflict，其中 3 个涉及语义冲突（不只文本）

---

## ⚠️ 重要：这不是简单 merge——有语义冲突

feat/multiturn 从 `70f2671` 分叉时，三个 Phase 5 RUNTIME 字段（`reasoning_effort` / `agent_profile` / `context_providers`）都还是 staged no-op。feat/multiturn 自己消费了 `reasoning_effort`（commit `63a437b`），但 **main 分支后来独立消费了全部三个**（ADR-0018 D7 / ADR-0020a / ADR-0020b）。两边的 `reasoning_effort` 实现方式不同——这是必须人工决策的语义冲突，不是机械合并能解决的。

### 关键语义冲突：`reasoning_effort` 实现方式不同

| | feat/multiturn (HEAD) | main (origin/main) |
| --- | --- | --- |
| **域值映射** | `minimal→low, standard→medium, deep→high`（REASONING_EFFORT_TO_API 映射表） | 直接传 `minimal/standard/deep`（ChatOpenAI 原生支持这些值） |
| **未知值** | `raise ValueError`（响亮失败） | 不校验（web 层已 422，runtime 不重复） |
| **位置** | `model/provider.py` + `assembly.py` | `model/provider.py` + `assembly.py` |
| **注释** | "RUNTIME 子批次 1" | "ADR-0018 D7" / "RUNTIME 子批次" |

**推荐决策：采用 main 版本。** 理由：
1. main 的三个 RUNTIME 子批次是 **完整系列**（reasoning_effort + agent_profile + context_providers），经过独立 code-review + 集成验证。
2. main 直接传域值（`minimal/standard/deep`），ChatOpenAI 原生支持——不需要额外映射表。feat/multiturn 的 `low/medium/high` 映射是基于早期假设（当时 ChatOpenAI 可能不支持域值），但后续验证发现原生支持。
3. feat/multiturn 的 `reasoning_effort` 实现是它的副产物（它在解决 multiturn 时顺手做了 RUNTIME 子批次 1），main 的实现是专门的 RUNTIME 子批次产物。

**具体操作：冲突文件中 reasoning_effort 相关部分全部取 main 版（`origin/main` 侧）。**

---

## Dry-run merge 冲突清单（已实际验证）

```
git checkout feat/multiturn
git merge --no-commit --no-ff origin/main
```

产生 **5 个文件 × 15 个 conflict hunk**：

| 文件 | conflict 数 | 冲突性质 |
| --- | --- | --- |
| `src/agent_harness/model/provider.py` | 3 | **语义冲突**：reasoning_effort 映射 vs 直接传——**取 main 版** |
| `src/agent_harness/assembly.py` | 2 | **语义冲突**：reasoning_effort 注释 + agent_profile/context_providers 消费——**取 main 版**（main 已完整消费三个字段） |
| `src/agent_harness/web/app.py` | 7 | **混合冲突**：reasoning_effort/agent_profile/context_providers 的注释 + validator + 清单端点（取 main 版）**以及** 续聊端点 + WebSocket + SessionService 相关新增（取 feat/multiturn 版）——需逐 hunk 分析 |
| `tests/test_assembly.py` | 1 | 测试 fixture 对齐——取 main 版的 lambda 签名（`**kw`） |
| `tests/web/test_web_models.py` | 2 | 测试 fixture 对齐——取 main 版的 lambda 签名 |

### 以下文件 auto-merge 成功（无冲突）

```
src/agent_harness/context/builder.py    （compaction bracket + system_prompt 双方改动不同区域）
src/agent_harness/web/__init__.py
tests/test_cli.py
tests/test_sse_disconnect.py
tests/test_structured_logging.py
tests/test_web_phase5.py
tests/web/test_web_cancel.py
tests/web/test_web_phase5_approval.py
tests/web/test_web_stream.py
```

### 完全新增文件（零冲突风险）

feat/multiturn 引入的核心新模块（main 中不存在）：

| 文件 | 行数 | 功能 |
| --- | --- | --- |
| `src/agent_harness/session/service.py` | 810 | **SessionService 领域层**——multiturn 的核心 |
| `src/agent_harness/session/queue.py` | 143 | 消息队列（续聊 steer/queue 事件） |
| `src/agent_harness/web/websocket.py` | 274 | WebSocket mux（续聊实时通道） |
| `demo/live_agent_repl.py` | 122 | CLI 续聊 REPL demo |
| `tests/session/test_service.py` | 215 | SessionService 测试 |
| `tests/session/test_queue.py` | 130 | queue 测试 |
| `tests/web/test_web_multiturn.py` | 154 | 续聊端点 E2E |
| `tests/web/test_web_batch51_spec_contract.py` | 384 | Batch 5.1 契约测试 |
| `tests/context/test_compaction_bracket.py` | 325 | 4-event compaction bracket 测试 |
| `tests/test_live_agent_repl.py` | 99 | CLI REPL 测试 |

---

## feat/multiturn 做了什么（12 个 commit）

| Commit | 功能 |
| --- | --- |
| `f4f0544` | Batch 5.1 permission/resolved 审计 trail + PermissionDecision 契约 |
| `a4c039a` | B1 集成提示词 + 前端 F1 执行手册（文档） |
| `80340ed` | merge main（先回后正 §14.6） |
| `54056c4` | **T1 #131 — SessionService 领域层抽离**（核心） |
| `0f39838` / `053f919` | T-IDENTITY — StaticFiles mount 遮蔽 /identity-probe 路由（main 也独立修了这个） |
| `c7a3dfd` | **T2 #132 — 续聊端点 + WebSocket mux + queue/steer 事件**（核心） |
| `4ac4643` | **T3 #133 — CLI 续聊 REPL + slash 命令** |
| `dc08fbd` | code-review fix #1 — pass created_at to enqueue/register_steer |
| `343531f` | code-review fix #3 — extract _append_session_event helper |
| `63a437b` | **reasoning_effort 消费**（与 main 重复——冲突源） |
| `f64360f` | RUNTIME 子批次 1 集成交接单（文档） |
| `3915a5a` | **T4 #134 — 4-event compaction bracket + six-section summary** |

### 四个主要功能域

1. **SessionService（T1 #131）**：从 web/app.py 内联逻辑抽离出领域层 `SessionService`（810 行），封装 session 生命周期（create / continue / queue / steer）。
2. **续聊端点 + WebSocket（T2 #132）**：新增 `POST /api/sessions/:id/continue` 续聊端点 + WebSocket mux（`web/websocket.py`）+ queue/steer 事件类型（`session/queue.py`）。
3. **CLI 续聊 REPL（T3 #133）**：`demo/live_agent_repl.py` + slash 命令交互界面。
4. **4-event compaction bracket（T4 #134）**：`context/compactor.py` 重构——compaction 从单 `CONTEXT_COMPACTED` 事件升级为 `COMPACTION_START` + `CONTEXT_COMPACTED`（六段摘要） + `COMPACTION_END` 三事件 bracket。同时 `auto_compact_threshold` 从 0.70→0.80、`hard_guard_threshold` 从 0.85→0.90。

---

## 集成步骤（推荐）

### 方案：在 main worktree 用「先回后正」方向 merge

```bash
# 1. 在 feat/multiturn worktree（或临时 checkout）先 merge main 解决冲突
git fetch origin
git checkout feat/multiturn   # 或建临时 worktree
git merge origin/main

# 2. 逐文件解决冲突（见下方逐文件指引）
#    核心原则：RUNTIME 三字段相关取 main 版；multiturn 功能取 feat/multiturn 版

# 3. 验证
python -m pytest --tb=short -q
ruff check

# 4. commit merge
git add .
git commit  # merge commit

# 5. 在 main worktree merge feat/multiturn（此时 feat/multiturn 已含 main，无冲突）
cd D:\intelligence-agent
git merge feat/multiturn

# 6. 最终验证 + push（按用户指示）
python -m pytest --tb=short -q
ruff check
# git push origin main  ← 仅在用户明确批准后
```

### 逐文件冲突解决指引

#### `src/agent_harness/model/provider.py`（3 hunks）→ **全部取 main 版**
- `REASONING_EFFORT_TO_API` 映射表：**删掉**（main 不需要映射）
- `create_chat_model` 签名：取 main 版（`reasoning_effort: str | None = None` 直接传入）
- 注释：取 main 版（"ADR-0018 D7"）
- 构造器 kwargs：取 main 版（`kwargs["reasoning_effort"] = reasoning_effort`，不映射）

#### `src/agent_harness/assembly.py`（2 hunks）→ **取 main 版**
- 注释块（profile_spec lookup + context_providers 消费）：取 main 版——main 已完整消费三个 RUNTIME 字段
- fallback 模型构造的尾逗号差异：取任一侧（纯格式）

#### `src/agent_harness/web/app.py`（7 hunks）→ **逐 hunk 分析**
这是最复杂的文件。原则：
- **reasoning_effort / agent_profile / context_providers 的注释、validator、清单端点**：取 main 版（main 的实现更新更完整）
- **CONTEXT_PROVIDER_DESCRIPTIONS 常量**：取 main 版
- **续聊端点（continue）+ WebSocket + SessionService 调用**：取 feat/multiturn 版（这是它的核心功能）
- **create_session 中的 run launch 路径**：需确认 main 的 ADR-0016 detached-run 与 feat/multiturn 的 SessionService 路径如何整合——**这是最需要人工判断的区域**

#### `tests/test_assembly.py`（1 hunk）→ **取 main 版**
- lambda 签名 `lambda config, **kw:` 是 main 的格式（接受 reasoning_effort kwarg）

#### `tests/web/test_web_models.py`（2 hunks）→ **取 main 版**
- 同上，lambda 签名对齐

### ⚠️ 注意重复测试文件

feat/multiturn 引入了 `tests/test_reasoning_effort.py`（148 行），main 已有 `tests/model/test_reasoning_effort.py`（53 行）。合并后两个文件都会存在——内容重叠但路径不同。**建议合并后删除 feat/multiturn 版（`tests/test_reasoning_effort.py`）**，保留 main 版（`tests/model/test_reasoning_effort.py`），因为 main 版是专门批次产物且已通过集成验证。

---

## 验证要点

### 合并后必须通过

```bash
# Python 3.13 环境下全量测试
python -m pytest --tb=short -q
ruff check
```

### 重点关注

1. **SessionService 路径与 main 的 build_runtime 路径整合**：feat/multiturn 的 `session/service.py` 调用 `build_runtime`——合并后需确认它传的参数与 main 的签名（含三个已消费的 RUNTIME 字段）兼容。已知 `service.py:286` 透传 `agent_profile`（之前勘察过）。
2. **compaction bracket 事件**：feat/multiturn 改了 `context/builder.py` 的 compaction 逻辑（新增 `COMPACTION_START` / `COMPACTION_END` 事件 + 阈值变更 0.70→0.80）。main 的 `builder.py` 有 `system_prompt` 注入（ADR-0020a）。两者的 `builder.py` 改动在**不同区域**（compaction 在 compact() 内，system_prompt 在 build() 返回前），auto-merge 成功——但合并后需确认 system_prompt token 估算与 compaction bracket 的交互正确。
3. **compaction 阈值变更**：`auto_compact_threshold` 从 0.70→0.80、`hard_guard_threshold` 从 0.85→0.90。这是行为变更——既有测试若依赖旧阈值可能需要更新。
4. **T-IDENTITY 修复**：feat/multiturn 和 main 各自独立修了同一个 bug（StaticFiles mount 遮蔽 /identity-probe 路由）——合并后应只有一份。

---

## 风险矩阵

| 风险 | 等级 | 缓解 |
| --- | --- | --- |
| app.py 7-hunk 冲突需逐个语义判断 | **高** | 本提示词逐 hunk 给了取侧建议；最复杂区域（create_session launch 路径）需人工确认 SessionService 与 detached-run 整合 |
| reasoning_effort 双实现 | **高** | 明确取 main 版；删掉 feat/multiturn 的映射表 + 旧测试文件 |
| compaction 阈值变更影响既有测试 | **中** | 合并后跑全量测试，按需更新 |
| 重复 T-IDENTITY 修复 | **低** | auto-merge 会处理（同一文件两边改同样内容） |
| builder.py compaction + system_prompt 交互 | **中** | auto-merge 成功但需验证——跑 `tests/context/` 全量 |
| feat/backend 有另一会话未提交 T5 工作 | **低** | 本合并不涉及 feat/backend |

---

## 与其他分支的关系

- **`main`（`080e1f1`）**：目标分支。已含三个 RUNTIME 子批次 + agent_profile system_prompt + context_providers 筛选 + 多个前端批次。
- **`feat/backend`**：有另一会话未提交 T5 (#135) MinIO 工作——**不涉及本次集成**。
- **`feat/runtime-context-providers`（`0e3f037`）**：已合入 main（`e18b7fa`）。
- **`feat/runtime-agent-profile`（`2dce596`）**：已合入 main（`11e5494`）。
- **`feat/runtime-reasoning-effort`（`88310b2`）**：已合入 main（`79e2860`）。

---

## 总结：这是一个需要人工判断的复杂集成

feat/multiturn 是一个 **45 文件 / +4452 行的大型功能分支**，核心贡献是 SessionService 领域层 + 续聊端点 + WebSocket + CLI REPL + compaction bracket。但它在分叉后做了 reasoning_effort 消费（副产物），与 main 的专门 RUNTIME 子批次系列冲突。

**集成 AI 需要做的核心决策：**
1. reasoning_effort 三字段实现全部取 main 版（语义更完整）。
2. app.py 的续聊/WebSocket 功能取 feat/multiturn 版，RUNTIME 三字段的 validator/清单端点取 main 版。
3. 合并后删除重复的 `tests/test_reasoning_effort.py`（保留 main 的 `tests/model/test_reasoning_effort.py`）。
4. 验证 SessionService 与 main 的 build_runtime 签名兼容。
5. 验证 compaction bracket 与 system_prompt 注入的交互。

**建议集成 AI 在解决冲突后、commit 前，先跑一轮测试确认绿，再 commit merge。**
