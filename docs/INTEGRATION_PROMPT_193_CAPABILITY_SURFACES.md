# 集成提示词：#193 能力声明侧缺口（后端 `feat/backend` + 前端 `feat/frontend`）

> 给集成 AI。这份是**跨端**票，两端都已本地 commit、未 push、未 merge。
> 你没读过上下文也能照这份做事：先看「一句话」，再看「怎么验」。

---

## 1. 一句话

`GET /api/capabilities` 此前只投影插件 capability，而「文件/改动」(`changes`) 与「输出」
(`terminal`) 两个面由**内置工具**产出、不由任何插件产出 ⇒ 保守默认恒置 false ⇒
`centerTabs` 把两个面在**所有真实部署**里滤掉，**用户看不到**（前端 #189 / #190 的实现都在，
只是没人声明）。本票补一条**恒在的 core 条目**如实声明它们；前端 e2e 同步改吃这份真实载荷。

**合并本批 ≠ 用户能看见**——这句在本票之后作废：合并后端 `21f5427` 之后，默认部署的
`GET /api/capabilities` 就会返回 `count=4`（core + websearch + multiagent + memory），
中心列出现三个面。**但要先合并后端**，只合并前端不会有任何变化（前端的默认载荷是镜像）。

---

## 2. 两端 commit

| 端 | worktree / 分支 | commit | 内容 |
| --- | --- | --- | --- |
| 后端 | `D:\intelligence-agent-backend` / `feat/backend` | `21f5427` | 新增 `capability/manifest.py`（唯一形状 + core 条目）、端点恒发 core、测试、验收文档 |
| 前端 | `D:\intelligence-agent-frontend` / `feat/frontend` | `127ecc3` | e2e 默认载荷换成 `CORE_CAPABILITY`、修 `m-stream-affordances` 严重模式冲突、跨仓行号引用改函数名 |

两笔都**未 push、未 merge**（§14.4 等批准）。建议顺序：**先后端，后前端**（§14.9 一次一端）。
前端那笔在后端合并前也能独立通过自己的门禁（它跑的是 mock），所以顺序上没有硬依赖，
但合并后**必须**跑下面第 4 节的真实验收。

---

## 3. 改了什么（逐条，可对账）

### 后端 `21f5427`（6 文件，+264 / -62）

- **新增 `src/agent_harness/capability/manifest.py`**：
  - `manifest_entry()` = 条目形状与保守默认的**唯一一份**（此前内联在端点循环里，
    core 一加入就会变成两份）。插件条目走它，默认与 #193 之前**逐字不变**
    （未声明 → `chat`/`timeline` = true，其余 false；`actions` 不补齐）。
  - `core_manifest_entry()`：`id="core"`、`display_name="内置工具"`、
    `provider_name="builtin"`、`surfaces` = `chat`/`timeline`/`changes`/`terminal` = true、
    `artifacts` = false、`actions` = `permissions`/`stop`/`resume` = true、`retry` = false。
  - 模块 docstring 写了**判据**（以后想再加一个 core 面时照三条问）：无条件注册？需要额外
    配置？不声明用户是否看不到已实现的面？
- **`web/app.py::list_capabilities`**：返回
  `{"capabilities": [core_manifest_entry(), *[descriptor_manifest_entry(d) for d in registry.available()]]}`
  —— core **恒在且排在最前**。docstring 重写（含"空就是空"那条旧取舍的修订说明）。
- **`capability/base.py`**：`CapabilityDescriptor` 的 surfaces/actions docstring 指向新模块。
- 测试：`tests/web/test_web_phase2_endpoints.py` 的 `TestCapabilities` 重写（4 条），
  `tests/web/test_web_phase5_staged_endpoints.py` 的过期交叉引用订正。
- `docs/ACCEPTANCE_LANE_ENV.md` §2：期望集 **count=3 → count=4**（core + 3 插件），
  并新增两条边界说明（见第 5 节）。

### 前端 `127ecc3`（8 文件，+142 / -55）

- `web/e2e/fixtures.ts`：新增 `CORE_CAPABILITY`（逐值镜像 `manifest.py`），
  `routeApi` 的 capabilities **缺省载荷从 `[]` 改为 `[CORE_CAPABILITY]`**（= 后端真实默认）。
- `web/e2e/workspace-modes.spec.ts`：AC2/AC3 改为"真实默认 → `['Chat','文件/改动','输出']`"；
  新增 `capabilities: []` 一条覆盖"目录真的为空"（老后端/降级路径）；AC4 用真实默认 + 调用计数；
  新增并集语义用例（core + 插件全 false → 三面仍在）。
- `web/e2e/x-output-panel.spec.ts` / `z-changes-panel.spec.ts`：去掉注入，走真实默认。
- `web/e2e/m-stream-affordances.spec.ts`：**这是本票在前端唯一一处真会被合并卡住的修**，
  见第 4 节的风险 1。
