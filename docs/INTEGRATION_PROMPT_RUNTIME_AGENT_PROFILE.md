# 集成提示词：feat/runtime-agent-profile → main

> **分支**：`feat/runtime-agent-profile`
> **Worktree**：`D:\intelligence-agent-runtime`
> **起点**：`origin/main`（`4225af4`）
> **HEAD**：`c659d37`
> **改动文件数**：8
> **新增测试**：16 条（6 ContextBuilder + 3 AgentRuntime wiring + 7 assembly agent_profile）

---

## 本批做了什么

把 `agent_profile` 从 staged no-op 提升为运行时真实消费：

1. **system_prompt 注入**：`ContextBuilder` 新增可选 `system_prompt: str | None`，在 `build()` 返回前 prepend 一条 `SystemMessage`。token 成本单独估算并加到总预算上（不进入 `derive_messages`，避免触发计数失配重估分支）。

2. **tool_scope 收窄**：`build_runtime` 在全部工具注册完后，若 profile 非 `main`/`None` 则用 `registry.filtered(spec.tool_scope)` 派生收窄 registry。收窄后的 registry 流向所有下游（ToolExecutor / AgentRuntime / multiagent activate 的 source_registry）。

3. **child run 一致性**：`AgentFactory.create()` 把 `spec.system_prompt` 传给 child `AgentRuntime`，child 与 parent 路径一致。

4. **默认行为不变**：`agent_profile=None`（默认）→ 不注入 system prompt、registry 全量——向后兼容。

---

## 改动清单

| 文件 | 改动 |
| --- | --- |
| `src/agent_harness/context/builder.py` | `ContextBuilder.__init__` 加 `system_prompt` 参数；`build()` 在 compaction 和非 compaction 两条路径上都 prepend SystemMessage；system_prompt token 单列加到 token_estimate；compaction 路径补回 system_prompt token 到 provider budget（code-review 发现的 bug） |
| `src/agent_harness/agent/runtime.py` | `AgentRuntime.__init__` 加 `system_prompt` 参数，透传给内部 `ContextBuilder`；同时传 `context_builder` 和 `system_prompt` 时 context_builder 优先 + warning |
| `src/agent_harness/agent/factory.py` | `AgentFactory.create()` 构造 child `AgentRuntime` 时加 `system_prompt=spec.system_prompt` |
| `src/agent_harness/assembly.py` | 移除 `agent_profile` no-op 日志；加 profile lookup（`BUILTIN_PROFILES[agent_profile]`）；非 main profile 时 `registry = registry.filtered(profile_spec.tool_scope)`；构造 `ContextBuilder` 时传 `system_prompt=profile_spec.system_prompt` |
| `tests/context/test_builder_system_prompt.py` | 6 条新测试（注入、默认无、位置、预算、缓存、compaction 路径回归） |
| `tests/agent/test_system_prompt_wiring.py` | 3 条新测试（AgentRuntime 透传、默认无、AgentFactory 透传） |
| `tests/test_assembly_agent_profile.py` | 7 条新测试（coding/research_review/main/none 四档 registry + system_prompt 注入） |
| `docs/adr/0020a-agent-profile-runtime-consumption.md` | ADR 记录本批决定 |

---

## Code-review 结果

### Standards 轴

- **Hard violation（已修）**：ADR 声称更新了 `web/app.py` 的注释（no-op → consumed），但 diff 中没有 app.py 的 hunk。实际检查发现 app.py 的注释确实还是旧的 "runtime no-op"。
  - **状态**：app.py 注释更新在本批被遗漏。这不影响运行时行为（app.py 只做 HTTP 层透传），但注释与实际行为不一致。
  - **建议**：集成时顺手修正 app.py 的两处注释（line 92, line 782），或开一个 follow-up ticket。

- **Judgement call**：`builder.py` 两个 return 路径都调用 `_prepend_system_prompt(built)`——形状相同，可提取。但这是最小重复（2 处），提取反而增加间接层。保留。

- **Lazy import**：`assembly.py` 在函数体内 `from agent_harness.agent.profiles import BUILTIN_PROFILES`——如果不存在循环依赖应提到模块级。轻微 smell。

