# 联调车道设计：本地 SSE Fixture Server

> 解决的问题：Playwright `route.fulfill` 字符串形态在 1.63 不保证逐帧流式（实测
> `response: new Response(ReadableStream)` 帧未送达）——当前 E2E 骨架（T8 #101）
> 只能断言终态，无法验证流式中间态（caret / reasoning 呼吸图标 / 工具输出
> 跟随浮标 / stdout-stderr 分色 / 重连断线条时序）。
>
> 这份文档不实现，只设计。实现是后续 ticket 的活，按完整 /implement 流程走。
> 关联：`docs/E2E_SCENARIO_MAP.md` 骨架车道已知边界 §1；ADR-0016 流式契约。

## 1. 为什么需要本地 SSE Fixture Server

### 1.1 当前骨架的边界

骨架车道（`e2e/fixtures.ts` 的 `fulfillSse`）用 `route.fulfill` 字符串形态：

```ts
await route.fulfill({
  status: 200,
  contentType: 'text/event-stream',
  body: frames.map(sseFrame).join(''),
});
```

所有帧在 `body` 里一次性序列化为字符串。浏览器收到响应后**立即**把全部帧交给
EventSource——投影瞬时完成，断言只能看到终态。

实测过的替代路径：

- `route.fulfill({ response: new Response(ReadableStream) })`：Playwright 1.63 下
  帧未送达（11/12 E2E 失败的根源）。
- `page.evaluate` 直接往 DOM 注入帧：绕过整个 SSE 投影管线，测的是假路径。

### 1.2 流式中间态是契约的一部分

ADR-0016 + PRD v2 §13 明确要求：text/delta 逐帧到达、reasoning 块流式聚合、
工具输出 stdout/stderr 分色随到达增量、断连后 800ms 断线条出现再消失、重连
after_seq 续传无重复——这些都是**时间维度的行为**，骨架车道无法覆盖。

### 1.3 联调车道的两个候选

| 方案 | 描述 | 优劣 |
| --- | --- | --- |
| A. 真后端联调 | 起 `agent_harness.web.app` + ScriptedModel 或真模型，前端 dev 指向它 | 最真实，但依赖后端环境、模型 SLA、启动成本高；CI 不稳定 |
| **B. 本地 SSE Fixture Server** | 起一个独立的轻量 HTTP server（Node/tsx），按脚本逐帧推 SSE，前端 dev 指向它 | **可控时序、零后端依赖、CI 友好、脚本是真测试资产** |

**推荐 B**，理由：

- 时序是 fixture 脚本声明的，不是等模型吐的——重连断点的时机精确可控。
- 脚本（帧序列 + 间隔 + 注入的故障）是版本化的测试资产，和 vitest 同等地位。
- 真后端联调保留为更高层的「整套链路」验证（见 `SMOKE_CHECKLIST_FRONTEND.md`），
  不用它在 E2E 里重复测前端逻辑。

## 2. 设计：Fixture Server 形态

### 2.1 运行时

- **Node + 内建 http**（不引 express——越轻越好，一个 server 一个文件）。
- 启动方式：`pnpm exec tsx e2e/server.ts`，或包进 playwright 的 `webServer`
  config（和 vite dev 并行起两个 webServer）。
- 端口：固定 5174（5173 是 vite），前端通过 `VITE_API_BASE` env 指向它。

### 2.2 协议：Fixture 脚本

每个场景对应一个 fixture 脚本，描述**帧序列 + 时序 + 故障注入**：

```ts
// e2e/fixtures-stream/stream-reconnect.ts （示意，不是实现）
import type { FixtureScript } from './types';

export const streamReconnectScript: FixtureScript = {
  name: 'stream-reconnect',
  // POST /api/sessions 的响应
  onCreate: { status: 200, body: { session_id: 'fix-reconnect', run_id: 'fix-run-1' } },
  // GET /api/sessions/{id}/stream 的帧序列
  stream: [
    { delay: 50, frame: { type: 'run/started', data: {}, seq: 1, run_id: 'fix-run-1' } },
    { delay: 100, frame: { type: 'text/delta', data: { delta: '从前' }, seq: 2, run_id: 'fix-run-1' } },
    // 第 3 帧前注入故障：故意延迟 3s 模拟卡顿（触发前端 stallCheck 或手动断网）
    { delay: 3000, frame: { type: 'text/delta', data: { delta: '慢' }, seq: 3, run_id: 'fix-run-1' } },
    { delay: 100, frame: { type: 'text/delta', data: { delta: '半字' }, seq: 4, run_id: 'fix-run-1' } },
  ],
  // GET /api/sessions/{id}/stream?after_seq=2 重连后续传（断线条后前端发起）
  reconnectAfterSeq: (seq: number) => [
    { delay: 50, frame: { type: 'text/delta', data: { delta: '后续' }, seq: 5, run_id: 'fix-run-1' } },
    { delay: 50, frame: { type: 'run/completed', data: { final_text: '从前…后续' }, seq: 6, run_id: 'fix-run-1' } },
  ],
  // GET /api/sessions/{id}/events 全量重放（viewing 迁移后前端重读）
  events: [
    { type: 'text/delta', data: { delta: '从前' }, seq: 2, run_id: 'fix-run-1' },
    { type: 'run/completed', data: { final_text: '从前…后续' }, seq: 6, run_id: 'fix-run-1' },
  ],
};
```

关键设计点：

- **`delay` 是 server 发帧前的真实 `setTimeout`**——这是 Playwright route 学不到的
  真时序控制。
- **故障注入靠 `delay` + 剧本时机**，不靠 server 自己断流（断流由测试本身触发
  `page.context().setOffline(true)` 配合）。
