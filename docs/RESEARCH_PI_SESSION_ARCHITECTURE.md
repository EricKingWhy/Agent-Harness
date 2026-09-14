# Pi / oh-my-pi / DeepSeek Harness Session 架构调研

> 调研性质：只读源码与文档调研；本次未修改产品源码。报告写入路径：`D:\intelligence-agent\docs\RESEARCH_PI_SESSION_ARCHITECTURE.md`。
>
> 日期：2026-09-07

## 1. 结论摘要

当前仓库并不是“没有多轮 Session 能力”，而是 **CLI demo 与 Web API 都把“发送一条消息”建模成“创建一个新 Session 并启动一次 run”**。底层已经具备同一 Session 追加多轮消息、从历史投影上下文、压缩、恢复、JSONL 持久化、工具审批和 SSE 断线重放等能力；缺口位于入口层：没有“向已有 `session_id` 追加一条用户消息并启动新 run”的 Web API，前端也没有调用该类 API。

直接根因：

1. CLI demo 交互循环在每次输入时执行 `_new_session(store_root)`。
2. Web 前端 `submitTask()` 总是调用 `startSession(payload)`，即 `POST /api/sessions`。
3. Web 后端 `POST /api/sessions` 每次生成 `uuid4()`，随后 `Session.start(...)`，所以每条消息必然获得新的 session_id。
4. 当前 Web API 只有“创建新 Session + 跑任务”，没有 `POST /api/sessions/{session_id}/messages`、`/prompt` 或等价的续聊端点。

底层可复用路径是：加载/恢复指定 Session → 调用已有 `AgentRuntime.run(session, user_input)` 或 `run_stream`。`AgentRuntime` 会把新的 `USER_MESSAGE` 追加到同一 Session，再由 `ContextBuilder` 通过 `Session.derive_messages()` 将历史投影为模型上下文。

## 2. Primary sources 是否存在

### 2.1 本机已存在的源码

本次在临时目录发现以下本地 primary-source 快照：

- `C:\Users\王浩宇\AppData\Local\Temp\oh-my-pi`：oh-my-pi 源码树（Rust/TypeScript/Bazel 等）。
- `C:\Users\王浩宇\AppData\Local\Temp\pi`：从 pi 相关源码抽取的 session、agent loop、compaction 文件。
- `C:\Users\王浩宇\AppData\Local\Temp\pi-mono`：完整 pi monorepo；`git remote` 为 `https://github.com/earendil-works/pi.git`。
- `C:\Users\王浩宇\AppData\Local\Temp\pi-mono-research`：另一份 pi-mono 研究快照。

未发现本机 `deepseek-harness` 源码目录；本报告对 DeepSeek Harness 采用官方 GitHub primary source：

- https://github.com/deepseek-ai/deepseek-harness

Pi 官方源码/文档链接（本地文档也直接给出）：

- https://github.com/earendil-works/pi-mono
- https://github.com/earendil-works/pi-mono/blob/main/packages/coding-agent/src/core/session-manager.ts
- https://github.com/earendil-works/pi-mono/blob/main/packages/coding-agent/src/core/compaction/compaction.ts
- https://github.com/earendil-works/pi-mono/blob/main/packages/coding-agent/src/core/compaction/branch-summarization.ts

## 3. 当前仓库：为什么每条消息都是新 Session

### 3.1 CLI demo

文件：`D:\intelligence-agent\demo\live_agent.py`

- 第 162-165 行：`_new_session()` 创建 `JsonlSessionStore` 并调用 `Session.start(store)`。
- 第 324-327 行：单次 `--task` 模式创建一个新 Session。
- 第 329-345 行：交互模式在 `while True` 中读取每条输入；第 342-343 行的注释明确写着“每次任务起一个新 session”，并在循环体内执行：

```python
session = _new_session(store_root)
await _run_task(runtime, session, task, store_root, session.session_id)
```

因此 demo 的行为是设计选择，不是 Session 层自动切断多轮。

### 3.2 Web 后端

文件：`D:\intelligence-agent\src\agent_harness\web\app.py`

