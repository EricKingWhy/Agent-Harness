# Ticket B2-MixIn：handler 层 422 校验（混合方案）

> **给后端 C（`D:\intelligence-agent-runtime` worktree）的提示词。**
> **背景**：B2（context_providers 运行时消费）有两个独立实现：
> - **实现 A（ADR-0020b，你写的，已在 main `e18b7fa`）**：类属性 `name` + `_select_context_providers` 纯函数筛选 + **fail-open**（未知 id 静默跳过，不 422）
> - **实现 B（ADR-0021，另一个会话写的，在 `feat/backend` `a731563`）**：`ContextProviderEntry` dataclass + `register_context_provider()` + **handler 层 422**（未知 id 报错含可用清单）
>
> 经 Integrator 对比分析（详见会话记录），用户批准**混合方案**：保留 main 上的实现 A 结构（不动 wiring、不碰 provider 类属性、不加 dataclass），只从实现 B 借鉴 **handler 层 422 校验**这一个核心优势。

---

## 为什么只拿 handler 层 422

实现 A 的 fail-open 把**用户输入校验**和 **capability 故障降级**混为一谈了：

- **不变量 #21**（optional capability 故障不拖垮 core）适用于 **capability 装配失败**——比如 MemoryCapability 配置缺失时跳过 memory provider，不让 core 崩溃。这是对的。
- 但用户提交 `context_providers: ["nonexistent"]` 不是 capability 故障——是**用户输入错误**，应该得到明确的 422 反馈（与 `model` 字段 `from_catalog` 422 同模式）。

fail-open 会让用户以为选成功了但实际被静默跳过，调试困难。handler 层 422 给出诚实反馈：未知 id + 当前可用清单。

## 要做什么

在 `src/agent_harness/web/app.py` 的 `create_session` handler 里，加一层 422 校验——**在 `get_wiring()` 之后、`build_runtime` 之前**：

```python
# 伪代码——位置在 create_session handler 内，get_wiring() 之后
if req.context_providers is not None:
    wired_names = {getattr(p, "name", None) for p in wiring.context_providers}
    wired_names.discard(None)  # 未声明 name 的匿名 provider 不参与校验
    unknown = [pid for pid in req.context_providers if pid not in wired_names]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"context_providers contains unknown ids {unknown}; "
                f"available: {sorted(wired_names)}"
            ),
        )
```

关键点：
- **复用实现 A 的现有结构**——`wiring.context_providers` 里的 provider 实例已经有 `name` 类属性（`"memory"` / `"skills"`），直接 `getattr` 读出来构建合法 id 集合
- **校验在 handler 层**（不是 Pydantic validator）——因为需要访问 `wiring`（runtime conditional），validator 在 parse 时拿不到
- **422 detail 含可用清单**——让客户端看到当前实际装配了哪些 provider
- **匿名 provider（`name` 为 None）不参与校验**——它们不出现在 GET 清单里，也不应该被用户引用

## 不要做什么

- ❌ **不引入 `ContextProviderEntry` dataclass**——实现 A 用类属性 + getattr 够了
- ❌ **不引入 `register_context_provider()` 函数**——实现 A 的 conditional append 够了
- ❌ **不碰 `wiring.py`**——不加 `context_provider_entries` dict
- ❌ **不碰 `memory/context_provider.py` / `skills/context_provider.py`**——类属性 `name` 已到位
- ❌ **不碰 `assembly.py` 的 `_select_context_providers`**——它的 fail-open 语义作为**防御性兜底**保留（万一 handler 层 422 漏了，或者 wiring 在 422 之后装配降级了，assembly 层不应该崩溃）。两层不矛盾：handler 层 422 是主校验，assembly 层 fail-open 是防御性兜底。
- ❌ **不改 Pydantic `_validate_context_providers`**——它继续做形状校验（非空字符串），handler 层做集合校验

## 现有上下文（你已经熟悉，不用重新扫描）

- `src/agent_harness/web/app.py` 的 `create_session` handler——当前在 `get_wiring()` 后直接调 `build_runtime`，没有 context_providers 集合校验
- `src/agent_harness/web/app.py` 的 `list_context_providers` GET 端点——你已经实现了动态投影（遍历 `wiring.context_providers` + `getattr(p, "name")`）
- 参考实现 B 的 422 逻辑（在 `feat/backend` `a731563` 的 `web/app.py` diff 里），但**不要照搬它的 wiring 结构**——只借 422 校验这个 idea

## 验收标准

- [ ] 用户传 `context_providers: ["nonexistent"]` → **422** + detail 含 `available` 清单
- [ ] 用户传 `context_providers: ["memory"]`（memory 已装配）→ 正常（不 422）
- [ ] 用户传 `context_providers: ["memory", "skills"]`（两个都装配了）→ 正常
- [ ] 用户传 `context_providers: []` → 正常（显式选零，不是 422）
- [ ] 用户不传 `context_providers`（None）→ 正常（用默认全量）
- [ ] bare 配置下（没装配任何 provider）传 `["memory"]` → 422（因为 memory 没装配）
- [ ] 422 detail 的 `available` 字段反映当前实际装配的 provider id 集合
- [ ] 全量 pytest 0 failed（Python 3.13 环境，当前基线 1268 passed）
- [ ] ruff clean
- [ ] 至少 2 条新测试：未知 id 422 + 合法 id 通过

## 工作流

1. 从最新 main（`080e1f1`）开新分支 `feat/runtime-context-providers-422`（或你选的名字）
2. 在 `D:\intelligence-agent-runtime` worktree 工作（干净，你的分支刚集成完）
3. 实现 handler 层 422 校验
4. 加测试
5. 四门禁（pytest / ruff）
6. 写交接单，交给 Git Integrator 集成

## 参考

- 实现 A（你的，已在 main）：`e18b7fa` merge commit，ADR-0020b
- 实现 B（参考 422 逻辑）：`feat/backend` `a731563`，ADR-0021
- 当前 main HEAD：`080e1f1`
- 会话记录里 Integrator 的对比分析（含两个实现的详细 diff 对照）
