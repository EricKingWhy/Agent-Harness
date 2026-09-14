# 前端问题登记簿（实时更新）

> **2026-09-13 集成归并说明**：本文档曾在 backend / frontend 两个 worktree 之间分叉（SID-04）。
> 本次 feat/backend → main 集成已完成两侧轮次归并：各轮按时间顺序全部保留，重复的
> 「第十一轮」编号已消歧为「第十一轮（前端侧）」（#155 两轴 code-review，2026-09-12）与
> 「第十一轮（后端侧）」（会话硬删 #172 真机验收，2026-09-13）。此后同一文件统一在 main 上维护。

> **用途**：真实浏览器点击测试 + 日常使用中发现的任何问题，实时登记在此。
> 修 bug 时照着本文档逐条处理；修完把状态改为 `已修复` 并补上 commit。
>
> 状态词汇：`未修复` / `修复中` / `已修复（commit）` / `不改（理由）`
> 严重级：`P0 功能不可用` / `P1 功能可用但体验破损` / `P2 边角 / 打磨`

---

## 问题清单

> **本轮（第三轮 · 控制面清点）新增的后端问题 OBS-011～OBS-014 与两项覆盖缺口，正文在文末「第三轮」章节**（含根因文件行号与原始字节级证据）——它们不在下方历史清单里，勿以为遗漏。

### BUG-011 双击模型项 → 两个 `POST /model` 并发写同一 seq → 会话日志损坏 → 续聊永久 404【P0 · 后端根因 · 已修复】

**发现时间**：2026-09-11 真实浏览器验收（用户报「续聊失败：Send failed: 404」，会话 `dd983104-733c-44e9-baa0-7807b86c9f58`）

**一句话**：模型选择器**双击**会发出两个并发 `POST /model`；后端 `change_model` 是「读快照 → 取号 → append」的读-改-写，**两次都取到同一个 seq，且都返回 200**，事件日志出现重复 seq；此后任何构造 `Session` 聚合的路径（含续聊）抛 `ValueError`，被 `service.py:431` 一刀切映射成 **404「会话不存在」**。**根因在后端**（并发写无序列化 + 错误码错配）；前端双击不去重是触发条件。

**完整证据链、复现实验与待决策项：见文末「第八轮」章节。**

**修复（2026-09-11，用户批准后按序实施）**：

| 步 | 侧 | 内容 | commit |
| --- | --- | --- | --- |
| ① | 后端 | 每会话写锁 + seq 单调性守卫：`store.append_event` 在任何写者落盘前校验 `seq > 已落盘最大 seq`（`threading.Lock`，因为写者跨线程：事件循环与恢复扫描的工作线程），违反抛 `SeqConflict` | `4b8eee4` |
| ② | 后端 | 冲突错误语义独立：`SeqConflict → 409`（不再假装 404）；`change_model` 写时冲突有界重试（3 次）后仍冲突才 409；删掉 `except ValueError → SessionNotFound` 的一刀切 | `4b8eee4` |
| ③ | 前端 | 选档入口 `ModelPicker.commitSelection`：**弹层已关（`!open`）即丢弃选中**——第一次选中后浮层进入 `--dur-out`(150ms) 退出动画，节点仍在 DOM 中可命中，第二次 click 会被这里丢弃 | `71e605b` |
| ④ | 前端 | 回归锁 `web/e2e/q-model-dedupe.spec.ts`（3 条 × 2 视口）：在途窗口内重复点击 / 已返回后双击同一项 / 换目标照常发 | `71e605b` |

**③ 的实现取舍（有实测依据，非按最初设想照抄）**：最初设想在 `useSession.changeModel` 加「同目标在途复用 Promise」。探针实测该层**永不生效**——`dblclick()`（一次手势两下点击）与 `page.mouse.click` ×2 都是「两次 click 之间 React 已提交 `open=false`」，第二个请求根本到不了 hook；删掉该层前后探针结果完全相同（`dblclick=1` / `mouseclick_x2=1`）。因此只保留入口一层（计划里「或在弹层关闭后立即 `pointer-events:none`」的等价做法），hook 处仅留注释指明真正的 seam，避免后人把守卫加在错误的层。

**④ 反「假绿」**：去掉 `!open` 守卫重跑 → 两例全红，且失败信息就是原始 bug 指纹（`Expected: 1 / Received: 2`；另一例 `Received length: 3`，三个 payload 完全相同）。证明绿不是「第二次点击根本没落到节点上」。

**未决/边界**：跨进程并发写（多进程共享同一 JSONL）仍未加文件锁——`store.py` 文档已如实标注该边界；读时发现的日志损坏（历史遗留）不可自愈，直接 409。

---

### BUG-007 命令面板 11 条静态命令的 label 全是英文，中文查询零命中（中文 UI 里的本地化缺口）【P2 · 已修复】

**发现时间**：2026-09-11 真实浏览器逐按钮巡检（Ctrl+K）

**现象**：面板整体是中文（标题「命令面板」、占位「搜索命令或运行事件…」、页脚「↑↓ 选择 Enter 执行 Esc 关闭」），但**可搜索的条目文案全英文**：`Toggle Run Inspector` / `Jump to Latest Event` / `Copy Run ID` / `Copy Trace ID` / `Open Trace` / `Toggle Theme` / `Focus Composer` / `Switch to Compact|Balanced|Detailed|Raw`。

**实测（同一面板，逐个输入）**：

| 输入 | 命中 |
| --- | --- |
| `Theme` | `Toggle Theme`（+4 条 fuzzy 子序列命中的事件项） |
| `toggle` | `Toggle Run Inspector` / `Toggle Theme` |
| `Compact` | `Switch to Compact` |
| `Copy` | `Copy Run ID` / `Copy Trace ID` |
| `MARKER-A2` | `tool/call · bash {...MARKER-A2}`（事件搜索正常） |
| **`主题`** | **空** |
| **`复制`** | **空** |
| `zzzz` | 空（对照组：确属无匹配） |

**判读**：
- 过滤本身**没坏**——`lib/commands.ts` 的 `fuzzyScore` 是「子序列匹配 + 前缀/连续加分」的纯函数，大小写不敏感，输入 `Compact`/`copy`/`MARKER-A2` 都正确命中。`Theme` 顺带命中 4 条 `tool/call` 事件项也是**正确的 fuzzy 行为**（`t..h..e..m..e` 在 `tool/call · bash {"command":"sleep 1 && echo MARKER-A3"}` 里按序出现），不是 bug。
- 真正的缺口是**文案语言**：中文用户按母语输入（「主题」「复制」「密度」）一条都搜不到，而工具栏上的同名按钮写的正是「紧凑/均衡/详细」「切换主题」。同一功能两套语言。

**归因：前端（文案）**。不是逻辑缺陷，是本地化一致性问题。

**为什么最终判定为「缺陷」而不是「产品文案决定」**：面板的 `hint` 早就是中文（`右栏` / `定位` / `输入框`），只有 `label` 是英文——这是**本地化做了一半**，不是刻意的英文设计。工具栏同名按钮的 `aria-label` 也是中文（`切换主题` / `收起 Inspector`）。两处中文夹着一处英文，用户按母语搜索却零命中，属可修的一致性缺陷。

**修复实现（2026-09-11）**：
1. `lib/commands.ts`：`CommandItem` 增加 **不显示** 的 `keywords?: string`；`filterCommands` 的匹配 haystack 改为 `label + ' ' + keywords`。label 在前，所以**只按 label 命中的那条打分逐字不变**（追加文本不会移动 label 字符的贪心下标；已穷举 3 字符以内 query 验证：0 个既有命中失分或改分）。但**跨命令仍按分数比大小**——一条命令靠 keywords 命中且分高于另一条靠 label 命中的，就会排到前面（例：query `to` 下 `切换主题` 经 keyword `toggle theme` 高于 `切换 Run Inspector` 的 `Inspector`）。这是可接受的：keywords 的存在就是为了让中文 label 的命令仍能被英文搜到。
2. `App.tsx`：11 条静态命令的 `label` 全部改中文，与工具栏/提示口径对齐——`切换 Run Inspector` / `跳到最新事件` / `复制 Run ID` / `复制 Trace ID` / `打开 Trace` / `切换主题` / `聚焦输入框` / `切换到紧凑|均衡|详细|Raw`（密度名与工具栏四档同名）。英文原词进 `keywords`，老用户的英文肌肉记忆不作废。
3. 事件项（`tool/call · bash {...}`）**保持原样**——那是后端事件类型，本就属技术词汇。

**验证（真实浏览器，同一面板）**：

| 输入 | 修复前 | 修复后 |
| --- | --- | --- |
| `主题` | 空 | **切换主题** |
| `复制` | 空 | **复制 Run ID** |
| `密度` | — | 切换到紧凑 / 均衡 / 详细 |
| `紧凑` | — | 切换到紧凑 |
| `toggle theme` | Toggle Theme | **切换主题**（经 keywords，英文仍可搜） |
| `Copy Run` | Copy Run ID | **复制 Run ID**（经 keywords） |
| `compact` | Switch to Compact | 切换到紧凑（经 keywords） |

静态条目现状（**11 条**）：`切换 Run Inspector` / `跳到最新事件` / `复制 Run ID` / `复制 Trace ID`* / `打开 Trace`* / `切换主题` / `聚焦输入框` / `切换到紧凑` / `切换到均衡` / `切换到详细` / `切换到Raw`。打 * 的两条按契约条件出现（取决于该会话的 run 终态事件是否带 `trace_id`/`trace_url`）；实测会话 `f181c5ce` 上 **11 条全部渲染**，两条 trace 命令也都能正常工作（见 OBS-010）。事件项（约 39 条 `tool/call · bash {...}`）的 label **保持英文**，那是后端事件类型。

**回归锁**：`e2e/i-keyboard.spec.ts` 的 Copy Run ID 用例改为**英文查询 + 中文条目**——一条测试同时锁「label 已本地化」与「英文别名仍命中」；`lib/commands.test.ts` 新增 3 例（中文 label 命中 / 英文 keywords 命中 / 无 keywords 条目不回归）。

**参考 deepseek harness 的结论（用户要求「能抄就抄」）**：查了 `docs/RESEARCH_DEEPSEEK_HARNESS_WEB.md`——dsh 的命令面板/侧栏本地化不在其研究范围内（该文档聚焦会话/流式/审批/恢复），本条无可直接抄的设计。有一处相关差异记录在案：dsh 的重连是**服务端权威快照**（`history.ts:180-200`，无客户端游标），我们的契约是 `?after_seq=` 游标重放（这是本项目后端 T4 #97 定的，不是前端能选的），所以 BUG-006 按游标实现是当前契约下的正解，不适用「改成快照」。

---

### OBS-010 会话**列表**端点的 `trace_id` 恒为 null（但事件里有，命令照常工作）【观察项 · 后端·已订正】

> ⚠ **本条已订正**：初版写成「70 个会话 trace_id 全为 null → Copy Trace ID / Open Trace 永不出现」，**结论是错的**。错因是只查了会话列表端点，没查事件。实录订正如下。

**实测（2026-09-11）**：
- `GET /api/sessions`：70 个会话，**`trace_id` 全部为 null**。
- 但**事件里有**：会话 `f181c5ce` 的 `run/failed`（seq 33）携带
  `trace_id: 2482fcee980f20ad111e3d19289043b1` +
  `trace_url: https://jp.cloud.langfuse.com/project/…/traces/2482fcee…`。
- 命令面板的两条命令**确实出现且工作**（同一会话上实测）：
  | 命令 | 实测行为 |
  | --- | --- |
  | `复制 Trace ID` | 拦截 `clipboard.writeText` 拿到实参 = `2482fcee980f20ad111e3d19289043b1`（与事件逐字一致）✓ |
  | `打开 Trace` | 拦截 `window.open` 拿到 `https://jp.cloud.langfuse.com/project/…/traces/2482fcee…`，`_blank` ✓ |

**判读**：Langfuse **已接入**。前端这两条命令的可见性取自 **`conversation.trace_id` / `conversation.trace_url`**（由 `projection` 从 run 终态事件抽取，契约 2d7f87a），**不依赖会话列表**——所以列表端点 trace_id 为 null 完全不影响它们。

**真正剩下的后端小观察**：`GET /api/sessions` 的 `trace_id` 字段**从来没有值**（不是「本部署没接 Langfuse」，是该端点没回填）。当前前端不用它（命令走事件、会话行也不显示 trace），所以**无用户可见影响**；但若将来想在会话行上直接标 trace，要先把该字段回填。

**归因：后端（会话列表端点未回填 trace_id）**。**前端无需改动**。

---

### OBS-008 `model/failed: RuntimeError`（glm-5.3-flash）紧跟在成功的 tool/result 之后【观察项 · 后端/provider】

**发现时间**：2026-09-11 真实浏览器刷新一致性测试中顺带记录（会话 `1fdac9b9`）

**事件真值**（`GET /events`，seq 404–409）：

```
404 tool/call      bash {"command": "sleep 8 && echo proof-8842"}
405 tool/output_delta  stdout: "proof-8842\n"
406 model/completed  model=glm-5.3-flash usage=9521  tool_calls=[bash]
407 tool/result      {"ok": true, "exit_code": 0, "stdout": "proof-8842\n", "duration_ms": 8115.9}
408 model/failed     "model call failed: RuntimeError"
409 run/failed
```

**判读**：工具**成功**（`ok:true, exit_code=0`），随后**模型调用**抛 `RuntimeError` → run 收口为 failed。UI 显示「失败」并保留工具成功输出，是对事件真值的忠实渲染，**不是前端 bug**。

**归因**：后端/provider。与既有 OBS-001 同族（同一模型 `glm-5.3-flash` 此前返回 400 BadRequestError），本次是 `RuntimeError`——同一默认链上的模型不稳定，值得后端排查（`model call failed: RuntimeError` 的原始异常被吞成了这一句，建议把 traceback 落进日志/JSONL 以便定位）。

**前端侧无需修**：失败态、错误横幅、后续可重试都已有既有通路。

---

### OBS-009 bash 工具执行上限 10.0 秒，`sleep 10` 恰好越界 → `TIMEOUT`（且 `retryable:false`）【观察项 · 后端工具运行时】

**发现时间**：2026-09-11 BUG-006 实机取证时顺带命中（会话 `affd6084-…`，seq 6/8）

**事件真值**：
```
seq 6  tool/call   bash {"command": "sleep 10 && echo MARKER-A1"}
seq 8  tool/result {"ok":false,"message":"工具 'bash' 执行超时（上限 10.0 秒）…",
                    "error_code":"TIMEOUT","retryable":false,
                    "metadata":{"attempt":1,"max_attempts":3,"duration_ms":10002.6}}
```
模型随后自行改写成 `sleep 1 && echo MARKER-A1` 并在 seq 14/17 成功，最终 `run/completed`。

**判读**：`sleep 10` 与上限 10.0s 贴边，必然越界。**前端渲染正确**——Timeline 第 8 行显示 `tool/result 失败 TIMEOUT`，同一 run 的 pulse 仍是「已完成」，因为工具失败可被模型恢复：这是忠实且正确的语义（工具失败 ≠ run 失败）。

**归因**：后端工具运行时（`bash` 超时上限 10s）。**两点值得后端确认（非前端，未改）**：
1. 超时被标 `retryable: false` —— 与不变量 #8「Tool Retry 归 ToolExecutor」的取舍值得确认：若 TIMEOUT 一律不重试，则瞬时超时只能靠模型自己重发（本例正是如此）。
2. 上限 10s 对 `sleep`/长构建类命令偏紧，且错误文案已说明「可稍后重试」却标 `retryable:false`，二者读起来略冲突。

---

### BUG-005 页面刷新后选中的会话与全部内容丢失（回到空态）【P1 · 已修复（138b056）】

**发现时间**：2026-09-11 真实浏览器测试（用户预判要求：刷新后会话必须与刷新前一致）

**测试环境**：真实浏览器（Chrome DevTools MCP）→ `http://localhost:5173/`（feat/frontend worktree 的 vite）；后端 `http://127.0.0.1:8000`（集成版 `agent_harness.web.app`）；会话列表 **67 个真实会话**。

**复现**：点左侧会话 `1fdac9b9-1dee-4fc5-95d3-d4ab2787b004`（305 事件）→ 按 F5 刷新。

**证据（刷新前后同脚本实测）**：

| 观测量 | 刷新前 | 刷新后 |
| --- | --- | --- |
| 侧栏选中行 | `1fdac9b9-…`（class `session-item selected`） | **无**（`selected: null`） |
| `.turn` 轮次 | **8** | **0** |
| 会话正文指纹 / 长度 | `-271347586` / 4102 字符 | **0 / 0 字符** |
| 主区 | 8 轮对话 + 「已完成 · 4,339 tok」脉冲 | **「暂无对话 / 在下方提交任务」** |
| 右栏 Inspector | 「RUN INSPECTOR / 已完成 / run 2ab617e9 / 显示最近 200 / 共 305 条」 | **「未选择会话 / 从左侧选择，或开始新任务。」** |
| 地址栏 | `http://localhost:5173/` | 同（**不含任何会话标识**） |
| `localStorage` | `ahi.theme` / `ahi.traceDensity` | 同（**存活**） |

**结论**：会话列表（67 条）还在，但**选中的会话与它的全部内容在刷新后消失**，主区退回空态。持久化的只有主题/密度/API token——**会话选择没有持久化**。

**归因：前端。** 后端数据完好（刷新后 67 条列表仍由 `GET /api/sessions` 返回，事件也在 JSONL 里）；丢的是 UI 的选中状态。

**根因**（代码可证）：
1. `web/src/hooks/useSession.ts:232` —— `const [mode, setMode] = useState<SessionMode>({ kind: 'idle' })`，**初始态恒为 idle**，没有任何恢复路径。
2. 全仓 `grep localStorage` 只有三处：`lib/theme.ts`、`lib/density.ts`、`lib/auth.ts`（token）。**没有第四处保存会话选择**。
3. `grep 'location.hash|history.replaceState|URLSearchParams|useSearchParams'` 在 `web/src` **零命中**——URL 里也没有会话标识，所以刷新既恢复不了，也无法分享/收藏会话，浏览器前进后退也不生效。
4. 初始加载 effect（`App.tsx:149`）只做 `refreshSessions() / fetchModels() / fetchControlCatalogs()`，**不恢复选中**。

**影响**：任何刷新（F5、误触、崩溃恢复、切标签页后重载）都会丢掉当前正在读的会话——长会话尤其痛（用户可能已经翻了很久）。属于「功能可用但体验破损」= P1。

**修复方向**：
1. 持久化选中的 `session_id`（沿用本仓既有 localStorage 惯例，键名 `ahi.` 前缀，如 `ahi.selectedSession`），在 `selectSession` / 分叉跳 child / 新任务落定 sid 时写入；显式回到「新建会话」空态时清除。
2. 首屏在会话列表返回后恢复：存了 id 且**该 id 仍在列表中** → `selectSession(id)`；不在（已被删/不存在）→ 清键并保持空态（不造假入口）。
3. `viewing` 分支本来就会 `GET /events` 重建（`projectHistory`，不变量 #22），所以恢复只需把 mode 设对，不必新增数据通路。
4. 待验证并决定：**流式中刷新**（下面是 BUG-006 的测试）、以及刷新后滚动落点是否要跟随内容。

**未修原因**：本次先完成取证与登记（用户要求实时写入），修复在后续步骤按 `/implement` 进行。

**修复实现（2026-09-11）**：
- 新增 `web/src/lib/sessionRestore.ts`（无 React 依赖，可单测）：`SELECTED_SESSION_KEY = 'ahi.selectedSession'`、`readStoredSessionId` / `writeStoredSessionId`（localStorage 不可用时静默降级，不抛）、`maxEventSeq`（供 BUG-006 接流游标）。
- 新增 `web/src/lib/sessionRestore.test.ts`（4 例）：读写成环；`null` 删键；storage 被拒时不抛不读；`maxEventSeq` 跳过 null / 空集返回 `-1`。
- `web/src/lib/api.ts`：新增 `NotFoundError`，`getSessionEvents` 遇 404 抛它——用于「存的 id 已被删」时静默回落空态，而不是弹错误。
- `web/src/hooks/useSession.ts`：
  - `mode` 改**惰性初始化**：`useState(() => readStoredSessionId() ? {kind:'viewing', sessionId} : {kind:'idle'})`——首帧即选中，**不出现空态闪烁**（这是替换「先 idle 再 effect 里 setMode」写法的原因：后者既闪一下空态，又触发 oxlint `set-state-in-effect`）。
  - 新增持久化 effect：`idle → 删键`；`live/viewing(sid) → 写 sid`。三态 `SessionMode` 是唯一真相（不变量 #22），持久化挂在它上面，不新增第二份状态。
  - 历史装载 `.catch`：`NotFoundError → 删键 + 回 idle`（陈旧 id 自愈）。

**修复验证（同一脚本，刷新前后对照）**：
| 观测量 | 修复前（刷新后） | 修复后（刷新后，**零点击**） |
| --- | --- | --- |
| 侧栏选中行 | 无 | **`1fdac9b9-…`（与刷新前同一行）** |
| `.turn` 轮次 | 0 | **8** |
| 正文指纹 / 长度 | `0` / 0 字符 | **`-271347586` / 4102 字符（与刷新前完全一致）** |
| 主区 | 「暂无对话」空态 | 8 轮对话 + 「已完成 · 4,339 tok」脉冲 |
| 右栏 Inspector | 「未选择会话」 | 「RUN INSPECTOR / 已完成 / run 2ab617e9 / 共 305 条」 |

→ 刷新后与刷新前**逐项一致**（用户要求的「刷新后会话要和刷新前一致」达成）。

---

### BUG-006 流式（run 在途）期间刷新页面：刷新后停在静态快照，不再继续接收【P1 · 已修复（已实机取证）】

**发现时间**：2026-09-11，随 BUG-005 的设计评审一并识别（BUG-005 修好只是「刷新后还能看见已落盘的历史」，**在途 run 的后续事件**是另一个问题）。

**问题**：`viewing` 分支只 `GET /events` 取一次历史快照就收工。若刷新时该会话的 run **仍在后端跑**（ADR-0016 detached-run：订阅者断开不影响 run 继续执行），刷新后 UI 会显示一个「停在半截、看起来已完成」的静态画面，后续事件（工具输出、模型回复、run 终态）再也进不来——直到用户手动再发一条消息。这是**数据正确性**问题：用户看到的不是当前真相。

**归因：前端。** 后端能力齐备且已实测：`GET /api/sessions/{id}/stream?after_seq=N`（T4 #97）会先重放 `after_seq < seq ≤ cursor` 的耐久事件，再**无缝接上实时流**；detached-run 确认有效（实测一次中途刷新，新会话仍产出 69 条事件）。缺的是前端刷新后**主动去接**。

**修复实现（2026-09-11）**：
1. `attachLiveStream` 增加 `opts.resume` + 帧计数器 `framesSeen`。
2. 历史装载后：`hasUnterminatedRun(events)`（`lib/runState` 既有纯函数，判「最后一个 run 无终态」）为真 → `resumeLiveStream(sid, maxEventSeq(events), projected)`。游标取自**已加载事件的最大持久 seq**，正好落在后端「重放 + 续流」契约上，不重不漏。
3. 新增 `resumeLiveStream`：清旧流 → 置 `live` → `streamSession(sid, afterSeq)`；404 则交回历史重跑裁决（已知会话被删 → `NotFoundError` → 清键回 idle，见下方审查 #1）；失败只回 `viewing` + 报错，**不把已渲染的历史打回空态**。
4. **零帧收流兜底**（关键）：若 `resume` 流**一帧未收到就 EOF**，说明「看的时候 run 其实已经跑完了」（刷新与 run 收尾的竞态）——此时**静默回落 `viewing`**，绝不弹「连接断开/重连中」。判据用 `framesSeen === 0 && !terminalSeenRef.current`。
5. **防死循环**：`resumeAttemptedRef` 按 **(sid, 游标)** 记账（`nextResumeAttempt` 纯函数，首轮审查后由 `Set<string>` 改造而来）。若不做这层，上面第 4 条会在「viewing → 接流 → 空流 → viewing」上无限转（该 bug 是自查发现的，已消除）；零帧空流不带来新事件 → 游标不变 → 第二次被拦下。按游标而非只按 sid，是为了不误伤「切走再切回来接着看」——并且 `selectSession`（用户显式切会话）会 `forgetResumeAttempt` 再彻底放行一次。刷新页面即重置，记录清空。

**已验证**：刷新与 run 收尾的竞态（第 4 条）——在 run 恰好于刷新窗口内完成的会话上刷新，UI 稳定落在 9 轮 / 「已完成 · 9,251 tok」，终态文本完整，**无错误横幅、无重连横幅**（兜底按设计静默生效）。

**实机正向取证（2026-09-11，决定性）**：

测试任务：新会话发 `用 bash 工具依次执行三条命令：sleep 10 && echo MARKER-A1 / A2 / A3…`（预计在途 ~30s）。

1. 提交后 5s，run **确在途**：新会话 `affd6084-1c04-4580-b24a-150387cc0fbb`，`pulse = 思考中 · 15s`，事件仅到 `run/started`、`model/started`；`ahi.selectedSession` = 该新会话。
2. **此刻 F5 刷新**（run 未结束）。刷新后 3s 观测：
   - 侧栏选中行已恢复 = `affd6084-…`；`stored` 同值；用户消息在。
   - `reconnecting = false`、**无「连接断开/重连」横幅**、**无空态**。
   - Inspector 已渲染事件 0–6，其中 `6 tool/call bash {"command":"sleep 10 && echo MARKER-A1"}`。

3. **网络层铁证**：`reqid=2380 GET /api/sessions/affd6084-…/stream?after_seq=2 [200]`。
   说明：刷新时 `GET /events` 快照只到 **seq 2**（`run/started`），`maxEventSeq` = 2 → 前端以 `after_seq=2` 接流；**事件 3–6（text/delta、tool/call）是经由这条流重放+续送达的**，而不是历史快照。

4. **零交互前进（决定性）**：此后**不碰页面**等待 16s，事件从 **3 → 54** 条，Inspector 末条 = `53 run/completed`，`pulse = 已完成 · 15,306 tok`。静态快照不可能自增——**证明实时流已接上并跟到终态**。

5. **与后端真值逐项对账**（`GET /api/sessions/{id}/events`）：服务端 54 条、seq 0–53、**重复 0、空洞 0**；UI 显示 54 条、末条 53。→ 「无缝无重复」契约在 UI 侧成立（游标取自已加载事件的最大持久 seq，恰好落在重放区间）。

**结论**：BUG-006 修复有效。「刷新后会话与刷新前一致」不仅覆盖已落盘历史（BUG-005），也覆盖**在途 run 的后续事件**（BUG-006）。

**附注**：本次 run 用的模型是 `deepseek-v4-flash-0731`，全程正常收口（`run/completed`）。对照 OBS-008 的 `glm-5.3-flash` 失败——**佐证 OBS-008 是 provider 侧的模型不稳定，与前端无关**。

---

### BUG-001 分叉按钮 422：`turn.step_id` 不是后端要的用户消息 seq 【P0 · 已修复（8469a34）】

**发现时间**：2026-09-10 真实浏览器点击测试（会话 28eb3302，点第 2 轮的「分叉」）

**修复时间**：2026-09-10（commit `8469a34`）；回归锁与补强 2026-09-11

**现象**：点击用户消息上的「分叉」按钮 → `POST /api/sessions/{id}/forks` 返回 **422**，UI 无任何反馈（静默失败）。

**网络证据**：
- 请求体：`{"from_seq": 2}`
- 响应：`{"detail": "fork 边界 seq=2 不是父会话中的用户消息（可用边界: [1, 30, 46, 62, 199]）"}`

**根因**（`web/src/components/Conversation.tsx:290`）：
```tsx
onClick={() => onFork(turn.step_id)}
```
前端传的是 `turn.step_id`——这是投影层 `resolveStep` 为轮次分组**前端合成**的 step 值；而后端 fork 锚点要求的是**用户消息事件在 JSONL 里的 `seq`**（后端报错里列的可用边界 `[1, 30, 46, 62, 199]` 正是该会话 5 条 user/message 的 seq）。真实数据里 `user/message` 事件的 `step_id=None`，两个语义完全不同。

**修复方向**（最小方案）：
1. 投影层：`projectUserMessage` 已经拿得到 `event.seq`（user/message 的 seq 就是合法锚点），在 `Turn` 上记录 `user_message_seq: number`（per-turn 事实，与 T9 turn_index 落当轮同一模式）。
2. `Conversation.tsx:290`：`onFork(turn.user_message_seq ?? turn.step_id)` 改为只传 `user_message_seq`；没有该字段的历史 turn 显示分叉按钮但点击时给出提示，或对缺锚点的轮不渲染按钮（不造假入口）。
3. 错误反馈：`handleFork`（`web/src/App.tsx:312`）的 `catch {}` 是**空吞**——422/409 用户毫无感知。至少 `setError(...)` 显示后端 detail；409（在途 run）单独提示「等当前 run 结束再分叉」。

**实际落地**：
1. `Turn.user_message_seq: number | null`（`types.ts`）；`projectUserMessage` 仅在 `event.seq !== null` 时写入（`projection.ts`）——不伪造锚点。
2. 按钮只在 `onFork && status !== 'streaming' && user_message_seq !== null` 时渲染，点击传 `user_message_seq`；缺锚点不造假入口。
3. `forkSession`（`api.ts`）解析后端 `detail`；`handleFork` 的 catch 改为 `setForkError(\`分叉失败：${message}\`)`，渲染为 `role="alert"`。
4. 2026-09-11 code-review 补强：
   - 第 1 轮的按钮加 tooltip「本轮之前没有历史：child 会话将是空会话」——后端允许首个 user 消息当锚点，得到的 child 继承 model + 空 workspace，合法但反直觉，提前说清（交接手册 §B.3）。
   - `handleFork` 的结局（跳 child / 弹错误）落地前用 `selectedIdRef` 校验用户仍停在发起会话上，切走即丢弃（stale-write 纪律）；切会话的两条入口（会话栏选择 / 分叉跳 child）**同步**写该 ref，把「已切走但 effect 还没 flush」的窗口压到零。
   - `forkError` 带上发起它的 `sessionId`，只在与当前选中会话一致时渲染——**不是**在切会话时清空（少了 effect 与额外渲染）；代价是切回原会话仍会看到那条旧错误，符合「它确实是在那个会话上失败的」。
   - 分叉请求在途时忽略重复点击（`forkInFlightRef`）：按钮没有 pending 态，连点会在后端造出两个 child 会话。
   - 后端**未**新增端点——遵循交接手册 §B.4「建议不加」。

