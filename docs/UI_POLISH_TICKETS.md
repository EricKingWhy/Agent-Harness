# UI Polish Tickets — 逐 Ticket 施工规格

> 配套 `docs/UI_POLISH_PRD.md`（决策与通用要求）+ 根目录 `DESIGN.md`（视觉基准）。
> 本文每条规格都是**规范性**的：与代码现状冲突时，以本文为目标状态；本文没写的，按 DESIGN.md；再没写的，登记 `docs/FRONTEND_ISSUES_LOG.md` 并停下询问，不许猜。
> 每个 ticket 的完成定义 = PRD §4 全部通用要求（SDD 循环 / 门禁 / 变异验证 / §15 同步 / selector 稳定 / 本地 commit / tracker 更新）。

---

## UI-01（P0）审批卡重塑——「决断时刻」配得上它的后果

### 背景（证据）
- `web/src/components/ApprovalCard.tsx:51` 根节点 `className={`approval-card glass ${decision}`}` —— 内联内容面挂玻璃材质，违反 DESIGN.md **Glass Only Floating Rule**（R4）。
- `web/src/styles/app.css:2360-2368` `.approval-card` 带 `box-shadow: 0 0 20px …` 第三级辉光（两级阴影体系之外）。
- 参数呈现：`<pre className="approval-args">` 直出 `JSON.stringify(arguments_preview)` —— 字符串内换行显示为字面 `\n`，`content` 里的 `rsync -av dist/ server:/srv/app` 这类风险点埋在转义串中段（违反 R7）。
- 后端下发且与 `session/approval.py` 同形状的 `description`/`reason` 字段**前端未渲染**（DOM 实测 `description_field_rendered: false`）。
- 无 `role` / 无焦点管理 / 无键盘路径；审批 pending 期间 Composer 照常可输入提交（`Composer.tsx` 只看 `streaming`）。
- 快捷键文案硬编码 `⌘`（Composer placeholder），本仓库无平台检测工具（grep 无 isMac/userAgent 工具函数）。

### In / Out
- **In**：ApprovalCard 结构与样式、DiffBlock 抽取复用、焦点/aria/键盘、Composer pending 置灰、`lib/platform.ts` 新增。
- **Out**：审批倒计时（D4 缓做，先在 `docs/FRONTEND_ISSUES_LOG.md` 登记核实任务：查后端 `PendingApprovalQueue` 是否在事件/响应中携带超时时间戳或剩余秒数）；后端契约任何改动；`allowed_decisions` 语义（仍只有 deny/approve_once 两键）。

### 规格（目标状态）

**A. 数据与组件结构** —— `ApprovalCard.tsx` 重写渲染（props 不变，仍是 `{ sessionId, approval }`）：

