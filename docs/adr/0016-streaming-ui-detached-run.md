# ADR-0016: Streaming UI 生产级改造——detached-run / 取消语义修订 / delta 落盘 / reasoning 与工具输出流

- 状态：Accepted（用户在前端侧 prompt 中逐项拍板 D-A/D-B/D-C/D-D；后端侧数值与细节由本 ADR 落定）
- 日期：2026-09-06
- 关联：PRD `01_AGENT_RUNTIME_STREAMING_UI_PRD_v2.md`（冻结决策 D1-D20/S1-S26）/ 协议规格 `02_RUNTIME_STREAMING_PROTOCOL_SPEC.md` / 前端实现规格 `03_FRONTEND_STREAMING_UI_IMPLEMENTATION_SPEC.md`（§21 后端所有权）/ 前端消费契约 `docs/BACKEND_PROMPT_STREAMING_UI.md`（C1-C7）/ ADR-0014（fallback 链不动）/ ADR-0015（delegation 语义不动）/ 不变量 #4 #7 #8 #22
- 上游边界（规格 01 §21 重申）：本轮**不触碰** Agent 决策语义 / 工具选择语义 / 授权行为 / 模型路由意图（fallback 链策略原样）。生命周期托管（run 与 HTTP 请求解耦）≠ 决策语义，这条边界是 D-A 的合法性依据。

## 1. 审计结论（规格 → 现状 → Gap）

| # | 规格要求 | 当前实现 | Gap |
|---|---|---|---|
| G1 | reasoning 真流式（S1-S9，02 §7.3/§8.1） | `runtime._drive` 流式逐 chunk 只取 `chunk.content` 文本；Qwen/DeepSeek 思考内容（`reasoning_content`）被丢弃 | 无 reasoning 事件族；无 block 标识；无 source 语义 |
| G2 | reasoning_content 接出（D-B①） | langchain-openai 1.5.0 基类 `_convert_delta_to_message_chunk` **静默丢弃** delta 里的 `reasoning_content`（基类 docstring 明示第三方字段需 provider 子类） | 需要 provider 子类把 `reasoning_content` 抬进 `additional_kwargs` |
| G3 | tool 输出真流式（S14，02 §7.5） | sandbox 全量捕获（2M cap）→ 一次返回；executor 只发 `tool/call` + `tool/result`；且 `tool/call` 在**执行完成后**才落盘 | 无 `tool/output_delta`；live 视角工具执行期间不可见；call/result 时序与 02 §8.3 状态机不符 |
| G4 | detached-run + 显式取消（D-A） | run 生命周期 = SSE 请求生命周期（EventSourceResponse 消费 `run_stream`）；断连 → 取消臂 `run/failed(reason=cancelled)`（Phase 9/R5-8 刻意硬化，tests/test_sse_disconnect.py 钉住） | 无 detached 语义；无 `POST /cancel`；Esc 中断借道断连 |
| G5 | 重连续传（02 §10.2，场景 E） | SSE 一次性流；重放只有 `GET /events` 全量；无 `after_seq` | 无 cursor 续传端点 |
| G6 | S18/S19 持久化粒度 | `model/delta` 为 stream-only 不落盘；断连窗口内的文本/思考在重连时无法恢复 | delta 类内容需以合帧（coalesced）形式持久化为 durable 事实 |
| G7 | 多模型（D-B②③） | `ModelConfig.from_settings` 单链；无会话级模型选择；无模型列表端点 | 需 catalog + `model` 参数 + `GET /api/models` |
| G8 | transport 决策收口（02 §4.5，D-D） | SSE（sse-starlette）+ canonical envelope 已满足 preserve-first | 需 ADR 对照表正式收口（本文 §6） |

已满足、不动：seq 每 session 单调（Session.append 增量计数 + resume 严格校验）、SSE 帧带 seq、JSONL fsync append-only、Recovery/Ledger 体系、delegation 白盒事件、心跳（sse-starlette 默认 ping）。

## 2. 决策一：detached-run（D-A）

### 2.1 生命周期解耦

