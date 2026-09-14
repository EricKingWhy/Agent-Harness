# PRD — Workspace Panel（工作区面板：文件/改动 · 输出 · 清单/详情）

> 状态：**待批准**（用户批准后进入 implement）。
> 依据与优先级：`docs/spec/Observable_Agent_Workspace_SDD/01_PRODUCT_PRD.md`（下称 PRD）>
> `../goal/.../Intelligence_Agent_Web_UI_Design_Brief.md`（下称 Brief）> `docs/BENCHMARK_SYNTHESIS.md`。
> 产品事实记录：`web/PRODUCT.md`（本批新建，用户已确认）。
> 决策来源：2026-09-13/14 三轮 grill（台账见 §7）；行业范式调研见 §3.0（带官方文档 URL）。

---

## 1. Job and audience

**到达者**：有工程背景的 agent 构建者，**本机自用/小团队**。他刚跑完或正在跑一次 run，发现 agent 行为不对（跑歪、改动超出预期、命令输出看不懂）。

**他的任务**：不离开当前会话，回答三个问题——"**它动了哪些文件、改成了什么样**"、"**命令到底输出了什么**"、"**这一条事件/工具调用到底发生了什么**"。

**成功的样子**：不用去翻日志文件、不用复制命令到别处执行、不用打开编辑器找 diff，就能指到具体证据。

**visitor mode**：Operate（工具界面：可扫读、一致、真实、键盘可达优先）。

**产品差异点**：append-only typed SessionEvent 是唯一真相，**每个面板都是它的投影**；"看一条事件"与"看它的详情"在架构上是同一件事的两面。

---

## 2. Selected direction（选定方向）

**按信息结构分工，而不是"把清单搬到中间"：**

| 信息结构 | 归属 | 理由 |
| --- | --- | --- |
| **"选中一条 → 看它的详情"**（Timeline / Artifacts 清单 / Changes 清单） | **Inspector（右栏）** | 列表与详情同框时往返成本最低；Linear / Notion / VS Code 一致的模式（§3.0） |
| **改动文件集合**（本次会话改过的文件 + 逐文件 diff） | **中心列（tab）** | 它是一整个集合的**横读面**，不是"选一条看详情"；且 diff 需要宽度。Claude Code 桌面版同形态：左侧文件列表 + 右侧逐文件 diff |
| **持续输出流**（只读命令输出） | **中心列（tab）** | 纯流、要宽度、不想与对话抢滚动 |
| **对话** | **中心列常驻** | 主阅读面 |

**`Split` / `Preview` 两个模式名删除**：Brief 要的是 tabs 不是分屏；`BENCHMARK_SYNTHESIS.md` 明确**不采纳**让步链三栏 shell（drag handle）。将来若需要 Codex 式"diff 贴在旁边"，用**内联展开**（VS Code peek 做法）实现，不做持久分栏。

### 2.1 目标布局

```
┌────────┬──────────────────────────────────────┬──────────────────────┐
│ Rail   │ Chat │ 文件/改动 │ 输出 │ ⟨能力声明⟩     │ 详情（可钉住/整页）    │
│ 240px  │ ──────────────────────────────────── │ 320 → 可拖到 480      │
│        │ Conversation（主阅读面，常驻）          │ ┌ 清单（Timeline /   │
│        │                                      │ │  Artifacts）        │
│        │                                      │ ├ 选中项详情          │
│        │  Composer                            │ └ 运行摘要（RUN/MODEL/ │
│        │                                      │   TOOLS/CONTEXT/      │
│        │                                      │   PERMISSION/TRACE）  │
└────────┴──────────────────────────────────────┴──────────────────────┘
   Esc 关闭 · Space 预览（按住=临时，快按=钉住）· ↑↓ 换条目 · ⤢ 整页
```

现状几何：`.app-regions { grid-template-columns: 240px minmax(0,1fr) 320px }`（`web/src/styles/app.css:35`），≤1200px 为 280px、窄屏 rail 56px（`:3647`、`:3654`）。本批**不改三区几何**，只让 Inspector 可拖宽。