1. 根节点：`className={`approval-card ${decision}`}` —— **删除 `glass`**；加 `role="alertdialog"`、`aria-modal="false"`、`aria-labelledby="approval-title-{approval_id}"`、`aria-describedby="approval-desc-{approval_id}"`、`tabIndex={-1}`、`ref`。
2. 挂载焦点：`useEffect` 首次挂载时 `ref.current?.focus()`；**多卡并存时只有第一张**（`Conversation.tsx:348` 的 `map` index===0）自动聚焦——给 ApprovalCard 加 prop `autoFocus?: boolean`，Conversation 传 `i === 0`。
3. 渲染顺序（自上而下）：
   - `.approval-header`：ShieldAlert(16) + `<span className="approval-title" id="approval-title-…">`（保留 class 与 id 新增）——内容仍是 `approval.title`。
   - **新增** `<p className="approval-desc" id="approval-desc-…">`：渲染 `approval.description ?? approval.reason ?? ''`（两者都有用 description）；为空则不渲染该元素（aria-describedby 指向存在的元素——描述为空时 aria-describedby 省略）。
   - `.approval-tool`：`tool_name` + 权限上下文 chips（`permission` / `policy` 存在时渲染成 `.approval-chip` 小徽章，12px，warning 淡染）。工具名文字色改 `var(--text-primary)` + mono（R1，配合 UI-02，但本 ticket 先把类内颜色改为 token 引用，避免 UI-02 重复劳动）。
   - **新增** `.approval-path`（仅当 `arguments_preview` 含路径语义键时）：mono 13px + `CopyButton`（复用 `components/CopyButton.tsx`）。路径键按优先级匹配：`path` → `file_path` → `file`。
   - **新增** `.approval-preview`：结构化参数区，替换原 `<pre class="approval-args">`。按键分类：
     - `command` → `.approval-cmd`：终端块样式（`--terminal-bg/fg`），`$ ` 前缀，**原始字符串**（不 JSON 转义）。
     - `old` + `new` 同时存在 → 渲染 `<DiffBlock diff={{ old, new }} />`（见 B）。
     - `content` → `.approval-content`：`<pre>` 显示**原始字符串**（真实换行），终端块样式。
     - 其余键 → 保留一个兜底 `<pre className="approval-args">`：`JSON.stringify(remainingArgs, null, 2)`（2 空格缩进；键名+值分行，仍是转义但结构可读）。全部键都被结构化消费时该兜底不渲染。
     - **class 名保留政策**：`.approval-title` / `.approval-tool` / `.approval-args` / `.approval-actions` / `.approval-error` / `.approval-approve` / `.approval-deny` 全部原样保留（e2e `n-approval-card.spec.ts` 依赖），只新增 `.approval-desc/.approval-path/.approval-preview/.approval-cmd/.approval-content/.approval-chip`。
   - `.approval-error`（role="alert"）——逻辑不动（OBS-015 回归锁）。
   - `.approval-actions`：两键保留；**每键内追加 `<kbd className="approval-kbd">`** 显示平台快捷键（批准 `⌘/Ctrl + ⏎`、拒绝 `⌘/Ctrl + ⌫`；文案用 platform.ts 的 `modKey()`）。
4. 键盘快捷键：组件内 `useEffect` 挂 `document` 级 `keydown`（仅 `decision==='pending' && !busy` 时激活；条件变化即重挂）：
   - `(e.ctrlKey||e.metaKey) && e.key==='Enter'` → `decide(true)`，`preventDefault()`。
   - `(e.ctrlKey||e.metaKey) && e.key==='Backspace'` → `decide(false)`，`preventDefault()`。
   - 忽略 `e.repeat`。卸载/决后移除监听。**不得**占用 Esc（Esc 是全局中断运行，语义冲突，明确不做）。
5. `Busy` 期间按钮 `disabled` 现状保留。

**B. DiffBlock 抽取**：
- 把 `ToolCard.tsx:367` 的内部函数 `DiffBlock`（含其样式类 `tool-diff-*`，若样式在 app.css 则类名不动）原样搬到新文件 `web/src/components/DiffBlock.tsx` 并 `export function DiffBlock(...)`；`ToolCard.tsx` 改为 import。**搬运不改逻辑不改样式**（纯移动，diff 可追溯）。`ApprovalCard` 的 old/new 分支调用它。
- 若 DiffBlock 的 props 形状与 `{old,new}` 不完全一致（以 `ToolCall['diff']` 类型为准），在 ApprovalCard 侧做键名适配，**不修改 DiffBlock 本身**。

**C. Composer pending 置灰**：
- `App.tsx` 在 `<Composer>` 渲染处（约 `:765`）新增 prop `approvalPending={(conversation?.pending_approvals.length ?? 0) > 0}`。数据来自同一 projection 状态（`conversation`，App.tsx:74 useSession 返回），**不建第二状态源**。
- `Composer.tsx`：新增 prop `approvalPending?: boolean`（默认 false）；`const locked = streaming || approvalPending`；textarea、发送按钮（`:172`）、控件行四个 picker（`:109-154` 现有 `disabled={streaming}` 处）全部改 `disabled={locked}`。
- pending 时 placeholder 换为 `运行被阻塞：等待审批决策…`；`!locked` 时保持原文案（`描述一个任务…（${modKey()}+Enter 发送）`——顺带完成本文件的平台键位整改，R6）。
- 置灰不是隐形：composer 外观保持可见（disabled 态样式已有），并加 `.composer-locked-hint`（12px，warning 淡染，位于 dock 顶部内沿）文案 `等待审批决策后再继续`。

