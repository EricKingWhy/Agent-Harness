# 前端交接单：三个「点了没反应 / 滚不动」缺陷（WorkBuddy）

> 面向 `D:\intelligence-agent-frontend`（`feat/frontend`）的前端 Agent。
> 来源：用户实测报告 + `[$diagnosing-bugs]` 诊断（后端会话执行）。
> 后端侧同期修了一个 P0（见 `docs/INTEGRATION_PROMPT_REASONING_EFFORT_FIX.md`），**本单三条全是前端**，后端无需改动。

---

## 0. TL;DR

| # | 症状 | 根因位置 | 责任 |
| --- | --- | --- | --- |
| A | 点「恢复会话」没反应 | `web/src/lib/runState.ts:116` 的 `isRecoverableRun` 不认识 T8 新终态 `run/interrupted` → 按钮永久可见；且成功无反馈 | 前端 |
| B | 点「分叉」没反应 | `web/src/components/Conversation.tsx:292` 传 `turn.step_id` 当 `from_seq`（该传用户消息 `seq`）；错误被 `web/src/App.tsx:318-323` 的 `catch {}` 吞掉 | 前端 |
| C | 流式期间滑轮往下滚被顶回去，输出完才正常 | `web/src/components/Conversation.tsx:121-132` 每个 delta 重发 `scrollIntoView({behavior:'smooth'})` | 前端 |

三条都能在**不改后端**的前提下修掉。B 若要更好的 UX 可能想要一个新后端端点，见 §B.4（可选，需产品定）。

---

## A. 「恢复会话」点了没反应

### A.1 现象与实证

用户在一个崩溃过的会话里点「恢复会话」，连点了 **15 次**，界面上没有任何变化。

证据一（点击确实到达了后端）：会话 `f181c5ce-7c84-43f9-b249-efa606293268` 的事件日志里，`session/resumed` 出现在 seq `12, 13, 14, 16..27, 29`——**15 条**。`POST /recover` 每被调用一次就追加一条。

证据二（后端已经修完了）：同一日志 `seq=15 run/interrupted`（`{"interrupted_seq":11,"reason":"process_restart"}`，信封 `step_id=3`）由 web 启动期的崩溃扫描补记，随后 `RecoveryCoordinator` 已按 Operation Ledger 回填了工具结果。也就是说用户点按钮时，**该修的都已经修完了**，`POST /recover` 是一次真正的 no-op：返回 200 + 与点击前**逐字相同**的投影。

证据三（按钮为什么还在）：`web/src/lib/runState.ts:116-150`

```ts
case 'run/completed':
case 'run/failed':
  lastRunTerminated = true;
  break;
```

`isRecoverableRun` 的终态集合里**没有 `run/interrupted`**。于是崩溃会话被修好之后 `lastRunTerminated` 仍是 `false` → `App.tsx:358` 的 `canRecover` 恒真 → 「恢复会话」按钮**永不消失**、提示条恒显示「最后事件非 run/completed——可尝试恢复」。

这就是一个闭环：按钮一直在 → 用户点 → 后端 200 no-op → 投影不变 → 用户看不出发生过什么 → 再点。

### A.2 修

1. **终态集合对齐后端**：`isRecoverableRun` 把 `run/interrupted` 也算作 run 终态。后端该集合是 `src/agent_harness/session/event.py` 的 `RUN_TERMINAL_TYPES = {run/completed, run/failed, run/interrupted}`——请照它对齐（`web/src/generated/event-types.ts` 已有 `RUN_INTERRUPTED` 常量，别再写裸字符串）。
2. **成功要有反馈**：`web/src/hooks/useSession.ts:740-762` 的 `recover()` 成功后回到 `RECOVER_IDLE`，界面与「什么都没发生」不可区分。建议给一次明确的成功提示（toast 或行内文案，例如「已恢复：回填 N 条工具结果 / 无可修复项」）。后端 200 的响应体就是全量事件数组，可据此算出「修了几条」，但**不要**为此发明第二套真相。
3. 顺带核对：`canRecover` 的提示文案「最后事件非 run/completed——可尝试恢复」本身也已经不准确（`run/failed` / `run/interrupted` 都是终态），建议一并改掉。

### A.3 后端备注（不需要改，但请你知情）

`POST /api/sessions/{id}/recover` 的 docstring 写「幂等：重复调用靠事件配对自然跳过已修复项」——严格说**修复是幂等的，标记不是**：每次调用都会追加一条 `session/resumed`（我实测 3 连击 = 3 条）。这是有意的（「我恢复过一次」是真事实），所以后端不打算改。A.2 的「成功后按钮消失」修好后，用户也没机会连点了。

---