**回归**：
- `web/e2e/b-fork.spec.ts` B1 锁 `from_seq === 30`（user/message 的 seq，而非 turn 序号 2）；夹具刻意让 seq 与 turn 序号错开，且 `user/message` 不写 `step_id`（真实信封形状）。**变异测试**：把 `onFork(turn.user_message_seq!)` 改回 `onFork(turn.step_id)` → B1 变红；改回即绿。
- `web/src/lib/projection.test.ts`：新增两条——持久 seq 落到 `user_message_seq`（不写合成 step 号）、`seq === null` 不伪造锚点。
- `web/src/components/Conversation.test.tsx`：`TurnView — 分叉入口（BUG-001）` 6 条 SSR 契约。

---

### OBS-005 非默认 amend 档位会让模型调用 400【观察项 · 疑似后端/provider】

**发现时间**：2026-09-11 真实浏览器点击巡检

**现象**：把 Composer 控制行改成 `Agent Profile=编程` + `Reasoning Effort=深度` 后提交任务，连续 2 次都在 `seq=3` 落 `model/failed: "model call failed: BadRequestError"` → `run/failed`（会话 `ba4faa9a-…` / `70cca9c0-…`，`D:\intelligence-agent` 存储）。把两个档位都改回默认（`通用` / `标准`）后**同一任务立刻正常流式输出**。

**初步判断**：`agent_profile` / `reasoning_effort` 作为 amend 字段透传给 provider 时被拒（400）。前端只是把控制行选中的值放进 payload（`api.test.ts` 已锁 payload 形状），没有加工——**疑似后端/provider 侧对这些档位的处理**。需要后端确认这两个档位在 `senseaudio` 上是否受支持。

**前端表现（正常）**：run 失败被正确消费为「失败」run pulse + turn 渲染，无崩溃、无假成功。

---

### OBS-006 审批卡（#37）「不可达」结论**已证伪**——两个按钮已真机点击【已闭合】

**原登记（错误）**：`App.tsx` 提交任务硬编码 `auto_approve: true` → 待审批项永不产生 → 卡片不可达；且 `ApprovalCard.tsx` 无测试、`e2e/` 无对应 spec。

**为什么错**（同一类错误的第二次：把「我没找到路径」当成「不存在路径」）：

1. 卡片的渲染完全由 **`tool/approval-requested` 事件**驱动（`projection.ts:514` 填 `pending_approvals` → `Conversation.tsx:348` 渲染），**与 `auto_approve` 无关**——`auto_approve` 只是 create 请求的 deprecated alias。
2. 后端真正的开关是 `session/service.py:348`：`interactive = permission_mode_explicit and permission_mode != danger-full-access`。**只要客户端显式传 `permission_mode`，交互式审批即开启**（`app.py:199` 明载「两者同传时 `permission_mode` 优先」）。
3. 前端**确实会传**：Composer 权限档位选择器 → `toCreateControls()` 的 `permission_mode`（`lib/amend.ts:47`）→ 键存在即 `permission_mode_explicit=True`。
4. 至于「哪个工具会被拦」：`tooling/approval.py:80` 的 `needs_approval`——policy=`read-only` 时任何 `workspace-write` 工具都需审批，`executor.py:659` 随即调 callback 发事件。

**真机证据（真实后端 + 真实模型 + 真实浏览器点击，无任何 `page.route` mock）**：

| 步骤 | 结果 |
| --- | --- |
| Composer 选「只读」→ 提交「创建工作区文件」 | 卡片渲染（「需要审批」+ 工具名 `write` + 参数预览含目标路径） |
| 点「批准」 | 卡片变「已批准」、按钮消失；`POST /approve` 体 `{approved: true, decision: 'approve_once'}` |
| 点「拒绝」 | 卡片变「已拒绝」、按钮消失；请求体 `{approved: false, decision: 'deny'}` |

落盘证据（`events.jsonl`，durable，**由联调车道自身的断言轮询**）：批准会话 `8e06984e` seq 26 `tool/approval-requested`(write) → seq 27 `permission/resolved` **decision=approve_once**；拒绝会话 `4c5a30c4` seq 30 requested → seq 31 resolved **decision=deny**。**后端把人类决策持久化了**，且这一步现在是**测试断言**（`expect.poll` 后端 `/events`），不再只是人工观察。联调车道 2 passed（2.1 分钟，含真实模型往返）。

**回归锁**：`web/e2e/n-approval-card.spec.ts`（4 用例 × 2 视口）用同形状 fixture 锁前端契约——事件→卡片渲染（工具名/参数预览）、批准/拒绝两键的**决策标签 + 按钮消失 + POST 请求体 + 请求 URL 的会话 id**、`permission/resolved` 把卡片移出待决队列。变异验证 5 处全部变红：批准 `onClick` 置空、拒绝 `onClick` 置空、`api.ts` 的 `decision` 线格式固定成 `approve_once`（**只有请求体断言能抓到**）、`api.ts` 的会话 id 换成常量（**只有 URL 断言能抓到**）、`projection.ts` 的 resolved 移除分支短路。

**保留结论**：默认路径（不选权限档位）下不会出现审批卡——这是**正确的产品默认**，不是缺口。要让普通用户看到卡片，UI 需在选「只读」时给出提示；是否把交互式审批做成默认档位属产品决策，不在本轮范围。

**注**：真机脚本**已入库但走独立车道**——`web/e2e-live/approval-live.spec.ts` + `web/playwright.live.config.ts`。主车道只扫 `./e2e`，**不会**把这条依赖真后端/真模型的用例拉进门禁（结果非确定：模型是否调工具由模型决定）；跑它用
`npx playwright test --config playwright.live.config.ts`（需后端已启动）。

---

### BUG-004 命令面板「Copy Run ID」复制的是 session id【P2 · 已修复（本次）】

**发现时间**：2026-09-11 真实浏览器点击巡检（Ctrl+K 面板逐条点击）

**现象**：命令面板执行「Copy Run ID」后，剪贴板得到的是**会话 id**，不是 run id。标签与动作不一致——两者都是 UUID，粘到日志查询/后端工单里只能用错地方才发现。

**根因**（`web/src/App.tsx` 创建命令处）：
```tsx
label: 'Copy Run ID',
hint: conversation ? conversation.session_id.slice(0, 12) : undefined,
run: () => conversation && copyText(conversation.session_id),
```
`ConversationState.run_id` 本来就存在（`types.ts`，注释写明「PRD §8.2 Inspector 头部 Run ID」），命令却抄了近处的 `session_id`。同区域的 `Copy Trace ID` / `Open Trace` 有 splice 兜底（值缺则命令移除），这条没有——`run_id` 为空时会留下一个点了没反应的假按钮。

**修复**：`run` 改为 `copyText(conversation.run_id)`；`run_id` 缺失时该命令整个不进入列表（条件展开生成，与 Trace 两条的「值缺则不出现」同一纪律）。

**回归**：`e2e/i-keyboard.spec.ts` 新增用例——夹具里 run id(`e2e-run-0002`) 与 session id(`e2e-session-0002`) 刻意不同，断言剪贴板等于 run id。**变异测试**：把 run 改回 `copyText(conversation.session_id)` → 断言变红（`Expected "e2e-run-0002" / Received "e2e-session-0002"`），改回即绿。

---

### BUG-003 工具输出面板内滚动会误触发对话「脱离跟随」【P1 · 已修复（本次）】

**发现时间**：2026-09-11 独立 code-review（Standards 轴，非用户报告）

**根因**：修 BUG 里的滚动问题时给 `.conversation-scroll` 加了 `wheel` 监听（用户上滚 → 同步脱离跟随）。但 `wheel` **冒泡**：工具输出面板 `.tool-out-body`（`max-height: 200px; overflow-y: auto`）与 reasoning 展开体本身就是独立滚动容器，在它们内部上滚同样会冒到会话容器，于是**对话根本没动**却脱离了跟随、弹出「↓ 最新」，之后所有 delta 都不再贴底。这是本次修复引入的回归（改动前的代码没有 wheel 监听）。

**修复**：`onWheel` 先沿 `e.target` 向上走到会话容器，把链上每个「可上滚的嵌套滚动容器」（`scrollHeight > clientHeight` 且 `overflow-y: auto|scroll`）的 `scrollTop` **累加**，再与本次上滚的位移比较：合计够 = 嵌套链吃下了这一下，忽略；不够 = 外层会被推动，释放跟随。累加（而不是「遇到第一个有余量的就忽略」）是必须的——浏览器按最内层→外层顺序分担，单看最内层会在内外层分担时误判「外层要动」，而「有余量就算」会在外层确实被推动时误判为不动（跟随仍为真、下一次 delta 把视口拽回，即原症状）。位移按 `deltaMode` 折算（像素 / ×16px 每行 / ×视口高每页）。算术收在 `lib/followLatest.ts` 的 `nestedChainAbsorbs` / `wheelDeltaPixels`。

另外补一条同类误报：容器已在顶部（`scrollTop <= 0`，内容没超视口或已滚到头）时上滚什么都不会动，不算「要离开底部」——`onWheel` 直接返回，否则浮标会为一次没发生的滚动弹出来。

**回归**：`lib/followLatest.test.ts` 锁累加语义、边界与 `deltaMode` 折算（含空链）；`e2e/j-scroll.spec.ts` 的浮标用例覆盖「对话容器内上滚」这一半；**按 DOM 走链收集余量那一半**（组件内 `parentElement` 循环）无自动化，属人工验证范围。

---

### BUG-002 交接手册 `HANDOFF_WORKBUDDY_FRONTEND.md` 关于 T9 的结论已过期 【P2 · 已勘误（2026-09-11）】

**发现时间**：2026-09-10 真实浏览器测试

**现象**：手册写「T9 未完成——TurnView 不渲染轮次标签」，但实际页面已真实渲染「第 1 轮」~「第 6 轮」。

**根因**：commit `cddea36`（T9 轮次标签 UI）已在当前 HEAD 里，手册是基于旧快照写的。**workbuddy 若照手册做会重复实现。**

**勘误（2026-09-11）**：手册 §1/§2 已正确写明「T9 已完成（`cddea36`）」，但 §7 注意事项第 5 条仍留着旧结论「T9 是唯一剩余工作」，**文档内部自相矛盾**——照做仍会重复实现。已删除该条并替换为指向 `SDD_TICKET_TRACKER.md` 的当前剩余项；§6 门禁基线（408/46）同时刷新为当日实跑值（494/96）并标注日期。

---

### OBS-001 续聊 run 失败：`model call failed: BadRequestError` 【观察项 · 非前端 bug】

**发现时间**：2026-09-10 测试「会话级模型切换后续聊」

**现象**：切到 `glm-5.3-flash` 后发消息 → 后端 `model/failed`（`BadRequestError`）→ `run/failed`。

**前端表现**（正常）：header 显示「失败」、第 6 轮 turn 渲染出来、无崩溃。前端行为正确。

**初步判断**：后端模型调用问题（provider `senseaudio` 对该模型返回 400），属后端/环境问题。前端已正确消费 `model/failed` + `run/failed` 终态。

**附注**：这次失败同时验证了 T7 的链路真实可用——`model/changed` 事件（seq=319，`from qwen3.8-27b → to glm-5.3-flash`）落库，续聊请求带上了 amend 档位（`model`/`agent_profile`/`reasoning_effort`）。

---

### OBS-002 preset 任务按钮只在空态显示 【观察项 · 符合设计】

三个 preset 按钮（FizzBuzz / todo.md / 目录结构）只在未选会话的空态渲染，选中会话后消失。符合「空态引导」设计，非 bug，登记备查。

---

### OBS-003 恢复反馈一度会把「补齐 run 终态」谎报成「无可修复项」【已修复（本次）】

**发现时间**：2026-09-11 独立 code-review（Standards + Spec 双轴）

**现象**：`repaired` 只统计回填的 tool/result 条数。当后端只补上了缺失的 run 终态（没有 dangling 工具）时，`repaired === 0` 且入口消失 → 提示落到 `已恢复：无可修复项（会话事件已完整）`——**日志本就不完整、恢复确实修了它**，这句话是谎报。

**修复**：`hasUnterminatedRun(events)` 判定「最后一个 run 有头无尾」；recover 前后各算一次得到 `terminalRepaired`；文案收敛到纯函数 `recoverDoneMessage()`，各结局分别表述（回填 N 条 / 补齐终态 / 两者都有 / 后端没修完可重试 / 真无可修）。两个「没修完」的原因（缺终态 / 悬空工具调用）**分开**传入——`isRecoverableRun` 是 OR，压成一个布尔会在「终态已补、只剩悬空调用」时误报「仍缺 run 终态」。

**回归**：`runState.test.ts` 八条分支单测（含「repaired>0 但仍缺终态必须附可重试提示」「只剩悬空调用不得说仍缺终态」）+ `d-recover.spec.ts` 新增「只补终态」用例（断言不出现「无可修复项」/「已完整」）。

---

### OBS-004 `run/interrupted` 的 `step_id` 缺失：后端排查线索（交接手册 §D 的回执）【已确认 · 非前端 bug】

**发现时间**：2026-09-11

**排查方法**：扫两个 worktree 的真实 JSONL（**当日快照**：71 个会话；后续会话继续累计，比率是承重结论）。

**结果**：`run/interrupted` 共 **4 条**，其中 **2 条的 `step_id` 字段整个缺失**（不是显式 null）：

| session_id | run/started seq | run/interrupted seq | step_id |
| --- | --- | --- | --- |
| `c63ce4d3-3b26-40bb-8e8c-e3af8dd33035` | 2 | 3 | 缺失（`reason: process_restart`） |
| `2f2f3187-fccc-4704-b9a4-f259f82d153d` | 2 | 3 | 缺失（`reason: process_restart`） |
| `f181c5ce-7c84-43f9-b249-efa606293268` | 2 | 15 | 3 |
| `3b35b83d-dcae-476f-8343-9912e40e77d7` | — | 34 | 1 |

**语义**：这两条里 `run/started`（seq 2）之后**没有任何带步号的事件**就中断了（seq 3 就是 `run/interrupted`）——进程在该 run 的第一个步骤开始前死亡，检测器（`detect_unterminated_runs` → `recovery/scan._mark_interrupted`）无从沿用 step_id，于是信封不带该字段。

**前端处置**：`projectRunInterrupted` 把缺失强制为 `null`；横幅文案区分「首个步骤开始前中断」与「第 N 步中断」，不再渲染「第 ? 步」。e2e `d-recover.spec.ts` 两条锁死。

**后端待办**（交接手册 §D 请求的复现 id 即上表）：`detect_unterminated_runs` 的取值路径可对照这两条确认——是「沿用最后见到的 step_id」在无可用值时留空，还是另有分支。

---

### OBS-007 中断的会话显示绿色「已完成」脉冲 + 过期不消的「上次运行…中断」横幅【P2 · 已修复（b4181ad）】

**发现时间**：2026-09-11（独立 code-review，Spec 轴）；**本轮真实浏览器复现并修复**

**现象（实测复现，会话 `c63ce4d3`）**：同一屏同时出现
- `run-pulse pulse-completed` + 文案「已完成 · 2,583 tok」（**绿色对勾**）
- `.interrupt-banner`「上次运行在首个步骤开始前中断（原因：process_restart）」

**真相（查事件后）**：该会话是 `run/started`(seq 2) → `run/interrupted`(seq 3) → **`run/started`(seq 9) → `run/completed`(seq 14)**。也就是说**中断的那次运行早已被后来一次成功的运行取代**——横幅是**过期提示**，而脉冲说的是**最新 run 的真实结局**。两者打架的根因不是脉冲错，而是**横幅不清**。

**根因（两处，缺一不可）**：
1. `projection.ts: projectRunStarted` 只置 `run_status='running'`，**从不复位 `run_interrupted`** → 该标记一旦置上就挂到会话生命结束；`App.tsx:671` 的横幅只看 `run_interrupted && !streaming` → 永久显示。
2. `projectRunInterrupted` 调 `finalizeRun(state, 'completed', …)`（冻结决策 69：中断 ≠ 失败，而 `finalizeRun` 只有 completed/failed 两档）→ 被中断且**此后再没跑过**的会话，脉冲是绿色「已完成」。

**修复实现**：
1. `projectRunStarted` 清空 `state.run_interrupted`——新 run 开始即「上次运行」已被取代，提示随之过期。语义收窄为：**`run_interrupted` = 最近一个 run 以中断收口**。
2. 新增第四种终态脉冲 `interrupted`：`RunPulseState` + `PULSE_TABLE`（`已中断` / `pulse-interrupted` / `CircleSlash`）+ `coarsenPulseState`（Inspector Overview 同步说「已中断」）+ CSS（复用既有中性语义 token `--text-secondary`/`--color-hover`/`--border-subtle`，**不新增 `:root` 变量，§15 无需补亮色覆盖**）。`deriveRunPulse` **优先看 `run_interrupted`，但连带恒真条件 `run_status === 'completed'`**（详见下方审查第 3 条）——因为 1 已保证该标记只反映最近一个 run，这两者在真实数据里必然同时成立。
3. 为什么必须两处一起改：只加第四态而不清标记，会让「中断后成功重跑」的会话反而显示「已中断」（比原来更错）；只清标记而不加第四态，被中断且未重跑的会话仍谎报绿色「已完成」。

**验证（真实浏览器 + 真实后端）**：
| 会话 | run 序列 | 修复前 | 修复后 |
| --- | --- | --- | --- |
| `c63ce4d3` | 中断 → **完成** | 绿色「已完成」+ 中断横幅（过期） | 脉冲「已完成」，**横幅消失**；Timeline 仍保留 `运行中断` 那一行（历史事实不删） |
| `f181c5ce` | 中断 → **失败** | 「失败」+ 中断横幅（过期） | 脉冲「失败」，**横幅消失**；Timeline 仍保留「第 3 步中断」 |

两例的**恢复入口都不受影响**（`canRecover` 由 `isRecoverableRun(events)` 判定，与本标记无关；两例会话语料本就没有 dangling，故按设计不出现入口）。

**覆盖边界（诚实说明）**：「`已中断` 脉冲」这一态在**当前真实语料里不可达**——两个含 `run/interrupted` 的会话都被后续 run 取代了，没有「中断且从未重跑」的真实会话。故该态由新增单测锁定（`runState.test.ts` 三例 + `projection.test.ts` 一例），未能在真机上目视确认。三例中两例经**变异验证**：把 `coarsenPulseState` 的中断映射改成「已完成」、或去掉 `run_status === 'completed'` 恒真条件，对应断言立刻变红，随后还原。

---

## 已验证正常的交互（2026-09-10 真实点击 17 项 + 2026-09-11 新增第 18–20 项）

| # | 交互 | 结果 |
| --- | --- | --- |
| 1 | 会话列表点击选择会话 | ✓ 319 事件加载，header 显示会话 ID / 状态 / tok |
| 2 | T9 轮次标签 | ✓ 「第 1 轮」~「第 6 轮」per-turn 正确渲染（`cddea36`） |
| 3 | 折叠按钮 | ✓ 变「已折叠 · 0 个工具 · 1 轮 · 5.1s」，内容收起 |
| 4 | Timeline → Chat 反向联动 | ✓ 点 `user/message 什么是rag` 行，chat 滚到目标轮并进入视口 |
| 5 | Timeline 行 → 事件详情 | ✓ StepDetail 打开，显示 seq=199 的 USER/MESSAGE（seq/time/event_id） |
| 6 | 密度四档切换 | ✓ `data-density` 即时生效，localStorage `ahi.traceDensity` 持久 |
| 7 | 主题切换 | ✓ dark ↔ light，`data-theme` 属性正确翻转 |
| 8 | Inspector 收起/展开 | ✓ 收起后面板移除，展开恢复，aria-pressed 正确 |
| 9 | 模型选择器打开/选择 | ✓ dialog + cmdk 列表（默认链 + 5 个模型），选中后按钮文案更新 |
| 10 | **T7 会话级模型切换** | ✓ 已选会话中选模型 → `POST /model` 200 `{status:changed}`，本地状态用响应 `model_id` 更新 |
| 11 | 权限模式选择器 | ✓ 三档（只读/工作区写入/完全访问），描述文案齐全 |
| 12 | Agent Profile 选择器 | ✓ 三档（通用/编程/研究审查），选择生效 |
| 13 | Reasoning Effort 选择器 | ✓ 三档（轻量/标准/深度），选择生效 |
| 14 | 思考块展开 | ✓ aria-expanded 翻转，reasoning 全文展开 |
| 15 | 续聊发送 | ✓ `POST /messages` 200，请求体带 amend 档位（model/agent_profile/reasoning_effort）|
| 16 | run 失败的 UI 呈现 | ✓ header「失败」+ turn 渲染，无崩溃（内容见 OBS-001）|
| 17 | 分叉按钮 | ✓ 已修复 `8469a34`（from_seq = user/message seq，422 detail 可见）——e2e 回归锁 `b-fork.spec.ts` |
| 18 | 恢复会话按钮反馈 | ✓ 已修复——成功落 `done` 提示（在 `canRecover` 门外）；文案区分「回填 N 条 / 补齐 run 终态 / 后端没修完（附具体原因）可重试 / 真无可修」；e2e `d-recover.spec.ts` |
| 19 | 流式中上滚被顶回 | ✓ 已修复——复用 `followLatest` 原语 + 瞬时贴底 + `overflow-anchor: none`；e2e `j-scroll.spec.ts` 用真实 `page.mouse.wheel` 锁可观察契约（上滚→浮标出现→点浮标回底）；**竞态本身（delta 到达时是否拽回）无法自动化**，证据见下方真机埋点 |
| 20 | 工具输出面板内上滚 | ✓ 已修复 BUG-003（wheel 冒泡导致的误脱离）；`e2e/j-scroll.spec.ts` 覆盖对话容器侧，嵌套容器侧人工验证 |

### 2026-09-11 全量逐按钮巡检（真实浏览器 + 真实后端，density 详细档）

| # | 交互 | 结果 |
| --- | --- | --- |
| 21 | 密度四档 | ✓ 紧凑/均衡/详细/Raw 均生效，`data-density` + localStorage `ahi.traceDensity` 同步，`.density-btn.sel` 跟随 |
| 22 | 主题切换 | ✓ dark ↔ light；亮色下截图逐项检查，文字/边框/工具卡/Inspector 对比度正常（无 §15 token 漏覆盖） |
| 23 | Inspector 收起/展开 | ✓ `.step-detail` 常驻 DOM，收起时 `.app-regions.inspector-closed` 归零宽度，展开恢复 320px |
| 24 | Workspace 模式 Chat/Split/Preview | ✓ 三者互斥选中，`aria-pressed` 跟随 |
| 25 | 模型选择器 | ✓ 5 项（默认链 + 4 模型），短目录无搜索框，选中后 trigger 文案更新 |
| 26 | 权限模式选择器 | ✓ 3 档带描述，选中回填 trigger |
| 27 | Agent Profile 选择器 | ✓ 3 档，选中回填 trigger |
| 28 | Reasoning Effort 选择器 | ✓ 3 档，选中回填 trigger |
| 29 | Context Provider 选择器 | ✓ **正确地不渲染**——后端 `/api/context-providers` 返回空列表，零伪造 |
| 30 | 空态 preset chip | ✓ 点击填入 Composer 并启用发送 |
| 31 | 发送 / ⌘+Enter | ✓ 空内容禁用；有内容可发；真实 run 流式输出（caret + run pulse 思考中/执行工具） |
| 32 | 停止按钮 | ✓ 流式中出现 `.composer-stop`、控制行禁用；点击后 run pulse → **已取消**（中性通道，非红色失败），按钮复位 |
| 33 | 思考块展开 | ✓ `aria-expanded` false→true，正文 258 字符渲染 |
| 34 | 工具卡展开/折叠 | ✓ `.act-node` 本身为按钮，detailed 档 `aria-expanded` 跟随；折叠按钮「折叠 ↔ 已折叠 · N 个工具 · M 轮 · Xs」 |
| 35 | 复制回答 | ✓ `aria-label` 复制回答→已复制，**系统剪贴板实测拿到回答正文** |
| 36 | Timeline 行 → StepDetail | ✓ 点 `model/completed` 行 → Inspector 切到事件焦点（`返回 Timeline`），返回按钮复位到 Run Inspector |
| 37 | 工具卡 Inspect | ✓ Inspector 切到该工具（focusType=bash，Input/Output/Raw 分页） |
| 38 | 委派节点 | ✓ 展开 `委派 → research_review` + 结果摘要区；复制子会话 ID（剪贴板实测）；Inspect 子会话；**打开子会话** → 主窗口切到 child |
| 39 | Ctrl+K 命令面板 | ✓ 唤起/输入过滤/Enter 执行/Esc 关闭；执行 Toggle Theme、Copy Run ID 等；**发现并修复 BUG-004** |
| 40 | 分叉按钮 | ✓ 真实点击 → 后端建 child、主窗口切到 child、child 为空会话（与首轮 tooltip 承诺一致）；分叉错误可见 |
| 41 | 恢复会话 | ✓ 真实 dangling 会话（停止 run 留下）→ 点击 → **「已恢复：回填 1 条工具结果」**，入口与 hint 消失而成功提示保留（原症状已消除） |
| 42 | 中断横幅 | ✓ 真实会话 `c63ce4d3-…`（run/interrupted 无 step_id）显示「上次运行在首个步骤开始前中断（原因：process_restart）」 |
| 43 | 浮标 ↓ 最新 | ✓ 见第 19 项（真实 wheel 上滚 → 浮标 → 点回底） |
| 未及 | 审批卡（#37） | ~~⚠ 本 UI 不可达~~ **已证伪并闭合**：显式选权限档位即开启交互式审批，两键已真机点击——见 OBS-006 订正条 |
| 73 ★ | `复制 Trace ID` / `打开 Trace` | ✓ 两条**确实渲染且工作**（初版误判为「不可达」，已订正，见 OBS-010）。实测会话 `f181c5ce`：`复制 Trace ID` 经拦截 `clipboard.writeText` 拿到实参 `2482fcee…43b1`（与 seq 33 `run/failed` 的 `trace_id` 逐字一致）；`打开 Trace` 经拦截 `window.open` 拿到 `https://jp.cloud.langfuse.com/project/…/traces/2482fcee…`、`_blank`。⚠ 用例的可达条件：会话的 run 终态事件带 `trace_id`/`trace_url`（取自 `conversation.*`，**不依赖会话列表**） |
| 74 ★ | 中断态脉冲与横幅的一致性（OBS-007 修复后复验） | ✓ 会话 `c63ce4d3`（中断→**完成**）：脉冲「已完成」且**过期中断横幅消失**；会话 `f181c5ce`（中断→**失败**）：脉冲「失败」且**横幅消失**。两例 Timeline 仍保留 `运行中断` / `第 3 步中断` 的历史行（事实不删）；恢复入口不受影响（`canRecover` 由事件判定）。⚠「已中断」脉冲态当前真实语料不可达（无「中断且从未重跑」的会话），由单测锁定 |

**第 19 项的真机证据（2026-09-11，dev server + 真实后端）**：会话内提交 2500 行生成任务，流式中用真实 wheel 事件上滚并对 `scrollTop` 打点（临时埋点，验证后已移除）——

```
wheel 前: {following:true}
wheel:    {deltaY:-120, runActive:true}     → 同步脱离
随后 6×250ms 采样: dTop 全为 0，gap 7221→15502（内容在长），相邻 PIN 事件数 0（贴底已静默）
浮标:     streaming:true 期间恒为可见
点浮标后: gap→0、PIN 恢复（following:true）、浮标消失
流结束后: 5×350ms 采样均 pill:false / gap:0（settle 补底生效，无残留浮标）
```

**测试环境**：后端 `localhost:8000`（探测时 71 个真实会话）+ 前端 dev server `localhost:5173`，Chrome 经 CDP 驱动，点击 + 网络面板 + 埋点三重验证。

---

### 2026-09-11 第二轮逐按钮巡检 + 刷新一致性专项（真实浏览器 + 真实后端）

> 起因：用户要求「每个功能按钮都要点一遍」「检查刷新后会话内容还在不在」。本轮把工具栏/Composer/Inspector/命令面板/委派节点全部真机点过，并新增 BUG-005/006 专项。带 ★ 的是本轮新验证。

