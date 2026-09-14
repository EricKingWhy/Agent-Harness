# Acceptance Control Inventory

> 交互控件清单（人工/Agent 在真实浏览器逐一点击验收用）。
> 源码根：`web/src/`。行号为 2026-09-11 `feat/frontend` 工作区快照。
> 每行 = 一个逻辑控件；列表型控件（会话行、工具行、tab 组、palette 条目）按组列出并注明基数。
> 「渲染条件」= 让该控件出现的 setup；「期望反应」= 点击/操作后 UI 的可观察变化。

## 区域（Region）索引

| # | 区域 | 控件数 |
| --- | --- | --- |
| R1 | App Bar / TopBar | 11 |
| R2 | Session Rail | 2 |
| R3 | Workspace：横幅 / 工具栏 / 模式条 | 7 |
| R4 | 空状态（Empty state） | 3 |
| R5 | Conversation 执行链（turn / tool / reasoning / delegation / markdown） | 20 |
| R6 | Approval 审批卡 | 2 |
| R7 | Composer + 目录选择器 | 20 |
| R8 | Command Palette | 17 |
| R9 | Run Inspector（StepDetail） | 28 |
| | **合计** | **110** |

---

## R1. App Bar / TopBar — `components/TopBar.tsx`

| 区域 | 控件（可见文案/aria-label） | 源码位置 file:line | 渲染条件 | 期望反应 |
| --- | --- | --- | --- | --- |
| TopBar | `紧凑`（role=radio, aria-checked） | components/TopBar.tsx:102 | 恒显（DENSITIES 四档） | 密度切 compact，`.density-btn.sel` 移动，localStorage 持久化 |
| TopBar | `均衡` | components/TopBar.tsx:102 | 恒显 | 密度切 balanced |
| TopBar | `详细` | components/TopBar.tsx:102 | 恒显 | 密度切 detailed |
| TopBar | `Raw` | components/TopBar.tsx:102 | 恒显 | 密度切 raw |
| TopBar | 钥匙图标 aria-label=`API 身份令牌设置` | components/TopBar.tsx:126 | 恒显（401 时加 `.attention` 提示点） | 展开/收起 token 设置面板，aria-expanded 翻转 |
| TopBar | Inspector 折叠 aria-label=`收起 Inspector`/`展开 Inspector` | components/TopBar.tsx:135 | 恒显 | 第三栏 Inspector 收起/展开（收起不卸载） |
| TopBar | 主题图标 aria-label=`切换主题` | components/TopBar.tsx:144 | 恒显 | dark↔light，图标 Sun/Moon 互换，`[data-theme]` 变 |
| TopBar | token 输入框（type=password, placeholder `粘贴 HS256 token…`） | components/TopBar.tsx:152 | `authPanelOpen` | 可输入；Enter 触发保存 |
| TopBar | `保存` | components/TopBar.tsx:167 | `authPanelOpen` | 写入 localStorage `ahi.apiToken`，面板关闭，身份 chip 出现 |
| TopBar | `清除` | components/TopBar.tsx:168 | `authPanelOpen` | 清 token，面板关闭 |
| TopBar | 面板内 `Escape` | components/TopBar.tsx:150 | `authPanelOpen` | 关闭 token 面板 |

## R2. Session Rail — `components/SessionList.tsx`

| 区域 | 控件（可见文案/aria-label） | 源码位置 file:line | 渲染条件 | 期望反应 |
| --- | --- | --- | --- | --- |
| Session Rail | `+` aria-label=`新建会话` | components/SessionList.tsx:42 | 恒显 | 新建空会话，主区回空态，Inspector 回 Run 视图 |
| Session Rail | 会话行按钮（短 ID + 标题 + N 事件） | components/SessionList.tsx:56 | `sessions.length > 0`（每个会话一行） | 选中会话，行加 `.selected`，主区加载该会话历史 |

## R3. Workspace：横幅 / 工具栏 / 模式条 — `App.tsx`

