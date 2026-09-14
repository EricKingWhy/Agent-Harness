# GOAL: RUNTIME 子批次——`reasoning_effort` 运行时真实消费

> **分支**：`feat/runtime-reasoning-effort`（从 `origin/main` 起）
> **Worktree**：`D:\intelligence-agent-runtime`（复用，切新分支）
> **范围**：把 `reasoning_effort` 从 staged no-op 提升为运行时真实消费——经 `create_chat_model` 注入到模型客户端的 `model_kwargs`。
> **约束**：不依赖外部 provider key；纯 runtime 接线；Reuse First——复用 `create_chat_model` 既有 seam。

---

> ## ⚠️ 勘误（2026-09-11，commit `4219cbc`）——本文件 §1.2 / §2.3 / §3.1 / §5 / §6 的透传假设已被生产证伪
>
> 本文件要求把 harness 档位（`minimal | standard | deep`）**原样**作为
> `reasoning_effort` 发出，并在 §5 风险表断言「不支持的字段会被 Provider
> 静默忽略，不会报错」。**该断言是错的。**
>
> 实测：OpenAI 兼容推理端点**严格校验该字段的取值枚举**并硬 400——
> `.agent/logs/agent.jsonl` 2026-09-08 ~ 09-11 反复出现
> `error_type=BadRequestError`，正文
> `'reasoning_effort' must be one of: 'none','minimal','low','medium','high','xhigh','max'`，
> `input: 'deep'`。只有 `minimal` 恰好同名合法；`standard` / `deep` 是非法字面量，
> 选这两档后**该会话每一次 run 都在第一次模型调用失败、零输出**。
>
> 现状（以代码为准）：
>
> - `minimal | standard | deep` 是**产品词汇**（前端显示 轻量/标准/深度），
>   不是任何 API 认的字面量；
> - `src/agent_harness/model/provider.py` 新增线格式合法枚举
>   `WIRE_REASONING_EFFORTS` 与翻译表 `REASONING_EFFORT_WIRE`
>   （`minimal→minimal` / `standard→medium` / `deep→high`），
>   `create_chat_model` 只注入翻译后的合法字面量；
> - 翻译表键集与 Web 层目录键集由
>   `tests/model/test_reasoning_effort.py` 的 G5 漂移守护锁住。
>
> 因此：**§1.2 的「静默忽略」结论、§2.3 的「同理透传」、§3.1 的
> `model_kwargs = {"reasoning_effort": reasoning_effort}`、§5 风险表第一行、
> §6 的 `"deep"` Gate 断言均已作废**，保留原文仅为记录当时的推理。
> §7「不做的事」中「不按 Provider 映射不同的 reasoning 参数」**未被违反**：
> 本次是 provider 无关的**线格式适配**，未引入 `enable_thinking` 等
> per-provider 参数名。

---

## 1. 现状勘察结论

### 1.1 `reasoning_effort` 当前完全未接线

- **Web 层**（`web/app.py`）：
  - `REASONING_EFFORT_DESCRIPTIONS`（line 77-90）定义三档：`minimal | standard | deep`
  - `CreateSessionRequest.reasoning_effort`（line 130）接受可选字符串
  - `_validate_reasoning_effort`（line 134-140）校验值在 `REASONING_EFFORT_DESCRIPTIONS` 中，否则 422
  - `GET /api/reasoning-efforts`（line 758-776）返回三档清单，docstring 标注 "当前 runtime no-op"

- **Assembly 层**（`assembly.py`）：
  - `build_runtime` 接收 `reasoning_effort: str | None`（line 114）
  - 仅记一条 INFO 日志（line 130-131），然后丢弃
  - 不传入 `create_chat_model`、不传入 `AgentRuntime`、不影响任何运行时行为

- **Model 层**（`model/provider.py`）：
  - `create_chat_model(config: ModelConfig)` 构造 `ReasoningChatOpenAI`
  - 不接受 `reasoning_effort` 参数
  - `ReasoningChatOpenAI` 继承 `ChatOpenAI`，后者支持 `model_kwargs` 字段（会被 SDK 作为 `extra_body` 传给 API）

### 1.2 Provider 差异

| Provider | 模型 | reasoning_effort 支持 |
| --- | --- | --- |
| deepseek | deepseek-chat | 不支持（deepseek-reasoner 才有思考，但不接受 effort 参数） |
| qwen | qwen-plus | 部分支持（qwen3-thinking 系列） |
| zhipu | glm-4 系列 | 部分支持（glm-4.5 思考模型） |

**关键决策**：`reasoning_effort` 是一个"尽力而为"参数——传给模型客户端，由 SDK 和 Provider 协商。不支持该参数的 Provider 会静默忽略它（OpenAI SDK 的 `extra_body` 语义）。这比按 Provider 映射不同参数更简单、更诚实（不变量 #7：Tool 只有一条统一执行路径——同理，模型参数也走统一路径）。

### 1.3 与 `agent_profile` 的关系

`agent_profile`（ADR-0020a）已落地：system_prompt 经 ContextBuilder 注入 + tool_scope 经 registry.filtered 收窄。`reasoning_effort` 是同一批 RUNTIME 子批次的另一个 staged 字段，正交于 `agent_profile`。

---

## 2. 设计决策

### 2.1 `reasoning_effort` 注入：经 `create_chat_model` 的 `model_kwargs`

`create_chat_model` 加可选 `reasoning_effort: str | None = None`。当非 None 时，把它加入 `model_kwargs` 字典，传给 `ReasoningChatOpenAI` 构造器。`ChatOpenAI` 会把 `model_kwargs` 作为 `extra_body` 传给 API 请求。