| # | 交互 | 结果 |
| --- | --- | --- |
| 44 ★ | 密度四档（复验） | ✓ 紧凑/均衡/Raw/详细 → `data-density` = compact/balanced/raw/detailed，`.density-btn.sel` 跟随 |
| 45 ★ | 主题切换（复验） | ✓ light→dark→light，`data-theme` 往返一致（无 §15 token 漏覆盖的可观察症状） |
| 46 ★ | Inspector 收起/展开（复验） | ✓ `.app-regions` ↔ `.app-regions.inspector-closed`，展开恢复原状 |
| 47 ★ | Workspace Chat/Split/Preview | ✓ 三者 `aria-pressed` 互斥（选中 true，另两个 false） |
| 48 ★ | 会话行「新建会话」 | ✓ 回到空态、Composer 就位 |
| 49 ★ | **刷新恢复（BUG-005）** | ✓ 刷新后零点击回到同一会话：选中行/轮次/正文指纹/脉冲逐项一致（详见 BUG-005 修复验证表） |
| 50 ★ | **流式中刷新（BUG-006）** | ✓ `GET /stream?after_seq=2 [200]` 接流，零交互下事件 3 → 54 条直到 `run/completed`；与后端真值 54 条 / 0 重复 / 0 空洞（详见 BUG-006 实机取证） |
| 51 ★ | 模型选择器（复验） | ✓ 5 项（默认链 + 4 模型），选中后 trigger 更新、浮层自动关闭 |
| 52 ★ | 权限模式选择器（复验） | ✓ 3 项（只读/工作区写入/完全访问），选中回填 trigger |
| 53 ★ | Agent Profile 选择器（复验） | ✓ 3 项（通用/编程/研究审查），选中回填 trigger |
| 54 ★ | Reasoning Effort 选择器（复验） | ✓ 3 项（轻量/标准/深度），选中回填 trigger |
| 55 ★ | 选择器浮层关闭语义 | ✓ 选完即关、浮层整体卸载（`totalMenusInDom: 0`）；**「多个浮层同时开着」是合成事件假象**——Radix 靠真实 `pointerdown` 判定外部点击，`.click()` 不产生它。用真实指针序列复测：全部正常 |
| 56 ★ | Inspector 五个 Tab | ✓ Timeline（事件行）/ Overview（run+session 摘要）/ Changes（「本次会话未产生文件变更。」）/ Terminal（真实命令回显 `$sleep 10 && echo MARKER-A1`）/ Artifacts（「本次会话未产生 Artifact。」）——空态文案诚实，无伪造 |
| 57 ★ | 命令面板 Ctrl+K（复验） | ✓ 50 项（11 静态命令 + 39 最近事件）；fuzzy 子序列过滤正确（`toggle`/`Compact`/`Copy`/`MARKER-A2` 均精准命中）；页脚快捷键提示在位。**新发现 BUG-007（label 全英文）** |
| 58 ★ | 工具卡展开/折叠 | ✓ `aria-expanded` true→false→true（首次测出「点不动」实为前一步折叠了整轮导致的连带现象，隔离后正常） |
| 59 ★ | 复制回答 | ✓ `aria-label` 复制回答 → 已复制 |
| 60 ★ | 工具卡 Inspect 芯片 | ✓ Inspector 切到事件焦点，出现「返回 Timeline」返回affordance |
| 61 ★ | 委派节点（真实会话 `7b84625c`） | ✓ 展开 true↔false；**复制子会话 ID** → 已复制；**Inspect 子会话** → Inspector 切到 `delegate target="research_review"`；**打开子会话** → 主窗口切到 child `2515a128`（2 轮内容），且 `ahi.selectedSession` 同步为 child |
| 62 ★ | 分叉按钮 | ✓ 真实点击 → 后端建 child `19c76d4b`（行数 69→70）、主窗口切到 child、child 为空会话 + 空态 hero；`POST /api/sessions/{parent}/forks [200]`；`ahi.selectedSession` 同步为 child |
| 63 ★ | 空态 preset chip | ✓ 3 个 chip；点击填入 Composer（「写一个 FizzBuzz 脚本并运行验证」）并启用发送 |
| 64 ★ | 发送禁用态 / 停止按钮 | ✓ 空内容禁用发送；有内容启用；run 中 `.composer-stop` 在场、发送消失、三个控制选择器禁用；点停止 → 脉冲 **「已取消」**（中性通道，非红色失败）、按钮复位、无横幅 |
| 65 ★ | API 身份令牌弹窗 | ✓ 打开：密码输入框（placeholder「粘贴 HS256 token（eyJ…）」）+ 说明文案（localStorage `ahi.apiToken`、claims 要求）；**Esc 真实按键可关**（合成 keydown 关不掉——同一类合成事件假象） |
| 66 ★ | 请求量核对 | ✓ 单次全新加载每端点恰好 2 次（React StrictMode dev 双调用，已知）；静置 3.5s 零增长——**无请求风暴** |
| 67 ★ | 中断横幅（复验，真实会话 `f181c5ce`） | ✓ 横幅「上次运行在**第 3 步**中断（原因：process_restart）」+ 文档内「第 3 步中断」标记；同一会话的工具卡另显示「工具 'bash' 执行超时（上限 10.0 秒）…可稍后重试」——**独立复现 OBS-009** |
| 68 ★ | 恢复会话按钮的**诚实自隐** | ✓ 两个含 `run/interrupted` 的真实会话（`f181c5ce` 末态 `run/failed`、`c63ce4d3` 末态 `run/completed`）都**不显示**恢复入口——因为它们的 run 都已有终态，确实**没有东西可修**。另：我本轮的「停止」实验（会话 `19c76d4b`）留下的是 `run/failed(reason=cancelled)` 干净终态，因此也不出现恢复入口。**这是正确行为不是缺按钮**：入口只在真有 dangling（tool/call 缺 result、或 run 缺终态）时才出现 |
| 69 ★ | 命令面板本地化（BUG-007 修复后复验） | ✓ 静态命令 label 全部中文（该会话 11 条俱在）；中文查询「主题/复制/密度/紧凑」命中，英文 `toggle theme`/`Copy Run`/`compact` 经 keywords 仍命中 |
| 70 ★ | Workspace Chat/Split/Preview（深挖，非仅 aria） | ✓ Chat **不渲染**占位行（零垂直占用，与源码注释一致）；Split/Preview 渲染 `.workspace-scaffold`，带「未来升级点」标签 + 各自说明文案（Split=另一视图 diff/预览，Preview=渲染 Artifact）——**是标注清楚的预留位，不是假面板**；三者切换间 Chat 主阅读面与 4 轮内容始终在位，切回 Chat 占位行消失 |
| 71 ★ | Timeline 行直接点击 → StepDetail | ✓ 点 `3 model/completed qwen3.8-flash · 2170 tok` 行 → Inspector 切到该事件（出现「返回 Timeline」）；点返回 → 复位到 Run Inspector（34 行 Timeline 全部可点） |
| 72 ★ | 命令面板**逐条执行**（不只搜到） | ✓ `切换 Run Inspector` → `app-regions` 加 `inspector-closed`；`切换主题` light→dark；`切换到紧凑` detailed→compact；`跳到最新事件` → Inspector 切到最后一条事件（`run/failed`）并出现「返回 Timeline」；`聚焦输入框` → 焦点落到 `textarea#composer-input`（与命令实现里的 id 逐字一致）。执行后已把主题/密度还原 |

**本轮未复验（依赖特定现场，沿用上轮结论）**：审批卡（OBS-006：~~UI 不可达~~ **第四轮已证伪并真机点击，见该条订正**）、浮标↓最新（上轮埋点验证）、恢复会话按钮的**正向**点击（上轮以真实 dangling 会话验证过成功反馈「已恢复：回填 1 条工具结果」；本轮语料里两个 interrupted 会话都无 dangling，故入口按设计不出现——见第 68 行）。

**合成事件假象清单（本轮新增，避免下次误报）**：Radix 系浮层/弹窗的外部点击关闭与 Esc 关闭依赖**真实** `pointerdown`/`keydown`；`element.click()` 与 `dispatchEvent(new KeyboardEvent(...))` 都不触发，会造成「浮层关不掉 / 多个同时开着 / Esc 无效」的假象。复测一律用真实指针序列或 CDP 按键。

---

## /code-review 第一轮（2026-09-11，BUG-005/006 未提交 diff）——6 findings 处置

审查范围：`web/src/lib/sessionRestore.ts`(+test)、`web/src/lib/api.ts`、`web/src/hooks/useSession.ts`。两轴（Standards + Spec/不变量）。**无 P0 / 无 P1**；3×P2 + 3×P3，逐条处置如下。

| # | 级别 | 结论 | 处置 |
| --- | --- | --- | --- |
| 1 | P2 | **成立**——resume-404 分支的 `writeStoredSessionId(null)` 是**死写**：紧接着 `setMode(viewing(sid))`，持久化 effect 会在同一批次把 sid 写回去，清了等于没清 | **已修**：删掉那行死写并写明理由。真正的「会话已被删」由紧随其后的历史重跑兜住（mode 变更 → `getSessionEvents` 404 → `NotFoundError` → 清键 + 回 idle，**那次落得住**） |
| 2 | P2 | **成立且重要**——`resumeAttemptedRef: Set<string>` 只按 sid 记账，会把**正当的再次恢复**也一并禁掉：A 会话接流成功 → 给 A 续聊 → 切到 B 再切回 A（期间 A 的新 run 在跑）→ 自动接流被拒 → 冻结在历史快照 | **已修**：改为按 **(sid, 游标)** 记账（`nextResumeAttempt` 纯函数）。死循环的断点仍在（零帧空流不带来新事件 → 游标不变 → 拦下），而「有新事件」时游标变大 → 允许再接。**追加加固**：`selectSession`（用户显式切会话）再调 `forgetResumeAttempt` 忘掉该 sid 的记账——消除「两次尝试之间只落了非持久帧（seq=null）→ 游标不变 → 手动切回来被误拦」这个边角；自动重入的死循环不经过 `selectSession`，断点不受影响 |
| 3 | P2 | **成立**——接流逻辑（本次改动的核心行为）无任何测试；`api.test.ts` 也没覆盖新增的 `NotFoundError` | **已修**：新增 `e2e/k-refresh-restore.spec.ts`（4 用例 × 2 视口 = 8 例）、`sessionRestore.test.ts` +5 例、`api.test.ts` +3 例 |
| 4 | P3 | 判断项——零帧回落是**全静默**的；若某天后端在 run 活着时返回 200+空 body（契约破坏），用户会永远盯着半截会话且无任何信号 | **接受的取舍**（不改）：零帧 + 干净 EOF 在**已实测的契约**下只能意味着「服务端已无在跑 run」（活着的 run 会把流开着、不会零帧 EOF）。加「延迟复查」会在回调里引入异步与新的重入面，收益不抵复杂度（§9.2）。风险已登记于此 |
| 5 | P3 | **成立（低影响）**——`scheduleReconnect` 的 404 分支也没清存储键 | **不改，补注释**：该分支 `live→viewing` 同样会重跑历史装载 → 404 → `NotFoundError` → 清键 + 回 idle，已在同一 tick 内自愈；单独加一次 `writeStoredSessionId(null)` 与 #1 同理是死写 |
| 6 | P3 | **成立**——diff 引入了一处多余空行 | **已修**：删除 |

**审查确认正确的部分**（作为覆盖凭据）：死循环断点充分（`nextResumeAttempt` 在首个 `await` 前记账；`mode.kind !== 'viewing'` 时历史 effect 早退，`setMode(live)` 不会二次装载）、StrictMode 双调用已被 `cancelled` 守卫挡住、游标数学不重不漏（`after_seq=max` 重放 `(max, cursor]`，`projection` 的 `seenSeqs` 再兜一层去重）、`framesSeen` 计数位置正确（被 mode/sid 拒的帧不计，去重帧计——「流还活着」的语义正确）、`terminalSeenRef` 每流重置、`streamGenRef` 代际守卫在 404/异常两路都复检、不变量 #22 未被破坏（复用同一 `projectHistory` 与唯一 `ConversationState`）、无 CSS/主题改动（§15 不涉及）。

**门禁（改后全量）**：`tsc -b` 0 · `vitest run` **484 passed**（476 → +8）· `oxlint` **35 warnings / 0 errors**（基线持平）· `playwright test --workers=2` **94 passed**（86 → +8）· `vite build` 0。

---

## /code-review 第二轮（对修复后的 diff 复审）——6 项一审 findings 全 RESOLVED，新发现 4 项（1×P2 + 3×P3）

### 一审 6 项的复核结论

| 一审 # | 复核 |
| --- | --- |
| 1（死写） | **RESOLVED**——404 分支只剩 `setMode(viewing)`；mode 对象是新的 → 持久化 effect 与历史 effect 双双重跑 → `/events` 404 → `NotFoundError` → 清键 + `idle`（`idle` 不会自恢复，故粘得住）。代码注释的说法成立（审阅者订正：严格说不是「同一批次」，是一次后续异步拉取，但同样粘得住） |
| 2（Set → 游标 Map） | **RESOLVED**——(a) 零帧分支直接 `setMode(viewing)` **不经过 `selectSession`**，记账因此留存，重装后再调被 `nextResumeAttempt` 拦下 → 死循环断点仍在（只有一条流请求，e2e 锁住）；(b) A→B→A 两条路都通（游标变大放行 / 显式切会话经 `forgetResumeAttempt` 放行）。ref 赋值在 effect 内，oxlint 无新增 refs 告警 |
| 3（补测试） | **PARTIALLY → RESOLVED**（见新发现 A：当时缺写入路径覆盖，已补） |
| 4（零帧静默取舍） | **RESOLVED / 站得住**——零帧 + 干净 EOF 在已实测契约下等于「无在跑 run」；「run 在缺口内收尾」这条竞态仍被覆盖（回到 viewing 会重跑历史、把终态重新渲染出来） |
| 5（重连 404 不清键） | **RESOLVED**——与 #1 同一自愈路径；若 `/events` 反而 200（会话确实还在），保留 id 才是对的。附注：首次历史重跑会多一次注定 404 的接流尝试，随即记上账稳定下来——有界，非循环 |
| 6（多余空行） | **RESOLVED**——五个改动文件无连续空行，`git diff --check` 干净 |

### 新发现 4 项及处置

| 新 # | 级别 | 内容 | 处置 |
| --- | --- | --- | --- |
| A | **P2** | **BUG-005 写入路径零自动化覆盖**——所有 e2e 都用 `addInitScript` 播种，而 `addInitScript` **每次导航（含 `page.reload()`）都会重跑**，所以它们只证明**读**路径；把持久化 effect 整段删掉，全套依然绿——恰好是本批要防的 BUG-005 回归 | **已修**：新增「空态 → 真实点击会话行 → 断言键被写下 → **不重新播种**刷新 → 仍恢复」用例（`k-refresh-restore.spec.ts`）。并做**变异验证**：临时把写入 effect 改为 no-op → 该用例在两个视口都变红（`Expected: "e2e-session-0001" / Received: null`），随后还原。这是本条 finding 的闭环证据。 |
| B | P3 | `useSession.ts:288` 注释称 ref 在 render 期赋值，与实现（effect 内）矛盾，会诱导后人「改回去」 | **已修**：改为「在 effect 里镜像」并加一句「曾据此改过一次，别改回去」 |
| C | P3 | 失败尝试在 `await` **之前**记账，会吃掉该游标的一次自动重试 | **不改 + 补注释写明理由**：这是刻意的。失败路径同样 `setMode(live)` → `setMode(viewing)`，mode 每变一次历史 effect 就重跑；若失败不记账，「失败 → 回 viewing → 重跑 → 再失败」就是**无上限重试**（每轮两条请求）。代价是失败后不自动重试（错误横幅已告知用户），用户重点一次该会话行即经 `selectSession → forgetResumeAttempt` 重新武装 |
| D | P3 | 交接文档定稿早于最后一次改动（测试数 9 vs 12、缺 `forgetResumeAttempt`） | **已修**：`FRONTEND_REFRESH_PERSIST_INTEGRATION_PROMPT.md` 已更新计数、模块导出表与「重新武装」机制 |

### 第二轮额外确认（「无 P0/P1」的依据）

`NotFoundError` 三个调用点：历史 effect 已处理；`doTruncatedRebuild` 走重连自愈；`useChildConversation` 仅读 `.message`（文案更友好，无回归）。`tsconfig` 目标 `es2023` → `class extends Error` 原型链完好，`toBeInstanceOf` 可靠。`maxEventSeq` 返回 `-1` 不会与 `hasUnterminatedRun` 同时成立（`run/started` 必带数字 seq），首帧不会被误判为 gap。`resumeAttemptedRef` 只按「本页会话内选中过的不同会话数」增长，刷新即清，非泄漏。§8 Scope Lock 与 §15 CSS 规则均未被触碰。`test-results/` 已被 `web/.gitignore` 忽略。

**第二轮后的门禁（实跑）**：tsc ✓ · vitest **487 passed**（28 文件）· oxlint **35 warnings / 0 errors** · playwright **96 passed** · vite build ✓。

---

## /code-review（BUG-007 修复，2026-09-11）——4 findings 全是 P3，无 P0/P1/P2

审阅者用**计算**而非目测验证了两条承重主张：①「label 命中的打分逐字不变」——穷举 3 字符以内全部 query × 11 条命令（3072 组），**0 个既有命中失分或改分**；②「英文仍可搜」——`toggle theme` / `compact` 在移除 keywords 后断言即失败，说明新测试真的守住了这个特性。e2e 的 BUG-004 回归锁（复制的是 **run** id 而非 session id）未被削弱。

| # | 级别 | 内容 | 处置 |
| --- | --- | --- | --- |
| 1 | P3 | 注释/文档把排序保证说过头了：「keywords 命中因下标靠后天然排在后面，不会抢位次」**跨命令不成立**——query `to` 下 `切换主题`（keyword `toggle theme`，37 分）会压过 `切换 Run Inspector`（label `Inspector`，21 分） | **已修**：订正为「同一命令内 label 优先；跨命令仍按分数比大小，keywords 命中可能排到前面，这是可接受的」。穷举验证结论写进注释（零既有命中改分） |
| 2 | P3 | 密度命令的 keywords 末尾重复了一次档位名（`switch to ${d} density 密度 ${d}`）；实测 1780 个 3 字符 query **只靠这层重复**命中（如 `aac`/`aca`），纯增噪而正当匹配一次都不受益 | **已修**：去掉尾部重复 token → `switch to ${d} density 密度`（`compact` 仍可由 `switch to compact` 命中） |
| 3 | P3 | 主题命令的**显示** hint 仍是英文（`→ Light` / `→ Dark`），与刚改中文的 label 同属「半本地化」 | **已修**：改 `→ 亮色` / `→ 暗色`（与已加的 keywords 同词）。判为 BUG-007 同一类而非范围外——它是面板里的显示文本；`Langfuse` 这类专有名词保留英文 |
| 4 | P3 | 问题登记簿自身的标题/清点不准：标题说「50 条命令 label 全是英文」（事件项 label 是后端事件类型，故意保留），正文说 11 条而清点只列 9 条 | **已修**：标题收窄为「11 条静态命令」；清点补齐 11 条并标注其中 2 条按契约条件出现（本部署实际渲染 9 条，见 OBS-010） |

**审阅者另附的过程提示**：审阅期间工作区有并发写入（我在同期更新 tracker/提示词文档，纯文档）。已在提交前重核 diff。

**门禁（修复后）**：tsc ✓ · vitest **490 passed** · oxlint **35w 0e** · playwright **96 passed** · vite build ✓。

---

## /code-review（OBS-007 修复，2026-09-11）——0 个可复现 bug（P0/P1/P2 全无），4 项 P3

审阅者独立复核了四条承重主张并**逐条给出反证或确认**：① 排序/优先级安全——不存在 `run_status === 'running'` 与 `run_interrupted` 同为真值的可达状态（`projectRunInterrupted` 必先 `finalizeRun`，而新 run 的 `run/started` 会清标记）；② 重放确定性——`projectRunStarted`/`projectRunInterrupted` 都只写纯函数状态，无时间/随机依赖；③ `run_interrupted` **没有**其他消费者（全仓 grep），改其语义不影响他处；④ `coarsenPulseState` 的穷尽性由编译器保证（实测删掉一个 case 触发 TS2366），非仅注释承诺。另确认 `CircleSlash` 是真实 lucide 导出、CSS 只复用双主题 token、3 条新测试在还原后确实变红、`git diff --check` 干净。

| # | 级别 | 内容 | 处置 |
| --- | --- | --- | --- |
| 1 | P3 | `coarsenPulseState` 的 `'已中断'` 映射**无任何测试断言**（`runState.ts`）：改成任一同类型字符串（如「已完成」）都不会有测试变红，Inspector Overview 会静默回归 | **已修**：在既有中断用例内补 `expect(deriveRunSummary(s).label).toBe('已中断')`——它与脉冲是**两条独立映射**，必须分开断言。已做变异验证（改成「已完成」→ 该用例变红） |
| 2 | P3 | 没有任何测试把 `pulse-interrupted` 这个**类名字符串**与 `app.css` 的**选择器**绑起来——类名字符串本身已被 `runState.test.ts` 锁住，但 CSS 选择器改名后无测试会发现（视觉表现当前恰好不变，因为 `.run-pulse` 基类已是同样的中性 token） | **不改 + 登记为已知覆盖缺口**：这是 JS/CSS 分界的固有限制，仓库无「测试读 CSS 文件」先例；为它引入构建期 CSS 断言属于 §9.2 之外的抽象。此处显式记录，避免被误当作已有覆盖 |
| 3 | P3 | 提前返回**同时覆盖** `failed`/`cancelled`（只要标记为真），而该分支在真实数据里不可达 → 优先级只靠「不变量成立」这一口头约定，无代码/测试约束 | **已修（显式化，非新分支）**：条件补成 `run_interrupted && run_status === 'completed'`。后端不变量保证两条件恒同时成立，故行为对全部合法日志**逐字节不变**（`deriveRunSummary` 的 8 个多 run 会话实测标签无变化）；破坏不变量时退化到「更晚的终态赢」，而非让过期标记把一次失败粉饰成中性色。新增一例锁住该退化语义 |
| 4 | P3 | (a) 后续发消息的 RTT 窗口内会短暂显示「已中断」（提前返回不看 `streaming`）；(b) `CircleSlash` 与邻位方形图标（`SquareCheckBig`/`SquareX`）风格不齐 | **不改（审阅者亦不建议改代码）**：(a) 该瞬时态比修复前的绿色「已完成」更接近真相，且窗口仅一个 RTT；(b) 纯审美，圆形已在图标族内（`CircleDashed` 空闲态）。换图标属无收益改动（§9.3） |

**审阅者结论**：本次修复**与规格一致**（冻结决策 69「中断 ≠ 失败」得到前端一致表达）、**无副作用**（`canRecover` 走 `isRecoverableRun(events)`，与本标记无关）、**范围克制**（§8 未被触碰）。

**门禁（修复后实跑）**：tsc ✓ · vitest **494 passed**（28 文件，+1 例）· oxlint **35 warnings / 0 errors** · playwright **96 passed** · vite build ✓。

---

## 真机验证（2026-09-11 追加）：子会话刷新一致性 + 新增回归锁

**起因**：交接提示词 §3.1 声称「刷新后恢复选中会话（**含分叉 child、委派 child、`打开子会话` 的目标**）」，但该断言当时**只有推断、没有证据**——`k-refresh-restore.spec.ts` 当时 5 个用例全用普通会话 id。用户的核心诉求正是「刷新后必须和刷新前一致」，故补做真机验证。

**方法**：真实浏览器（CDP 驱动）+ 真实后端，对每个子会话取「刷新前 / 刷新后」的正文指纹（bodyLen + 全文哈希 + 轮数 + 脉冲）逐字节对比，**零点击**。语料取自真实 workspace：委派 child `2515a128`（父 `7b84625c`）、分叉 child `1fdac9b9`（410 事件，父 `0c4fdcd0`）。

| 场景 | 入口 | 刷新前 | 刷新后 | 结论 |
| --- | --- | --- | --- | --- |
| 委派 child `2515a128` | 会话列表**点击该行** | hash `818904662` / 4710 字符 / 2 轮 / 脉冲「已完成 · 4,635 tok」 | **逐字节相同** | ✓ 一致 |
| 委派 child `2515a128` | 父会话委派节点的**「打开子会话」按钮** | 同上（切到 child 且键写为 `2515a128`） | **逐字节相同** | ✓ 一致（两条入口收敛到同一状态） |
| 分叉 child `1fdac9b9` | 会话列表点击该行 | hash `-815616722` / 12,887 字符 / 8 轮 / 脉冲「失败 · 28,357 tok」/ Inspector「显示最近 200 / 共 410 条」 | **逐字节相同** | ✓ 一致（大会话同样成立） |

**边界（有意为之，非缺陷）**：右栏的委派**钻取**（`Inspect 子会话` → `.detail-run-id` = child id）在刷新后会退回默认的 run 焦点（刷新后 `.detail-run-id` = 当前 run id）。这与既有冻结决策一致——Inspector 是**视图状态**（`inspectorOpen` 的注释即写明「仅本会话内，不持久化」，DSH 语义），与「会话内容」不是一回事：会话选中与正文全部恢复，只有「你上次在右栏盯着哪个子面板」不恢复。**记录于此，避免后人误判为刷新不一致的 bug。**

**新增回归锁**：`web/e2e/k-refresh-restore.spec.ts` 增 1 例（×2 视口）——「子会话 id 与普通会话同一持久化/恢复路径：非首行真实点击 → 写键 → 刷新恢复」。设计要点（每条都对应一次踩坑或审查意见）：
- 走**真实点击的写入路径**，不用 `addInitScript` 播种（播种每次导航都重跑，只能证明读路径——本轮首版就踩了这个坑：**变异后依然全绿**，见下）；
- 点**非首行**，且 id 是首行 id 的**严格前缀**（`SID` vs `SID-child`）→ 刷新断言真的能区分「恢复了错会话」；
- 事件按请求的 session id 返回**不同正文**（父「父会话正文。」/ child「子会话结论。」），并断言父正文**不出现**——否则 `toContainText` 在恢复错会话时也会通过，等于没锁内容一致性。

**变异验证（两次都要，第一次暴露了测试缺陷）**：
1. 首版（播种式）在「写入按 `-child` 过滤」的变异下**依然全绿** → 证明它只覆盖读路径，遂改真实点击写入路径；
2. 改后同一变异 → 两个视口都红：`Expected: "e2e-session-0001-child" / Received: null`，随后还原。

**本轮审查（对新 e2e 用例）**：**0 个 P0/P1/P2**，5 项 P3——全部指向「注释/标题的说法超出用例实际断言」（合成 fixture 无真委派/分叉事件却写得像自动化复现了真机结果；`toContainText` 无鉴别力；`toBeNull()` 前置断言在全新上下文里恒真）。**5 项已全部处置**：标题与注释改为准确表述并明确「真机验证记在登记簿」、事件按 id 区分、移除恒真断言的误导性说法、行定位改用 `title` 属性前缀（稳定身份，不依赖业务文案）。

**门禁**：tsc ✓ · vitest **494 passed** · oxlint **35w 0e** · playwright **98 passed**（+2）· vite build ✓。

---

## 第三轮：控制面清点（源码 45 个 `<button>` 逐个对照登记簿）

**起因**：前两轮的巡检表是**人工列举**的，无法证明「每个按钮都点过」——这正是用户的硬要求（「每个功能按钮你必须都要点击一下…每个都要点一遍」）。故本轮改用**可核对的方法**：从源码枚举全部交互控件，再逐项对照登记簿。

**方法**：扫 `web/src/**/*.tsx`（排除测试）取全部 `<button>` 标签 → **45 个**，分布在 17 个文件（StepDetail 10、TopBar 6、ToolCard 4、Conversation 4、DelegationNode 3、App 3、SessionList 2、ReasoningBlock 2、Composer 2、ApprovalCard 2、markdown/ModelPicker/JsonTree/CopyButton/ControlPicker/ContextProviderPicker/CommandPalette 各 1）。另有 `onClick` 非 `<button>` 元素 **0 个**（即按钮即全部点击面）。再逐个在登记簿里找覆盖证据。

**结果：11 项此前从未被点过**（前两轮的 74 行表确实漏了）。本轮逐项真机验证后，9 项正常、1 项不可达（已补 e2e）、1 项实际不可达（登记为覆盖缺口）。

### 本轮真机验证通过（9 项 + 附带确认）

| 控件 | 真机证据 |
| --- | --- |
| **Inspector 5 个 tab**（Timeline/Overview/Changes/Terminal/Artifacts） | 各渲染不同内容：Overview = RUN/TOOLS/TRACE/MODEL/CHECKPOINT（状态失败、15 轮、28,357 tok、7 工具 2 失败、410 事件、含 `glm-5.3-flash → glm-4.5-air` 切换史）；Changes = 文件写入前后 diff；Terminal = 5 行 shell 输出；Artifacts = 诚实的「本次会话未产生 Artifact。」；Timeline = 200 行 |
| **加载更早 210 条**（`.timeline-earlier`） | 点击后时间线 **200 → 410 行**（等于该会话真实事件总数），按钮消失，首行变为 `0 session/started`——**不重不漏** |
| **时间线行点击**（`.timeline-row` ×200） | 点 seq 406 `model/completed`：主区滚动 `0 → 5205`，出现 1 个跳转脉冲——反向联动（Inspector → 主区定位）成立 |
| **终端行**（`.detail-terminal-row` ×5） | 点击后 Inspector 头部切为 `bash`、出现返回键、io-tabs 出现 |
| **io-tabs ×4**（Overview/Input/Output/Raw） | 四档渲染各不相同：正文长度 136 / 122 / 276 / 921 字符；JSON 行 0 / 3 / 6 / 29 |
| **JSON 树展开**（`.json-row[aria-expanded]`，5 个可展开） | `args: {1 key}`：`aria-expanded` false → true，行数 29 → 31 |
| **返回父会话 Run 视图**（`.child-back-btn`） | 钻取态点它：从 child `2515a128` 退回父 run `2c2ad2e6`，返回键消失 |
| **代码块换行**（`.md-code-wrap-btn`） | label `自动换行 → 不换行`，class 加 `md-code-wrap`，`aria-label` 同步为「代码不换行」 |
| **停止（工具运行中点）** | 脉冲 → 中性「已取消」，无重连横幅；且**全语料 0 个 dangling tool_call**——取消会把工具收口，**不会**留下虚假的「恢复」入口（配合 `isRecoverableRun` 设计正确） |
| （附带）工具终态输出未丢失 | 卡片展开渲染 `.act-detail-result`（含 `stdout: "LINE-1 \nLINE-2 \nLINE-3 \n"`），Inspector 亦有——流式尾窗关闭**不是**输出丢失 |

### 覆盖缺口 1：`auth-banner-close`——本轮已补 e2e

**不可达原因**：后端仅在配置 `jwt_secret` 时校验令牌并要求 401（`src/agent_harness/web/app.py:594`，未配置则 fail-open），本地开发不设该密钥 → 横幅永不出现。重启后端加密钥属改动后端状态、且超出前端范围，故按**后端已冻结的契约形状**（`lib/auth.ts` 文档：匿名 → 401 `{"detail":"Missing identity token"}`）补 e2e。

**新增** `web/e2e/l-auth-banner.spec.ts`（×2 视口）：401 → 横幅出现（含文案断言）→ 点「关闭提示」→ 横幅消失 → 且**不再自行复现**（把 401 翻成 200 后再断言，否则「关闭后复现」会变成假阴性）。**变异验证**：把 `onClick={() => setAuthRequired(false)}` 改为空实现 → 两个视口都红（`Expected: hidden / Received: visible`，14 次轮询都可见），随后还原。

### 覆盖缺口 2：`tool-out-wrap-btn` / `tool-out-jump`——登记为**实际不可达**（非缺陷）

> **【第四轮已作废本条结论】** 本节的前提是「必须等真实后端出现流式尾窗」，该前提是错的：尾窗的开关是 **projection 状态**，不是网络时序（`ToolCard.tsx:137` 的 `streaming={tool.status === 'running'}`）。用 mock SSE 只发 `tool/output_delta`、**不发** `tool/result`，尾窗即**永久驻留**，两个按钮都变成可控点击。**第四轮实测：两按钮各点击成功并完成变异验证**（`onClick` 改 no-op → 断言立刻变红）。回归锁：`web/e2e/m-stream-affordances.spec.ts`。以下「不可达」叙述仅作历史记录保留。

**机制**（源码 + 事件双侧取证）：输出尾窗的渲染条件是 `tool.output.length > 0 && (status === 'running' || !tool.result)`（`ToolCard.tsx:136`）。而本后端 cmd.exe **缓冲输出**，整段输出以**单个**终态 `tool/output_delta` 到达，`tool/result` 紧随其后——窗口只存在毫秒级。实证：会话 `01fa7167` 的 `echo LINE-1 & ping…` 三个 echo 在 6.2s 内跑完，`tool/output_delta` **仅 1 条**，其 `stdout` 一次性为 `"LINE-1 \nLINE-2 \nLINE-3 \n"`。叠加 bash 工具 **10.0s 硬超时**（见 OBS-014）与模型不确定性（本轮 6 次尝试中出现 1 次模型不改写命令、1 次完全拒绝调用工具、1 次 3.5 分钟退化循环），该窗口是移动靶。

