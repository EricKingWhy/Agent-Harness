# 集成提示词 · 第十一轮真机验收发现的**前端**修复（2026-09-13）

> 来源：`docs/FRONTEND_ISSUES_LOG.md` 第十一轮（本人 + 2 个 subagent 真实浏览器逐控件点击）。
> 写给 **`D:\intelligence-agent-frontend`（feat/frontend）** 的 agent / 集成 AI。
> 本文只列**前端**可执行项；后端项已在本仓 `feat/backend` 修完（commit `164fbc2`）。
> 每条都给了「位置 / 现状 / 期望 / 最小改法 / 要加的测试」——可直接当工单用。

## 0. 交付纪律（先读）

- 前端工作**只在 frontend worktree** 做。**不要用本仓 `feat/backend` 的 `web/` 覆盖前端树**：
  本仓那份是旧快照（`grep 永久删除 web/src` 零命中，即缺 `57dd028` 的会话硬删对话框），
  这是本轮发现的**合并安全隐患**，已在登记簿记名。
- 前端门禁（AGENTS.md §16.6，逐条都要过）：
  `cd web && npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build`
  （e2e 必须 `--workers=2`）。
- 每条修完在 `docs/FRONTEND_ISSUES_LOG.md`（back/front 两份已分叉，见 SID-04）
  把对应 finding 状态改成 `已修复（commit）`。
- 验收车道与陷阱见 `docs/ACCEPTANCE_LANE_ENV.md`（已修正：期望能力集 **3** = websearch + multiagent + memory）。

## 1. 必修（P1）

### FE-R11-01（= ART-01）`artifact/externalized` 未接线 → **Artifacts 页签恒空**、且给出错误结论

- **位置**：`web/src/lib/projection.ts:824`（`[EventType.ARTIFACT_EXTERNALIZED]: { apply: unhandledProjection, summarize: unknownSummary }`）
  与 `StepDetail.tsx:171,762`（Artifacts 页签数据源 = `tools.filter(t => t.artifact)`）。
- **现状（真机，会话 `a39876d7`）**：该会话有 2 条 `artifact/externalized`
  （`87d71b1befad2f76` size=8578 `web_search`；`197e88d95cd917b9` size=39600 `bash`），
  模型还调过 `inspect_artifact artifact_id="197e88d95cd917b9…"`，但：
  Artifacts 页签显示 `Artifacts0` + 正文「**本次会话未产生 Artifact。**」（事实错误），
  同时 Overview 的 TRACE 出现 `未知事件 2`（= 这 2 条落 `unknown_events`）。
- **根因（三处对齐）**：
  1. 后端运行时**只发 `artifact/externalized`**（`assembly.py:227` 用 `ArtifactOverflowHandler`
     默认 `externalize_event_type=ARTIFACT_EXTERNALIZED`；`tooling/overflow.py:47`；
     全仓无运行时发射点发 `artifact/created`，`tests/tooling/test_overflow.py:46-51,128` 已锁定）；
  2. spec `03_SESSION_EVENT_MODEL.md` §3 事件表只列 `artifact/created`（**规格↔实现分歧**，见 §4）；
  3. 前端按 spec 接了 `ARTIFACT_CREATED`（→ `projectArtifactCreated` 写 `tool.artifact`），
     把 `ARTIFACT_EXTERNALIZED` 登记为「词汇表内但前端尚未接线」→ 生产路径上该字段**永不写入**。
- **最小改法**：`artifact/externalized` 的 payload 与 `projectArtifactCreated` 消费的字段**完全同构**
  （`artifact_id / session_id / source_tool / tool_call_id / size / mime_type`）——
  把 `ARTIFACT_EXTERNALIZED` 的 `apply` 指向**同一个** `projectArtifactCreated`
  （或让 `projectArtifactCreated` 同时接受两种 type，注释写明"两种事件同一个投影"）。
  副作用：`未知事件` 计数归零、TRACE 不再有假告警。**不需要后端改动。**
