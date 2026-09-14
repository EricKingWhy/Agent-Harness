# UI Polish PRD — Agent Harness Inspector 设计优化批次（2026-09-12）

> **文档性质**：本 PRD 是 `feat/frontend` worktree 上一批 UI 设计优化工作的**唯一需求事实源**。后续任何 AI（或人）接手时，先读本文档，再读 `docs/UI_POLISH_TICKETS.md`（逐 ticket 施工规格），再读根目录 `DESIGN.md`（视觉规范基准）。
> **状态语义**：ticket 状态只以 `docs/SDD_TICKET_TRACKER.md` 的最新记录为准；本文档描述的是「应该做什么」，不追踪「做到哪了」。
> **评审出处**：impeccable critique 双评估（2026-09-12），快照 `.impeccable/critique/2026-09-12T14-05-30Z__web-src.md`，Nielsen 总分 **24/40**（Acceptable）。截图证据 `web/test-results/ui-audit/`（8 张，mock 数据真实渲染，暗/亮双主题，临时产物不入库）。

---

## 0. 决策记录（用户 2026-09-12 grill-me 拍板，不可违约）

| # | 决策 | 内容 |
|---|------|------|
| D1 | 范围 | 五个评审 issue **全部做**，按 P0 → P1 排版 → P1 Inspector → P2 → P2 分批 SDD 循环；每批独立 code-review + 全量门禁 + 本地 commit |
| D2 | 基调 | **Refinement**：冻结视觉世界不换（粉色 accent、暗色优先、材质模型、radius 阶梯全部不动）；同时把「accent 使用性质」补成成文规则（进 DESIGN.md，见 §2） |
| D3 | 排版 | `--text-xs` 11→12px；`--text-tertiary` 暗 0.42→0.52 alpha、亮 0.42→0.55 alpha；10px 仅保留给全大写 micro-label（按 AGENTS.md §15 双块同步纪律执行）。**实施修正（UI-02 实测）**：亮色 0.55 实测仅 4.12:1（白底）/ 0.60 实测 4.46:1（选中染底），均不达 AA → 亮色最终落地 **0.63**（白底 ≈5.4、染底 ≈5.0），估算让位实测（R3 纪律） |
| D4 | 审批 | 升级项 ①结构化参数呈现 ②焦点/aria 管理 ③键盘快捷键 ⑤pending 期间 Composer 置灰 **做**；④fail-closed 倒计时 **缓做**——必须先核实后端是否下发超时时间戳（不允许前端硬编码 300s，违反「Web UI 不维护第二套真相」不变量）；核实结果与后续决定记入 `docs/FRONTEND_ISSUES_LOG.md` |
| D5 | 规范 | 先生成根目录 `DESIGN.md`（已生成，含 `.impeccable/design.json` sidecar）再动代码；之后每批 code-review 以 DESIGN.md 为基准之一 |
| D6 | 交付质量 | PRD 与 tickets 必须详细到「另一个 AI 接手零歧义」（用户原话要求） |

---

## 1. 背景与证据摘要

### 1.1 评审结论（详见快照）

- **Nielsen 24/40**：底座工程纪律高（渐进披露、材质 token 化、Run Pulse 三通道状态），失分集中在启发式 2（真实世界语言：未知事件泄漏 JSON）、4（一致性：审批卡材质违例）、6（识别 vs 回忆：11 个无标签 icon）、10（帮助：几乎为零）。
- **DOM 实测**（B 评估，Playwright computed style）：`--text-tertiary` 实测对比度暗 3.96–4.09 / **亮 2.65–2.76**（AA 需 4.5）；亮色 accent 作 11px 事件名 **3.15**、亮色审批工具名 **3.04**；字号分布 `font-size:10px`×30 处 + 11px×98 处 ≈ **75% 文字声明**，14px 仅 4 处；正文行宽 78ch / 行高 1.7 / tabular-nums 全达标（这些是优点，不许回退）。
- **detector**：4 处 `side-tab` 彩色左边条（app.css:1859/2366/2444/4157），逐条核实为刻意设计非误报；处置政策见 §2 R5。
- **焦点/命中区**：focus-visible 双环存在（发送键 outline:none 是刻意的 box-shadow 双环）；全部命中区 ≥32px（优点，不许回退）。
- **行为证据**：审批卡出现时无 aria-live、无焦点移入；`description/reason` 字段后端下发但前端**未渲染**（`ApprovalCard.tsx` 只渲染 title/tool/args）；审批 pending 期间 Composer 可正常输入提交。

### 1.2 一句话问题定义