- 第 511-548 行：提供 Session 列表和事件读取。
- 第 654-710 行：`POST /api/sessions` 的处理函数，文档字符串就是“起新 session + 跑任务”。
- 第 672 行：`session_id = str(uuid4())`。
- 第 688-693 行：调用 runtime factory，然后第 693 行 `Session.start(state.store, session_id=session_id)`。
- 第 697 行：`state.run_manager.launch(session, runtime, req.task)`。
- 第 716-776 行：`GET /api/sessions/{session_id}/stream` 只负责读取既有事件并订阅在途 run，不负责追加下一条 user message。
- 第 778-817 行：已有 Session 的 cancel/recover 端点，但没有已有 Session 的 prompt/continue 端点。

这形成了当前 API 的单向生命周期：

```text
POST /api/sessions
  -> uuid4()
  -> Session.start()
  -> launch(session, task)
  -> SSE
```

而不是：

```text
POST /api/sessions/{id}/messages
  -> Session.resume(id)
  -> runtime.run_stream(session, new_user_input)
  -> SSE / existing stream
```

### 3.3 Web 前端

文件：`D:\intelligence-agent\web\src\hooks\useSession.ts`

- 第 363-368 行注释明确写着：`Submit a new task. Creates a fresh session and streams the response.`
- 第 369-382 行：`submitTask()` 重置当前 conversation/mode，然后调用 `startSession(payload)`。
- 第 380 行：mode 设置为 `{ kind: 'live', sessionId: null }`，等待新 Session 的首个 SSE 帧返回 session_id。
- 第 382 行：调用 `startSession(payload)`，而不是带当前 `selectedId` 的续聊请求。
- 第 409 行：run 结束后切换到新返回的 session_id 的 viewing 状态。

文件：`D:\intelligence-agent\web\src\lib\api.ts`

- 第 60-77 行：`StartSessionPayload` 与 `startSession()`，固定 POST `/api/sessions`。
- 第 80-88 行：`streamSession(sessionId, afterSeq)` 仅用于已有在途 run 的 SSE 续传/重放。
- 第 137-151 行：已有 cancel API。
- 第 153-179 行：已有 recover API。
- 没有 `continueSession`、`sendMessage(sessionId, ...)` 或同等客户端函数。

所以前端的会话列表/历史查看/流重连是存在的，但“在当前会话继续发言”没有传输层入口。

## 4. 当前底层 Session 与上下文能力

### 4.1 Session 是 append-only durable aggregate

文件：`D:\intelligence-agent\src\agent_harness\session\session.py`

- 第 50-70 行：Session 持有 `session_id`、内存事件列表、JSONL store 与 listener。
- 第 112-135 行：`Session.start()` 生成/接受 session_id，追加 `SESSION_STARTED`。
- 第 137-187 行：`Session.resume()` 从 JSONL 读取事件、校验 seq、修复 dangling tool call，并追加 `SESSION_RESUMED`。
- 第 191-243 行：`append()` 分配递增 seq，先写 durable store，再更新内存并通知 listener。
- 第 267-269 行：`derive_messages()` 从完整事件序列投影模型可见消息。
- 第 273-277 行：`begin_run()` 只创建一个 run_id 并追加 run/started；Run 与 Session 是两个层次。

这说明“Session 生命周期”和“一次 run 生命周期”在当前设计中已经分离：一个 Session 理论上可以包含多个 run；入口层目前只是每次都选择创建新的 Session。

### 4.2 短期上下文注入

文件：`D:\intelligence-agent\src\agent_harness\session\derive.py`

- 第 74-101 行：将 `user/message` 投影为 `HumanMessage`，`model/completed` 投影为 `AIMessage`，`tool/result` 投影为 `ToolMessage`。
- 第 103-139 行：为未配对 tool call 注入合成 ToolMessage，避免恢复后的 provider 消息序列非法。

文件：`D:\intelligence-agent\src\agent_harness\context\builder.py`

- 第 56-78 行：`ContextBuilder.build(session)` 每次从 Session 全部事件投影消息；低于预算时直接返回，超过阈值时调用 compactor。
- 第 64-70 行：默认 auto compact threshold 为最大上下文的 70%，hard guard 为 85%。
- 第 112-133 行：可选 ContextProvider 在剩余预算内选择附加消息，并插入 system message 之后。
- 第 49-52 行：token memo 以 `(session_id, seq)` 为键，说明 builder 按 Session 累积历史工作。

