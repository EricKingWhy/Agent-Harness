# 集成提示词：feat/runtime-context-providers → main

> **分支**：`feat/runtime-context-providers`
> **Worktree**：`D:\intelligence-agent-runtime`
> **起点**：`origin/main`（`d7cb1c7`）
> **HEAD**：`0e3f037`
> **改动文件数**：10（6 modified + 4 new）
> **新增测试**：14 条（8 条 assembly 筛选 + 6 条 endpoint 投影 + provider name 属性）

---

## 本批做了什么

把 `context_providers`（Phase 5 的第三个也是最后一个 staged 字段）从 no-op 提升为运行时真实消费：会话级 `context_providers: list[str] | None` 按 provider 的 `name` 属性筛选 wiring 自动装配的 ContextProvider 子集注入 ContextBuilder。

这是 RUNTIME 子批次系列的收尾——`reasoning_effort`（ADR-0018 D7）、`agent_profile`（ADR-0020a）之后，`context_providers`（ADR-0020b）全部消费完毕。

---

## 改动清单

| 文件 | 改动 |
| --- | --- |
| `src/agent_harness/memory/context_provider.py` | `MemoryContextProvider` 加类属性 `name: str = "memory"`（稳定标识） |
| `src/agent_harness/skills/context_provider.py` | `SkillCatalogContextProvider` 加类属性 `name: str = "skills"`（稳定标识） |
| `src/agent_harness/assembly.py` | 新增 `_select_context_providers(wired, requested)` 模块级 helper；移除 `context_providers` 的 no-op INFO 日志；ContextBuilder 构造处从 `list(wiring.context_providers)` 改为筛选后子集 |
| `src/agent_harness/web/app.py` | 新增 `CONTEXT_PROVIDER_DESCRIPTIONS` 常量；新增 `_validate_context_providers` validator（形状校验，不 422 未知名字）；`/api/context-providers` 端点从硬编码空改为动态投影 `wiring.context_providers` |
| `docs/spec/.../03_RUNTIME_EVENT_CONTRACT.md` | Phase 5 三字段从 "staged" 改为 "runtime consumed"（全部落地记录） |
| `docs/spec/.../08_DECISION_LOG.md` | ADR-0020 末尾追加 RUNTIME 三批落地小结 |
| `docs/adr/0020b-context-providers-runtime-consumption.md` | 新增 ADR（为什么类属性而非 Protocol 强约束；为什么未知名字 fail-open 而非 422；None vs [] 语义；动态投影而非静态枚举） |
| `docs/goal/GOAL_RUNTIME_CONTEXT_PROVIDERS.md` | 新增 GOAL 规格 |
| `tests/test_assembly_context_providers.py` | 8 条新测试：5 条 build_runtime 筛选 + 3 条 helper 单元测试 |
| `tests/web/test_context_providers_endpoint.py` | 6 条新测试：3 条 endpoint 投影 + 2 条 provider name 属性 + schema 断言 |

---

## 设计决策

### 为什么用类属性而非 Protocol 强约束

`ContextProvider` Protocol 只声明 `select()`。加 `name: str` 到 Protocol 会要求所有未来 provider 同时声明——超出本批范围。改用 `getattr(p, "name", None)` 容错读取：未来未命名 provider 不会被任何请求命中（fail-open），不报错。Protocol 可在未来批次收紧。

### 为什么未知名字 fail-open 而非 422

`reasoning_effort` / `agent_profile` 是封闭枚举——未知值是配置错误，422 合理。`context_providers` 是开放集合：是否装配取决于 CAPABILITIES 运行时状态，validator 没法静态判定。运行时跳过比 422 更宽容（不影响 Core，不变量 #21）。

### 为什么 None ≠ []

- `None` = "没指定，用默认"（全量 wired provider）；
- `[]` = "显式选零"（用户想要一个"纯净"上下文，不要 memory/skills 注入）。

合并两者会让"请求零 provider"变得不可能——你必须同时暗示"给我全部"。

### 为什么清单端点动态投影而非静态枚举

端点此前已声称"provider 装配落地后会自然返回真实清单"——本批兑现这个契约。静态枚举会在未装配时撒谎；动态投影诚实（bare 时空，configured 时有），与 `/api/capabilities` 同原则。