**D. `web/src/lib/platform.ts`（新增）**：
```ts
/** 平台检测（快捷键文案用）。测试经注入 userAgent 覆写。 */
export function isApplePlatform(ua: string = navigator.userAgent): boolean {
  return /Mac|iP(hone|ad|od)/.test(ua);
}
/** 修饰键文案：macOS ⌘，其余 Ctrl。 */
export function modKey(ua?: string): string {
  return isApplePlatform(ua) ? '⌘' : 'Ctrl';
}
```
配 `platform.test.ts`（Mac / Windows / iPhone 三例，注入 ua 字符串——因此签名必须接受 ua 参数）。

**E. 样式**（`app.css` 审批卡区块 `:2355-2456` 一带）：
- `.approval-card`：删除 `box-shadow: 0 0 20px …` 辉光行；`padding` 改 `var(--space-lg) var(--space-lg2)`（16/20，安全决策面加大呼吸）；其余（warning hairline + 3px 实条 + 7% 淡染）保留（R5a 合法形态）。终态 `.approval-card.approved/.denied` 的收敛样式保留，同样删除任何辉光残留。
- 新增 `.approval-desc`（12px，`--text-secondary`，margin-top 4px）、`.approval-path`（mono 13px 行 + CopyButton，elevated 底条）、`.approval-preview`（column gap 8px）、`.approval-cmd/.approval-content`（终端块，复用 `.bash-block` 类的视觉变量而非类本身）、`.approval-chip`、`.approval-kbd`（10px mono，淡染底——**这是 10px 合法形态吗？不是**：kbd 是可读文本 → 11px？**规范性决定：kbd 用 `var(--text-xs)` 即 12px**，砍掉歧义）、`.composer-locked-hint`。
- 所有新增颜色一律 token 引用；新增/改动 token 检查亮色块（本 ticket 预计**不需要**新 token）。

### 验收标准（AC）
- [ ] 审批卡 DOM 无 `glass` 类、无第三级辉光；`role="alertdialog"` + labelledby/describedby 正确指向。
- [ ] 单卡挂载后 `document.activeElement` 是卡片根；两卡并存只有第一张聚焦。
- [ ] `description` 文本可见；无路径键时不渲染 `.approval-path`。
- [ ] `{path,content}` 预览：path 行 + content 块，且 content 块内是**真实换行**（断言 textContent 含 `\n` 换行而非字面 `\\n`）。
- [ ] `{old,new}` 预览渲染 DiffBlock；`{command}` 渲染命令块。
- [ ] `Ctrl+Enter` 触发 POST `/approve` 且 body `decision:'approve_once'`；`Ctrl+Backspace` 触发 `decision:'deny'`；决后快捷键失效。
- [ ] 审批 pending 期间：composer textarea/send/pickers disabled + 锁定提示可见；决策完成后恢复可用。
- [ ] 既有 class 名（§A.3 保留政策清单）全部未变。
- [ ] Windows 下 kbd 显示 `Ctrl`、macOS 下显示 `⌘`（unit 覆盖）。

