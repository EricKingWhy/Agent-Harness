# 后端协调 brief：`data.trace_url` 契约（Langfuse 跳转链接）

> 来源：前端 B（feat/frontend-B）。写给后端 A / 集成 AI。
> 前提已拍板：用户确认走方案 Q6(b) + Q7(i)——后端用官方 SDK 下发完整 trace URL，前端纯消费。
> 不是命令，是契约提案。后端 AI 拿到后请按自己的工程规格评估、拍板、排期。

## 一、为什么是这张票（不是前端票）

Phase 15 前端观测的契约链路目前是这样：

```
runtime.py 六处终态分支
  → tracer.trace_id（Langfuse SDK 真实 trace id）
  → 写入 run/completed.data.trace_id 或 run/failed.data.trace_id
  → 前端 projection.ts:390 抽取进 ConversationState.trace_id
  → 前端 StepDetail.tsx:258-263 条件渲染（有 → mono code 可复制 / 无 → 「未追踪」灰字）
  → 前端 App.tsx:296-300 命令面板「Copy Trace ID」
```

前端这一侧**已经接完**。用户想要的下一步是把详情面板的 trace_id 升级成**可点超链接**，点击直达 Langfuse dashboard 对应 trace 页。

但 Langfuse trace 的深链 URL 不是 `{host}/trace/{id}`——官方文档（`https://langfuse.com/docs/observability/features/url`，2026-09-07 查证）的真实格式是：

```
https://{host}/project/{project_id}/traces/{trace_id}
```

其中 `{project_id}` 是 Langfuse 项目 CUID（形如 `clkpwwm0m000gmm094odg11gi`），前端没有任何渠道拿到它。所以：

- **前端单方面做不了这张票**——拼 URL 需要后端上下文。
- **不该让前端自己拼**——§6 Reuse First：官方 Langfuse SDK 提供 `get_trace_url(trace_id)` 自动解析 host + project_id，前端硬拼是重复造轮子且会把 URL 模板钉死在前端代码里（未来 Langfuse 改 URL 结构就要前后端联动改）。

结论：这是**后端票**，前端是纯消费者。

## 二、契约提案

### 字段：`data.trace_url: string`

在 `run/completed` 和 `run/failed` 的 `data` 里新增 `trace_url` 字段，承载官方 SDK 构造的完整可点击 URL。

**与现有 `trace_id` 的关系**：

- `trace_id`（现有）：保留不变。它是机器可读的唯一 id，前端「Copy Trace ID」命令继续用它（用户复制的是纯 id，不是 URL——后者含 project_id，更敏感）。
- `trace_url`（新增）：人类可读的可点击 URL，由官方 `langfuse.get_trace_url(trace_id)` 构造。前端只在「点击跳转」场景用。

两字段并列，不互相替代，不破坏现有契约。

### 语义

| 情形 | `trace_id` | `trace_url` |
| --- | --- | --- |
| Langfuse 启用，run 正常终态 | 真实 trace id 字符串 | `langfuse.get_trace_url(trace_id)` 构造的完整 URL |
| Langfuse 启用，run 失败终态 | 真实 trace id 字符串 | 同上（失败 run 在 Langfuse 也有 trace，跳转有价值——建议对称下发，但这是后端的拍板项） |
| Langfuse 未启用（key 空） | `null`（现有行为） | `null` |
| Langfuse 启用但 SDK 返回空 trace id（理论上不应发生） | `null` | `null` |

**绝不伪造**：`trace_url` 缺失或空 = 不下发该字段，或下发 `null`。前端降级为「显示纯 mono code 的 trace_id」（现有行为），不回退成「未追踪」（因为 trace_id 真实存在，只是不可点击）。

### 为什么用官方 `get_trace_url` 而不是手拼

官方 SDK 的 `langfuse.get_trace_url(trace_id)`（Python）会自动从 SDK 配置解析 host 和 project_id，不要求调用方知道这两个值。这带来：

- **零硬编码**：host（jp 区 / eu 区 / 自托管）和 project_id 都不在调用方代码里。
- **零同步成本**：未来切自托管 Langfuse 或换区，只改 `LANGFUSE_HOST` env，前后端代码都不动。
- **§6 Reuse First 合规**：用官方抽象，不自己维护 URL 模板。

官方文档明确这是推荐用法（`https://langfuse.com/docs/observability/features/url`）。

## 三、实现建议（供后端参考，不是命令）

以下是基于 main 当前代码的改动位置草图，后端 AI 请按自己的工程规格评估。

### 1. `LangfuseSink` 暴露 `get_trace_url`（`src/agent_harness/observability/sink.py`）

当前 `LangfuseSink._client` 是原生 `langfuse.Langfuse` 实例（`sink.py:39`），官方 SDK 自带 `get_trace_url(trace_id=None)` 方法。新增薄封装：

```python
def get_trace_url(self, trace_id: str) -> str | None:
    """故障隔离的 trace URL 构造（ADR-0018 D3 同款异常边界）。"""
    client = self._client
    if client is None or not self.enabled:
        return None
    try:
        return client.get_trace_url(trace_id=trace_id)
    except Exception:
        # 旁路异常一律吞，主流程零感知（ADR-0018 D3）
        return None
```

`disabled` sink（key 空）的 `self._client is None`，自动返回 `None`——零额外门控。

### 2. `RunTracer` 在终态时计算 `trace_url`（`src/agent_harness/observability/tracer.py`）

`RunTracer.trace_id`（`tracer.py:103/124/151`）是已暴露字段。新增并列的 `trace_url` 字段，在 trace finalize（run 终态）时由 sink 构造：