---

## 3. 交互与各面规格

### 3.0 行业范式依据（每条均有官方文档；用于避免拍脑袋）

- **清单与详情同框 + 快速预览 + 一键升级**：Linear 的 peek（`Space` 开、按住=临时、松手=关；键盘唯一）`https://linear.app/docs/peek`；Notion 的 side peek 明说"左侧数据库视图继续可交互"，并有 side / center / **Full page** 三态 `https://www.notion.com/help/views-filters-and-sorts`；VS Code peek 内联展开、`Esc` 或双击关闭、点文件名/`F12` 开进外层编辑器 `https://code.visualstudio.com/docs/editing/editingevolved`。
- **改动文件呈现的主流形态 = 左文件列表 + 右逐文件 diff**：Claude Code 桌面版官方原文 "displays a **file list on the left** and the changes for each file on the right"、diff 统计 `+12 -1`、有 "Review code" `https://code.claude.com/docs/en/desktop`；VS Code Copilot 的 "Changes panel" + 点文件名开 diff `https://code.visualstudio.com/docs/copilot/chat/chat-agent-mode`；Cursor 实时 diff + Source Control 集成 `https://cursor.com/docs/agent/review`；Devin 内嵌 IDE 的 diff view `https://docs.devin.ai/work-with-devin/devin-session-tools`。
- **也有刻意的极简派**：Codex IDE 原文 "inspect a **focused diff**... **without an extra navigation pane**" `https://learn.chatgpt.com/docs/codex/ide`；Aider `/diff` 内联 `https://aider.chat/docs/usage/commands.html`。→ 说明"文件列表"不是非有不可，但**主流是有的**。
- **终端位置**：VS Code 默认在底部 Panel，但**可以**移到编辑器区当 tab `https://code.visualstudio.com/docs/terminal/basics`；Zed 的终端可 "as a regular tab alongside your files" 放中央面板 `https://zed.dev/docs/terminal`；Warp 自我定位 "the terminal **beside your conversation**" `https://docs.warp.dev/features/warp-ai/agent-mode`；Claude Code 桌面版由可自由排布的 pane 组成（chat/diff/browser/terminal/file/plan/tasks/subagent）`https://code.claude.com/docs/en/desktop`。
- **只读输出不叫 Terminal**：Replit 把 **Console（只读日志）与 Shell（可输入）分成两个东西** `https://docs.replit.com/replit-workspace/workspace-features/console`；GitHub Actions 叫 logs `https://docs.github.com/en/actions/monitoring-and-troubleshooting-workflows/using-workflow-run-logs`；Claude Code 桌面版另设 Tasks pane 显示后台 shell 输出。**未查到任何厂商把只读视图命名为 Terminal。**
- **长内容/被截断内容**：通行做法是**就地内联**（Codex/Aider 同上）；把"被截断的大内容"做成独立列表也有先例（Claude artifacts 侧栏 `https://support.claude.com/en/articles/9487310-what-are-artifacts-and-how-do-i-use-them`）——但 Claude 的 artifact 是**用户产物**，我们的 artifact 是**被截断的工具输出**，所以本产品**同时**保留清单与就地展开（§3.4）。

### 3.1 键位与触发（Q2 = 鼠标默认可用 + 键盘加速）

| 动作 | 鼠标 | 键盘 | 备注 |
| --- | --- | --- | --- |
| 清单内移动 | 点击某条 | `↑` / `↓`（`j` / `k` 可选） | 移动时**详情实时跟随**（Linear 做法） |
| 预览（peek） | 点击即选中即预览（现状不变） | `Space` 快按=保持打开 / 按住=松手即关 | Linear peek 语义 |
| 关闭 | 关闭按钮 / 点面板外 | `Esc` | 关闭**不卸载**（既有冻结决策） |
| 钉住（pin） | 面板头部按钮 | 面板内可达 | 钉住后切换会话/选中不自动收起 |
| 整页打开（⤢） | 面板头部按钮 | 命令面板项 | 供长 trace / 大 diff 宽读；**键位留待实现时定**（避免与浏览器快捷键冲突） |
| 跳到对象 | — | 既有命令面板 | 已有；本批要求定位到**对象**（事件/工具调用/产物/改动文件）时能就地预览 |