**本轮实际观察到**：窗口确实渲染过（3 次），默认态为 `tool-out-body tool-out-wrap` + 按钮文案「不换行」，内容为真实输出（`LINE-1 LINE-2 LINE-3`）。**未观察到**：换行点击的切换效果、`↓ 最新` 的出现与点击（它还需要「流式中用户上滚」这一叠加条件）。（**第四轮已用 mock 流全部点到并变异验证**，见下文「第四轮」。）

**测试侧现状（本轮时点，勿误认为已覆盖）**：`ToolCard.test.tsx` 只断言窗口的**存在条件**（`tool-out-stream` 的有/无），**没有**换行或跳转的点击用例；`j-scroll.spec.ts:53` 只断言非流式态**不出现** `↓ 最新`。两处点击均无覆盖，也未能在真机点击——如实登记，不当作已完成。（**该缺口已由 `web/e2e/m-stream-affordances.spec.ts` 在第四轮闭合。**）

### 本轮新发现的**后端**问题（含根因文件行号，供后端修复）

#### OBS-011 子进程输出按 UTF-8 解码，而 cmd.exe 输出 GBK → **乱码被持久化进 JSONL**（P2）

**现象**：工具输出在 UI 与**落盘事件**中都成乱码。两次实证：`��ʱ��Ӧ�� i��`（cmd 的「此时不应有 i。」）、`���� Ping 127.0.0.1 …`。

**铁证（区分前后端的关键）**：读 `25fe14b0…/events.jsonl` 的**原始字节**，delta 为
`\xef\xbf\xbd\xef\xbf\xbd\xca\xb1\xef\xbf\xbd…` ——
即 **U+FFFD（`\xef\xbf\xbd`）与"侥幸合法的 UTF-8 双字节"混杂**：`\xca\xb1` 被解成 U+02B1（ʱ）、`\xd3\xa6` 被解成 U+04E6（Ӧ）。GBK 的「时」「应」两字节恰好构成合法 UTF-8 序列 → 剩下非法处变 U+FFFD。文件本身是**合法 UTF-8**、含 **24 个 U+FFFD**。

**归因：后端，且写入发生在事件落盘之前**——前端只是忠实渲染磁盘上的内容。

**根因**：`src/agent_harness/sandbox/local.py:166-167` 的 `encoding="utf-8", errors="replace"`（源码注释已自承认「Windows 中文系统默认 GBK…用 errors=replace 保证不崩」——代价是把乱码固化进了 append-only 事件日志）。同一模式另见 `sandbox/docker.py:140-141`。

**为什么值得修**：JSONL 是本项目可观测性的**单一事实源**（回放 / eval / Langfuse 都读它）。乱码一旦落盘即不可逆，且会让「模型看到的工具输出」与「真相」不一致。

#### OBS-012 `bash` 工具在 Windows 上不是 bash（P2）

**现象**：`for i in $(seq 1 10); do …; done` 41ms 内以 `exit_code=1` 失败，stderr 为 cmd.exe 的「此时不应有 i。」。

**根因**：`sandbox/local.py:161` `shell=True` → Windows 下走 `COMSPEC`（cmd.exe）。

**旁证（同会话 `1fdac9b9`）**：`echo "Current user: $(whoami)"` 的输出里 `$(whoami)` 被**原样回显**（`"Current user: $(whoami)"`）——cmd.exe 不做命令替换；而 `ls -la` 却能工作（PATH 里有 Unix 工具）。模型据此在**同一任务里反复试错**（该会话 4 次 `model/fallback`、7 次工具调用、2 次工具失败）。

**影响**：工具名与语义不符会让模型（与人类）按 bash 语法写命令并莫名失败，直接拉高 token 与失败率。

#### OBS-013 模型退化重复循环 + 频繁 fallback（P2 · provider）

**现象**：会话 `7d5a6f24` 一轮生成 **2,868 个 `text/delta`、共 186,507 字符**，内容为 `"Let me run the command."` 的无限重复，**始终没有发出工具调用**，持续 3.5 分钟后由我点「停止」收口（`model/failed: model call cancelled`）。全语料另有多次 `model/fallback: deepseek-v4-flash-0731 → glm-4.5-air · InternalServerError`。

**归因：provider/后端**。前端表现正确（脉冲「思考中」，文本持续流入，停止可用）。但值得后端评估：该 provider 是否存在重复惩罚/最大生成长度护栏，以及「长时间无工具调用的大段自重复」能否作为可观测信号提前暴露。

#### OBS-014 bash 工具 10.0s 硬超时且 `retryable:false`（与 OBS-009 同族，此处补实证）

`sleep 30 && echo resume-test-done`、`ping -n 45 127.0.0.1` 均以 `TIMEOUT`（`retryable:false`）失败；`ping -n 4` / `sleep 9` 正常。即单条命令**上限 10.0s**，长任务必须由模型自行切分。结合 OBS-013 会出现「想跑长命令 → 超时 → 反复重试/退化」的组合失效。

#### OBS-015 审批卡的 `catch` 把「任何错误」都当成已决——注释与行为相反（P2，**已修复**）

**位置**：`web/src/components/ApprovalCard.tsx:26-33`。

```ts
} catch {
  // 409 = already resolved (idempotent success); other errors leave card pending
  setDecision(approved ? 'approved' : 'denied');
}
```

**问题**：注释写「其它错误保持 pending」，**代码却把任何错误都翻成「已批准/已拒绝」**。后果：审批 POST 真的失败（网络抖动、404、403、后端未接线）时，用户看到的是「已批准/已拒绝」的**乐观假象**，而 run 实际仍卡在等审批（直到 300s fail-closed 超时）。对安全相关的审批交互，这个方向的假象比「转圈不响应」更危险：用户以为放行了。

**证据（本轮反驳「UI 变了 = 决策成功」的直接原因）**：把 `/approve` 改成恒返回 404，UI 依旧显示「已批准」、按钮消失、请求体依旧正确——**只有查后端 `permission/resolved` 才能区分**。故联调车道的判决断言改为轮询后端事件（`e2e-live/approval-live.spec.ts`）。

---

**处置结果（2026-09-11 修复）**：

1. **`api.ts` 新增 `AlreadyResolvedError`**：`postApproval` 在 HTTP 409 时抛 `AlreadyResolvedError`，其它非 ok 抛普通 `Error`。这样调用方可以区分「幂等已决」（409）与「真失败」（5xx/网络）。
2. **`ApprovalCard.tsx` 修复 `decide` 的 catch**：
   - `AlreadyResolvedError`（409）→ 视为幂等成功，翻卡片为「已批准/已拒绝」。
   - 其它错误 → **保持 pending**，显示可见错误提示（`role="alert"`），按钮重新可用，用户可重试。
3. **回归锁**（`e2e/n-approval-card.spec.ts` 新增 2 用例 × 2 视口 = 4 例）：
   - **POST 500 → 卡片保持「需要审批」+ 按钮仍可用 + 出现错误提示**。
   - **POST 409 → 幂等成功，卡片翻「已批准」**。
4. **变异验证**（两处各一次，全部生效）：
   - 把 `ApprovalCard` 的 catch 还原为旧行为（任何错误都翻卡片）→ POST 500 用例变红（`Expected: "需要审批" / Received: "已批准"`）。
   - 把 `AlreadyResolvedError` 分支改为 `if (false)` → POST 409 用例变红（卡片不再翻「已批准」）。

**门禁**：tsc ✓ · vitest **501 passed** · oxlint **35 warnings / 0 errors** · playwright **116 passed** · vite build ✓。

### 本轮审查（对新增的 `l-auth-banner.spec.ts`）：0 个 P0/P1，1 项 **P2** + 4 项 P3——全部已处置

审阅者做了三件我没有做的核验：① 用**实测的网络捕获**确认「横幅出现后到关闭前没有任何 `/api/sessions` 请求」；② 用 `playwright-core@1.63.0` 源码确认「后注册路由优先」；③ **逐字检查了我注释里的覆盖声明**。

| # | 级别 | 内容 | 处置 |
| --- | --- | --- | --- |
| 1 | **P2** | **注释谎报覆盖**：我写「`lib/api.test.ts` 测 401 的分类（`UnauthorizedError`）」，实际该文件**零个 401 引用**——全 `src` 测试树里都搜不到 401/Unauthorized。即 **401→`UnauthorizedError` 这条缝当时根本没有单测** | **已修（把谎报变成事实，而非删掉句子）**：在 `api.test.ts` 新增一组 3 例——401 → 抛 `UnauthorizedError`（且**不是** `NotFoundError`）、401 → `onUnauthorized` 收到后端 detail、**body 非 JSON 时回退文案**（覆盖 `readErrorDetail` 的失败路径）。注释改为准确的两层分工 |
| 2 | P3 | `denied` 开关与 `waitForTimeout(400)` 是**惰性构件**：实测「横幅出现后再无 `/api/sessions` 请求」，故 200 分支永不执行、「关闭后不复现」是**空断言**；且它把真实行为**说反了**——关闭并非永久忽略（`App.tsx:148` 每次广播都会 `setAuthRequired(true)`） | **已修并改成测真实行为**：删掉开关与空等；改为走应用内真实路径「配置令牌」→ `onTokenChange` 先清横幅再 `refreshSessions()` → 后端仍 401 → **断言横幅重新出现**。**变异验证**：删掉那句 `refreshSessions()` → 两视口都红（`Expected: visible`），随后还原 |
| 3 | P3 | 契约形状的 body 只作输入、从未断言被传播；`toContainText('身份令牌')` 命中的是**静态文案**，`readErrorDetail` 坏了也照样通过 | **已修**：detail 的传播与回退文案由上面新增的 3 个单测覆盖；e2e 注释写明「文案是静态的，传播由单测覆盖」，不再暗示 e2e 覆盖了它 |
| 4 | P3 | `toBeHidden()` 在**组件树崩溃卸载**时也会通过（`main.tsx` 无 error boundary），故「点了没反应」与「点崩了」区分不开 | **已修**：关闭后补断言顶栏「API 身份令牌设置」按钮仍可见（页面还在，真的只是横幅关了） |
| 5 | P3 | `getByRole('button', { name: '关闭提示' })` 的 `name` 是归一化子串匹配，当前唯一但不够表态 | **已修**：加 `exact: true` |

**审阅者结论**：**approve with a P2 comment fix**——该用例确实锁住了此前零覆盖的关闭按钮（空 `onClick` 变异会让它红），路由优先级与其余 gate 均确认无误；要求订正注释里的覆盖声明，并把惰性的粘性构件简化或改成测真实行为（两者均已照做）。它另确认：未改动任何生产代码、无其它 spec 与之重复、`oxlint` 仍是 **35 warnings / 0 errors**。

**该轮审查后的门禁（`l-auth-banner`，历史快照）**：tsc ✓ · vitest **497 passed**（+3）· oxlint **35 warnings / 0 errors** · playwright **100 passed** · vite build ✓。

### 修正：文本比对审计本身不可靠（本轮自查，务必以真机点击为准）

上文的「11 项未覆盖」是**文本关键词比对**的产物，复查发现该方法**两个方向都会错**：

- **假阳性（判成已覆盖，实际没点过）**：`保存` 命中的是第 160 行「没有第四处**保存**会话选择」、`清除` 命中的是第 167 行「回到空态时**清除**」——两处都是无关散文，于是**令牌弹窗的「保存」「清除」两个按钮实际从未被点过**，却被判为 OK。同理 `Inspect` 一词的泛命中掩盖了 `act-inspect-chip`。
- **假阴性（判成未覆盖，实际有 e2e 或真机证据）**：`滚动到最新`（第 19 行明确写着 e2e `j-scroll.spec.ts` 用真实 `page.mouse.wheel` 锁「上滚→浮标出现→点浮标回底」）、`恢复会话`（第 41 行：真实 dangling 会话点击 →「已恢复：回填 1 条工具结果」）其实都有覆盖。

**结论：按钮级覆盖率不能用关键词比对裁决。** 故改为**逐个真机点击**，见下表。

### 本轮真机点击的完整清单（新增覆盖，均已确认「点了有反应且符合预期」）

| 控件 | 真机观察到的反应 |
| --- | --- |
| Inspector tab ×5 | Overview/Changes/Terminal/Artifacts/Timeline 各渲染**不同**内容（见上文详表） |
| 加载更早 210 条 | 200 → **410** 行，按钮消失，首行 `0 session/started` |
| 时间线行 ×200 | 主区滚动 `0 → 5205` + 出现 1 个跳转脉冲 |
| 终端行 ×5 | Inspector 头切 `bash`、出现返回键、io-tabs 出现 |
| io-tab ×4 | Overview/Input/Output/Raw 正文长度 136/122/276/921，JSON 行 0/3/6/29 |
| JSON 树行 | `aria-expanded` false → true，行数 29 → 31 |
| 返回父会话 Run 视图 | 从 child `2515a128` 退回父 run `2c2ad2e6` |
| 代码块换行 | 文案 `自动换行 ↔ 不换行`，class 加/去 `md-code-wrap`，`aria-label` 同步 |
| 空态示例 chip ×3 | 点「创建 todo.md，写入三条今日计划」→ Composer 文本被填入该任务 |
| **推理块展开**（`.reasoning-header` ×5） | `aria-expanded` false → true（**此前无任何覆盖**） |
| **Inspect chip**（`.act-inspect-chip` ×3） | 点击 → Inspector 聚焦 `bash` 工具 + 出现返回键（**此前无覆盖**） |
| **Inspector 工具行**（`.detail-tool-row` ×7） | 点 `bash` 行 → Inspector 聚焦该工具（**此前无覆盖**） |
| **令牌保存**（`.auth-panel-save`） | 填 dummy token → 点保存 → `localStorage ahi.apiToken` = 该串（**此前无覆盖**） |
| **令牌清除**（`.auth-panel-clear`） | 点清除 → `ahi.apiToken` 变 `null`（**已还原，无残留**）（**此前无覆盖**） |
| Inspector 展开/收起 | `aria-label` `收起 Inspector ↔ 展开 Inspector` 互换（配合第 8/23 行：`.app-regions.inspector-closed` 归零宽度） |
| 停止（工具运行中） | 脉冲 → 中性「已取消」；**全语料 0 dangling tool_call**——不留虚假恢复入口 |

### 全部 45 个 `<button>` 的最终状态

**逐个文件核对 45 个标签**（StepDetail 10、TopBar 6、ToolCard 4、Conversation 4、DelegationNode 3、App 3、SessionList 2、ReasoningBlock 2、Composer 2、ApprovalCard 2、其余 7 个文件各 1）：

| 状态 | 数量 | 项 |
| --- | --- | --- |
| 真机点击验证通过 | **38** | **前两轮已验**：`detail-back-btn`（返回 Timeline）、`density-btn`（密度四档）、身份令牌图标、主题切换、`act-node`（ToolCard 与 DelegationNode 两处展开）、`fork-btn`、`turn-collapse-btn`、`workspace-mode`、`recover-btn`、`follow-pill`、新建会话、会话行、发送、停止、模型选择、CopyButton、ControlPicker（权限模式）、`palette-item`。**本轮新验**：Inspector `detail-tab` ×2 标签（5 个实例）、`timeline-earlier`、`timeline-row`、`detail-terminal-row`、`io-tab` ×2 标签（4 个实例）、`json-row`、`child-back-btn`、`md-code-wrap-btn`、`example-chip`、`reasoning-header`、`act-inspect-chip`、`detail-tool-row`、`auth-panel-save`、`auth-panel-clear`、Inspector 展开/收起 |
| 不可达 · 已补 e2e | 1 | `auth-banner-close`（本地未配 `jwt_secret`；新增 `l-auth-banner.spec.ts` + 变异验证） |
| 不可达 · 按设计 | ~~3~~ **1** | ~~审批卡「批准」「拒绝」（`auto_approve` 硬编码，OBS-006）~~ **已证伪：两键均已真机点击**；仅剩 `ContextProviderPicker`（本部署后端目录为空 → 正确地不渲染，第 29 行；组件本身由 `picker-search-visibility.spec.ts` 用长目录 fixture 覆盖） |
| **已用可控流补点**（见本文末「第四轮」） | 3 | `tool-out-wrap-btn`、`tool-out-jump`、`reasoning-jump`——**已不再是缺口**：新增 `m-stream-affordances.spec.ts` 用 mock 流把窗口钉住后**真实点击**，三个按钮各经一次变异验证 |
| **审批卡两键**（见 OBS-006 订正条） | 2 | 「批准」「拒绝」——**真机点击**（真实后端 + 真实模型：选「只读」→ `write` 工具触发 `tool/approval-requested` → 点击 → JSONL 持久化 `permission/resolved`）；回归锁 `n-approval-card.spec.ts` |

**该行账目已被「第四轮」取代**（下表为历史快照）：~~`45 = 38 真机 + 4 真实浏览器点击（mock 网络）+ 1 e2e 内激活 + 2 产品不可达`——即 **43/45 已被真实点击**~~ → **现为 45/45**（审批卡两键已证伪「不可达」，见 OBS-006 订正条）。


**附带证据：控制台干净**。走完上述全部点击后，页面控制台（含最近 3 次导航的保留消息）只有 **2 条 error**，且都是**本轮变异验证自身的残留**——临时改坏 `App.tsx` 再还原时，Vite HMR 报了一次 500 与一次「Failed to reload /src/App.tsx」。**没有**任何一条来自被点控件（Inspector tab / io-tab / JSON 展开 / 令牌保存 / 推理展开 / 委派钻取等）的应用级错误。

---

## 第四轮：三个瞬态按钮的确定性覆盖（把「缺口」补成「点过」）

**起因**：第三轮把 `tool-out-wrap-btn` / `tool-out-jump` / `reasoning-jump` 记为「瞬态窗口不可达」——真机六次尝试只看到窗口、点不进去。但「不可达」不等于「不可能」：窗口之所以只有毫秒级，是因为**真实后端缓冲输出**，而不是按钮本身不可及。用**可控 mock 流**把窗口钉住即可确定性地点击。

### 手段：不发终态帧，让容器保持「流式中」

`lib/followLatest.ts:33-38` 决定 `suspended` 只在 `streaming === true` 时置位；而两个容器的 `streaming` 来源都是**投影状态**，不是 socket 是否开着：

- 工具尾窗：`ToolCard.tsx:137` 传 `streaming={tool.status === 'running'}` —— **不发 `tool/result`** 即恒为 running；
- 推理块：`ReasoningBlock.tsx:206` 传 `streaming={block.status === 'streaming'}` —— **不发 `reasoning/completed`** 即恒为 streaming。

于是按 `c-tool-output.spec.ts` / `a-reasoning.spec.ts` 既有形态造帧（`routeApi` + `onSessionPost: fulfillSse` + 同一份 `events`），再补足文本量保证容器**可滚动**（滚动是 `suspended` 的前置条件，故测试里用 `expect(scrollable).toBe(true)` 显式断言该前置，而不是默默假设）。

### 新增 `web/e2e/m-stream-affordances.spec.ts`（2 用例 × 2 视口）

| 按钮 | 断言的可观察契约 |
| --- | --- |
| `tool-out-wrap-btn` | 默认「不换行」+ body `tool-out-wrap` → 点击变「自动换行」+ body `tool-out-nowrap`（且不再匹配 `tool-out-wrap`）→ 再点回到「不换行」+ `tool-out-wrap` |
| `tool-out-jump` | 初始 0 个 → 上滚触发 `suspended` → **出现** → 点击 → **`toHaveCount(0)`**（回底即复位）且 `scrollHeight - scrollTop - clientHeight < 8`（真的回到底部，不只是隐藏） |
| `reasoning-jump` | 同上：展开思考正文 → 初始 0 个 → 上滚 → 出现 → 点击 → 消失 + 真的回底 |

### 变异验证（三个按钮各一次，全部生效）

| 变异 | 结果 |
| --- | --- |
| `ToolCard` 换行按钮 `onClick={() => setWrap((v) => !v)}` 改空实现 | 两视口都红：`Expected: "自动换行" / Received: "不换行"` |
| `ToolCard` `jump` 改空实现 | 两视口都红：`Expected: 0 / Received: 1`（点完浮标不消失） |
| `ReasoningBlock` `jump` 改空实现 | 两视口都红：`Expected: 0 / Received: 1` |

三次变异后均还原（`git diff` 无残留）。

### 口径说明（避免把 mock 说成真机）

这三次点击发生在**真实浏览器里的真实鼠标事件**上，只有**网络**被替换成 fixture。所以它与前 38 个的口径**不同**，登记时分开记：前者是「真实后端 + 真机」，这里是「真实浏览器点击 + mock 流」。这么做的正当性在于：这些按钮的渲染条件是**组件契约**（`streaming === true`），与「后端为什么缓冲输出」无关——任何会增量产出输出的后端（例如按行 flush 的容器 / Docker 沙箱）都会让这个窗口长期存在，届时这三个按钮就是常规可达控件。

### 最终覆盖账目（45 个 `<button>`）

| 验证口径 | 数量 | 按钮 |
| --- | --- | --- |
| 真实后端 + 真实浏览器点击 | **38** | 见第三轮清单 |
| 真实浏览器点击 + **mock 流** | **3** | `tool-out-wrap-btn`、`tool-out-jump`、`reasoning-jump`（本轮） |
| 真实浏览器点击 + mock 401 | **1** | `auth-banner-close`（第三轮 `l-auth-banner.spec.ts`） |
| e2e 内激活（mock 目录，键盘 Enter 触发） | **1** | `ContextProviderPicker` 触发器（`picker-search-visibility.spec.ts`） |
| **真机点击（真实后端 + 真实模型，第五轮）** | **2** | 审批卡「批准」「拒绝」——（原登记「产品不可达」**已证伪**：显式选权限档位即开启交互式审批）。真机点过 + JSONL 持久化决策；回归锁 `n-approval-card.spec.ts`（另用 mock fixture 锁前端契约） |

**合计 45 = 38 + 3 + 1 + 1 + 2** ✓ —— **45/45 全部已被点击**。此前记为「2 个产品不可达」的两个按钮**已证伪并闭合**（OBS-006 订正条）：`auto_approve` 不是审批卡的门，`session/service.py:348` 的 `permission_mode_explicit` 才是。**本轮无任何「未验证」按钮遗留**。

### 第四轮收尾：独立审查结论与 6 项 P3 处置

新 spec 先送独立 agent 审查：**结论 approve，P0/P1/P2 均为 0**，P3 共 6 项。审查方另逐条排除了 5 个「疑似」——「点击不是真实点击」（无间接路径：`setWrap` / `jump` 是唯一改写点）、「fixture 态不可达」（`running + output + 无 result` 任何按行 flush 的工具都会出现）、`expect.poll` 阈值、`submitTask` 竞态、以及「与既有 spec 重复」（三个选择器全仓仅此一处点击）。**无空洞断言**：唯一「看起来空洞」的 `scrollable` 前置被确认**可证伪**（删掉 `.tool-out-body` 的 `max-height` 即变红；没有它 `scrollTop=0` 会变成空操作、jump 断言反而假通过）。

6 项 P3 **全部已修**（非仅记录）：

| # | 问题 | 处置 |
| --- | --- | --- |
| P3-1 | 文件头把三个按钮的挂载条件混为一谈（换行键实际**无** streaming 条件） | 头注释改为分别陈述：换行键看尾窗挂载条件（`ToolCard.tsx:136`）、两个跳转键才额外要求 `suspended`（`followLatest.ts:33-38`） |
| P3-2 | 上滚是 `scrollTop=0` + **合成** `scroll` 事件，不是真实滚轮 | 头注释加「没锁什么」小节，明确划界（另：fixture 一次铺完，无「suspended 期间持续增量」时序） |
| P3-3 | `if (aria-expanded==='false') click` 是**隐藏分支**，正常走不到 | 删掉条件分支，改为显式断言 `aria-expanded='true'`（顺带锁住 `disclosure.ts:109` 的流式自动展开规则） |
| P3-4 | `toBe(true)` 失败只报 `Received: false`，看不出差距 | 改为数值断言 `expect(scroll, '容器必须可滚动…').toBeGreaterThan(client + 5)` |
| P3-5 | 只断 class 名，删掉 `.tool-out-nowrap` 的真实 CSS 仍然会绿 | 补 `toHaveCSS('white-space', 'pre-wrap' / 'pre')`——断到**生效样式**而非类名 |
| P3-6 | 头注释指向第三轮「缺口 2」，而那处当时仍写「无覆盖」 | 头注释明写该结论**已在第四轮作废并补齐**；第三轮原文亦加同向作废标记 |

**加固后的变异复验（针对修改后的版本重跑，非沿用旧结论）**：换行 `onClick` → 空实现 ⇒ `Expected: "自动换行" / Received: "不换行"` 两视口红；`ToolCard` 跳转 `onClick` → 空实现 ⇒ `Expected: 0 / Received: 1`；`ReasoningBlock` 跳转同理 ⇒ `Expected: 0 / Received: 1`。三处均还原，`git ls-files --eol` 确认两个源文件回到 `i/lf w/lf`（**注意**：用 Python 文本模式改写会把 LF 变成 CRLF，`git diff` 因 `autocrlf=input` 而归一化看不出差异——必须用 `git ls-files --eol` 才能发现）。

**第四轮最终门禁**：tsc ✓ · vitest **497 passed**（28 文件）· oxlint **35 warnings / 0 errors**（基线未变）· playwright **104 passed**（100 + 本轮 4）· vite build ✓。

### 第五轮：审批卡两键——证伪「不可达」+ 真机点击 + 回归锁

见上「OBS-006 订正条」与「最终覆盖账目」。要点：`auto_approve` 不是审批卡的门，`session/service.py:348` 的 `permission_mode_explicit` 才是；真实后端 + 真实模型下选「只读」即可让 `write` 工具触发卡片，两键真机点击后 JSONL 留下 `permission/resolved`（`approve_once` / `deny`）。回归锁 `web/e2e/n-approval-card.spec.ts`（4 用例 × 2 视口），4 处变异全红；真机脚本入独立联调车道 `web/e2e-live/` + `playwright.live.config.ts`（**主车道只扫 `./e2e`，不受影响**）。

**第五轮最终门禁（含前四轮全部用例）**：tsc ✓ · vitest **497 passed**（28 文件）· oxlint **35 warnings / 0 errors**（扫 99 文件，基线未变）· playwright **112 passed**（104 + 审批卡 8）· vite build ✓。主车道对 live 车道用例计数为 **0**（已核验）。

**本轮自曝缺陷（已修，值得记住）**：新建联调车道后，`vitest.config.ts` 的 `exclude` 只写了 `'e2e/**'`，**没覆盖 `'e2e-live/**'`** → vitest 把 Playwright 的 `test()` 当单测收集，**单测车道直接变红**（`1 failed | 28 passed`，29 文件）。我第一次跑 vitest 时该文件尚未就位，故报了「497 passed」——**这是错误的门禁结论**，随后的自查才发现。修复：`exclude` 增补 `'e2e-live/**'`（与 `e2e/**` 同理，注释写明原因）。**教训：新增任何测试目录，必须同时检查 vitest 的 `exclude` 与 playwright 的 `testDir` 两侧，只查一侧会漏。**

### 第五轮审查（对 `n-approval-card.spec.ts` + fixtures + 联调车道）：0 个 P0/P1，2 项 **P2** + 4 项 P3

**2 项 P2 全部已修**（都是「断言不足以证明所声称之事」）：

1. **URL 里的 session id 未断言**：只断请求体时，把 `api.ts` 的会话 id 换成常量（打到别的会话）**两条车道都会绿**（`routeApi` 的 route 正则是 `[^/]+`，任何 id 都匹配）。→ 已改为记录并断言 `path === /api/sessions/${SID}/approve`；联调车道同样记录 path。
2. **联调车道分不清「后端已决」与「POST 失败 + 乐观 UI」**：这正是 OBS-015 的直接后果——`catch` 对任何错误都翻标题。→ 已改为点击后 **`expect.poll` 后端 `/events` 里的 `permission/resolved`**，POST 被拒就过不去。

**P3 处置**：`reuseExistingServer: true` → 改 `!process.env.CI`（与主车道同规矩）并在头注释写明「可能复用到别 worktree 的 5173」；档位选择按序号会随目录重排而失效 → 保留但注明「会**明确变红**，不是静默错选」；「`resolved` 移除」用例对**新增**路径非自足（审查方确认与用例 1 配对后可接受，已保留）。

**审查方排除的误报**（记录以免后人重复怀疑）：fixture 与后端 `approval.py:56-72` **逐字段一致**（含 `allowed_decisions: ['deny','approve_once']`）；`fixtures.ts` 新分支不影响任何既有 spec（无其它 spec 命中该路径，catch-all 仍在最后）；联调车道不会进主门禁；点击类断言均**非空洞**（三轮变异可证）；`service.py:348` 的引用**准确**。

**审查方另指出（预存在，未改）**：`tsconfig.app.json` 只含 `src`、`tsconfig.node.json` 只含 `vite.config.ts` → **e2e spec 与 Playwright 配置都不被 `tsc -b` 类型检查**，`onApprovePost` 之类的接线错误无编译期兜底（靠 playwright 运行时加载与 oxlint 解析）。属既有结构，登记备查。

---

## 第六轮：全量真实浏览器验收（2026-09-11，真实 dev server 5173 + 真实后端 8000）

> 起因：用户要求「前端的每个功能都要测试一遍，每个按钮都要点一下，遇到任何问题实时写入本文档」。
> 本轮在**当前 `feat/backend` 后端（源码树启动，非 main worktree 的旧进程）+ `feat/frontend` 前端**上重建验收面：
> 先复验刷新一致性，再逐个点过此前未覆盖的控件，最后跑真实模型 run。

### 本轮刷新一致性复验（新增证据，结论与 BUG-005 一致）

在会话 `3b35b83d-dcae-476f-8343-9912e40e77d7`（35 事件 · 中断态）上做**同函数**前后对比
（`document.body.innerText` 的 djb2 `${len}:${hash}` + 按钮指纹 + 滚动位 + tab 选中态）：

| 量 | balanced 档 | detailed 档 |
| --- | --- | --- |
| 内容指纹 | `2235:1645848761`（刷新前后**逐字节相同**） | `2309:2105849635`（同） |
| 按钮指纹（74 键） | `2032:3401835054`（同） | 同 |
| 滚动位 | `session-items 0/822`、`detail-body 0/860`（同） | 同 |
| `ahi.selectedSession` | 恢复为该会话 | 同 |