- **`reconnectAfterSeq` 是函数**：因为重连发起时机不确定，后续帧要在请求到达时
  动态拼装（关键：把请求的 `after_seq` 参数读出来，跳过已发过的帧）。
- **`events` 全量重放**：覆盖终态后 viewing 迁移触发的前端重读（骨架车道边界
  §3 的教训：mock 必须提供 events fixture）。

### 2.3 Server 路由

```
GET  /api/health                              → 200 {"status":"ok"}
GET  /api/sessions                            → 200 []（或场景提供的列表）
POST /api/sessions                            → 按 fixture.onCreate 响应
GET  /api/sessions/{id}/events                → 按 fixture.events 响应
GET  /api/sessions/{id}/stream?after_seq=N    → 按 fixture.stream 或 reconnectAfterSeq(N) 逐帧推
GET  /api/models                              → 200 {"models": [...]}（场景提供）
POST /api/sessions/{id}/cancel                → 200 {"status":"cancelling"}（场景可选）
其它                                          → 404
```

实现核心是 `/stream` 路由：

```ts
// 伪代码
res.writeHead(200, {
  'Content-Type': 'text/event-stream',
  'Cache-Control': 'no-cache',
  'Connection': 'keep-alive',
});
const frames = afterSeq !== null
  ? fixture.reconnectAfterSeq(afterSeq)
  : fixture.stream;
let i = 0;
const next = () => {
  if (i >= frames.length) { res.end(); return; }
  const { delay, frame } = frames[i++];
  setTimeout(() => {
    res.write(`data: ${JSON.stringify(frame)}\n\n`);
    next();
  }, delay);
};
next();
```

不用 `sse-starlette`，不用 `EventSource` 库——HTTP server 原生 `res.write` 就是
SSE 帧（前端 EventSource 自带解析）。

## 3. 场景矩阵（覆盖骨架车道边界 §1）

骨架车道 12/12 已覆盖终态矩阵；本车道增量覆盖**流式中间态 + 时序**：

| 场景 | 骨架车道对应 | 本车道增量覆盖 |
| --- | --- | --- |
| **流式 caret** | 无法验 | 帧间 100ms 间隔内看到输入 caret 移动（reasoning/text 共用） |
| **reasoning 呼吸图标** | 无法验 | reasoning 块流式聚合过程中呼吸图标在场，完成后消失 |
| **工具输出跟随浮标** | 无法验 | tool/output_delta 多帧到达时浮标跟随最后一帧位置 |
| **stdout/stderr 分色块** | 无法验（终态被 result 校准替换） | 工具运行中看到增量分色，终态后被 result 校准（T3 设计） |
| **断线条时序（重连）** | 无法验（断线条只声明可见→隐藏，无 800ms 时序） | 慢帧 > 800ms → 断线条出现；续传帧到达 → 断线条消失 |
| **after_seq 续传无重复** | 无法验（一次性到达无续传） | 故意制造 seq=2 之后再断 → 续传从 seq=3 开始，无重叠 |
| **backlog>1000 全量重建** | 无（fixture 难造 1000+ 帧） | fixture 脚本声明「收到第 N 帧后发 stream/truncated 控制帧」 |

## 4. 与现有车道的关系（不替代）

| 车道 | 工具 | 范围 | 触发 |
| --- | --- | --- | --- |
| vitest | pnpm exec vitest | 纯函数/投影契约（351） | 每次提交 |
| Playwright 骨架 | route.fulfill 字符串 | mock 终态矩阵（12） | 手动/夜间 |
| **Playwright + Fixture Server**（本设计） | Node SSE server | **流式中间态 + 时序** | 手动/夜间（实现后） |
| 真后端冒烟 | 真 agent_harness | 整套链路 | 联调阶段（见 `SMOKE_CHECKLIST_FRONTEND.md`） |

四层互补，各有不重叠的责任。本设计只新增第三层，不动其它三层。

## 5. 实现时的注意点（给后续 ticket）

不是命令，是实现时的参考清单：

- **WebServer 配置**：`playwright.config.ts` 的 `webServer` 数组加一项指向
  fixture server（5174），启动顺序要在 vite 之后。
- **fixture 选择**：每个 spec 文件在 `test.beforeEach` 里通过环境变量或
  HTTP 切换声明当前场景脚本（如 `GET /__test__/use?script=stream-reconnect`）。
- **CI 稳定性**：`delay` 设短值（50-200ms）+ 断言用 `expect.poll` 而不是
  `setTimeout`；长 delay（3s 慢帧）只用于触发特定状态，断言只看后续状态变化。
- **不引新依赖**：Node 内建 `http` + `fs` 读 fixture 脚本就够，避免把 E2E
  车道变成另一个需要维护的子系统。
- **fixture 脚本即资产**：放进 `e2e/fixtures-stream/`，和 vitest 的
  `*.test.ts` 同等地位提交。
- **首版只覆盖 1-2 个关键场景**（建议从「重连续传无重复」+「reasoning 流式聚合」
  开始），避免一上来就把所有场景都搬到 fixture server——骨架车道已有的终态
  断言不要重复。

## 6. 决策与替代方案记录

- **否决方案 A（真后端 E2E）作为常规车道**：依赖模型 SLA、CI 不稳定、启动成本
  高。保留为整套链路验收（冒烟清单）。
- **否决方案 C（mock EventSource 在浏览器里假推）**：绕过投影管线，测的是假
  路径，发现问题不能反推真后端问题。
- **否决方案 D（升级 Playwright 到支持 ReadableStream fulfill 的版本）**：截至
  1.63 该路径不可靠；即使后续版本修复，也无法精确控制帧间时序（浏览器调度
  决定，不是测试决定）。
- **决策理由**：fixture server 把时序控制权拿回测试手里，是唯一能精确测
  时序相关契约（断线条 800ms、重连续传、backlog 重建）的路径。