**不做 Linear 式"键盘唯一"**：PRD 目标 6 是"键盘优先"而非"键盘专属"，且既有 e2e 与使用习惯都是点击驱动。

### 3.2 能力声明显隐（Q3 已批准；PRD §6.3 原文 "Visible when the active capability/session can produce code/file changes"）

**前端必须消费 `GET /api/capabilities`**（当前零消费）。契约已存在（`src/agent_harness/web/app.py:902-943`）：

```json
{"capabilities":[{"id":…,"display_name":…,"version":…,"provider_name":…,
  "surfaces":{"chat":true,"timeline":true,"changes":false,"terminal":false,"artifacts":false},
  "actions":{"permissions":false,"stop":false,"retry":false,"resume":false}}]}
```

缺省语义**保守**：`chat`/`timeline` 默认 true、其余默认 false（`app.py:918-927`）。规则：

- tab 集 = `chat`（常驻）+ 当前能力声明为 true 的面；**不硬编码 Coding-only tab**（PRD 非目标 6）。
- 声明为 false 的面：**不渲染**（Q4 已批准），能力为真时出现。
- 拉取失败/未就绪：**降级为 PRD 缺省语义**，不阻塞主流程；**Chat 永不因此消失**。
- 面的**名称**与声明键的对应关系必须在代码里显式登记（避免"声明了 terminal 却渲染成 Terminal 面板"这类名不符实）。

### 3.3 「文件/改动」面（本批新增，中心列 tab，Q1=C / Q2=a）

**要回答的问题**："这次 agent 到底动了哪些文件、每个文件改成了什么样。"

**规格**

1. **左侧：改动文件列表**（文件路径 + 改动统计，如 `+12 -1`）；**右侧：选中文件的逐文件 diff**。形态对齐 Claude Code 桌面版与 VS Code Changes panel（§3.0）。
2. **数据来源（无需新后端接口）**：`write`/`edit`/`apply_patch` 的 path 推导出的 `changed_files`（`multiagent/provider.py:58-87`）+ `ToolResult.data` 里的 `before/after`（`tools/_diff_data.py`）+ 持久 operation ledger（`storage/sqlite.py:45,234`）。
3. **同一文件多次修改必须合并成一行**（按文件聚合，按时间顺序叠加/展示各次改动），不能一个文件出现三行——这是"看文件集合"与"看工具调用流水"的区别。
4. **范围限定**：本批只显示**本次会话改动过的文件**（Q2=a）。**浏览工作区全部文件**、**读取当前文件内容**、**git 状态**属后续票（见 §6 票 8）。
5. 只读：**不提供编辑**。若要跳去看文件内容，属于票 8。
6. 长 diff 就地折叠/截断，**不新开导航面**（Codex/Aider 的通行做法）；被截断处的展开见 §3.4。
7. 无改动时如实显示"本会话未改动任何文件"，而不是空列表。

### 3.4 Artifacts（外置大内容）与「就地展开」（Q3=C：清单保留 + 就地展开）

**先纠正一个事实**：artifact **不是** agent 生成的文件，而是**被截断外置的大内容**——工具结果超过 `artifact_overflow_chars`（默认 2000）时，大内容存进对象存储、原结果替换为"摘要 + 引用"（`tooling/overflow.py:68-113`，不变量 #15）。agent 写的文件在工作区目录里，不在 artifact 里。今日 artifact **只来自工具输出/大 diff**（`artifact/created` 事件无生产者，只发 `artifact/externalized`）。

**两条并存**（用户决策 C）：

