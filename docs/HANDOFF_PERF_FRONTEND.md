# 前端性能优化交接 — 给 workbuddy

> 交接人：前端 AI（ZCode 会话，feat/frontend 全部历史工作）
> 交接对象：workbuddy（性能优化专项）
> 本文档是唯一事实源：调研结论、实测证据、缺口、建议方案、验收标准全在这里。
> 规格优先级遵循仓库 AGENTS.md §1；本批工作属于**性能专项**，不改产品语义。

---

## 0. 工作边界（先读，违反即返工）

- 工作目录：`D:\intelligence-agent-frontend`（worktree，分支 `feat/frontend`，基线 HEAD `0f1249b`）
- **只改前端**（`web/` + 前端 docs）；不合并 main、不碰 `D:\intelligence-agent-backend`、不动 main worktree
- commit 后允许 `git push origin feat/frontend`；**merge / push main 必须等用户批准**
- `D:\intelligence-agent-frontend\.env` 含 API Key，**不得读取内容、不得外泄、不得写入任何文档**
- 并发约束：同一时刻**最多 1 个 subagent**（超出会报 user concurrency limit）
- Scope Lock（AGENTS.md §8）：不顺手重构、不提前做未来 Phase、每行 diff 可追溯

## 1. 本地环境启动（踩过的坑，直接照做）

后端 :8000 用**前端 worktree 自己的 venv** 启动（它的 editable install 指向本 worktree 的 `src/`，且本 worktree `.env` 有模型 Key）：

```bash
cd /d/intelligence-agent-frontend
.venv/Scripts/python.exe -m uvicorn agent_harness.web.app:create_app --factory --host 127.0.0.1 --port 8000
```

- ⚠️ **不要用 `D:\intelligence-agent-backend\.venv`**：那份环境加载不到模型 Key（`provider 'deepseek' 缺少 API key` → POST /api/sessions 返回 500）
- 前端 dev server：`cd web && npm run dev -- --port 5199 --strictPort`（若 5199 被占说明已在跑，`http://localhost:5199` 直连；注意 curl `127.0.0.1` 可能探不到 IPv6 监听，用 `localhost`）
- 验证后端可用：`curl http://127.0.0.1:8000/api/health` → `{"status":"ok"}`
- ⚠️ **不要对真实会话调 POST recover 做延迟测试**——它幂等但会在事件流尾部追加 `session/resumed`，会污染用户真实数据（我已误污染 544a96e7 一条，无害但别再犯）

## 2. 当前基线（交接时状态）

- 分支：`feat/frontend` @ `0f1249b`（后端 df4f7d8 硬化批同步：auth 接缝 + recover + 工具新形状），已推 origin
- 质量门：Vitest **118/118**、`tsc -b` clean、`vite build` 通过
- 关键不变量（改动后必须仍然成立）：
  - **#22**：`web/src/lib/projection.ts` 是唯一投影源，UI 不维护第二套会话真相
  - **引用稳定契约**：`projection.test.ts` 里有 7 个 copy-on-write 引用稳定性测试——**性能改造不许破坏它们**（它们是 React.memo 生效的前提）
  - 事件真值时间戳优先（`event.time ?? new Date()`）；缺失观测字段显示「—」/「未追踪」，**零伪造**
- 运行中的服务（交接时）：uvicorn :8000（本地信任模式）+ vite :5199；若已死按 §1 重启

## 3. 已查到的调研结论（两个标杆项目怎么做性能）

### 3.1 oh-my-pi（can1357/oh-my-pi，Pi 的增强 fork；上游 earendil-works/pi）

对本项目最有参考价值的做法：

1. **TUI 差分渲染**：pi-tui "differential rendering"，只重绘变化区域 → 对应我们的"渲染层只动活跃 turn"
2. **热路径零 fork/exec**：搜索/AST/PTY 全部进程内 libuv 池执行 → 思想：热路径上不做任何 O(N) 系统性开销
3. **工具输出"读即摘要"**：read 工具返回 summarized snippets 而非全文倾倒 → 对应我们的 truncateForDisplay 已做，但**流式 markdown 重解析没做增量化**
4. **流中途规则注入可在 token 边界 abort** → 流式管线是可控可中断的，不是黑盒
5. **模型故障转移链 + 凭据轮转**（429 自动切下一家、per-credential backoff）→ 延迟优化的供给侧思路
6. 内置环形缓冲 profiler + flamegraph → **持续性能观测是内置能力，不是事后补**

