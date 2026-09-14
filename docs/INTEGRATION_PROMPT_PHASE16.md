# Integration Prompt — feat/phase16 → main

> 本文件是把 `feat/phase16`（Phase 16：Final Full E2E）合入 `main` 的**单分支合入手册**。
> 遵循仓库 `AGENTS.md` §13 并行开发 / §14 Git Workflow / §14.11 Approval Workflow。
> 适用对象：Git Integrator（或用户明确授权的集成角色）。

---

## 0. 一句话摘要

`feat/phase16` 在 `D:\intelligence-agent-phase16` 交付了 Phase 16「Final Full E2E」的全部产出：**ADR-0019 冻结决策 + Tickets #126-#130 逐票 TDD + Gate 6/6 PASS**（11 passed / 1 Docker probe-gated skipped / ruff clean）。Phase 16 是 Roadmap 的最终里程碑——完成场景链全链验证（历史 → 研究 → KB → Web → 引用 → coding → kill → 恢复 → replay → fork → Langfuse trace → Eval 报告）。本分支**未 push、未 merge**，等待用户审批。

---

## 1. 拓扑与前置检查

### 1.1 Branch 与 Worktree 映射（合入前必须复核，§14.2）

```bash
git worktree list --porcelain
# 期望：D:\intelligence-agent-phase16 的 branch 是 feat/phase16
git -C D:/intelligence-agent-phase16 branch --show-current
# 期望：feat/phase16
git -C D:/intelligence-agent-phase16 status --short
# 期望：clean（或仅有本手册新增的 docs 改动待 commit）
```

### 1.2 拓扑快照（合入前再跑一次确认）

```bash
git -C D:/intelligence-agent fetch origin --prune
git -C D:/intelligence-agent checkout main
git -C D:/intelligence-agent pull --ff-only origin main      # 仅 fast-forward
git -C D:/intelligence-agent merge-base main feat/phase16    # 记录 merge-base
git -C D:/intelligence-agent rev-list --count main..feat/phase16   # feat 领先 main 的 commit 数
git -C D:/intelligence-agent rev-list --count feat/phase16..main   # main 领先 feat 的 commit 数
```

> 上次记录的拓扑：merge-base = `0ac49f3`；`feat/phase16` 领先 7 commits；`main` 领先 9 commits；两边唯一文件交集是 `docs/PHASE_STATUS.md`（两边都改了 Phase 16 行 + 周边）。

### 1.3 Working Tree 必须 clean（§14.10 Validation Gate）

```bash
git -C D:/intelligence-agent-phase16 status --short
# 合入前所有源码改动必须已 commit；docs 改动随最后一次 commit 入库
```

---

## 2. feat/phase16 的 7 commits（领先 merge-base）

```
3b308bd test(phase16): T5 #130 replay/fork/langfuse-trace/eval-report 分段断言（ADR-0017/0019 D8/D12）
8bbbbe3 test(phase16): T4 #129 kill/restart/reconcile/sandbox-restore 分段断言（ADR-0003/0004/0019 D4/D5/D8）
1a38339 test(phase16): T3 #128 coding/edit/test-failure/mutating-tool 分段断言（ADR-0002/0004/0019 D6）
bad588a test(phase16): T2 #127 research/KB/web/citation + permission 分段独立断言（ADR-0019 D1/D8）
93174f1 test(phase16): T1 #126 E2E helpers + 薄编排层 critical path test（ADR-0019 D1/D7/D10）
97c842d docs(status): Phase 15 COMPLETED 修正 + Phase 16 IN PROGRESS（ADR-0019 立项）
1c09677 docs(phase16): ADR-0019 + CONTEXT.md Final E2E 术语（Phase 16 grill 三轮收敛）
```

> 本手册 + `docs/PHASE16_GATE.md` + `docs/PHASE_STATUS.md` 的 Phase 16 行更新会作为**第 8 个 commit**（docs 收尾）入库——见 §5。

### 2.1 改动文件清单

| 类型 | 路径 | 说明 |
| ---- | ---- | ---- |
| 新增 | `docs/adr/0019-phase16-final-e2e-segmented-assertions.md` | ADR-0019 冻结决策（12 项 D1–D12） |
| 新增 | `tests/integration/_phase16_helpers.py` | 薄编排层 + 全段 fixture（T1-T5 累积） |
| 新增 | `tests/integration/test_phase16_gate.py` | 12 个分段独立断言（Gate 主体） |
| 修改 | `tests/integration/_kill_child.py` | 向后兼容扩展：`backend` 字段（默认 `"local"`，不破坏 Phase 4 调用方） |
| 修改 | `CONTEXT.md` | 「Phase 16 / Final Full E2E」术语段 |
| 修改 | `docs/PHASE_STATUS.md` | Phase 15 行修正 + Phase 16 行立项→完成 |
| 新增 | `docs/PHASE16_GATE.md` | Gate 证据总表（本手册同批 commit） |
| 新增 | `docs/INTEGRATION_PROMPT_PHASE16.md` | 本手册 |

