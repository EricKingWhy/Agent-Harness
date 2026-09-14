# Phase 5 交接手册 — Artifact + Context Compaction

> **交接对象**：Codex（Secondary / Task Agent）
> **交接时间**：2026-09-04
> **交接人**：ZCode（本会话）
> **当前进度**：#45–#50 全部完成，真实七牛 Gate 通过（Codex 2026-09-04 更新，证据见 `docs/PHASE5_GATE.md`）

---

## 1. 背景与决策来源

Phase 5 的全部决策已通过 `/grill-with-docs` 四轮拷打冻结，文档产出在：

| 文档 | 内容 |
|------|------|
| `CONTEXT.md` | Phase 5 新增 12 条术语（Artifact / ArtifactStore / Overflow / inspect_artifact / ContextBuilder / estimate_tokens / Compaction / 三层降级 / ContextProvider / artifact/created / context/compacted） |
| `docs/adr/0006-artifact-store-qiniu-s3-compatible.md` | 对象存储用七牛云 Kodo S3 兼容（aioboto3），不做 Local/MinIO |
| `docs/adr/0007-context-compaction-three-tier-fallback.md` | Compaction 三层降级（LLM→机械→拒绝）+ tiktoken cl100k_base 精确计数 + max_context_tokens=200000 |
| GitHub Issue #44 | Phase 5 Spec（完整 user stories + implementation decisions + acceptance criteria） |

**Codex 必读**：开始任何 ticket 前先读 #44 + 两个 ADR + CONTEXT.md 的「Artifact / Context 层」段落。

---

## 2. Ticket 状态

| # | GitHub | 标题 | 状态 | Blocked by |
|---|--------|------|------|------------|
| 1 | #45 | ArtifactStore ABC + FakeArtifactStore + inspect_artifact Tool | ✅ DONE (fd7439a) | — |
| 2 | #46 | estimate_tokens + ContextBuilder base (no Compaction) | ✅ DONE (c98c9a5) | — |
| 3 | #47 | Overflow Handler + Executor 集成 + artifact/created | ✅ DONE (de6a894) | #45 ✅ |
| 4 | #48 | S3ArtifactStore (七牛云 S3 兼容) | ✅ DONE (80086a9) | #45 ✅ |
| 5 | #49 | Context Compactor 三层降级 + context/compacted | ✅ DONE (e19905d) | #46 ✅ |
| 6 | #50 | AgentRuntime 集成 + Phase 5 端到端测试 | ✅ DONE (c0a4b0f) | #47, #48, #49 ✅ |

**Phase 5 已完成**：真实七牛 Gate 2 passed，全量回归 424 passed。证据见 `docs/PHASE5_GATE.md`。

**剩余任务**：本 Phase 无；main 最终集成和后续 Phase 按用户/Primary Developer 排期。

**Context 接口说明**：`ContextBuilder.build` 和 `ContextProvider.select` 为 async，调用时使用 `await`；token 估算计入消息结构（含 tool_calls）。#49 已接入阈值执行；压缩成功追加 `context/compacted`，硬限制失败抛异常。

---

## 3. #45 已交付内容（供后续 ticket 参考）

### 新建文件

- `src/agent_harness/storage/artifact.py`
  - `Artifact(BaseModel)`: artifact_id / session_id / size / mime_type / source_tool / tool_call_id / created_at / content(可选)
  - `ArtifactSlice(BaseModel)`: artifact_id / lines / total_lines / returned_lines / truncated / query
  - `ArtifactStore(ABC)`: `save()` / `load()` / `inspect()` 三个 async 抽象方法
  - `compute_artifact_id(content) -> str`: SHA-256 前 16 字符
  - `_slice_lines(...)`: 通用切片函数（按行范围或关键词），FakeArtifactStore 和 S3ArtifactStore 共享
  - `FakeArtifactStore(ArtifactStore)`: 内存 dict 实现

- `src/agent_harness/tools/inspect_artifact.py`
  - `InspectArtifactTool(Tool)`: 构造注入 `ArtifactStore`（不是 `Sandbox`）
  - `name="inspect_artifact"` / `side_effect=READ_ONLY` / `permission=READ_ONLY`
  - `reconcile_hint` 返回 `verifiable=True`
  - args: artifact_id(必填) / start_line / end_line / keyword / max_lines=200

- `tests/storage/test_artifact_store.py`: 14 个测试
- `tests/tools/test_inspect_artifact_tool.py`: 9 个测试

### 注意事项

- `inspect_artifact` 尚未注册到 `tools/__init__.py` 的 `__all__`——后续 ticket 集成时再加（Phase 5 不需要自动注册，Runtime 手动构造注入）。
- `_slice_lines` 是共享工具函数，#48 S3ArtifactStore 的 `inspect()` 直接复用它做切片，不要重复实现。