- `POST /api/sessions` 仍是唯一入口，但 handler 改为：装配 → `Session.start` → **`asyncio.create_task` 驱动 `run_stream`（detached）** → 返回 EventSourceResponse 订阅该 run 的事件广播。
- 断连（EventSourceResponse 取消 SSE generator）只做 `unsubscribe`，**不再取消 run**。这是对 Phase 9 取消臂语义的有意修订（原语义保留在 `run_stream` 层：消费者 aclose 仍触发取消收尾，web 层不再利用它）。
- 广播层（web 新增 `RunManager`）：
  - 每 session 至多一个在途 run（重复 POST 同一 session 不可能——session_id 服务端生成）。
  - subscriber = 有界 `asyncio.Queue`（上限 2000 帧）；满时**丢最旧保最新**（seq gap 让客户端检测并走 after_seq 重连自愈，02 §16.3；实现评审修订：原"移除 subscriber"方案会让断连重连路径复杂化，丢旧在语义上等价且自愈性更好）。run 侧 `put_nowait`，**慢客户端永不阻塞 Agent Loop**（02 §13.1）。
  - 事件合并去重：subscriber 队列按 seq 幂等合并——`seq is None`（stream-only）总是入队；durable 事件仅当 `seq > 已入队最大 seq` 才入队。durable 事实的唯一来源是 `Session.append`，因此挂一个 session 级 listener 即可实时捕获执行期间追加的一切事件（含 tool 输出 delta），与 `_drive` 的镜像 yield 天然汇流不重复。
  - run task 结束 → 向所有 subscriber 发 sentinel，SSE 流正常收尾（终态帧已先行）。
- **孤儿回收**：零 subscriber 连续 `run_disconnect_grace_seconds`（默认 300s，Settings 可覆盖）→ run task 被 cancel，取消臂正常收尾，`run/failed(reason=orphaned)`。有 subscriber 期间不计时；run 自然完成则无事发生。max_steps/tool timeout/流看门狗继续兜底长 run，不另设总寿限。
- `memory_session_var` 从 SSE generator 移到 run task 内绑定（信任边界不变：session id 仍是服务端事实）。

### 2.2 显式取消端点（C3）

- `POST /api/sessions/{session_id}/cancel`：
  - 有在途 run → `task.cancel()`（既有取消臂收尾：drain fallback 事实、`model/failed`、`run/failed(reason=cancelled)`），返回 200 `{"status": "cancelling"}`；
  - 无在途 run（已完成/从未运行）→ 200 `{"status": "no_active_run"}`（幂等成功——前端 Esc 与「run 恰好刚终结」的竞态是常态而非错误）；
  - session 不存在 → 404。
  - 取消与失败不混淆（02 §17）：`reason=cancelled` vs `reason=orphaned` vs 异常臂（无 reason）。
- 断连宽限期内的 run 只能靠显式 cancel 终止——**取消只发生在显式 `POST /cancel` 或孤儿回收**（场景 E 验收语义）。

### 2.3 重连续传（C4/C5）

- `GET /api/sessions/{id}/stream?after_seq=N`（N 默认 -1 = 从头）：
  1. session 无事件 → 404；
  2. 重放 durable 事件（seq > N，按 seq 序，来自 JSONL）；
  3. backlog 过大（`latest_seq - after_seq > 1000`）→ 发一帧控制事件 `stream/truncated`（无 seq，`data: {after_seq, latest_seq}`）后关闭流，客户端走 `GET /events` 全量重建后带 `after_seq=latest_seq` 重连（02 §10.4 的简化版；snapshot 层按前端 prompt 明确 DEFER）；
  4. run 在途 → 接上在途广播（幂等合并保证重放与 live 无缝、无重复）；
  5. run 已终态 → 重放到终态后正常收尾；run 不在途且未终态（进程崩溃遗留悬空 run）→ 重放完即收尾，不伪造终态（修复走既有 `/recover`）。
- 帧形状全端统一：`{type, data, seq?, run_id?, step_id?, session_id, time, event_id?, block_id?}`（重放帧来自 SessionEvent、live 帧来自 AgentEvent，同形）。
- 前端按 seq 幂等投影（C5）；后端承诺：不重置、不回跳（store 追加写 + resume 校验已保证）。