**scope 边界（§8）**：改动严格限定在 `docs/` + `tests/integration/`——**零 src/ 改动**（除 `_kill_child.py` 这一处向后兼容扩展，是测试基础设施而非产品代码）。Phase 16 是验证型 Phase，不引入新模块。

---

## 3. 验证门（合入 main 前必跑，§14.10）

### 3.1 在 feat/phase16 worktree 上跑

```bash
cd D:\intelligence-agent-phase16

# (a) Phase 16 Gate 本体
uv run pytest tests/integration/test_phase16_gate.py -m integration -v
# 期望：11 passed, 1 skipped（无 Docker daemon 时）

# (b) 全量离线回归（确保未引入跨模块回归）
uv run pytest -q
# 期望：基线 passed 数 + 无新失败（与本分支起点基线对齐）

# (c) Lint
uv run ruff check src/ tests/
# 期望：clean

# (d) Diff 卫生
git -C D:/intelligence-agent-phase16 diff --check
# 期望：无 whitespace / conflict-marker 问题
git -C D:/intelligence-agent-phase16 diff --stat main...feat/phase16
# 期望：只有上述 §2.1 清单内的文件
```

### 3.2 合入 main 后在 `D:\intelligence-agent` 上跑

```bash
cd D:\intelligence-agent
git checkout main
# 合入完成后（见 §5）：
uv run pytest -q                              # 全量回归
uv run pytest tests/integration/test_phase16_gate.py -m integration -v   # Gate 复核
uv run ruff check src/ tests/
```

---

## 4. 冲突预测与处置策略（§14.7）

### 4.1 唯一可能冲突的文件：`docs/PHASE_STATUS.md`

- **原因**：`feat/phase16` 与 `main` 都改了这张大表（`feat/phase16` 更新 Phase 15/16 行；`main` 在此期间也积累了集成记录行）。
- **冲突处置原则**（§14.7：逐文件分析，不机械 ours/theirs）：
  1. 保留 `main` 侧新增的集成记录行（它们记录的是 Phase 15 合入 main 等历史事实，不应被覆盖）。
  2. 保留 `feat/phase16` 侧对 Phase 15 行的修正（commit `97c842d` 已校正 Phase 15 状态为 ✅ COMPLETED——这是事实修正，不是覆盖历史）。
  3. 保留 `feat/phase16` 侧对 Phase 16 行的更新（本手册同批 commit 已把状态从 🔄 IN PROGRESS 更新为 ✅ COMPLETED，并附 commit 列表 + Gate 证据）。
  4. 表头、其它 Phase 行：以 `main` 为准（除非 `feat/phase16` 有明确事实修正）。
- **推荐语义**：两边都是「在同一张大表上追加事实」，没有逻辑对立——逐行手工合并即可，不需要 `ours`/`theirs`。
- **禁止**：为了让冲突消失直接删一侧整段（§14.7）。

### 4.2 其它文件：预期零冲突

- `docs/adr/0019-*.md`、`tests/integration/_phase16_helpers.py`、`tests/integration/test_phase16_gate.py`、`docs/PHASE16_GATE.md`、`docs/INTEGRATION_PROMPT_PHASE16.md`：纯新增，`main` 侧无对应文件 → 零冲突。
- `tests/integration/_kill_child.py`：`feat/phase16` 只加了一行 `backend = config.get("backend", "local")`（向后兼容）。若 `main` 在此期间也改了同一处，需逐行分析；概率低（Phase 4 已稳定）。
- `CONTEXT.md`：`feat/phase16` 在尾部新增「Phase 16」术语段；若 `main` 也改了 CONTEXT.md 的其它段，多半是不同段落，冲突可逐段手工合并。

### 4.3 冲突处置流程（§14.7 / §14.11）

1. 发生冲突**立即停止自动解决**；
2. 逐文件按 §4.1/§4.2 分析：`main` 改了什么、`feat/phase16` 改了什么、为什么冲突、能否同时保留、推荐最终语义、是否影响 Contract/Runtime/Test、风险等级；
3. **请求用户批准**后再 `git add` + 继续 merge；
4. 严禁机械 `ours`/`theirs` 或删侧让冲突消失。

---

## 5. 推荐合入流程（§14.6 先回后正 / §14.9 一次一个分支）

按「先回后正」方向，优先在 feature worktree 上把 `main` 合进来、解决冲突、跑全套验证，再合入 `main`：

