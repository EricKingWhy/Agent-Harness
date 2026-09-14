# 交接手册：UI Polish 六票（设计优化批）

> **分支**：`feat/frontend` @ `D:\intelligence-agent-frontend`
> **本手册覆盖**：`cd107a2` → `1ae3bf2` → `236049f` → `522602d` → `e543ae1` → `d0ddac9`（2026-09-12/13）
> **门禁终值（U-3 尾实跑）**：tsc 0 · vitest **623 passed**（35 文件）· oxlint **38 warnings / 0 errors**（基线持平）· playwright **196 passed**（`--workers=2`）· vite build ✓
> **禁止推送远程**：`git push` / merge 由集成 AI 执行（AGENTS.md §13.2 / §14.4）
> **本批无后端代码改动，无契约变更**——后端 AI 读完本手册后需要做的事只有一件（见 §8）。

---

## 1. 一句话结论

用户要求「前端功能已经很全，UI 设计要优化」。经 impeccable 双评估（Nielsen 24/40 基线）+ 用户 grill-me 五问决策（D1-D6），产出六票施工规格并全部交付：**UI-01 审批卡重塑、UI-02 排版地板+对比度、UI-03 Inspector run 分组、UI-04 信任裂缝（不造假精度）、UI-05 Rail 空态指路、UI-06 minor 打磨**。每批都走了「双轴 code-review → 修复到零 finding → 全量门禁 → 本地 commit」的 v2 批量循环。**零未解决 P0/P1。**

---

## 2. 用户决策记录（grill-me，2026-09-12，不可违约）

| 问 | 决策 |
| --- | --- |
| 修哪些 | 全部五项 critique 问题，分批 SDD 循环（P0 → P1 排版 → P1 Inspector → P2×2），每批 code-review + 全量门禁 + 本地 commit |
| 视觉方向 | **Refinement**——保留已冻结的视觉世界（粉色 accent / 暗色优先 / 材质模型 / 圆角阶梯），把「accent 只用于交互与状态」升格为成文规则 |
| 排版地板 | `--text-xs` 11→12px；`--text-tertiary` 暗 0.42→0.52、亮提至 **0.63（实测 AA 修正）**；10px 只留大写 micro-label |
| 审批卡升级 | ①结构化参数+diff 复用 ②焦点/aria ③快捷键 ⑤composer 锁定 做；**④ fail-closed 倒计时 defer**——必须先核实后端是否发超时时间戳，禁止硬编码 300s（不变量 #22：Web UI 不维护第二真相） |
| 规范产物 | 先生成根目录 `DESIGN.md`（impeccable document 模式），照它施工 |

---

## 3. 交付物地图（后端 AI 只需浏览前两行）

| 产物 | 位置 | 用途 |
| --- | --- | --- |
| **DESIGN.md**（根目录） | `D:\intelligence-agent-frontend\DESIGN.md` | 视觉规范基准：YAML frontmatter + 8 节 + 4 条 Named Rule（One Voice / 12px Floor / Contrast Floor / Glass Only Floating）。**长期有效**，后续前端票必须遵守 |
| `.impeccable/design.json` | 同目录 sidecar | 组件 drop-in HTML/CSS + 色阶元数据 |
| `docs/UI_POLISH_PRD.md` | frontend worktree | 决策 D1-D6 + 规则 R1-R7 + 批次划分 + 验收协议 |
| `docs/UI_POLISH_TICKETS.md` | 同上 | UI-01～06 逐票规格（file:line 证据 / In-Out / AC / 测试计划） |
| `docs/SDD_TICKET_TRACKER.md` | 同上 | U-1/U-2/U-3 双轴审查处置表 + 变异验证台账 |
| `docs/integration/FRONTEND_REFRESH_PERSIST_INTEGRATION_PROMPT.md` §10 | 同上 | **集成 AI 的唯一入口**——commit 链 / 7 条行为变化 / 遗留清单 |

---

## 4. 六票各做了什么（一行一票）

| 票 | 内容 | 用户可感知的变化 |
| --- | --- | --- |
| UI-01 | 审批卡重塑 | 结构化参数（path/command/diff/content 分类渲染，diff 复用 DiffBlock 组件）；role=alertdialog + 挂载焦点；**Ctrl/Cmd+Enter=批准、Ctrl/Cmd+Backspace=拒绝**（仅第一张 pending 卡挂监听，防多卡批量批准）；审批期间 Composer 锁定（placeholder「等待审批决策…」） |
| UI-02 | 排版地板 + 对比度 | 全局小字 11→12px；暗/亮 tertiary 提对比度（亮色实测 4.5:1）；28 处 10px 升档（只留 2 处合法大写 micro-label）；时间线事件类型名去 accent（One Voice Rule）；新增 `t-contrast.spec.ts` 对比度回归锁（8 用例 × 2 视口，含 oklab/color(srgb) 解析、未知格式 throw） |
| UI-03 | Inspector run 分组 | 时间线按 run_id 分组：组头「Run N + 状态徽标 + 事件数」；**序数按全会话首现顺序**（尾窗裁剪后 Run 2 仍叫 Run 2）；头部「N runs · M 事件」；五个视图 tab 带条目计数徽标 |
| UI-04 | 信任裂缝 | 时长 <50ms 显 `<50ms`（不再造「1ms」假精度）；ReasoningBlock <1s 显「持续 <1s」/「中断于 <1s」（不再有「持续了 0 秒」）；`session/forked`→「已分叉」、`tool/approval-requested`→「等待审批 · {tool}」、`permission/resolved`→「审批已决（{decision}）」（不再落「未知事件」） |
| UI-05 | Rail 空态指路 | 真·空态出**文字按钮**（新建项目 / 新会话）+ 文案带「注册项目目录 →」行动链接；列表加载失败仍只显错误条（不与错误自相矛盾）；非空态回 icon 按钮 |
| UI-06 | minor 打磨 | 命令面板「切换到Raw」→「切换到 Raw」（CJK 半角空格）；主题 hint 去方向箭头；run-badge 与顶栏 Run Pulse 视觉参数收敛（padding 2px→3px）；Composer 平台键位 UI-01 已覆盖 |