### 3.2 DeepSeek harness（deepseek-ai/deepseek-harness）

它的 `docs/architecture.md` + `docs/subsystems/session-projection.md` 是**本任务的标准答案**，关键原文思想：

1. **Projection seam（session-projection）**：注册的投影单元对事件日志做**增量折叠（fold committed events incrementally）**，消费者读 `stateOf()` 拿单一 typed state——**日志本身在内存里，折叠过程不复制日志**
2. **Watermark 一致性**：`snapshot()` 携带 `asOfSeq` 序号水位，页面切片读取与快照读取对齐在同一序列号——不用重放就能保证一致
3. **Change feed 只在 `Object.is` 变化时通知**：视图引用没变就不广播——和我们 React.memo 的引用稳定性思想同源，但它在**投影层**就挡掉了
4. **Cropped client views**：`snapshot()` 只返回"裁剪过的客户端视图"，carrier 批量下发——**全量真相留在状态，UI 只渲染窗口**
5. **会话列表 header-only**：`stat`/`list` rescan "without loading events"——列会话不扫事件（我们的 GET /api/sessions 带 event_count，后端疑似逐会话读事件，可转给后端 AI）
6. **流式词汇表分离**：`agent/assistant-stream chunk*` 是 transient 帧，settlement 才是 durable——我们已同构（STREAM_ONLY_TYPES vs 持久事件），保持
7. **Web 性能有专门测试车道**：`vitest.web.perf.config.ts` + `--expose-gc` 强制 GC 内存基线（`apps/web/tests/**/*.perf.ts`、`ui-conversation/tests/**/*.perf.client.ts`）——性能预算是测试资产，防回归

## 4. 现有证据（实测数据 + 复现方法）

### 4.1 API 层（本地，curl 实测）

| 端点 | 延迟 |
|---|---|
| GET /api/health | 12ms |
| GET /api/sessions（21 会话） | 30ms |
| GET /api/sessions/{id}/events | 4ms |
| POST recover（幂等） | 33ms |

**结论：本地 API 不是瓶颈。** 复现：`curl -s -o /dev/null -w "TTFB %{time_starttransfer}ms total %{time_total}s\n" ...`

### 4.2 真实流式（POST /api/sessions 全链路）

- POST TTFB：**902ms**（后端建 session + 模型连接）
- 首 model/delta：**2184ms**（模型 TTFT ~1.3s 主导）
- **结论：TTFT 是模型侧的，前端只能做感知优化（Run Pulse 计时已有）；前端可控空间全在渲染层**

复现（页面 Console / evaluate_script）：

```js
const ta = performance.now();
const res = await fetch('/api/sessions', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ task: '只回答四个字：你好世界', max_steps: 1, auto_approve: true }) });
// 之后按 \n\n 分帧解析 SSE，记录首个 type==='model/delta' 的 performance.now()-ta
```

### 4.3 投影层 O(N²)（核心证据）

`applyEvent` 每事件成本随**事件总数**线性增长（页面内实测，200 次均值）：

| state 中已有事件数 | 单事件成本 |
|---|---|
| 100 | 8 µs |
| 1 000 | 72.5 µs |
| 5 000 | 373 µs |
| 20 000 | **1 349.5 µs** |

- 根因：`projection.ts` `applyEvent` 开头的 `const next = { ...state, events: [...state.events, event] }`——**每个事件都整体克隆 events 数组**，总代价 O(N²)
- 后果：4 650 事件合成会话 `projectHistory` 耗时 **963.7ms**；2 万事件的长会话里**每个流入 delta 都白付 1.35ms**
- 对比：turns/compactions 等已经 COW 化（e47e7e7），只有 events 数组漏了

复现（页面内）：

```js
const proj = await import('/src/lib/projection.ts');
const mk = n => { let s = proj.initConversation('b'); for (let i=0;i<n;i++) s = proj.applyEvent(s, {type:'model/delta',data:{delta:'x'},seq:i,run_id:'r',step_id:1,session_id:'b'}); return s; };
for (const n of [100,1000,5000,20000]) { const s = mk(n); const t0=performance.now(); for(let i=0;i<200;i++) proj.applyEvent(s,{type:'model/delta',data:{delta:'x'},seq:999999,run_id:'r',step_id:1,session_id:'b'}); console.log(n, ((performance.now()-t0)*5).toFixed(1)+'µs/事件'); }
```