| 区域 | 控件（可见文案/aria-label） | 源码位置 file:line | 渲染条件 | 期望反应 |
| --- | --- | --- | --- | --- |
| Workspace | 关闭提示 `X` aria-label=`关闭提示` | App.tsx:606 | `authRequired`（401 未配 token） | 隐藏鉴权横幅（不刷新） |
| Workspace | `恢复会话`（RotateCcw 图标） | App.tsx:632 | `canRecover`：selectedId && !streaming && !loadingHistory && conversation && `isRecoverableRun`（缺 run 终态或 dangling tool_call） | POST recover；pending 时禁用显示「恢复中…」；done 后出现恢复成功提示 |
| Workspace | 模式 `Chat`（aria-pressed） | App.tsx:693 | 恒显 | 主区保持 chat 阅读面（默认） |
| Workspace | 模式 `Split` | App.tsx:693 | 恒显 | 下方出现 Split 占位说明条 |
| Workspace | 模式 `Preview` | App.tsx:693 | 恒显 | 下方出现 Preview 占位说明条 |
| Workspace | `Escape`（全局） | App.tsx:171 | `streaming` 为真 | 取消当前流（= Composer 停止按钮），不抢 dialog 内 Esc |
| Workspace | `Ctrl/Cmd+K`（全局快捷键） | App.tsx:427 | 恒显 | 打开/关闭命令面板 |

## R4. 空状态 — `components/Conversation.tsx`

| 区域 | 控件（可见文案/aria-label） | 源码位置 file:line | 渲染条件 | 期望反应 |
| --- | --- | --- | --- | --- |
| 空态 | chip `写一个 FizzBuzz 脚本并运行验证` | components/Conversation.tsx:298 | `!conversation \|\| turns.length===0` 且传入 `onPresetTask` | 文本注入 Composer 输入框（可编辑后再发送） |
| 空态 | chip `创建 todo.md，写入三条今日计划` | components/Conversation.tsx:298 | 同上 | 同上 |
| 空态 | chip `列出当前目录的文件结构并总结` | components/Conversation.tsx:298 | 同上 | 同上 |

## R5. Conversation 执行链 — Conversation/ToolCard/DelegationNode/ReasoningBlock/markdown/JsonTree