- `web/src/lib/capabilities.ts` / `api.ts` / `capabilities.test.ts`：**注释/文档级**改动
  （跨仓行号引用改函数名——那些行号被本票重写端点时作废；`CORE_CAPABILITY` 的漂移说明改成
  如实口径）。**前端运行时代码零行为改动**，`deriveSurfaces` / `centerTabs` 一个字没动。

---

## 4. 合并后必须做的验收（真端点，不是 e2e）

1. **后端真端点**（这是本票的交付判据）：
   ```bash
   curl -s http://127.0.0.1:8000/api/capabilities | python -m json.tool
   ```
   期望：`count=4`；第一条 `id == "core"`；`surfaces.changes == true` 且
   `surfaces.terminal == true`。**三个面是否出现以这条为准**，不要只看 e2e。
2. **前端真机**：起 `web`，默认部署下中心列应是 `['Chat','文件/改动','输出']`
   （#193 之前只有 `['Chat']`）。点开「输出」应看到命令输出、点开「文件/改动」应看到改动。
3. **两侧同值**：`ACCEPTANCE_LANE_ENV.md` §2 已写死期望值，照它核。前后端的 core 值是
   **手工镜像**（跨仓无共享来源）——若后端将来改值，前端 e2e **不会**变红，只能靠这条人工核。

### 风险 1：前端 `m-stream-affordances.spec.ts` 的严重模式冲突（已修，但要知道为什么）

`ToolOutputStream` 是对话工具卡与「输出」面**共用的同一个渲染器**（#190 AC9）。#193 让
「输出」面在默认载荷下**真的存在**之后，它还带同一个工具的一份输出（`App.tsx` 的 `hidden`
面板，不卸载——切面保留滚动位置）⇒ 裸类名 `.tool-out-body` / `.tool-out-wrap-btn` /
`.tool-out-jump` 同时命中**两处**，Playwright strict mode 直接报"两个元素"；而且藏起来那份
`scrollHeight === 0`，可滚动前置断言会**假失败**。已按面板 id 收窄到 `#workspace-panel-chat`。

**同类隐患**：任何 e2e 里**裸类名**去查「输出」面/「文件/改动」面内部元素的地方，在真实默认
载荷下都可能变成两个。本批全量 e2e（306 passed）没再发现，但如果以后新增面，记得先跑全量。

---

## 5. 两条必须传下去的口径（别当成 bug 报）

1. **反例守卫的正确读法**（票面 AC4 的字面读法已过时）：前端对多条条目取**并集**，core 恒在
   ⇒ 插件写 `changes: false` **不会**让「文件/改动」面消失。那是"这个插件不产出它"，不是
   "这个会话产不出它"（内置工具确实产出）。要验闸门语义只能用**不含 core 的载荷**
   （`capabilities: []` → 只剩「Chat」）。真实端点不会返回空列表，那条路径只在"老后端 /
   端点被裁剪"的降级场景出现。
2. **声明是部署级，不是 profile 级**：该端点没有 session 上下文，读不到某个 `agent_profile`
   的 `tool_scope`。若某 profile 把 `bash` 收窄掉，「输出」面仍会出现（**空态**）而不是消失。
   这是**有意取舍**（如实的空面 > 按 profile 猜）：profile 级声明需要让端点在 session 上下文里
   算，属另一张票。

---

## 6. 门禁证据

| 端 | 命令 | 结果 |
| --- | --- | --- |
| 后端 | `ruff check .` | 全绿 |
| 后端 | `pytest`（全量） | **2207 passed / 10 skipped / 42 deselected / 0 failed**（290.33s） |
| 前端 | `npx tsc -b` | 通过 |
| 前端 | `npx oxlint` | 0 error（44 既有 warning） |
| 前端 | `npx vitest run` | **813 passed**（48 files） |
| 前端 | `npx playwright test --workers=2` | **306 passed** |
| 前端 | `npx vite build` | 通过 |

**注意**：后端全量 pytest 与前端 e2e **不要并发跑**（已知资源竞争型抖动：
`tests/sandbox/test_exec_hardening.py::test_local_exec_timeout_kills_grandchild_tree`
会受前端 e2e 负载影响）。本批的门禁是**串行**跑的。

---

## 7. 关单状态

`#193` 已按 §14.12 关闭（两端都完成，comment 写明两端分支 + commit + 由集成 AI 执行合并）。
残余项（**不阻塞本票**，已记在 comment 里）：

- 前后端 core 值是手工镜像，无跨仓共享来源；后端改值前端测试不会红（第 4.3 节的人工核对是
  当前的唯一防线）。
- profile 级声明（`tool_scope` 收窄后仍显示空面）——需要另开票。