## B. 「分叉」点了没反应

### B.1 现象与实证

**两个独立的失败模式，都表现为「没反应」。**

**B-1：第 1 轮以外，锚点参数传错 → 后端 422 → 被静默吞掉**

`web/src/components/Conversation.tsx:288-294`：

```tsx
<button className="fork-btn" onClick={() => onFork(turn.step_id)} >分叉</button>
```

`POST /api/sessions/{id}/forks` 的 `from_seq` 契约是**父会话中用户消息事件的 `seq`**（见 `web/src/lib/api.ts:406-430` 与后端 T7 交接单）。而 `turn.step_id` 是**投影层的 turn 键**——`web/src/lib/projection.ts:1005-1016` 的 `resolveStep` 在事件不带 `step_id` 时兜底为 `state.turns.length + 1`，即「第几轮」。

两套编号只在**第 1 轮偶然相等**。实证：会话 `f181c5ce` 的用户消息在 `seq=1` 与 `seq=30`；第 2 轮的 `turn.step_id` 是 `2` → 请求 `from_seq=2` 落在 `run/started` 事件上 → 后端 422 `from_seq 不是合法 fork 锚点`。

而这个 422 永远不会被用户看到：`web/src/App.tsx:318-323`

```ts
} catch {
  // 分叉失败静默——用户可重试
}
```

**B-2：第 1 轮的分叉会「成功」，但结果是一个空会话**

第 1 轮 `turn.step_id` 恰好 == `seq` 1，请求成功。但 `from_seq` 的语义是「锚点消息本身不进 child seed」——seed = `[0, 1)` 只有 `session/started`，所以 **child 是空会话**。

实证：会话 `a21fa4a9-4c83-4db7-9255-8cb0cc2dbb70` 全量事件只有两条：

```
seq=0 session/started
seq=1 session/forked  {"parent_session_id":"16c08b7c-…","boundary_user_message_seq":1,"fork_point_seq":null}
```

前端拿到 200 就 `selectSession(child)` + `refreshSessions()`，用户看到的是一个「暂无对话」的空页面——体感同样是「点了没反应」。

### B.2 修

1. **传正确的锚点**：给 `Turn` 加一个字段保存**该轮用户消息事件的 `seq`**，fork 按钮传它。`web/src/types.ts:163` 的 `Turn` 目前**没有**这个字段；在 `web/src/lib/projection.ts` 投影 `USER_MESSAGE` 时写入即可（`projection.ts` 已持有原始事件的 `seq`）。
2. **让失败可见**：至少把 422 / 409 / 404 落到界面（行内错误条或 toast），不要 `catch {}`。409 = 该会话有在途 run，历史未 settled。
3. **空 child 要提前告知**：第 1 轮的 seed 必然为空（没有比它更早的用户消息）。建议对第 1 轮**不渲染**分叉按钮，或在点击前明确提示「本轮之前没有历史，分叉将得到空会话」。

### B.3 建议的测试

- `projection` 层：`Turn` 带上用户消息 `seq`，且在「事件缺 `step_id`」的真实形状下仍然正确（别依赖 `step_id` 兜底）。
- 组件层：第 1 轮不出现分叉按钮（或出现但有明确提示）；第 2 轮点击发出的 `from_seq` 等于该轮用户消息的 `seq`。
- 错误可见性：fork 返回 422 时界面出现错误，不是静默。

### B.4 可选的后端配套（需产品决定，不做也能修）

后端内部已有 `src/agent_harness/session/fork.py:find_fork_boundaries(events)`，能把**合法锚点**（前缀 run 已全部收口的用户消息 seq）算出来，但**没有任何 HTTP 端点暴露它**。若希望前端「只在该能分叉的轮上显示按钮」，可以加一个只读端点（例如 `GET /api/sessions/{id}/fork-anchors` → `{"anchors":[1,30]}`）。这属于新增 API，需要你先确认要不要做——前端也可以自己从 `GET /events` 的 `seq` 推出同一结果（规则：前缀里 `run/started` 与终态计数归零的用户消息）。**我倾向先不加端点**，把 B.2 的 1-3 修掉即可，避免为一个已经不复杂的规则扩 API 面。

---

## C. 流式期间滑轮往下滚被顶回去

### C.1 现象

用户原话：「我发了一条信息，虽然能输出，但是我滑轮往下滚他就自动又上去了，我根本看不到下面啊，必须要输出完才能看见」。

### C.2 确证的代码缺陷

`web/src/components/Conversation.tsx:121-132`

```tsx
useEffect(() => {
  if (conversation?.run_status !== 'running') return;
  const el = scrollRef.current;
  if (!el) return;
  const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  setFollow(nearBottom);
  if (nearBottom) {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }
}, [conversation]);
```