| 区域 | 控件（可见文案/aria-label） | 源码位置 file:line | 渲染条件 | 期望反应 |
| --- | --- | --- | --- | --- |
| 执行链 | `分叉`（fork-btn） | components/Conversation.tsx:432 | `onFork` && turn.status!=='streaming' && `user_message_seq!==null`（仅真人用户气泡，非系统注入） | 从该消息 seq 派生 child session 并跳转；失败显示错误条；同 origin 在途去重 |
| 执行链 | 轮次折叠按钮 `折叠`/`已折叠 · N 个工具 · M 轮 · 时长` | components/Conversation.tsx:466 | `collapsible`：turn.status!=='streaming' && turn.model.text.length>0，且 activities>0 | 收起/展开该轮执行链正文 |
| 执行链 | 模型段复制 aria-label=`复制回答`/`复制输出` | components/Conversation.tsx:618 | done 模型段且 `segment.text` 非空 | 复制全量文本，按钮 1.6s 显示已复制 |
| 执行链 | `↓ 最新`（follow-pill） | components/Conversation.tsx:367 | `runActive`（投影 run_status==running）&& `suspended`（用户上滚脱离跟随） | 滚回底部并恢复自动跟随，浮标消失 |
| 执行链 | 工具行按钮（act-node，aria-level/aria-expanded） | components/ToolCard.tsx:84 | 每个 tool 恒显 | 点击循环 L0→L1→L2 展开级（明细/完整内容/raw JSON） |
| 执行链 | `Inspect`（hover chip） | components/ToolCard.tsx:118 | 传入 `onFocus` | 切到 Inspector 工具事件详情（不触发行级展开） |
| 执行链 | 工具流输出 `不换行`/`自动换行` | components/ToolCard.tsx:301 | `tool.output.length>0` && (status==='running' \|\| !tool.result) | 切换输出区 pre-wrap / nowrap |
| 执行链 | `复制全部输出` | components/ToolCard.tsx:308 | 同工具流输出条件 | 复制全量 chunks（不受尾窗裁剪影响） |
| 执行链 | 工具流 `↓ 最新`（tool-out-jump） | components/ToolCard.tsx:323 | 输出区 `suspended`（上滚） | 输出区滚到底并恢复跟随 |
| 执行链 | `复制代码` | lib/markdown.tsx:69 | 完成态模型输出含 ``` 围栏代码块 | 复制完整代码 |
| 执行链 | 代码块 `自动换行`/`不换行`（aria-label 代码自动换行/代码不换行） | lib/markdown.tsx:61 | 完成态模型输出含围栏代码块 | 代码块横向换行切换 |
| 执行链 | `复制 inspect_artifact 引用` | components/ToolCard.tsx:383 | L2 且 diff `archived` && `artifactId`（>2000 字符归档） | 复制 `inspect_artifact(id)` 文本 |
| 执行链 | `复制续读 offset` | components/ToolCard.tsx:492 | L2 read 结果含 `continuation` | 复制 `offset=N` |
| 执行链 | JSON 折叠开关（json-toggle，aria-expanded） | components/JsonTree.tsx:100 | 容器值且出现在 L2 GenericBlock / Inspector Input/Output/Raw | 展开/折叠该 JSON 容器（>50 项只渲染前 50） |
| 执行链 | 委派行按钮（`委派 → target`，aria-expanded） | components/DelegationNode.tsx:57 | 每个 delegation 节点；`hasSummary` 时可展开 | 展开/收起结果摘要；无 summary 时点击无反应（title 为 undefined） |
| 执行链 | `复制子会话 ID` | components/DelegationNode.tsx:89 | 每个 delegation 节点 | 复制 child_session_id |
| 执行链 | `Inspect 子会话` | components/DelegationNode.tsx:91 | 传入 `onInspectChild` | Inspector 原位展开 child 会话（父上下文保留） |
| 执行链 | `打开子会话` | components/DelegationNode.tsx:102 | 传入 `onOpenSession` | 主窗切换到 child session |
| 执行链 | reasoning header（`正在思考`/`思考`，aria-expanded） | components/ReasoningBlock.tsx:172 | 存在 reasoning block（streaming 默认开、完成自动收，手动 override 优先） | 展开/收起推理正文 |
| 执行链 | reasoning `↓ 跳到最新` | components/ReasoningBlock.tsx:256 | 展开体 `suspended`（在展开正文内上滚） | 推理正文滚到底恢复跟随 |

## R6. Approval 审批卡 — `components/ApprovalCard.tsx`

| 区域 | 控件（可见文案/aria-label） | 源码位置 file:line | 渲染条件 | 期望反应 |
| --- | --- | --- | --- | --- |
| Approval | `批准`（approval-approve） | components/ApprovalCard.tsx:73 | `conversation.pending_approvals` 非空 && decision==='pending'；busy 时禁用 | POST approve；卡片翻为「已批准」；409 视为成功；其它错误保留 pending + 错误条 |
| Approval | `拒绝`（approval-deny） | components/ApprovalCard.tsx:80 | 同上，decision==='pending'；busy 时禁用 | POST deny；卡片翻为「已拒绝」；错误处理同上 |

## R7. Composer + 目录选择器 — `components/Composer.tsx` (+ 三个 picker)

| 区域 | 控件（可见文案/aria-label） | 源码位置 file:line | 渲染条件 | 期望反应 |
| --- | --- | --- | --- | --- |
| Composer | textarea `#composer-input` aria-label=`Agent 任务` | components/Composer.tsx:100 | 恒显（streaming 时 disabled） | 输入任务；空状态 chip 会注入文本 |
| Composer | `Cmd/Ctrl+Enter`（发送快捷键） | components/Composer.tsx:82 | 恒显 | 提交（等价发送按钮） |
| Composer | 模型选择 trigger aria-label=`模型选择`（可见 `默认链`/模型名） | components/ModelPicker.tsx:69 | `models.length>0`（目录端点缺席则整块不渲染） | 打开 Popover；streaming 时 disabled |
| Composer | 模型搜索框 placeholder=`搜索模型`（cmdk role=combobox） | components/ModelPicker.tsx:104 | Popover 打开 && `models.length+1>5` | 过滤模型项（匹配 name/provider/model） |
| Composer | 模型项 `默认链` | components/ModelPicker.tsx:109 | Popover 打开 | 选中 null → 提交不带 model 字段 |
| Composer | 模型项（每个模型名） | components/ModelPicker.tsx:122 | Popover 打开，每个模型一项 | 选中模型；已有会话时 POST /model 切换 |
| Composer | 权限 trigger aria-label=`权限模式`（可见 `权限`/display_name） | components/Composer.tsx:120 → ControlPicker.tsx:61 | `permissionModes.length>0` | 打开 Popover；streaming 时 disabled |
| Composer | 权限搜索框（entries>5 才显示） | components/ControlPicker.tsx:93 | Popover 打开 && `entries.length>5` | 过滤权限项 |
| Composer | 权限项（每条 entry） | components/ControlPicker.tsx:97 | Popover 打开 | 选中该 permission_mode（提交时携带） |
| Composer | Agent trigger aria-label=`Agent Profile`（可见 `Agent`） | components/Composer.tsx:129 → ControlPicker.tsx:61 | `agentProfiles.length>0` | 打开 Popover |
| Composer | Agent 搜索框 | components/ControlPicker.tsx:93 | Popover 打开 && entries>5 | 过滤 |
| Composer | Agent 项 | components/ControlPicker.tsx:97 | Popover 打开 | 选中 agent_profile |
| Composer | 推理 trigger aria-label=`Reasoning Effort`（可见 `推理`） | components/Composer.tsx:138 → ControlPicker.tsx:61 | `reasoningEfforts.length>0` | 打开 Popover |
| Composer | 推理搜索框 | components/ControlPicker.tsx:93 | Popover 打开 && entries>5 | 过滤 |
| Composer | 推理项 | components/ControlPicker.tsx:97 | Popover 打开 | 选中 reasoning_effort |
| Composer | Context trigger aria-label=`Context Providers`（可见 `Context`/`Context · N`） | components/Composer.tsx:147 → ContextProviderPicker.tsx:64 | `contextProviders.length>0` | 打开 Popover（多选） |
| Composer | Context 搜索框 | components/ContextProviderPicker.tsx:96 | Popover 打开 && entries>5 | 过滤 |
| Composer | Context 项（role=checkbox aria-checked） | components/ContextProviderPicker.tsx:100 | Popover 打开，每条 entry 一项 | 切换勾选，Popover 不关闭（连续多选）；trigger 计数更新 |
| Composer | `停止` aria-label=`停止`（Square 图标） | components/Composer.tsx:164 | `streaming` 为真 | 取消当前 run（= Esc） |
| Composer | `发送` aria-label=`发送`（ArrowUp 图标） | components/Composer.tsx:169 | `!streaming`；输入为空时 disabled | 提交任务；续聊走 sendMessage，新会话走 submitTask |

