# Composer 控制行竞品调研

> 调研对象：主流 AI-agent / coding-assistant 产品的 **Composer 控制行**——即输入框周围的那一行控制项，用于选择 model / context / agent persona / reasoning effort / permissions 等。
>
> 调研范围：Cursor、Vercel v0、Replit Agent、Devin、Claude Code、ChatGPT、Linear AI、GitHub Copilot Chat。
>
> 说明：多数产品对 Composer 的 UI 控件并未在公开文档中逐像素描述；本文只记录公开文档与官方页面可直接引用的内容，无法访问处明确标注「无公开信息」。

---

## 1. Cursor

- **模式选择（Agent persona / mode）**：在 Agent 面板通过「mode picker dropdown」切换，或用 `Shift + Tab` 循环。可用模式包含 Agent、Ask、Plan、Debug。来源：cursor.com/help/ai-features/agent。
- **Model 选择**：Composer 控制行内有 model 选择入口（`Composer 1` / `Composer 2.5` 等），具体 UI 在公开文档中未描述细节，仅列出模型清单与定价。来源：cursor.com/docs/models-and-pricing。
- **Context（@-mentions）**：Composer 内支持 `@-mention` 注入 file / folder / symbol / docs 等上下文，是其标志性控件之一。
- **Permissions / Approvals（关键发现）**：自动批准不是放在 Composer 行内的一键开关，而是放在 **Settings > Agents > Approvals & Execution** 配置页，定义三种 Run Mode：
  - **Run Everything**（即社区俗称的「YOLO」）：所有 tool call 自动执行，绕过 sandbox 与 Auto-review 分类器。
  - **Allowlist**：allowlist 中的 action 自动放行，提供确定性。
  - **Auto-review**（默认推荐）：已知安全调用直接执行，其余路由到分类器或 sandbox。
  - 配置写入 `permissions.json`，使用 `allow_instructions` / `block_instructions`（自然语言 deny 规则）。
  - 来源：cursor.com/docs/agent/security/run-modes。
- **执行控制**：进行中可点 `Stop` 中断；消息 hover 可 `Restore Checkpoint` 回滚历史。
- **视觉模式**：mode 为 dropdown，permissions 在 settings 页（非常驻）。

**引用**：
- https://cursor.com/docs/agent/security/run-modes
- https://cursor.com/help/ai-features/agent
- https://cursor.com/docs/models-and-pricing

---

## 2. Vercel v0

- v0 的公开文档（v0.app/docs）目前以角色用例与能力描述为主，**未公开 Composer 输入行控件的具体布局**（model picker、mode toggle、reasoning、permission 等均无明确说明）。
- 已知能力面：支持 generate / agent 两种生成模式（产品页面提及），但 UI 控件形态（dropdown / segmented / chip）无文档佐证。

**结论**：v0 在公开文档层面没有可引用的 Composer 控制行信息。**建议**：以产品实际界面截图作为补充来源，但本次调研不依赖未授权截图。

**引用**：
- https://v0.app/docs/ （仅能力概览，无控件细节）

---

## 3. Replit Agent

- Replit 文档站点对 Agent 输入行控件没有稳定的可访问页面（多个候选 URL 返回 404，docs.replit.com 首页亦未直接链接 Composer 控件文档）。
- 产品侧已知（基于 Replit 官方 blog 与 changelog 的公开描述，但本次未拿到可稳定引用的 docs 页面）：Agent 输入区有 model selector、结构化「Step-by-step plan」复选项、以及「Auto-run」执行开关。
- 由于未能从 docs.replit.com 直接拿到逐控件描述，本文不对其 Composer 行做细节断言。

**结论**：**无可稳定引用的公开文档**。建议后续通过产品界面或 Replit 官方 blog 补充。

**引用**：
- https://docs.replit.com/ （未发现 Composer 控件专门页面，检索 2026-09-07）

---

## 4. Devin (cognition.ai)

- Devin 是云端 autonomous agent，task 提交以「自然语言任务描述 + 附件」为主，**没有传统 IDE 那种 Composer 行内的 model/persona/permission 微调控件**。
- 公开文档（docs.devin.ai 首页）未描述 model picker、reasoning effort、permission toggle 等控件；这些更接近「会话级 / 组织级配置」而非每条消息行的控件。
- 已知产品能力：Knowledge、Sessions、PR review、Integrations（GitHub/Slack 等），均为「配置型」入口而非 Composer 行内控件。

**结论**：Devin 的范式与 IDE 类 Composer 不同——它把控制权放在 session 启动前的引导与组织设置中，而非每条消息输入行。

