# Phase 13 集成提示词（集成 AI 执行手册）

> **收件人**：集成 AI（Git Integrator 角色，AGENTS.md §14）
> **任务**：把 `feat/backend` 的 Phase 13（Multi-Agent / Delegation，ADR-0015，tickets #82-#93）合入 `main` 并完成验证
> **写于**：2026-09-06，后端 HEAD = `80eaad6`（本文件所在仓库 `D:\intelligence-agent-backend`，动手前以 `git log -1 --oneline` 为准）
> **红线**：永不 force-push / rebase / reset --hard；凭证零泄漏（.env 内容绝不打印/提交/复制进文档）；每次合并动作前确认所在 worktree 与分支（§14.2）；冲突后立即停止自动解决（§14.7）

---

## 0. 机器现状（已核验的事实，动手前复查）

三 worktree 布局（§13.1）：

| 路径 | 分支 | 角色 |
| --- | --- | --- |
| `D:\intelligence-agent` | `main` | **本次集成的主战场** |
| `D:\intelligence-agent-backend` | `feat/backend` | 后端施工区 |
| `D:\intelligence-agent-frontend` | `feat/frontend` | 本轮不动 |

- Phase 13 内容 = **12 commits**（`79a0014` ADR-0015 + 术语起，至 `0f1d01d` #91）+ #93 收尾 commit（Gate 文档 / PHASE_STATUS / 本手册 / 集成 gate 测试）；对 origin/main 的 diff ≈ 34 文件 +2500/−25（动手前 `git diff origin/main...HEAD --stat` 复核）
- **零新 Python 依赖**：`uv.lock` / `pyproject.toml` 零变化。LangGraph **未引入**——#92 只交付 `OrchestrationAdapter` Protocol seam（protocol-only，import 边界契约测试钉死 Core 永不 import langgraph）
- **无新 .env 密钥**。启用 multiagent 只需改 `CAPABILITIES` 现有 JSON 配置（见 §D2）
- 新增配置键（可选，有默认值）：`MODEL_MAX_CONCURRENCY`（进程级模型并发闸门，默认 3——防多 child 并行打爆上游 QPS/TMP 限额；不配 = 3）
- 新增 SessionEvent ×2：`agent/delegation-started` / `agent/delegation-finished`（父 JSONL 白盒事件，决策 6/8）；`web/src/generated/event-types.ts` 已由后端同步（backend-owned，+2 类型），前端投影层尚未消费——未适配前落 UnknownSurface 兜底（不丢）
- 上游网关（senseaudio）在 Gate 期间间歇故障（超时/500 服务繁忙）：集成验证若遇 model/failed + InternalServerError，先探针确认上游再怀疑代码（§C2 注记）

### refs 闪断恢复协议（历史发生过多次）

若 git 报 `ambiguous HEAD` / ref 凭空消失：

```bash
git fetch origin
git log origin/feat/backend -1          # 拿到 origin 侧 tip
git update-ref refs/heads/feat/backend <origin-tip-sha>
git log -1                              # 自检
```

origin 是唯一恢复源。

---

## A. 后端 worktree 预清理（`D:\intelligence-agent-backend`，目的：§14.2 merge 前工作区干净）

```bash
cd D:\intelligence-agent-backend
git branch --show-current                          # 必须是 feat/backend
git status --short                                 # 记录起点
```

已核验的未提交残留（性质各異，逐项处理）：

1. `tests/integration/test_phase13_gate.py` — **#93 交付物，必须已随 #93 commit 入库**（若仍 untracked，说明 #93 收尾 commit 缺失，停下来报告用户）
2. `sessions/`、`workspaces/` — 本地运行时产物（gate/冒烟运行写入），**不入库**：确认 `.gitignore` 已覆盖后 `git clean -fd sessions/ workspaces/`
3. `.tmp-pytest/` — 调试残留，直接 `git clean -fd .tmp-pytest/`（先 `ls` 抽查内容确无价值）
4. 其他任何意外修改 — 逐文件 `git diff` 核验后再决定，拿不准停下来报告

```bash
git status --short                                 # 必须为空（或仅 gitignore 产物）
```

## B. 先回后正：merge origin/main 进 feat/backend（§14.6）

```bash
git fetch origin --prune
git merge origin/main
```

### C1. 冲突处理原则

本次 origin/main 领先仅 2 commits（`bf5ae1a` merge + `636de0f` docs，后者只改 `docs/PHASE_STATUS.md` +2 行）——预期**零冲突或仅 PHASE_STATUS.md**：

- **`docs/PHASE_STATUS.md`**：feat/backend 侧是 Phase 12 完成条目翻转 + Phase 13 完成条目；main 侧是 2 行集成记录——**语义并集**：按日期倒序共存，一条都不丢
- 超出此清单出现冲突 = 停下来逐文件分析（§14.7），禁止机械 ours/theirs

## C2. 合并后验证 Gate（§14.10，在 feat/backend 上）

```bash
uv sync --all-extras              # 本项目 gate 恒为 all-extras 口径（裸 sync 被 extras 剪枝——Phase 12 教训）
uv run pytest -q                 # 基线：见下「测试基线」
uv run ruff check src/ tests/    # clean
git diff --check                 # 无 whitespace/冲突标记
```

**测试基线**：Phase 12 基线 987 + Phase 13 纯新增 58+（`test_profiles_factory` / `multiagent/` / `test_multiagent_wiring` / `test_concurrency_gate` / `test_seam` 等）+ 熔断全循环 pin + event_store 2 条——总数以 **#93 commit 后 `uv run pytest -q` 实测为准**（预期 ≥1049 passed），允许 ±个位数波动（main 侧可能带新测试），**不得出现失败**；有失败先定位是合并语义问题还是 main 侧既有问题，报告后再继续。

