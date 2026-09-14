# 集成提示词：BUG-008（前端）+ 第六轮真实验收

> 给集成 AI 的交付说明。**本批只在前端 worktree（`feat/frontend`）**，后端无代码改动。
> 本 Agent **未 push**、未建 PR、未合并 `main`（§13.2 / §16.4）。

## 0. 机器状态

| 项 | 值 |
| --- | --- |
| worktree | `D:\intelligence-agent-frontend` |
| branch | `feat/frontend` |
| commit | `365fbee` — `fix(BUG-008): step_id 键缺失时不再渲染 "step undefined" 与空幽灵行` |
| 改动文件 | 6 个（4 源码/测试 + 2 文档），486 insertions / 7 deletions |
| 工作区 | clean |
| 门禁 | tsc 0 · vitest **507 passed / 0 failed** · oxlint **35 warnings / 0 errors** · playwright **118 passed** · vite build 0 |

改动清单：

```
web/src/components/StepDetail.tsx       （2 处判空 + 文档注释）
web/src/components/StepDetail.test.tsx  （+3 用例，含 2 个红灯锁）
web/src/lib/eventKind.ts                （1 处判空 + 文档注释）
web/src/lib/eventKind.test.ts           （+1 红灯锁）
docs/FRONTEND_ISSUES_LOG.md             （第六轮：验收实录 + BUG-008 修复条 + OBS-016）
docs/ACCEPTANCE_CONTROL_INVENTORY.md    （新增：110 控件清单，本批验收用的对照表）
docs/SDD_TICKET_TRACKER.md              （第六轮进度）
```

## 1. BUG-008 是什么（用户可见症状）

后端序列化**省略值为 `null` 的字段**，所以无步号事件（`session/started`、`user/message`、
`run/started`）的 `step_id` 是**键整个缺失**（实测 `'step_id' in e === false`），
而前端类型声明 `AgentEvent.step_id: number | null`。三处消费点用**严格** `!== null` 判等：

| 站点 | 症状 |
| --- | --- |
| `StepDetail.tsx::formatEventTooltip` | Timeline 行 hover 浮层渲染字面量 **`step undefined`** |
| `StepDetail.tsx` 事件详情 Overview | 多出一行**只有 key、value 为空的 `step` 幽灵行** |
| `eventKind.ts::streamKeyFromEvent` | 返回**伪造 key `step:undefined`**，违背其文档写明的「无 step → null」契约 |

**修法**：三处统一改**宽松判空** `!= null`——与 `projection.ts::resolveStep` 既有口径一致
（该处注释记录了同一 bug 类此前的一次回归）。**否决的两案**：① 改后端让 `step_id` 恒出现 →
会改动 Raw 档「完整源事件原样透传」的形状；② 在 `eventValidate::validateEvent` 统一归一化 →
该层 docstring 明确把归一化范围限定为缺失的 `data`/`seq`（「只守可辨、不崩」），塞业务字段等于扩权。

**第三处的诚实口径**：它的可见后果为**零**（`Conversation.tsx:126` 找不到目标时 `idx === -1` 直接
`return`），所以这一处的价值是**契约正确性 + 不伪造 key**，不是修一个可见症状。三处都修了、都有锁。

## 2. 需要集成 AI 注意的**环境事实**（本批结论必须带这条读）

两个 worktree 的 `.env` 是**本地文件、按 §13.1.6 不在 worktree 间同步**，能力集天然可能不同：

| worktree | `CAPABILITIES` |
| --- | --- |
| `D:\intelligence-agent`（main） | `websearch` + **`multiagent`（enabled）** |
| `D:\intelligence-agent-backend`（feat/backend） | **仅 `websearch`** |

后果：**`:8000` 上跑哪个 worktree 的后端，决定了前端能看到什么语料与能力**。
- 跑 main 后端 → 有 `delegate`（委派/子会话 UI 可达）、有 410 事件的 fork child（`加载更早` 可达）。
- 跑 feat/backend 后端 → 只有 11 个会话（最大 35 事件）、`/api/capabilities` **只返回 `websearch`**，
  委派整块 UI **按设计不渲染**（`assembly.py:211-221`，ADR-0015 opt-in，不变量 #21）。

**这不是缺陷**：前端只由真实事件驱动渲染（零伪造），后端 `/api/capabilities` 也诚实只报 `websearch`。
**若要在验收车道上真机覆盖委派**：给 `feat/backend` 的 `.env` 加 multiagent，或直接用 main 后端。
**这属改运行配置（会改变产品实际行为），本 Agent 未擅自改**，请用户决定。

## 3. 集成前建议的验证命令

```bash
cd /d/intelligence-agent-frontend
git log --oneline -1                     # 期望 365fbee
git diff --stat main...feat/frontend     # 期望只含上述 6 文件
cd web && npx tsc -b && npx vitest run && npx oxlint \
  && npx playwright test --workers=2 && npx vite build
```

**变异验证（证明红灯锁非空洞）**——把三处 `!= null` 逐个改回 `!== null`，期望：
`formatEventTooltip` 用例得 `["step undefined"]` 而红；Overview 用例见 `>step<` 而红；
`streamKeyFromEvent` 用例得 `"step:undefined"` 而红。**验证后务必还原。**

## 4. 已知风险 / 未决项

1. **类型仍是过度承诺**：`AgentEvent.step_id: number | null` 与线上「可能缺键」不符。本轮**未改类型**
   （改成 `| undefined` 会强迫所有消费点改，属跨模块大 diff，超本 ticket 边界）。已修的三处是
   本轮已知的全部消费点；**若未来新增消费点，同一坑会再现**。建议后续单独开票做类型诚实化。
2. **`加载更早 N 条`（>200 事件）的产品行为**只在其他轮次语料上真机点过；本轮语料不可达。
3. **Trace 三件套**（`复制 Trace ID` / `打开 Trace` / Inspector Trace 超链接）需 Langfuse 启用，
   本部署未配 → 三项在本部署**恒不渲染**（零伪造，正确行为）。
4. **后端观察项（非本批范围）**：默认链 `deepseek-v4-flash-0731` 停顿 50s+ 才回退 `glm-4.5-air`；
   停顿期间 UI 无「等待/即将回退」中间态。建议后端更早发 fallback 事件。
5. **§14.12 关单**：本 Agent **未创建 GitHub issue**（本轮按用户要求把问题登记在
   `docs/FRONTEND_ISSUES_LOG.md`）。若需要 issue 追踪，请集成 AI 或用户按登记簿条目补建并关单。
