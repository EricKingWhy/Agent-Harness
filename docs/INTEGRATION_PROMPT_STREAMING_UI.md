# Streaming UI 生产级改造 集成提示词（集成 AI 执行手册）

> **收件人**：集成 AI（Git Integrator 角色，AGENTS.md §14）
> **任务**：把 `feat/backend` 的 S-UI（Streaming UI 生产级改造，ADR-0016，tickets T1-T8）合入 `main` 并完成验证
> **写于**：2026-09-06，后端 HEAD = `3a9d0b8`（本文件所在仓库 `D:\intelligence-agent-backend`，动手前以 `git log -1 --oneline` 为准）
> **红线**：永不 force-push / rebase / reset --hard；凭证零泄漏（.env 内容绝不打印/提交/复制进文档）；每次合并动作前确认所在 worktree 与分支（§14.2）；冲突后立即停止自动解决（§14.7）

---

## 0. 机器现状（已核验的事实，动手前复查）

四 worktree 布局（§13.1；**注意比上轮多了一个**）：

| 路径 | 分支 | 角色 |
| --- | --- | --- |
| `D:\intelligence-agent` | `main` | **本次集成的主战场** |
| `D:\intelligence-agent-backend` | `feat/backend` | 后端施工区（本批：6 commits `96fa393..3a9d0b8`） |
| `D:\intelligence-agent-frontend` | `feat/frontend` | 本轮不动（前端流式适配将按契约文档另行开工） |
| `D:\intelligence-agent-phase14` | `feat/phase14` | **Phase 14 并行施工区（A AI）——见下方「并行开发协调」，先读再动手** |

- S-UI 内容 = **6 commits**（`1b04445` T1+T2 → `3a9d0b8` T8）；对 merge-base 的 diff ≈ 30 文件 +2600/−90（动手前 `git diff origin/main...HEAD --stat` 复核）
- **零新 Python 依赖**：`uv.lock` / `pyproject.toml` 零变化
- **无新增必需密钥**。新增可选 env ×2（有默认值，不配 = 行为不变）：
  - `AGENT_MODELS`（JSON 数组，多模型 catalog；不配 = `GET /api/models` 只列默认链、`model` 参数一律 422）
  - `RUN_DISCONNECT_GRACE_SECONDS`（孤儿回收宽限期，默认 300 秒）
- **新增 SessionEvent 词汇 ×6（全部加法）**：`text/delta`、`reasoning/started|delta|completed|interrupted`、`tool/output_delta`（全部 durable）；`model/delta` 词汇保留 stream-only 但**运行时不再发射**；`model/started` 不变。`web/src/generated/event-types.ts` 已由 `scripts/gen_event_types.py` 重新生成（backend-owned 产物，`tests/test_event_types_generated.py` 兜底防漂移）
- 决策依据：`docs/adr/0016-streaming-ui-detached-run.md`；**前端契约回执（最终帧形状 + 迁移清单）：`docs/BACKEND_CONTRACT_STREAMING_UI.md`**——前端侧 prompt（BACKEND_PROMPT_STREAMING_UI.md）C1-C7 的逐项落定都以该文件为准，`text/delta` 替代方案是唯一与其假设不同的形状微调（原因见 §F1）
- 附带小改：`PROVIDER_PRESETS` 增 `zhipu` 条目（智谱 OpenAI 兼容端点；后端施工区 `.env` 的 fallback 已配 zhipu，此前会装配报错）；web 认证/CSP 中间件由 BaseHTTPMiddleware 重写为**纯 ASGI**（行为逐字节不变，既有 identity/auth 测试钉住——重写原因见 §F3）

### 并行开发协调（本轮最高优先级注意事项）

Phase 14（A AI，ADR-0017）在 `feat/phase14` 并行施工，双方约定 `session/event.py` **只做加法**。集成前必须先核实其状态：

```bash
git fetch origin --prune
git log origin/feat/phase14 --oneline -3     # A AI 进度
git log origin/main --oneline -3             # main 是否已吸收 phase14
```

