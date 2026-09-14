# Phase 12 集成提示词（集成 AI 执行手册）

> **收件人**：集成 AI（Git Integrator 角色，AGENTS.md §14）
> **任务**：把 `feat/backend` 的 Phase 12 + 性能硬化 + 可靠性收尾合入 `main` 并完成验证
> **写于**：2026-09-06，后端 HEAD = `4925b55`（本文件所在仓库 `D:\intelligence-agent-backend`）
> **红线**：永不 force-push / rebase / reset --hard；凭证零泄漏（.env 内容绝不打印/提交/复制进文档）；每次合并动作前确认所在 worktree 与分支（§14.2）

---

## 0. 机器现状（已核验的事实，直接采信但动手前复查）

三 worktree 布局（§13.1）：

| 路径 | 分支 | 角色 |
| --- | --- | --- |
| `D:\intelligence-agent` | `main` | **本次集成的主战场** |
| `D:\intelligence-agent-backend` | `feat/backend` | 后端施工区（HEAD `4925b55`，已 push） |
| `D:\intelligence-agent-frontend` | `feat/frontend` | 本轮不动 |

- `feat/backend` 领先 merge-base **12 commits**（Phase 12 六票 + 性能硬化 + DSML 泄漏守卫 + 流式卡流看门狗 + 文档）；对 origin/main 的 diff = 46 文件 +4044/−72；**零新 Python 依赖**（无需 uv sync 新包）
- `origin/main` 比 merge-base 多 48 commits（期间的其它集成）
- 双方都改过的文件仅 2 个：`.gitignore`、`docs/PHASE_STATUS.md`（预期冲突点，见 §C2）
- **端口 8000 上有一个旧代码进程在跑**（Phase 12 之前启动）——集成验证前必须先杀掉重启，否则会测到旧代码
- 后端 worktree 的 `.env` 含全部所需凭证（`MODEL_*`、`FALLBACK_MODEL_*`、`TAVILY_API_KEY`、`CAPABILITIES` 共 7 行新增键）；main 侧 `.env` 需要同步这些键（§D2）
- 后端 worktree 的 `.scratch/perf/` 有一套冒烟脚本（smoke.py / probe.py，已 gitignore 不入库）——集成验证可参考其模式，但不依赖它存在

### refs 闪断恢复协议（历史发生过 4 次）

若 git 报 `ambiguous HEAD` / `does not have any commits yet` / ref 凭空消失：

```bash
git fetch origin
git log origin/feat/backend -1          # 拿到 origin 侧 tip
git update-ref refs/heads/feat/backend <origin-tip-sha>
```

恢复后 `git log -1` 自检。origin 是唯一恢复源。

---

## A. 后端 worktree 预清理（`D:\intelligence-agent-backend`，目的：满足 §14.2 merge 前工作区干净）

后端 worktree 有一批**未提交内容，性质已逐一核验**：

1. `AGENTS.md` / `CLAUDE.md` / `docs/INTEGRATION_NOTES.md` — 与 origin/main 逐字节一致（main 同步残留）
2. `docs/PHASE_STATUS.md` — = feat/backend 已提交版 + main 的集成记录（记录已在 origin/main 上，merge 会带回）
3. `web/` 全部修改 + 全部 untracked 新文件（auth.ts、toolShapes.ts、vitest 配置等）— **本 worktree 的陈旧副本，main 侧是超集**（diff 方向已验证：main 有 formatTimestamp/auth/toolShapes/vitest 等新内容而 worktree 没有；无任何未推新工作）
4. 根目录的研究残留（.rs/.ts/.json 片段）——**已删除**，若再现照删

执行（每步先验证再动手）：

```bash
cd D:\intelligence-agent-backend
git branch --show-current                          # 必须是 feat/backend
git status --short                                 # 记录起点

# 逐文件核验「main 侧是超集」后再丢弃（本次已预验证 9 个差异文件全部如此；
# 若你核验时发现任何文件是 worktree 侧有而 main 没有的新工作 —— 停止，报告用户）
git diff origin/main -- web/src/lib/format.ts      # 抽查方向：应为 main 侧多内容

git checkout -- AGENTS.md CLAUDE.md docs/INTEGRATION_NOTES.md docs/PHASE_STATUS.md web/
git clean -f docs/HANDOFF_PERF_FRONTEND.md \
  web/src/components/Conversation.test.tsx web/src/components/CopyButton.tsx \
  web/src/components/StepDetail.test.tsx web/src/hooks/useSession.test.ts \
  web/src/lib/auth.ts web/src/lib/projection.perf.test.ts \
  web/src/lib/toolShapes.test.ts web/src/lib/toolShapes.ts \
  web/vitest.config.ts web/vitest.perf.config.ts
git status --short                                 # 必须为空
```