- 时机：trace 完成后、runtime 读 `tracer.trace_id` 的同一时刻。
- 实现：`RunTracer` 持有 sink 引用（或通过装配传入），在 `tracer.trace_id` 首次有值时调 `sink.get_trace_url(self.trace_id)` 缓存结果。

具体是「构造时机」还是「runtime 按需调 sink」由后端 AI 拍——只要终态时 `tracer.trace_url` 能读到值即可。

### 3. `runtime.py` 六处终态分支并列下发 `trace_url`

当前模式（`runtime.py` 里六处）：

```python
trace_id=(tracer.trace_id if tracer else None)
```

建议并列改为：

```python
trace_id=(tracer.trace_id if tracer else None),
trace_url=(tracer.trace_url if tracer else None),
```

涉及位置（按行号，main 状态）：

- `runtime.py:472`（context window exceeded 失败路径）
- `runtime.py:691`、`:712`（正常完成路径分支）
- `runtime.py:865`、`:910`（失败路径分支）
- `runtime.py:975`（cancelled_terminal 调用）

### 4. `session.py` 的 `end_run` 和 `cancelled_terminal` / `failure_terminal` 签名扩展

`session.end_run`（`session.py:285`）已有 `trace_id` 参数，并列加 `trace_url`：

```python
if status == "completed":
    data["cost_usd"] = cost_usd
    data["trace_id"] = trace_id
    data["trace_url"] = trace_url  # 新增
```

`runtime.py` 的 `cancelled_terminal`（`:202`）和 `failure_terminal`（`:225`）的 `terminal_data` 里并列加 `trace_url`（同 `trace_id` 模式）。

### 5. `run/failed` 是否对称下发 `trace_url`

这是**后端拍板项**，不是前端要求。理由：

- **对称下发**的理由：失败 run（含 cancel / orphan）在 Langfuse 也有可见 trace，运维点开能看到失败调用链，有排查价值。
- **只在 `run/completed` 下发**的理由：失败路径的 SDK `get_trace_url` 可能在 trace 未 finalize 时返回不确定值，保守起见只下发确定有效的。

前端对此**无偏好**：消费逻辑是「有 `trace_url` 就渲染链接，没有就不渲染」，两种选择都不破坏前端。

## 四、前端将做的事（契约就绪后）

后端这张票落地（或集成 AI 把它排进队列）后，前端 B 在 feat/frontend-B 上独立开票，走完整 `/implement`（红测先行）→ 四门禁 → 双轴 `/code-review` 流程。范围严格限定为：

1. **`types.ts`**：`ConversationState` 新增 `trace_url: string | null`；`AgentEvent.data` 类型扩展 `trace_url?: string | null`。
2. **`projection.ts`**：`RUN_COMPLETED` 和 `RUN_FAILED` 抽取 `data.trace_url`（同 `trace_id` 模式），缺省 `null`。
3. **`StepDetail.tsx`**：详情面板 Trace 行——`trace_url` 有值时把 trace_id 渲染成 `<a href={trace_url} target="_blank" rel="noopener noreferrer">`，无值时退回现有纯 mono code。
4. **`App.tsx`**：命令面板可选加「Open Trace」（`window.open(trace_url)`），`trace_url` 无值时该命令不出现。Copy Trace ID 命令保持不变。
5. **`styles/app.css`**：链接样式（与现有 mono code 视觉协调，hover 态、external-link 图标可选）。
6. **测试**：projection 单测覆盖 `trace_url` 抽取 + null 降级；StepDetail 组件测覆盖 `<a>` 渲染 + 无 URL 降级。

**前端不做的事**：

- 不做 `/api/config` 端点消费（Q2(a) 已否决）。
- 不自己拼 Langfuse URL 模板（Q6(a)(c)(d) 已否决）。
- 不在 `trace_url` 缺失时显示错误提示或 tooltip（Q4 降级为现有行为，最小变更）。

## 五、集成协调建议

这是跨 worktree 票（后端 + 前端）。建议顺序：

1. 后端 A 在 feat/backend 实现 `data.trace_url` 契约 + 测试（本 brief 的 §二/三）。
2. 后端 A 合入 main（走集成 AI 的常规 merge 流程）。
3. 集成 AI 通知前端 B「契约就绪」。
4. 前端 B 在 feat/frontend-B 开票实现消费侧（本 brief §四）。
5. 前端 B 走完四门禁 + 双轴 review，合入 main。

**前端 B 在第 3 步之前不会动这笔工作**——动了就是为尚不存在的契约造消费端（§8 Scope Lock）。

如果后端 AI 对契约字段名（`trace_url` vs `trace_uri` vs `langfuse_url`）或语义有不同意见，请在实现前反馈，前端消费侧的字段名会随后端最终命名对齐。

## 六、规格与不变量对账

- **ADR-0018 D7**「trace_id 回填」精神延伸：回填的实质是「可跳转的 trace 句柄」，URL 比 id 更贴近这个意图。
- **ADR-0018 D3** 故障隔离：`trace_url` 构造走 sink 异常边界，不拖垮主流程。
- **§6 Reuse First**：用官方 `get_trace_url`，不自己拼 URL。
- **§8 Scope Lock**：前端不为自己拼 URL 造抽象。
- **不变量 #21**：Optional Capability（Langfuse）故障不拖垮 Core——`trace_url` 缺失不影响 run 终态事件的核心语义。
- **不变量 #22**：Web UI 不维护第二套不可对账 Session 真相——`trace_url` 来自事件真值，不是前端构造。

---

联系人：前端 B（feat/frontend-B）。有问题反馈到本 brief 或直接找用户协调。
