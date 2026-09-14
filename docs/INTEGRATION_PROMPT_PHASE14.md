# Phase 14 集成提示词（集成 AI 执行手册）

> **收件人**：集成 AI（Git Integrator 角色，AGENTS.md §14）
> **任务**：把 `feat/phase14`（Phase 14 Resume / Replay / Fork 完整化，ADR-0017，tickets #107-#115）合入 `main` 并完成验证
> **写于**：2026-09-06，分支 HEAD 见 `git -C D:\intelligence-agent-phase14 log -1`（本文件所在仓库）
> **红线**：永不 force-push / rebase / reset --hard；凭证零泄漏；每次合并动作前确认 worktree 与分支（§14.2）；冲突后立即停止自动解决（§14.7）
> **协作注记**：`feat/backend` 上另有流式改造（ADR-0016，#104-#106 区间的 B AI 会话）可能未合——**§14.9 一次一支**：若 feat/backend 未合入 main，先完成其集成再处理本分支；反之本分支先行亦可，后合者负责先回。

---

## 0. 机器现状（动手前复查）

| 路径 | 分支 | 角色 |
| --- | --- | --- |
| `D:\intelligence-agent` | `main` | **本次集成的主战场** |
| `D:\intelligence-agent-phase14` | `feat/phase14` | Phase 14 施工区（本分支） |
| `D:\intelligence-agent-backend` | `feat/backend` | 流式改造施工区（ADR-0016，另一 AI 会话） |

- Phase 14 内容 = ADR/术语/调研 1 commit + 9 票实现（`1685ed3`..#115 收尾）；对 main 的 diff 动手前 `git diff origin/main...HEAD --stat` 复核（预期 ~20 文件：session/fork+lineage 新模块、storage 扩列、cli 三命令、web/lineage.py、model/config zhipu preset、web/src/generated/event-types.ts、tests ×5、docs ×3）
- **零新 Python 依赖**；`.env` 无新密钥（`FALLBACK_MODEL_*` 若 main 侧已同步过智谱值则零改动——本分支 gate 用它实测过）
- 新 SessionEvent ×1：`session/forked`（child 文件 provenance 事件）；`web/src/generated/event-types.ts` 已由本分支再生成（backend-owned）
- 上游故障应对：主上游（senseaudio）间歇 500；main 侧 `.env` 的 fallback 已是智谱（独立上游）——Gate 若遇主上游抖动会经 fallback 自愈，属预期行为

## A. 施工区预清理（`D:\intelligence-agent-phase14`）

```bash
cd D:\intelligence-agent-phase14
git branch --show-current              # 必须是 feat/phase14
git status --short                     # 记录起点；工作区必须干净
```

可能的本地残留（均为运行时产物，不入库）：`sessions/`、`workspaces/`、`harness.db`、`.env`（从 backend worktree 复制的本机凭证——**保留，不要删**）、`.scratch/`（gitignored）。逐项核验后 `git clean -fd` 只清确认无价值者；`.env` 与任何拿不准的文件保留并报告。

## B. 先回后正 + 合入

```bash
git fetch origin --prune
git merge origin/main                  # 先回（预期仅 PHASE_STATUS.md 语义并集；本分支与流式改造文件面零交集——session/event.py 双方均为纯加法）
git -C D:\intelligence-agent merge --no-ff feat/phase14 -m "Merge feat/phase14: Phase 14 Resume/Replay/Fork (ADR-0017, #107-#115) — file-per-lineage fork + seed + lineage tree + copy-on-fork + tail summary + CLI fork/replay/sessions-tree + read-only web lineage API"
```

## C. 验证 Gate

```bash
cd D:\intelligence-agent-phase14
uv sync --all-extras                   # 本项目 gate 恒为 all-extras 口径
uv run pytest -q                       # 基线：1089 passed / 9 skipped / 25 deselected（±个位数波动，不得失败）
uv run ruff check src/ tests/
git diff --check
```

可选（本机有凭证，推荐）：Phase 14 真实 Gate 五条

```bash
uv run pytest tests/integration/test_phase14_gate.py -m integration -v   # 5 passed（生产装配形态：每会话一 runtime）
```

main 侧（`D:\intelligence-agent`）：`uv sync --all-extras` → `uv run pytest -q` 同基线 → `ruff check` → `.env` 核对 `FALLBACK_MODEL_PROVIDER=zhipu`（已有则零改动）→ 真实冒烟（可选）：

```bash
# 造一个会话后：
agent-harness fork <session_id> --from-message 1   # 观察 child id 输出
agent-harness sessions --tree                      # 观察 [fork @seq] 边
agent-harness replay <session_id>                  # 只读回放，终端应见 [用户]/[工具]/冻结结果
```

## D. Push 与收尾

1. 全绿后 `git push origin main`（最后一步）
2. `docs/PHASE_STATUS.md` 追加集成记录条目（范围/冲突解法/验证数字）
3. 关闭遗留：无
4. 向用户报告：完成什么 / 改了哪些 / 测试结果 / commit 区间 / 遗留项

## E. 集成后的已知协作点

1. **前端 lineage 树形渲染**：`GET /api/sessions/{id}/lineage` 已就绪（形状见 src/agent_harness/web/lineage.py docstring）——前端批应在**流式改造与本分支都合入后**进行（inspector 同窗改动），消费 delegation 边（Phase 13 已适配）+ fork 边（本批）统一树
2. **与 ADR-0016 流式改造的合并顺序**：本分支 `session/event.py` 只加了 `session/forked`；流式侧加 reasoning 事件族并修订 STREAM_ONLY——双方纯加法，预期自动合并；若冲突，按 §14.7 逐文件分析，语义并集
3. **DEFER 清单**（ADR-0017）：重新执行式 replay / 步进 TUI / Web 发起 fork / tree-in-file 导航
