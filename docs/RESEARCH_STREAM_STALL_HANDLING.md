# 研究：模型流「停滞/缓慢」的处理方式（DeepSeek Harness vs ZCode vs 本项目）

> 2026-09-11。起因：真实 run 中主模型（`deepseek-v4-flash-0731`）约 50s 无任何输出，
> 60s 时看门狗触发、回退 `glm-4.5-air` 完成；期间 UI 只有诚实的 `思考中 · Ns` 计时，
> **没有任何「可能已停滞/即将回退」的中间态提示**。用户要求先查同类产品怎么做，再决定。
>
> 方法：dsh 以其公开仓库的源码/文档为准（引用到文件:行）；ZCode 无公开源码，
> 证据来自本机安装产物的 bundle 与字符串，**标注为「由 bundle 推断」**。

## 1. 本项目现状（对照基线）

| 机制 | 值 | 位置 |
| --- | --- | --- |
| idle 看门狗 | **60.0s** 无任何新 chunk → `ModelStallError` | `src/agent_harness/model/stall.py`、`config.py:31` |
| total 看门狗 | **600.0s** 整条流必须完成 | `config.py:32` |
| 可配 | env `MODEL_STREAM_IDLE_TIMEOUT` / `MODEL_STREAM_TOTAL_TIMEOUT`（`.env` 未覆盖，走默认） | `config.py:31-32` |
| 停滞后果 | 判为**瞬时** → 两级模型回退（不变量 #9），并发闸包在看门狗**外面**（排队不计入 idle） | `fallback.py`、`concurrency.py:9` |
| 用户可见信号 | 停滞**期间**：无（只有 Run Pulse 的实时秒数）；停滞**之后**：`model/fallback` 事件（Inspector 明细行 + 模型卡「已切换」态） | `StepDetail.tsx:417`、`types.ts:335` |
| 首 token 计入 idle | 是（idle 统计「任何 chunk 都没有」） | `stall.py` 模块 docstring |

## 2. DeepSeek Harness（dsh）

**有 idle 看门狗，没有 total 时限。**

- 实现：`idleWatchdog()`（`packages/util/timeout/src/index.ts`）——**只在有一个 `next()` 未决时计时**，
  超时映射为 `TIMEOUT`；错误码 `LLM_STREAM_IDLE_TIMEOUT`。其 README 的 Known Limitations 明写
  **"An idle watchdog is not a total deadline."**
- **默认 300,000 ms = 5 分钟**：`DEFAULT_STREAM_IDLE_TIMEOUT_MS = 300_000`
  （`packages/llm/llm-deepseek/src/adapter.ts:145`）；`docs/subsystems/llm-streaming.md`（~L296）：
  "Both shipping remote adapters expose positive finite `streamIdleTimeoutMs` with a five-minute default."
- 配置键 **`streamIdleTimeoutMs`**（per 连接 / per 模型 profile），经 `cordis.yml`；**未发现对应的 env 变量**。
- **没有独立的首 token 超时**——首 token 就是第一个未决 `next()`，与其它 chunk 同一间隔。
- **失败前没有任何事件或 UI 信号**：重试事件 `llm/retry` / `llm/retry-started` 是 durable 但
  **non-surface**（`packages/llm/llm-retry/README.md:58,115`："Nothing here is model-visible"）。
  没有 heartbeat，也没有 stall 警告事件。最接近的是 `generationReadyWarnMs`（默认 3000），
  但它警告的是**连接握手慢**，不是模型出流慢。
- 重试：省略 `retryPolicy` 即 normal 模式，对 `EMPTY_RESPONSE/RATE_LIMIT/SERVER/TIMEOUT/TRANSPORT`
  **重试 5 次**，退避 **500 ms → 10 s、10% 抖动**；看门狗 `TIMEOUT` 属可重试。
  **⚠ dsh 没有模型回退机制**——重试打的是同一条路由（"One adapter call is one provider attempt"）。

## 3. ZCode（本会话所在的 CLI）

以下均由 `D:\DevTools\ZCode\resources\glm\zcode.cjs`（Electron `resources\app.asar`）**bundle 推断**。

- **有自己的停滞看门狗**：`ModelStreamIdleTimeoutError`，码 `MODEL_STREAM_IDLE_TIMEOUT`，
  消息 `Model stream stalled: no event received for ${timeoutMs}ms.`，且**判为可重试**
  （`reason: StreamIdleTimeout, retryable: true`）。
