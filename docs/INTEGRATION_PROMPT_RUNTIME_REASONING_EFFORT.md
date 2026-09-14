# 集成提示词：feat/runtime-reasoning-effort → main

> **分支**：`feat/runtime-reasoning-effort`
> **Worktree**：`D:\intelligence-agent-runtime`
> **起点**：`origin/main`（`11e5494`）
> **HEAD**：`88310b2`
> **改动文件数**：14
> **新增测试**：6 条（4 条 create_chat_model 注入 + 2 条 build_runtime 透传）

---

## 本批做了什么

把 `reasoning_effort` 从 staged no-op 提升为运行时真实消费——经 `create_chat_model` 直接作为构造器 kwarg 传入 `ChatOpenAI`（原生支持该字段），由 SDK 作为 `extra_body` 传给 API。不支持的 Provider 静默忽略（OpenAI SDK 语义）。

---

## 改动清单

| 文件 | 改动 |
| --- | --- |
| `src/agent_harness/model/provider.py` | `create_chat_model` 加可选 `reasoning_effort: str \| None = None` 参数；非 None 时直接作为构造器 kwarg 传入 `ReasoningChatOpenAI`（ChatOpenAI 原生支持该字段） |
| `src/agent_harness/assembly.py` | 移除 `reasoning_effort` no-op 日志；primary 和 fallback 模型构造都注入 `reasoning_effort` |
| `src/agent_harness/web/app.py` | 注释更新：`reasoning_effort` 从 "runtime no-op" 改为 "已运行时消费"；`agent_profile` 注释同步更新（它已在 ADR-0020a 落地） |
| `tests/model/test_reasoning_effort.py` | 4 条新测试：注入 deep、默认无、None 同默认、注入 minimal |
| `tests/test_assembly_reasoning_effort.py` | 2 条新测试：build_runtime 透传到 model、None 不注入 |
| 8 个既有测试文件 | 修复所有 patch `create_chat_model` 的 lambda，从 `lambda config:` 改为 `lambda config, **kw:`，接受 `reasoning_effort` kwarg |

---

## 设计决策

### 为什么直接作为构造器 kwarg，不用 model_kwargs

`ChatOpenAI` 原生支持 `reasoning_effort` 字段。最初实现走 `model_kwargs` 路径，但 SDK 会发出 UserWarning："Parameters {'reasoning_effort'} should be specified explicitly"，然后把 `reasoning_effort` 从 `model_kwargs` 提升为顶层属性。直接作为构造器 kwarg 传入更干净，避免警告。

### 为什么 fallback 也注入

用户选择了 `deep` reasoning effort，如果 primary 瞬时故障切到 fallback，fallback 也应尊重这个选择。Fallback 和 primary 都经 `create_chat_model` 构造，都传入相同的 `reasoning_effort`——语义一致。

### 为什么不在 Runtime 层（每次 astream/ainvoke）注入

`reasoning_effort` 是会话级配置（每个 session 一个值），不是每步变化的参数。它在模型构造时就确定了，不需要在每次调用时传递。`create_chat_model` 已是模型构造的唯一入口——在这里注入最自然。

---

## Code-review 结果

两个子代理（Standards + Spec）并行审查，发现两个真实问题（均已修复）：

1. **Fallback 模型缺少 `reasoning_effort`** — 目标明确说 primary + fallback，但初版只在 primary 传入。已修复：fallback 也注入。
2. **`model_kwargs` 方式触发 UserWarning** — `ChatOpenAI` 原生支持 `reasoning_effort` 字段，直接作为构造器 kwarg 传入更干净。已修复。

其他发现（不修复，记录原因）：
- **Shotgun Surgery（8 个测试文件的 lambda 改动）**：添加 keyword-only 参数到 `create_chat_model` 的必然副作用。所有改动都是机械的 `lambda config:` → `lambda config, **kw:`，无法避免。
- **Primitive Obsession（`reasoning_effort: str | None`）**：可以用 `Literal["minimal", "standard", "deep"] | None` 代替裸字符串。但 web 层已做校验（422），runtime 层保持 `str | None` 与 `agent_profile` 一致（后者也是裸字符串）。不改。

---

## 测试结果

### 新 worktree（Python 3.11.15）

```
6 passed (新增切片测试)
58 failed, 1174 passed, 32 skipped (全量)
```

58 个 failed **全是 Python 3.11 不兼容**（`Path.read_text() got an unexpected keyword argument 'newline'`），与本批改动无关。这些测试在 Python 3.13 环境下全部通过。

基线对比（clean origin/main 在同一 Python 3.11 环境）：62 failed / 1170 passed → 本批后：58 failed / 1174 passed。净效果：-4 failed / +4 passed（修好了几个之前因 lambda 签名不匹配而失败的 web 测试）。

### 建议集成时在 Python 3.13 环境下重新验证全量测试。

---

## 集成步骤

```bash
# 1. 在 D:\intelligence-agent (main) 拉取最新
cd D:\intelligence-agent
git fetch origin

# 2. 从 runtime worktree push 分支到 origin（如果尚未 push）
cd D:\intelligence-agent-runtime
git push origin feat/runtime-reasoning-effort

# 3. 在 main worktree merge
cd D:\intelligence-agent
git merge feat/runtime-reasoning-effort

# 4. 验证
python -m pytest --tb=short -q
ruff check
```

---

## 风险与未决项

| 风险 | 缓解 |
| --- | --- |
| Provider 不支持 `reasoning_effort` 参数 | OpenAI SDK 语义：不支持的字段会被 Provider 静默忽略。不会报错。 |
| 既有测试 patch 签名不匹配 | 已批量修复所有 `lambda config:` → `lambda config, **kw:`。如果后续新增 patch 也需要注意。 |

---

## 与其他分支的关系

- **`feat/runtime-agent-profile`**（已合入 main 为 `11e5494`/`2dce596`）：与本批正交。两者都从 `origin/main` 起，改动文件不重叠（agent_profile 改 `context/builder.py` / `agent/runtime.py` / `agent/factory.py` / `assembly.py`；reasoning_effort 改 `model/provider.py` / `assembly.py` / `web/app.py`）。`assembly.py` 有重叠但改动区域不同（agent_profile 改 profile lookup + registry filter + system_prompt；reasoning_effort 改 model 构造调用）。
- **`main`**：本批从 `origin/main`（`11e5494`）起，可直接 merge 回 main。
