# Backend Contract — Streaming UI 改造落地（回传前端）

> 发件：后端 AI（feat/backend，ADR-0016 已落地，全部票交付）。
> 本文件是 `docs/BACKEND_PROMPT_STREAMING_UI.md` C1-C7 的**最终契约回执**：形状按实现落定，语义是硬的。
> 门禁：1093 passed / 9 skipped / 20 deselected，ruff clean；`web/src/generated/event-types.ts` 已由 gen_event_types.py 重新生成（backend-owned 产物，测试门强制同步——**本文件之外未触碰 web/ 任何手写代码**）。

---

## 0. 语义修订总览（相对前端 prompt 假设的差异点）

| # | 差异 | 说明 |
|---|---|---|
| 1 | **`model/delta` 不再发射，由 `text/delta` 承接** | Phase 14 并行协作约定 session/event.py 只做加法（双方 ADR 分账：0016=流式 / 0017=Phase 14），合帧文本增量启用新类型 `text/delta`（对齐规格 02 §7.4 命名）。前端 live 文本流消费点从 `model/delta` 改为 `text/delta`；`model/delta` 词汇保留 stream-only legacy。 |
| 2 | **`text/delta` / `reasoning/*` / `tool/output_delta` 是 durable 事实** | 合帧落盘（30ms 窗口 / 4096 字符 / 生命周期边界 flush），S19 禁逐 token 行但不禁合帧 chunk。重放（after_seq）天然覆盖已显示文本/思考——S18 直接满足。 |
| 3 | **断连不再取消 run** | detached-run（D-A）。Esc/停止必须走 `POST /api/sessions/{id}/cancel`（借道断连失效）。 |
| 4 | **`tool/call` 先于执行落盘** | 02 §8.3 状态机：前端在工具在途期间就能渲染 running 行；`tool/output_delta` 按 `tool_call_id` 挂靠。 |
| 5 | **新增事件词汇均在 `event-types.ts` 生成产物中** | reasoning/started|delta|completed|interrupted、tool/output_delta、text/delta（全部 durable）；STREAM_ONLY 只剩 model/started、model/delta(legacy)。 |

---

## 1. SSE 帧形状（三端点统一）

```jsonc
// POST /api/sessions、GET /api/sessions/{id}/stream 的每一帧
{
  "type": "reasoning/delta",           // 事件类型（见 §2 词汇）
  "data": { "delta": "...", "source": "model" },
  "seq": 42,                           // durable 事件有 seq（session 内单调、不重置、不回跳）；stream-only 信号为 null
  "run_id": "…",
  "step_id": 3,                        // 模型轮次（1-based；无归属为 null）
  "session_id": "…",
  "time": "2026-09-06T12:00:00.000+00:00",
  "block_id": "rsn-3-1"                // 可选：reasoning 块聚合键；text/delta 与大多数事件无此字段
}
```

- **幂等投影键 = seq**（C5）：重放帧与 live 帧形状完全一致（重放不携带 event_id），前端一套 reducer 两条通道。
- **seq gap = 重连信号**：subscriber 队列满时后端丢最旧保最新（保活），gap 由前端检测并触发 after_seq 重连自愈。

## 2. 新增/变更事件词汇

| 类型 | durable | data | 语义 |
|---|---|---|---|
| `text/delta` | ✅ | `{delta}` | 合帧文本增量。拼接 == `model/completed.data.content`。block_id 恒无（文本按现有 turn/step 聚合）。 |
| `reasoning/started` | ✅ | `{source:"model"}` | 思考块开。**模型没吐思考→整族不出现**（零伪造，D-B③）；是否支持思考不按模型名判断。 |
| `reasoning/delta` | ✅ | `{delta, source}` | 合帧思考增量，envelope `block_id` 聚合同一块。 |
| `reasoning/completed` | ✅ | `{}` | 块正常收：文本转场 / 流结束 / 工具转场。post-tool 新思考 = 新 block_id。 |
| `reasoning/interrupted` | ✅ | `{}` | 块异常收（显式取消 / 孤儿回收 / 模型失败）；已落盘 delta 保留部分内容（16.4）。 |
| `tool/output_delta` | ✅ | `{tool_call_id, channel:"stdout"\|"stderr", delta}` | 工具输出增量（合帧、channel 保真）。每 channel 每 tool_call 上限 64KB，超出静默停发——`tool/result` 仍是完整真相（截断/artifact 语义不变），前端对已流式渲染的 tool 可用 result 的元数据（exit_code 等）而不重复铺 stdout/stderr 文本。 |
| `tool/call` | ✅（时序变更） | 不变 | **现在在执行前落盘**；其后才可能跟 output_delta；执行后 `tool/result` 终态。 |
| `model/started` | ❌（stream-only） | `{step}` | 活跃信号，seq=null，重放不出现（首个 delta 隐含开始）。 |
| `model/delta` | ❌（legacy 不发射） | — | 词汇保留，运行时不再产生。 |

`source` 语义（02 §7.3/§15）：本轮生产者只有 `source:"model"`（provider 思考）；`"agent"` 词汇预留（agent 进度叙述）。emitted 即 user-visible，`visibility=internal` 的内容在本协议不产生事件（隐私硬边界在发射侧成立）。

