# 交接手册：逐按钮覆盖收口（45/45）+ 审批卡证伪 + 联调车道

> **分支**：`feat/frontend` @ `D:\intelligence-agent-frontend`
> **本手册覆盖**：`35cd0a1` → `8ed86f0` → `1a75c3a` → `c9dcf2a` → `e215ec8`（2026-09-11）
> **门禁终值**：tsc ✓ · vitest **497 passed**（28 文件）· oxlint **35 warnings / 0 errors** · playwright **112 passed**（`--workers=2`）· vite build ✓ ｜ 联调车道 **2 passed**（需真后端）
> **禁止推送远程**：`git push` / merge 由集成 AI 执行（AGENTS.md §13.2 / §14.4）

---

## 1. 一句话结论

用户要求「每个功能按钮都必须点一遍」。**最终 45/45 全部有真实点击证据**，其中最后两个（审批卡「批准」「拒绝」）此前被登记为「产品不可达」——**那个结论是错的**，本轮证伪并真机点击成功。同时新增一条不入 CI 的联调车道，用于承载「必须真后端 + 真模型」的取证。

---

## 2. 覆盖账目（最终）

| 验证口径 | 数量 | 项 |
| --- | --- | --- |
| 真实后端 + 真实浏览器 | 38 | 见 `FRONTEND_ISSUES_LOG.md` 第三轮清单 |
| 真实点击 + **mock 流** | 3 | `tool-out-wrap-btn`、`tool-out-jump`、`reasoning-jump` |
| 真实点击 + mock 401 | 1 | `auth-banner-close` |
| e2e 内激活（mock 目录） | 1 | `ContextProviderPicker` 触发器 |
| **真机点击（真实后端 + 真实模型）** | 2 | 审批卡「批准」「拒绝」 |
| **合计** | **45** | **无「未验证」按钮遗留** |

---

## 3. 本批做的三件事

### 3.1 三个「瞬态按钮」——用 mock 流钉住窗口后真实点击

`tool-out-wrap-btn` / `tool-out-jump` / `reasoning-jump` 此前被登记为「实际不可达」，理由是真实后端里那个窗口只有毫秒级（cmd.exe 缓冲输出 + bash 工具 10s 硬超时）。

**前提是错的**：窗口开关来自**投影状态**，不是网络时序——

- 工具尾窗：`ToolCard.tsx:137` 传 `streaming={tool.status === 'running'}`
- 推理块：`ReasoningBlock.tsx:206` 传 `streaming={block.status === 'streaming'}`

所以 mock SSE **只发 `tool/output_delta`、不发 `tool/result`**（推理块同理不发 `reasoning/completed`），状态恒为流式，窗口永久驻留。回归锁 `web/e2e/m-stream-affordances.spec.ts`（2 用例 × 2 视口），三处变异验证全红。

### 3.2 401 缝：补单测 + 凭据横幅 e2e

- 原注释谎报「`api.test.ts` 测了 401 分类」，实则全 `src` 测试树**零个 401 引用**（已改成事实）：`api.test.ts` +3 例（401 → `UnauthorizedError`、`onUnauthorized` 广播 detail、body 非 JSON 的回退文案）。
- 新增 `web/e2e/l-auth-banner.spec.ts`：401 → 横幅 → 关闭 → **再有 401 会重新出现**（原注释把行为说反了：关闭不是永久忽略，`App.tsx:148` 每次广播都会重新显示）。

### 3.3 审批卡两键：证伪「不可达」+ 真机点击

详见 §4。回归锁 `web/e2e/n-approval-card.spec.ts`（4 用例 × 2 视口）；真机脚本走独立车道 `web/e2e-live/approval-live.spec.ts`。

---

## 4. 关键发现：审批卡其实可达（原结论错误）

**原登记**：`App.tsx` 硬编码 `auto_approve: true` → 待审批项永不产生 → 卡片不可达。

**真相（源码链路）**：

| 环节 | 位置 | 事实 |
| --- | --- | --- |
| 卡片由什么渲染 | `projection.ts:514` → `Conversation.tsx:348` | `tool/approval-requested` 事件填 `pending_approvals`，**与 `auto_approve` 无关** |
| 真正的开关 | `session/service.py:348` | `interactive = permission_mode_explicit and permission_mode != danger-full-access`——**显式传 `permission_mode` 即开启交互式审批** |
| 字段优先级 | `app.py:199` | 「两者同传时 `permission_mode` 优先」 |
| 前端会传吗 | `lib/amend.ts:47` | **会**：Composer 权限档位选择器 → `toCreateControls()` 的 `permission_mode` |
| 哪个工具会被拦 | `tooling/approval.py:80`（`needs_approval`） | policy=`read-only` 时任何 `workspace-write` 工具都需审批；`executor.py:659` 随即调 callback 发事件 |