**视图状态（非内容）刷新不保留**：切到 Overview tab、`.detail-body` 滚到 105.5、思考区折叠
→ 刷新后回到 Timeline / `scrollTop 0` / 展开。**这与「真机验证（2026-09-11 追加）」记录的冻结边界一致**
（Inspector 是视图状态、DSH 语义、刻意不持久化），**不是缺陷**；本轮为它补了
「内容一致 + 视图状态不保留」并存的实测证据。`ahi.theme` / `ahi.traceDensity` 两个 localStorage
键按设计跨刷新保留（density 手动切 detailed 后刷新仍为 detailed）。

### 本轮真机点过并确认正常（新增覆盖）

| 控件 | 结果 |
| --- | --- |
| Inspector 运行级 5 个 icon tab | ✓ 每个 21×21，label span `display:none`，名称经 `title`（如 `title="Timeline"`）；点击切换正确 |
| 事件详情 io-tabs Overview/Input/Output/Raw | ✓ 四段内容各自正确（Input 出 args、Raw 出完整事件 JSON）；`返回 Timeline` 复位 |
| 事件 Input/Output `复制 JSON`、Raw `复制 Raw` | ✓ 剪贴板实得 165 / 165 / 490 字符，均为 JSON；按钮 `aria-label` 1.6s 内翻 `已复制` |
| 工具详情 4 tabs（默认 Output） | ✓ `bash echo smoke-ok`：Overview 出 status/duration；Input `复制 JSON`→`{"command":"echo smoke-ok"}`(32)；Output `复制输出`→`{"exit_code":0,"stdout":"smoke-ok\n",…}`(85)；Raw **两个** `复制 Raw`→seq 4(446) / seq 5(685) = tool/call + tool/result |
| 中断会话的工具详情零伪造 | ✓ `delegate` 无 tool/result 时**不渲染 Output tab**、Raw 只有 1 个复制键（`hasOutput`/`hasRaw` 判定正确） |
| Timeline 行 hover 浮层 | ✓ 出现 `role=tooltip` 且带完整时间戳（毫秒）——**但文案发现 BUG-008** |
| 会话切换（rail 行） | ✓ 点 `b46a6029` → 头显示 `已完成 · 5,922 tok`，`ahi.selectedSession` 同步 |
| `返回 Timeline` | ✓ 事件/工具视图下点击后返回键消失、运行级 tabs 恢复 |

**方法说明（诚实口径）**：Inspector 内的点击用**页面内 `.click()`**（React `onClick` 正常触发）；
Radix 浮层 / `Esc` 类依赖真实指针与按键事件者，沿用既有的 MCP/CDP 真实序列
（「合成事件假象清单」不变）。**本轮两处自曝误报已排除**：(1) 我最初用
`innerText` 匹配 `^复制` 找复制键，得出「事件详情没有复制按钮」的**错误**结论——
`CopyButton` 是纯图标按钮（`aria-label`/`title` 承载名称、`innerText` 为空），换
`button.copy-btn` 选择器后三个键全部存在且工作；(2) 曾怀疑「事件 Output 段与 Input 段显示同一份
JSON」是 bug——读源码 `:807`/`:818` 确认两者都 render `event.data`，**是事件级视图的既定语义**
（事件没有 call/result 两段，只有 data），非缺陷。

### BUG-008 Timeline 浮层渲染字面量 `step undefined`，事件详情出现空的 `step` 幽灵行【P2 · 已修复（见下方修复条）】

**发现时间**：2026-09-11 第六轮真机 hover。

**现象（两处，同一根因）**：
1. 悬停 Timeline 第 1 行（seq 0 `session/started`）→ 浮层文字为
   `2026-09-06 05:57:19.553 step undefined`（**字面量 `undefined`**）。
2. 点开该行事件详情 → Overview 段多出一行 `step` 但**值为空**。实测 `.detail-row` =
   `[{seq:"0"},{time:"2026-09-05T21:57:19.553+00:00"},{step:""},{event_id:"034292cf-2c13-41"}]`。

**根因（文件行号）**：
- 后端序列化**省略值为 null 的字段**——实测 `GET /api/sessions/b46a6029-…/events` 的 seq 0/1/2
  均为 `'step_id' in e === False`（**键整个不存在**，不是 `step_id: null`）。
- 前端 `components/StepDetail.tsx:478` 用**严格判等**：
  ``if (e.step_id !== null) lines.push(`step ${e.step_id}`)`` —— `undefined !== null` 为真
  → 推出模板串 `step undefined`。
- 同文件 `:783` ``{event.step_id !== null && (<div className="detail-row">step {event.step_id}</div>)}``
  同理，且 `<span>{undefined}</span>` 被 React 渲染为空 → **幽灵行**。

**为什么别处没中招（对照，证明是渲染层疏漏而非契约问题）**：
`lib/projection.ts:1024` 用宽松判断 ``if (event.step_id != null)``；`:453` 对派生字段做
``event.step_id ?? null``；`App.tsx:679` 读的是已归一的 `conversation.run_interrupted.step_id`，
故中断横幅文案（「第 N 步」/「首个步骤开始前」）**不受影响**。

> ⚠ **初版结论已订正（对 reviewer 的 Spec 轴自查）**：初版写「只有 `StepDetail.tsx` 这两处」是**错的**。
> 同一 bug 类**还有第三处**：`lib/eventKind.ts::streamKeyFromEvent` 也是严格 ``stepId !== null``，
> 入参由 `App.tsx:223` 直接传 `event.step_id`（同样是可能缺失的键）。键缺失时它返回**伪造 key
> `step:undefined`**——违背它自己文档里写明的「无 step 且非工具/委派域 → 返回 null（无可定位目标）」
> 契约，并让 `App.tsx:222` 的 `if (key)` 把一个不存在的定位目标当真。**诚实的后果评估**：
> `Conversation.tsx:126-127` 的兜底 `turns.findIndex(...)` 会得到 `-1` 并 `return`，**当前不产生
> 任何可见差异**（无 step 的事件本来就无处可跳）；所以这一处的价值是**契约正确性 + 不伪造 key**，
> 不是修复一个可见症状。三处均已修，且各自有测试锁。

**归因：前端（渲染判空）**。后端「省略 null 字段」是既定序列化约定（Raw 档"完整源事件原样透传"，
见 `projection.ts:313` 注释），改后端会改动 Raw 真相源形状，不作首选。

**测试缺口**：`StepDetail.test.tsx` 的 5 个 `formatEventTooltip` 用例只覆盖
`step_id: 9 / 2 / null / null / 0`，**没有「键缺失（undefined）」这一真实线上形状**——所以它一直绿。
`eventKind.test.ts` 的 `streamKeyFromEvent` 6 个用例同理：只测 `null`，不测 `undefined`
（第 113-116 行「无 tool_call_id 且无 step → null」用的正是 `null`，所以第三处的伪造 key 也一直是绿的）。

**为什么定 P2 而非 P1**：不影响会话内容、不阻断任何操作；但确实是用户可见的**伪造文本**
（不变量 #21 精神：缺席不得被渲染成一个看似有值的占位）。

### BUG-008 修复条（2026-09-11）

**思路**：三处都是**渲染/构造层用严格判等读一个线上可能缺失的键**，统一改为宽松判空
（``!= null``）——与仓库既有口径一致：`projection.ts:1024` 的 `resolveStep` 早就这么写，
且它的注释记录了**同一 bug 类此前已造成过一次回归**。**明确否决的两个替代方案**：
① 改后端让 `step_id` 总是出现——会改动 Raw 档「完整源事件原样透传」的形状（`projection.ts:313`），
且后端省略 null 字段是既定约定；② 在 `lib/eventValidate.ts::validateEvent` 统一归一化——
它的 docstring 明确把归一化范围限定为缺失的 `data`/`seq`（「只守可辨、不崩」），
把业务字段塞进去等于扩权该层。两轴 reviewer 独立得出同一结论：修在消费点、保持一致。

**改动（3 文件）**：

| 文件 | 改动 |
| --- | --- |
| `web/src/components/StepDetail.tsx` | `:481` `formatEventTooltip` 的 ``e.step_id !== null`` → ``!= null``；`:788` 事件详情 Overview 的 `step` 行同改。docstring 补齐「缺失或 null」语义，行内注释收敛为一句指针（消除两处重复注释的漂移风险） |
| `web/src/lib/eventKind.ts` | `streamKeyFromEvent` 的 ``stepId !== null`` → ``!= null``（第三处，见上方订正块）；docstring 写明为何必须宽松 |
| `web/src/components/StepDetail.test.tsx`<br>`web/src/lib/eventKind.test.ts` | 各补「键缺失（undefined）」红灯用例（TDD：先见 ``["step undefined"]`` / ``"step:undefined"`` 再修）；Overview 的相邻语义用例补 `withStep(0)` 并改名（原名把 `null` 说成「缺失」，措辞不准） |

**验证**：

1. **红灯→绿灯**：修复前 `formatEventTooltip` 实收 ``["step undefined"]``、SSR HTML 里确有
   ``<span class="detail-key">step</span><span class="detail-val num"></span>``、
   `streamKeyFromEvent` 实收 ``"step:undefined"``；修复后三处全绿（`StepDetail` 16 + `eventKind` 19）。
2. **真实浏览器复验**（dev 5173，会话 `b46a6029`）：
   - 无 step 的行 hover → 浮层 `2026-09-06 05:57:19.553`（**无 `undefined`**）；带 step 的 `tool/call` 行 → `…21.816 step 1`（正对照）。
   - 事件详情 Overview 的 `.detail-row` 由 `[seq, time, step(空), event_id]` 变为 `[seq, time, event_id]`。
   - 跳转路径正/负对照：点 `session/started`（无 step）`stream-jump-pulse` **0** 个；点 `tool/call`（有 step）**1** 个、pulse 落在工具行——**修复没有破坏跳转**。
3. **门禁**：`tsc -b` 0 · `vitest run` **507 passed / 0 failed**（28 文件）· `oxlint` **35 warnings / 0 errors**（基线未变）· `playwright test --workers=2` **118 passed** · `vite build` 0。

**过程自查（两条，值得记住）**：
- 我最初的探针用 `innerText` 匹配 `^复制` 找 Inspector 的复制键，得出「事件详情没有复制按钮」的
  **错误**结论；`CopyButton` 是纯图标按钮（名称在 `aria-label`/`title`）。**教训：图标按钮必须按
  `aria-label` 定位，不能按可见文本**。
- 本轮的第一次全量门禁我把 vitest 输出接了 `| tail`，**管道退出码掩盖了 `1 failed`**，命令链继续
  跑完并报「成功」。发现后重跑：**连续 5 次全量均只失败我当时故意留的红灯**，那次失败**不可复现**。
  **教训：门禁链路必须用 `set -o pipefail`（或 `${PIPESTATUS[0]}`），任何 `| tail` 都会吞掉失败。**
  那次未复现的失败已如实记录在此，不当作已通过。

### OBS-016 委派/子会话整块 UI 在当前后端配置下**不可达**（multiagent capability 未启用）【配置 · 非缺陷 · 验收环境缺口】

**发现时间**：2026-09-11 第六轮真实 run（为验收委派节点而发起）。

**现实现象**：我发起的真实 run（新会话 `a39876d7`，提示词就是「用 delegate 工具把任务委派给
research_review…」）里，**模型自己说没有这个工具**，并列出它实际可见的工具表：
`read / write / edit / apply_patch / bash / glob / grep / git_status / git_diff / inspect_artifact / web_search`
——**有 `inspect_artifact` 但没有 `delegate`**，随后它自行改用 `web_search` 完成任务（自适应行为正确）。

**证据链（三层，互相印证）**：
1. `GET /api/capabilities` → **只返回 1 个能力 `websearch`**，无 `multiagent`。
2. 后端启动配置 `CAPABILITIES` = 仅 `websearch`（`"enabled": true`）——`multiagent` 是
   **ADR-0015 的显式 opt-in capability**，未列即不激活。
3. 装配层 `assembly.py:211-221`：capability 贡献的 delegate 工具只在 multiagent 启用时进 registry，
   且 `session_store is None` 时还会「降级缺席」并打 warning——
   即 **delegate 缺席是设计内的 optional-capability 语义**（不变量 #21：可选能力缺席不得拖垮 Core）。

**归因：既不是前端 bug 也不是后端 bug，是运行配置。**
- 前端正确：委派 UI（`DelegationNode`、`复制子会话 ID`、`Inspect 子会话`、`打开子会话`、child 视图
  `Run` 返回）**只由真实事件驱动渲染**，无事件就不渲染——零伪造，符合不变量 #21。
- 后端正确：`main` profile 的 `tool_scope`（`agent/profiles.py:58`）确实含 `delegate`，
  但 capacity 未启用时 registry 里根本没有它；`main` profile 不做过滤（`assembly.py:224`），
  所以不是被 scope 收窄掉的。

**本轮覆盖后果（诚实登记）**：以下 **5 个控件在本轮配置下无法真机点击**，故本轮不宣称覆盖：
`委派行按钮（委派 → target）`、`复制子会话 ID`、`Inspect 子会话`、`打开子会话`、`child 视图 Run（child-back-btn）`。
它们**已有上两轮的真机结论**（第二轮第 38/61 项：展开、复制子会话 ID 实测剪贴板、Inspect 子会话、
打开子会话切到 child `2515a128`；`k-refresh-restore.spec.ts` 还锁了 child 会话刷新），
**e2e 回归锁也在**（`k-refresh-restore.spec.ts` 的 `.session-item[title^="${CHILD} "]`）。
本轮追加的语料核查：**当前 11 个会话里只有 `3b35b83d` 出现过 `tool/call delegate`，且它没有任何
`child_session_id`**（那次的委派在 run 被中断前没跑起来）——所以库里**确实不存在**可钻取的子会话。

**建议（需用户决定，我没有擅自改）**：若要在这条验收车道上真机覆盖委派/子会话，需要在
`feat/backend` 的 `.env` 里给 `CAPABILITIES` 增加 multiagent 项。这是**改运行配置**（会改变产品
实际行为，不只是测试开关），按 §9.1 属需要用户确认的范围，故**只登记建议、不改**。

**决定性补充（两个 worktree 的 `.env` 差异——也解释了前几轮为何能点委派）**：

| worktree | `CAPABILITIES` |
| --- | --- |
| `D:\intelligence-agent`（main） | `websearch` **+ `multiagent`（enabled）** |
| `D:\intelligence-agent-backend`（feat/backend） | **仅 `websearch`** |

`.env` 按 §13.1.6 属**不在 worktree 之间同步**的本地文件，所以两个 worktree 的能力集天然可能不同。
这同时解释了另外两件此前看起来矛盾的事：
1. **前几轮的委派/子会话真机结论成立**（第二轮第 38/61 项）——当时 :8000 上跑的是 **main 的
   后端**（multiagent 开），所以 `delegate` 在册；本轮跑的是 **feat/backend 后端**（multiagent 关）。
2. **第三轮「加载更早 200→410」也是真机点过的**——那需要一个 >200 事件的会话（fork child
   `1fdac9b9`，410 事件），它属于 main 那次后端的语料库；本轮 feat/backend 语料 11 个会话最大
   35 事件，**`加载更早 N 条`（阈值 >200）在本轮语料下不可达**，但**并非产品不可达**。

**结论口径修正**：本轮称「不可达」的控件（委派 5 项、`加载更早`、Trace 三件套、四个 picker 搜索框、
Context picker）**全部是「本轮运行配置/语料下不可达」，不是产品缺陷**；其中委派 5 项、`加载更早`、
picker 搜索框均**已在其他轮次真机点过并有 e2e/单测回归锁**。真正的产品不可达只有「Trace 三件套」
（需 Langfuse 启用，本部署未配）。

### 本轮新增真机覆盖（第二批：真实 run 路径）

| 控件 | 结果 |
| --- | --- |
| `Escape`（全局，R3） | ✓ **决定性证据**：真实 CDP 按键后 fetch 记录器立刻捕获 `POST /api/sessions/a39876d7-…/cancel`；脉冲 `思考中 · 2s` → **`已取消`（中性通道）**；停止键消失、发送键复位、四个控制选择器恢复、无错误横幅。与 Composer 停止键行为一致 |
| 流式期的 Composer 状态 | ✓ run 中：`[aria-label="停止"]` 在场、发送键消失、`.composer-control/.composer-model` 四个选择器 `disabled`；结束/取消后全部复位 |
| 顶栏 Run Pulse（观察项） | ✓ 忠实反映真实阶段：`思考中 · Ns` → `执行工具 · Ns` → `已完成 · N tok` / `已取消`；无伪造进度 |
| 代码块 `自动换行`/`不换行`（markdown.tsx:61） | ✓ `.md-code` ↔ `.md-code md-code-wrap`，标签 `代码自动换行` ↔ `代码不换行` 往返一致 |
| 代码块 `复制代码`（markdown.tsx:69） | ✓ 剪贴板实得 22 字符 `print("Hello, World!")`，与 `.md-code code` 的 `textContent` **逐字相等**（非截断版），反馈翻 `已复制` |

**真实 run 的模型行为观察（后端/provider，非缺陷）**：本次「写 hello world 代码块」的 run 在
`思考中` 停留 **50s+ 且 token 零增长**（默认链 `deepseek-v4-flash-0731` 停顿），随后**模型回退
按设计生效**（不变量 #9：Model Fallback 与 Tool Retry 分离）——时间线落
`model/completed glm-4.5-air · 6907 tok`，由 glm-4.5-air 完成，`run/completed 13873 tok`。
**UI 全程诚实**：期间只显示 `思考中 · Ns` 实时计时、不伪造进度、不报假错误、也不假装卡死；
用户可随时用停止键/Esc 取消（本轮已实测）。这与 `3b35b83d` 里
`model/fallback deepseek-v4-flash-0731 → glm-4.5-air · ModelStallError` 是同一现象。
**建议（供后端参考，不在本轮前端范围）**：停顿检测的阈值约 50s 偏长，且停顿期间 UI 没有任何
「正在等待模型/即将回退」的中间态提示——可考虑让后端更早发出 fallback 事件，前端已有渲染通道。

### BUG-009 非流式 run 的 Model Fallback 在带并发闸时**必崩**（`AttributeError`）【P1 · 后端 · 已修复】

**发现时间**：2026-09-11 第六轮验收——把 `multiagent` 加进 `feat/backend` 的 `.env` 后跑真实委派，
**委派子会话 `run/failed`**，而父会话正常完成。这属于用户问的「判断是前端还是后端的问题」的典型：
**后端**，前端只是把后端的真实失败如实渲染出来。

**症状（真实事件，非推断）**：child `1f2c2af4` 的事件序列
```
3 model/fallback {"from_model":"deepseek-v4-flash-0731","to_model":"glm-4.5-air","reason":"InternalServerError"}
4 model/failed   {"message":"model call failed: AttributeError"}
5 run/failed     {"trace_id":null,"trace_url":null}
```

**根因（后端服务端日志 traceback 逐字）**：
```
File ".../agent_harness/agent/runtime.py", line 663, in _drive
File ".../agent_harness/model/fallback.py",  line 176, in ainvoke
File ".../contextlib.py",                    line 212, in __aenter__
AttributeError: '_AsyncGeneratorContextManager' object has no attribute 'args'
```

`fallback.py::ainvoke` 把 `slot = self._gate.slot() if self._gate is not None else nullcontext(None)`
**只取一次**，然后在「首次尝试」和「回退重试」两处 `async with slot:` **复用同一个 CM**。
`ModelCallGate.slot()` 带 `@asynccontextmanager`（`concurrency.py:52`），其产物是**一次性**的——
contextlib 退出时执行 `del self.args, self.kwds, self.func`（CPython 源码注释原话：
"only needed for recreation, **which is not possible anymore**"），二次进入即抛 `AttributeError`。

**影响面（不变量 #9 被破坏）**：`runtime.py` 的 `if stream:` **else 分支**（`:663`）走 `ainvoke`。
`run()` 传 `stream=False`（`:432`），`run_stream()` 传 `True`（`:455`）；delegate 派生的子会话走
`child_runtime.run(...)`（`multiagent/provider.py:229`）→ **非流式**。所以
**所有非流式 run（含全部 delegate 子会话）在主模型瞬断时永远回退不了**，直接 `model/failed` + `run/failed`。
生产恒带闸（`model_max_concurrency` 默认 3）故必然触发。

**为什么既有测试长期没抓到（精确的覆盖缺口）**：`tests/test_model_fallback.py::TestCoordinatorAinvoke`
的用例**全部 `gate=None`**——此时走 `contextlib.nullcontext`，而 `nullcontext` **可以重复进入**，
所以那条 `async with slot` 第二次进入是合法的。**「闸 + ainvoke 回退重试」这个组合此前零覆盖。**

**修复**：新增 `_slot()` 帮助方法（每次调用取**新** CM），两处尝试各自调用它。
改 `src/agent_harness/model/fallback.py`，并补回归锁 2 例（含 5xx 形状参数化与「回退也失败」的
重试一次边界）。**变异验证**：把 `ainvoke` 改回复用同一个 CM → 只有新用例变红（红灯非空洞）。

**真实 A/B 实证（同一触发形状、不同结局）**：
| | 触发 | 结局 |
| --- | --- | --- |
| 修复前 child `1f2c2af4` | `model/fallback … reason: InternalServerError` | `model/failed(AttributeError)` → `run/failed` |
| 修复后 child `6eed381f` | `model/fallback … reason: InternalServerError`（**同形**） | `model/completed` → `tool/result` → **`run/completed`**，`final_text` = "Python 官网网址是 https://www.python.org" |

父会话 `7cf291d1` 也 `run/completed`，`final_text` = "子代理 `research_review` 已成功完成任务：…"。

**门禁**：`ruff check src/ tests/` 干净 · `pytest -q` 全绿。**登记归因：后端**（前端无需改动）。
**另记**：`fallback.py::_guarded_stream` 末尾有一处**重复的 `return stream`（死代码，非本次引入）**，
按 §8 Scope Lock 只报告、不顺手改。

---

## 第七轮（2026-09-11）：停顿提示（FE-01/#148）——阈值依据 + 真机时间线

### 停顿提示阈值：可复现的测量

方法（可重跑）：对 `GET /api/sessions` 前 20 个会话，各取 `GET /api/sessions/<id>/events`，
找**首个带 `time` 的 `user/message`** 到其后**首个模型活动事件**（`model/started` /
`text/delta` / `reasoning/started` / `tool/call`）的 `time` 差，作为「首事件延迟」的代理
（它量的是「提交 → 模型开始动弹」，不是 SSE 首帧的网络延迟）。

实测（本机 `:8000`，脚本见本条记录时的 `/tmp/lat.py`）：**n=13，min 0.8s，p50 4.6s，
max 61.0s；>15s 占 3/13，>30s 占 2/13**。样本：0.8 / 1.3 / 1.4 / 2.3 / 2.3 / 4.6 / 4.6 /
11.3 / 12.3 / 13.5 / 23.2 / 60.5（s）。

结论：30s 阈值落在真实分布的长尾上（历史上约 15% 的 run 会触发），而提示文案只陈述
「已经多久没有新进展」这一已观测事实，所以长尾触发时它说的是真话，不是误报。

### 真机时间线（真实后端 + 真实模型，Reasoning Effort=Deep）

`.wait-hint` 用 250ms 采样器记录（页面内 `window.__obs`）：

| 时刻（自提交） | 脉冲 | 提示 |
| --- | --- | --- |
| 0.3–20.3s | `思考中 · 11s` → `思考中 · 31s` | 无 |
| **20.5s** | `思考中 · 31s` | **`已 30s 没有新进展，仍在等待模型`**（首次出现） |
| 21.5s–24.5s | `思考中 · 32s` → `35s` | `已 31s…` → `已 34s…`（逐秒递增） |
| ~65s | `思考中`（无秒数） | 无（**断线横幅接管**：`连接中断（connection stalled）：重试 3 次未成功` → `连接中断，正在重连…`） |
| ~70s+ | `思考中 · 4s`（重连成功后**流龄重置**） | `已 79s 没有新进展，仍在等待模型`（空闲是**跨重连累计**的） |

**三条结论**：
1. **AC7「真机出现该说明」成立**——首 token 等了 31s 的真实 run 上，提示在空闲 30s 时
   出现并逐秒递增；且提示秒数（30）**小于**同屏脉冲秒数（31），正是「锚空闲而非流龄」的
   现场证明（e2e 里把这条做成了决定性断言）。
2. **降级路径是对的**：客户端自己 give-up 时 `streaming=false`，提示让位给断线横幅/恢复
   入口（`思考中` 无秒数 + 横幅），重连成功后提示带着累计空闲秒数回来。三种信号不互相
   冒充，符合「等待态是展示层状态」的设计。
3. **观察（未改，§8 Scope Lock）**：脉冲的 `思考中 · Ns` 是**流龄**、重连成功后会重置
   （上表 `4s`），而提示的秒数是**跨重连累计的空闲**（`79s`）——两个数字可以相差很大，
   同屏看会以为是矛盾。这是脉冲既有语义（不是本票引入）；若要消除，最小改法是提示可见
   时隐藏脉冲秒数，但那会改动本票 AC 明确要求保留的既有计时显示，故**只登记不动**，
   交用户决定。
   **用户决定（2026-09-11）：保留计时显示，不改。**（观察闭合，不再挂「待决定」。）

### 停顿提示与重连 give-up 的窗口关系（用户已决定：不改）

提示在空闲 30s 出现，而客户端 `RECONNECT_STALL_MS(10s) × MAX_RECONNECT_ATTEMPTS(3)`
约在 30–40s 走 give-up（`streaming=false` → 提示让位给断线横幅），因此真实停顿里提示的
可见窗口约 10s，之后由断线横幅 / 恢复入口接管。**用户决定（2026-09-11）：不需要改**——
保留「旁注 → 断线横幅 → 恢复入口」这个升级顺序。

### 过程自查（值得记住）

- **假绿一次**：给「工具执行中不提示」写的第一版 e2e，用 `route.fulfill` 的**有限响应体**
  mock 流 → 流立刻结束 → 重连额度（3 次）十几秒内耗尽走 give-up → `streaming` 先变 false
  → 「有提示」和「无提示」两个变体都不显示，用例**因错误的原因通过**（变异验证时抓到：
  把相位门改回 `active` 依然全绿）。结论：**这类相位门必须在纯函数层锁**（`shouldShowWaitHint`
  单测，变异后 2 处变红），不能靠有限体 mock 的 e2e。
- **真实后端与 mock 的差异**：真机 `/stream` 在途会话是长连接（所以不会连锁 give-up），
  已收口会话回放完即关（实测 237ms/21831B 正常退出）。mock 的有限体两头都不像，是上一条
  假绿的根因。

---

## 第八轮（2026-09-11）：续聊 `Send failed: 404` 根因（BUG-011 / 后端·已定位待修）

**触发**：用户报「续聊失败：Send failed: 404」（会话 `dd983104-733c-44e9-baa0-7807b86c9f58`）。
按 `diagnosing-bugs` 协议执行（先建可复现环 → 再假设）；除方法说明外无任何代码改动。

### 现场证据（全部来自真实进程，未做任何写入于用户会话）

| # | 证据 | 内容 |
| --- | --- | --- |
| 1 | 浏览器历史网络记录（page 2，保留请求） | `reqid=966 POST /sessions/dd983104…/model [200]` 与 `reqid=967 POST …/model [200]` **相邻**（中间无任何其它请求），紧接着 `reqid=970 POST …/messages [404]` |
| 2 | 失败响应体 | `{"detail":"Session 'dd983104-…' 事件 seq 重复: 5"}` |
| 3 | 事件流（7 行） | seq 0 `session/started`、1 `user/message`、2 `run/started`、3 `model/failed`、4 `run/failed`，然后 **两条 seq=5 的 `model/changed`**（11:21:54.297 / .400） |
| 4 | 两条 seq=5 的 payload | **完全相同**：`from_provider=null, from_model_id=null, to_provider=qwen, to_model_id=qwen3.8-27b` |
| 5 | 只读本地复现（`JsonlSessionStore` + `Session.load`） | 存储层 `read_events` 正常返回 7 条（故 `GET /events` 仍 200、UI 仍显示该会话）；**聚合层 `Session.load` 抛 `ValueError: … 事件 seq 重复: 5`** |

**证据 4 是关键**：两条 `from_*` 都是 `null`，说明**两次写入各自基于「变更前」快照**（若第二次读到了第一条，`from_model_id` 必然是 `qwen3.8-27b`，且不会撞号）。即两个聚合各取到 seq 5。`103ms` 只是第一条的同步 `fsync` 阻塞事件循环后第二条才被调度，**不代表两次点击相隔 103ms**。

### 复现实验

**(a) 服务端：并发两次 `POST /model` → 重复 seq（靶 = 健康会话的临时副本，用完即删）**

| 错开量 | 3 次试验中撞号 |
| --- | --- |
| 0ms | **3/3**（首轮另一组 2/3） |
| 20ms | 1/3 |
| 50 / 100 / 200ms | 0/3 |

单请求耗时 26–46ms（`append` 走整行写 + flush + fsync，**fsync 阻塞事件循环**正是竞态窗口来源）。两次请求均返回 **200**，无任何冲突检测。两请求同时刻提交时，两条 append 时间戳相差 4ms（正常串行时反而 22ms）——反证现场 103ms 是循环被阻塞所致。

**(b) 前端：是「单击」还是「双击」发出两个请求（无头 Chromium 打真实 5173 + 真实 8000，会话指向临时副本）**

| 手势 | `POST /model` 次数 |
| --- | --- |
| **单击** | **1** |
| `dblclick`（两次点击间隔 0ms） | 2（间隔 7ms） |
| 两次真实点击、间隔 20 / 50 / 80 / 120ms | **均为 2**（弹层视觉已关，但第二次点击在 ~150ms 内仍命中模型项） |
| 间隔 200ms | 1 |

**结论**：前端**单次点击不会重复发送**（cmdk 的 `CommandItem` 一次点击只触发一次 `onSelect`；`changeModel` 全仓只有 `App.tsx:285` 一个调用点、`api.ts` 无重试、无 effect 重复触发）。重复来自**双击**——一次人类双击（实测 ≤120ms）即可发出两个并发请求。附带发现：**弹层关闭后约 150ms 内模型项仍在 DOM 中可被命中**，这是双击能穿透的直接原因。

### 根因链（三环，缺一不可）