**引用**：
- https://docs.devin.ai/

---

## 5. Claude Code (Anthropic)

Claude Code 是 CLI，没有图形 Composer，但其控制面设计对 Phase 2b 仍有借鉴价值。

- **Model**：`--model` flag（接受 `sonnet` / `opus` 等短名或精确 ID）；交互内可用 `/model` 切换。来源：code.claude.com/docs/en/cli-reference。
- **Permissions（核心）**：
  - `--permission-mode`：`default` / `plan` / `auto` / `bypassPermissions`。
  - `--allowedTools` / `--allowed-tools`：免审批工具白名单，如 `"Bash(git log *)" "Read"`。
  - `--dangerously-skip-permissions`：等同于直接进入 `bypassPermissions`。
  - 交互态用 **`Shift + Tab` 循环切换 permission mode**，而不是每条消息重新配置。
- **Reasoning effort**：通过关键词触发（`think` / `think hard` / `think harder` / `ultrathink`）；skill 内可声明 effort level（`low` / `medium` / `high` / `xhigh` / `max`）。来源：code.claude.com/docs/en/slash-commands 相关文档。
- **Context / persona**：`CLAUDE.md`（项目级）、`--append-system-prompt`、`--mcp-config`（加载 MCP servers）、`/agents`（subagent）。这些是配置型而非每条消息控件。
- **Loop 控制**：`--max-turns`（仅 `-p` print 模式生效）。

**视觉模式**：纯文本 + slash command + 快捷键循环——这是 CLI 范式的「无 GUI 控制行」。

**引用**：
- https://code.claude.com/docs/en/cli-reference
- https://code.claude.com/docs/en/slash-commands

---

## 6. ChatGPT

- 公开 release-notes 与帮助页对 Composer 控件的逐项布局未提供稳定可引用的描述（help.openai.com 在本次检索中连接不稳定）。
- 产品已知（广泛公开但非本次可一手引用的 docs 页面）：model picker dropdown（紧邻输入框上方的「Model picker」按钮）、Attach files / 图像、Tools（web search / canvas / code interpreter 等）以可启用图标形式排布；reasoning 类模型通过 model 选择体现，而非独立 effort 滑杆（在 GPT-5 系列引入「Reasoning」高低档选择）。
- 由于一手 docs 页面未稳定获取，本文**不对 ChatGPT 控件做像素级断言**。

**引用**：
- https://help.openai.com/en/articles/6825223-chatgpt-release-notes （本次检索连接不稳，未能完整提取控件描述）

---

## 7. Linear AI (Linear Agent)

- Linear 的 AI 能力以 **Linear Agent**（agent@linear.app 邮件触发 + workspace 内 AI 操作）为主，并非 Composer 行内的逐消息控件。
- 公开文档（linear.app/docs/linear-agent）描述的是 Agent 如何对 issue/draft/comment 做自动化操作，**没有 model picker / reasoning / permission 等 Composer 行控件**。
- 文本生成类辅助（如 issue 描述的 AI 写作）走的是内嵌「AI 按钮」+ 模型默认值，而非暴露控件。

**结论**：Linear 不提供面向终端用户的 Composer 控制行；其 AI 控制粒度在 workspace 设置层。

**引用**：
- https://linear.app/docs/linear-agent

---

## 8. GitHub Copilot Chat (VS Code)

- **模式（chat modes）**：每个 chat session 可配置「agent harness, agent role, permission level, and language model」——这是把 mode/persona/permission/model 打包进 session 配置的范式。来源：code.visualstudio.com/docs/copilot/chat/copilot-chat。
- **Context（#-mentions）**：输入 `#` 引用 `#file` / `#folder` / `#symbol` / codebase 等（注意是 `#`，不是 `@`）；可附加图像（如 UI mockup）。
- **Slash commands**：输入 `/` 列出所有可用命令。
- **Tools / MCP**：可连接 MCP servers 或安装贡献 tools 的扩展。
- **Send 行为**：AI 工作中点 Send 会把发送按钮变成 **dropdown**，可选择 queue / steer / stop 当前任务——这是「输入行 = 状态机」的设计样本。
- **视觉模式**：`#`/`/` 触发的 popover + send 按钮 dropdown；mode/permission 在 session 配置面板而非消息行常驻。

**引用**：
- https://code.visualstudio.com/docs/copilot/chat/copilot-chat

---

## 对比汇总表