---

## 4. 各 Ticket 实施要点

### #46: estimate_tokens + ContextBuilder base

**核心交付**：
- `src/agent_harness/context/__init__.py` + `src/agent_harness/context/tokens.py`:
  `estimate_tokens(text: str) -> int` 用 `tiktoken.get_encoding("cl100k_base")`
- `src/agent_harness/context/builder.py`:
  `ContextBuilder` 类，`build(session: Session) -> list[AnyMessage]`
  - 构造参数：`model_provider` / `max_context_tokens=200_000` / `auto_compact_threshold=0.70` / `hard_guard_threshold=0.85` / `context_providers: list[ContextProvider] | None = None`
  - 内部调 `session.derive_messages()` 直接返回（不做 compaction，那是 #49 的活）
- `src/agent_harness/context/provider.py`:
  `ContextProvider(Protocol)` 定义 `select(session, token_budget) -> list[AnyMessage]`，不实现
- `config.py` Settings 增加：`max_context_tokens` / `auto_compact_threshold` / `hard_guard_threshold`
- `pyproject.toml` dependencies 加 `tiktoken>=0.7.0`

**测试 seam**：单元测试 `tests/context/test_tokens.py` + `tests/context/test_builder.py`
**注意**：`tiktoken` 第一次 import 会下载编码文件——确保测试环境能联网或缓存了编码。

### #47: Overflow Handler + Executor 集成

**已完成的接线约定（供 #50 使用）**：
- `ToolExecutor(..., overflow_handler=ArtifactOverflowHandler(store))`；`execute()` / `execute_batch()` 需要显式传 `session=session`。没有 handler 的原调用兼容；缺 Session 或与 OperationContext 不匹配时在副作用前拒绝。
- Runtime 的 Session 传递、事件流镜像和默认构造仍由 #50 集成，本 ticket 不修改 AgentRuntime。
- 兼容现有 BashTool 的 `stdout/stderr`。单个大字段存原文；多个大字段存可完整还原的 JSON 对象，共用一个 ref，各字段返回摘要。短字段、exit_code、错误语义与 metadata 保留。
- 默认阈值 2000 字符，摘要首尾各最多 10 行并限制字符数。阈值小于固定引用提示长度时仍保留提示，摘要可能超过这个极小阈值。
- 上传或事件持久化失败直接传播，不能进入 Tool retry；已有 Ledger 保留 RUNNING 供恢复对账，不伪造 artifact_ref。
- 复用决策：REUSE 已有 ArtifactStore / ToolResult / Ledger，BUILD 本项目后处理接线；参考 DeepSeek Harness 的 post-execute spill 设计（MIT，`docs/subsystems/spill.md`，master）。未移植代码；本项目存储失败中断，与上游保留内联大输出的 best-effort 策略不同。

**核心交付**：
- `src/agent_harness/tooling/overflow.py`:
  - `OverflowHandler(ABC)`: `async maybe_overflow(session, tool_call_id, tool_name, result) -> ToolResult`
  - `ArtifactOverflowHandler(OverflowHandler)`: 构造注入 `ArtifactStore` + `overflow_chars` 阈值
  - 溢出逻辑：提取 ToolResult 主输出字段（`data.get("output")` 或 `data.get("content")` 或 `message`），字符数超阈值 → `store.save()` → 截断替换 → `result.artifact_ref = artifact_id`
  - 截断格式：前 N 行 + `"... [truncated, {total} lines total, use inspect_artifact({artifact_id}) to view]"` + 后 N 行
- `src/agent_harness/tooling/executor.py`:
  - 构造函数增加 `overflow_handler: OverflowHandler | None = None`
  - 在 `tool.execute()` 成功返回后、`Ledger.update_state()` 之前调 `overflow_handler.maybe_overflow()`
- `src/agent_harness/session/event.py`:
  - EVENT_TYPES 增加 `ARTIFACT_CREATED = "artifact/created"`
  - data 格式：`{artifact_id, session_id, source_tool, tool_call_id, size, mime_type}`

**插入点精确位置**（读 `executor.py` 的 `execute` 方法）：
```
现有流程：
  1. 校验 → 2. 权限 → 3. Ledger PENDING → 4. Ledger RUNNING → 5. tool.execute → 6. Ledger SUCCEEDED → 7. return

加溢出后：
  5. tool.execute → 5.5. overflow_handler.maybe_overflow() → 6. Ledger SUCCEEDED → 7. return
```

**测试**：用 `FakeArtifactStore`（#45 已有），验证未超阈值原样返回 / 超阈值截断 + artifact_ref / artifact/created 事件被 append。