1. **保留 Artifacts 清单**（Inspector 内既有 tab）：列出本会话的外置内容（id / size / mime）；借助票 4 的新接口，**可点开读内容**。
2. **就地展开**：在"被截断的那一处"（工具卡、diff）提供**真实可用**的"查看完整内容"入口——这是长内容处理的通行做法（Codex/Aider 内联派）。
3. 两处的呈现必须**同一渲染器**，不得各写一套（沿用 Q5 的 DiffBlock 收敛原则）。

### 3.5 「输出」面（中心列 tab；**不叫 Terminal**）

**为什么改名**：本项目**没有 PTY**——`sandbox/local.py` 是一次性 `subprocess.Popen`，输出经 `tool/output_delta` 合帧推送。叫 Terminal 等于承诺不存在的输入能力（撞 PRD"不得伪造"）。业界只读输出的先例都叫 Console / Logs / Tasks / Progress（§3.0），故本产品命名为**「输出」**。

**规格**

1. 聚合本会话的命令输出（复用既有 `TerminalTab` 的聚合逻辑），**只读**：面内明示"只读：本项目命令为一次性执行，无交互终端"。
2. 支持按工具调用分组、复制；长输出就地折叠（§3.4 同一策略）。
3. **能力声明为 false 时不渲染**（如非编码会话）。
4. 价值边界如实：命令输出已**内联**在中心列的对话流里（Claude Code CLI / Codex CLI 同做法），本面服务于"输出很长、要宽度、不想和对话抢滚动"的场景——不得宣称它是终端。

### 3.6 Inspector 的三段结构（PRD §12）

PRD §12 要求"context 可以是：当前 Run / 选中 Timeline 事件 / 工具调用 / 产物 / 改动"，并列出 8 段。现状已有 RUN / TOOLS / CONTEXT / TRACE / MODEL（`StepDetail.tsx:270,333,364,414,438`），CHECKPOINT 为诚实占位（`:477-482`）。本批**补**：

- **PERMISSION**：权限档 + 待审批请求 + 裁决结果。数据齐：`tool/approval-requested`、`permission/resolved`（`session/approval.py:59,93`）、`GET /api/permission-modes`（`web/app.py:884-900`）、`POST /api/sessions/{id}/approve`（`web/app.py:1228-1274`）。
- **ARTIFACTS / CHECKPOINT**：**不新增 run 级段**——Artifacts 由既有清单 tab 承担（§3.4），CHECKPOINT 保持诚实占位（后端无 API）。不得为"填满八段"而伪造。

### 3.7 响应式与既有约定

- `<1200px`：Inspector 先折叠（PRD §5.1），**保持挂载不卸载**。
- Inspector 可拖宽 320 → 480，**不持久化**（`App.tsx:12` 不变量 #22 原文 "Panel geometry is transient — NOT persisted"）。
- 新增面板必须：可 Tab 到达、可 `Esc` 关闭、`aria-*` 如实；对比度 ≥4.5、字号 ≥12px（`e2e/t-contrast.spec.ts`）。

---

## 4. States and ranges（状态与数据范围）

实测供给面：事件流 `GET /api/sessions/{id}/events`；改动以 `tool/result.data.{before,after,truncated}` 携带（**无独立 diff 事件**）；命令输出经 `tool/output_delta`；外置阈值默认 2000。

**必须如实的四类状态**（PRD：No fake values）：

1. **空**："本会话未改动任何文件" / "未产生外置内容" / "无命令输出"——说明原因，不留空白或 0。
2. **不可得**：后端拿不到（CHECKPOINT、MinIO provider 缺元数据）→ `—` / `Unavailable` / 整段省略。
3. **截断/外置**：明示"已截断，完整内容为 artifact `<id>`"，并给出**可用**入口（§3.4）。
4. **加载/失败**：面板内就地显示（后端 detail 原文），不得静默。

---

## 5. Scope and boundaries

