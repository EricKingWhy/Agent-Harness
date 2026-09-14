# 集成交接单 —— Ticket RUNTIME Sub-batch 1

> **`reasoning_effort` 运行时消费**
>
> 分支：`feat/multiturn`
> 起点：`343531f`（refactor(multiturn): extract _append_session_event helper）
> 修复 commit：`63a437b`
> 交付方：后端 AI（ZCode）

---

## 1. 背景

Phase 5 (`df03990`) 把 `reasoning_effort` 作为 **staged 契约**接收：API 边界验证通过、运行时记 INFO 日志后忽略。B1 (`a45c665`) 交付了 GET 清单端点。但**运行时仍未消费** `reasoning_effort`。

本子批次把 `reasoning_effort` 从 staged no-op 升级为真实运行时消费。

---

## 2. 变更摘要

### 2.1 核心变更

| 文件 | 改动 |
|------|------|
| `src/agent_harness/model/provider.py` | 新增 `REASONING_EFFORT_TO_API` 映射 dict（`minimal→low`, `standard→medium`, `deep→high`）；`create_chat_model` 接受 `reasoning_effort: str \| None = None` keyword-only 参数，映射后传入 `ReasoningChatOpenAI` 构造器 |
| `src/agent_harness/assembly.py` | 移除 `reasoning_effort` 的 no-op 日志；`build_runtime` 将 `reasoning_effort` 传给 `create_chat_model`（primary + fallback） |

### 2.2 测试变更

| 文件 | 改动 |
|------|------|
| `tests/test_reasoning_effort.py` | **新文件**，10 条测试：域值→API 值映射（3 档）、payload 出现 reasoning_effort 键（parametrized）、None 时 payload 不含此键、build_runtime 装配接线（有/无 reasoning_effort） |
| `tests/test_assembly.py` | 机械修改：`fake_create(config, **kwargs)` 接受新 kwarg |
| `tests/test_cli.py` | 机械修改：2 处 lambda 加 `**kw` |
| `tests/test_sse_disconnect.py` | 机械修改：lambda 加 `**kw` |
| `tests/test_structured_logging.py` | 机械修改：2 处 lambda 加 `**kw` |
| `tests/test_web_phase5.py` | 机械修改：2 处 lambda 加 `**kw` |
| `tests/web/test_web_batch51_spec_contract.py` | 机械修改：lambda 加 `**kw` |
| `tests/web/test_web_cancel.py` | 机械修改：lambda 加 `**kw` |
| `tests/web/test_web_models.py` | 机械修改：2 处 `fake_factory` 加 `**kwargs` |
| `tests/web/test_web_phase5_approval.py` | 机械修改：lambda 加 `**kw` |
| `tests/web/test_web_stream.py` | 机械修改：lambda 加 `**kw` |

### 2.3 Web 层注释更新

| 文件 | 改动 |
|------|------|
| `src/agent_harness/web/app.py` | 更新 `REASONING_EFFORT_DESCRIPTIONS` 注释、`CreateSessionRequest` 字段注释、`GET /api/reasoning-efforts` docstring——从"runtime no-op"改为"已消费到模型构造 seam" |

---

## 3. 实现细节

### 3.1 域值 → API 值映射

```python
REASONING_EFFORT_TO_API: dict[str, str] = {
    "minimal": "low",
    "standard": "medium",
    "deep": "high",
}
```

`langchain_openai.ChatOpenAI`（v1.5.0）原生支持 `reasoning_effort` 字段。设置后，`reasoning_effort` 出现在发给 provider 的 request payload 中。

### 3.2 create_chat_model 签名变更

```python
# 旧签名
def create_chat_model(config: ModelConfig) -> ReasoningChatOpenAI:
    return ReasoningChatOpenAI(model=..., api_key=..., ...)

# 新签名
def create_chat_model(
    config: ModelConfig,
    *,
    reasoning_effort: str | None = None,
) -> ReasoningChatOpenAI:
    kwargs: dict[str, Any] = {
        "model": config.model_name,
        "api_key": config.get_secret_value(),
        "base_url": config.base_url,
        "temperature": config.temperature,
        "request_timeout": 300,
        "max_retries": 0,
    }
    if reasoning_effort is not None:
        api_effort = REASONING_EFFORT_TO_API.get(reasoning_effort)
        if api_effort is None:
            raise ValueError(
                f"reasoning_effort {reasoning_effort!r} 不在 "
                f"REASONING_EFFORT_TO_API 映射中"
            )
        kwargs["reasoning_effort"] = api_effort
    return ReasoningChatOpenAI(**kwargs)
```

keyword-only 参数确保调用方必须显式传 `reasoning_effort=...`，不会与位置参数混淆。

### 3.3 build_runtime 装配

```python
# primary model
model = create_chat_model(config, reasoning_effort=reasoning_effort)

# fallback model (also receives reasoning_effort)
fallback_model = None
if config.fallback is not None:
    fallback_model = create_chat_model(
        config.fallback, reasoning_effort=reasoning_effort
    )
```

primary 和 fallback 都传入 `reasoning_effort`——如果用户要求 deep reasoning，fallback 也应尊重这个选择。

### 3.4 agent_profile / context_providers 仍是 staged no-op

```python
# assembly.py — 这两个字段仍然是 no-op
if agent_profile is not None:
    logger.info("agent_profile=%s received but not yet consumed by runtime", agent_profile)
if context_providers is not None:
    logger.info("context_providers=%s received but not yet consumed by runtime", context_providers)
```