- **要加的测试**（`projection.test.ts`）：给一条 `artifact/externalized` → 断言
  ①`turn.tools[i].artifact.artifact_id/size/mime_type/source_tool` 写入正确；
  ②`unknown_events` 为空；③Artifacts 页签渲染出该条。
- **验收**：真机重开 `a39876d7` → `Artifacts2`，面板列出两条（含 39,600 字节的 bash 输出），
  且 `inspect_artifact` 的 id 能在列表中看到。

### FE-R11-02（= MOD-01）composer 选「默认链」**不发请求**：界面说"默认链"，会话仍跑上一个非默认模型

- **位置**：`web/src/components/ModelPicker.tsx:73-79`（`commitSelection`：`value === DEFAULT_VALUE ? null : value`）
  → `web/src/App.tsx:297-317`（`handleModelChange` 的 `if (selectedId && name)` 在 `name===null` 时**跳过 POST**）。
- **现状（真机，会话 `fb3619c6`，判据是 JSONL 里有没有新的 `model/changed`）**：
  选 `glm-5.3-flash` → 新增 `seq6 model/changed {to=glm-5.3-flash}`；
  再选 `默认链` → trigger 变 `默认链`，但**事件总数仍是 7、没有新事件** → 会话模型仍是 `glm-5.3-flash`。
  同一屏内 composer 说 `默认链`、右侧 Inspector 的 MODEL 区说 `模型 glm-5.3-flash`；刷新也不纠错
  （picker 只反映本地 state，不从会话事件反推）。之后每次发送都带 glm-5.3-flash 跑。
- **后端契约（已核对，不用改后端）**：`session/model_switch.py:97-132` ——
  切回默认链要 **POST `GET /api/models` 里 `is_default=true` 那个条目的名字**（`is_default_selection()` 命中即"清覆盖"），
  响应回传 `effective_model_id` 供 picker 对齐；`web/src/lib/api.ts:528` 的注释已经写明这一点。
  实测：选 picker 里另一个 `deepseek-v4-flash-0731 默认` → 新增 `seq7 {from=glm-5.3-flash → to=None}`，覆盖被正确清空。
- **最小改法**：`DEFAULT_VALUE` 不再是 `null` 直传——有 `selectedId` 时解析成
  `models.find(m => m.is_default)?.name`（取不到就退化为当前行为 + 可见提示），
  然后走**同一条** `changeModel()` 路径；`selectedModel` 用响应里的 `effective_model_id` 回填。
- **要加的测试**：①有 selectedId + 选 `默认链` → 断言发出 `POST /model` 且 body 是 is_default 条目名；
  ②无 selectedId → 不 POST（保持新会话语义）；③catalog 缺 is_default 条目 → 不崩、有提示。
- **附带**：picker 同时存在 `默认链 系统自动选` 与 `<默认模型名> 默认` 两个语义相近的选项，
  建议顺手在 UI 上区分（例如后者标注"清除会话覆盖"），否则用户仍会踩。

### FE-R11-03（= APR-01）进程重启后遗留的未决审批卡**永久残留**，点了只有 404

- **位置**：`web/src/components/ApprovalCard.tsx:58-69`（只把 409 当幂等成功，其余一律"保留 pending + 显示错误 + 允许重试"）
  + `Conversation.tsx:344-348`（`pending_approvals` 非空即渲染）。
- **现状（真机，会话 `d51bdf05`）**：`tool/approval-requested` 2 条、`permission/resolved` 1 条
  → 1 条审批永不配对（bash/danger），会话末态是 `run/interrupted`(process_restart)+`session/resumed`。
  对话区仍渲染 `需要审批` + 可点 `批准/拒绝`，**上方同时**提示「上次运行在第 2 步中断（原因：process_restart）」；
  点 `拒绝` → `POST /approve` → **404** → 卡面 `审批失败（404）`、按钮仍可点、再点还是 404、**无任何忽略/关闭路径**。
- **后端无过**：`approval_queues` 是纯内存（`session/service.py:934` → `ApprovalQueueMissing` → 404；
  `app.py:1236-1240` 已把"approval_id 不存在 → 404（前端过期事件）"写进契约），
  run 终结即 GC（`service.py:1233-1241`），且恢复链路（`recovery/`）**完全不碰 approval** →
  重启后这条审批**永远不可能再被 resolve**。