文件：`D:\intelligence-agent\src\agent_harness\agent\runtime.py`

- 第 337-351 行：`run()` 与 `run_stream()` 接收显式 Session。
- 第 430-436 行：一次 run 先追加 `USER_MESSAGE`，再 `begin_run()`。
- 第 464-471 行：每个 agent step 通过 `ContextBuilder` 构建模型可见上下文。
- 第 695-723 行：正常/失败终态均写入 Session，并执行 memory writeback。

因此，若同一个 Session 被重复传给 `runtime.run_stream(session, input)`，旧的 user/assistant/tool 轮次会自然进入下一轮上下文；并不需要另造第二套 history。

### 4.3 Compaction/summarization

文件：`D:\intelligence-agent\src\agent_harness\context\compactor.py`

- 第 43-55 行：配置最大上下文、自动压缩阈值、硬保护阈值和摘要超时。
- 第 57-107 行：保留 system prefix 与最近 turn；把早期消息序列化后交给 LLM 摘要；失败时使用机械摘要 fallback；超出 hard guard 则抛 `ContextWindowExceededError`。
- 第 163-181 行：校验 AI tool-call 与 ToolMessage 的完整配对，禁止孤立 tool result。

当前实现的 compaction 结果以 `CONTEXT_COMPACTED` durable event 记录元数据，但与 pi 的 `retainedTail` 自包含 checkpoint 相比，当前报告未发现同等的树节点级 retained-tail 数据模型。

## 5. Pi / pi-mono 的架构要点

### 5.1 多轮 CLI 生命周期

本地 primary source：

- `C:\Users\王浩宇\AppData\Local\Temp\pi-mono\packages\coding-agent\docs\sessions.md`
- `C:\Users\王浩宇\AppData\Local\Temp\pi-mono\packages\coding-agent\src\core\agent-session.ts`

`sessions.md`：

- 第 3-7 行：Pi 将对话保存为 Session，可继续工作；默认保存到 `~/.pi/agent/sessions/`，JSONL 文件带树结构。
- 第 9-16 行：`pi -c` 继续最近会话，`pi -r` 选择历史会话，`--session` 指定会话，`--fork` fork 会话。
- 第 22-35 行：`/resume`、`/new`、`/tree`、`/fork`、`/clone`、`/compact` 等命令显式区分“继续、建新、分支、压缩”。

核心差异：Pi 的交互进程通常持有一个 `AgentSession`，用户每次 prompt 都在该对象和同一 `SessionManager` 上追加消息；“新 Session”是显式操作，而不是每次 prompt 的默认动作。

`agent-session.ts`：

- 第 1-13 行：`AgentSession` 统一封装 agent state、事件订阅、session persistence、模型切换、compaction、session switching/branching。
- 第 310-404 行：`AgentSession` 持有一个 `SessionManager`，订阅 agent 事件并自动持久化。
- 第 1105-1117 行：`_runAgentPrompt()` 调用同一个 agent 的 `prompt()`，完成后处理 retry/compaction/queued continuation。
- 第 1150-1317 行：`prompt()` 在非 streaming 时创建当前 user message，调用 agent；如果 streaming，则通过 `steer` 或 `followUp` 入队，而不是强制创建新 Session。
- 第 1542-1580 行：`sendUserMessage()` 始终触发一次 turn；streaming 时可选择 `steer` 或 `followUp`。

### 5.2 Session tree/branch

本地文档：`...\packages\coding-agent\docs\sessions.md` 第 69-127 行；格式文档 `...\docs\session-format.md` 第 1-3、174-185、306-342 行。

- 每个 entry 有 `id` 与 `parentId`；当前 leaf 表示 active position。
- `/tree` 在同一 JSONL 文件内移动 leaf，允许从历史点继续并产生新 child branch。
- `/fork` 与 `/clone` 才创建新的 session file。
- `SessionManager` API（`session-format.md` 第 386-439 行）区分 `continueRecent`、`open`、`forkFrom`、`branch`、`buildContextEntries` 和 `buildSessionContext`。

