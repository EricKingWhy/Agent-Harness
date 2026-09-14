# Streaming UI 10k 逻辑节点基准报告（#102，PRD §15.3 验收证据）

> 2026-09-06，T9。可复现脚本：`web/src/lib/streaming.perf.test.ts`（perf 手动车道，`npx vitest run -c vitest.perf.config.ts`）；预算断言入库防回潮。机器：Windows 10.0.26200 x64 / Node 22。

## 逻辑节点定义

执行链 activity（model 段 / tool / reasoning 块）= Conversation 虚拟化与 Inspector Timeline 的真实渲染单元。fixture：5000 轮 × 3 activity（user/message + model burst + reasoning 块 + tool call/result，共 7 事件/轮）= **15k 节点 / 23k 事件**——超出 PRD 10k 验收线 50%，且覆盖 T2/T3 新事件管线（reasoning/started|completed、tool 配对）。

## 实测数字（预算 = 20x+ 余量，拦回潮非精确基准）

| 指标 | 实测 | 预算 | 备注 |
|---|---|---|---|
| projectHistory 全量重建（23k 事件 → 15k 节点） | **203.4ms** | < 400ms | 历史加载一次性成本 |
| applyEvent 尾部追加 @15k 节点 | **5.40µs/事件** | < 10µs | 流式 O(1) 契约；修复前 8.79µs（见下） |
| 重复 seq 全量重放（全命中去重） | **~4ms** | < 100ms | T1 幂等在 10k+ 规模的上界 |
| deriveChain（3 活动轮） | **~1µs/次** | < 0.1ms | 锁 deriveChain 不引入全量扫描 |
| **比例探测器**：每轮重建成本 @5k 轮 vs @1k 轮 | **2.6x** | < 8 | 机器无关 O(N²) 回潮探测 |

既有基线（纯 model/delta 流，projection.perf.test.ts 持续守护）：applyEvent @20k = 0.1-0.3µs/事件、projectHistory 20k = 17.2ms。

## 基准发现并修复的真问题（T9 附带产出）

**`withTurnAt` / `locateToolHostTurn` 轮查找 O(turns)**：5000 轮时每事件 8.79µs（健康值 0.1µs）——`findIndex` 线性扫描成为长会话流式热点主导成本。修复：最后一轮 O(1) 快路径（流式与顺序重放的目标几乎总是最后一轮；前提 = turn.step_id 唯一，resolveStep 单调递增设计不变量）。修复后 5.40µs——剩余为 turns 数组 COW 拷贝的 O(turns) 结构性下界（每次事件复制引用数组，React 身份语义所需；对 15k 节点 = ~4µs，比例探测器守住其线性形态）。

## DOM 侧有界性论证（PRD §15.3：10k 节点保持可滚动/响应）

无界 DOM 的四道闸，全部既有机制（历史实测在案）：

1. **Conversation turn 级虚拟化**（@tanstack/react-virtual + measureElement 动态测高）：窗口外 turn 不进 DOM。
2. **Timeline 尾窗 200 行 + 加载更早 500 步长**：20k 事件全量渲染曾实测 359ms → 尾窗后每秒流式 40fps 合帧不再触发全量重渲染（HANDOFF_PERF_FRONTEND P1-4 实测）。
3. **JsonTree 单容器 50 子项渲染预算 + 余量提示**（Inspector raw 面）。
4. **ToolOutputStream 尾窗 8000 字符**（T3）+ ReasoningBlock 前读游标有界加速（T2）。

投影层成本由本基准的预算 + 比例探测器持续守护；浏览器滚动/交互延迟的实测归 T8 Playwright 矩阵（1280/1920 宽度档）与人工 DevTools performance 面板。
