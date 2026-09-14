# 前端真后端冒烟清单（Streaming UI + Phase 15 观测）

> 用途：前端代码合入 main 后、或联调阶段，对着真后端逐项验收整条链路。
> 由前端 B（feat/frontend-B）起草。契约来源：`docs/BACKEND_CONTRACT_STREAMING_UI.md`、ADR-0016、ADR-0018。
> 这份清单不是 vitest/E2E 的替代——单测 351 + Playwright 12 覆盖的是 mock 终态矩阵；本清单覆盖的是**真后端的运行时行为**，两者互补（骨架车道已知边界见 `docs/E2E_SCENARIO_MAP.md`）。

## 怎么用

1. 后端就绪（`uv run uvicorn agent_harness.web.app:create_app --factory` 或项目既有的启动脚本）。
2. 前端 dev 起来（`cd web && pnpm dev`，5173）。
3. 按清单逐项操作，每项标 ✅ / ❌ / 跳过（原因）。失败的项记现象 + 复现步骤，反馈给前端 B 或后端 AI。

## 前置：环境核对

- [ ] `.env` 里 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_BASE_URL` 已配（冒烟 trace_id 链路要用）；不配则相关项标「Langfuse 未启用」跳过。
- [ ] `AGENT_MODELS` 配了至少两个模型（冒烟模型选择器要用；至少一个会思考的模型如 qwen3-max，一个不会思考的）。
- [ ] 后端 health 端点响应 200（`GET /api/health`）。
- [ ] 前端打开无控制台报错（404/422/5xx 都值得记）。

## 1. 文本流式（text/delta durable 承接）

契约要点：`model/delta` 不再发射；durable `text/delta` 承接文本流。

- [ ] **1.1 提交一个简单任务**（如「用一句话介绍自己」），观察回答是否**逐字流式出现**（不是一次性 dump）。
- [ ] **1.2 流式过程中刷新页面**（或关闭再打开同一会话）→ 走历史重放（`GET /api/sessions/{id}/events`）→ 回答完整呈现，无截断、无重复。
- [ ] **1.3 提交长任务**（生成几百字）→ 文本流式连贯，无明显卡顿（>3s 无帧算异常，记现象）。

## 2. Reasoning 块（零伪造边界）

契约要点：模型不吐思考 → reasoning 族不出现；吐了 → 按 block_id 聚合。

- [ ] **2.1 用会思考的模型**（如 qwen3-max）提交任务 → **看到独立的思考块**（与正文视觉区分），思考块完整、无明显乱码。
- [ ] **2.2 用不会思考的模型**提交任务 → **没有思考块出现**（零伪造：后端不发 reasoning 事件，前端不渲染块）。
- [ ] **2.3 详情面板打开思考块对应的 activity** → block_id 一致、内容完整（路径 B 重点验证区：projection.applyReasoningEvent 的 envelope block_id 聚合）。

## 3. Esc / 停止（detached-run，POST /cancel）

契约要点：断连不再取消 run；Esc/停止必须走 `POST /api/sessions/{id}/cancel`（200 cancelling / 200 no_active_run 幂等 / 404）。

- [ ] **3.1 流式过程中按 Esc**（或点 Composer 停止按钮）→ 流即时终止，UI 迁移到 viewing 态，详情面板 reason 显示 `cancelled`。
- [ ] **3.2 流式过程中关浏览器标签页**（模拟断连）→ 后端 run **不取消**（后端日志确认）；重新打开同一会话 → 若 run 已结束看到完整结果，若仍在跑看到中间态。
- [ ] **3.3 流结束后再点停止**（或对已结束会话发 POST /cancel）→ 返回 200 no_active_run（幂等，不报错）。

## 4. 重连（GET /stream?after_seq=N）

契约要点：seq gap = 重连信号；backlog>1000 收 stream/truncated 控制帧后走 GET /events 全量重建再带 after_seq=latest_seq 重连。

- [ ] **4.1 流式过程中切到后台标签**（5+ 秒）再切回 → 前端继续接收新帧，无重复、无丢帧（路径 B 重点验证区：useSession 重连状态机的 stallCheck + visibility 触发）。
- [ ] **4.2 模拟网络瞬断**（DevTools Network → Offline 3 秒 → Online）→ 出现「连接中断，正在重连」横条（800ms 阈值后才显示），重连成功后横条消失、流续接无重复。
- [ ] **4.3 重连失败 3 次**（持续断网）→ 横条消失，错误提示「连接中断：重试 3 次未成功」，UI 迁移到 viewing 态（recover 入口可能出现）。
- [ ] **4.4 流式过程中后端重启**（kill -9 后端进程再起）→ 前端检测到断流，重连，行为同 4.2/4.3 之一（视后端恢复速度）。

## 5. 模型选择器（GET /api/models）

契约要点：会话级模型选择；未知名字 422；422 后前端刷新目录并回退选择。

- [ ] **5.1 打开 Composer** → 模型选择器下拉出现真实目录（至少两项）；选一个非默认模型提交 → 任务正常完成（后端日志确认用的是选定的模型）。
- [ ] **5.2 选「默认链」提交** → 行为同不选模型（现有行为不变）。
- [ ] **5.3 手动改 AGENT_MODELS 配置后**（后端重启加载新配置）→ 前端刷新页面 → 选择器出现新目录（fetchModels 在 onTokenChange 触发）。
- [ ] **5.4 选一个不存在的模型提交**（需构造场景，如配置改了但前端缓存了旧选择）→ 后端返回 422 → 前端刷新目录 + 自动回退到「默认链」+ 不残留错误状态（路径 B 重点验证区：isUnknownModelError + setSelectedModel 回退）。

## 6. Trace 观测（Phase 15，Langfuse）

契约要点：后端 Langfuse 开启时 `run/completed.data.trace_id` = 真实 trace id（ADR-0018 D7），前端自动显示。

- [ ] **6.1 Langfuse 已配置** → 提交任务完成 → 详情面板 Trace 行显示真实 trace id（mono code，不是「未追踪」灰字）。
- [ ] **6.2 命令面板（Ctrl+K）** → 出现「Copy Trace ID」命令 → 点击复制 → 粘贴到 Langfuse 搜索框 → 跳转到对应 trace（trace_id 与 Langfuse 一致）。
- [ ] **6.3 Langfuse 未配置**（清空 LANGFUSE_PUBLIC_KEY 重启后端）→ 提交任务完成 → Trace 行显示「未追踪」灰字；命令面板不出现「Copy Trace ID」命令。
- [ ] **6.4（待 trace_url 契约落地后补）** Trace 行的 trace_id 是可点超链接 → 点击在新标签打开 Langfuse dashboard 对应 trace 页（见 `docs/BACKEND_PROMPT_TRACE_URL.md`）。

## 7. 密度四档（Compact / Balanced / Detailed / Raw）

- [ ] **7.1 命令面板切换密度** → 即时生效，视觉密度变化（折叠/展开行）。
- [ ] **7.2 刷新页面** → 密度持久化（localStorage `ahi.traceDensity`）。
- [ ] **7.3 四档各跑一次任务** → 每档渲染正确（Balanced 工具卡是折叠行 `.act-node`；Detailed 是展开卡 `.tool-card-body`）。

## 8. 历史会话列表

- [ ] **8.1 列表显示多个会话** → 每行标题是首条用户消息（截断 128 字），不是短 ID（除非首条非 user/message）。
- [ ] **8.2 点列表行切换会话** → 详情面板加载该会话内容；再切回原会话 → 内容正确无串。
- [ ] **8.3 长会话（50+ 事件）加载** → 无明显卡顿（virtualization 生效）。

## 9. 键盘可达性

- [ ] **9.1 Ctrl+K 唤起命令面板** → 焦点在面板输入框 → 输入筛选 → 上下键导航 → Enter 执行 → Esc 关闭。
- [ ] **9.2 Composer Ctrl+Enter 提交**（焦点在输入框）→ 任务发送。
- [ ] **9.3 Tab 导航** → 能从会话列表 → Composer → 详情面板，顺序合理。

## 10. 边界场景

- [ ] **10.1 提交空任务**（空字符串或纯空白）→ 后端 422，前端提示「任务不能为空」类，不卡死。
- [ ] **10.2 工具调用**（如 bash 执行 `echo hello`）→ Balanced 档看到工具折叠行（含命令名 + 参数摘要 + 状态 chip）；展开看到完整输出。
- [ ] **10.3 子会话钻取**（如果有 delegate 场景）→ 点子会话节点 → 详情面板加载子会话内容（useChildConversation），返回主会话不串。

## 路径 B 扫描结论：重点验证区

以下三个区域是路径 B 架构扫描识别出的**耦合最密 / 测试覆盖依赖纯函数**的区域，冒烟时若出问题优先查这里：

### useSession.submitTask 闭包（370-625 行）

八个闭包函数（`finishLive`/`onEvent`/`onStreamEnd`/`onStreamError`/`attach`/`scheduleReconnect`/`doTruncatedRebuild`/`stallCheck`）共享 `conv`/`gen`/`reconnectPending`/`reconnectProgressBase`。纯决策函数已抽到模块顶层且有单测（decideCancel/decideStreamEnd/isSeqGap/parseTruncated/reconnectDelayMs），但闭包内的交互只有集成路径能验。

- **冒烟重点**：§4 重连场景全部。尤其是 4.1（stallCheck + visibility）、4.2（reconnectPending 单飞守卫）、4.3（reconnectProgressBase 额度复位——悬空 run 不无限重连）。

### projection.applyEvent 的 reasoning 分支（block_id 聚合）

`applyReasoningEvent` 的 block_id 解析有三层 fallback（envelope top-level → data.block_id → lastStreaming）。envelope top-level 是 Phase 15 后端契约的关键（reasoning 族事件的 block_id 在信封顶层，不在 data）。

- **冒烟重点**：§2.3。若思考块聚合错乱（跨块串内容、同一块重复），优先查 projection.ts 的 block_id 解析链。

### App.tsx 模型 422 刷新链

`isUnknownModelError` → `fetchModels` → `setSelectedModel` 回退。纯函数有测，但整条链路（错误识别 → 目录刷新 → 选择回退 → 用户无感）只有真后端 422 能验。

- **冒烟重点**：§5.4。

## 失败项反馈模板

```
【冒烟失败】§X.Y 标题
现象：<观察到什么>
复现步骤：
  1. ...
  2. ...
预期：<清单描述的应该是什么>
实际：<观察到什么>
环境：后端 commit / 前端 commit / 浏览器
怀疑区域：<路径 B 扫描结论里的重点验证区，如有>
```