```bash
# —— 在 feat/phase16 worktree 把 main 合进来 ——
cd D:\intelligence-agent-phase16
git fetch origin --prune
git merge origin/main           # 注意：不是 git pull（§14.5）
# 若冲突：按 §4 逐文件分析 → 请求用户批准 → git add <file> → git commit
uv run pytest tests/integration/test_phase16_gate.py -m integration -v
uv run pytest -q
uv run ruff check src/ tests/

# —— 在 main worktree 合入稳定的 feat/phase16 ——
cd D:\intelligence-agent
git checkout main
git merge feat/phase16
# 此时应零冲突（冲突已在上面解决）
uv run pytest -q
uv run pytest tests/integration/test_phase16_gate.py -m integration -v
uv run ruff check src/ tests/
```

**顺序约束（§14.9）**：本分支合入 `main` 时，**不要同时**集成其它 feature 分支。一个分支走完整套验证门、稳定下来，再处理下一个。

---

## 6. 合入后的遗留验证项

| 项 | 在哪里跑 | 期望 | 处置 |
| -- | --------- | ---- | ---- |
| 真实模型 smoke（ADR-0019 D2 双层模型的真模型层） | `D:\intelligence-agent` main 合入后 | 关键路径 4 轮用真实网关跑通；Langfuse trace 结构与本 Gate `test_langfuse_trace_structure_complete` 断言一致（root agent-run + generation + tool children ≥3 + metadata 含 session_id/run_id/agent_id） | 上游网关间歇 500 时沿用 Phase 14 probe-gated 登记法：SKIPPED 写明原因，FAIL 不掩盖，复跑直到拿到一次干净 trace |
| Docker 容器恢复（D5） | `D:\intelligence-agent` main 合入后，宿主启动 Docker daemon | `test_docker_sandbox_restore_after_kill` 从 SKIP 转 PASS：容器按 `container_name` 确定性重绑 + workspace Volume 内容跨进程保留 | daemon 不在场时保持 SKIP 登记（环境属性，非缺陷） |
| `.env` 同步 | `D:\intelligence-agent` main worktree | `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` 已就位（真云 jp 区） | **密钥值不得写进任何文档/commit/输出**（§安全边界）；只在本地 `.env` 文件层面同步 |

---

## 7. 安全边界与合规巡检

- **`.env` 密钥零泄漏**：本 Phase 全程使用 fake（FakeRecorder / FakeKnowledgeVectorStore / ScriptedModel），未触碰真实密钥；Gate 文档与 commit 消息中均不含密钥值。
- **Approval Workflow（§14.4 / §14.11）**：`feat/phase16` 只做了本地 commit；**未 push、未 merge、未创建 PR、未删除 branch/worktree、未 reset/rebase/cherry-pick**。所有这些动作都需用户明确逐项批准。
- **Scope Lock（§8）**：改动严格限定在 `docs/` + `tests/integration/`，零产品代码 src/ 改动（除 `_kill_child.py` 一处向后兼容扩展）；不顺手重构、不扩架构、不做投机性抽象。
- **不变量（§7）**：本 Gate 在分段断言中实证了 §7.3 / §7.7 / §7.11 / §7.12 / §7.13；详见 `docs/PHASE16_GATE.md` §5.4。

---

## 8. 完成判据（合入 main 的 Definition of Done）

- [ ] §3.1 在 `feat/phase16` 上四项全过（Gate / 全量回归 / ruff / diff --check）
- [ ] §5 合入流程执行完毕，`main` 上零冲突或冲突已逐文件分析 + 用户批准
- [ ] §3.2 在 `D:\intelligence-agent` main 上三项全过
- [ ] §4 冲突处置遵循「逐文件分析 + 用户批准」原则，未机械 ours/theirs
- [ ] §6 遗留验证项至少登记一次结果（PASS / SKIPPED+原因 / FAIL+复跑）
- [ ] `docs/PHASE_STATUS.md` Phase 16 行状态为 ✅ COMPLETED 且 commit 列表含最终合入 commit
- [ ] Tickets #126-#130 在 GitHub 上逐票关闭（带 commit + 测试数字证据评论）

---

## 9. 相关产物索引

- ADR：`docs/adr/0019-phase16-final-e2e-segmented-assertions.md`
- Gate 证据：`docs/PHASE16_GATE.md`
- 进度表：`docs/PHASE_STATUS.md`（Phase 16 行）
- 测试：`tests/integration/test_phase16_gate.py`、`tests/integration/_phase16_helpers.py`、`tests/integration/_kill_child.py`
- 术语：`CONTEXT.md`「Phase 16 / Final Full E2E」段
- Tickets：#126 / #127 / #128 / #129 / #130