> 三个 picker 的 Popular 外点/Esc 关闭由 Radix Popover 提供；无法用文案定位，点击空白或按 Esc 即可验证。

## R8. Command Palette — `components/CommandPalette.tsx` + `App.tsx`

| 区域 | 控件（可见文案/aria-label） | 源码位置 file:line | 渲染条件 | 期望反应 |
| --- | --- | --- | --- | --- |
| Palette | 搜索框 aria-label=`搜索命令` placeholder=`搜索命令或运行事件…` | components/CommandPalette.tsx:70 | `open`（Ctrl/Cmd+K 打开） | fuzzy 过滤命令/事件项，列表重排 |
| Palette | overlay 点击关闭 | components/CommandPalette.tsx:61 | `open` | 关闭面板（Radix Dialog） |
| Palette | `Escape` | components/CommandPalette.tsx:59 | `open` | 关闭面板（Radix Dialog） |
| Palette | `↑`/`↓` | components/CommandPalette.tsx:42 | `open` | 移动 active 项（循环），`.active` 移动 |
| Palette | `Enter` | components/CommandPalette.tsx:48 | `open` | 执行 active 命令并关闭 |
| Palette | 条目 `切换 Run Inspector` | App.tsx:447 | 恒显（actions） | 收起/展开 Inspector |
| Palette | 条目 `跳到最新事件` | App.tsx:459 | 恒显（actions） | focus 最后一个事件 + 主区滚动定位 |
| Palette | 条目 `复制 Run ID` | App.tsx:475 | `conversation.run_id` 存在 | 复制 run_id（hint 显示前 12 位） |
| Palette | 条目 `复制 Trace ID` | App.tsx:485 | `conversation.trace_id` 存在（Langfuse 启用） | 复制 trace_id |
| Palette | 条目 `打开 Trace` | App.tsx:495 | `conversation.trace_url` 存在 | 新窗口打开 Langfuse trace |
| Palette | 条目 `切换主题` | App.tsx:506 | 恒显（actions） | dark↔light（hint 显示目标） |
| Palette | 条目 `聚焦输入框` | App.tsx:514 | 恒显（actions） | 焦点移到 `#composer-input` |
| Palette | 条目 `切换到紧凑` | App.tsx:538 | 恒显（density） | 密度 compact（当前档 hint=`当前`） |
| Palette | 条目 `切换到均衡` | App.tsx:538 | 恒显（density） | 密度 balanced |
| Palette | 条目 `切换到详细` | App.tsx:538 | 恒显（density） | 密度 detailed |
| Palette | 条目 `切换到 Raw` | App.tsx:538 | 恒显（density） | 密度 raw |
| Palette | 事件条目（`{type} · {summary}`，#seq） | App.tsx:551 | `conversation` 存在，取最近 100 条事件倒序 | focus 该事件 + 主区跳转定位；Inspector 关着时一并打开 |