### 测试计划
- **新增 unit** `ApprovalCard.test.tsx`（vitest，node 环境——注意现仓 unit 无 jsdom，聚焦逻辑与 renderToStaticMarkup 级断言或抽取纯函数测；若渲染断言受环境限制，把「路径键匹配」「参数分类」抽成纯函数 `classifyPreviewArgs()` 放 `lib/toolShapes.ts` 旁并直接单测，组件级行为交给 e2e）：classify 各键分支、platform kbd 文案。
- **扩展 e2e** `n-approval-card.spec.ts`：新增用例——① description 可见 + path 结构化（textContent 断言）；② `Ctrl+Enter` 批准（请求体断言）+ 决后按钮消失；③ pending 期间 `textarea` disabled + 决后 enabled；④ 焦点落卡（`toBeFocused()`）。既有 4 条用例**必须原样通过**（class 保留政策的证明）。
- **变异验证**（至少）：键盘快捷键断言（删掉 keydown effect → 红）；composer disabled 断言（去掉 locked → 红）。记录进 tracker。
- platform.test.ts 三例。

### 涉及文件
`components/ApprovalCard.tsx`、`components/DiffBlock.tsx`(新)、`components/ToolCard.tsx`、`components/Composer.tsx`、`App.tsx`、`lib/platform.ts`(新)+test、`lib/toolShapes.ts`(若抽纯函数)+test、`styles/app.css`、`e2e/n-approval-card.spec.ts`、`Conversation.tsx`(传 autoFocus)。

---

## UI-02（P1）排版地板 + 对比度——把「微字号雾」换成有节奏的层级

### 背景（证据）
- `index.css:32` `--text-xs: 11px`；`app.css` 内 `font-size: 10px` ×30 处、`var(--text-xs)` ×98 处、`--text-base`(14px) 仅 4 处（≈75% 落在 10–11px）。
- DOM 实测对比度：`--text-tertiary` 暗 3.96–4.09 / 亮 2.65–2.76（AA 4.5 未达）；亮色 accent 11px（`.tl-type`）3.15；亮色 `.approval-tool code` 3.04；placeholder 亮 2.76。
- accent 性质混用：Inspector 整列事件名粉色 mono（非交互语法高亮），违反新成文 R1。

### In / Out
- **In**：`index.css` token 三处（D3）、app.css 的 10px 分类整改、非交互 accent 文字整改、对比度/字号回归 e2e。
- **Out**：type scale 档位数量不变（12/13/14/15/20）；不改行高；不动交互态 accent（hover/selected/focus/主按钮）；不动 R5 两类 side-tab。

### 规格

**A. token 改动**（`index.css`，含 §15 双块同步）：
1. `:root` `--text-xs: 11px` → **`12px`**（亮色块无字号 token，无需同步字号）。
2. `:root` `--text-tertiary: rgba(255,255,255,0.42)` → **`rgba(255,255,255,0.52)`**。
3. `:root[data-theme='light']` `--text-tertiary: rgba(18,18,24,0.42)` → **`rgba(18,18,24,0.63)`**（实施修正：规格原估 0.55，实测白底 4.12:1 / 染底 4.46:1 均不达 AA，0.63 才过线——估算让位实测）。
4. 改完在两块注释里补一行「UI-02 2026-09-12：地板 12px / tertiary 提对比（PRD D3）」。

**B. 10px 清理**（`app.css` 全量 `font-size: 10px` 逐处分类，结果表追加到 tracker）：
- 判据：该元素 `text-transform: uppercase`（或内容恒为大写字面量）**且**带 `letter-spacing ≥ 0.05em` → 保留 10px（micro-label 合法形态）；否则 → 改 `font-size: var(--text-xs)`。
- 已知必改例：`.slice-line-chip`（app.css:2350-2356，10px 无大写）、`.tl-seq`/`.tl-summary` 类 11px 引用自动随 token 升到 12px（无需逐处改）。
- 允许**逐点豁免**：密集布局确实撑不住时，可留 11px 并加注释 `/* UI-02 豁免: <原因> */`；豁免总数与理由记 tracker，**预期 ≤5 处**，超过说明分类有问题。
- 改后跑 6 档宽度 spec（`g-visual-qa`）+ 密度 spec（`h-density`）确认无溢出。