## 3. 决策二：delta 合帧落盘 + reasoning 事件族（D-B / C1）

### 3.1 词汇扩展（session/event.py 单一真相源 + gen_event_types.py 再生成）

> **协作约束（2026-09-06 补记）**：Phase 14（Resume/Replay/Fork）在独立 worktree `D:\intelligence-agent-phase14`（feat/phase14）并行开发，ADR 编号分账为 0016（本流式改造）/ 0017（Phase 14）；双方约定 `session/event.py` 只做加法改动。因此合帧文本增量**不改** `MODEL_DELTA` 的集合归属，而是新增 `text/delta`（同时更贴规格 02 §7.4 text 事件族命名）；`MODEL_DELTA` 词汇原样保留在 STREAM_ONLY_TYPES，运行时不再发射（legacy）。

新增 durable 类型：

| 类型 | data | 语义 |
|---|---|---|
| `reasoning/started` | `{source}` | 思考块开（模型真吐思考才有，零伪造）；块标识走 envelope `block_id` |
| `reasoning/delta` | `{delta, source}` | 合帧后的思考增量 |
| `reasoning/completed` | `{}` | 思考块正常收（文本转正 / 流结束 / 工具转场） |
| `reasoning/interrupted` | `{}` | 思考块异常收（取消 / 模型失败）；部分内容以已落盘 delta 保留（S18/16.4） |
| `tool/output_delta` | `{tool_call_id, channel: 'stdout'\|'stderr', delta}` | 工具输出增量（合帧，channel 保真；按 tool_call_id 聚合） |
| `text/delta` | `{delta}` | 合帧后的文本增量（替代 model/delta 成为唯一文本流通道） |

`text/delta` / `reasoning/*` / `tool/output_delta` 进 EVENT_TYPES（durable）；`model/started` 与 `model/delta` 保持 STREAM_ONLY（前者是活跃信号，重放由首个 delta 隐含——前端 4592fa2 已容忍缺失；后者不再发射）。`Session.append` 拒绝持久化 stream-only 的不变量不变（invariant #4 语义修订记录于此：合帧 chunk 属于「meaningful raw/coalesced runtime chunks」（02 §9.2），是事实不是日志）。

`text/interrupted` 不设：文本中断 = `run/failed` + 已落盘 `text/delta`（现有语义已满足 16.4，不为对称而加类型）。

### 3.2 block 标识（envelope 层）

- `SessionEvent` / `AgentEvent` / SSE 帧增加 `block_id: str | None`（02 §5 canonical envelope 的语义等价物；additive，`from_dict` 缺省 None 向后兼容）。
- reasoning 块 id = `rsn-<step>-<序号>`；文本块由既有 step/turn 语义聚合（不另设 block_id，`text/delta` 的 block_id 恒 None——前端按现有 turn 聚合文本，按 block_id 聚合 reasoning，按 tool_call_id 聚合工具输出）。
- 同一段思考的 delta 共享 block_id；post-tool 新思考段 = 新 block_id（02 §8.1 不变量）。

### 3.3 合帧器（runtime 内，S19）

- 每 run 一个 `StreamCoalescer`：文本缓冲 + 思考缓冲（+ 工具输出缓冲在 executor 侧同类机制）。
- flush 条件（先到先刷）：窗口 30ms（02 §9.1 建议区间）/ 缓冲 ≥ 4096 字符 / 生命周期边界（reasoning started/completed、model/completed、tool 转场、run 终态）/ run 取消收尾。**逐 token 行被禁止**（S19），绝不为了打字机效果扣数据（S20/02 §9.1）。
- 一条合帧 = 一次 `session.append` = 一个 durable seq = 一帧 SSE。live 帧与重放帧完全同源，客户端按 seq 幂等拼接即无缝。
- flush 无定时器：chunk 到达时惰性检查窗口到期（chunk 间隔 ≪ 30ms，检查成本可忽略），确定性无竞态。

### 3.4 reasoning 提取（D-B）