## R9. Run Inspector（StepDetail）— `components/StepDetail.tsx`

| 区域 | 控件（可见文案/aria-label） | 源码位置 file:line | 渲染条件 | 期望反应 |
| --- | --- | --- | --- | --- |
| Inspector | tab `Timeline`（role=tab） | components/StepDetail.tsx:176（事件视图同组在 :108） | `conversation` 存在且 focus.kind==='run'；事件视图下也常驻 | 切到 Timeline 事件真序日志 |
| Inspector | tab `Overview` | components/StepDetail.tsx:176/:108 | 同上 | 切到 Run 摘要（RUN/TOOLS/CONTEXT/MODEL/TRACE） |
| Inspector | tab `Changes` | components/StepDetail.tsx:176/:108 | 同上 | 切到文件 diff 聚合 |
| Inspector | tab `Terminal` | components/StepDetail.tsx:176/:108 | 同上 | 切到 bash 调用聚合 |
| Inspector | tab `Artifacts` | components/StepDetail.tsx:176/:108 | 同上 | 切到 artifact ref 聚合 |
| Inspector | `返回 Timeline`（detail-back-btn） | components/StepDetail.tsx:93 | focus.kind 为 `tool` 或 `event`（事件级视图） | 回到 Run 级 Timeline（与 tab 点击同效果） |
| Inspector | ChatTab 工具行按钮（ChevronRight + 工具名） | components/StepDetail.tsx:310 | Run 级 Overview 且传入 `onFocusTool`（child 只读视图不渲染为按钮） | 钻取到该工具事件详情 |
| Inspector | Timeline 行按钮（seq · type · summary） | components/StepDetail.tsx:598 | Timeline tab 且有事件 | focus 该事件 + 主区反向滚动定位 + pulse |
| Inspector | `加载更早 N 条`（timeline-earlier） | components/StepDetail.tsx:548 | `hidden>0`：事件数 > 窗口默认 200 | 窗口 +500 条，显示「显示最近 X / 共 Y 条」更新 |
| Inspector | Timeline 行 hover 浮层（role=tooltip） | components/StepDetail.tsx:545,570 | 悬停行且事件有 time/step_id | 显示完整时间戳 + step；滚动/缩放自动隐藏（hover 非点击） |
| Inspector | Terminal 行按钮（`$ cmd` + stdout + exit badge） | components/StepDetail.tsx:667 | Terminal tab 且存在 bash 工具 | 钻取到该 bash 工具事件详情 |
| Inspector | 事件详情 io-tab `Overview` | components/StepDetail.tsx:753 | focus.kind==='event'（非 tool） | 显示事件元信息段 |
| Inspector | 事件详情 io-tab `Input` | components/StepDetail.tsx:753 | 同上 | 显示 event.data JSON 树 |
| Inspector | 事件详情 io-tab `Output` | components/StepDetail.tsx:753 | 同上 | 显示 event.data JSON 树（语义入口） |
| Inspector | 事件详情 io-tab `Raw` | components/StepDetail.tsx:753 | 同上 | 显示完整 event JSON 树 |
| Inspector | 事件 Input `复制 JSON` | components/StepDetail.tsx:807 | 事件视图 Input tab | 复制 dataJson |
| Inspector | 事件 Output `复制 JSON` | components/StepDetail.tsx:818 | 事件视图 Output tab | 复制 dataJson |
| Inspector | 事件 Raw `复制 Raw` | components/StepDetail.tsx:829 | 事件视图 Raw tab | 复制完整事件 JSON |
| Inspector | 工具详情 io-tab `Overview` | components/StepDetail.tsx:871 | focus.kind==='tool' | 显示 tool/tool_call_id/status/耗时 |
| Inspector | 工具详情 io-tab `Input` | components/StepDetail.tsx:871 | focus.kind==='tool' | 显示 args JSON 树 |
| Inspector | 工具详情 io-tab `Output` | components/StepDetail.tsx:871 | focus.kind==='tool' && `hasOutput`（result!==undefined） | 显示 result（对象=JSON 树/文本=pre）；默认选中此项 |
| Inspector | 工具详情 io-tab `Raw` | components/StepDetail.tsx:871 | focus.kind==='tool' && `hasRaw`（raw_call \|\| raw_result） | 显示原始 tool/call、tool/result 事件 |
| Inspector | 工具 Input `复制 JSON` | components/StepDetail.tsx:920 | 工具 Input tab | 复制 argsJson |
| Inspector | 工具 Output `复制输出` | components/StepDetail.tsx:928 | 工具 Output tab 且 hasOutput | 复制 outputText |
| Inspector | 工具 Raw `复制 Raw`（tool/call） | components/StepDetail.tsx:943 | 工具 Raw tab 且 `raw_call` | 复制 raw_call JSON |
| Inspector | 工具 Raw `复制 Raw`（tool/result） | components/StepDetail.tsx:952 | 工具 Raw tab 且 `raw_result` | 复制 raw_result JSON |
| Inspector | Trace 超链接（trace_id 文本） | components/StepDetail.tsx:277 | `conversation.trace_id && conversation.trace_url` | 新窗口打开 Langfuse dashboard |
| Inspector | child 视图 `Run`（child-back-btn） | components/StepDetail.tsx:139 | focus.kind==='child'（点过 `Inspect 子会话`） | 返回父会话 Run 视图 |