1. **后端并发写不序列化（根因）**：`service.change_model`（`service.py:788-806`）先 `await read_events` 取快照，再 `Session(...)` 取号 `_next_seq = max(seq)+1`（`session.py:66`），最后 append（`:275-290`）。两个请求各自的**读**都早于对方的**写**时，双双取到同一 seq，且**都不检测冲突、都回 200**。任何两个并发写该会话的请求（双击模型项、两个标签页、客户端重试）都能把会话写死。
2. **错误码错配（放大伤害）**：重复 seq 在聚合层是 `ValueError`（`session.py:206`），而 `service.py:431-432` 把该 try 块内的 `ValueError` **一刀切**转成 `SessionNotFound` → HTTP **404**。于是「日志损坏」被报成「会话不存在」：前端只能显示无从下手的 `Send failed: 404`，运维也无法从状态码判断真因。
3. **前端双击不去重（触发条件）**：`handleModelChange` 无 in-flight 门（`void changeModel(...)`，失败静默），双击直接产生两个请求。severity 上它是「触发」，不是「根因」——因为第 1 环不修，任何并发写都能损坏日志。

**影响面**：一旦撞号，该会话**永久不可续聊**（`/messages` 恒 404）；`GET /events` 仍 200 故 UI 仍显示会话，用户看到的是「会话在，但一续聊就 404」。是否影响 fork/recover/approve 未逐一实测（它们同样构造聚合，按第 2 环推断同为 404）。

### 未做与待决策（按 §8 Scope Lock 只报告）→ 已于 2026-09-11 全部处置

- **用户决定**：① 删除损坏会话 `dd983104`（删前已逐字节记录：7 条事件 + 工作区注册文件 + 空工作区目录）；② 按上述顺序实施 ①②③④ 四步修复。
- 四步均已落地（见文件头 BUG-011 的修复表：后端 `4b8eee4`、前端 `71e605b`），前置说明保留在下方，方法备注仍然有效。

### 原「未做与待决策」记录（保留原貌）

- **未改任何代码**：用户此次是提问式报障，交付物是根因判定；修复方案见下，等指令再动。
- **未改动 `dd983104` 的任何字节**：该会话日志已损坏（重复 seq 5），原样保留（7 行）。它**不会自愈**，续聊会持续 404。
- **待用户决定（数据处置）**：① 重编号修复（把第二条 seq 5 改成 6，会话复活）；② 隔离/备份后删除；③ 暂不处理（只修后端，避免以后复发）。**我未擅自改写用户数据。**
- **待用户决定（修复范围，建议按序）**：
  1. 后端：按会话串行化 append（per-session 锁，或把取号放进 `append_event` 的临界区），使并发写不再撞号；
  2. 后端：撞号时给出**独立错误语义**（冲突重试或 409），而不是伪装成 404；`ValueError` 的兜底不应再无条件等于 `SessionNotFound`；
  3. 前端：模型项加 in-flight 去重（或在弹层关闭后立即 `pointer-events:none`），双击不再发出第二个请求；
  4. 回归锁：服务端并发 `/model` 不得产生重复 seq（pytest，TDD 先红）；前端双击只允许一个 `POST`（e2e 计数）。

### 观察：事件文件在、工作区映射缺失 → 500（**已用真实服务端验证**，Scope 外仅登记）

原记录（合成副本复现时 `POST /messages` 返回 500 而非现场 404）当时**不作为结论**；修完 BUG-011 后用真实
uvicorn（`WORKSPACE_DIR` 指向临时目录）复测，**已确认并拿到 traceback**：

```text
File "src/agent_harness/session/session.py", line 242, in resume
    session = cls.load(store, session_id, workspace_registry=workspace_registry)
File "src/agent_harness/session/session.py", line 223, in load
    workspace_registry.get(session_id)
File "src/agent_harness/sandbox/registry.py", line 73, in get
    raise KeyError(f"Session '{session_id}' 没有对应的 workspace 映射记录。")
KeyError: "Session 'bug011-fix' 没有对应的 workspace 映射记录。"
```

**判读**：这是 `KeyError` 而非领域异常，没有进 `domain_errors.py` 的表 → **500「Internal Server Error」**。
且它发生在 **seq 校验之前**（`registry.get` 在 `load` 的更早位置），所以这类会话走不到 409。
**属另一张票**（健康日志 + 缺工作区映射的状态应走受控错误路径，如 404/409 或可恢复提示），本次**未改**（§8 Scope Lock）。
注意：正常会话不会进入该状态——`Session.start(..., workspace_registry=...)` 会同时写 JSONL 与映射文件；
只有手工构造 / 半删除（事件文件在、映射文件丢）才会出现。

### 方法备注（代价与边界）

- 所有服务端复现都在**健康会话的临时副本**上做（靶子用完即删，删前核对）；探针 15 条 `model/changed` 全部落在靶子上，用户会话 `dd983104` 始终保持 7 行。
- 浏览器侧用**独立无头 Chromium**，未干扰用户已打开的页面，也未向其会话写入任何事件。
- 现场没有服务端访问日志（应用日志只记了 19:02 的孤儿回收），因此「两个请求」由浏览器侧历史网络记录 + `from_* = null` 反证，而非服务端计数。

---

## 第九轮（2026-09-12）：WS-3 #153 会话列表 `workspace` 契约——真机验收 + 一条待 #155 决策的可见行为

**背景**：后端 #152 建了「项目实体 + 有序账本」，#153 把它暴露进列表契约：
`GET /api/sessions` 每行新增 `workspace: {id, title} | null`（未分组 = `null`），
`GET /api/sessions?workspace_id=<id>` 返回该项目会话、顺序 = 账本手工序（非活动时间序）。

**真机验收（真 uvicorn 127.0.0.1:8792 + 真 `.env` + 真 SQLite + 真盘上 28 个会话）**

| 检查 | 结果 |
| --- | --- |
| 每行都带 `workspace` 键 | ✅ 28/28 |
| 分组会话的项目值 | ✅ 8 行分别指向真项目 `ws1-e2e` / `ws2-e2e`（id 与 `harness.db` 逐字段一致） |
| 未分组会话 | ✅ 20 行 `workspace: null`，且**仍在列表里可见**（AC5） |
| `?workspace_id=<id>` 顺序 | ✅ 与 `workspace_sessions.position` **逐项一致**（ws2-e2e 3/3） |
| 未注册 id | ✅ **404** `workspace '…' not found`（不是空列表——空列表会谎报「这个项目没有会话」） |
| `?workspace_id=`（空串） | ✅ 404（不静默退化成"全部会话"） |
| OpenAPI | ✅ `SessionSummary.required` 含 `workspace`；类型为 `WorkspaceRef \| null`，`WorkspaceRef.required=['id','title']` |

### 观察到的一条可见行为（不是 bug，需 #155 决策）

`ws1-e2e` 的账本有 **6** 条，API 只返回 **5** 条。差额是 `e2dc33b6`——它的
`session/started.agent_id == "coding"`，即**内部子代理子会话**。#152 的 ADR-0025 D6 显式收窄：
内部子代理**不算项目成员**（运行期没有任何路径 attach 它们；纳入会让"同一类会话在不在项目里"
取决于它生于引导标记前后）。**后果**：这类子会话在**默认列表里仍会出现，但 `workspace` 是 `null`**
——即它与"用户真的没选项目"的会话在契约上**无法区分**。

- 与 #151 源码注释「子会话继承父 cwd 是为了不显示成未分组」**相反**（#152 交接时明确选了"过滤"）；
- #153 不改这个语义（不是它的 AC），**#155 做分组 UI 时必须决定**：折叠进父项目？
  按 `agent_id` 另行标注"子代理"？还是彻底不显示？契约层目前只给了 `null`，
  如果 #155 需要区分，`SessionSummary` 要再加一个字段（例如 `agent_id` 或 `parent_session_id`），
  那是 #155 的契约变更，不要在前端靠猜。

---

## 第十轮（2026-09-12）：WS-5 #155 项目分组 UI —— 交付 + 真机验收 + 第九轮待决策项的答案

**交付**（前端半；后端半 #153 / #154 已在 feat/backend）：会话侧栏「项目 → 会话」层级 +
未分组区 + 项目 CRUD（新建 / 重命名 / 加入 / 移出 / 项目内重排 / 软删除）。

| 文件 | 内容 |
| --- | --- |
| `src/types.ts` | `Project` / `ProjectStatus` / `ProjectDeleted`（后端 `web/projects.py` 逐字段对齐） |
| `src/lib/api.ts` | 7 个项目端点 + `ProjectError(status, message)` + `describeProjectError`（后端 detail 优先）+ 窄化解析 |
| `src/lib/projects.ts` | 纯函数：`buildRailModel`（分组投影）+ `moveAnchor` / `dropAnchor`（重排锚点） |
| `src/hooks/useProjects.ts` | 项目列表 + 动作；每次写操作后重拉（**不维护前端影子成员名单**，不变量 #22） |
| `src/components/SessionList.tsx` | 改版：项目块（折叠 / 行内重命名 / ⋯菜单）+ 行（点选 / ⋯菜单 / 拖拽重排）/ 未分组区 |
| `src/components/ProjectDialogs.tsx` | 新建 / 删除确认（**明示只解除分组**）/ 加入项目 三个 Radix Dialog + 行内重命名 |
| `e2e/r-project-groups.spec.ts` | 6 用例 × 2 视口（AC1–AC5 + 端点失败降级） |
| `e2e/fixtures.ts` | 项目端点的**有状态** mock（create/rename/attach/detach/order/软删除都真改状态） |

### 第九轮待决策项的答案（内部子代理子会话怎么显示）

**决定：照契约如实显示在「未分组」区，不折叠进父项目、不隐藏、不前端猜 `agent_id`。**
理由：#152 的 AC14 收窄明确「内部子代理不算项目成员」，所以后端给它的 `workspace` 就是
`null`——这是**真值**（它确实不属于任何项目）。前端把它藏起来才是制造第二套真相（不变量
#22）：同一个会话在"项目视图"里没有、在"列表视图"里也不该凭空消失。若将来要在视觉上
区分"子代理子会话"与"用户没选项目"，正确做法是**先加契约字段**（`SessionSummary.agent_id`
或 `parent_session_id`）再改 UI，不在前端从 id/标题猜——已作为后续票候选记录。

### 注册项目为什么不批量回溯 attach 该目录下的历史会话

**做不到，且不猜。** `attach` 的后端校验是「会话的 `session/started.cwd` == 项目规范路径」，
而 `SessionSummary` **不暴露会话 cwd** —— 前端无法判断"哪些未分组会话属于这个新项目"。
盲 attach 全部未分组会话只会得到一堆 409（还会把失败原因冲成噪音）。
**当前做法**：逐行「加入项目…」显式选择；后端 409 的 `detail` 原样显示（说明是 cwd 不一致）。
**建议**：若要"注册即归拢"，应由后端提供一个按目录匹配的端点（或在 `SessionSummary` 暴露
`cwd`），属新票。

### 🔴 用户原始诉求的最后一块缺口（不是 #155 的 AC，必须单独立票）

用户的原话是"怎么才能做到一个项目下多个会话"。目前：①项目能注册任意已存在的目录 ✅；
②分组/管理 UI ✅；③**但没有"在某个项目目录里新建会话"的入口** ❌ ——
`POST /api/sessions` 的 `workspace` 字段仍然只接受**单段目录名**（
`SessionService._validate_workspace_name` 拒绝绝对路径），会话的 cwd 永远落在
`workspaces_root/<name>`；而项目路径来自 bootstrap（`workspaces_root/<name>`，可 attach）
或用户注册的任意目录（**没有任何路径能产出 cwd 等于它的会话**，fork 除外）。
**后果**：用户注册 `D:\my-repo` 后，这个项目永远拿不到新会话。修法明确（让 create 接受
绝对路径并把 cwd 定为该目录，cwd 的写侧唯一规范化已存在于 `sandbox/paths.py`），
但**属后端契约变更，不在 #155 范围**。

### 真机验收（真 uvicorn 127.0.0.1:8000 + 真 `.env` + 真 SQLite + 真浏览器 5173，无任何 mock）

| 检查 | 结果 |
| --- | --- |
| 真实项目渲染顺序 = 注册表序（`ws2-e2e` → `ws1-e2e`） | ✅ 2 个项目 |
| 项目内会话数 = 账本长度（3 / 5） | ✅ |
| 未分组区行数 | ✅ 22 条（该次运行共 30 个会话，其中 8 条已分组；截图轮的 24 是因为随后两次真模型用例又新增了会话） |
| 注册临时目录（`.scratch/ws5-live-project`） | ✅ 标题默认取目录名 → 行内重命名生效 |
| 软删除（0 会话） | ✅ 确认文案含"不会/会话日志"；成功提示用后端原文（含"可重新注册同一目录"） |
| 注册真实目录 `workspaces/ws-delete-me` + 真会话 attach | ✅ 会话进入项目（cwd 相等后端放行） |
| detach → 再 attach → 软删除（1 会话） | ✅ 提示"1 个会话回到未分组"；会话仍在未分组、目录仍在盘上 |
| 真项目内重排 | ✅ 上移后后端账本序真的变（读 API 验证），下移后**精确还原** |
| **基线比对** | ✅ 项目（含账本序）与会话归属与开测前**逐字段相等**（30 条会话） |

截图：`web/gui-test-screenshots/ws5/`（01–06 真机流程、10–16 暗/亮/中/窄四态）。
**本地留存、未入库**：截图是运行时产物（1.3MB），与既有各轮一致不进版本库；跑
`e2e-live/project-groups-live.spec.ts` 或按上表步骤可复现同一组图。

### 视觉检查（impeccable）逮到并修复的 1 个真 bug

侧栏菜单（`.rail-menu`）最初复用了命令面板的 `palette-in` 关键帧，而那组关键帧带
`translateX(-50%)`（面板居中才需要）→ **菜单被永久左移自身宽度的一半**。
Hermetic e2e **全绿**（Playwright 点元素真实位置，位移不影响点击），只有人眼看截图才发现。
已改为独立的 `rail-menu-in`（只做 opacity + scale，并用 Radix 的
`--radix-dropdown-menu-content-transform-origin` 作为缩放原点）。
**教训**：跨组件复用 `@keyframes` 前先看它有没有把定位也写进关键帧里。

detector（`impeccable detect`）对本次改动文件：**0 findings**；`app.css` 里 4 条 `side-tab`
告警全部落在**既有**组件（行号 1584 / 2091 / 2169 / 3885，非本票插入段），按 Scope Lock 未动。

### 其它观察（都不改，记录在案）

1. **CORS `*`（后端既有）**：跨源 `POST /api/sessions` 实测 200 并真的起 run。项目端点本身
   已过来源闸（ADR-0025 D1 (b)），但会话端点没有。**建议后端单独立票**。
2. **56px 折叠轨下侧栏只剩图标按钮**：`.session-item-dot` / `.session-item-body` 的
   `display:none` 是**既有**规则（本票只往同一个 hide 列表里追加了项目 chrome），
   所以窄屏"看不见会话行"不是本票引入；要修应是独立票（例如窄屏显示首字母）。
3. `approval-live.spec.ts`（联调车道、非门禁）的「LIVE 拒绝」用例本轮连续 2 次失败：
   点拒绝后卡片未在 10s 内翻到「已拒绝」，但后端 `/approve` 日志是 **200**（决策已落库、
   工具后续如实 failed）。判断为**真实模型在同一 run 里再次请求审批**导致定位到新的 pending
   卡片（该用例自身的注释就写明"结果非确定，只作真机取证"）。**与本票 diff 无关**：
   本票未触碰 `ApprovalCard` / `api.postApproval` / 投影管线，门禁内的
   `e2e/n-approval-card.spec.ts`（真正的回归锁）全绿。

### 门禁（末次实跑，最终 revision）

`npx tsc -b` ✅ · `npx vitest run` **556 passed**（30 文件；本票新增 36 条：18 分组/锚点 + 18 契约）·
`npx oxlint` **0 errors**（37 warnings，全部既有规则；本票 10 个文件 0 warning）·
`npx playwright test --workers=2` **142 passed**（本票新增 12 例）· `npx vite build` ✅。

---

## 第十一轮（前端侧）（2026-09-12）：#155 两轴 code-review 的发现与修复（commit `8db0e5f`）

独立 Spec / Standards 两轴 review（只读、不看我的自述）一共给出 2 个 P2 + 若干 P3。
**两条 P2 都不是"代码不好看"，而是"会在真机或流式下真实发生"**，记在这里。

### P2-1：mock 的语义与真机**相反**——围栏绿灯证明不了契约一致

`e2e/fixtures.ts` 的 attach 把会话 `push` 到账本**队尾**，AC4 也因此断言
`['s1','s2','s3']`。真实后端写的是：

```python
# src/agent_harness/workspace/index.py::attach_session
await self._persist_ledger(record.id, [session_id, *kept])   # 前插
```

`tests/web/test_projects_api.py` 也用 `assert ids == [second, first]` 锁住"新建项目前插"。
**后果**：这条用例在真机后端下必然失败（我自己的 live spec 恰好只 attach 了单成员项目，
顺序不可观测，所以没暴露）。已把 mock 改为 `unshift`、断言改为 `['s3','s1','s2']`，
并在两处写明"顺序由后端账本决定，mock 必须跟它一致"。

**教训**：hermetic e2e 的绿灯只证明"前端与我的假后端一致"。凡是"顺序/归属/幂等"
这类由后端定义的语义，mock 必须逐条对着后端源码与后端测试写，否则围栏会**保护**
一个错误实现。以后写有状态 mock 时，先在后端找到锁住该语义的测试，再决定 mock 怎么写。

### P2-2：内联箭头破掉 memo → 流式期间整片侧栏重渲染

`App.tsx` 的 `onRetryProjects={() => {…}}` 每次渲染新建函数 → `SessionList`（`memo`）
的 props 每帧都变，流式 delta 期间整片 Session Rail 重渲染。本仓库对同名字段
（`handleSelect` 一列）有明文规则，这里是纯粹的遗漏。已改 `useCallback`。

### 其他修复（P3）

| 发现 | 处理 |
| --- | --- |
| `SessionSummary.workspace` 只在注释里"被消费"（注释声称两个真相源） | 真的消费它：项目不在当前列表里时未分组行带 `staleProject` 注解；注释改写成真实分工 |
| Pydantic **422 的 detail 是数组**，只认字符串 → "path must be an absolute path" 被降级成"注册项目失败（422）" | `readErrorDetail` 两种形状都认，剥掉 `Value error, ` 前缀；标题输入补 `maxLength`（后端 200 / path 4096） |
| `useProjects` 可能被乱序响应覆盖（旧列表盖新真相）；挂载 + 会话列表到位两次 GET 重复 | generation 守卫 + in-flight 合并；写操作后的 `refetch` 绕过合并（合并到一个写前发出的请求会让列表停在写前） |
| 拖拽落点提示在**别的项目**里也亮（跨项目拖动不是重排） | 记来源项目，落点只在来源项目内亮；跨项目 drop 直接忽略 |
| Enter 提交绕过 `disabled={pending}` → 双发 | 三处提交路径补 `if (pending) return` |
| `role="list"` 容器里混着非 `listitem` 子节点；`button` 被标成 `listitem` 丢"可按"语义;折叠时 `aria-controls` 悬空;`<p>` 里塞 `<ul>` | 删掉不成立的 list 角色；`aria-controls` 仅在展开时输出；`Dialog.Description asChild` + `div` 包列表 |
| 空项目提示引导"在该目录下新建会话"——**不可达**（`POST /api/sessions` 只接单段 workspace，建不出项目内会话） | 改文案：指向"加入项目…"并说明前提是会话 cwd 与项目路径一致 |
| 项目列表请求失败时仍显示"还没有项目"（与错误条自相矛盾） | 只在确实知道为空时才说 |
| mock 的 order 端点没有自锚点 no-op → "先删后 indexOf 插"会插到倒数第二位，凭空改账本 | 补 no-op（真实后端 `ProjectService.reorder` 显式挡下） |
| 不可达的 `/api/projects/resolve` mock 分支 + 无人使用的 `onProjectPost` 接缝 | 删掉（不可达的 mock 会让人以为那条路被测过） |
| AC3 的 404 detail 是我自己编的字符串，证明不了"透传" | mock 改用真实后端的 `[WinError 3] …` 原文，断言打在 `WinError 3` + 路径上 |
| attach 的 409 路径完全没有覆盖 | 新增 `onAttachPost` 拦截口 + 一条 e2e：后端原因就地显示、归属不变 |
| 56px 轨会隐藏 `staleProject` 注解（body 的既有 hide 规则） | **不改**：与行标题/事件数同一规则，窄屏只剩点是既有降级 |
| 软删除成功后的兜底文案丢了"什么都没删" | 补全（AC5 的安全感不能只留在后端文案里） |
| 因改版而死的 `.session-group*` 样式（4 条规则） | 删掉（本次改动产生的孤儿） |

### 视觉复核（新增的 `staleProject` 注解）

用真浏览器（hermetic mock 复现"项目列表 502"这一唯一会显示注解的状态）截了暗/亮两色：
注解在 meta 下方、斜体、三级灰、长标题省略号截断（全文在 tooltip 里），亮色下对比度可读；
未分组的正常行（`workspace=null`）**不带**注解——"孤儿"与"真的没选项目"在视觉上分得开。
窄屏（420px）注解随 `session-item-body` 一起隐藏，符合既有规则。

### 门禁（末次实跑，最终 revision）

`npx tsc -b` ✅ · `npx vitest run` **561 passed**（30 文件；本轮 +5：3 条 workspace 消费
+ 2 条 422 数组/null 回执）· `npx oxlint` **0 errors**（37 warnings，与改版前同数）·
`npx playwright test --workers=2` **144 passed**（本轮 +2：409 用例 × 2 视口）·
`npx vite build` ✅。`impeccable detect` 对本次改动 **0 新增**发现（4 条 `side-tab` 告警
落在既有规则上，按 Scope Lock 未动）。

顺带把 `--workers=2`（§16.6 硬要求）写进 `playwright.config.ts`：以前只有门禁命令带这个
参数，裸跑 `npx playwright test` 会默认 4 worker —— 那正是"门禁绿、本地红"这类
反复消耗排查时间的来源之一。

---

## 第十二轮（2026-09-12）：MEM-5 #160 记忆管理 UI —— 交付 + e2e 逮到的真 bug + 真机验收

**范围**：跨端票 MEM-5 的前端半（后端半 #159 已关单）。前端用户入口从「只有 API」变成
「看得见 + 删得掉」。契约来源：`src/agent_harness/web/memory.py`（`MemorySummary` /
`MemoryDeleted` / `GET /api/memories` 分页 / `DELETE` 的 200·404·403·503 语义）。

### 一、e2e 逮到的一个真 bug（本票唯一产品缺陷，已修）

| 项 | 内容 |
| --- | --- |
| 症状 | 读取失败（HTTP 500 / 网络断）时，面板**同时**渲染「还没有记忆」与错误条 |
| 根因 | 状态分支写成 `disabled → loading → visible.length === 0 → 空态 → 列表`，末条**漏了** `loadError === null`。于是"一条都没读到 + 读取失败"落进空态分支 —— 正是 AC4 明令禁止的「把读不到伪装成没有」（不变量 #21 同族） |
| 证据 | `e2e/s-memories.spec.ts` 的 500 用例断言 `.memory-empty` count 必须为 0 → **首版两视口都红**（也正是这条用例逼出该缺陷，不是事后补的） |
| 修复 | 空态条件改为 `visible.length === 0 && loadError === null`；「0 行 + 失败」只留错误条 + 重试 |
| 教训 | 「空 / 错 / 降级」三态是**互斥**的语义，不是"优先级排队"——分支链里任何一个 `&&` 漏写，就会把一种状态说成另一种 |

### 二、真机验收（真 .env / 真模型 / 真 Zilliz / 真 sqlite / 真浏览器 5173+8000）

种子数据走生产同一条装配 + `consolidate()` 契约（脚本 `.scratch/seed_real_memories.py`，
后端 worktree，不入库）。**实测三条都 `degraded=consolidation_failed: VectorStoreError`**：
外部向量服务当时不健康 → 按 #158「不丢写」设计降级为无条件 insert（记录行仍落盘，故列表有内容）。
这是**如实记录的环境事实**，不是本票缺陷。

| 验收项 | 真机结果 |
| --- | --- |
| 列表渲染 | 点顶栏 Brain 按钮 → 面板列出 3 条真记忆（content + `用户` chip + 本地化时间；`已全部加载`） |
| 二次确认文案 | 行内确认条：「这是硬删除，**删除不可恢复**——没有回收站，删掉后模型不会再想起这条。」 |
| 删除成功 | 确认后行消失 → `curl` 后端只剩 2 行 → 日志 `memory forget via api: forgotten` → **整页刷新**后再开面板该条仍不在（= 后端权威，不是本地隐藏） |
| 删除失败回滚 | **杀后端**后点确认 → 行**回到列表** + 「删除记忆失败（502）」+ 面板错误条「加载记忆失败（502）」+ 重试；重启后端点重试 → 列表恢复一致 |
| 真空态 | 经界面删光 → 「还没有记忆」（非降级态、无错误条）；`curl` 复查 0 行 |
| 503 降级契约 | `CAPABILITIES={}` 的另一实例（:8001）：真 GET/DELETE 都回 503 + `memory capability 未启用：请在 CAPABILITIES 中配置 memory。` —— 与 e2e mock **逐字一致** |
| 视觉 | 暗/亮两色 + 确认条截图复核；新增样式全部复用既有 token（无 §15 亮色遗漏问题） |
| 环境还原 | 种子记忆已全部经界面删除（真记忆库不留假事实，避免被模型当真召回）；dev server 已停（含残留 uvicorn 占 `.instance.lock` 的已知坑） |

### 三、门禁（实跑）

`npx tsc -b` ✅ · `npx vitest run` **580 passed**（31 文件）· `npx oxlint` **0 errors**
（38 warnings：37 既有 + 1 条本票同类）· `npx playwright test --workers=2` **160 passed**
（本票 +16 = 8 用例 × 2 视口）· `npx vite build` ✅。

### 四、过程自查

- **StrictMode 双跑会把"只失败一次"的 mock 立刻覆盖成成功**：首版 500 用例用 `failures -= 1`
  计数器，dev 下挂载 effect 跑两遍 → 第二个请求 200 → 错误条从未出现（用例假红）。
  改为「失败保持到测试显式关掉」。同理 `requested[1] === '?limit=50&offset=50'` 这种
  **按请求序号断言**在 StrictMode 下不稳（序号里混着重复的首屏请求）→ 改成
  「翻页前**所有**请求 offset=0；翻页后**存在** offset=50」。
  （这两个都是 mock 侧的测试写法问题，不是产品缺陷。）

### 五、批次审查（B-1，两轴 subagent）发现并修掉的问题

| 问题 | 性质 | 处置 |
| --- | --- | --- |
| 重拉 `limit` 越过后端硬上界（>4 页后 422）→ 回滚重拉与"重试"永久失败 | **真缺陷（AC3 破）** | `MEMORY_MAX_LIMIT` + `refetchLimit()` 夹取 + 3 单测 |
| 404（别处已删）的删除失败被界面吞掉 | **真缺陷（AC3 破）** | 面板级错误条 + e2e `memoryVanishedIds` + 1 用例 ×2 视口 |
| e2e 的 403 detail 是编的中文（真后端是 `Memory belongs to a different namespace`） | **测试保真度缺陷** | mock / e2e / 单测统一改用真后端原文 |
| DELETE 挂死无超时 → 行隐藏 + 按钮永久禁用 | **真缺陷（"点了没反应"）** | `lib/timeout.ts` + `DELETE_TIMEOUT_MS=30s` + 4 单测 |
| `MemoriesState.rows` 无消费方 | 判断项 | 去掉导出 |
| `.project-dialog-*` 类名复用 / `describeMemoryError` 与 `describeProjectError` 同形 / v2 与 §16.1 的协议矛盾 / AC4"检索不可用"在后端无独立状态 | 判断项 + 只登记 | 3 条说明理由不改（§8 Scope Lock）；1 条只登记（503=未装配、5xx=读取失败即事实上的"暂不可用"） |

**修复后门禁**：tsc 0 · vitest **587** · oxlint 0 error（38w）· playwright **162** · vite build ✅；
**修复后真机复验**：3 条 → 界面真删 1 条 → 后端剩 2 条 → 再删 2 条 → 后端 0 条 + 面板「还没有记忆」。

## 第九轮（2026-09-12）：PromptRegistry 迁移期的后端观察（自主 SDD 批次）

本轮在 `feat/backend` 自主推进 #150 + #161–#168 + #149–#160。迁移类票的验收靠
**逐字节等价**，所以下面的观察全部是"后端 / 文档"性质，无前端问题。

### OBS-9.1 【后端·已修】`--help` 曾被单实例锁挡住（#150）

`cli.main()` 最初无条件取锁，导致服务在跑时 `agent-harness --help` 也会以 rc=2 被拒。
`--help` 不触碰 session root（argparse 直接打印帮助退出），不该被锁挡住。
**修复**：`-h/--help` 走豁免路径，但仍守 ADR-0018 D3 的 `flush_process_sink` 契约
（既有测试 `test_cli_main_flushes_on_normal_exit` 正是这条契约的裁判——修复时它先红，
证明该测试有效）。**归属：后端**。

### OBS-9.2 【后端·设计约束，非缺陷】Windows 区间锁是 mandatory 的

`msvcrt.locking` 锁住某个字节区间后，**同进程的另一个句柄**读该区间也会被拒
（`PermissionError`）。若锁 byte 0，锁文件里写的 `pid=` / 诊断信息就再也读不出来，
第二进程的错误信息会退化成"未知占用者"。
**处置**：锁区间取在载荷之外的偏移（`1 << 20`），载荷区保持可读。
**归属：后端**（POSIX `flock` 是 advisory，无此问题）。

### OBS-9.3 【后端·flaky·已确认与本次改动无关】`test_disconnect_leaves_run_running_and_cancel_stops_it`

`tests/test_web_api.py::test_disconnect_leaves_run_running_and_cancel_stops_it`
（WebSocket 断开 / cancel，5s 超时）在全量跑中**间歇性失败**：

- 2026-09-12 T3 期间全量跑出现 1 次失败 → 同 commit 重跑两轮全绿，单跑绿，整文件跑绿（28 passed）。
- T4 的独立审查者（只读子代理）在**同一份代码上跑 5 次：2 次失败 / 3 次通过**，
  并验证 **clean HEAD 归档同样通过**、`test_web_api.py` **不在本批任何 diff 里**。
- 本 Agent 的 T4 全量跑一次通过（1706 passed / 0 failed）。