### 4.4 流式 markdown 重解析（渲染层热点）

- `renderMarkdown` 全量解析成本 ~**4µs/字符**
- 模拟一条消息流式增长（160 个 delta 到 4.8k 字符）：**每个 delta 都对累计全文重新 parse，累计 574ms**
- 调用点：`Conversation.tsx` ChainNodeView 对活跃 segment 每次 render 都执行 `renderMarkdown(truncateForDisplay(segment.text))`（流式期间每 delta 触发活跃轮重渲染 → 全量重 parse）
- 复现：

```js
const md = await import('/src/lib/markdown.tsx');
let text=''; const t0=performance.now();
for (let i=0;i<160;i++){ text+='这是流式输出的一段中文文本，包含**加粗**与`行内代码`。\n\n'; md.renderMarkdown(text); }
console.log('累计', (performance.now()-t0).toFixed(0)+'ms');
```

## 5. 缺口清单（当前差什么）

1. **events 数组 O(N²)**（§4.3）——2 万事件级长会话的流式渲染与历史重建都会劣化
2. **流式 markdown 全量重解析**（§4.4）——长回答流式期间吃掉大半帧预算
3. **delta 无合帧**——每个 SSE 帧一次 `setConversation`，高频流逐帧 setState
4. ~~**无 perf 回归测试**——O(N²) 这类退化没有护栏~~ ✅ 已由 P2-6 车道承担（比例探测器 + 绝对预算）
5. **已知 bug（上批 code-review 抓到，顺手修掉）**：
   - `useSession.recover` 无模式守护：pending 期间切换会话，A 的 200 响应仍 `setConversation` 覆盖 B 视图（同 `shouldApplyStreamFrame` 家族的 stale-write，违反 #22 视图一致性）
   - `projection.ts` TOOL_RESULT 的全局配对扫描**无条件先执行**（正常带 step_id 的事件也付 O(轮×工具)）——应仅 `step_id == null` 时走全局定位；顺带 `orphanId` 改名 `callId`
   - api.ts 两处重复的 `res.json().then(j=>j.detail).catch()` 形状 → 提 `readErrorDetail()`
   - `ToolCard.tsx` TruncationAwarePre 直接 `slice` toolShapes 的标记 → 下沉 `stripGrepTruncatedSuffix()`
   - `useSession` recover 三态字面量重复 3 次 → 提常量
   - `docs/INTEGRATION_NOTES.md` §4.1 "localStorage 仅两个非敏感枚举键"已失真（现有 `ahi.apiToken` 凭据键）→ 更新表述

## 6. 建议优化点（按对响应速度影响排序）

### P0-1 消灭 events 数组 O(N²)（预计 ~百倍收益：20k 事件 1.35ms/delta → <10µs）

DSH 方案 = 增量折叠 + watermark，日志不复制。落地方案（二选一，推荐 a）：

- **a. 批量路径可变累积**：`projectHistory`（历史重建）里用一个本地可变 events 数组收集，结束后一次性构造不可变 state；`applyEvent` 单事件路径保留现有克隆语义（单事件 O(N) 只在 live 流发生，且下一条把它也消掉）
- **b. live 路径去克隆**：`ConversationState.events` 改为 push + `eventsVersion: number` 版本号；React 消费端（Timeline 等）以 `eventsVersion` 做 memo key。**注意**：这会改变 events 数组引用语义，必须核对所有把 `conversation.events` 放进 useEffect/memo 依赖的地方（StepDetail Timeline、App canRecover 等），引用稳定契约测试可能需要同步调整——这是唯一允许动那些测试的场景，且需在 commit message 里说明理由
- 验收基准：§4.3 复现脚本在 20k 事件下 <10µs/事件；4650 事件 projectHistory <50ms

### P0-2 流式 markdown 增量化（收益：长回答流式期间重解析 CPU 归零）

三档方案（可叠加，至少做 a）：