- provider 层：新增 `ReasoningChatOpenAI(ChatOpenAI)` 子类（基类 docstring 指定的正路），覆写 `_convert_chunk_to_generation_chunk`，把 `choices[0].delta.reasoning_content` 抬进 `AIMessageChunk.additional_kwargs["reasoning_content"]`。已验证 `AIMessageChunk` 聚合时 additional_kwargs 同名字符串拼接（langchain-core merge 语义），聚合 AIMessage 自带完整思考文本但不消费——model/completed.data 保持 content-only（思考不回灌上下文，D7/02 §15 隐私边界）。
- runtime 层：per-chunk 读 `additional_kwargs.get("reasoning_content")`；状态机：无块 → 思考 chunk 开新块（`reasoning/started`）；思考块 open → 累积；文本 chunk 到达 / 流结束 / 取消 / 失败 → 关块（completed / interrupted）。文本与思考同流交错按 chunk 类型切换块，各自 block_id。
- **事件驱动，零伪造**：模型不吐思考 → reasoning 事件整族不出现（无空块、无占位）；是否支持思考不按模型名硬编码（D-B③）。`source: "model"` 落 data；agent 进度叙述复用同一事件族 `source: "agent"`（本轮无生产者，词汇预留）。emitted 即 user-visible（`visibility=internal` 的内容在本协议里根本不会产生事件，02 §15 硬边界在发射侧成立）。

### 3.5 取消/失败臂的块收尾

- 取消臂（sync、不 yield）：flush 残余缓冲（部分内容落盘）→ 有 open 思考块则 `reasoning/interrupted` → 既有 model/failed + run/failed 收尾不变。
- 异常臂：同上（interrupted 先于 model/failed），flush 失败只落日志不掩盖原异常。

## 4. 决策三：工具输出流 + tool/call 预持久化（C2）

### 4.1 tool/call 预持久化

- 时序改为 02 §8.3 状态机：`tool/call`（执行前落盘）→ 执行（期间 `tool/output_delta*`）→ 延迟事件（artifact/created、delegation）→ `tool/result`（终态全量）。
- `ToolExecutor.emit_call_events`（plural）拆为 `emit_call_event`（单条，执行前）与 `emit_pending_events`（延迟事件，执行后 result 前）；`_flush_committed_events` 不再补 TOOL_CALL（已预持久化，防重复），只补延迟事件——R6-7 顺序不变量由同一 owner 继续持有。
- 崩溃窗口语义不变或更优：中断后留下「tool/call 无 result」→ 既有 dangling 合成 + Ledger-first 回填按原语义处理（Kill 测试族回归验证）。

### 4.2 输出流通道

- `Sandbox.exec` 增加可选 `on_output(channel, text)` 回调（threading 上下文调用；LocalSubprocessSandbox 的 reader 线程逐段回调，Docker 后端同签名后补）。ABC 默认参数 = additive，不破坏既有实现。
- `ToolExecutor` 在执行期设置 `tool_output_sink` contextvar；自愿接入的工具（BashTool 首发）读取 sink 并转发给 sandbox。`Tool.execute` 签名零改动。
- sink：thread-safe 收集（线程 → `loop.call_soon_threadsafe` 入队）+ executor 内并发 drain task 逐段合帧落盘 `tool/output_delta`（窗口 30ms / 8KB 先到）。执行结束 flush + 停泵；CancelledError 路径同样收口。
- **上限**：每 channel 每 tool_call 最多流式 `tool_output_stream_max_chars = 64KB`，超出停止发射（`tool/result` 的截断/artifact 语义仍是完整真相，不变量 #15 不被旁路；2M 捕获 cap 不动）。
- 非流式工具零变化（不读 sink → 零 delta，02 §7.5「不要求每个工具都流」）。

## 5. 决策四：多模型（D-B② / C6）