**结论**：与本批 PromptRegistry 改动无关，属既有 flaky（n=5 命中率约 40%，样本小）。
**未定位，本轮不追**（§8 Scope Lock：scope 外问题只报告不顺手修）。
若后续修：方向是"客户端断开后 run 应继续 + cancel 应停住"的时序竞态
（websocket 断开与 `RunManager.cancel` 的先后），建议先加确定性同步点再断言，
**不要靠放宽超时**——那只会把竞态藏得更深。
**归属：后端（测试稳定性）**。

### OBS-9.4 【文档·已报告未改】PRD §10.7 / §10.2 与实现不一致

- §10.7 的 `AssembledPrompt` 代码块只列 2 字段，§10.4 与交接文档 §4.2 要求 3 段
  （含 `fragment_text`）；#162 票面自身 step 1 亦为 3 字段。
- §10.2 导出清单缺 `run_self_check`（T2 引入）与 `DEFAULT_REGISTRY`（T3 引入）。
- §10.8 把"模板语法"列为自检职责，实际由 `register`（R3a）承担。
按交接文档 §2「不要自行改两边」，**只报告不改**。
**归属：文档**。

### OBS-9.5 【后端·本 Agent 自己的错误说法，已修正】T5 与 `DEFAULT_REGISTRY` 的关系

T3 落地时我在 `builtin.py` 注释与两个测试 docstring 里写了"T5 会让 `DEFAULT_REGISTRY`
带上 persona"——这与交接文档 §4.4（`DEFAULT_REGISTRY = build_registry()` **永不读环境**、
persona 由装配点 `build_registry(persona=…)` 注入）矛盾。若按我原来的说法实现 T5，
`_builtin_prompt` 会变成环境相关，`profile:*:identity` 的逐字节断言会在设了
`AGENT_PERSONA` 的机器上红。
**已在 T3 内修正注释与 docstring**（无行为变化），并把
`test_default_registry_equals_build_registry_in_p0` 重述为**该不变量的机器化表达**。
**归属：后端**。

### OBS-9.6 【后端·潜在顺序隐患，未触发】`harness:identity` 的 order 早于 `persona:prefix`

`SECTION_ORDERS` 里 `harness:identity = -1000`，而 `persona:prefix = 0`。父路径走
`registry.assemble()`（按 order 排序）时 harness 段本应在 persona 前缀**之前**；
但 child 路径走 `apply_persona(base, persona)`，它把 persona 前缀硬放在最前。

今天不会出问题：`harness:identity` 是**预留键**，`_BUILTIN_SECTIONS` 里没有这条
section，所以父/子两条路径一致（`test_apply_persona_matches_registry_order` 绿）。

若将来有人为 profile scope 注册 `harness:identity`，**漂移守卫会立刻变红**——这正是
那条守卫的主要未来价值（它比较的是活的注册表，不是硬编码期望值）。届时需要决定：
让 `apply_persona` 也感知 order，或把 harness 段移出 persona 包裹范围。
**归属：后端（T5 已知边界）**。

### OBS-9.7 【文档·命名漂移】交接文档 §4.5 的 `compose_agent_prompt` 与实现名不一致

`docs/HANDOFF_PROMPT_REGISTRY.md` §4.5 写 persona 拼接用
`compose_agent_prompt(base, persona, guidance_text)`，实际交付的是
`apply_persona(base, persona)`（#165 票面本身 prescribed 这个名字，票面优先）。

T6 加 tool guidance（order 2000）时**无需改 `apply_persona`**：它包裹的是**已组装完**
的 profile 文本，guidance 已含在 base 里，顺序天然正确。§4.5 的名称与三参签名已过期。
**归属：文档**。

## 第十轮（2026-09-12）：Memory 生命周期（#156 MEM-1）期间的后端观察（自主 SDD 批次）

### OBS-10.1 【后端·既有 flaky，负载相关·已确认与本票无关】OBS-9.3 那条用例

`tests/test_web_api.py::test_disconnect_leaves_run_running_and_cancel_stops_it` 本轮先表现为
"约 40% 命中率的 flaky"，随后出现**本机 3/3 连续失败**（隔离跑、整文件跑都失败；10s 上下），
再之后又回到**时好时坏**。**2026-09-12 #157 复核（同一份工作区代码连跑 3 次：pass / fail /
pass；stash 掉全部工作区改动后在 commit `ff57700` 上跑：pass）——所以它既不是确定性失败，
也不由本票代码决定。** 下面记录的根因与冷路径成本仍然成立，只是"确定性"这个措辞要撤回：
它是**负载相关的间歇失败**。
定位到的根因（与 OBS-9.3 的猜测不同，不是断连时序竞态）：

1. 失败断言是 `_DisconnectingASGI` 的 `"app 未在 5s 内响应 disconnect"`；
2. 抓到的 traceback 停在一个 **TLS 读**上（`anyio/streams/tls.py` → `_ssl_object.read`），
   而该 await 属于 `POST /api/sessions` 的**端点处理路径**（`starlette/routing.py` 的
   `dependant.call` 之下），即请求路径里真的有外部 HTTPS 调用；
3. 该外部调用来自 `.env` 里启用的 capability 装配（本机 `CAPABILITIES` 含 `memory`，
   provider `builtin`）→ 首次装配会 `MilvusVectorStore.initialize()` 真连 Zilliz；
4. 实测本机冷启动成本：**Milvus 冷 connect 2.01s**（热 0.29s）＋ **langmem 冷 import 1.32s**，
   再加会话创建与其余装配，冷路径突破该用例 **5s** 的预算。

**不是本票引入**（用 stash 证明）：把 #156 的全部工作区改动 `git stash` 掉、在**同一个
commit（f70ebe7）**上复跑，该用例**同样失败**；而该 commit 今天早些时候的全量跑是绿的 —
即失败随**机器/网络负载**漂移，不由本票代码决定。本票 diff 只在 `memory/` + 测试 + ADR。

**本轮不修**（§8 Scope Lock：scope 外问题只报告）。若后续修，按 OBS-9.3 的原判断**不要
放宽超时**，正确方向是让计时块不再包含冷装配：在计时块**之前**预热 capability 装配
（只读探针或显式 `await app.state...initialize()`），或让该用例显式密封 `CAPABILITIES`
（本仓 `tests/conftest.py` 只清洗 Settings 的**环境变量**，`.env` 文件仍会被 `Settings()`
读到——这是同一根因的另一条已知路径）。**归属：后端（测试稳定性 / 装配期外部依赖）**。

**2026-09-13 已修（集成期 `feat/backend`）：按上述规定的方向落地——计时块**之前**预热，
**未放宽 5s 预算**。** `_DisconnectingASGI` 增加 `budget_s` 参数（默认仍 5.0，测量请求沿用它）；
测试在测量请求前先发一次**预热请求**（`_ImmediateRuntime` + `budget_s=60`），把
`POST /api/sessions` 的一次性冷装配在测量窗外付掉。选预热**真实请求**而不是
`await app.state...initialize()` 的理由：被测成本就落在这条端点路径上（`get_wiring` 缓存 +
能力装配），预热同一条路径最忠实，且对"冷 connect 到 Zilliz"这类外部耗时一并免疫。
**独立实测（本机 2026-09-13）**：预热请求 **6.546s**（冷）→ 测量请求 **0.005s**；
Python 层 socket 埋点（`getaddrinfo` / `create_connection`）**零调用**，说明这段冷成本走的是
C 扩展的 gRPC/TLS 通道，与上面记录的 `anyio/streams/tls.py` TLS 读、Milvus 冷 connect 2.01s 相互印证。
**验证**：单测在**全新冷进程**连跑 4 次 **4/4 passed**（修复前同条件 4/4 failed）；
全量 **2135 passed / 0 failed**（修复前 `2134 passed / 1 failed`）。

### OBS-10.2 【后端·真机集成用例的冷 connect 抖动·#157 期间观察】同一个冷路径也在真机集成用例上出现

`tests/integration/test_phase6_memory_e2e.py::test_real_connection_and_missing_collection`
（#156 期加入）在 #157 的复核里**偶发失败**：整文件跑（5 条，热机）时它挂了，单独重跑
**3.11s 通过**。同一轮里 `.scratch/run_langmem_actions_gate.py` 也撞到过一次同样的形状——
`MilvusVectorStore._call` 的 SDK `timeout=15` 被**冷握手**吃掉（实测单次 `list_collections`
冷启 16.7s），归类成 `VectorStoreError("unavailable")`，与"集合不存在/凭证错误"这些真实故障
无法从错误类型上区分开。

隔离结论：与 #157 的改动无关（该用例只 `connect()` 与查一个不存在的集合，不碰
drain/real_count/drain 重构）。**本轮不修**；两条可选的后续方向（都属 #156/#157 之外的稳定性
工作）：(1) 给真实集成用例的首次 `connect()` 加预热/重试（gate 脚本本次就是这么绕过的）；
(2) 更根本地把"冷握手超时"与"真实故障"在错误分类上区分开（例如超时单列一个 category），
否则生产启动期的首连抖动会被误报成 `unavailable`。**归属：后端（memory 真机测试稳定性）**。

---

## UI Polish 批次登记（2026-09-12，U-1 批量审查 defer 项）

来源：U-1 批量两轴 code-review（diff `cd107a2..1ae3bf2` + 修复）。以下三项**有意 defer**（非遗漏）：

1. **UIP-DEFER-1（P3，安全边界）**：ApprovalCard 同帧双 keydown 理论双 POST——`decide` 的 busy 是异步 setState，同一帧内两次独立 keydown 会复用旧 `busy=false` 闭包。人手触发概率极低（需同帧两次独立按键事件）；根治方案 = decide 内加请求在途同步标志（ref）。键盘路径已由「仅 autoFocus 卡挂监听」把暴露面收窄到单卡。
2. **UIP-DEFER-2（P3，a11y 边界）**：`aria-labelledby/describedby` 直接内插 `approval_id`——id 含空格/引号时引用失效。后端 id 形如 `ap-…` 安全；若后端未来放宽 id 生成规则，需在前端做 id sanitize（或改用 ref + setAttribute）。
3. **UIP-DEFER-3（P3，测试缺口）**：审批卡 `{old,new}→DiffBlock`、`{command}→approval-cmd` 的**渲染级**断言（浏览器 DOM 级）未补——现有覆盖 = 分类级单测 + path/content 形状的 t-contrast 渲染断言。计划 UI-03 批次动 StepDetail 时顺带补（同一审批 fixture 基建）。

另登记两个**边界项备案**（R1 accent 审计中的两处留用，非交互但语义特殊）：`detail-section-title svg`（面板标识 icon）与 `workspace-scaffold-tag`（Split/Preview 诚实占位标记）——若后续 review 认为违反 One Voice Rule，整改点在此。

---

## 第十一轮（后端侧）（2026-09-13）：会话硬删（#172 / ADR-0029）真机验收 + 全功能点击（后端 AI 独立执行）

**车道**：前端 `D:\intelligence-agent-frontend`（`feat/frontend`，含 #172 前端半 `57dd028`）dev server `:5173`；
后端 `D:\intelligence-agent-backend`（`feat/backend`，含 #172 后端半 `4109b08`）uvicorn `:8000`；
浏览器 Chrome DevTools（CDP），视口 **1440×900**。

> ⚠️ **环境前置（不是缺陷，但会让人误判）**：本轮开始时的浏览器视口 **< 820px**，会话行的 kebab
> 菜单被媒体查询整块 `display:none`，于是「删除会话…」看起来"不存在"。**验收必须在 ≥820px 视口做**，
> 否则会把响应式隐藏当成功能缺失。已把视口固定为 1440×900 后复测（见 SID-02 的窄视口结论）。

### 已通过（作为证据登记，非问题）

- **`SID-P0` 会话硬删全链路（#172 前端半 + 后端半）真机通过**。步骤与证据：
  1. 用 UI 新建一个一次性会话（`6d2f6b90-8d6d-4c57-a513-2a0f45fda034`，任务「只回复两个字：OK」，
     15 事件；`model/fallback deepseek-v4-flash-0731 → glm-4.5-air` 是设计内回退）。
  2. kebab → 菜单三项（加入项目… / 新建项目… / 删除会话…）→ 「删除会话…」→ 确认弹窗：
     文案含「**硬删除，不可恢复**」「没有回收站、没有撤销」，并显示标题 + id 片段；确认按钮写
     「永久删除（不可恢复）」。
  3. **取消路径零请求**：点「取消」后 `role="dialog"` 消失、行仍在，网络面板无任何 `DELETE`（只有之前的 GET/POST）。
  4. 确认删除 → `DELETE /api/sessions/6d2f6b90-…` → **200**，响应体与 ADR-0029 契约逐字一致：
     `{"id":"6d2f6b90-…","deleted":true,"events":17,"detached_from_projects":0}`。
  5. 前端收敛（实测）：行从 33 → 32 消失；对话区回到「暂无对话」空态；**RUN INSPECTOR 面板整体消失**；
     `localStorage` 清空（记住的会话 id 已清，刷新不会被拉回死会话）；URL 无死 id；随后自动重拉
     `GET /api/sessions` + `GET /api/projects`。
  6. 后端收敛（实测）：`sessions/<sid>/`、`workspaces/<sid>/`、`workspaces/<sid>.json` 三条路径全部不存在；
     `session_meta` / `operations` / `checkpoints` / `workspace_sessions` 四表该 id 计数全为 0；
     `GET /api/sessions` 32 条不含它；`GET /api/sessions/<sid>/events` → **404**。
  7. 审计（实测）：`.agent/logs/agent.jsonl` 恰有 1 条 `session_delete`，字段只有
     `session_id` / `events=17` / `detached_from_projects=0` / `repaired_delegation_links=0` + 时间戳，
     **不含任何会话内容**（ADR-0029 D7）。
- **列表 `事件数` 与删除回执 `events` 可以不一致，且这是对的**：列表行显示 15、回执 17。差值是 run
  完成**之后**由 memory capability 追加的 2 条事件——列表是拉取时的快照，回执是删除前现取的真值。
  前端半刻意**不**把列表里的 `event_count` 放进确认弹窗（`DeleteSessionTarget` 不含事件数），
  正是为了不拿二手值当事实陈述。此处前后端口径一致，非缺陷。

### 问题清单（本轮）

#### SID-01 【前端·P2·设计确认项】≤820px 视口下删除会话入口彻底不可达

- **现象**：视口 < 820px 时，会话行的 kebab（`.rail-menu-btn`）被 `@media (max-width: 820px)` 置为
  `display: none`，且会话行内部**没有替代入口**（无右键菜单、无长按菜单、无行内删除）。删除会话
  这个功能在窄窗口/小屏上**物理上无法触达**。
- **证据**：`getComputedStyle(kebab) → {display: none, opacity: 0, rect: all-zero}`；
  CSS 规则实测为 `.rail-menu-btn { opacity: 0; width:22px; height:22px }` +
  `.session-row:hover .rail-menu-btn, .session-row:focus-within .rail-menu-btn, … { opacity: 1 }` +
  `@media (max-width: 820px) { … .rail-menu-btn { display: none } }`。
- **注意**：同一媒体查询也隐藏 `项目` 分组头菜单（`.rail-project-head`），所以窄视口下**项目重命名/软删
  也不可达**——这是既有设计（不是 #172 引入的），但 #172 让"不可达的后果"从"不能整理"升级成"不能删数据"。
- **建议**：要么把 820px 断点下移/允许横向滚动，要么在窄视口给一个替代入口（行内 `…` 或长按）。
- **归属**：前端。**修之前先确认产品是否支持窄视口**（当前更像桌面工具，若明确不支持则本项标 `不改（理由）`）。

#### SID-02 【前端·P2】删除确认弹窗的初始焦点落在「关闭(X)」

- **现象**：弹窗打开后焦点在右上角 `关闭` 按钮（`uid=8_2` / `11_2`，`focusable focused`），而不是
  「取消」。键盘用户回车/空格会直接关闭弹窗（后果无害），但焦点位置与"危险操作默认落在安全项"的
  通行做法相反；风险点是**键盘用户按 Tab 的落点顺序**（关闭 → 取消 → 永久删除），而不是误删。
- **建议**：Radix `onOpenAutoFocus` 指到「取消」。
- **归属**：前端。

#### SID-03 【文档·P2】`docs/ACCEPTANCE_LANE_ENV.md` §2 的"期望能力集"已过期

- **现象**：文档写「期望 count=2: websearch + multiagent」，实测 `GET /api/capabilities` 返回 **3**：
  `websearch` + `multiagent` + **`memory`**（#159 MEM-4 之后接入的）。
- **影响**：接手验收的人按文档核对会以为多出来的 `memory` 是异常，或反之漏检。
- **建议**：§2 期望值改为 3（并说明 memory 提供什么面）。
- **归属**：文档（后端侧维护）。

#### SID-04 【流程·P2】`docs/FRONTEND_ISSUES_LOG.md` 在两个 worktree 之间已**分叉**

- **现象**：同一路径下两份内容不同——`feat/backend` 工作区 1502 行（末轮=第十轮），
  `feat/frontend` 工作区 1780 行；**两边都有「第九轮」但内容不同**（后端侧=PromptRegistry 迁移观察，
  前端侧=WS-3 #153 列表契约）。合并时必然撞车，且"第十一轮"这个编号在两侧会指向不同东西。
- **本轮的处置**：按 AGENTS.md §13.1.3（不共用一个 worktree）**只写本工作区（feat/backend）这一份**，
  不动前端工作区那份。
- **建议**：集成 AI 在合并时把两侧各轮**按时间顺序保留并在冲突处重新编号**（append-only 日志不允许
  丢任何一轮），此后约定"谁改哪个 worktree 就往哪份写"或统一收敛成一份。
- **归属**：集成。

### 第十一轮 · 追加（同一轮继续，2026-09-13）

#### 已通过（证据登记）

- **`SID-P0b` 删除成功后的回执态**：确认删除后弹窗**不立即关闭**，而是切成回执：`role="status"`
  实时区播报「已永久删除 17 条事件记录（不可恢复）；它不在任何项目里。」+「完成」按钮。
  两个数字都取自后端响应（`events` / `detached_from_projects`），与 ADR-0029 的回执意图一致。
- **`SID-P0c` 刷新一致性（用户点名项）真机通过，且是逐字节一致**。同一会话 `7cf291d1`（59 事件、
  含 delegate 委派）刷新前后指纹完全相同：
  | 指标 | 刷新前 | 刷新后 |
  | --- | --- | --- |
  | `body.innerText` 哈希 | `1507534181` | `1507534181` |
  | 正文字符数 | 4339 | 4339 |
  | 选中会话（`ahi.selectedSession`） | `7cf291d1-…` | `7cf291d1-…`（同一行仍带 selected） |
  | Inspector 页签 | `Timeline59 / Overview / Changes0 / Terminal0 / Artifacts0` | 完全一致 |
  | 委派内容（Tavily/委派行） | 在 | 在 |
  机制：`lib/sessionRestore.ts`（`ahi.selectedSession` + 恢复游标），源码注释写明它就是为
  BUG-005「刷新后选中的会话与全部内容消失」修的——本轮实测确认该修复在真机上成立。
  **附注（非缺陷）**：选中会话**不进 URL**（无路由 / 无 hash），所以不能靠链接直达或分享某个会话；
  刷新恢复完全依赖 localStorage（清掉 localStorage 或换浏览器即回到空态）。若将来要"可分享链接"，
  这是要新做的功能，不是当前 bug。
- **密度四档（紧凑/均衡/详细/Raw）全部有反应**：正文长度 4339 → 4281 / 4339 / 4691 / 6440（Raw 最全），
  切换即生效且**跨刷新保持**（`ahi.traceDensity`）。
- **思考块展开 / 运行折叠：有反应**（+3 / −424 字符）。
- **Run Inspector 五个页签全部有反应**：Overview / Changes / Terminal / Artifacts 均切换出对应面板
  （Timeline 点第二次无变化属正确——它本来就是选中页签，重复点击是幂等的）。
- **`Esc` 关闭令牌浮层：有效**。⚠️ 过程记录：用页面内合成 `KeyboardEvent('Escape')` 关不掉它，
  一度误判为"浮层关不掉"；改用**真实按键**（CDP `press_key`）后立刻关闭。结论：那是合成事件的
  限制（Radix 只信真实按键），**不是产品缺陷**——记在这里以免下次有人重踩。

#### 方法学备注（写给下一轮验收的人）

1. **视口必须 ≥820px**，否则 `.rail-menu-btn` / `.rail-project-head` 被媒体查询整块隐藏（见 SID-01）。
2. **页面内合成 `.click()` 对 React `onClick` 有效，对 Radix 触发器无效**（Radix 菜单/弹层要
   `pointerdown` 序列）。所以：批量撒点可以用合成点击做**初筛**（筛出"没反应"的候选），
   但每个候选必须再用**真实点击**复验后才能登记成缺陷——否则会把合成事件限制误报成 bug（本轮
   Escape 与 kebab 都踩过这个坑，两次都由"真机复验"纠正）。
3. 危险词（删除/清空/永久/重置/移除）与会起 run 的词（发送/新建会话/分叉）**不进自动撒点**，
   逐个手点并单独验证。

### 第十一轮 · 追加二（2026-09-13，同轮继续）

#### 已通过（证据登记）

- **`SID-P0d` fork 父会话删除 → 409 守卫真机通过，且零副作用**。语料：`7c681c45`（6 事件）
  是 `40ee6420` 的 fork 父（`GET /api/sessions/7c681c45…/lineage` → `children[0].origin="fork"`）。
  路径：kebab → `删除会话…` → 弹窗 → 真实点击 `永久删除（不可恢复）`。
  实测结果：
  | 断言 | 期望 | 实测 |
  | --- | --- | --- |
  | HTTP 状态 | 409 | 409 |
  | 弹窗内错误文案 | 后端 detail 原文 | `session '7c681c45-…' is the fork parent of 1 session(s): delete the child session(s) first` |
  | 弹窗状态 | 保持打开（不静默关闭） | 保持打开 |
  | 会话列表条数 | 不变（32） | 32 |
  | 父/子目录 | 都在 | 都在（`.agent/workspace/sessions/…`） |
  | 子的血缘 | 父链不断 | `ancestors=["7c681c45"]` |
  **⚠️ 安全提示**：这一步是**不可逆操作的真机演练**，执行前必须先把父、子两个会话目录
  `cp -r` 到临时目录留底（本轮已做），确认守卫生效后再删备份；否则守卫若失效就直接毁掉语料。
- **`ACT-01` 工具卡 `Inspect` → Step Detail 全链路有反应**（会话 `a39876d7`，280 事件）：
  点 `Inspect`（`.act-inspect-chip`）后出现 `.step-detail`（头部 `返回 Timeline` + 工具名 + 耗时），
  子页签 `Input` / `Output` / `Raw` 分别渲染出 `{query, k}` / 原始 `output` 字符串 / 同 Output 的 raw 视图；
  点 `返回 Timeline` 回到时间线。对话内同时出现 `.act-detail-inline`（INPUT/OUTPUT 内联块，4 个）。
- **`ACT-02` 对话区 32 个控件全部枚举完毕**（`.conversation` 内可见可点元素）：
  4× `分叉` + 8× `折叠`/展开 + 6× `思考`头 + 6× `复制回答` + 4× `act-node` + 4× `Inspect` + 2× json 折叠。
  `分叉` 的 `title` 会按上下文区分：本轮之前无历史时 = `本轮之前没有历史：child 会话将是空会话`，
  否则 = `从此处分叉新会话`（正确反映 fork 语义差异，不是文案 bug）。

#### 委派 / 分叉 / 审批 控件逐个点击结果（真机）

| 控件 | 语料 | 结果 | 证据 |
| --- | --- | --- | --- |
| `展开结果摘要`（`.deleg-row-expandable`） | `7cf291d1` | **通过** | 展开后节点内出现子代理结论「Python 官网网址是 https://www.python.org。」 |
| `复制子会话 ID`（`.deleg-child-row .copy-btn`） | 同上 | **通过** | `class="copy-btn"` → `"copy-btn copied"`，`aria-label`/`title` 由 `复制子会话 ID` → `已复制`，图标 Copy→Check |
| `复制回答`（`.copy-btn`） | 同上 | **通过** | 同上（`aria-label=已复制`） |
| `Inspect 子会话`（`.deleg-open-btn`） | 同上 | **通过** | Inspector 头由 `Run Inspector` → `Run / 子会话 · research_review / 6eed381f`，面板内容切到 child 的 run（`7d845d27`、2 轮、9 事件、`web_search`），**父会话时间线仍在**（与 title 承诺一致） |
| `打开子会话`（`.deleg-open-btn`） | 同上 | **通过** | `ahi.selectedSession` 由 `7cf291d1…` → `6eed381f…`，主窗切换 |
| child 视图 `Run` 返回（`.child-back-btn`） | 同上 | **通过** | 头由 `Run / 子会话…` → `Run Inspector / 1 runs · 59 事件`（会话 `7cf291d1`），回到父视图 |
| `加载更早 N 条`（`.timeline-earlier`，在 **Inspector 的 Timeline 页签**内，不在对话区） | `a39876d7`（280 事件） | **通过** | 提示行 `显示最近 200 / 共 280 条（前段已折叠，真相完整保留）`；点一次 → 行数 `200 → 280`，按钮消失（已全加载） |
| `分叉`（`.fork-btn`） | `34276f99` | **通过** | 会话数 `32 → 33`，`ahi.selectedSession` 跳到新 child `e82249fc…`，头部 `空闲`，无错误条；child 事件流 = `session/started` + `session/forked`（`parent_session_id=34276f99…`），`/lineage` 确认 `ancestors=[34276f99…]` |
| 硬删（对**分叉 child** 复用一次） | `e82249fc` | **通过** | 回执「已永久删除 2 条事件记录（不可恢复）；它不在任何项目里。」→ 列表 `33 → 32`，选中态清空（`null`） |

**⚠️ 分叉无二次确认（记录为设计观察，非缺陷）**：`App.tsx:399 handleFork` 点一次**立即**调
`POST /api/sessions/{id}/fork` 并跳转到 child，没有确认弹窗。判断：这是**创建**语义（非破坏性）、
且有 tooltip 说明 child 会是什么（`本轮之前没有历史：child 会话将是空会话` / `从此处分叉新会话`），
连点也有 `forkInFlightRef` 挡住同一 origin 的在途请求。故不登记为缺陷；若产品希望"一键不可撤销创建"
收敛，再另开票。

**⚠️ ADR-0029 D2（永不删 `workspace_root`）在分叉场景得到真机验证**：fork child 的
`session/started.cwd` 指向的是**父会话的** workspace 目录
（`…\workspaces\34276f99-…`）。删掉这个 child 后实测：
`child 会话目录 = 已消失`、`父会话目录 = 完好`、`父 workspace 目录 = 完好`、会话总数回到 32。
即删除只按 `<root>/<sid>` 与 `<workspaces>/<sid>*` 两个自有路径动手，**没有**顺着映射去删父目录。
这条是"删 child 顺手把父的工作区一起删了"这类灾难的最低成本防线，值得保持。

#### 刷新一致性（用户点名项）· 第二轮：富语料 + **运行中刷新**

**A. 视图态刷新前后对照（会话 `a39876d7`，280 事件，`density=detailed`，页签=Changes）**

| 指标 | 刷新前 | 刷新后 | 结论 |
| --- | --- | --- | --- |
| `ahi.selectedSession` | `a39876d7…` | `a39876d7…` | ✅ 一致 |
| `ahi.traceDensity` | `detailed` | `detailed` | ✅ 一致 |
| 轮次数量 / 工具卡数量 | 4 / 4 | 4 / 4 | ✅ 内容一致 |
| Inspector 激活页签 | **`Changes1`** | **`Timeline280`** | ⚠️ **丢失**（回默认页签） |
| Timeline 尾窗 | 280 行（已点过「加载更早」） | 200 行（按钮重新出现） | ⚠️ **丢失**（回默认窗口） |

→ **观察·P2（非阻断）**：Inspector 的**视图态**（当前页签、Timeline 尾窗大小）不跨刷新保留，
而选中会话/密度/主题是保留的（都在 localStorage）。用户点名的"刷新后会话要和刷新前一致"
指的是**会话内容**——这一条**成立**；页签/窗口回默认属于"视图态未持久化"，是否要一起持久化
由产品定，本轮不当作 bug。

**B. 运行中刷新（真正的危险路径）· 会话 `43e7b46e`**

步骤：composer 输入 `只回复：ok` → 点发送 →（`发送` 立刻变 `停止`，5 个 picker 全部
`disabled`——与清单 §A 第 189 行一致）→ **运行途中真实刷新页面**（reload）。

结果（刷新后 14 秒内三次采样，状态稳定）：

| 断言 | 实测 |
| --- | --- |
| 选中会话 | 仍是 `43e7b46e…`（未跳走、未回空态） |
| 消息是否丢失/重复 | 事件流 `user/message` **= 2**（原有 1 + 新增 1），**无重复**；`run/started`/`run/completed` 各 2 |
| 后端是否继续把这一轮跑完 | **是**：`run/completed`，`final_text="\nok"`，并伴随 `model/fallback`（`deepseek-v4-flash-0731 → glm-4.5-air`，`reason=InternalServerError`） |
| 刷新后 UI 是否与事件流一致 | **是**：对话区 `第 1 轮 / 第 2 轮`，两条都是 `ok`，模型徽标 `glm-4.5-air`，第 2 轮有思考块 |
| 失败/降级是否可见 | **是**：Inspector Overview 的 MODEL 区显示 `已切换 deepseek-v4-flash-0731 → glm-4.5-air · InternalServerError` + `用量 3,400 tok（3,355 + 45）` |
| 是否卡在"停止"态 | 否，刷新后 `发送` 可用（无悬挂 streaming） |

源码侧机制（与真机一致）：`hooks/useSession.ts:366-379` 加载历史后
`if (hasUnterminatedRun(events)) resumeLiveStreamRef.current?.(sid, maxEventSeq(events), projected)`
——即"先渲染历史，再按未收口 run 接回实时流"（注释直指 BUG-006）。另外
`hooks/useSession.ts:383-388`：记住的选中会话若已不存在（被删/换后端）→ 清 key + 静默回空态，
不弹无法处理的错误（与"删掉当前选中会话后 `ahi.selectedSession=null`"的实测一致）。

**结论**：刷新一致性在"内容"这一层**真机通过**（含运行中刷新的续跑与对账）；仅"视图态"未持久化。

#### MOD-01 【前端·P1】composer 选「默认链」**不发请求**：界面说「默认链」，会话实际仍跑上一个非默认模型（同屏自相矛盾）

> 来源：Subagent（composer 扫描）静态定位 F3 → **本 Agent 动态复现并确认为真**（subagent 为保护真实数据主动回避了动态验证）。

