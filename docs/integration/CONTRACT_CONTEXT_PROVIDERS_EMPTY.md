# 契约决策：`context_providers: []`（显式空）vs 省略字段

> **状态**：已决策（2026-09-09，后端会话）
> **决策人**：后端会话（用户授权「听你的吧」）
> **影响端**：前端（需要改） / 后端（不改）
> **依据**：ADR-0020b / ADR-0021（三值语义）、`docs/spec/06_CONTEXT_ARTIFACT_MEMORY.md`

---

## 1. 问题

前端 Composer 的 Context Providers 是多选控件。用户**把已选的 provider 全部取消**时，
请求体应该发什么？

- A. 省略 `context_providers` 字段（等价 JSON 里没有这个 key）
- B. 发 `"context_providers": []`

后端 `context_providers: list[str] | None` 是三值语义，两者含义不同，选错会静默地把
用户「我不要任何 provider」变成「给我全部 provider」。

## 2. 决策

**后端保持 ADR-0020b / ADR-0021 的三值语义不变；前端必须发 `[]`（方案 B）。**

| 请求体 | 后端语义 | 用户意图 |
|---|---|---|
| 字段缺失 / `null` | 装配全部已注册 provider | 「没动过这个控件，用默认」 |
| `[]` | 注入零个 provider | 「我明确不要任何 provider」 |
| `["memory", "skills"]` | 只注入 name 命中的 | 「我只要这两个」 |

`[]` 与省略的语义差异是**有意设计**（ADR-0020b §"Why `None` ≠ `[]`?"），
不是实现疏漏：默认全开保证未触碰控件的旧客户端行为不变；显式空保证用户能真正
关掉记忆/技能等上下文注入。改 `[]` 为「默认全开」会让「关闭全部」这一操作不可表达，
因此**不改后端**。

## 3. 前端需要做什么

1. **区分「未触碰」与「已清空」**：控件状态需要一个 dirty / touched 标记，
   不能只靠 `selected.length > 0`。
2. **提交时**：
   - 未触碰 → 不传 `context_providers`（保持默认全开）；
   - 触碰过且 `selected.length === 0` → 传 `"context_providers": []`；
   - 触碰过且有选中 → 传 `["id1", "id2"]`。
3. **反例（不要这样写）**：
   ```ts
   // ❌ 全选清空后退化成「不传字段」→ 后端恢复全部 provider
   context_providers: selected.length > 0 ? selected : undefined
   ```
4. **建议**：给「无 provider」一个可见的选中态（例如 chips 全空但控件处于 active），
   让用户能确认自己确实清空了。

## 4. 后端证据（当前已 pin 的行为）

| 层 | 位置 | 行为 |
|---|---|---|
| 装配 | `src/agent_harness/assembly.py` `_select_context_providers` | `None` → 全集；`[]` → 空；`[ids]` → 命中子集 |
| 端点 | `src/agent_harness/web/app.py` `create_session` | 透传，不做 None/[] 归一化 |
| amend | `src/agent_harness/session/service.py` `AmendOptions` | 三值原样透传到 `build_runtime` |
| 测试 | `tests/test_assembly_context_providers.py` | `test_build_runtime_none_request_keeps_all_providers` / `test_build_runtime_empty_list_injects_no_providers` / `test_select_helper_empty_returns_empty` |
| 测试 | `tests/web/test_context_providers_endpoint.py` | 端点 `[]` 载荷用例 |

## 5. 验收方式（前端改完后）

- 清空全部 provider 后发消息 → 后端该 run 不注入任何 context provider
  （观察 `GET /api/sessions/{id}` 或 run 的 wiring 投影）。
- 未触碰控件直接发消息 → 行为与改动前一致（全部 provider 注入）。
- 不要只测 UI 选中态；要断言**实际请求体**里 key 的存在性与值。

## 6. 非目标

- 不新增 `"all"` 之类的魔法值。
- 不把 `[]` 重定义为默认全开。
- 不改 `GET /api/context-providers` 的诚实空返（bare 配置下 `{"providers": []}` 保持不变）。
