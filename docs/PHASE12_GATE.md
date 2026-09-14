# Phase 12 Real Gate — Web Search / Reliability

> **日期**：2026-09-06
> **Ticket**：#81（Phase 12 收尾）
> **决策来源**：ADR-0014（决策 19：in-process Fake 进 CI + 真实 Gate 收尾）
> **执行方式**：`uv run pytest tests/integration/test_phase12_web_gate.py -m integration -v`
> **凭证**：Tavily key 与 fallback provider key 均从 `.env`（Settings）读取，本文档与测试输出零泄漏（REDACTED 处理）。

---

## 结果总览

| Gate | 内容 | 结果 |
| --- | --- | --- |
| Gate 1 | Tavily 真实联网搜索 | ✅ PASS |
| Gate 2 | Model Fallback 真实切换 | ✅ PASS |
| Gate 3 | 同错熔断真实触发 | ✅ PASS |

CI 全量回归：**955 passed, 8 skipped, 12 deselected**（12 = 本 gate 3 条 + 既有 integration/qiniu 凭证门），ruff clean。

---

## Gate 1 — Tavily 真实联网（WebSearchProvider 默认实现）

**验证点**：真实 Tavily API 端到端——`WebSearchTool` → `TavilyWebSearchProvider`（手写 httpx）→ 真实网络 → 带 citation 的命中。

实测查询 `Python asyncio 官方文档`（k=3）：

| citation | score | 标题（截取） |
| --- | --- | --- |
| `web:https://docs.python.org/zh-cn/3.12/library/asyncio.html` | 0.845 | asyncio --- 异步 I/O — Python 3.12.13 文档 |
| `web:https://docs.python.org/zh-cn/3/library/asyncio.html` | 0.827 | asyncio --- 异步I/O — Python 3.14.7 文档 |
| `web:https://docs.python.org/zh-cn/3/library/asyncio-dev.html` | 0.801 | 用 asyncio 开发 — Python 3.14.7 文档 |

- citation 一路携带（`web:<url>`，ADR-0014 决策 12）
- snippet / score 真实返回；`include_raw_content=true` 生效（raw_content 字段在 payload）
- 分数为 Tavily 真实相关分，未做任何修饰

## Gate 2 — Model Fallback 真实切换（瞬时故障转移）

**验证点**：primary 指向死端点（`http://127.0.0.1:1/v1`，连接失败 = 瞬时错误，ADR-0014 决策 1/15）→ `ModelFallbackCoordinator` 按 `TwoLevelFallbackPolicy` 切换 → **真实 fallback provider** 完成回答 → `model/fallback` SessionEvent 落 JSONL。

实测（provider = senseaudio / `deepseek-v4-flash-0731`，凭证来自 `.env`）：

```json
{"status": "completed", "final_text": "1+1等于2。"}
{"model/fallback": {"from_model": "deepseek-v4-flash-0731", "to_model": "deepseek-v4-flash-0731", "reason": "APIConnectionError"}}
```

- **reason=APIConnectionError 实证了 openai SDK 异常按类名分类的共享 helper
  在真实路径生效**（`is_transient_model_error`，ADR-0014 决策 15）——死端点在
  langchain-openai 下抛的是 openai 包装异常，不是 httpx 原生异常。
- 切换事实在 `model/completed` 之前持久化（JSONL 顺序 = 时间顺序，白盒透明）。
- 非瞬时错误（认证/参数错）不切换的语义由单元测试钉死（`tests/test_model_fallback.py`）。

## Gate 3 — 同错熔断真实触发（#69）

**验证点**：真实模型被要求同轮并行发起 8 个同参数调用 `fail_probe`（总是
`ok=False`）→ guard 累计同指纹失败 → 硬熔断 `end_run(failed)`。

实测（同上 provider）：

- 熔断事件：`tool_failure_guard`，`level=hard`，`consecutive_failures=6`，
  `tool_name=fail_probe`
- run 终态：`identical_tool_failure_loop`（绝不伪造最终回答）

**单批塌缩语义（实测发现）**：8 个同指纹失败在同一批并行调用中一次性到达时，
观察循环塌缩到最严重信号——只发 `hard` 事件（硬熔断终结 run，软熔断的纠正
消息注入已无意义）。`soft → hard` 的跨轮次顺序双事件语义由 T1 的
ScriptedModel 单元/集成测试钉死（`tests/agent/test_repeated_tool_failure_loop.py`）。

**概率性说明**：真实模型对「发起 8 个同参调用」指令的服从是概率性的
（temperature=0 也不保证）。gate 最多独立尝试 3 次（各自全新 session），熔断
在任一次触发即通过；确定性语义全部由单元测试覆盖。本次 gate 实测一次即触发。

---

## 遗留 / DEFER（ADR-0014 权衡已记录）

- 质量型 Model Fallback（LLM judge）——复杂度跳级，DEFER
- oh-my-pi 全链 fallback（role/wildcard、cooldown 切回）——`FallbackPolicy`
  seam 已预留，升级只换实现
- `fetch_url` 通用网页抓取工具、web 二次读取工具、自动 web 检索编排（学术 CRAG）
- 同错熔断精确指纹对「args 抖动」场景可能漏判——等前端实测再加参数规范化