**本批做**：删 Split/Preview + 能力声明显隐骨架；中心列「文件/改动」面（本次会话范围）；中心列「输出」面（改名 + 只读如实）；Inspector peek/钉住/整页升级链；补 PERMISSION 段；diff 单一渲染；artifact 读取接口（后端）+ Artifacts 清单可读 + 截断处就地展开。

**本批不做（anti-goals）**：持久分栏/拖拽分栏；PTY 或交互式终端；浏览工作区全部文件/读当前文件内容/git 状态（票 8）；视图/过滤器保存（单机自用不成立）；移动端适配（PRD §5.2 非目标）；复制 Linear/ZCode/Raycast 品牌外观（PRD 非目标 2）；改三区几何、动 Session Rail、改 Conversation 聊天行为；为未来能力预造抽象。

---

## 6. 票与依赖

| # | 票 | 工作区 | issue | 依赖 |
| --- | --- | --- | --- | --- |
| 1 | 删 Split/Preview + 能力声明显隐骨架 | 前端 | #182 | — |
| 2 | Inspector peek/钉住/整页升级链 | 前端 | #183 | — |
| 3 | 补 PERMISSION 段 | 前端 | #184 | — |
| 4 | **后端**：artifact 内容读取接口（JSON 切片；补 MinIO 形态校验） | 后端 | #185 | — |
| 5 | Artifacts 清单可读 + 截断处就地展开 + diff 单一渲染 + marker 文案统一 | 前端 | #186 | 4 |
| 6 | 中心列「文件/改动」面（本次会话改动文件 + 逐文件 diff） | 前端 | #189 | 1 |
| 7 | 中心列「输出」面（Terminal 改名，只读如实） | 前端 | #190 | 1 |
| 8 | **后续（本批不做）**：后端开放工作区文件读取（列文件 + 读文件内容 + git 状态） | 后端 | #191 | — |

建议顺序：**4 → 1 → 7 → 3 → 2 → 6 → 5**（先把后端供给打穿 → 能力显隐骨架 → 两个内容面
→ 补 Inspector → 收口）。**订正**：原写的 `4 → 7 → …` 与本节依赖列矛盾——票 7（#190）与
票 6（#189）都依赖票 1（#182）的能力显隐骨架，先做内容面会把 tab 条写两遍或写出一个挂不
上去的面板；以依赖列为准。

---

## 7. 决策台账

| # | 决策 | 结论 |
| --- | --- | --- |
| 1 | 面板交付物定位 | **分工方案（B）**：清单+详情归 Inspector、集合/流式宽读面归中心列 |
| 2 | peek 触发 | **鼠标默认可用 + 键盘加速（C）** |
| 3 | 能力声明显隐 | **做**；为 false 的面**不渲染**，为真时出现 |
| 4 | Inspector 缺口 | **补 PERMISSION**；CHECKPOINT 保持诚实占位；ARTIFACTS 不新增 run 级段 |
| 5 | diff 渲染收敛 | **DiffBlock 为唯一渲染器** |
| 6 | 本批边界 | **一批做完**（含 artifact 接口） |
| 7 | 旧设计可否被取代 | **可以**——"这是个 Demo，什么设计好就用哪个"；故 Split/Preview 可删 |
| 8 | 首要用户 | 自己/小团队自用 |
| 9 | 实际使用的面 | Timeline / Terminal / Overview 用；Changes / Artifacts 原本不用 |
| 10 | artifact 接口响应形态 | **JSON 切片**（带截断/总行数标记），不做到字节流 |
| 11 | 中心列第二个面 | **两个都做（C）**：「文件/改动」优先，其次「输出」 |
| 12 | 「文件/改动」深度 | **本批只做"本次会话改动过的文件"**；浏览全工作区/读文件内容/git 状态→票 8 |
| 13 | Artifacts 面 | **清单保留（C）+ 被截断处就地展开**；两处同一渲染器 |
| 14 | 整页打开键位 | 面板按钮 + 命令面板项；键位实现时定 |
