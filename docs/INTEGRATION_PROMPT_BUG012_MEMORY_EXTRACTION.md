# 集成提示词：记忆写入装配 + BUG-012 抽取降级修复 + Milvus 正式集合

> 面向集成 AI。分支 `feat/backend`（worktree `D:\intelligence-agent-backend`）。
> 两个本地 commit：`ee2977e`（BUG-012 主体）、`e675480`（两轴 review 收口）。
> **均未 push**（§16.4）。无 GitHub issue（现场发现，同 OBS-* 先例）。

---

## §0 机器可执行摘要

| 项 | 值 |
| --- | --- |
| 分支 / worktree | `feat/backend` / `D:\intelligence-agent-backend` |
| commit | `ee2977e`、`e675480` |
| 改动文件 | `src/agent_harness/memory/extractor.py`、`src/agent_harness/memory/writeback.py`、`tests/memory/test_extractor.py`、`tests/memory/test_writeback.py`（**仅 4 个**） |
| 门禁 | `uv run ruff check .` clean；`uv run pytest -q` → **1611 passed / 10 skipped / 39 deselected / 0 failed** |
| 需要集成方手工做的 | ⚠️ 见 §4：`.env` 三处改动是**本地文件**（§13.1.6 不同步），必须由集成方在自己的 `.env` 手工复现 |
| 是否可自动合并 | 是。改动集与 `docs/**` 不相交，与前端零重叠 |
| 未决 / 风险 | §6：跨进程文件锁（独立议题）、Phase 6 gate 测试因改名而跳过（需 env 覆盖） |

---

## §1 这批做了什么（三件事）

### 1.1 记忆写入装配（`.env`，本地）

用真实 Langfuse 旁路 key 打开可观测，并把 memory capability 装配起来：

- Langfuse 块：`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_BASE_URL`（**值不在此文档**）。
- `CAPABILITIES` 增加 `"memory": {"provider": "builtin", "enabled": true}`。
- `LANGFUSE_TRACE_CONTENT` **按用户明确要求未改**（保持默认 `full`）；`.env` 里只留了一行注释说明可切 `redacted`。

### 1.2 BUG-012：抽取降级不再静默（`ee2977e`）

**现象（真机验收发现）**：记忆抽取的 LLM 路径失败时**静默**退回正则启发式，事件流里零痕迹——一次"记忆质量降到关键词水平"的运行，从 JSONL 上完全看不出来。

**修法**：① 新增 `ExtractionOutcome`（`candidates` + `degraded_reason`）替代裸 list 返回，降级原因随候选一起传出来；② LLM 失败时产出 `heuristic_fallback: <detail>`，规则路径自己也失败时产出 `heuristic_unavailable: <类型名>`（**空结果，不伪造候选**）；③ `writeback` 侧落一条 `memory/degraded` durable 事件（`operation="extraction"`）。

**证据（真机，真实模型）**：修复前 5/5 次回退都无痕；修复后同样 5 次调用 **0/5 回退**且事件流可见降级。

### 1.3 两轴 review 收口（`e675480`）

Standards + Spec 两个独立子代理各报 finding，本 scope 内 3 项已修：

| # | 轴 | 缺陷 | 修法 |
| --- | --- | --- | --- |
| 1 | P1 Standards | `_repair_json` 全局替换**静默篡改字符串内容**：`"content":"use [1, 2, ] then stop"` 的 `,]` 被当尾逗号删掉、`don’t` 被改成 `don't`，而重校验照样通过 → 改坏的数据被当成功候选存下去 | 改为**字符串感知扫描**：引号族只在字符串外当分隔符、尾逗号只在字符串外删、字符串内容逐字保留、转义对整体保留 |
| 2 | P2 Spec | `heuristic_unavailable` **归因错阶段**：规则路径自己抛异常，reason 里写的却是 LLM 阶段的异常类型名（把"正则抽不出来"说成"模型输出有问题"） | 归因改为规则路径自身的异常类型 |
| 3 | P2 Standards+Spec | 降级事件缺 `run_id` 归因；且 `append` 与候选存储循环同在一个 `try` 内 → **观测写盘失败会整段跳过候选存储** | 补 `run_id`；把 `append` 包进自己的 `try/except`——**降级只在质量，不在可用性** |

等价地：修复 3 实现了一条明确契约 —— **宁可回退，不可静默篡改**。

---

## §2 验收证据

### 2.1 变异验证（三组，全部隔离复跑并还原）

| 变异 | 期望 | 实测 |
| --- | --- | --- |
| 忠实回退到 `ee2977e` 的旧 `_repair_json`（`translate` 引号族 + 全局尾逗号正则） | 2 例字符串篡改 killer 用例变红 | **2 failed**（`test_string_content_that_looks_like_json_is_never_rewritten`、`test_curly_apostrophe_inside_content_survives_repair`） |
| 删掉降级事件的 `run_id=` 参数 | 归因用例变红 | **1 failed**（`test_degraded_event_carries_run_id_for_attribution`） |
| 拆掉观测写失败的内层 `except` | 候选保全用例变红 | **1 failed**（`test_observability_write_failure_does_not_drop_candidates`） |

> 第一次做的变异 C 只替换了全角双引号、漏了撇号，只红了 1 例；改为**逐字复刻旧实现**后才 2 例全红。记录在此以免后人把"只红一例"当成测试强度不够。

### 2.2 Milvus 正式集合验收（真机，Zilliz Cloud）

`MILVUS_COLLECTION` 由测试名 `memory_gate_test` 改为正式名 **`agent_memory`**。

