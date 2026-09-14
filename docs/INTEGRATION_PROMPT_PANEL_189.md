# 集成提示词：#189 中心列「文件/改动」面（前端）→ `main`

**一句话**：把中心列的「文件/改动」面从"能力接口声明为真、但登记表压着不渲染"补成真的
能看：本会话改动过的文件清单 + 逐文件 net diff。纯前端，零后端改动、零新 API、零契约变更。

工作区：`D:\intelligence-agent-frontend`，分支 `feat/frontend`，
上一批审查固定点 `2ae4e38`。本票 commit `3e9b150`。**只动前端**。

---

## 1. 本轮 commit

| commit | 内容 |
| --- | --- |
| `3e9b150` | `feat(web): #189` 数据投影 + 面板 + CSS + 登记表翻转 + 测试 + e2e（11 文件，+691 / −20） |
| （随后一条） | `docs(panel): #189` 在途进度登记（`docs/SDD_TICKET_TRACKER.md` § 第十九轮）+ 本提示词 |

---

## 2. 改了什么

| 文件 | 改动 |
| --- | --- |
| `web/src/lib/changedFiles.ts`（新） | 纯逻辑：写工具白名单（与后端 `_WRITE_TOOL_NAMES` 对齐）/ `lineDelta` 多重集行差 / `netStatOf` 取首版→末版 / 按 path 聚合 / 无 path 计入 `unattributed` |
| `web/src/components/ChangesPanel.tsx`（新） | 左文件清单（`aria-current`）+ 右逐次改动，每次一个 `DiffBlock`；只读；空态文案 |
| `web/src/lib/capabilities.ts` | `changes` 登记项 → `implemented: true`，注释写明与 `App.tsx` 分支**成对** |
| `web/src/App.tsx` | `tab.key === 'changes'` → `<ChangesPanel tools={tools} />`（替掉"内容待 #189"的占位注释） |
| `web/src/styles/app.css` | `.changes-*`：两栏 grid / 行选中态 / 统计徽章（`+N`/`-M`/`±0`/`—`）/ `<560px` 容器堆叠；`.workspace-panel` 加 `container-type` |
| `web/e2e/z-changes-panel.spec.ts`（新） | 3 条 × 2 视口 |
| `web/src/components/ChangesPanel.test.tsx`（新） | 10 条（含 AC4 只读断言：无 input / textarea / contenteditable，无保存应用撤销按钮） |
| `web/src/lib/changedFiles.test.ts`（新） | 19 条 |
| `web/src/lib/capabilities.test.ts` | 骨架期守卫换对象（见下 §3.4） |
| `web/e2e/workspace-modes.spec.ts` | AC4/AC6 期望 tab 集加入「文件/改动」，注释同步 |
| `web/e2e/y-inspector-peek.spec.ts` | fixture 字段 `name` → `tool_name`（见下 §3.5） |

---

## 3. 行为语义（评审时要看的五条，都不是默认套路）

1. **统计口径是 net，不是各次相加**。`netStatOf` 用「首版 before → 末版 after」的行
   多重集差：改 3 行再加回 3 行显示 `±0`，而不是 `+3/-3`。相加口径会把"改完又改回"
   渲染成"改动很大"，是假热度；这个面要回答的是"文件现在跟原版差多少"。
2. **归档 / 截断时统计为 `—`，不给数字**。内容已经不在事件里（转 artifact，或超
   `_DIFF_MAX_BYTES` 被截断），任何 `+N/-M` 都是编的。UI 渲染 `—` 并给 `title` 说明
   原因（归档 / 已截断）。
3. **无 path 的改动计入 `unattributed`**，在面板脚注提示。静默丢弃会让"列出的文件"
   与实际改动不符。
4. **登记表翻转是成对的**：`capabilities.ts` 的 `implemented: true` 与 `App.tsx` 的
   `<ChangesPanel>` 分支少任何一半都会得到一个空面板（注释已写明）。原来那条断言
   "`changes` 声明为真也不渲染"的骨架期守卫，改为**注入一个未实现的 `artifacts` 面**
   来继续覆盖同一条规则，规则本身没有被删。
5. **`tool/call` 投影的字段是 `tool_name`，不是 `name`**。e2e fixture 写错字段会让工具名
   解析成 `unknown` → 不进写工具白名单 → **0 行文件，且测试"全绿"**（断言写的是空态）。
   这是本票实现过程中被测试抓到的一个真缺陷，fixture 已修正，`y-inspector-peek` 里同一
   个字段也一并改正。

---

## 4. 门禁（全绿）

```
cd web
npx tsc -b                            # 0
npx vitest run                        # 778 passed（+29）
npx oxlint                            # 0 error / 44 warnings（= 基线，新文件与新代码零 warning）
npx playwright test --workers=2       # 292 passed（+6）
npx vite build                        # 0
```

---

## 5. 集成时要注意

- **无契约变更**：不改 `GET /api/capabilities`，不改任何后端返回结构。`ChangesPanel`
  的输入是既有 `ToolCall[]` 投影。
- **⚠ 订正（2026-09-14 总门禁两轴审查发现，本节此前写错）**：原文写"此前能力接口声明为
  true 但被登记表压住"——**后端从未把 `changes` 声明为 true**。`web/app.py:918-927` 的
  投影规则是"descriptor 未声明 `surfaces` → `changes`/`terminal`/`artifacts` 一律
  **false**"，而 `capability/wiring.py` 里 7 个 descriptor（memory / skills / mcp /
  knowledge / multiagent / websearch / ticker）**没有一个填 `surfaces`**；
  `ProviderConfig` 是 strict 模型且只有 provider/enabled/options，配置路径也填不了。
  ⇒ **真实部署里 `GET /api/capabilities` 恒返回 `changes:false, terminal:false`**，
  本票与 #190 的两个面在 `centerTabs` 里被过滤掉，**用户看不到**。
  这不是本票的实现缺陷（票面 AC 的"声明为真 → 出现"已逐条满足，e2e 用显式声明钉住），
  缺的是**声明侧**：把 Core 工具集（bash / write / edit / apply_patch / git diff）能产出
  的面声明为 true。该工作原属 Phase 6 "capability surfaces 装配"（`PHASE_STATUS.md`
  记为延后项），已开票 **#193** 跟踪——**合并本批不等于用户能看见这两个面**。
- **一处用户可见变化**：在"能力声明为 true"的前提下，中心列 tab 集会多出「文件/改动」。
  `workspace-modes` AC4/AC6 的期望值已同步更新。
- **未做的相邻项（Scope Lock）**：`StepDetail.tsx` 内 `ChangesTab` 的 `.diff-cols` →
  `DiffBlock` 的收敛属 **#186 AC3**（本票的 `ChangesPanel` 已直接用 `DiffBlock`，没有
  复制第二套 diff 渲染）。~~`tabCounts.terminal` 用 `t.name === 'bash'` 而 `TerminalTab`
  行用 `isCommand` 的既有不一致~~ —— 该处已在总门禁修复中收敛为 `isCommand`（两者本
  同形，收敛只为不让"什么算一次命令"有两个答案）。
- **不建议只合本票**：本批按 v2 批量循环审查（**#183 + #189 一起**，fixed point
  `2ae4e38`）。集成 AI 应按批合并。

---

## 6. 关单状态

#189 **未关单**：按 §14.12，代码完成但尚未合入 `main`，关单 comment 需写明分支与
commit——留给集成 AI 合并后关闭（或由本 AI 在批量审查通过后再关）。