这比当前 repo 的线性 seq SessionEvent 更接近“同一会话中的可审计分支树”。当前 repo 已有 `session/fork.py`、`session/lineage.py`，但 Web composer 没有把 branch/continue 入口接起来。

### 5.3 短期上下文与 compaction

本地文档：`...\packages\coding-agent\docs\session-format.md` 第 320-342 行、`...\docs\compaction.md` 第 25-81 行。

Pi 的 context 构建流程：

1. 从当前 leaf 沿 parentId 回溯得到 active path。
2. 遇到 compaction entry 时，用 summary 加 retained tail/kept boundary 重建可见上下文。
3. 将 message、compaction、branch summary、custom message 转为 LLM messages；普通 custom state 不进上下文。

自动 compaction：

- 在上下文超过 `contextWindow - reserveTokens` 时触发；默认 reserve 16384 tokens。
- 多轮 agent run 中，在 tool result 写入后、下一次 assistant response 前检查。
- 默认保留最近约 20k tokens；在 turn 边界压缩，tool result 不被单独切断。
- overflow recovery 可在压缩后重试被中断的 turn。

分支摘要：切换 `/tree` 分支时，可对被放弃分支生成 `branch_summary`，在新路径继续时保留重要上下文。

### 5.4 跨 provider/model

本地 `agent-session.ts`：

- 第 1652-1677 行：`setModel()` 校验 provider auth，把 `model_change` 写进 session transcript，并更新 thinking level。
- 第 1700-1780 行：`cycleModel()` 可在 scoped models 或全部可用 models 中切换；切换同样写入 `model_change`。
- `session-format.md` 第 213-219 行：`model_change` entry 记录 provider/modelId。

这表示同一 Session 可以跨 provider/model 延续，模型选择是 session transcript 的一部分，不必拆成新会话。当前 repo 的 `POST /api/sessions` 支持创建时选择 model，但没有“当前 Session 中途切换模型并记录变更”的 Web 续聊接口。

### 5.5 Tool approval

Pi 的 tool hooks 位于本地 `...\packages\coding-agent\src\core\agent-session.ts` 第 478-539 行：`beforeToolCall` 可阻止/批准调用，`afterToolCall` 统一处理结果、错误、details 与图片归一化。交互层的审批/项目可信度相关代码位于：

- `...\packages\coding-agent\src\cli\project-trust.ts`
- `...\packages\coding-agent\src\modes\interactive\interactive-mode.ts`

当前 repo 的统一 ToolExecutor/approval 边界更明确：`demo/live_agent.py` 第 139-159 行定义 auto/ask approval callback，第 319-320 行选择 `WORKSPACE_WRITE`，`--yolo` 才切到 `DANGER_FULL_ACCESS`。这是符合“权限在 runtime，而非 prompt”的设计；但 Web 的 `postApproval` 客户端存在（`web/src/lib/api.ts` 第 90-98 行），后端 app.py 当前路由检索显示主要生命周期接口仍以 create/cancel/recover 为主，续聊状态机尚未形成完整闭环。

### 5.6 Recovery/replay

当前 repo：

- `Session.resume()` 会校验 seq 并修复 dangling tool call（`src/agent_harness/session/session.py` 第 137-187 行）。
- Web `GET /stream?after_seq=` 通过 durable seq 重放并与 live stream 去重（`src/agent_harness/web/runmanager.py` 第 81-123 行、第 204-221 行）。
- RunManager 将 run 与 HTTP/SSE 请求解耦：断开 SSE 默认只是 unsubscribe，run 继续到终态；孤儿宽限后才取消（`runmanager.py` 第 1-18 行）。
- 前端重连状态机位于 `web/src/hooks/useSession.ts` 第 95-141、477-601 行。

Pi：

- JSONL 是 durable session transcript，加载时可从 active leaf 重建 context。
- `/resume`、`--session`、`continueRecent` 用于继续既有 transcript。
- compaction entry/branch summary entry 让 replay 不必盲目重放全部早期内容。

DeepSeek Harness 官方源码/文档应重点核对其 agent loop、session/replay、tool approval 与 checkpoint 实现；本机没有该仓库快照，因此不把未现场验证的细节写成确定结论。官方入口：https://github.com/deepseek-ai/deepseek-harness 。