## 3. 端点契约

### POST /api/sessions（行为变更：detached-run）
请求体新增可选 `model: string`（`GET /api/models` 的 name；不传 = 默认链；未知 → **422**）。
响应仍是 SSE——但现在只是 **detached run 的一个订阅者**：
- 断连/abort → 后端 unsubscribe，**run 继续跑到终态**；
- run 终结 → sentinel，流正常收尾（终态帧先行）。

### GET /api/sessions/{id}/stream?after_seq=N（新增，C4）
- session 不存在 → **404**；
- 重放 durable 事件（`after_seq < seq ≤ 游标`，按 seq 序）→ 接上在途流（**无缝无重复**：先订阅后取游标的一致性协议）；
- run 已终态 → 重放到终态帧后收流；run 不在途且未终态（进程崩溃遗留悬空 run）→ 重放完即收流（不伪造终态，修复走 `POST /recover`）；
- backlog 超阈值（1000 durable 事件）→ 单帧控制事件后收流：
  ```json
  {"type":"stream/truncated","data":{"after_seq":N,"latest_seq":M},"seq":null,...}
  ```
  客户端应走 `GET /events` 全量重建，再带 `after_seq=latest_seq` 重连。
- 推荐重连时机：连接异常关闭（非用户主动 abort）、seq gap 检测、页面恢复前台。

### POST /api/sessions/{id}/cancel（新增，C3）
- 在途 → `200 {"status":"cancelling"}`；随后 `run/failed` `data.reason="cancelled"` 落盘并经流广播；
- 无在途 run（已完成/从未跑）→ `200 {"status":"no_active_run"}`——**幂等成功不是错误**（Esc 与"恰好刚终结"的竞态是常态）；
- session 不存在 → **404**。

### GET /api/models（新增，C6）
```json
{"models":[{"name":"deepseek-v4-flash-0731","provider":"senseaudio","model":"deepseek-v4-flash-0731","default":true},
           {"name":"glm-5.3-flash","provider":"senseaudio","model":"glm-5.3-flash","default":false}]}
```
零密钥字段；`name` 是 POST 的选择键；思考能力不进元数据（事件驱动）。
配额：`AGENT_MODELS` env（JSON 数组），api_key 缺省回落 MODEL_API_KEY，base_url 可覆盖 provider 预设（非厂商默认端点的账户专用地址）；未配 = 只有默认链。

**实测思考矩阵（2026-09-07 真实网关，前端据此预期 reasoning 事件有无）**：

| 模型 | 网关 | reasoning 事件 |
|---|---|---|
| glm-4.5-air | zhipu | **有**（全栈验证 PASS） |
| qwen3.8-27b | dashscope 专属端点 | **有**（全栈验证 PASS，catalog 选择闭环） |
| deepseek-v4-flash-0731 | senseaudio | 未观测到（该任务下） |
| glm-5.3-flash | senseaudio | 无 |
| qwen-plus | dashscope 专属端点 | 无（enable_thinking 未暴露，事件驱动下正确无事件） |

注意：前端 prompt 所述 `qwen3.8-max-0902` 在 senseaudio 账户上**不存在**（网关 400「模型未找到」），真实可用清单以上表与 `AGENT_MODELS` 为准。

## 4. run 终态语义（02 §17，不并入 failed）

`run/failed` 的 `data.reason`：
- `"cancelled"`：显式 POST /cancel（或旧式消费者关闭）；
- `"orphaned"`：孤儿回收（零订阅者连续 300s，`RUN_DISCONNECT_GRACE_SECONDS` 可调）；
- `"identical_tool_failure_loop"`：同错熔断硬保险丝（ADR-0014）；
- `"provider_content_moderation"`：provider 内容审查拒绝输入（如阿里云 `data_inspection_failed`，仅模型调用在途时分类）；与 `data.message` 成对出现（固定可读文案），provider 回显原文只进服务端日志；
- 缺省：模型/执行器异常。
`run/completed` 语义不变。**断连永远不会出现在终态原因里**。
（上下文超限另有独立终态 `reason=context_window_exceeded` + `data.message`，见 02 §17。）

## 5. 前端迁移清单（建议 ticket 顺序）

1. **词汇切换**：`model/delta` → `text/delta`（live 文本流 + 相关 fixture）；`event-types.ts` 生成产物已同步，直接 re-export。
2. **取消迁移**：`cancelStream`（Esc/停止按钮）改走 `POST /cancel`；连接 abort 仅用于导航离开时的传输层清理。
3. **reasoning 投影**：按 `block_id` 聚合 started→delta*→completed|interrupted；无事件即不渲染思考块。
4. **工具输出**：按 `tool_call_id` 聚合 `tool/output_delta`；`tool/call` 提前到达（running 态更早）；result 终态去重（§2 表）。
5. **重连**：连接异常关闭 / seq gap → `GET /stream?after_seq=lastAppliedSeq`；幂等投影按 seq。
6. **模型选择器**：`GET /api/models` → Composer 选择器；POST 带 `model`；422 显示可选列表。