**真机取证**（真实后端 + 真实模型 + 真实浏览器，无任何 `page.route` mock）：Composer 选「只读」→ 提交「创建工作区文件」→ `write` 工具超出策略 → 卡片渲染 → 点「批准」/「拒绝」→ 后端 `events.jsonl` 落库 `permission/resolved`：

- 批准：会话 `8e06984e` seq 26 `tool/approval-requested`(write) → seq 27 resolved **decision=approve_once**
- 拒绝：会话 `4c5a30c4` seq 30 requested → seq 31 resolved **decision=deny**

**这一步是测试断言，不是人工观察**：联调车道点击后 `expect.poll` 后端 `/events`，POST 被拒就过不去。

**保留结论**：默认（用户不选权限档位）不出现审批卡，这是**正确的产品默认**；是否把交互式审批做成默认档位属产品决策。

---

## 5. 怎么跑

### 5.1 主门禁（hermetic，CI 用）

```bash
cd web
npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build
```

`--workers=2` 是硬要求（4 worker 有资源竞争型抖动）。

### 5.2 联调车道（真后端 + 真模型，手动）

```bash
# 1) 后端：在 D:\intelligence-agent-backend 起 web app（127.0.0.1:8000）
# 2) 前端 + 测试：
cd web && npx playwright test --config playwright.live.config.ts
```

配置 `web/playwright.live.config.ts`（`testDir: './e2e-live'`，`workers: 1`，单 project）。**不进主门禁**：模型是否真调工具由模型决定，结果非确定。

### 5.3 新增测试目录时必查两侧

见 §6 坑点 1。

---

## 6. 坑点清单（本批实际踩到 / 差点踩到）

### 坑点 1（最严重，我自曝的）：新增测试目录只改了一侧配置，单测车道被污染

新建 `web/e2e-live/` 后，`vitest.config.ts` 的 `exclude` 只写了 `'e2e/**'`，**没覆盖 `'e2e-live/**'`** → vitest 把 Playwright 的 `test()` 当单测收集，**单测车道直接变红**（`1 failed | 28 passed`，29 文件）。

更坏的是：我第一次跑 vitest 时该文件尚未就位，于是报了「497 passed」——**那是个错误的门禁结论**，靠事后自查才发现。

**规则**：新增任何测试目录，必须**同时**检查：

- `playwright.config.ts` 的 `testDir`（默认车道往哪扫）
- `vitest.config.ts` 的 `exclude`（别让 vitest 扫到 Playwright 用例）
- 验证方法：`npx playwright test --list | grep -c <新目录>` 应为 0；`npx vitest list | grep <新目录>` 应无输出

### 坑点 2：Python 文本模式改写文件 → LF 变 CRLF，`git diff` **看不出来**

用 `python -c "open(p,'w')..."` 做变异时，Windows 上会把 `\n` 写成 `\r\n`。因为 `core.autocrlf=input`，`git diff` / `git hash-object` 都会归一化，**看着是干净的**；但 `git status` 会挂着一个幽灵 `M`。

**发现方法**：`git ls-files --eol <file>` —— 正常应显示 `i/lf w/lf`，异常时是 `i/lf w/crlf`。

**修复**：`git show ":<path>" > "$path.tmp" && mv -f "$path.tmp" "$path"`（从索引取原始字节）。

**预防**：脚本里用 `open(p,'w',encoding='utf-8',newline='')`。

（注：仓库有 `.gitattributes` 钉住 `sh=LF / ps1=CRLF`，但那条不覆盖 `.ts`。）

### 坑点 3：「不可达」这个结论，本批**两次都错了**

第一次：三个瞬态按钮（以为要等真实流式窗口，实际窗口由投影状态决定）。
第二次：审批卡（以为 `auto_approve` 是门，实际门是 `permission_mode_explicit`）。

**共同错法**：把「我没找到路径」当成「路径不存在」，然后把它写进文档当成结论。

**规则**：登记「不可达」前，必须先把**渲染条件 / 状态来源**追到源码行；只要渲染依赖某个事件或状态分支，就问「这个分支能不能用 fixture 造出来」。造不出来才叫不可达，并写明**造不出来的原因**。

### 坑点 4：mock 网络的点击 ≠ 真机点击；「UI 变了」≠「后端已决」

`ApprovalCard.tsx:26-33` 的 `catch` 对**任何**错误都把标题翻成「已批准/已拒绝」（注释却写「其它错误保持 pending」，与代码相反）。后果：把 `/approve` 改成恒返回 404，UI 依旧显示「已批准」、按钮消失、请求体依旧正确——**只有查后端 `permission/resolved` 才能区分**。已登记 **OBS-015（P2）**。

**规则**：涉及「写入是否真的发生」的断言，要落到**durable 真相**（后端事件 / JSONL / 副作用），不要只断 UI。

### 坑点 5：断言不足 = 假绿