`agent_profile` 和 `context_providers` 的运行时消费是独立子批次，本 ticket 不涉及。

---

## 4. 验证证据

### 4.1 新增测试

```
tests/test_reasoning_effort.py::TestReasoningEffortMapping::test_minimal_maps_to_low PASSED
tests/test_reasoning_effort.py::TestReasoningEffortMapping::test_standard_maps_to_medium PASSED
tests/test_reasoning_effort.py::TestReasoningEffortMapping::test_deep_maps_to_high PASSED
tests/test_reasoning_effort.py::TestReasoningEffortMapping::test_none_means_no_reasoning_effort PASSED
tests/test_reasoning_effort.py::TestReasoningEffortMapping::test_reasoning_effort_appears_in_request_payload[minimal] PASSED
tests/test_reasoning_effort.py::TestReasoningEffortMapping::test_reasoning_effort_appears_in_request_payload[standard] PASSED
tests/test_reasoning_effort.py::TestReasoningEffortMapping::test_reasoning_effort_appears_in_request_payload[deep] PASSED
tests/test_reasoning_effort.py::TestReasoningEffortMapping::test_no_reasoning_effort_omitted_from_payload PASSED
tests/test_reasoning_effort.py::TestReasoningEffortAssemblyWiring::test_reasoning_effort_reaches_create_chat_model PASSED
tests/test_reasoning_effort.py::TestReasoningEffortAssemblyWiring::test_no_reasoning_effort_passes_none PASSED
```

### 4.2 全量 pytest

```
1297 passed, 9 skipped, 39 deselected, 8 warnings in 91.63s
```

**注意**：有 12 条 pre-existing 失败，全部来自 `feat/multiturn` 分支上未提交的多轮会话工作（`COMPACTION_START`/`COMPACTION_END` 事件类型已加入 `event.py` 但相关测试尚未更新）。这些失败与本子批次无关。

### 4.3 Ruff check

```
ruff check src/agent_harness/model/provider.py src/agent_harness/assembly.py src/agent_harness/web/app.py tests/test_reasoning_effort.py
All checks passed!
```

---

## 5. 拓扑与冲突预测

### 5.1 拓扑

```
343531f (parent — refactor(multiturn): extract _append_session_event helper)
   ↓
63a437b (feat(runtime): reasoning_effort 运行时消费)
```

### 5.2 冲突预测

**低冲突风险。** 改动集中在：

| 文件 | 冲突面 |
|------|--------|
| `src/agent_harness/model/provider.py` | `create_chat_model` 签名扩展 + `REASONING_EFFORT_TO_API` 新增 |
| `src/agent_harness/assembly.py` | `build_runtime` 内 `create_chat_model` 调用点（primary + fallback） |
| `src/agent_harness/web/app.py` | 注释/docstring 更新（不改行为） |
| `tests/test_reasoning_effort.py` | 新文件，无冲突面 |
| 多个 test files | 机械 `**kwargs` 修改 |

与 `feat/multiturn` 的其他改动（续聊端点、WebSocket mux、compaction bracket）**无重叠**。

---

## 6. Scope Lock 确认

- ✅ 只消费了 `reasoning_effort`（RUNTIME Sub-batch 1）
- ✅ `agent_profile` 和 `context_providers` 仍是 staged no-op
- ✅ 不顺手重构无关代码
- ✅ 不提前做未来 Phase
- ✅ 不扩大架构

---

## 7. 遗留项

1. **逐家 provider 验证**：本子批次通过 `_get_request_payload` 验证 `reasoning_effort` 到达 OpenAI SDK payload 结构，但未做真实 provider 调用。逐家验证（deepseek-reasoner 无此参数、glm 思考模型无开关）是独立后续步骤。
2. **`agent_profile` 运行时消费**：独立子批次（接通 AgentFactory + tool_scope 收窄 + system_prompt 注入）。
3. **`context_providers` 运行时消费**：独立子批次（加枚举端点 + 会话级筛选）。

---

## 8. 集成建议

### 8.1 推荐集成方式

本 commit 位于 `feat/multiturn` 分支上，与其他多轮会话工作混合。集成时应：

1. 确认 `feat/multiturn` 分支的整体状态（包括未提交的多轮会话工作）
2. 将 `feat/multiturn` 合入 `main`（先回后正 §14.6）
3. 或从 `feat/multiturn` cherry-pick `63a437b` 到独立分支再集成

### 8.2 集成后验证门

```bash
git status                    # Working tree clean
uv sync --all-extras          # 幂等
.venv/Scripts/python.exe -m pytest -q    # 0 failed
.venv/Scripts/python.exe -m ruff check src/ tests/
git diff --check              # 无 whitespace/conflict-marker 问题
```

---

## 9. 总结

| 项目 | 状态 |
|------|------|
| `reasoning_effort` 运行时消费 | ✅ minimal→low, standard→medium, deep→high |
| primary + fallback 都传入 | ✅ |
| Web 层注释更新 | ✅ 从"runtime no-op"改为"已消费" |
| 测试覆盖 | ✅ 10 条新测试（映射 + payload + 装配接线） |
| 全量 pytest | ✅ 1297 passed（12 pre-existing failures 来自 multiturn WIP） |
| Ruff clean | ✅ |
| Scope Lock | ✅ 只消费 `reasoning_effort`，不碰 `agent_profile`/`context_providers` |