> 产品性格在「观察」侧很强（Run Pulse、Trace Ladder、渐进披露），在「决断」侧缺位（审批时刻整体失格）；视觉执行层有「微字号雾 + 低对比 + accent 墙纸化」三个系统性偏差。本批次不做新功能，只把执行质量拉到冻结决策应有的水平。

---

## 2. 成文规则（本批次新增/重申的设计规范，code-review 必查）

以下规则已写入根目录 `DESIGN.md`（含 Named Rules），此处列出供 review 时逐条对照：

- **R1 One Voice Rule**：accent 只给交互（hover/selected/focus/主操作）与状态指示；**禁止**给非交互内容当语法高亮。首批整改对象：Inspector 时间线事件类型名（`.tl-type`）、审批卡工具名（`.approval-tool code`）。
- **R2 12px Floor Rule**：可读文本下限 12px（`--text-xs: 12px`）；10px 仅限「全大写 + letter-spacing」micro-label（如面板眉标 `RUN INSPECTOR`）。现存 30 处 10px 逐一分类整改（UI-02）。
- **R3 Contrast Floor Rule**：一切可读文本两主题实测 ≥4.5:1。`--text-tertiary` 按 D3 调整后须复测达标（暗 ≈4.9:1、亮 ≈4.6:1，UI-02 验收时用 DOM 实测证明）。
- **R4 Glass Only Floating Rule**：玻璃材质与阴影只属于浮层。**审批卡是现存唯一违例**（`approval-card glass` 双类 + `0 0 20px` 第三级辉光），UI-01 修复；修复后不得回退。
- **R5 Side-tab 政策**：彩色单侧粗边条只允许两类既有形态——(a) 语义告警实色条（审批卡 3px warning、错误提示 2px destructive）；(b) accent 半透明 2px 签名条（delegation 摘要、reasoning 文本）。不得新增第三类；detector 对这 4 处的 warning 接受为「已知、刻意、有注释」，不算违规。
- **R6 平台键位规则**：快捷键文案按平台显示（macOS `⌘` / 其他 `Ctrl`），新增 `web/src/lib/platform.ts` 统一提供；禁止再硬编码 `⌘`（现存违例：Composer placeholder，UI-06 整改）。
- **R7 结构化呈现规则**：不给用户直出原始 JSON / 带字面转义（`\n`）的字符串；关键字段（path、command、diff）结构化呈现（UI-01/UI-04）。

**明确不动的东西**（Refinement 边界，动了就是违约）：粉色 accent 色值、暗色优先策略、语义表面五层模型、radius 阶梯、两级阴影体系、三栏布局结构、四档密度机制、Run Pulse / Trace Ladder 交互设计、78ch 行宽、tabular-nums 纪律、32px 命中区下限。

---

## 3. 批次与依赖

```
批次 0  DESIGN.md 固化（已完成：根目录 DESIGN.md + .impeccable/design.json）
批次 1  UI-01 审批卡重塑（P0）           ← 含 R4/R6/R7 首批落地
批次 2  UI-02 排版地板 + 对比度（P1）     ← 含 R1/R2/R3 落地（token 级，全局）
批次 3  UI-03 Inspector run 分组 + 过滤 chips（P1）
批次 4  UI-04 信任裂缝（P2）+ UI-05 Rail 空态（P2）   ← 两个小批可合一次门禁，分开 commit
批次 5  UI-06 minor 打磨（依赖 UI-01 的 platform.ts）
```

依赖关系：UI-01 产生 `src/lib/platform.ts`（UI-06 复用）；UI-02 动全局 token（**必须**在 UI-03/04/05 之前完成，避免它们基于旧 token 调间距）；其余无依赖。严格按批次顺序执行。

---

## 4. 全批次通用的工程要求（每个 ticket 的完成定义都包含）

1. **SDD 循环**（AGENTS.md §16.6）：/implement（TDD 先红后绿）→ /code-review（Standards + Spec 双轴，Spec 轴含 DESIGN.md 对照）→ 修复到零 finding → 全量门禁 → 本地 commit → 更新 `docs/SDD_TICKET_TRACKER.md`。
2. **门禁命令**（任一失败不得 commit）：
   ```bash
   cd web && npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build
   ```
   - oxlint 基线 **38 warnings / 0 errors**（B-1 批起为 38；本批新增文件 0 warning，基线不增加）。
   - Playwright **必须 `--workers=2`**（4 worker 有资源竞争抖动）。