**C. accent 去墙纸化**（R1 首批整改对象）：
1. `.tl-type`（Inspector 事件类型名）：`color` 从 accent 系改 **`var(--text-secondary)`**（mono 字体、tabular-nums 保留）。行内状态字（`ok`/`失败` 等由 `.tl-status-*` 类承担，若现状混在同一元素，拆出状态 span 用语义色）。
2. `.approval-tool code`：改 `var(--text-primary)`（UI-01 若已完成则已带此改动，本条跳过并在 tracker 标注「已由 UI-01 覆盖」）。
3. 全量审计 `grep -n "var(--accent)" web/src/styles/app.css`：逐条标注「交互/状态（保留）/非交互（整改）」，整改非交互项；清单入 tracker。已知保留例：focus ring、`::selection`、fork 按钮、`.timeline-earlier`（可点）、Run Pulse 思考相、会话选中染底。

**D. 回归锁**：新增 `web/e2e/t-contrast.spec.ts`：
- 两个主题（localStorage `ahi.theme` 注入，参考 `g-visual-qa` 的浅色用例写法）各断言：
  1. `.session-item-meta`：computed `font-size === '12px'` 且对比度 ≥4.5。
  2. `.tl-seq`：同上。
  3. composer `textarea` 的 `::placeholder` 色：对比度 ≥4.5。
  4. `.tl-type` 的 color **不等于** accent 计算值（断言 `!== getComputedStyle(document.documentElement).getPropertyValue` 解析后的 accent rgb；更稳：断言等于 text-secondary 的解析值）。
- 对比度计算函数写进 spec 内（相对亮度公式，背景色逐层合成——参考 `web/audit-dom-evidence.mjs` 的现成实现，**该脚本用完即删**）。
- 用丰富会话 fixture（复用 `n-approval-card` 的 HEAD 帧风格自造三帧即可，不依赖 audit 脚本）。

### 验收标准（AC）
- [ ] token 三处按 D3 落地，亮色块同步，注释更新。
- [ ] app.css 无裸 `font-size: 10px`（除 uppercase micro-label 与已登记豁免）。
- [ ] DOM 实测：session-item-meta / tl-seq / placeholder 两主题对比度全部 ≥4.5:1（e2e 断言证明）。
- [ ] `.tl-type` 非粉色（等于 text-secondary）。
- [ ] g-visual-qa 6 档 + h-density 全绿；无新增横向溢出。
- [ ] audit 脚本中对应测量值被正式 spec 固化后，tracker 记录「固化完成」。

### 测试计划
- `t-contrast.spec.ts`（新，≥8 断言：4 项 × 2 主题）。
- 变异验证：把 `--text-tertiary` 暂时改回 0.42 → 对比度断言红 → 还原绿（记录）；把 `.tl-type` 色暂时改回 accent → 断言红 → 还原。
- 既有全部门禁（10px 改动面广，重点盯 `h-density`、`picker-search-visibility`、`control-row`）。

### 涉及文件
`src/index.css`、`src/styles/app.css`、`e2e/t-contrast.spec.ts`(新)。两个 audit 脚本按 PRD §8.5 在**全部 ticket 完成后**统一删除（非本票内）。

---

## UI-03（P1）Inspector 时间线——run 分组 + 过滤 chip 化 + 头标对齐

### 背景（证据）
- 时间线平铺全会话事件跨多个 run（02/04 截图：19 行含 2 次 run/started，无分隔）；`.detail-run-id` 徽章显示 `run-2`（最新 run id）而列表是全会话——状态与内容不对应。
- 过滤行 5 个裸 icon（`.detail-tabs` 同排的 kind filter 按钮）无标签无计数，违反启发式 6（识别而非回忆）。

### In / Out
- **In**：Run 级时间线的分组头、过滤按钮 chip 化（icon+计数）、`detail-header` 徽章语义修正。
- **Out**：事件级详情视图（StepDetail 的 focus 细分视图）结构；L0-L2 disclosure 机制；Main↔Inspector 联动 pulse。