---

## Code-review 结果

两轴审查（Standards + Spec），发现并修复一个问题：

1. **Pydantic validator 中 `raise TypeError` 绕过 422** — 初版用 `TypeError`（ruff TRY004 建议），但 Pydantic `field_validator` 只捕获 `ValueError` / `AssertionError`。改为移除该死分支（Pydantic 类型注解 `list[str] | None` 已强制类型，validator 内的 `isinstance(v, list)` 检查是 redundant dead code），只保留非空字符串语义校验。

其他发现（不修复）：
- **`name` 作为类属性而非实例属性**：类属性对所有实例共享，但 provider 的 name 是类型级常量（所有 MemoryContextProvider 都叫 "memory"），不需要实例化时区分。正确。
- **`getattr(p, "name", None)` 的 None 容错**：未来无 name 的 provider 被 None 容错跳过，不会出现在清单也不会被请求命中。这是刻意设计（fail-open），不是 bug。

---

## 测试结果

### 新 worktree（Python 3.11.15）

```
22 passed (新增 + 相关测试)
58 failed, 1187 passed, 32 skipped, 39 deselected (全量 1303 collected)
```

**58 个 failed 全是 Python 3.11 预存不兼容**（`Path.read_text() got an unexpected keyword argument 'newline'`），与本批改动无关。已在 clean origin/main（d7cb1c7）上用 `git stash` 验证同样的失败存在。

本批新增的 14 条测试全部通过。本批改动涉及的文件（assembly.py / memory+skills context_provider.py / web/app.py）相关测试全部通过。

### Ruff

```
All checks passed!
```

### 建议集成时在 Python 3.13 环境下重新验证全量测试。

---

## 集成步骤

```bash
# 1. 从 runtime worktree push 分支到 origin
cd D:\intelligence-agent-runtime
git push origin feat/runtime-context-providers

# 2. 在 main worktree merge
cd D:\intelligence-agent
git fetch origin
git merge feat/runtime-context-providers

# 3. 验证
python -m pytest --tb=short -q
ruff check
```

---

## 风险与未决项

| 风险 | 缓解 |
| --- | --- |
| 改 provider 的 `name` 值破坏请求兼容 | 已在 `name` 属性注释中标注稳定性契约；ADR-0020b 记录 |
| 未来无 `name` 的 provider 在清单端点不可见 | `getattr` 容错读取；匿名 provider 刻意不暴露（稳定 id 契约） |
| feat/backend 有另一会话的未提交工作（T5 #135 MinIO） | 本批在隔离 worktree（D:\intelligence-agent-runtime）开发，不与 feat/backend 冲突；assembly.py 改动区域不同（本批改 ContextBuilder 构造处 ~line 261，T5 改 artifact 注册后 ~line 170） |

---

## 与其他分支的关系

- **`feat/runtime-agent-profile`**（已合入 main 为 `2dce596`/`11e5494`）：与本批正交。都改 `assembly.py` 但改动区域不同（agent_profile 改 profile lookup + registry filter；本批改 ContextBuilder 构造处）。都改 `web/app.py` 但改动区域不同。
- **`feat/runtime-reasoning-effort`**（已合入 main 为 `88310b2`/`79e2860`）：同上。
- **`main`**：本批从 `origin/main`（`d7cb1c7`）起，可直接 merge 回 main。
- **`feat/backend`**：当前有另一 AI 会话的未提交工作（T5 #135 MinIO externalization）。本批不在 feat/backend 开发（§13.3 并行隔离），与本批无文件冲突（不同区域）。

---

## RUNTIME 子批次收尾说明

本批完成后，Phase 5 的三个 staged 字段全部运行时消费完毕：

| 字段 | ADR | 消费方式 |
| --- | --- | --- |
| `reasoning_effort` | ADR-0018 D7 | `create_chat_model` 注入 ChatOpenAI 原生字段 |
| `agent_profile` | ADR-0020a | `ContextBuilder` 注入 system_prompt + `registry.filtered` 收窄 tool_scope |
| `context_providers` | ADR-0020b | `_select_context_providers` 按 name 筛选已装配 provider 子集 |

Phase 5 RUNTIME 子批次系列到此结束。