3. **变异验证**：每个新增断言必须证明有效——故意改坏实现 → 该断言变红 → 还原 → 变绿。记录进 ticket 完成笔记。
4. **§15 亮色同步**：凡动 `:root` token，必须检查 `:root[data-theme='light']` 是否需要同步覆盖；DESIGN.md 的 Colors 节若受影响也要同步。
5. **e2e selector 稳定性**：重构组件时**尽量保留既有 class 名**（`.approval-title/.approval-actions/.approval-error` 等 e2e 依赖项）；必须改名时，同一 ticket 内同步更新全部引用，并在 tracker 里列出 selector 变更清单。
6. **不推送远程**：只本地 commit；merge/push 由集成 AI 负责（AGENTS.md §13/§14）。
7. **临时产物**：`web/audit-screenshots.mjs`、`web/audit-dom-evidence.mjs` 是审查工具脚本（未入库）；UI-02 需要把其中对比度/字号测量固化成正式 e2e spec，之后这两个脚本删除，不入库。
8. **进度落点**：在途进度记 `docs/SDD_TICKET_TRACKER.md`；全部合入 main 后由集成侧更新 `docs/PHASE_STATUS.md`。

---

## 5. Ticket 总览（详细施工规格见 `docs/UI_POLISH_TICKETS.md`）

| Ticket | 优先级 | 一句话 | 关键文件 |
|--------|--------|--------|----------|
| UI-01 | P0 | 审批卡重塑：结构化参数+diff、焦点/aria、键盘快捷键、Composer 置灰、材质违例修复 | `ApprovalCard.tsx`、`app.css`、`Composer.tsx`、新增 `lib/platform.ts` |
| UI-02 | P1 | 排版地板与对比度：token 三改 + 10px 清理 + accent 去墙纸化 + 对比度回归锁 | `index.css`、`app.css`、新增 e2e 对比度 spec |
| UI-03 | P1 | Inspector 时间线 run 分组 + 过滤 chip 化 + 头标对齐 | `StepDetail.tsx`、`app.css` |
| UI-04 | P2 | 信任裂缝：未知事件摘要、forked 分类、`<50ms`、0 秒省略 | `projection.ts`、`format.ts` |
| UI-05 | P2 | Rail 空态指路：带文字按钮 + 行动链接 | `SessionList.tsx` |
| UI-06 | P3 | minor 打磨：平台键位文案、CJK 间距、徽章样式收敛 | `Composer.tsx`、`CommandPalette.tsx`、`app.css` |

---

## 6. 非目标（Scope Lock，AGENTS.md §8）

- 不做新功能（Split/Preview 保持诚实空架子；不实现审批倒计时——除非 D4 的后端核实发现字段已存在且用户确认追加）。
- 不换字体、不换 accent 色、不引入新组件库/动画库（现用 lucide 保留）。
- 不重构 projection/useSession 等非视觉逻辑（UI-04 只改摘要函数与一处注册表登记）。
- 不动后端契约；发现契约问题只登记 `docs/FRONTEND_ISSUES_LOG.md`。
- 不顺手修本 PRD/tickets 之外的问题（发现了记 issues log，不顺手改）。

## 7. 风险与回滚

| 风险 | 缓解 |
|------|------|
| UI-02 全局 token 改动引发密集布局位移 | 门禁含 6 档宽度 e2e（g-visual-qa）+ 密度 spec（h-density）；位移超限处允许**逐点豁免**（该处显式 `font-size` 覆盖），豁免清单记 tracker |
| UI-01 改审批卡 DOM 破坏既有 e2e | class 名稳定策略（§4.5）；n-approval-card.spec.ts 全量保留并扩展 |
| token 改动造成亮色漂移 | 每个 token 改动后在亮色主题截图（复用 audit-screenshots.mjs 流程）肉眼确认 + 对比度 spec 断言 |
| 快捷键与既有 ⌘K/⌘+Enter 冲突 | UI-01 审批快捷键仅在审批卡挂载且 pending 时激活；Composer 在 pending 期间 disabled，发送路径天然关闭；e2e 锁冲突场景 |

## 8. 交接协议（给接手的 AI）

1. 读本文档 §0 决策记录 → §2 成文规则 → §4 工程要求。
2. 读 `docs/UI_POLISH_TICKETS.md` 里**编号最小的未完成 ticket**（完成状态以 `docs/SDD_TICKET_TRACKER.md` 最新记录为准）。
3. 读根目录 `DESIGN.md`（视觉基准）。
4. 按 §4.1 SDD 循环施工；不确定的事查本 PRD 对应 ticket 的「零歧义规格」；规格没写的按 DESIGN.md；再没写的，停下来在 issues log 登记而不是猜。
5. 全部 ticket 完成后：删除两个 audit 临时脚本 → 跑一次完整门禁 → 更新 tracker 总结 → 更新 `docs/integration/FRONTEND_REFRESH_PERSIST_INTEGRATION_PROMPT.md` 告知集成 AI。