### 规格
1. **Run 分组头**：Run 级视图（`StepDetail.tsx:158` 起 `run` 分支的时间线列表）按 `run_id` 的**首次出现顺序**分组；组间插入 `.tl-run-header` 行：
   - 内容：`Run {序数}`（序数 = 该 run 在会话中的次序，从 1）+ 状态徽章（由该 run 的终态事件推导：`run/completed→已完成`、`run/failed→失败`、`run/interrupted→已中断`、无终态且是最新 run→`进行中`）+ `{n} 事件`；`title` 属性放完整 run_id。
   - 样式：上下 `var(--space-md)` 留白 + 顶部 1px dashed `--border-strong` 分隔线 + 12px `--text-secondary` 文字 + 状态徽章复用语义色淡染药丸（与 `.run-badge` 同语言）。单 run 会话**同样渲染分组头**（结构一致，无特判）。
2. **过滤 chip**：kind filter 按钮改为 `.tl-filter-chip`：icon(13) + 计数徽章（`.tl-filter-count`，tabular-nums，该 kind 在当前会话的行数，0 时 chip 显示但 disabled）。`aria-label` 保留原语义并追加计数（如 `工具调用过滤（3 行）`）；`aria-pressed` 语义保留。
3. **头标对齐**：`.detail-run-id`（`StepDetail.tsx:166`）文本从 `conversation.run_id` 改为 **`{runGroupCount} runs · {conversation.events.length} 事件`**（num 类保留）；完整 run_id 已在各分组头 `title` 与事件级详情中可见，不再在头标展示单个 run id。`detail-header` 的「已完成」徽章保留（会话级 run 状态）。
4. 时长/时间显示复用 `format.ts` 现有工具，新增格式化进 UI-04 一并处理（本 ticket 不动 format.ts）。

### 验收标准（AC）
- [ ] 双 run fixture 下：2 个分组头按序渲染，各自事件数正确（15+4=19 行覆盖两 run 的 fixture 需自造，参考 audit-screenshots 的 RICH_EVENTS 形状）。
- [ ] 分组头状态徽章与该 run 终态一致；无终态最新 run 显示「进行中」。
- [ ] 过滤 chip 显示计数；点击过滤行为与改前一致（不改过滤逻辑）。
- [ ] 头标显示 `2 runs · 19 事件`，不再显示裸 run_id。
- [ ] 单 run 会话回归：一个分组头，布局不破。

### 测试计划
- `StepDetail.test.tsx` 扩展：分组头渲染/计数/状态映射（completed/failed/interrupted/进行中 四例）；头标文案。
- e2e：`g-visual-qa.spec.ts` 追加一条断言（1440px 暗色、双 run fixture、分组头可见且计数正确）。
- 变异验证：分组头计数断言（故意聚合错误 → 红 → 还原）。

### 涉及文件
`components/StepDetail.tsx`、`styles/app.css`、`components/StepDetail.test.tsx`、`e2e/g-visual-qa.spec.ts`。

---

## UI-04（P2）信任裂缝——摘要与时长不再撒谎

### 背景（证据）
- `projection.ts:184` `unknownSummary` 直出 `JSON.stringify(event.data).slice(0, 40)`（截图 05：`未知事件:{"a…`）。
- `projection.ts:784-786` `SESSION_FORKED` 挂 `unknownSummary`，注释自述「待确认后再定它的单行语义」——本 ticket 就是那个确认（用户已批 D1/D6）。
- `format.ts:4` `formatDuration` 与思考块时长：`<50ms` 显示 `1ms` 类假精度；reasoning 终态 `持续了 0 秒`。