- **最小改法（前端）**：
  1. **主修**：当该审批所在 run 已到终态/中断（`run/interrupted`、`run/completed`、`run/failed`
     之后仍 pending 的审批）时，渲染成**只读失效态**（标题「审批已失效」+ 禁用按钮 +
     说明"运行已中断，该决策无法再提交"）。判据完全来自事件流，无需新 API。
  2. **辅修**：把 404 从"可重试错误"里分出来，文案改成「该审批已失效（运行已中断或服务已重启）」，
     不再暗示重试；5xx/网络错误仍保持 OBS-015 的可重试行为。
  3. "重新发起审批"是新功能（需后端在 resume 时重放 approval），不在本票范围。
- **要加的测试**：①`run/interrupted` 后仍 pending → 卡片是失效态且按钮 disabled；
  ②切到"已中断"前仍是可点态（防误伤正常流程）；③404 → 文案是"已失效"而不是"重试"。

## 2. 建议修（P2，体量都很小）

| ID | 位置 | 现状 | 最小改法 |
| --- | --- | --- | --- |
| FE-R11-04 | `ModelPicker.tsx:7` 注释 + 各 ControlPicker | 条目 ≤5 时 `CommandInput` 被 `hidden`(display:none) → 焦点落在 Radix content（`focusedInsideCmdk=false`），`[cmdk-root]` 的 `onKeyDown` 收不到事件 → **方向键/Enter 失效**（纯键盘用户无法选择） | 要么始终保留一个可聚焦元素（隐藏而非 `display:none`），要么把键盘处理挂到 content 上并显式转发给 cmdk；顺手改掉"由 cmdk 内置、无需自造"的错误注释 |
| FE-R11-05 | `ControlPicker.tsx` | 单选（权限 / Agent / 推理）选完**没有回到"未选（默认）"的入口**，只能整页 reload | 列表首项加「默认（未选）」entry，提交 `null` |
| FE-R11-06 | `ContextProviderPicker.tsx:47-49` + 勾选 span | 勾选态画在 `aria-hidden="true"` 的 checkbox 上，辅助技术读不到（`role=option` 的 `aria-selected` 只表示 cmdk 高亮） | 把勾选态暴露到 `role=option` 的 `aria-checked`（`role=option` → `aria-selected` 表示勾选），或去掉 `aria-hidden` 并给 checkbox 正确的 role/aria |
| FE-R11-07 | `ContextProviderPicker` | `selectedIds` 未与 `entries` 对账 → entries 变化后可能出现"已选但列表里没有、也取消不了"的幽灵项（静态结论） | 渲染前 `selectedIds ∩ entries`；trigger 的计数用交集 |
| FE-R11-08 | 重命名输入（`ProjectDialogs.tsx:434-436` → `SessionList.tsx:270-276`） | 纯空白标题被静默丢弃：无请求、无提示、编辑态退出 → 用户以为改名成功 | 提交前空值给出可见反馈（或恢复编辑态并提示"项目名不能为空"） |
| FE-R11-09 | `StepDetail.tsx` / `App.tsx`（≤820px 媒体查询） | 视口 ≤820px 时 `.rail-menu-btn` / `.rail-project-head` 整块 `display:none` → **删除会话入口彻底不可达**（无替代路径） | 窄屏给一个替代入口（长按 / 选中行后的操作条 / 底部操作面板）；同时确认这是有意设计还是漏配 |
| FE-R11-10 | 删除确认弹窗（`DeleteSessionDialog`） | 弹窗打开时初始焦点落在右上「关闭(X)」上（危险操作把焦点放在"关闭"上，回车即取消） | 初焦给「取消」，或给弹窗容器（`role=alertdialog` + `aria-describedby` 已有），把主/次按钮的 kbd 提示保留 |
| FE-R11-11 | Chat/Split/Preview | Split/Preview **并不真正分栏**，只插一条 `workspace-scaffold` 提示条（UI 自标"未来升级点"） | 需要产品决策：要么本轮做真副面板（升级为 P1），要么把按钮改为"未实现"态（disabled + title 说明），别让用户以为坏了 |