- **a. streaming 期纯文本 + 完成后 markdown**：segment `status === 'streaming'` 时渲染 plain text（等宽样式即可），`model/completed` 后一次性 renderMarkdown。最简单，视觉效果可接受（流式时本来就在打字机状态）
- **b. 节流合帧 parse**：活跃段 markdown 解析节流到 ~250ms 一次（rAF 或 timer），中间帧沿用上次解析结果
- **c. 块边界增量**：只重解析最后一个未闭合块之后的尾部（markdown.tsx 已有逐块 push 结构可依托）——收益最大工程量也最大，a 做完 b/c 视需要

### P1-3 delta 合帧渲染

`useSession` 的 SSE `onEvent` 回调里，`setConversation` 按 ~16-30ms 窗口合帧（rAF 或 setTimeout 批量），帧内多个 delta 只触发一次 React 提交。**注意**：合帧不能改变 `shouldApplyStreamFrame` 的逐帧判别语义（守卫仍逐帧执行，只合并提交）；流结束（run/completed、onDone、onError）必须立即 flush 待合帧数据，否则尾帧丢失。

### P1-4 大会话窗口化（cropped views）——✅ Timeline 部分落地（`da01efd`）；Conversation 部分按 YAGNI 暂缓（turn 级 memo + 增量 markdown 已挡热路径，待真实大会话证据）

真相全量留在状态（#22 不动），UI 层裁剪：Timeline 只渲染最近 N（如 200）行 + "加载更早"；Conversation 超过 ~30 turn 时虚拟化或折叠早期轮次。参考 DSH `snapshot()` cropped client views。

### P1-5 会话列表 header-only（转后端 AI）

`GET /api/sessions` 现带 `event_count`，后端可能逐会话读事件文件。DSH 做法：list rescan 只读 header 不加载事件。**这条不在你的 scope 内**——写入 `docs/BACKEND_GAP_PROMPT.md` 或在交付报告里转给后端 AI 即可。

### P2-6 perf 回归测试车道

仿 DSH `vitest.web.perf.config.ts`：新增手动 perf 车道（不进默认 CI inventory），
`web/src/lib/projection.perf.test.ts`：
- 20k 事件 projectHistory < 200ms 预算断言（宽松防 flaky，目的是拦 O(N²) 回潮，不是精确基准）
- 4650 事件重建 < 50ms
- 可选：`--expose-gc` 内存基线

### P2-7 首帧感知

TTFT 模型侧主导，Run Pulse「思考中·Ns」已是最优解——**不要动**。

## 7. 建议施工顺序与提交切分

1. `fix(web): recover stale-write 守护 + TOOL_RESULT 条件配对`（§5 的 5 个 bug/清理一次提交，红测先行）
2. `perf(web): events 数组去 O(N²)`（P0-1，含 §4.3 基准前后对比数字写进 commit message）
3. `perf(web): 流式 markdown 增量化 + delta 合帧`（P0-2a + P1-3，一个提交）
4. `test(web): perf 预算车道`（P2-6）
5. P1-4 视时间，可留待下批

每个提交独立过门禁；文档更新（PHASE_STATUS 时间线 + 本文档勾掉对应项）随最后一个提交。

## 8. 验收标准（全部满足才算完）

- [ ] Vitest 全绿（118+，含引用稳定契约测试——除非 P0-1 方案 b 明确说明的调整）
- [ ] `tsc -b` clean、`vite build` 通过
- [ ] §4.3 基准复测：20k 事件 <10µs/事件；4650 事件重建 <50ms（前后数字写进报告）
- [ ] §4.4 复测：流式 4.8k 字符消息 markdown 累计解析 <50ms
- [ ] 浏览器实测：真实流式任务长回答无卡顿；recover pending 期间切会话 B 视图不被覆盖；会话列表/历史回放正常
- [ ] 不变量 #22、事件真值时间戳、零伪造语义不变
- [ ] 未触碰 backend、未合并 main；commit 已推 origin feat/frontend
- [ ] PHASE_STATUS.md 新增时间线条目 + 本文档 §5/§6 勾选状态更新

## 9. 陷阱备忘（前人踩过的）