### 规格
1. `unknownSummary` 改为返回 **`未接线的类型（payload 已保留，点行看详情）`**——不含 JSON、不含 type（行标签已是 type，不重复）。
2. `SESSION_FORKED` 的 summarize 注册为专函数：`已分叉`（+ 若 `data.child_session_id` 存在追加 ` → {id.slice(0,12)}…`？**不做截断 id**（R7/半截 ID 教训）：就 `已分叉` 两个字，详情看 L2）。同步删除 `:785-786` 的「待确认」注释，替换为 `// session/forked：单行语义 = 已分叉（UI-04 定案）。`
3. `tool/approval-requested` 的 summarize 若当前落 unknown（截图证据如此），注册为 `等待审批 · {tool_name}`（`data.tool_name` 存在时）；不存在时 `等待审批`。
4. `format.ts` 新增 `formatShortDuration(ms: number): string`：`ms < 50 → '<50ms'`；`< 1000 → '{n}ms'`；否则秒（1 位小数截断，`12.3s`）。`formatDuration` 与 act-duration 调用点改用它（保持 `null` 语义不变）。
5. Reasoning 时长：找到渲染「持续了 N 秒」的位置（`ReasoningBlock.tsx` 或 Conversation 摘要行），`N===0` 时改显 `持续 <1s`，其余不变。
6. 未知模型的自动纠正静默问题（评审启发式 9 扣分点）**本 ticket 不做**，登记 issues log（涉及流式协议语义，超出视觉批次）。

### 验收标准（AC）
- [ ] 未知事件行摘要无 `{`/`"` 字符。
- [ ] forked 事件摘要为「已分叉」；approval-requested 摘要为「等待审批 · {tool}」。
- [ ] mock 帧（seq 间隔 <50ms）时长显示 `<50ms`；0 秒思考显示 `<1s`。
- [ ] `projection.perf.test.ts` 不因摘要改动劣化（门禁自然覆盖）。

### 测试计划
- `projection.test.ts`：forked/approval-requested/未知事件三例摘要断言（注意 `:120` 既有 UnknownSurface 测试的兼容——它断言的是 unknown_events 记录行为，不受摘要文案影响，跑一遍确认）。
- `format.test.ts`：formatShortDuration 三档边界（49/50/999/1000）。
- 变异验证：forked 断言（改回 unknownSummary → 红 → 还原）。

### 涉及文件
`lib/projection.ts`、`lib/format.ts`+test、`lib/projection.test.ts`、`components/ReasoningBlock.tsx` 或摘要所在组件、（如需要）`components/Conversation.tsx`。

---

## UI-05（P2）Rail 空态指路——别把新手指向不存在的按钮

### 背景（证据）
- `SessionList.tsx:377-382`：空态文案「用右上角的『新建项目』…」指向两个 icon-only 按钮（FolderPlus/Plus），全 Rail 无文字标签——文案指涉的文字实体不存在。

### 规格
1. Rail 头部按钮簇（约 `SessionList.tsx` 顶部「会话」标题右侧）：**当 `projects.length === 0 && model.ungrouped.length === 0`（真·空态）时**，两个 icon 按钮切换为文字按钮：
   - 「新建项目」：实心小按钮（accent 淡染底 + primary 文字 + 12px + 6px + 高 28px），onClick = 原 FolderPlus 处理器。
   - 「新会话」：描边小按钮，onClick = 原 Plus 处理器。
   - 非空态维持 icon 按钮现状（aria-label 不动）。
2. 空态文案改为：`还没有项目。注册一个已存在的目录，同目录的会话就会归到一起。` + 同段内嵌行动链接 `.rail-empty-action`「注册项目目录 →」（button 语义，样式为 accent 文字下划线 hover 加深），点击打开 CreateProjectDialog（与「新建项目」同 handler）。
3. `projectsError` 存在时维持现有错误条 + 不显示空态文案（现状逻辑保留）。

