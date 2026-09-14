# ADR-0005: Phase 9+10 精简版提前施工 + Web UI 技术栈冻结

**Status**: Accepted  
**Date**: 2026-09-04  
**Phase**: 9 (Streaming Surfaces) + 10 (Web Session Inspector) — 精简版提前

## Context

用户的核心痛点：项目一直在跑（zcode/codex 后台开发），但**看不到效果**——没有面向人的入口能让用户看见 agent 在思考、调工具、被边界拦住、给最终回答。`demo/live_agent.py`（终端 demo）解决了第一层，但用户要的是 Web UI：可观测、全透明、流式、展示思考过程，质感对标 DeepSeek Harness 网页版，视觉走 Apple 液态玻璃风。

规格 `14_IMPLEMENTATION_ROADMAP.md` 把 Phase 9 (Streaming Surfaces) 和 Phase 10 (Web Session Inspector) 排在 Phase 4-8 之后（距当前状态 5-6 个 Phase）。但 Phase 9 的**技术硬前置**只有 Phase 1 events + Phase 2 tool events（都已完成）；Phase 4-8 是 roadmap 顺序排序，不是技术依赖。Phase 10 的 Step Detail 面板想要 Phase 4-5 的数据（operation state、artifact、checkpoint），但「initial inspector」可以更早交付，后续 Phase 再往里填字段。

`11_STREAMING_API_WEB_UI.md` 已冻结了大部分设计：三栏布局、AgentEvent 词汇、SSE 默认传输、前端不维护第二套真相（不变量 #22）。`13_OPEN_SOURCE_REUSE_MATRIX.md` 冻结了 FastAPI + Pydantic（REUSE），但**前端框架未定**（Gap）。

## Decision

### 1. 把 Phase 9+10 精简版提前到现在施工

承认跳过 Phase 4-8 的完整交付，但交付 Phase 10 的「initial inspector」：三栏布局 + chat 流 + 流式 + 工具卡片 + approval + 历史 session 回放。Step Detail 面板里 Phase 4-5 相关字段（checkpoint、artifact、operation state）留接缝点占位，后续 Phase 补。**这不是平行架构，是 Phase 10 规格的渐进式交付，只是顺序变了。**

### 2. 流式传输：SSE + REST POST（守规格默认）

- 下行流式：SSE（`GET /sessions/{id}/stream` 推 AgentEvent）
- 上行控制：REST POST（`POST /sessions` 起新任务、`POST /sessions/{id}/approve` 审批决策）
- 历史：REST（`GET /sessions`、`GET /sessions/{id}/events`）

不用 WebSocket（DSH 用 WS，但规格说 V1 可以 SSE；Approval 频率低，REST POST 够；真做多用户广播再上 WS）。

### 3. 前端栈：React 18 + Vite + Radix Primitives + 纯 CSS（液态玻璃）

- React 18 + Vite 6（与 DSH 同栈，生态成熟）
- **Radix Primitives**（无样式可达组件：popover/dialog/tooltip 等）—— 解决手写可达性的坑，不强加视觉
- **纯 CSS（CSS Modules + CSS custom properties）**—— 液态玻璃靠手写（`backdrop-filter`、layered box-shadow、superellipse 圆角），不用 Tailwind/MUI（避免"Tailwind 味"和组件库模板感）
- 不用 Cordis（DSH 的插件架构对这个规模过重）

### 4. AgentRuntime 加 streaming，不改现有契约

新增 `run_stream(session, user_input) -> AsyncIterator[AgentEvent]`，用 `model.astream()` 逐 chunk 产 `model/delta` 事件。**保留旧 `run()` 签名和语义**（现有 252 测试 + demo 不破），`run()` 重构成 `run_stream` 的消费端薄封装避免逻辑重复。

### 5. 前端直接消费 raw SessionEvent（守不变量 #22）

后端只负责「持久化事件 + 推 live AgentEvent」，前端有个纯 reducer 把 raw event 投影成渲染模型（镜像 Python 的 `derive_messages` 逻辑）。**不在后端做投影层**（会造第二套真相）。保证刷新后从 JSONL 完整重建（Phase 10 Gate）。

### 6. 工具卡片：bash 专属 + diff 类专属 + 其余通用折叠

- bash → 终端黑卡（stdout/stderr 分流、exit code 标记）
- edit/apply_patch/write → diff 视图（双栏绿增红删）
- 其余 7 个 → 统一折叠卡片（参数 + 结果，可展开）

### 7. diff 数据：工具侧补返回 before/after

改 `EditTool/ApplyPatchTool/WriteTool` 的 ToolResult，在 `data` 里加 `before`/`after` 或 unified diff 字段。**surgical change**——只加字段不破坏现有契约，对后续 artifact/replay 也有用。

### 8. Approval：对话流内联卡片

agent 卡在某个 tool_call 时原地出现 approval 卡片（工具名 + 参数 + 风险 + 同意/拒绝），批准后工具继续、结果回填同一卡片。不用 modal（割裂感）。

### 9. 前端代码位置：`web/` 顶层目录

独立于 Python `src/`，Vite 工程。FastAPI 用 `StaticFiles` mount serve 构建产物。

### 10. 多用户埋点：auth 中间件留空壳

单用户本地起步，但 FastAPI 的 auth 中间件留接缝点（依赖注入位预留），后续接多用户不用推倒。

## Consequences

**正向**：
- 用户立刻拿到「看见 agent 干活」的能力，痛点解决。
- 守规格不变量（单一真相、事件事实源、前端不存第二套真相）。
- 前端栈冻结消除 Gap，后续 agent 进来不用重新决策。
- Phase 9+10 的 initial 版本落地，正式 Phase 9/10 开工时在此基础上填字段而非重写。

**负向 / 风险**：
- 偏离 roadmap 顺序（Phase 4-8 未完成就做 9+10）—— 但用户明确授权，且技术依赖满足。
- Step Detail 里 Phase 4-5 字段是占位 —— 视觉上会有空槽，需要 graceful empty state 设计。
- 改工具返回 diff 字段是 breaking change for 测试 —— 要补测试覆盖。
- `run_stream` 是新方法，要补 Phase 9 的 streaming 契约测试。

## Alternatives Considered

- **B. 纯临时工具（demo 升级版），不绑 Phase 9/10** —— 违背 AGENTS.md §5（不造平行架构），否决。
- **C. 等 Phase 4-8 完成再开 9/10** —— 守纪律但不解决用户当下痛点，否决。
- **WebSocket 而非 SSE** —— 双向天然但重，REST POST 够覆盖 Approval，留作多用户广播时再上。
- **Tailwind / shadcn 而非纯 CSS** —— 液态玻璃的细腻层级靠 Tailwind 啰嗦且显 Tailwind 味，否决。
- **不改 runtime，UI 端假流式** —— 造假，违背「全透明」诉求，否决。

## References

- Spec `11_STREAMING_API_WEB_UI.md` §1-§9（Phase 9+10 冻结设计）
- Spec `14_IMPLEMENTATION_ROADMAP.md` Phase 9/10 依赖链
- Spec `13_OPEN_SOURCE_REUSE_MATRIX.md` FastAPI/Pydantic REUSE
- DeepSeek Harness 调研报告（三栏布局、tool 卡片、turn folding、WebSocket、CSS Modules）
- AGENTS.md §5（不创建平行架构）、§7.22（Web UI 不维护第二套真相）、§9.3（surgical changes）
- 本决策由 grill-with-docs 流程产出，Q1-Q19 决策树全程记录。