依赖是 `[conversation]`，而 `conversation` 是投影产物，**每个流式 delta 都是一个新对象** → 这个 effect 每个 delta 都跑一次，条件成立就**重发一次 `scrollIntoView({behavior:'smooth'})`**。

流式 delta 的到达频率远高于一次 smooth 滚动的完成时间（Chrome 约数百毫秒），所以动画被反复重启，视口实际上被这个自动滚动「占住」；用户的手动滚动立刻被下一次重启覆盖。`run_status` 一旦不是 `running`，effect 直接 return，用户才拿回滚动权——这正对应「**必须等输出完才能看见**」。

### C.3 次要放大器（建议一并处理）

1. **重复实现已有原语**：`web/src/lib/followLatest.ts` 里 `nearBottom` / `FOLLOW_THRESHOLD_PX` / `followOnScroll` / `useFollowResetOnStop` 已经写好、有测试，并且已被 `ReasoningBlock.tsx` 与 `ToolCard.tsx` 消费。`Conversation.tsx:127,140` 又把同样的判断抄了一份（阈值硬编码 `120`，而不是 `FOLLOW_THRESHOLD_PX = 48`），且抄的这份**没有测试**。同一个「跟随 / 上滚脱离 / ↓ 跳到最新」现在有两套语义。
2. **浏览器滚动锚定**：`.conversation-scroll`（`web/src/styles/app.css:503-513`）配合 `@tanstack/react-virtual` 的动态测高（`Conversation.tsx:75-81`，`estimateSize: 240`），流式期间 spacer 高度持续变化，浏览器默认的 `overflow-anchor: auto` 会重新锚定视口。建议给 `.conversation-scroll` 显式加 `overflow-anchor: none`。

### C.4 修

1. 复用 `followLatest` 原语，**`follow === false` 时绝不发任何滚动**（现在只在 effect 里重新算 `nearBottom`，与 `follow` 状态是两套判断）。
2. 流式期间用 `behavior: 'auto'`（瞬时跳转）而不是 `'smooth'`——连续追加场景下 smooth 永远追不上。
3. 收窄 effect 依赖：不要依赖整个 `conversation` 对象，改成真正需要滚动的信号（最后一个 turn 的长度 / 最新 `seq` / `turns.length`），否则每个 delta 都会重跑。
4. `.conversation-scroll` 加 `overflow-anchor: none`。
5. 验证并保留 `↓ 最新` 浮标（`Conversation.tsx:223-234`）：脱离跟随时应出现，点击回底并恢复跟随。

### C.5 浏览器验证脚本（请你在真实 dev server 上跑）

发一条会产生长输出的消息，输出过程中：① 滑轮上滚 → 视口应停住不回弹，「↓ 最新」浮标出现；② 滑轮继续上/下滚 → 视口跟手，不被拽走；③ 点「↓ 最新」→ 回底并恢复跟随；④ 输出结束 → 无残留浮标。C.2 的「每个 delta 重发 smooth scrollIntoView」我已从代码确证（客观存在、必然有害）；「被顶回去」的精确像素路径需要浏览器实测确认，所以 ①② 是主验证项。

---

## D. 一个待确认的小疑点（不一定要修）

用户截图里有「上次运行在第 **?** 步中断」。该文案来自 `web/src/App.tsx:570` 的 `conversation.run_interrupted.step_id ?? '?'`，`?` 意味着事件信封 `step_id` 为 `null`。

但我抓到的真实会话 `f181c5ce` 里，`run/interrupted`（seq=15）的信封 `step_id = 3`，不该渲染成 `?`。所以那张截图可能来自另一个会话，或来自标记之前的数据。**请你确认一次**：若确实存在 `step_id` 为 null 的 `run/interrupted`，把复现的 session id 给我，我再查后端 `detect_unterminated_runs` 的取值路径。

---

## E. 相关后端事实（仅供你参考，不需要改）

- 崩溃扫描在 **web 启动期**跑（`src/agent_harness/web/app.py` lifespan），归属长驻会话宿主；CLI 子命令刻意不扫描（单进程假设）。
- `run/interrupted` 的 `data` 只有 `{interrupted_seq, reason:"process_restart"}`，`run_id` / `step_id` / `agent_id` 挂在**事件信封**上——前端读 `event.step_id` 是对的。
- `POST /recover` 成功返回**全量事件数组**（与 `GET /events` 同构），失败：404 会话不存在 / 409 存在需人工裁决的 UNKNOWN Operation。
- `POST /forks` 失败：404 会话不存在 / 409 有在途 run / 422 `from_seq` 不是合法锚点。