- **§14.9 一次一支**：若 phase14 尚未合入 main → 本手册照常执行，phase14 随后另行集成（其集成 AI 须重新分析）；若 phase14 **已经**合入 main → 先回后正（B 节）时本批会撞上它的改动，按下表预判处理
- 预判冲突点（均为平凡冲突，但仍须逐文件语义复核，禁止机械 ours/theirs）：
  1. **`docs/PHASE_STATUS.md`**——两边都会加进度行 + changelog 条目：语义并集共存，一条不丢
  2. **`src/agent_harness/session/event.py`**——两边都往 `EVENT_TYPES` frozenset 加常量：解法 = **并集**（双方新增常量全部保留；本批还会带 `block_id` 字段与 `_CSP` 无关的 SessionEvent 扩展，phase14 侧不应动这些）
  3. **`web/src/generated/event-types.ts`**——生成产物**不要手工合并**：合并完 event.py 后在 feat/backend 上跑 `uv run python scripts/gen_event_types.py` 重新生成，`tests/test_event_types_generated.py` 会验证
  4. 若 phase14 也有 ADR/tickets 文档——文件名不撞（0016 vs 0017 分账已定），直接共存

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
git status --short                                 # 应为干净（本批交付时已核验）
git log --oneline origin/feat/backend -1           # 应为 3a9d0b8（或其后继）
```

任何意外残留逐文件 `git diff` 核验后再决定，拿不准停下来报告用户。

## B. 先回后正：merge origin/main 进 feat/backend（§14.6）

```bash
git fetch origin --prune
git merge origin/main
```

### C1. 冲突处理原则

- main 自本批 merge-base 后的增量取决于 phase14 是否已先行合入（见「并行开发协调」）；预期冲突面 = **PHASE_STATUS.md + session/event.py + event-types.ts** 三类，处理原则见预判表
- 超出此清单出现冲突 = 停下来逐文件分析（§14.7），报告用户后再继续

### C2. 合并后验证 Gate（§14.10，在 feat/backend 上）

```bash
uv sync --all-extras              # 本项目 gate 恒为 all-extras 口径（裸 sync 被 extras 剪枝——Phase 12 教训）
uv run pytest -q                  # 基线见下
uv run ruff check src/ tests/     # clean
git diff --check                  # 无 whitespace/冲突标记
```

**测试基线**：本批交付时 **1093 passed / 9 skipped / 20 deselected**（连续两轮复跑稳定）。若 phase14 已先行合入 main，总数会 ≥1093（其新增测试叠加）——以合并后实测为准，**不得出现失败**；有失败先定位是合并语义问题（重点怀疑 event.py 并集解、中间件栈顺序）还是 main 侧既有问题，报告后再继续。

重点回归族（本批语义修订的钉子，若红 = 合并解错了）：

```bash
uv run pytest tests/test_sse_disconnect.py tests/web/ tests/session/test_streaming_vocabulary.py tests/agent/test_reasoning_stream.py tests/tooling/test_tool_output_stream.py tests/model/ -q
```

## D. 主战场：main 侧合入与验证（`D:\intelligence-agent`）

### D1. 合入

```bash
cd D:\intelligence-agent
git branch --show-current                          # 必须是 main
git status --short                                 # 必须干净（不干净先报告用户）
git fetch origin --prune
git merge --no-ff feat/backend -m "Merge feat/backend: Streaming UI production overhaul (ADR-0016) — detached-run + cancel endpoint + reasoning/text/tool-output streaming + after_seq reconnect + model catalog"
```

### D2. main 侧 .env 增补（可选键，绝不回显其他键值）

1. **可选** `RUN_DISCONNECT_GRACE_SECONDS=300`（默认已是 300，仅显式覆盖时才写）
2. **可选** `AGENT_MODELS`（多模型 catalog，JSON 数组；main 不配 = 单默认链，`GET /api/models` 照常返回默认条目）。示例形状（**name 是 POST /api/sessions 的 model 参数选择键**；非厂商默认端点必须显式 `base_url` + `api_key`）：

```json
[{"name": "qwen3.8-27b", "provider": "qwen", "model_name": "qwen3.8-27b",
  "base_url": "https://ws-z6pxn1u9u3hqds3j.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
  "api_key": "<dashscope-key>"}]