本批被独立审查抓出的两类：

- **只断请求体、不断 URL**：把 `api.ts` 的会话 id 换成常量（打到别的会话），两条车道**都会绿**——因为 mock 的路由正则是 `[^/]+`，任何 id 都匹配。
- **只断 class 名、不断生效样式**：删掉 `.tool-out-nowrap { white-space: pre }` 的真实 CSS，测试照样绿。
  修法：`toHaveCSS('white-space', 'pre')` / `toHaveCSS('white-space', 'pre-wrap')`。
- **前置条件不显式断言 → 后续断言假通过**：`suspended` 要求容器可滚，若容器不可滚，`scrollTop = 0` 是空操作，「点击跳转」断言会**假通过**。修法：数值断言 `expect(scrollHeight, '容器必须可滚动…').toBeGreaterThan(clientHeight + 5)`。

### 坑点 6：Playwright 路由优先级与 `addInitScript`

- **后注册的路由胜**（用于在 `routeApi` 的 catch-all 之外加专用端点）。
- **`addInitScript` 每次导航都重跑**（含 `page.reload()`）——用它播种会让测试变成**只测读路径**。子会话刷新回归锁首版就是这么被变异验证证伪的；改成真实点击写入路径才有效。

### 坑点 7：真实后端的流式窗口是移动靶

本后端 `bash` 工具在 Windows 走 cmd.exe（`shell=True`）且**缓冲输出**，整段输出以**单个终态** `tool/output_delta` 到达、`tool/result` 紧随其后；叠加工具 10s 硬超时，流式窗口只有毫秒级。想在真机上点流式 UI，六次尝试都失败——**必须用 mock 流钉住窗口**（这正是 3.1 的做法）。

### 坑点 8：变异验证本身会被误用

- 变异脚本写错语法（Python 语法混进 TS）会产生**无意义的失败**，看起来像「测试有效」。
  **规则**：变异后先确认 `tsc -b` 通过，再相信失败结果。
- 变异可能**静默没应用**（锚点字符串不匹配），测试通过会被误读为「测试抓不到」。
  **规则**：脚本里 `assert` 锚点存在并打印「MUTATED」。

---

## 7. 未决项（明确披露，勿误判为完成）

| 项 | 级别 | 说明 | 谁能定 |
| --- | --- | --- | --- |
| **OBS-015** 审批卡 `catch` 乐观翻转 | P2 | 任何错误都翻「已批准/已拒绝」，与注释相反；失败时用户看到假象。本轮**未改代码**（§8 Scope Lock）。建议：409/404 幂等已决 vs 其它错误保持 pending + 提示重试；并补「POST 500 → 保持 pending」用例 | 产品决策 |
| 是否默认开启交互式审批 | 产品 | 现在需用户显式选权限档位才会出现审批卡。是否给 UI 提示或改默认属产品范围 | 产品决策 |
| `StreamOrchestrator`（C1 深水） | 架构 | `attachLiveStream` 仍约 200 行嵌套闭包（合帧 / 停摆心跳 / truncated 重建 / seq-gap 分流）。处于热路径交汇处，**需监督 + 测试先行** | 需用户批准 |
| `session/forked` 摘要仍落「未知事件」 | 文案 | pre-existing，文案变更未经确认 | 产品确认 |
| 7 个未接线事件类型 | 产品 | 是否显示给用户待确认 | 产品确认 |
| `api.ts` 的 amend 字段集两处书写 | 整洁 | `START_SESSION_FIELDS` / `SEND_MESSAGE_FIELDS` 各自穷尽，是否抽公共表待定 | 可延后 |
| e2e spec 不被 `tsc -b` 类型检查 | 工具链 | `tsconfig.app.json` 只含 `src`、`tsconfig.node.json` 只含 `vite.config.ts` → 新 e2e/配置的接线错误无编译期兜底（靠 playwright 运行时加载 + oxlint 解析） | 可延后 |
| `已中断` 脉冲态真实语料不可达 | 覆盖 | 无「中断且从未重跑」的真实会话，仅单测覆盖；`pulse-interrupted` 类名与 CSS 选择器无测试绑定 | 需构造语料 |

---

## 8. 怎么复核本手册的说法

```bash
cd web
# 45/45 账目：数一遍按钮，再对照 docs/FRONTEND_ISSUES_LOG.md 的账目表
grep -rn "<button" src --include=*.tsx | grep -v test | wc -l

# 审批卡可达性（后端仓库）：看 interactive 的判定
grep -n "interactive = " "D:/intelligence-agent-backend/src/agent_harness/session/service.py"
grep -n "pending_approvals" src/lib/projection.ts
sed -n '20,40p' src/components/ApprovalCard.tsx

# 门禁
npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build
```

真机取证需要后端在跑：`curl -s http://127.0.0.1:8000/api/health` → `{"status":"ok"}`。