- **集合存在且 schema 正确**：9 字段（`id`/`memory_id`/`tenant_id`/`user_id`/`scope`/`session_id`/`content`/`metadata`/`vector`）、`vector.dim = 1024`、`tenant_id.is_partition_key = True`。
- **端到端往返（真 embedding）**：`upsert` → `search`（命中，score **0.7957**）→ `delete` → 真实 count 回到 **0**。
- **遗留归零**：`agent_memory` / `memory_gate_test` / `knowledge_gate_test` 真实行数**全为 0**；本地 `.agent/workspace/memory.db` 的 `memory_records` / `memory_outbox` 也是 0 行。

> ⚠️ 计数必须用 `query(filter="", output_fields=["count(*)"])`（不要带 `limit`，会报 `count entities with pagination is not allowed`）。`get_collection_stats` 的 `row_count` 是**惰性陈旧值**——本次它对已清空的 `memory_gate_test` 仍报 `4`，真实值是 `0`。

---

## §3 记忆提取的触发语义（回答"什么时候触发"）

**只在 run 的终态触发，没有定时器**。`_write_memories(session, memory_event_start)` 全仓只有 3 个调用点：

| 行 | 触发条件 |
| --- | --- |
| `src/agent_harness/agent/runtime.py:800` | 正常完成 |
| `src/agent_harness/agent/runtime.py:822` | 达到 `max_steps` |
| `src/agent_harness/agent/runtime.py:976` | 工具连续失败硬停 |

抽取窗口 = 该次 run 的事件切片（`memory_event_start = session.mark()`，`runtime.py:522`），窗口内排除 `reasoning/*`、`text/delta`、`tool/output_delta`。

**已知缺口（本次未改，属独立议题）**：`_RunFinalizer`（异常 / 取消路径）**没有** memory hook——run 因异常或用户取消结束时**不提取**记忆。

**向量索引是另一条时间线**：`OutboxRelay` 默认 **5s 轮询**（`outbox_relay.py:26`）把 outbox 里的记录推给 Milvus。所以"记忆已形成"与"已可被语义检索"之间有一个轮询间隔。

---

## §4 ⚠️ 集成方必须手工做的事（`.env` 不同步）

`.env` 是 gitignored 的本地文件（§13.1.6），**不在 commit 里**。集成方需在自己 worktree 的 `.env` 复现：

1. 补 Langfuse 三个 key（值向用户索取，**不要**从本仓库或本文档抄）。
2. `CAPABILITIES` 里加 `"memory": {"provider": "builtin", "enabled": true}`。
3. `MILVUS_COLLECTION=agent_memory`（从 `memory_gate_test` 改名）。

不改这三项时：BUG-012 的代码修复**依然生效**（有单测覆盖），只是生产运行不会装配 memory capability / 不会上报 Langfuse。

---

## §5 副作用与交叉影响

- **`tests/integration/test_phase6_memory_e2e.py` 会跳过**：它 `pytest.skip` 除非 `settings.milvus_collection == "memory_gate_test"`。改名后要跑 Phase 6 gate，需用 env 覆盖：`MILVUS_COLLECTION=memory_gate_test uv run pytest tests/integration/test_phase6_memory_e2e.py`。**本次未改该测试**（§8 Scope Lock），若希望它跟随正式名，属独立小票。
- **空集合 `memory_gate_test` / `knowledge_gate_test` 仍留在集群里**：二者是 Phase 6 / Phase 11 的 gate 专用集合（`docs/PHASE6_GATE.md`、`docs/PHASE11_GATE.md`），**不是残留垃圾，未 drop**。`knowledge_gate_test` 仍是 `KNOWLEDGE_COLLECTION` 的当前值，正在使用中。
- **`provider` 配置目前是装饰性的**：`build_memory_components()` 不按 `cfg.provider` 分派，`"builtin"` 与 `"langmem"` 都会构造 `LangMemMemoryCapability`（`factories.py:42-90`）。`CapabilityDescriptor.provider_name` 会如实写配置值——**所以描述符会声称一个并未生效的 provider**。这是"可插拔"的真实缺口，已列入设计讨论（见 §7）。

---

## §6 未决 / 风险

1. **跨进程并发写仍无文件锁**（BUG-011 遗留，本次未动）：同一 session root 被多进程共享时，JSONL 只有进程内 `threading.Lock`。属独立设计议题，需与"项目 → 多会话"模型一起决策。
2. **旧损坏会话不自愈**：本次只防再犯。
3. **run 异常/取消不提取记忆**（§3）。
4. **`get_collection_stats` 不可用于对账**（§2.2）。

---

## §7 设计讨论（已产出建议，待用户拍板）

见本批对话结论 + `docs/RESEARCH_STREAM_STALL_HANDLING.md` 同源的上游调研：
**可插拔记忆** = 把 `build_memory_components` 按 `cfg.provider` 分派（子注册表），这是最小改动即可让 `provider` 配置名副其实；
**项目 → 多会话** 参考 DeepSeek Harness 的 Workspace 实体 + 有序 `sessionIds` 账本模型；
**workspace 独占锁**：Pi 用 `proper-lockfile`（仅 server/worker 模式）+ `flag:"wx"`；DSH 用单写者 `SessionHandle` + 跨进程文件租约（第二次 `open(id,'write')` → `SessionAlreadyOwnedError`）。是否引入取决于是否会真的多进程共享同一 workspace（当前 ZCode 观察到的形态是 SQLite WAL + 每会话独立文件）。

---

## §8 合并顺序建议

1. 先合本批（后端 `feat/backend` @`e675480`）→ 验证 `pytest` 全绿。
2. 再处理前端（§14.9：后端合入后重新 `fetch` / `diff` / `merge-base`，之前的前端冲突判断全部视为过期）。
3. 合完再手工复现 §4 的 `.env` 三项，跑一次真机会话确认 `memory/degraded` 不再静默。