---

## 需要特殊 setup 才能出现的控件（供 clicker 预先构造状态）

### A. streaming / 进行中（run 正在跑）
- `Escape` 全局中断 — App.tsx:171
- Composer `停止` — Composer.tsx:164
- Composer 发送按钮切换到停止、五个 picker 全部 `disabled` — Composer.tsx:169 / ModelPicker.tsx:69 / ControlPicker.tsx:61 / ContextProviderPicker.tsx:64
- 工具流输出区（`不换行` / `复制全部输出`）— ToolCard.tsx:301/308（条件 `status==='running' || !result`）
- reasoning header（streaming 默认展开、有 LiveDuration）— ReasoningBlock.tsx:172
- 顶栏 Run Pulse 显示秒数/`tok`（非控件，观察项）— TopBar.tsx:89/93

### B. 用户上滚脱离跟随（scrolled-up）
- 对话 `↓ 最新` follow-pill — Conversation.tsx:367（需 run 仍在 running）
- 工具输出 `↓ 最新` — ToolCard.tsx:323
- reasoning `↓ 跳到最新` — ReasoningBlock.tsx:256（需先展开 reasoning）

### C. run 中断 / 不完整（interrupted / dangling tool_call）
- `恢复会话` 按钮 — App.tsx:632（`isRecoverableRun`：最后 run 无终态或存在未配对 tool_call）
- 中断横幅为纯展示（无控件）— App.tsx:671