```

3. `MODEL_*` / `FALLBACK_MODEL_*`：main 侧 Phase 12 批已同步过；后端施工区 `.env` 本次新增了 `FALLBACK_MODEL_PROVIDER=zhipu`（智谱）与 `AGENT_MODELS`（3 条目实测可用：glm-5.3-flash / qwen3.8-27b / qwen-plus，思考矩阵见契约文档）——若用户希望 main 与施工区同配，把 fallback 四键 + AGENT_MODELS 对齐（**值零回显**）；`zhipu` preset 已随本批进入代码，配置了即可用
4. 零新密钥要求：catalog 条目的 `api_key` 缺省回落 `MODEL_API_KEY`

### D3. main 侧验证 Gate

```bash
uv sync --all-extras
uv run pytest -q                 # 与 C2 同基线口径
uv run ruff check src/ tests/
```

### D4. 真实冒烟（流式场景逐项验证）

```bash
uv run uvicorn agent_harness.web.app:create_app --factory --host 127.0.0.1 --port 8000
# 另开终端：
curl http://127.0.0.1:8000/api/health
```

1. **基础回归**：`POST /api/sessions`（curl 带 `-N` 不缓冲）发「1+1等于几」→ SSE 应见 `user/message` → `model/started` → **`text/delta`（新类型，注意不再是 model/delta）** → `model/completed` → `run/completed`，每帧带 `seq`/`session_id`/`time`
2. **reasoning 真流式（D-B 验收）**：用支持思考的模型发一个需要推理的任务（如「9.11 和 9.8 哪个大？先想清楚再答」）→ SSE 应见 `reasoning/started` → `reasoning/delta`×N（同 `block_id`）→ `reasoning/completed` → `text/delta`…；**若换不吐思考的模型，reasoning 族整族不出现 = 正确（零伪造）**
3. **detached-run + 断连继续（D-A 验收）**：流式中途 Ctrl-C 杀掉 curl → `GET /api/sessions/{id}/events` 轮询：run **继续跑到 run/completed**（不是 run/failed cancelled）——这是 Phase 9 语义的有意反转
4. **重连续传**：接 3 的场景，从 events 里记下断连前的最大 seq → `GET /api/sessions/{id}/stream?after_seq=<seq>`（run 未终结时）→ 应收到缺失区间的重放帧 + 接上在途流，seq 连续无重复；run 已终结时重放至终态收尾
5. **显式取消**：新起一个长任务 → 流式中途 `POST /api/sessions/{id}/cancel` → 200 `{"status":"cancelling"}`，流以 `run/failed`（`data.reason="cancelled"`）收尾；立刻再 POST 同一端点 → 200 `{"status":"no_active_run"}`（幂等）；对不存在 session → 404
6. **模型列表**：`GET /api/models` → 默认条目 + AGENT_MODELS 条目（若配）；响应无任何密钥字段；`POST /api/sessions` 带 `"model": "<name>"` 正常跑通，带未知名 → 422
7. **孤儿回收（可选，默认 300s 太久）**：`.env` 临时设 `RUN_DISCONNECT_GRACE_SECONDS=20` 重启，起长任务 → 杀客户端 → 等 20s+ → events 终态 `run/failed` 且 `reason="orphaned"`；验证完恢复配置

注记：上游网关（senseaudio）间歇故障期内，model/failed + fallback 行为正确但双 provider 同网关无法自救（Phase 12 已知环境噪声），先探针上游再怀疑代码。

### D5. Push（最后一步，前面全绿才做）

```bash
git push origin main
```

## E. 收尾报告（main 侧）

1. `docs/PHASE_STATUS.md` 更新日志加一条集成记录（范围、冲突解法、验证数字，参照既有集成条目格式；S-UI 行已在本批写入进度表）
2. 向用户报告：完成什么 / 改了哪些 / 测试结果 / commit 区间 / 遗留项；**明确告知前端：流式适配批（§F1）现在可以开工，契约以 `docs/BACKEND_CONTRACT_STREAMING_UI.md` 为准**

## F. 集成后的已知协作点（写给用户的交接，不是本次要做的）

1. **前端流式适配批（`feat/frontend` 侧，**手册已备**：后端契约回执 `docs/BACKEND_CONTRACT_STREAMING_UI.md` §5 给了六步迁移清单）**：①live 文本流 `model/delta` → **`text/delta`**（词汇生成产物已同步，re-export 即可）——**适配前 main 上的旧前端构建会退化成「文本等 model/completed 才显示」**（临时降级，历史回放不受影响）；②Esc/停止改走 `POST /cancel`（断连借道取消已失效——这是行为反转，旧前端按 Esc 只会断流不终止）；③reasoning 按 `block_id` 聚合；④`tool/output_delta` 按 `tool_call_id` 聚合、`tool/call` 提前到达（running 态更早）；⑤seq gap → `GET /stream?after_seq` 重连；⑥`GET /api/models` 选择器。前端批应在本次集成完成后启动
2. **Phase 14 交互**：若 phase14 尚未合入，其集成 AI 合入前须重新 fetch/diff 分析（§14.9）；本批给 phase14 的礼物是 `text/delta`/`reasoning/*` durable 化——Replay 重建直接消费 durable 事实即可，无需再处理 stream-only 补偿
3. **纯 ASGI 中间件**（AuthSeamMiddleware / CSPHeaderMiddleware）：行为契约与旧 BaseHTTPMiddleware 版逐字节一致；重写动机 = SSE 流过 BaseHTTPMiddleware 时断连取消会经 anyio 任务组传染相邻请求（全量回归 500 风暴实证）。改回 BaseHTTPMiddleware 等于 reintroduce 该缺陷，勿动
4. **已知边界（诚实声明）**：Docker sandbox 的 `on_output` 接受但忽略（exec_run 无逐段读取窗口）；重放快照层 DEFER（backlog>1000 走 `stream/truncated` 控制帧 + `GET /events` 全量重建替代）；崩溃遗留悬空 run 重连时重放完即收流不伪造终态（修复走 `POST /recover`）