## 3. 仅报告（不是前端改的事）

- **DEV-R11-01【规格·P2】（= DOC-01）** `03_SESSION_EVENT_MODEL.md` §3 事件表与实现已大面积对不上：
  spec 有实现没有 8 个（`agent/completed`、`agent/delegated`、`approval/requested`、`approval/resolved`、
  `checkpoint/saved`、`context/built`、`step/started`、`step/completed`），实现有 spec 没有 21 个
  （含 `artifact/externalized`、`tool/approval-requested`、`permission/resolved`、`reasoning/*`、
  `run/interrupted`、`model/fallback`、`steer/*` 等）；抽查 7 个实现侧名字在 `docs/spec/` 下 **0 命中**。
  → **已按用户指示升级为正式流程**：母票 **#173** + 子票 **#174–#178**
  （T1 重写实装 37 个 / T2 改名映射 / T3 移出 `checkpoint/saved` / T4 三个未实现名定性 /
  T5 契约源指向 + 漂移守卫）。**不改事件名**（会动已落盘 JSONL，风险更高）。
  补充事实：契约源其实一直存在——`generated/event-types.ts` 由 `scripts/gen_event_types.py`
  从 `session/event.py` 生成，且 `tests/test_event_types_generated.py` 已在守卫生成物；
  只是 spec §3 表没被任何检查覆盖。`checkpoint/saved` 更严重：实现明令它**永不进 SessionEvent**
  （ADR-0004 Round 5），spec 却把它列在事件表里。
  **FE-R11-01 就是这条分歧的受害者**（前端照 spec 接线 → 页签恒空），所以先按 §1 在前端侧兼容，
  等 spec 重写完再决定是否收敛掉双事件名。
- **未覆盖的验收缺口（需产品/环境决策才能补）**：①项目内"真·拖拽重排后顺序改变 + 刷新保持"、
  ②「移出项目」导致的 `sessions_detached > 0`、③项目内会话的写项（上移/下移/移出/删除）——
  三者都要求**存在一条属于该项目的会话**，而当前唯一创建路径 `POST /api/sessions` 总是
  `create_and_launch()`（`app.py:1013-1046`），"新建会话"按钮只回到空态不落盘 → 不启动 LLM run 就造不出会话。
  若不希望验收依赖"起 run"，需要一个**不启动 run 的空会话创建入口**（产品决策）。
- **环境提醒**：`localStorage.ahi.selectedSession` 是同源单键，多标签并发会互相覆盖
  （本轮 3 页并发时实测）。单人单标签无感；但如果将来想"多标签各自记住会话"，要换 per-tab 存储。

## 4. 回归范围与风险

- 本轮所有前端 finding 都是**读操作或只读投影**层面，无契约/状态机改动；
  FE-R11-01/02/03 三个 P1 都只改投影或提交路径，**状态码、事件类型、后端 API 全不动**。
- 改动风险点：`projection.ts` 的投影表（FE-R11-01）——**必须同步**改一条既有测试：
  `web/src/lib/projection.test.ts:918-930`「未接线类型仍进 unknown_events（显式登记，行为与重构前一致）」
  的循环列表里**逐个包含 `EventType.ARTIFACT_EXTERNALIZED`**。接线后要把它从该列表移出
  （其余 6 个 `COMPACTION_START/END`、`MESSAGE_QUEUED`、`QUEUE_CANCELLED`、`STEER_REQUESTED/APPLIED`
  仍应留在列表里——它们确实还没接线），并新增"externalized → 写入 tool.artifact 且不进 unknown_events"的用例。
  这条测试的存在本身就是设计意图（"让未来接线成为一次显式决定"），所以**改它是预期动作，不是绕过测试**。
- MOD-01 的动态验证会写真实会话的 `model/changed` 事件（append-only 审计，**属正常留痕**，不是脏数据）；
  若 e2e 要覆盖，请用一次性会话或 `ScriptedModel` 起的会话，别在验收语料上跑。