### #48: S3ArtifactStore (七牛云)

**已完成的接线约定（供 #50 使用）**：
- 构造：`S3ArtifactStore(settings, session_id=session.session_id)`。每个 Session 单独构造；恢复时传相同 ID。`load(id)` / `inspect(id)` 由构造绑定的 Session 得到 `{session_id}/{artifact_id}`，没有内存索引或 bucket 扫描。
- `save()` 的 Session ID 必须与实例绑定值一致。Fake/S3 共用契约测试覆盖同一 Session 内的行为；Fake 原有的跨 Session 去重测试不代表生产 Provider 可以跨 Session 共享实例。Fork 跨 Session 引用策略留 Phase 14。
- 正文用 UTF-8，元数据以 ASCII JSON 放在同次 `put_object` 的 S3 Metadata 中；不会出现正文和元数据分两次写入的窗口。
- `NoSuchKey` 转为契约的 `KeyError`，权限/上传/其他 SDK 错误直接传播。client 与 response body 通过 async context manager 关闭。
- 安装：`uv sync --inexact --extra artifact`。默认测试排除 `qiniu`；显式验证：`uv run --extra artifact python -X utf8 -m pytest tests/integration/test_qiniu_artifact.py -m qiniu -q`。测试使用随机专属 key，结束清理这个 key。真实七牛尚未验证。
- Settings 的五个 `artifact_store_*` 字段都须配置；bucket 应填七牛的 **S3 空间名**，region/endpoint 取空间所在区域。参考 [七牛服务域名](https://developer.qiniu.com/kodo/4088/s3-access-domainname)。
- REUSE + ADAPT aioboto3（Apache-2.0；[官方用法](https://aioboto3.readthedocs.io/en/latest/usage.html)），锁定版本 15.5.0；未移植 SDK 代码。Core 不直接依赖具体客户端。

**核心交付**：
- `src/agent_harness/storage/s3_artifact.py`:
  `S3ArtifactStore(ArtifactStore)`，用 `aioboto3` 的 async S3 client
  - `save()`: `put_object` 到 bucket，key = `{session_id}/{artifact_id}`
  - `load()`: `get_object` 读回完整内容
  - `inspect()`: `get_object` 读回后调 `_slice_lines()` 切片（复用 #45 的共享函数）
- `config.py` Settings 增加：`artifact_store_endpoint` / `artifact_store_bucket` / `artifact_store_access_key` / `artifact_store_secret_key` / `artifact_store_region`
- `pyproject.toml` optional-dependencies 加 `[project.optional-dependencies] artifact = ["aioboto3>=13.0"]`
- 测试：mock aioboto3 client 验证调用参数；集成测试标 `@pytest.mark.qiniu` 默认 skip

**七牛云 S3 兼容端点配置**（用户提供，到 #50 才需要）：
- endpoint、bucket、access_key、secret_key 从 `.env` 读
- `aioboto3` 的 `Session().client("s3", endpoint_url=..., ...)` 对接

**注意**：`_slice_lines` 已在 `storage/artifact.py` 中定义，直接 import 复用。

### #49: Context Compactor 三层降级

**已完成的接线约定（供 #50 使用）**：
- `await ContextBuilder(model_provider, ...).build(session)` 返回安全投影；从 `context.builder` 可导入 `ContextWindowExceededError`。Runtime 必须捕获它并结束当前 run；不得继续发模型请求。
- 保留前置 SystemMessage 和当前用户 turn，压缩此前完整 turns。进入压缩前验证每个 AIMessage + 连续 ToolMessage 原子块，缺失、重复、孤立结果均拒绝。没有早期完整 turn 时：预算未超 hard 则原样返回、不造事件；超过 hard 则拒绝。
- LLM 输出为八字段 JSON，各字段是字符串列表。摘要总投影须低于 auto；格式错、请求预算超 hard、超时（默认 30 秒）、模型失败或摘要未达到 auto 目标时机械降级。机械降级后允许 auto～hard 的安全区间；超过 hard 抛异常。外部取消继续传播。
- `estimate_message_tokens` 统一估算模型消息结构，摘要请求本身也受 hard guard 约束。ContextProvider 保持空扩展点，未接 Memory。
- 每次从完整 SessionEvent 独立计算，无摘要缓存。`context/compacted` 记录四项指标，不保存摘要正文；原有历史事件不删除。#50 需镜像新事件到流式输出。
- PORT DESIGN 参考 [Pi compaction](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/compaction.md)（MIT），REUSE 现有 tokenizer / ModelProvider / Session 投影。未移植上游代码，未采用其 split-turn 或增量摘要缓存。

**核心交付**：
- `src/agent_harness/context/compactor.py`:
  `ContextCompactor` 类，三层降级逻辑
  - 第一层：LLM 摘要——取早期 turns 送 `ModelProvider.ainvoke()`，prompt 要求结构化 summary（facts/decisions/constraints/failed_attempts/unresolved/artifact_refs/citations/tool outcomes），产出 `SystemMessage` 注入头部
  - 第二层：deterministic 机械提取——HumanMessage 截断 / AIMessage 只留 tool_calls / ToolMessage 只留 tool_call_id + 截断 content
  - 第三层：两层降级后 token 仍超 `hard_guard_threshold` → 抛 `ContextWindowExceededError`
  - AIMessage(tool_calls) + 紧跟 ToolMessage 块为不可分割原子单元
- `src/agent_harness/context/builder.py`:
  `ContextBuilder.build()` 集成 compaction（检测 token → 调 compactor → 返回安全 messages）
- `src/agent_harness/session/event.py`:
  EVENT_TYPES 增加 `CONTEXT_COMPACTED = "context/compacted"`
  data: `{compacted_turn_count, summary_message_count, token_estimate, fallback_used: bool}`

**依赖**：#46（estimate_tokens + ContextBuilder base）

### #50: AgentRuntime 集成 + 端到端测试

**已完成**：Runtime 默认/注入 ContextBuilder；hard guard 返回 `context_window_exceeded` 并持久化 `run/failed`；Executor 收到 Session；新增事实镜像到实时流。Web 按 Settings 装配 Context/S3/inspect/overflow。串行及并行部分失败先发送已提交事件，再传播异常。真实七牛 Gate 已运行通过，凭证保存在本地 Git 忽略的 `.env`。

**核心交付**：
- `src/agent_harness/agent/runtime.py`:
  - 构造函数增加 `context_builder: ContextBuilder`
  - loop 第 1 步从 `session.derive_messages()` 改为 `context_builder.build(session)`
- 端到端测试（**用真实七牛云 S3ArtifactStore**，不用 Fake）
- Phase 5 Gate 达成证据

**七牛云配置**：用户已提供并写入本地 `.env`，不在文档复述；其他环境按 `.env.example` 配置。

**注意**：现有 345+23=368 个测试不能回归。Runtime 改第 1 步后所有用 `session.derive_messages()` 的测试仍通过——因为 ContextBuilder.build() 内部调 derive_messages。

---

## 5. 测试命令

```bash
# 全量测试
cd D:/intelligence-agent-backend
.venv/Scripts/python.exe -X utf8 -m pytest tests/ -q --tb=no

# 只跑 Phase 5 相关
.venv/Scripts/python.exe -m pytest tests/storage/test_artifact_store.py tests/tools/test_inspect_artifact_tool.py tests/context/ tests/tooling/test_overflow*.py -q

# ruff
.venv/Scripts/python.exe -m ruff check .
```

**当前基线（#50 后，安装 artifact extra）**：424 passed, 8 skipped, 5 deselected, ruff All checks passed；真实七牛单独运行 2 passed。Windows 使用上面的 `-X utf8`，避免既有 mapping JSON 测试用默认编码读取中文路径导致失败。

---

## 6. 必须守的约束

1. **Scope Lock**（AGENTS.md §8）：不顺手重构、不提前做未来 Phase、不扩大架构
2. **Reuse First**（AGENTS.md §6）：`_slice_lines` 已在 artifact.py，S3ArtifactStore 直接复用
3. **21 条架构不变量**（AGENTS.md §7）：特别关注 #6（完整保存 ≠ 完整注入）、#4（Event ≠ Log）
4. **七牛云凭证不在代码里硬编码**——走 Settings / .env
5. **每完成一个 ticket**：commit + push + close issue + 更新 `docs/PHASE_STATUS.md`
6. **Phase 5 与 Phase 6 边界**：Phase 5 不做 Memory（MemoryCapability / LangMemProvider），ContextProvider Protocol 只定义不实现
7. **Python venv**：`D:/intelligence-agent-backend/.venv/Scripts/python.exe`
8. **worktree**：只在 `D:/intelligence-agent-backend`（feat/backend）操作，不碰 frontend

---

## 7. Phase 5 Gate（spec 06 §9）

实施完 #50 后验证：
- [x] 大 Tool Output 完整保存（Artifact）
- [x] Model 默认只收到 summary + ref（截断摘要 + artifact_ref）
- [x] `inspect_artifact` 能找回细节
- [x] 七牛云 Provider 可替换 Fake Provider
- [x] Compaction 后历史不删除（原有 SessionEvent 不变）
- [x] 替换成 Fake Provider 时 Agent Core 无需修改（契约隔离）