## 6. Web 多轮续聊 API 对照

### 当前 repo

当前接口集合体现的是：创建、列表、读事件、SSE 流、取消、恢复。核心缺少：

```text
POST /api/sessions/{session_id}/messages
或
POST /api/sessions/{session_id}/runs
```

该接口至少需要：

1. 校验 session_id 与权限。
2. 读取/恢复既有 Session（不能生成新 uuid）。
3. 确认没有冲突的 active run，或显式支持 steer/follow-up 语义。
4. 将新 user input 交给同一个 `AgentRuntime` 与 Session。
5. 复用现有 RunManager/SSE/after_seq 机制。
6. 让前端在当前 selectedId 下继续，不重置为 `live(null)`。

### Pi 的可借鉴形态

Pi 将“Session 选择”和“Prompt/turn”分离：

```text
open/continue SessionManager
  -> AgentSession.prompt(user message)
  -> Agent core run
  -> SessionManager.appendMessage()
```

同时支持 streaming 时的 `steer`/`followUp`，这比把每条输入都变成独立 HTTP create request 更适合多轮交互。

## 7. 最小修复方向（仅研究建议，未修改代码）

不建议重写 Session/Event/Runtime。最小架构路径是：

1. 保留现有 `Session`, `Session.resume`, `AgentRuntime.run_stream`, `ContextBuilder`, `RunManager`。
2. 增加一个“已有 Session 发送消息”的 Web contract，复用同一 SSE 事件格式。
3. 该 handler 通过 `Session.resume(state.store, session_id, workspace_registry=...)` 或等价的已加载 Session 获取 durable history。
4. 对 idle session 调用 `run_manager.launch(existing_session, runtime, req.task)`；运行中则明确拒绝、steer 或 follow-up，不能静默并发写同一 Session。
5. 前端 `submitTask` 根据是否有 selectedId 分派 create-new 与 continue-existing；不要再无条件清空 conversation/selectedId。
6. 继续使用 durable event stream 作为唯一事实源；历史读取、live SSE、reconnect、recover 均复用现有 reducer/投影。
7. 若需要 branch，应优先接入已有 `fork.py`/`lineage.py`，而不是复制一套前端 conversation history。

## 8. 关键引用索引

### 当前 repo

- `D:\intelligence-agent\demo\live_agent.py:162-165,324-345`
- `D:\intelligence-agent\src\agent_harness\web\app.py:511-548,654-776`
- `D:\intelligence-agent\src\agent_harness\web\runmanager.py:1-18,81-123,186-221`
- `D:\intelligence-agent\src\agent_harness\session\session.py:112-187,191-243,267-277`
- `D:\intelligence-agent\src\agent_harness\session\derive.py:74-139`
- `D:\intelligence-agent\src\agent_harness\context\builder.py:56-78,112-133`
- `D:\intelligence-agent\src\agent_harness\context\compactor.py:43-107,163-181`
- `D:\intelligence-agent\src\agent_harness\agent\runtime.py:337-351,430-471`
- `D:\intelligence-agent\web\src\hooks\useSession.ts:363-382,403-410`
- `D:\intelligence-agent\web\src\lib\api.ts:60-88`

### Pi / pi-mono 本地 primary source

- `C:\Users\王浩宇\AppData\Local\Temp\pi-mono\packages\coding-agent\docs\sessions.md:3-35,69-139`
- `C:\Users\王浩宇\AppData\Local\Temp\pi-mono\packages\coding-agent\docs\session-format.md:1-3,19-37,174-185,229-342,386-439`
- `C:\Users\王浩宇\AppData\Local\Temp\pi-mono\packages\coding-agent\docs\compaction.md:25-81,150-215`
- `C:\Users\王浩宇\AppData\Local\Temp\pi-mono\packages\coding-agent\src\core\agent-session.ts:1-13,310-404,478-539,1105-1317,1542-1580,1652-1780`

### 官方 URL

- Pi monorepo: https://github.com/earendil-works/pi
- Pi session docs: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sessions.md
- Pi session format: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/session-format.md
- Pi compaction: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/compaction.md
- DeepSeek Harness: https://github.com/deepseek-ai/deepseek-harness