- Settings 增 `agent_models`（JSON 数组）：`[{"name": ..., "provider": ..., "model_name": ..., "base_url"?: ..., "api_key"?: ..., "temperature"?: ...}]`；`api_key` 缺省回落 `MODEL_API_KEY`，`base_url` 缺省回落 provider 预设。密钥 SecretStr 待遇不变。
- `POST /api/sessions` 增可选 `model: str`（catalog 名）：未传 = 默认链（现行为逐字节不变）；命中 catalog 项 → 该项作为 primary；未知名 → 422。
- **fallback 链语义不动（ADR-0014）**：settings 配置的 fallback 模型仍是 fallback；per-model fallback 属于模型路由意图扩张，本轮不做。
- `GET /api/models`：`{"models": [{"name", "provider", "model", "default": bool}]}`，无任何密钥字段。
- 思考能力不进 catalog 元数据（D-B③ 事件驱动：真吐思考才有 reasoning 事件，不按名字预判）。

## 6. 决策五：transport 收口（D-D，02 §4.5 对照表）

| 轴 | 现有 SSE（保留） | 增强现有 SSE（= 本轮） | AI SDK data-stream 层 | 全面迁移 AI SDK |
|---|---|---|---|---|
| 首帧延迟 | 已达标（POST 直推流） | 同左 + 合帧 ≤30ms | 需重排 envelope | 需重排 envelope |
| 重连/续传 | 无（一次性流） | **after_seq cursor + 幂等合并（本轮交付）** | SDK 内置但不携带 seq/事件语义 | 同左 |
| 工具流 | 无 | tool/output_delta 通道 | part 协议可表达，但需双轨翻译 | 同左 |
| reasoning 流 | 无 | reasoning 事件族 + block_id | reasoning part 可表达，同上 | 同左 |
| Inspector 兼容 | 原生（canonical envelope 直达 Raw） | 原生保持 | 需并行维护 canonical 镜像（双真相风险，违反 #22） | 同左 |
| 重放/历史 | GET /events 全量 | + cursor 增量 | 协议不覆盖持久化 | 同左 |
| Provider 支持 | 与 transport 无关 | 同左 | JS-first 协议，Python 后端为二等公民 | 同左 |
| 复杂度 | 现状 | +RunManager/合帧器（内聚 web/runtime 层） | 双协议翻译层（canonical + data-stream） | 全前端协议重写 + 后端重排 |
| 运维风险 | 低 | 低（无新基础设施） | 中 | 高 |
| 可测性 | ASGI 层已有断连回归族 | 同左扩展 | 新增协议一致性测试面 | 大 |

结论：**保留 SSE + canonical envelope，本轮增强（after_seq / block_id / 新事件族）**。AI SDK data-stream 是 JS-first 协议，对齐它会重排 canonical envelope、与 Inspector 深度和不变量 #22 冲突——与用户拍板 D-D 一致，spike 就此收口。

## 7. 数值与配置汇总（本 ADR 落定，代码内为模块常量或 Settings）

| 参数 | 值 | 位置 |
|---|---|---|
| delta 合帧窗口 | 30ms | runtime/tooling 模块常量 |
| 合帧尺寸上限（模型 delta） | 4096 字符 | 同上 |
| 工具输出流尺寸上限（合帧 + 总量） | 8KB/帧、64KB/channel/tool_call | tooling 模块常量 |
| 重放 backlog 阈值 | 1000 durable 事件 | web 模块常量 |
| subscriber 队列上限 | 2000 帧（溢出踢出重连） | web 模块常量 |
| 孤儿宽限期 | `RUN_DISCONNECT_GRACE_SECONDS=300` | Settings |
| 多模型 catalog | `AGENT_MODELS`（JSON） | Settings |

## 8. 测试与验收映射

- 场景 C（工具输出）：sink 假工具逐段发射 → delta 序列 channel 保真 + 64KB 截断 + result 终态。
- 场景 D（中断）：取消/模型失败 → 部分思考与文本以 durable delta 保留 + reasoning/interrupted + run/failed 语义分型。
- 场景 E（重连）：断连 → run 继续 → after_seq 重放 + live 无缝无重复；取消仅经 POST /cancel；孤儿 300s 回收。
- 场景 F（历史）：重放含 reasoning/tool 输出/block 边界（S18 直接验收）。
- 既有契约回归：SSE 断连测试族改写为 detached 语义（断连 → run 完成到终态）；R6-7 事件顺序、Kill 恢复、usage 记账、fallback、delegation 全族保持绿。