### 验收标准（AC）
- [ ] 空会话+空项目首屏：两个文字按钮可见、链接可见；点击「新建项目」/链接都能打开项目对话框。
- [ ] 有项目或有会话时：按钮回到 icon 形态，文案不出现。
- [ ] 既有 r-project-groups e2e 全绿（若其 mock 了空态场景需按新 DOM 更新断言——同一 ticket 内完成）。

### 测试计划
- 新增 `SessionList.test.tsx`（若渲染断言受 node 环境限制则只测「空态判定函数」+ 交给 e2e）：`isEmptyRail(model, projects)` 抽纯函数单测。
- e2e `r-project-groups.spec.ts` 追加：空态 → `getByText('新建项目')` 可见 + 点击打开对话框（对话框打开断言复用该 spec 现有方式）。
- 变异验证：空态按钮文字断言。

### 涉及文件
`components/SessionList.tsx`、`styles/app.css`、（新）`components/SessionList.test.tsx` 或纯函数 + test、`e2e/r-project-groups.spec.ts`。

---

## UI-06（P3）minor 打磨批——平台键位 / CJK 间距 / 徽章收敛

### 背景
评审 Minor ①-⑥ 中未被前五个 ticket 消化的项。依赖 UI-01 的 `lib/platform.ts`。

### 规格
1. **Composer placeholder 平台键位**：若 UI-01 已顺带完成（规格 C），本条跳过并标注。
2. **CJK 间距**：`CommandPalette` 内「切换到Raw」→「切换到 Raw」；同文件排查其余中英文混排 label，统一「中文与英文/数字间加半角空格」。密度档 `Raw` 名称保留（产品术语）。
3. **palette hint 语义**（低风险子集）：「→ 亮色」去掉方向箭头改「亮色」；`当前` 状态 chip 保留；其余 hint 不动（完整分组化 defer，登记 issues log）。
4. **徽章收敛**：`detail-header` 的 run 状态徽章与顶栏 Run Pulse 是两种组件——统一**视觉参数**（padding/radius/字号/字重，向 `.run-pulse` 的 3px 10px 内边距药丸看齐），保留各自颜色语义。改 `.run-badge`（或实际类名，实现时 grep 定位）数值即可，不动 DOM。
5. 评审 Minor ⑤（Split/Preview 空架子）与 ⑥（半截 ID）**明确不做**（前者是诚实设计，后者涉及信息架构取舍，登记 issues log 留待产品决策）。

### 验收标准（AC）
- [ ] palette 无「中文直接贴英文」的 label（排查清单入 tracker）。
- [ ] 「亮色」hint 无箭头。
- [ ] run 状态徽章与 Run Pulse 的 padding/radius/字号 computed 值一致。
- [ ] macOS 模拟下 Composer placeholder 显示 `⌘+Enter`，Windows 显示 `Ctrl+Enter`。

### 测试计划
- `commands.test.ts` 扩展：label 文案断言（改到的命令）。
- `platform.test.ts` 已覆盖键位文案。
- 变异验证：改到的 label 断言至少一处。

### 涉及文件
`components/CommandPalette.tsx`、`lib/commands.ts`（若 label 在此）+test、`styles/app.css`（run badge）、`components/Composer.tsx`（若 UI-01 未覆盖）。

---

## 附：e2e selector 依赖总账（改 Class 名前必查）

| class / 属性 | 依赖方 | 状态 |
|---|---|---|
| `.approval-title/.approval-actions/.approval-error/.approval-approve/.approval-deny/.approval-tool/.approval-args` | n-approval-card.spec.ts | UI-01 **保留** |
| `.composer-control/.composer-dock/.composer-controls` | g-visual-qa / control-row 等 | 全批次保留 |
| `.session-item/.turn/.conversation-scroll/.follow-pill` | j-scroll / f-history 等 | 全批次保留 |
| `.detail-tab/.detail-tabs` | StepDetail 相关 | UI-03 保留 |
| `.tl-*`（时间线行族） | UI-03 新增断言 | UI-03 中新增 `.tl-run-header/.tl-filter-chip/.tl-filter-count` |