- **引用稳定契约测试是 memo 的前提**——改造投影层前先读 `projection.test.ts` 那 7 个测试，理解哪些引用必须稳定
- 合成测试事件用 `ev()` helper（`projection.test.ts` 顶部），strict TS 下缺 `step_id` 键会编译错——用 `step_id: undefined` 显式写
- 后端不持久化 `model/started`（stream-only），无工具纯对话只有 `model/completed`——投影里该事件会回填 segment/activity（4592fa2 修的 P0），**不许回退**
- `resolveStep` 用 `!= null` 松散判空（null 与 undefined 同收）——同理不许回退
- recover 合成的 tool/result 无 step_id 且 content 是纯文本（"工具执行被中断，结果未知"）——投影按 tool_call_id 全局配对是有意为之，条件化时**必须保留无 step_id 场景**
- 浏览器验证时 React 受控输入用 CDP 真实键盘输入（`type_text`），`fill` 对部分受控组件不触发 onChange；合成 `el.click()` 能触发 React 委托事件，但不确定时用 CDP click

---

## 9. 进度回执（2026-09-05 workbuddy 批，feat/frontend `c13d08b..a78c322`）

**已完成（§7 ①②③，全部红测先行，Vitest 136/136，tsc clean，lint 0 error）：**

| 项 | commit | 基准（本机前后） |
| --- | --- | --- |
| 5 个已知 bug（§5） | `c13d08b` | — |
| P0-1 events 去 O(N²)（方案 b append-only 共享日志） | `3344e34` | applyEvent @20k：240.9µs→**0.2µs**/事件；projectHistory 4650：35.0→**2.8ms**；20k：1536.9→**7.2ms** |
| P0-2a 流式 markdown 增量化 + P1-3 delta 合帧 | `a78c322` | §4.4：239.9ms→**1.9ms**（预算 <50ms） |

- P0-1 走了方案 b（不是推荐的 a）：验收基准直接测 applyEvent 单事件成本，方案 a 无法达标。全量核对无消费者把 `conversation.events` 放进 memo/useEffect 依赖（App/Conversation/StepDetail/Run Pulse），故未引入 eventsVersion（Simplicity First）。「纯追加」测试按 §5 唯一许可改写为 append-only 契约，另加引用稳定锁——turns/tools/compactions 的 7 个引用稳定契约原样全绿。
- P1-3 合帧语义：只合并「提交」不合并「折叠」——每帧仍逐帧过 shouldApplyStreamFrame 守护并立即 applyEvent；run/completed、run/failed、onDone、onError 立即 flush；submit 守卫 mode 仍是 live（cancel 后迟到 fire 不写回）。

**剩余（交接 ZCode）——✅ ZCode 批后全部关闭或显式转出（见下方回执）：**

> **✅ ZCode 接手批回执（2026-09-05，`77de188..da01efd`）：**
> 1. **P2-6 ✅**（`77de188`）：默认车道排除 `*.perf.test.ts`（vitest.config.ts + configDefaults）；手动车道 vitest.perf.config.ts（`pnpm test:perf`）；预算断言含**机器无关 O(N²) 比例探测器**（applyEvent @20k/@1k 成本比 <8，健康≈1，回潮 ~180x）+ 绝对预算（@20k <50µs、projectHistory 4650 <50ms、20k <200ms，基线 20 倍以上余量）。
> 2. **P1-4 ✅（Timeline 部分）**（`da01efd`）：实测坐实（renderToString 探针：20k 全量 359ms / 2k 40ms）→ TimelineTab 尾窗 200 行 + 「加载更早」500 步长 + 全局序号 key；SSR 行为契约测试 4 个；不变量 #22 不动（只裁视图）。**Conversation 虚拟化未做**——turn 级 memo + 增量 markdown 已挡住主要热路径，待真实大会话出现性能证据再议（YAGNI）。
> 3. **候选优化点实测结论**：ToolCard grep split 非流式热路径（memo 已挡）→ 暂缓；StepDetail Timeline 全量 map 坐实 → 已修复。
> 4. P1-5 维持转后端。Vitest 137/137，tsc clean，build 通过（dist 已清理）。
1. **P2-6 perf 预算测试车道**：`web/src/lib/projection.perf.test.ts` 已在库（基准可跑），还差独立 `vitest.perf.config.ts` 手动车道 + 预算断言（20k projectHistory <200ms、4650 <50ms）+ 默认套件 exclude `*.perf.test.ts`。
2. **P1-4 大会话窗口化**（cropped views，真相全量不动）。
3. **P1-5 会话列表 header-only**（转后端 AI）。
4. 候选额外优化点（workbuddy 读码观察，**未验证**，供参考）：StepDetail Timeline 每渲染全量 map `conversation.events`（大会话 O(N)/render，可与 P1-4 合并设计）；ToolCard grep 输出每渲染 split/map 全行（长输出可 memo）；TurnView memo 已挡住完成段重复 markdown 解析（无需再动）。

