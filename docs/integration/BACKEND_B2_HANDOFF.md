# Backend B2 Handoff — `context_providers` 运行时消费（集成入 main）

> **给 Git Integrator 的集成提示词。** 本文档汇总 Ticket B2 在 `feat/backend`
> 的实现成果，供集成入 `main` 时审查与验证。

---

## 完成了什么

让用户通过 web 层提交的 `context_providers: list[str]` 真正影响 runtime 装配
的 provider 集合。这是 RUNTIME 子批次的最后一个字段（`agent_profile` 和
`reasoning_effort` 已分别在 ADR-0020a / `79e2860` 落地）。

### 四项改动

1. **wiring 加 id→provider 映射**（`capability/wiring.py`）：
   - 新增 `ContextProviderEntry` dataclass（id / provider / display_name / description）
   - 新增 `register_context_provider()` 单一注册入口（同时更新 dict 和兼容 list）
   - `CapabilityWiring` 新增 `context_provider_entries: dict[str, ContextProviderEntry]`
   - `_wire_memory` 注册 id=`"memory"`，`_wire_skills` 注册 id=`"skills"`
   - 保留 `context_providers: list[Any]` 向后兼容

2. **build_runtime 消费用户 context_providers**（`assembly.py`）：
   - `None` → wiring 全集（向后兼容）
   - `[]` → 空集（用户显式选了不启用任何 provider）
   - `["memory", ...]` → 子集（按用户顺序）
   - 未知 id（config 降级）→ 跳过 + WARNING 日志，不崩溃

3. **GET /api/context-providers 返真实清单**（`web/app.py`）：
   - 从 `wiring.context_provider_entries` 投影 `{id, display_name, description}`
   - 惰性装配 wiring（与其他依赖 wiring 的端点一致）
   - 未装配任何 provider → `{"providers": []}`（B1 测试仍通过）

4. **handler 层 422 校验**（`web/app.py`）：
   - `create_session` 在 `get_wiring()` 后校验未知 id（与 `model` 字段
     `from_catalog` 422 模式一致——validator 无法访问 wiring，handler 才能）
   - 未知 id → 422 + detail 含可用清单

## 改了哪些文件

```
src/agent_harness/capability/wiring.py    # ContextProviderEntry + register_context_provider + 两个 _wire_* 注册
src/agent_harness/assembly.py             # build_runtime 消费 context_providers（三值语义）
src/agent_harness/web/app.py              # GET 端点投影真实清单 + handler 层 422

docs/adr/0021-context-providers-runtime-consumption.md  # ADR（新增）

tests/test_assembly_context_providers.py             # 6 条 assembly 测试
tests/web/test_web_context_providers_b2.py           # 7 条 web 测试（GET 投影 + 422）
```

## 测试结果

```
全量 pytest：1258 passed / 9 skipped / 3 deselected（78s）
集成测试：10 passed / 36 deselected（9.7s）
ruff check src/ tests/：All checks passed
```

测试覆盖了验收标准的全部条款：

- [x] 用户传 `["memory"]` → 只启用 MemoryContextProvider（不含 skills）
- [x] 用户传 `[]` → 不启用任何 provider
- [x] 用户不传 → wiring 全集（向后兼容）
- [x] 用户传不存在的 id → 422（handler 层校验）
- [x] `GET /api/context-providers` 返真实清单（非空当配置开了）
- [x] 配置关了某 provider → 不出现在 GET 清单，POST 也不接受
- [x] 未知 id 在 build_runtime 跳过不崩溃（防御性，web 层应先 422）
- [x] 顺序保留（用户传 `["skills", "memory"]` → 输出按用户顺序）

## ADR

[ADR-0021](../adr/0021-context-providers-runtime-consumption.md) 记录了三个
关键决策：

1. **最小 id 映射层**（不是 provider registry subsystem）——§9.2 Simplicity First
2. **handler 层 422 校验**（不是 Pydantic `@field_validator`）——validator 无法
   在 parse 时访问 AppState/wiring，与 `model` 字段同一约束
3. **三值语义**（None / [] / [ids]）——明确区分"用默认"与"显式选空"

## 是否建议合并

✅ **建议合并入 main**——这是 RUNTIME 子批次的收官字段，落地后前端 F3
（context_providers 多选控件）才有数据可消费（依赖关系：B2 → F3）。

### 集成注意事项

- 无 schema 破坏性变更：`context_providers: list[str] | None` 契约形态不变，
  只是从 no-op 变成真实消费。旧客户端（传 `None`）行为完全不变。
- `CapabilityWiring` 新增字段 `context_provider_entries` 有 default
  (`field(default_factory=dict)`)——直接 `CapabilityWiring()` 的旧调用方不受影响。
- GET `/api/context-providers` 契约形态不变（顶层 `providers` key），只是从
  永远空变成真实投影。前端 F3 据此实现多选控件。

## 还剩什么

无后端剩余工作。RUNTIME 三字段（`agent_profile` / `reasoning_effort` /
`context_providers`）全部落地。

下一个依赖 ticket：**F3（前端）**——context_providers 多选控件。需要从新 main
（B2 集成后）开 `feat/frontend-context-providers`。