---

## 5. 验证方式（后端 AI 复核时可直接引用）

1. **双轴 code-review**：每批两个独立只读 subagent（Spec 轴对照 TICKETS/PRD/DESIGN；Standards 轴对照代码质量）。U-1 共 24 findings、U-2 共 14、U-3 共 4——**全部处置**（修 / 说明不改 / 登记 issues log），逐条理由在 tracker。
2. **变异验证**：每个新断言都用「改坏实现 → 测试红 → 还原 → 绿」闭环。台账：U-1 5 处 + U-2 3 处 + U-3 2 处，全部红→绿后 `grep MUTATION` 复核 0 残留。
3. **真机探针**：空态/502 态、hooks 崩溃、tab 可访问名三处用 raw Playwright 脚本（不入库）在真浏览器复验过。
4. **门禁链**：`cd web && npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build`，每批收口前实跑（e2e 必须 `--workers=2`，4 worker 有资源竞争抖动）。

---

## 6. 审查抓到的两个值得后端 AI 记住的坑

1. **Rules of Hooks + early-return**（U-2）：`useMemo` 挂在 StepDetail 的三个 early-return 之后 → 从事件详情分支切回时 hook 数不一致，**点开会话整页崩溃**。tsc/vitest 全绿、只有真浏览器红。教训：往带 early-return 分支的组件里加 hook，必须挂在所有 return 之前。
2. **「断言假绿」两类**：① `>3</span>` 这种裸子串断言会命中无关元素（改成锚定类名 + 完整文本）；② 往 tab 里加可见徽标会**改变可访问名**（`getByRole(tab, 'Timeline')` 变成 name '4'，既有 e2e 假红）——改 DOM 时同步查 e2e 选择器依赖账（TICKETS 附录）。

---

## 7. 遗留 / 明确不做（都已登记，勿误判为遗漏）

| 项 | 处置 |
| --- | --- |
| 审批 fail-closed 倒计时 | **用户决策 defer**。需先核实后端 `tool/approval-requested` 事件是否携带超时时间戳；拿不到就不做（不硬编码 300s）。**这是后端 AI 可以一起回答的问题**（见 §8） |
| 时间线 kind 过滤 chips | UI-03 票面原意，但五个图标实为视图 tab——以 tab 计数徽标实现，偏离已记录 |
| Split/Preview 空架子、半截 ID | 明确不做（诚实设计 / 信息架构取舍），登记 issues log |
| 10px 保留 2 处 | `.rail-section-label` / `.model-picker-group-label`——合法大写 micro-label（uppercase + 0.08em 字距），非违例 |

---

## 8. 请后端 AI 在集成提示词里回答的两个问题

1. **审批超时时间戳**：后端 `tool/approval-requested`（或审批队列相关契约）里是否有一个字段能让前端算出「还剩多少秒自动拒绝」？如果有，请把字段名与语义写进集成提示词（前端可以补一张诚实倒计时卡）；如果没有，请在提示词里明确「无此字段，倒计时不做」，让集成 AI 把 UIP-DEFER 关掉。
2. **本批对后端零契约变更**：`web/src/types.ts` / `src/lib/api.ts` 本次未动。集成 AI 合并时 `feat/backend` 与本批无冲突面（`web/**` 独占）；唯一已知冲突文件仍是 AGENTS.md §16（后端口径 vs 前端口径，处置建议已在 `docs/integration/BRANCH_TOPOLOGY_AUDIT.md` 与旧提示词中，本轮无新增）。

---

## 9. 复核命令（在 `D:\intelligence-agent-frontend`）

```bash
git log --oneline cd107a2..d0ddac9          # 本批 6 个 commit
git diff 2b51914..d0ddac9 --stat -- web/    # web/ 全部改动面
cd web && npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build
```

---

## 10. 移交状态

- 全部工作在 `feat/frontend` 本地 commit，**未 push、未 merge**。
- 下一步：后端 AI 出具联合提示词 → 集成 AI 按 `FRONTEND_REFRESH_PERSIST_INTEGRATION_PROMPT.md` §0（先回后正）执行合并 → `docs/PHASE_STATUS.md` 回填由集成方负责。