### D. 审批 pending（approval pending）
- `批准` / `拒绝` — ApprovalCard.tsx:73/80（需 `pending_approvals` 非空）

### E. 长目录（long catalogue，>5 项才出现搜索框）
- ModelPicker 搜索框 — ModelPicker.tsx:104（`models.length+1>5`）
- 权限/Agent/推理 picker 搜索框 — ControlPicker.tsx:93（`entries.length>5`）
- Context picker 搜索框 — ContextProviderPicker.tsx:96（`entries.length>5`）
- Timeline `加载更早`、尾窗提示 — StepDetail.tsx:548（事件数 >200）

### F. child / forked session（子会话 / 分叉）
- 分叉按钮 — Conversation.tsx:432（非流式、有 user_message_seq、非系统注入）
- `Inspect 子会话` / `打开子会话` / `复制子会话 ID` — DelegationNode.tsx:91/102/89（需存在 delegation 节点，且分别传入 `onInspectChild` / `onOpenSession`）
- child 视图 `Run` 返回 — StepDetail.tsx:139（先点 Inspect 子会话）

### G. 依赖目录 / 观测字段（可空隐藏）
- 模型选择 trigger 整块隐藏 — ModelPicker.tsx:64（`models.length===0`）
- 权限/Agent/推理/Context picker 各自隐藏 — ControlPicker.tsx:56 / ContextProviderPicker.tsx:52（entries 为空）
- 命令 `复制 Run ID` — App.tsx:475（`conversation.run_id` 缺失即不出现）
- 命令 `复制 Trace ID` / `打开 Trace` / Trace 超链接 — App.tsx:485/495、StepDetail.tsx:277（`trace_id` / `trace_url` 为 null 时不出现）
- 空状态示例 chip — Conversation.tsx:298（仅无 turn 时）

### H. 其它条件
- 鉴权横幅关闭 `X` — App.tsx:606（401 触发 `authRequired`）
- token 面板输入/保存/清除/Esc — TopBar.tsx:150-168（先点钥匙图标）
- `Inspect` 工具 chip — ToolCard.tsx:118（需传入 `onFocus`，主区路径恒有）
- 归档 diff `复制 inspect_artifact 引用` — ToolCard.tsx:383（diff >2000 字符归档）
- read 续读 `复制续读 offset` — ToolCard.tsx:492（结果含 continuation）
- 工具 Raw tab / 复制 Raw — StepDetail.tsx:871/943/952（tool 带 raw_call/raw_result）
- JSON 折叠开关 — JsonTree.tsx:100（容器型值；L2 GenericBlock 或 Inspector Input/Output/Raw）
- 委派摘要展开 — DelegationNode.tsx:57（delegation.summary 存在）
- 代码块复制/换行开关 — markdown.tsx:61/69（完成态模型输出含 ``` 围栏）