- **语料**：`fb3619c6-9817-487c-9a10-59bd3716ad1a`（cwd `ws2-e2e`，6 事件，原本无任何 `model/changed`）。
- **真机步骤与硬证据**（判据是**会话 JSONL 里有没有新的 `model/changed` 事件**，不靠 UI 自述）：
  1. 选中 `fb3619c6` → composer 模型 picker 显示 `默认链`。选 **`glm-5.3-flash`** →
     **新增** `seq 6 model/changed {from=None → to=glm-5.3-flash}`（POST 生效）。
  2. 再选 **`默认链`** → trigger 变回 `默认链`，**但 JSONL 事件总数仍是 7、`model/changed` 仍只有 seq 6**
     → 会话当前模型**仍是 `glm-5.3-flash`**。
  3. **同屏自相矛盾**：此时同一页面里，composer 说 `默认链`，而右侧 Inspector 的 MODEL 区说
     `模型 glm-5.3-flash`。
  4. **刷新不纠错**：reload 后 picker 仍显示 `默认链`（前端不从会话事件反推 picker，picker 只反映本地 state）。
     → 用户此后每次发送都会**带着 glm-5.3-flash 跑**，而界面从头到尾告诉他"默认链"。
- **根因（前后端契约对齐后判定：前端没按契约调用）**：
  - 后端契约（`session/model_switch.py:97-132`）：`ModelTarget.model_id=None` = 切回默认链，
    **`effective_model_id` 是 picker 应显示的 id**；而进入这条分支的合法入参是
    **`GET /api/models` 里 `is_default=true` 那个条目的名字**（`is_default_selection()` 命中即视为"清覆盖"）。
  - 前端（`components/ModelPicker.tsx:73-79` `commitSelection`）：把 `DEFAULT_VALUE` 映射成
    **`null`** 再回调 → `App.tsx:297-317 handleModelChange` 的 `if (selectedId && name)` 因 `name===null`
    **直接跳过 POST**，只 `setSelectedModel(null)`。
  - `web/src/lib/api.ts:528` 的注释本身就写明"`GET /api/models` 的默认条目（is_default=true）
    也是合法 POST target = 切回默认链"——即**契约要求传默认条目名**，UI 传了 `null`。
  - 注意 picker 里**另有一个** `deepseek-v4-flash-0731 默认` 选项：选它**会** POST 并清覆盖。
    两个看起来都像"用默认"的选项，只有一个真的清覆盖——这正是容易漏掉的原因。
- **修复可行性（已实测，无需后端改动）**：选 `deepseek-v4-flash-0731 默认` →
  新增 `seq 7 model/changed {from=glm-5.3-flash → to=None}`，覆盖被清空、会话回到默认链。
  → 前端最小修复：`DEFAULT_VALUE` 应解析为 `models.find(m => m.is_default)?.name`（有 selectedId 时）
  再走同一条 POST 路径；若该条目缺失则退化为当前行为并给出可见提示。
- **数据收尾**：`fb3619c6` 已被显式切回默认链（seq 7 `to=None`），无遗留脏模型。

#### ART-01 【跨端·P1】`artifact/externalized` 前端未接线 → **Artifacts 页签恒空**，且在有产物的会话里给出**错误结论**

- **现象（真机）**：会话 `a39876d7` 有 2 条 `artifact/externalized` 事件：
  - `artifact_id=87d71b1befad2f76`（`source_tool=web_search`，`size=8578`）
  - `artifact_id=197e88d95cd917b9`（`source_tool=bash`，`size=39600`）
  时间线里也能看到模型调过 `inspect_artifact artifact_id="197e88d95cd917b9…"`。
  但 Run Inspector 的 **Artifacts 页签**显示 `Artifacts0`，面板正文写
  **「本次会话未产生 Artifact。」**；同时 Overview 的 TRACE 区块出现 **`未知事件 2`**（= 这 2 条）。
  → 同一份数据在两处给出互相矛盾的结论，且 Artifacts 页签的那句是**事实错误**。
- **根因（三处对齐后判定）**：
  1. **后端运行时只发 `artifact/externalized`**：`assembly.py:227`
     `ArtifactOverflowHandler(artifact_store, settings.artifact_overflow_chars)` 用默认
     `externalize_event_type=ARTIFACT_EXTERNALIZED`（`tooling/overflow.py:47`）；
     全仓检索**没有任何运行时发射点**发 `artifact/created`（只有 `cli.py` 的展示判断、
     `multiagent/provider.py` 的透传、`session/event.py` 的定义）。
     `tests/tooling/test_overflow.py:46-51,128` 已把 `artifact/externalized` 锁成既定行为。
  2. **规格事件表只列 `artifact/created`**：`03_SESSION_EVENT_MODEL.md` §3 的事件清单里有
     `artifact/created`，**没有** `artifact/externalized`（`grep externalized` 在该 spec 目录下 0 命中）。
     → 这是**规格 ↔ 实现的事件名分歧**，不是前端单方面写错。
  3. **前端按规格接线**：`lib/projection.ts:820` 把 `ARTIFACT_CREATED` 接到
     `projectArtifactCreated`（写 `tool.artifact`），而
     `lib/projection.ts:824` 把 `ARTIFACT_EXTERNALIZED` 登记为 `unhandledProjection`
     （源码注释：「词汇表内但前端尚未接线——显式登记，保持既有兜底行为（进 unknown_events）」）。
     Artifacts 页签的数据源是 `tools.filter(t => t.artifact)`（`StepDetail.tsx:171,762`），
     而 `artifact/externalized` **压根不进这个字段** → 该页签在生产路径上**永不可能有内容**。
- **字段可用性**（说明前端侧修复成本很低）：`artifact/externalized` 的 payload 已带
  `artifact_id / session_id / source_tool / tool_call_id / size / mime_type`，
  与 `projectArtifactCreated` 消费的字段**完全同构**——把 `ARTIFACT_EXTERNALIZED` 指向同一投影即可，
  无需后端改契约。
- **归属与建议**：
  - **前端（最小修复，可自主做）**：`ARTIFACT_EXTERNALIZED` 改为复用 `projectArtifactCreated`
    （或等价地在该投影入口同时接受两种 type）。副作用是「未知事件」计数同时归零，
    TRACE 区块不再有假告警。需补 `projection.test.ts` 用例。
  - **后端 / 规格（只报告，不擅自改，AGENTS.md §8/§9.1）**：事件名分歧要由规格侧定案——
    要么规格事件表补 `artifact/externalized`（并与 `artifact/created` 的关系写清），
    要么后端统一到规格名（但会动已落盘 JSONL 与冻结契约，风险更高）。
    **本轮不动后端、不动 spec**，只登记为待决策项。
- **为什么不是 P0**：主链路（对话 / 工具卡 / 审批 / 委派 / 删除）全部正常，Artifacts 是边缘页签；
  但它在**确实存在产物**时会给出错误结论，所以也不止于 P2。

#### APR-01 【前端·P1】进程重启后遗留的未决审批卡**永久残留**，且点了只会拿到 404（无失效态、无忽略路径）

- **语料**：会话 `d51bdf05-4b80-4652-b2d0-a954e1836305`。事件流里 `tool/approval-requested`
  **2 条**、`permission/resolved` **1 条** → 有 **1 条审批永不配对**（`bash`，`action_type=danger`，
  `approval_id=9ce3a0b31d8f4d70bc3fa1ae6d3f9bfa`），且该会话最后是
  `run/interrupted`（原因 `process_restart`）+ `session/resumed`。
- **真机现象**：
  1. 对话区仍渲染一张 `approval-card pending`（`需要审批`），工具行 `bash danger read-only`，
     命令原文 `$ dir live-deny.txt 2>nul & echo --- & type live-deny.txt 2>nul`，
     按钮 `批准 Ctrl+⏎` / `拒绝 Ctrl+⌫` **可点**；
  2. 上方同时有提示「上次运行在第 2 步中断（原因：process_restart）」——**与卡片的"等你决策"语义互相矛盾**；
  3. 点 `拒绝` → `POST /api/sessions/d51bdf05…/approve` → **404** → 卡面出现
     `审批失败（404）`，卡片回到 `pending`，两个按钮**仍然可点**；再点还是 404。
- **根因（两端对齐，后端无过）**：
  - 后端：`approval_queues` 是**纯内存**的（`session/service.py:934`，
    缺队列 → `ApprovalQueueMissing` → 404；`app.py:1236-1240` 已把
    "approval_id 不存在 → 404（前端过期事件）"写进契约文档），且 run 终结时
    `_attach_approval_queue_gc` 直接 `pop`（`service.py:1233-1241`）。
    **恢复链路（`recovery/`）完全不碰 approval** → 重启后这条审批**永远不可能再被 resolve**。
    后端行为符合已冻结契约，**不是后端 bug**。
  - 前端：`ConversationState.pending_approvals` 由事件投影得出（`requested` 未配对 `resolved`），
    `ApprovalCard` **不看 run 是否已 interrupted**，也不区分 404 与网络失败
    （`ApprovalCard.tsx:58-69` 只把 409 当幂等成功，其余一律"保留 pending + 显示错误 + 允许重试"）。
    → 对一条**已死**的审批，"允许重试"这个策略本身就是错的：重试永远不会成功。
- **为什么算 P1**：`run/interrupted` 是 T8 #138 崩溃恢复**明确支持**的场景，不是异常边角；
  每次进程重启都会在受影响会话里留下**无法消除**的假交互，且文案在骗用户（"需要审批"）。
  对用户的实际伤害：被卡在一个不可能完成的操作上，反复点击只得 404。
- **归属与建议（前端）**：
  1. **主修**：run 处于中断/终态且该 `approval_id` 无后续 `permission/resolved` 时，
     把卡片渲染为**只读失效态**（例如标题改「审批已失效」+ 禁用按钮 + 说明"运行已中断，该决策无法再提交"）。
     判据可以完全来自事件流（`run/interrupted` / `run/completed` / `run/failed` 之后仍 pending 的审批）。
  2. **辅修**：把 404 从"可重试错误"里分出来，文案改为"该审批已失效（运行已中断或服务已重启）"，
     不再暗示重试。仍保留 5xx/网络错误时的可重试行为（OBS-015 的原意）。
  3. 若要"重新发起审批"，那是**新功能**（需要后端在 resume 时重放 approval），不在本票范围。

#### DOC-01 【规格·P2】`03_SESSION_EVENT_MODEL.md` §3 事件表与实现已大面积对不上（与 ART-01 同源）

- **做法**：把 spec §3 事件清单（24 个名字）与前端 `generated/event-types.ts`（37 个，由后端契约生成）
  做集合差。
- **结论**：
  - **spec 有、实现没有（8 个）**：`agent/completed`、`agent/delegated`、`approval/requested`、
    `approval/resolved`、`checkpoint/saved`、`context/built`、`step/completed`、`step/started`。
  - **实现有、spec 没有（21 个）**：`agent/delegation-started`/`-finished`、`artifact/externalized`、
    `compaction/start`/`end`、`memory/degraded`、`message/queued`、`model/changed`、`model/fallback`、
    `permission/resolved`、`queue/cancelled`、`reasoning/started`/`delta`/`completed`/`interrupted`、
    `run/interrupted`、`steer/requested`/`applied`、`text/delta`、`tool/approval-requested`、
    `tool/failure-guard`。
  - 抽查 7 个实现侧名字（`agent/delegation-started`、`reasoning/started`、`text/delta`、
    `tool/approval-requested`、`permission/resolved`、`model/fallback`、`run/interrupted`）
    在整个 `docs/spec/` 目录下 **0 命中** —— 即 spec 里根本没有这些名字的落点。
- **为什么重要**：ART-01 就是这条分歧的**具体受害者**——前端照 spec 的 `artifact/created` 接线，
  运行时却只发未收录的 `artifact/externalized`，于是页签恒空。同理 `approval/requested` 对应的是
  实现里的 `tool/approval-requested`，照 spec 找会找不到。
- **归属**：规格（Primary Developer 维护）+ 后端契约。**本轮只报告，不改 spec、不改后端**
  （AGENTS.md §1.1：代码与规格冲突应报 Gap，不得反向覆盖冻结需求；§8 Scope Lock）。
- **建议**：集成时把 §3 事件表按**实现的实际名字**重写（并标明哪些是持久化、哪些是广播），
  或明确标注该表是"概念速写、非契约"，把契约指向 `generated/event-types.ts` 的来源。
- **已升级为正式流程（2026-09-13，用户批准重写并要求先走 issue/ticket）**：
  母票 **#173**，子票 **#174–#178**（T1 重写实装 37 个 / T2 改名映射 / T3 移出 `checkpoint/saved` /
  T4 三个未实现名定性 / T5 契约源指向 + 漂移守卫）。补充事实：`generated/event-types.ts` 由
  `scripts/gen_event_types.py` 从 `session/event.py` 生成，且有守卫测试
  `tests/test_event_types_generated.py`——**契约源一直存在，只是 spec §3 没被任何检查覆盖**；
  `checkpoint/saved` 更严重：`agent/runtime.py:1165` 与 `storage/checkpoint.py:4` 明令它
  **永不进 SessionEvent**（ADR-0004 Round 5），spec 却把它列在事件表里。
  **状态：已交付（2026-09-13）**。T1–T4 已关单（#174–#177）；T5 由用户 2026-09-13 选定
  **路线 B** 并落地（#178）：spec §3 的事件表**整体移除**，改为「生成物 + 守卫」——
  `docs/EVENT_VOCABULARY.md` 由 `scripts/gen_event_vocabulary.py` 从 `session/event.py` 生成，
  `tests/test_event_vocabulary_generated.py` 与事实源双向比对（缺名 / 多名 / 分节归属错都红）。
  spec §3 从此只留语义、分层与契约源指向链，MUST NOT 再写死事件名或数量。
  订正：上文"重写实装 37 个"按票面原数记录；T1 实测为 **38**（票面两处清单都漏了 `tool/output_delta`）。
  交付落点（`feat/backend`，母票 #173 AC6 要的 commit）：T3 `4a261c2` → T2 `d134c21` →
  T4 `b43f1b1` → T1 `88fbd46` → T5 `60c8d05`；收口记录 `2e3dd16` / `a73dd88`。
  守卫现状（2026-09-14 复跑）：`tests/test_event_vocabulary_generated.py` +
  `tests/test_event_types_generated.py` **6 passed**；生成物头部合计行 = 38 类型
  （36 持久化 + 2 仅广播）。

### 第十一轮 · Subagent 扫描汇总（2 个 subagent，真机点击，2026-09-13）

> 两个 subagent 各自 `new_page` 独占一页（pageId 2 / 3），与我的 pageId 1 隔离；
> 全程真实 CDP 点击 + DOM/网络/console/截图判据。原始报告留在验收现场
> （`docs/.round11_subagent_composer.md`、`docs/.round11_subagent_sidebar.md`，**未提交**，
> 属现场证据不进版本库）；可执行项已全部落进下面的 finding 表与集成提示词。

#### 通过（证据登记，节选；两个 subagent 合计真实点击 46 个控件，0 个"点了没反应"）

- **Composer / 空态 / 记忆面板 15 个控件全部 reacted**：模型 picker（5 项，当前值带 `sel`+Check）、
  权限模式（3 项）、Agent Profile（3 项）、Reasoning Effort（3 项）、Context Providers（多选，勾选态
  `☑/☐` 往返）、发送按钮 gating（纯空格不解禁）、Chat/Split/Preview 三态 `aria-pressed`、
  记忆管理（`GET /api/memories` 200 + 诚实空态「不是加载失败，是真的没有」）、新建会话（空态 + 3 个
  example-chip，**不发 `POST /api/sessions`**）、3 个快速提示 chip（只回填 textarea，**不起 run**）。
- **侧栏 / 项目管理 31/32 项 reacted**：目录浏览器四种情形（200 只列目录 / 404 `目录不存在：` /
  422 `不是目录：` / 403 `无权限访问：`）UI **逐字**显示后端 detail；注册项目（默认标题取 basename）、
  重命名（PATCH 200）、软删除（DELETE 200 + 四条承诺 + 回执 `sessions_detached:0`）全程
  **磁盘零改动**、`GET /api/sessions` 恒 32、未分组恒 24；attach 冲突 409 的 dialog `role=alert`
  逐字显示、浮层不关闭；拖拽机制（`.dragging` / `.rail-drop-tail` "放到最后" / `.rail-drop-indicator`）
  正常且 no-op 落点**不发请求**。

#### 新增 finding（subagent 提出，本 Agent 复核归属）

| ID | 归属 | 级别 | 摘要 | 位置（只读定位） |
| --- | --- | --- | --- | --- |
| **API-01** | **后端** | P2 | `POST /api/projects` 的 422 detail 是**裸 OSError**：`[Errno 20] 不是目录: 'D:\...\readme.txt'`（反斜杠双重转义可见），与 `GET /api/host/dirs` 同场景的策展文案 `不是目录：<path>` 不一致 | `web/domain_errors.py:170-178 workspace_http_error()` 用 `detail=str(exc)` |
| **API-02** | **后端** | P2 | 注册项目填相对路径 → 中文界面里冒出英文 `path must be an absolute path`（Pydantic 校验原文） | 前端 `readErrorDetail()` 已正确解析 detail 数组并剥 `Value error, `，问题在文案本身 |
| **MOD-F1** | 前端 | P2 | 模型/权限/Agent/推理 picker **键盘导航失效**（条目 ≤5 时搜索框 `hidden` → 焦点落在 Radix content，`cmdk-root` 的 `onKeyDown` 收不到事件）；对纯键盘用户是功能不可用 | `components/ModelPicker.tsx:7` 注释宣称"方向键/Enter 由 cmdk 内置"与实测矛盾 |
| **MOD-F2** | 前端 | P2 | 单选 ControlPicker（权限/Agent/推理）选了之后**没有任何回到"未选（默认）"的入口** | `components/ControlPicker.tsx` 只渲染 `entries` |
| **MOD-F4** | 前端 | P2 | Context Providers 的勾选态画在 `aria-hidden="true"` 的 span 上，辅助技术读不到；`role=option` 的 `aria-selected` 只表示 cmdk 高亮 | — |
| **MOD-F5** | 前端 | P2 | Split / Preview **并不真正分栏**，只插一条 `workspace-scaffold` 提示条（UI 自标"未来升级点"） | 若产品本轮就要求副面板，则升级为 P1 |
| **MOD-F6** | 前端 | P2 | `selectedIds` 未与 `entries` 对账 → entries 变化后可能出现"已选但不可见/不可取消"的幽灵项（静态结论，未动态复现） | `ContextProviderPicker.tsx:47-49` |
| **PRJ-F3** | 前端 | P3 | 项目重命名输入**纯空白**时静默丢弃（无请求、无提示、编辑态退出），用户易误以为改名成功 | `ProjectDialogs.tsx:434-436` → `SessionList.tsx:270-276` |

**未覆盖 / 环境限制（须记入，避免被误判为缺陷）**：

- **PRJ-F4【方法限制】**"真·重排后顺序改变并刷新保持"、「移出项目」导致 `sessions_detached>0`、
  项目内会话的写项（上移/下移/移出/删除）**本轮不可达**：唯一创建会话的路径
  `POST /api/sessions` 总是 `create_and_launch()`（`app.py:1013-1046`）→ 造一条自己的会话必须起一次
  LLM run（被本轮硬约束禁止），而 attach 真实会话会改用户可见分组。**这三项仍待验**。
- **PRJ-F5【环境噪声】**`localStorage.ahi.selectedSession` 是**同源单键**：三个页面并发时互相覆盖
  （subagent 页面顶栏/选中行是 `d51bdf05`，读到的键却是别的 id）。单标签用户无感，
  **不能**作为前端缺陷判定；但它也解释了"刷新恢复被别的标签页带偏"的现象。
- **`<后端>\web\` 是旧快照（集成安全警示）**：本工作区 `feat/backend` 的 `web/` 里**没有**
  前端 `57dd028` 的会话硬删对话框（grep `永久删除` 零命中），即 backend 分支的前端树**落后于**
  frontend worktree。集成时**不要用 backend 分支的 `web/` 去覆盖 frontend 的 `web/`**；
  本轮所有前端 finding 均**不在本工作区改**（改了也送不到 frontend worktree，只会再造一份分叉副本，
  见 SID-04）。前端修复另出提示词交付。
- **`workspaces/ws-delete-me/` 不是垃圾**：它是会话 `43e7b46e` 的 `cwd`
  （`session/started.cwd = …\workspaces\ws-delete-me`），来自更早一轮 #172 测试语料；
  它不在 `GET /api/projects` 里是**正确**的（不是项目，只是会话工作目录）。**不要当成遗留目录清掉**。

### 第十一轮 · 修复收口（2026-09-13，本轮 finding 的落地状态）

> 与上面各 finding 的正文配套读：这里是**每条 finding 现在的状态 + commit**（母票 #173 AC6 要求）。
> 前端修复全部在 `D:\intelligence-agent-frontend`（`feat/frontend`）落地——本 worktree 的 `web/`
> 是旧快照（见 SID-04 与文件末尾的"集成安全警示"），在那改送不到前端。spec 修复在 `feat/backend`。

#### P1

| ID | 状态 | commit（分支） | 真机/测试证据 |
| --- | --- | --- | --- |
| **ART-01** | **已修复** | `47b2644`（feat/frontend） | `artifact/externalized` 接线到 Artifacts 页签；真机会话有产物时页签有内容、`unknown_events` 为空；门禁 224 e2e 绿 |
| **MOD-01** | **已修复** | `65c8b7b`（feat/frontend） | 真机 `fb3619c6`：选 `glm-5.3-flash` → JSONL `seq8 {to=glm-5.3-flash}`；再选「默认链」→ `seq9 {from=glm-5.3-flash, to=None}`，覆盖被真的清空（修复前零请求）。新增 `lib/modelSelection.ts`（取默认条目名提交）+ 5 条单测 |
| **APR-01** | **已修复** | `2c5adbd`（feat/frontend） | 真机 `d51bdf05`（JSONL seq11 审批 + seq12 `run/interrupted`）：卡片 `approval-card pending invalid`、标题「审批已失效」、批准/拒绝均 disabled、**零 `/approve` 请求**；并且 composer 解锁（打字后发送键可用）。修复前是永久死局：卡点不动 + 输入框禁用，这个会话再也发不出消息 |

#### P2（后端侧，早于前端批次，`164fbc2` on feat/backend）

| ID | 状态 | 证据 |
| --- | --- | --- |
| **API-01** | 已修复 | `POST /api/projects` 的 422 detail 与 `GET /api/host/dirs` 同款策展文案（新增 `os_error_detail()`）；测试断言两处 detail 逐字一致 |
| **API-02** | 已修复 | 相对路径/空路径/含 NUL 路径全部中文文案（`path 必须是绝对路径` 等）；全量 pytest 2130 passed |
| **SID-03** | 已修复 | `docs/ACCEPTANCE_LANE_ENV.md` §2 期望能力集 2 → 3（补 `memory`），与真机 `/api/capabilities` 对齐 |
| **SID-04** | 已处置 | 登记簿在两侧 worktree 已分叉：集成 AI 在 **main** 侧把第十一轮拆成「（前端侧）/（后端侧）」并加头注；本 worktree 保留**后端侧**副本。后续每轮新章节只在本侧追加，不再假设两侧同名章节同一内容 |

#### P2（前端侧）

| ID（旧 → 本轮编号） | 状态 | commit | 证据 |
| --- | --- | --- | --- |
| **SID-01** → FE-R11-09 窄屏删除入口不可达 | **已修复** | `8e8f0ab` | `≤820px` 不再收起 `.rail-menu-btn`；槽位共享（空闲=会话点、hover/聚焦=⋯，⋯ 绝对定位不挤可点面积）。真机 800px 实测：`focusInCmdkRoot`/`dot` 切换正确、`itemW≥24`；e2e 800px 视口跑完删除确认全流程。**同时发现同一条规则误伤 `.session-item-dot`**（注释声称"只留下点"实际把点也藏了 → 行是空条），已一并修正 |
| **SID-02** → FE-R11-10 危险弹窗初焦 | **已修复** | `8e8f0ab` | 删除确认弹窗初焦从右上「关闭(X)」改为「取消」（回车 = 零请求安全取消）；e2e 断言 `toBeFocused()` + 零 DELETE |
| **MOD-F1** → FE-R11-04 picker 键盘导航 | **已修复** | `59673ef` | 短目录搜索框隐藏时把初焦交给 listbox（cmdk 的 keydown 承接者在 `[cmdk-root]` 内）；**变异验证**：去掉修复该用例报 `focusInCmdkRoot=false` 失败。真机实证：打开后 `activeElement` 已在 root 内、Enter 直接提交高亮项 |
| **MOD-F2** → FE-R11-05 单选无"未选"入口 | **已修复** | `59673ef` | 首项「默认（未选）」提交 `null`；真机实键选回后 trigger 回到 placeholder；e2e 锁住往返 |
| **MOD-F4** → FE-R11-06 勾选态对 AT 不可见 | **已修复** | `59673ef` | cmdk 硬写 `aria-selected`（=高亮），故勾选态改挂 `role="option"` 的 `aria-checked` + listbox `aria-multiselectable`；e2e 断言 true/false 往返 |
| **MOD-F6** → FE-R11-07 幽灵 selectedIds | **已修复** | `59673ef` | `selectedIds ∩ entries` 后再计数与 toggle；单测两条（含全幽灵 → 回 placeholder） |
| **PRJ-F3** → FE-R11-08 空白重命名静默丢弃 | **已修复** | `8e8f0ab` | Enter 遇空白就地拦下：可见提示 + 保留编辑态 + `aria-invalid`/`aria-describedby`；补字后正常提交。e2e 三段锁住 |
| **MOD-F5** → FE-R11-11 Split/Preview 占位 | **未修（待产品决策）** | — | 已开 **#180**：改「未实现」态（disabled + title）还是本轮做真副面板。**没有自行改**——它是产品可见的能力声明，按 §9.1 停下报告 |

#### 本轮新发现（修复过程中冒出来，不是原 finding）

| ID | 归属 | 级别 | 摘要 | 处置 |
| --- | --- | --- | --- | --- |
| **MOD-F7** | 前端 | P2 | `≤820px` 时 `.rail-project-head` 整块收起 → **项目级操作**（重命名项目 / 删除项目 / 新建会话）在窄屏没有任何入口（与 SID-01 同源，但作用在项目层；那一块的注释只说"层级信息丢失是刻意降级"，没提"操作不可达"是副作用） | 已开 **#179** 待决策；本轮**未改**（改法涉及窄屏项目行是否保留一个槽位，属产品取舍） |
| **方法学** | 测试基建 | P2 | `pickControl` 在 Escape 后不等退出动画卸载就再次 open → 选中静默失效（只在连续两次调用时复现） | 已修：helper 末尾等 `[role="listbox"]` 卸载（`59673ef`），并在注释里写明成因 |

#### spec 侧（母票 #173 的 T1–T5）

| 子票 | 状态 | commit | 说明 |
| --- | --- | --- | --- |
| **T3**（#176） | **已交付并关单** | `4a261c2` | `checkpoint/saved` 移出事件表 + 新增 §3.1 存储层分层说明 |
| **T2**（#175） | **已交付并关单** | `d134c21` | 4 个历史名 → 实装名映射表（§3.2）+ 表内行内注记；脚本核对无"裸契约行" |
| **T4**（#177） | **已交付并关单** | `b43f1b1` | `step/started`/`step/completed`/`context/built` → §3.3「设计草案，勿按此实现」 |
| **T1**（#174） | **已交付并关单** | `88fbd46` | §3 按实装重写：**38** 个类型（36 持久化 + 2 仅广播），脚本比对与 `event.py` 集合相等 |
| **T5**（#178） | **未交付（待决策）** | — | 票面自己写明"两条路线需 Primary Developer 选一条，本票不得自行决定"：① spec §3 表允许被机器解析（加守卫测试）② 权威副本生成到代码侧、spec 只引用。**已按票面停下**，等选定后一条 commit 可完成 |

**两处数量订正（按代码为准，已在 #174 评论区说明）**：实装类型是 **38** 不是 37（母票两处清单都漏了
`tool/output_delta`）；母票 AC1 把 `text/delta`、`reasoning/delta`、`tool/output_delta` 举例为"仅广播"，
与 `STREAM_ONLY_TYPES` 和 ADR-0016 §3.1 相反——它们都是**持久化**的合帧 chunk。

---

## 第十二轮（后端侧）（2026-09-13）：面板 T4（#185 artifact 只读接口）期间的观察

### OBS-11.1 【后端·全量门禁间歇性·非本票引入·未复现】偶发 22 个 web 用例失败

**现象（2026-09-13）**：`feat/backend` 上**同一份代码**（#185 完成态）连跑 5 次全量 `pytest -q`：

| 轮次 | 结果 | 用时 |
| --- | --- | --- |
| 1 | 2152 passed / 0 failed | 317.97s |
| 2 | **22 failed / 2130 passed** | 326.44s |
| 3 | 2152 passed / 0 failed | 199.58s |
| 4 | 2152 passed / 0 failed | 218.05s |
| 5 | 2152 passed / 0 failed | 289.78s |

失败样本（当轮 tail 里还看得见的两条）：`tests/web/test_web_stream.py::test_replay_backlog_threshold_emits_control_frame`、
`tests/web/test_web_ws_relay.py::test_ws_multisession_real_snapshots`——都集中在 `tests/web`，
且都是**真 ASGI / 真 WebSocket 传输**类用例。

**已做的排查**：
1. 失败那轮的完整输出**没有留存**（只 tail 到 3 行），所以**拿不到 traceback**——这是流程缺陷：
   本轮之后的全量门禁统一先落 `/tmp/*.log` 再 tail（后 4 次即如此办理）。
2. 把两个已知失败文件**单独连跑 3 轮**：10 passed / 12-14s，**全绿** → 不是确定性失败。
3. 排除"与前端 e2e 抢 CPU"：失败轮次当时没有并行前端任务。

**判断：非本票引入**。#185 的 diff 只碰 artifact 读路径（`web/artifacts.py`、`storage/*artifact*.py`、
`web/app.py` 一条新路由），不触达失败用例的代码路径；且同一份代码多数轮次不可复现。

**未定位的假设（留给下次复现时验证，别当成已排除）**：
- Windows 上大量 `TestClient` / 真 WS 连接的**临时端口 / TIME_WAIT 压力**（失败集中在传输类用例）；
- 某个共享外部依赖（Milvus / Langfuse / 模型网关）在那一轮瞬时不可用造成**级联失败**；
- 失败是否集中在整轮跑的**尾部**（若如此，指向资源累积而不是随机）。

**归属：后端（测试稳定性）**。本轮**不修**（§8 Scope Lock）。下次复现时按上面三条假设取证，
**不要**用"重跑一次过了"结案。