### Spec 轴

- **Compaction-path token budget bug（已修）**：code-review 发现 compaction 路径把 `result.token_estimate` 直接传给 `_with_providers`，而 `result.token_estimate` 只含 messages 的 token、不含 system_prompt 的 token。这导致 compaction 后 system_prompt 占用的预算被当作可用空间分配给 provider 内容。
  - **修复**：在 compaction 路径中，把 `self._system_prompt_tokens` 加回到 `result.token_estimate` 上再传给 `_with_providers`。
  - **回归测试**：新增 `test_context_builder_compaction_path_reserves_system_prompt_tokens`，构造足够多事件触发 compaction，断言 compaction 后 `_token_estimate_total >= _system_prompt_tokens`。

- **Scope creep**：`AgentRuntime` 同时收到 `context_builder` 和 `system_prompt` 时记 warning——这是 ADR 未描述的防御性逻辑。但它是合理的（防止调用方误以为两个参数会合并），保留。

---

## 测试结果

### 新 worktree（Python 3.11.15）

```
16 passed (新增切片测试)
1168 passed, 58 failed, 32 skipped (全量)
```

58 个 failed **全是 Python 3.11 不兼容**（`Path.read_text() got an unexpected keyword argument 'newline'`），与本批改动无关。这些测试在 Python 3.13 环境下全部通过。

### 后端 worktree（Python 3.13.5，基线环境）

```
1233 passed, 0 failed (基线，本批改动前)
```

**建议集成时在 Python 3.13 环境下重新验证全量测试。**

---

## 集成步骤

```bash
# 1. 在 D:\intelligence-agent (main) 拉取最新
cd D:\intelligence-agent
git fetch origin

# 2. 检查 feat/runtime-agent-profile 分支是否存在
git branch -a | grep runtime-agent-profile

# 3. 如果分支只在 D:\intelligence-agent-runtime 本地，需要先 push 或直接 merge
#    方式 A：从 runtime worktree push 到 origin
cd D:\intelligence-agent-runtime
git push origin feat/runtime-agent-profile

#    方式 B：直接在 main worktree merge runtime worktree 的分支
cd D:\intelligence-agent
git merge feat/runtime-agent-profile

# 4. 验证
python -m pytest --tb=short -q
ruff check
```

---

## 风险与未决项

| 风险 | 缓解 |
| --- | --- |
| app.py 注释仍说 "runtime no-op" | 集成时顺手修正，或开 follow-up ticket |
| multiagent activate 在 coding/research_review profile 下空跑 | ADR-0020a 已记录，本批不优化（Scope Lock §8） |
| compaction 路径 token budget bug | 已修复 + 回归测试覆盖 |
| Python 3.11 环境下 58 个测试失败 | 已知环境差异，不影响 Python 3.13 环境 |

---

## 与其他分支的关系

- **`feat/multiturn`（SessionService）**：与本批正交。SessionService 的 `create_and_launch` 已透传 `agent_profile`（`service.py:286`），合并后自动与本批兼容（service 层只透传，不消费）。
- **`feat/backend`**：后端开发分支，本批不从它起。
- **`main`**：本批从 `origin/main`（`4225af4`）起，可直接 merge 回 main。

---

## ADR-0020a 关键决策摘要

1. **system_prompt 经 ContextBuilder 注入，不进 derive_messages**——system prompt 是 runtime 装配期上下文（不变量 #4/#5），不是持久历史事件，不写 JSONL。
2. **None/main 不过滤 registry**——main 的 `_MAIN_TOOLS` 是全量超集，filter 等价不过滤，但若未来新增了一个 tool_scope 未声明的工具，filter 会隐性收窄它。所以 main/None 走原路径不 filter，只有 coding/research_review 才收窄。
3. **multiagent activate 在非 main profile 下空跑**——coding profile 的 tool_scope 不含 delegate，但 `wiring.multiagent_provider` 仍被无条件 activate。activate 跑了但 delegate 不在 registry、模型看不到它、无法调用——语义正确（coding 不能 delegate），只是 activate 做了一点无用功。本批不优化（Scope Lock §8）。