- **默认 600,000 ms = 10 分钟**：常量 `XT=6e5`，默认对象 `Va={... modelStream:{idleTimeoutMs:XT} ...}`；
  store 键 **`modelStream.idleTimeoutMs`**。另有一个 `3e4`（30 s）常量位于
  `resolveModelStreamIdleTimeoutMs` 附近，该函数会**按重试次数缩放** idle 超时。
- **中途信号：只有停滞之后，停滞期间没有。** 未找到任何 warn 阈值（检索
  `stallWarn/slowStream/warnMs/slowThreshold` 均无）。恢复开始时
  `streamRecovery.updated` / `api_retry` 会送到 UI：`chat.apiRetryStatus` =
  `"Reconnecting... {attempt}/{maxRetries}"` / `"重新连接中... {attempt}/{maxRetries}"`
  （由 `session_info_update.apiRetry` 驱动）。遥测状态 `model_stream_stalled` 映射到
  devtools 的 `developerTools.network.status.stalled` = "Stream stalled"/"流式响应停滞"。
- 重试：`streamRecoveryRetryCount` 递增、上界 `retry.maxAttempts`；通用 AI-SDK 默认
  `maxRetries=2, initialDelayInMs=2000, backoffFactor=2`。

## 4. 三方对照

| 维度 | 本项目 | dsh | ZCode |
| --- | --- | --- | --- |
| idle 看门狗 | ✅ 60s | ✅ 300s（5 min） | ✅ 600s（10 min） |
| total 时限 | ✅ 600s | ❌ 明确不做 | 未发现 |
| 可配 | ✅ env（两项） | ✅ `streamIdleTimeoutMs`（无 env） | ✅ `modelStream.idleTimeoutMs`（store 键） |
| 首 token 单独超时 | ❌（计入 idle） | ❌（同一间隔） | ❌ |
| 停滞**期间**的用户信号 | ❌ | ❌ | ❌ |
| 停滞**之后**的信号 | `model/fallback` 事件 | 重试事件（non-surface，用户看不到） | `Reconnecting… attempt/max` + 遥测 stalled 状态 |
| 模型回退 | ✅ 两级 | **❌ 无（重试同路由）** | 未发现（重试 + 恢复） |

## 5. 结论（对决策的直接含义）

1. **「阈值偏长」这个说法被证据否决。** 两个参考实现的 idle 阈值分别是我们的 **5×**（dsh 300s）
   和 **10×**（ZCode 600s）。我们的 60s 已经是三者中最激进的；再调低会把**合法的长首 token 推理**
   误判为停滞（三者的 idle 都把首 token 计入），代价是用可靠性换观感。→ **不动默认值**，
   只把它作为已文档化的旋钮。

2. **「停滞期间的中间态提示」两个参考实现都没有。** dsh 的相关事件刻意 non-surface；
   ZCode 只在**超时之后**显示 "Reconnecting… attempt/max"。所以这不是「抄现成」，
   而是**一个新产品特性**——必须走产品决策，不能以「对齐参考实现」为理由引入。
   若要做，**最省的形态是纯前端本地观察提示**（前端已知「流已开始」与「有没有收到新帧」），
   **不新增 SessionEvent**：不变量 #4 明确 "Event ≠ Diagnostic Log"，而两个参考实现也都把
   「等待/重连」放在**事件流之外**（遥测/瞬时 UI 状态）——这条印证了不变量 #4 的取向。

3. **值得借鉴的一处**：ZCode 的 `resolveModelStreamIdleTimeoutMs` **按重试次数缩放** idle 超时
   （首次给足时间、重试时收紧）。我们的 total 看门狗已经能治慢滴漏，但 idle 是固定 60s；
   若将来发现「首次调用正常慢、重试仍慢」的模式，这是可参考的取舍。

## 6. 未能确定

- dsh：「失败前无信号」是从文档/源码/代码搜索得到的**自信否定**，但未实测其运行时 UI。
- ZCode：生产环境的 `streamRecovery.maxAttempts` 具体值（随配置）；`modelStream.idleTimeoutMs`
  是否在 GUI 设置里暴露（只找到 store 键）。bundle 中的 `3001ms/3000ms` 是测试夹具，非默认值。