可选（本机有凭证，推荐做）：Phase 13 真实 Gate 八条

```bash
uv run pytest tests/integration/test_phase13_gate.py -m integration -v
# 上游网关故障期会批量失败（model/failed InternalServerError）——先探针：
# 20s 超时直接调 MODEL_BASE_URL 一次小请求，确认上游健康再跑 Gate
```

## D. 主战场：main 侧合入与验证（`D:\intelligence-agent`）

### D1. 合入

```bash
cd D:\intelligence-agent
git branch --show-current                          # 必须是 main
git status --short                                 # 必须干净（不干净先报告用户）
git fetch origin --prune
git merge --no-ff feat/backend -m "Merge feat/backend: Phase 13 Multi-Agent/Delegation (ADR-0015, #82-#93) — everything-is-a-plugin capability + delegate tool + AgentFactory/profiles + budget/breaker + LangGraph seam"
```

### D2. main 侧 .env 增补（无新密钥；CAPABILITIES 按行编辑，绝不回显其他键值）

1. **启用 multiagent（可选，默认关）**：在 main 侧 `.env` 的 `CAPABILITIES` JSON 中追加：

```json
"multiagent": {"provider": "builtin", "enabled": true, "options": {}}
```

   （不启用 = 单代理零感知，main 默认行为不变——推荐集成验证时启用以跑 D4 冒烟）
2. **可选**：`MODEL_MAX_CONCURRENCY=3`（或按上游限额调低，如 2）——进程级模型并发闸门，多 child 并行委派时防上游 QPS/TMP 限流
3. `MODEL_*` / `FALLBACK_MODEL_*` / `TAVILY_API_KEY` 等 Phase 12 键值 main 侧已同步，无需动

### D3. main 侧验证 Gate

```bash
uv sync --all-extras
uv run pytest -q                 # 与 C2 同基线口径
uv run ruff check src/ tests/
```

### D4. 真实冒烟（CAPABILITIES 启用 multiagent 后）

```bash
uv run uvicorn agent_harness.web.app:create_app --factory --host 127.0.0.1 --port 8000
# 另开终端：
curl http://127.0.0.1:8000/api/health
```

冒烟场景（SSE 逐项验证）：

1. **单代理回归**：`POST /api/sessions` 发「1+1等于几」→ run/completed，行为与 Phase 12 完全一致（multiagent 启用不影响琐碎任务——delegate 工具描述明确「不要为委派而委派」）
2. **委派链路**：发「用 delegate 工具把任务委派给 research_review：搜索 Python 官网网址，一句话回答」→ SSE 应见 `agent/delegation-started` → `tool/call(delegate)` → `agent/delegation-finished`（status=completed）→ 最终回答引用 child 结果
3. **父流白盒**：`GET /api/sessions/{id}/events` 父流只有紧凑事件（delegation-started/finished 在场，无 child 内部多轮 delta）；child session_id 在 delegation 事件 data 里，child 自己的 JSONL 有完整历史
4. （可选）mixed 任务：research 搜索结论 → coding 写文件 → 共享 workspace 出现产物

注记：若上游网关故障期（model/failed InternalServerError + model/fallback 事件后 run/failed），先探针上游健康再复跑——fallback 正确触发但双 provider 共用同一网关时无法自救，属环境噪声非代码缺陷。

### D5. Push（最后一步，前面全绿才做）

```bash
git push origin main
```

## E. 收尾报告（main 侧）

1. `docs/PHASE_STATUS.md` 更新日志加一条集成记录（范围、冲突解法、验证数字，参照既有集成条目格式）
2. `docs/INTEGRATION_NOTES.md` 若有新协作点则追加
3. 向用户报告：完成什么 / 改了哪些 / 测试结果 / commit 区间 / 遗留项

## F. 集成后的已知协作点（写给用户的交接，不是本次要做的）

1. **前端投影适配**（`feat/frontend` 侧，**手册已备**：`docs/FRONTEND_PROMPT_PHASE13.md`）：两个新 SessionEvent `agent/delegation-started`（data: target/task/child_session_id）与 `agent/delegation-finished`（data: target/child_session_id/status/summary）的前端渲染——`web/src/generated/event-types.ts` 已由后端同步（backend-owned），投影层尚未消费，未适配前落 UnknownSurface 兜底（不丢）。可做的 UI：Trace Ladder 委派节点 + 点击跳 child session 钻取（child_session_id 已在事件 data，决策 8 白盒边界）。**前端批应在本次集成（D 节）完成后启动**——其类型常量随本批 merge 到达 main
2. **LangGraph 编排（DEFER，seam 已就位）**：`src/agent_harness/orchestration/adapter.py` 是 Protocol-only seam（#92）；接 LangGraph = 新增 adapter 实现（Graph State → agent node 调 AgentRuntime → 结果写回；Graph Checkpoint 永不替代 Operation Ledger），Core 零改动。import 边界由契约测试守护，新违反必须显式进豁免清单
3. **深度 >1 / fork / 异步 park-revive（Phase 14 地盘）**：`AgentSpec.max_depth` 字段已保留（V1=1，child 无 delegate）；lineage = delegation 事件 child_session_id 引用，Phase 14 lineage tree 直接消费；V1 阻塞串行/阻塞并行，异步委派待 Phase 14+
4. **上游网关稳定性**：senseaudio 间歇故障（500 服务繁忙/超时挂起）在 Gate 期间反复出现；可靠性层（看门狗 + fallback + 熔断）行为正确但双 provider 共用同一网关无法自救。若持续，建议上游侧更换/增设独立 fallback provider