**为什么不在 Runtime 层注入**：`reasoning_effort` 是会话级配置（每个 session 一个值），不是每步变化的参数。它在模型构造时就确定了，不需要在每次 `astream`/`ainvoke` 调用时传递。`create_chat_model` 已是模型构造的唯一入口——在这里注入最自然。

**为什么不在 ModelConfig 层注入**：`ModelConfig` 是"模型是什么"的描述（provider、name、key、temperature），而 `reasoning_effort` 是"模型怎么跑"的运行时控制。把它塞进 `ModelConfig` 会让 frozen dataclass 变成 mutable，且混淆了"配置"和"运行时参数"的边界。

### 2.2 Fallback 模型也注入

`build_runtime` 中 primary 和 fallback 都经 `create_chat_model` 构造。两者都传入 `reasoning_effort`——如果用户要求 deep reasoning，fallback 也应尊重这个选择。

### 2.3 默认行为不变

- `reasoning_effort=None`（默认）→ 不传 `model_kwargs`，行为不变（向后兼容）
- `reasoning_effort="minimal"` → `model_kwargs={"reasoning_effort": "minimal"}`
- `reasoning_effort="standard"` → 同理
- `reasoning_effort="deep"` → 同理

### 2.4 Web 层注释更新

`web/app.py` 中标注 "当前 runtime no-op" 的注释需要更新为 "runtime consumed"。`GET /api/reasoning-efforts` 端点的 docstring 同理。

---

## 3. 改动清单

### 3.1 `src/agent_harness/model/provider.py`

- `create_chat_model` 加 `reasoning_effort: str | None = None` 参数
- 当非 None 时，构造 `model_kwargs = {"reasoning_effort": reasoning_effort}` 并传给 `ReasoningChatOpenAI`

### 3.2 `src/agent_harness/assembly.py`

- 移除 `reasoning_effort` 的 no-op 日志（line 130-131）
- 把 `reasoning_effort` 传入 `create_chat_model(config, reasoning_effort=reasoning_effort)`（primary）
- 把 `reasoning_effort` 传入 `create_chat_model(config.fallback, reasoning_effort=reasoning_effort)`（fallback，如果存在）

### 3.3 `src/agent_harness/web/app.py`

- 更新 `reasoning_effort` 相关注释：no-op → consumed
- 更新 `GET /api/reasoning-efforts` docstring

### 3.4 测试

**`tests/model/test_reasoning_effort.py`**（新增）：
- `test_create_chat_model_passes_reasoning_effort` — 传 reasoning_effort="deep" → model_kwargs 含 "reasoning_effort": "deep"
- `test_create_chat_model_no_reasoning_effort_by_default` — 不传 → model_kwargs 不含 reasoning_effort
- `test_create_chat_model_none_reasoning_effort` — 传 None → 同默认
- `test_build_runtime_passes_reasoning_effort_to_model` — build_runtime(reasoning_effort="deep") → model 的 model_kwargs 含 reasoning_effort

**`tests/web/test_web_phase5_amend_fields.py`**（改动既有测试）：
- 如果有 `test_reasoning_effort_accepted_but_noop` 类似测试，改为断言 "consumed"

---

## 4. 实施顺序（TDD 切片）

1. **切片 A — `create_chat_model` 加 `reasoning_effort`**：改 `provider.py` + 4 条新测试。先红后绿。
2. **切片 B — `build_runtime` 透传 `reasoning_effort`**：改 `assembly.py`（移除 no-op 日志 + 传入 create_chat_model）+ 1 条新测试。
3. **切片 C — Web 层注释更新**：改 `app.py` 注释 + docstring。
4. **全量回归**：`pytest`（基线 1233 passed）+ `ruff check`。
5. **Code-review**：Standards + Spec 双轴审查。

---

## 5. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| Provider 不支持 `reasoning_effort` 参数 | OpenAI SDK 的 `extra_body` 语义：不支持的字段会被 Provider 静默忽略。不会报错。 |
| `model_kwargs` 被 `ChatOpenAI` 正确处理 | `ChatOpenAI` 的 `model_kwargs` 字段是 LangChain 官方支持的扩展点，会被 SDK 作为 `extra_body` 传给 API。 |
| Fallback 模型的 `reasoning_effort` 行为 | Fallback 和 primary 都注入相同的 `reasoning_effort`——语义一致。 |
| 既有 `build_runtime` 调用未传 `reasoning_effort` | 默认 None → 不传 model_kwargs，行为不变。 |

---

## 6. 完成判据（Gate）

- `pytest` 全绿（含新增测试；基线 1233 passed 不破）。
- `ruff check` 清洁。
- `reasoning_effort=None`（默认）→ 行为不变（不传 model_kwargs）——向后兼容。
- `reasoning_effort="deep"` → `create_chat_model` 构造的 `ReasoningChatOpenAI` 的 `model_kwargs` 含 `{"reasoning_effort": "deep"}`。
- Fallback 模型也注入 `reasoning_effort`。
- Web 层注释更新：no-op → consumed。
- Code-review 通过（Standards + Spec 双轴）。
- commit 一条：`feat(runtime): reasoning_effort 运行时真实消费——经 create_chat_model 注入 model_kwargs（RUNTIME 子批次）`。

---

## 7. 不做的事（Scope Lock §8）

- 不按 Provider 映射不同的 reasoning 参数（如 Qwen 的 `enable_thinking`）——统一走 `extra_body`，Provider 自己决定是否认。
- 不加 `reasoning_effort` 到 `ModelConfig`——它是运行时控制，不是模型配置。
- 不改 `ModelFallbackCoordinator`——`reasoning_effort` 在构造期注入，不需要 per-call 传递。
- 不优化 `agent_profile` 的 multiagent activate 空跑——那是 ADR-0020a 的 follow-up。