**⚠️ 环境异常备案（接手必读）：** 本批施工期间 `refs/heads/feat/*` loose ref 两次神秘消失（reflog 出现无消息 `0000→sha` 重建条目），backend 侧同样发生。提交对象与 reflog 始终完好，非仓库损坏。根因指向多 AI 会话 × 双 Git 工具链（`D:/DevTools/Git` 与 workbuddy PortableGit）× 沙箱对 worktree 外 `.git` 路径写入拦截的复合干扰；backend 还观察到裸 `git status` 卡死而 `-uno` 秒过（疑 index 全量刷新 + 大目录 untracked 扫描）。应对协议：commit 后同命令内 `git log -1` 验证，缺失则从 reflog 重建 ref 文件并立即 push；以远端 `ls-remote` 为最终事实源；清理分支前 `git worktree list` + 确认无未推送提交。

---

## 10. UI 精修第二批回执（2026-09-06 workbuddy，feat/frontend `6f9a55b..56a3c24`）

**主题：Inspector 与运行链的信息呈现（承接 §9 剩余候选的 UI 侧 + 第一批后续点）。纯表现层：零逻辑改动、零依赖新增。**

| 项 | commit | 内容 |
| --- | --- | --- |
| C1 JsonTree | `6f9a55b` | Inspector JSON dump 平铺文本 → 折叠树 + 语法着色（string/number/literal 三类 token 双主题）；defaultDepth=2、单容器 50 子项渲染预算 + 余量行、160 字符串截断；**真值通道不变**（CopyButton 持全量文本，视图裁剪不删数据，同 truncateForDisplay 级）。集成：EventInspector data/Raw、ToolEventSections、ToolCard GenericBlock。9 个 SSR 契约测试 |
| C2 IO 标签条 | `56a3c24` | ToolEventSections Input/Output/Raw 三段堆叠 → io-tabs segmented（density 同语言）；默认 Output（运行中回退 Input）；耗时右上置。3 个 SSR 测试 |
| C3 内联整合+Compact | `56a3c24` | detailed/raw 档 args/result 裸 pre → act-field 面板（Input/Output 微标签，与 Inspector 同语言）；[data-density='compact'] 密度作用域（行距/字号/轨道线全面降档，信息零删减）。4 个 SSR 测试（ToolCard.test.tsx 新文件） |
| C4 Timeline 浮层 | `56a3c24` | 行 hover 显示完整时间戳（含毫秒）+ step；formatEventTooltip 纯函数 + 单元素 fixed 浮层 + 容器事件委托（零每行 handler）；滚动/缩放/移出即隐藏；glass popover 合法玻璃区 + reduced-motion 兜底。4 个纯函数测试 |

**验证**：Vitest 174/174（+20 vs §9 末态 154），perf 6/6，tsc clean，oxlint 0 error。双主题/各密度档 playwright 截图目检通过（系统 Chrome channel，免下载 Chromium）。

**⚠️ 本批环境备案（新增两条，接手必读）**：
1. **Edit 工具写入丢失**：同一会话内对同一文件的多个 Edit 出现部分落盘（StepDetail.tsx 的 EventInspector 段、ToolCard.tsx 的 GenericBlock 段、TimelineRow 签名各丢一次，工具返回成功但文件未变）。**对策：每次 Edit 后立即 grep 关键锚点验证**——tsc/vitest 全绿不代表编辑落盘（旧代码同样合法）。
2. **本地 refs 写入静默吞没依旧**（`update-ref` 退出 0 但 ref 文件物理不存在；与 git 二进制无关，文件系统层）。**可靠路径：`git push origin <full-sha>:refs/heads/feat/frontend`**（sha 直推绕开本地 ref）；本地 ref 恢复由用户/集成 AI 终端执行 `git fetch origin && git update-ref refs/heads/feat/frontend origin/feat/frontend`。