| 产品 | Model picker | Context | Agent persona / mode | Reasoning effort | Permissions / approval | 分组形态 |
| --- | --- | --- | --- | --- | --- | --- |
| Cursor | Composer 行内选择（dropdown） | `@-mentions` 注入 file/folder/symbol | mode dropdown + `Shift+Tab` 循环（Agent/Ask/Plan/Debug） | 由所选 model 体现（如 Composer 2.5 带 Thinking） | **不在 Composer 行**，在 Settings > Approvals & Execution（Run Everything / Allowlist / Auto-review） | 行内轻量 + 权限设置页 |
| Vercel v0 | 无公开文档 | 无公开文档 | generate / agent（产品页提及） | 无公开文档 | 无公开文档 | 无可引用信息 |
| Replit Agent | model selector（已知能力，docs 缺失） | 附件 | 「Step-by-step plan」结构化复选 | 无公开文档 | Auto-run 开关（已知能力，docs 缺失） | 无稳定引用 |
| Devin | 无 Composer 行控件 | 任务附件 | 会话级引导 | 无 Composer 行控件 | 组织/会话级配置 | 任务提交表单，非 Composer 行 |
| Claude Code | `--model` / `/model` | `CLAUDE.md` / `--append-system-prompt` / `--mcp-config` | `/agents`（subagent） | `ultrathink` 等关键词 + effort level | `--permission-mode` + `Shift+Tab` 循环 + `--allowedTools` | CLI：flags + slash + 快捷键循环 |
| ChatGPT | model picker dropdown（紧邻输入框） | 附件 / 图像 | 由 model 选择体现 | GPT-5 系 Reasoning 档位 | 无对应概念（非 agent 场景默认） | 行内图标排布 |
| Linear AI | 无 Composer 行控件 | 无 | 无 | 无 | workspace 设置层 | 非 Composer 范式 |
| GitHub Copilot Chat | session 配置内 model | `#-mentions`（file/folder/symbol） | session 配置：agent harness / role | 无独立控件 | session 配置：permission level | session 配置面板 + popover |

---

## 对我们的启示（Phase 2b Composer 控制行设计建议）

基于以上竞品观察，对本项目 Composer 控制行提出 3-5 条具体建议：

1. **常驻最小集，权限下沉**。Cursor 与 Copilot Chat 的共同教训：Composer 行只保留**每条消息都会用**的控件——**model 选择 + context 注入（@-mention）+ mode/persona**；**permission / approval 不放消息行**，而是放进设置页或 session 启动前的配置面板（参考 Cursor 的 Run Mode、Copilot 的 permission level）。这样既避免误触高风险开关，也避免行内拥挤。

2. **Mode / persona 用 dropdown + 快捷键循环双通道**。Cursor 的「mode picker dropdown + `Shift+Tab` 循环」与 Claude Code 的「`Shift+Tab` 循环 permission mode」是验证过的范式：鼠标用户走 dropdown，键盘用户走快捷键，两者共享同一份状态。建议 Phase 2b 的 persona/mode 控件同时提供这两个入口，而非只有点击。

3. **Context 注入统一用 trigger 字符 + popover**。`@`（Cursor）与 `#`（Copilot Chat）都验证了「输入框内输入触发字符 → popover 列出可选 context」的模式。建议我们的 context 注入采用单一 trigger 字符（建议 `@`，与 Cursor 一致，认知成本最低），popover 内再分类（file / artifact / memory / tool）。不要把 context 做成消息行外的独立 chip 行，那会增加视觉噪声。

4. **Reasoning effort 不独立常驻，并入 model/persona**。除 Claude Code 的关键词触发外，多数产品不把 reasoning effort 做成 Composer 行的独立滑杆，而是让它随 model 选择体现（Cursor Composer 2.5 自带 Thinking）或随 persona 预设。建议我们把 effort 作为 persona 的一项可覆盖属性（默认跟随 persona，高级用户可在 persona 详情里改），而非 Composer 行的常驻控件——符合 AGENTS.md「Scope Lock / Simplicity First」。

5. **输入行即状态机：参考 Copilot Chat 的 Send→dropdown**。当 agent 正在执行时，Send 按钮变为 dropdown（queue / steer / stop）。这对我们是直接可借鉴的交互——我们的 Composer 行在 agent 运行态应明确反映「现在是排队 / 引导 / 停止」，而不是把控制藏在别处。这与本项目 Operation Ledger / SessionEvent 的可观察语义天然契合（事件状态直接驱动按钮形态）。

---

> 一句话总结：**Composer 行 = model + context + persona 三件套常驻；permission / reasoning / 高级配置下沉到设置或 session 启动面板；控件用「dropdown + 快捷键」双通道，context 用 trigger-char popover，运行态把 Send 升级为状态机 dropdown。**