（被丢弃内容的权威版本都在 origin/main 上，随 §B 的 merge 原样回来，零丢失。）

## B. 先回后正：merge origin/main 进 feat/backend（§14.6）

```bash
git fetch origin --prune
git merge origin/main
```

### C1. 冲突处理原则

预期冲突文件（超出此清单出现冲突 = 停下来逐文件分析，禁止机械 ours/theirs）：

- **`docs/PHASE_STATUS.md`**：feat/backend 侧是 Phase 12 完成条目（两条，2026-09-06），main 侧是期间的集成记录条目——**语义并集**：两条时间线按日期倒序共存，一条都不丢（前两次集成的先例同款）
- **`.gitignore`**：双方各自追加条目——并集即可

## C2. 合并后验证 Gate（§14.10，在 feat/backend 上）

```bash
uv sync --all-extras              # 本项目 gate 恒为 all-extras 口径（裸 sync 被 extras 剪枝）
uv run pytest -q                 # 基线：987 passed / 8 skipped / 12 deselected
uv run ruff check src/ tests/    # clean
git diff --check                 # 无 whitespace/冲突标记
```

测试数允许 ±个位数波动（main 侧 48 commits 可能带了新测试），但**不得出现失败**；有失败先定位是合并语义问题还是 main 侧既有问题，报告后再继续。

可选（本机有凭证，推荐做）：真实 Gate 三条

```bash
uv run pytest tests/integration/test_phase12_web_gate.py -m integration -v   # 3 passed
```

## D. 主战场：main 侧合入与验证（`D:\intelligence-agent`）

### D1. 合入

```bash
cd D:\intelligence-agent
git branch --show-current                          # 必须是 main
git status --short                                 # 必须干净（不干净先报告用户）
git fetch origin --prune
git merge --no-ff feat/backend -m "Merge feat/backend: Phase 12 (Web Search / Reliability) + perf hardening + stream watchdog"
```

### D2. main 侧 .env 增补（凭证经文件复制，绝不回显）

main 侧 `.env` 需要追加后端 worktree `.env` 已有的 7 行键（用脚本/编辑器按行复制，**不要 cat 到终端或写进任何文档**）：
`MODEL_PROVIDER` / `MODEL_NAME` / `MODEL_BASE_URL` / `MODEL_API_KEY` / `FALLBACK_MODEL_PROVIDER` / `FALLBACK_MODEL_NAME` / `FALLBACK_MODEL_BASE_URL` / `FALLBACK_MODEL_API_KEY` / `TAVILY_API_KEY` / `CAPABILITIES`（值以后端 worktree `.env` 为准）。

### D3. main 侧验证 Gate

```bash
uv sync --all-extras
uv run pytest -q                 # 与 C2 同基线口径；main .env 缺 Qiniu artifact 凭证时允许 +2 skip（历史基线口径）
uv run ruff check src/ tests/
```

### D4. 真实冒烟（杀掉旧进程后）

```bash
# 杀掉 8000 上的旧进程后：
uv run uvicorn agent_harness.web.app:create_app --factory --host 127.0.0.1 --port 8000
# 另开终端：
curl http://127.0.0.1:8000/api/health
# 会话列表（应 <100ms 热态）
curl http://127.0.0.1:8000/api/sessions
# 全链路：POST /api/sessions 发一个需要 bash 工具的任务，SSE 流应看到
# run/completed + 正确 final_text；再发一个要求 web_search 的任务应看到
# tool/call(web_search) → tool/result → 回答引用真实网页
```

### D5. Push（最后一步，前面全绿才做）

```bash
git push origin main
```

## E. 收尾报告（main 侧）

1. `docs/PHASE_STATUS.md` 更新日志加一条集成记录（范围、冲突解法、验证数字，参照既有集成条目格式）
2. `docs/INTEGRATION_NOTES.md` 若有新协作点则追加
3. 向用户报告：完成什么 / 改了哪些 / 测试结果 / commit 区间 / 遗留项

## F. 集成后的已知协作点（写给用户的交接，不是本次要做的）

1. **前端投影适配**（`feat/frontend` 侧）：两个新 SessionEvent `tool/failure-guard`（soft/hard 两级）与 `model/fallback`（from/to/reason/usage）的前端渲染——`web/src/generated/event-types.ts` 已由后端同步（backend-owned），投影层尚未消费；未适配前落 UnknownSurface 兜底（不丢）
2. **待拍板小决策**（可折进 Phase 13 grill）：逐事件 fsync vs 上游撕裂行修复模式；#77 RetrievalProvider 适配器形态 vs store 直继承；FallbackPolicy seam 签名与 ADR-0014 决策 14 字面的偏差（`should_fallback(bool)` vs `resolve(error,current)->ModelConfig`）
3. **Roadmap 下一阶段**：Phase 13 Multi-Agent（入口 `/grill-with-docs`）
