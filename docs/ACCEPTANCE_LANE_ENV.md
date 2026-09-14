# 验收车道环境（真实浏览器验收的**前提**）

> 起因：2026-09-11 第六轮验收时，同一批控件在前几轮「能点」、这一轮「不可达」。
> 根因不是代码，而是 **`:8000` 上跑着哪个 worktree 的后端**决定了语料与能力集。
> 本文把这条车道的前提写死，避免下次再有人对着「不可达」误判为产品缺陷。

## 1. 车道构成

| 角色 | 值 |
| --- | --- |
| 前端 | `D:\intelligence-agent-frontend`（branch `feat/frontend`），dev server `:5173` |
| 后端 | `:8000`——**由启动者决定是哪个 worktree**（见 §3） |
| 代理关系 | `web/vite.config.*` 把 `/api` **硬编码**代理到 `http://127.0.0.1:8000`，不读环境变量 |

推论：**`:8000` 上是谁，这条车道就在验谁。** 前端只是如实渲染后端给的事件与能力。

## 2. 期望能力集（`/api/capabilities` 是唯一判据）

启动后先查一次，期望 **4** 条（1 个 core + 3 个插件）：

```bash
curl -s http://127.0.0.1:8000/api/capabilities
# 期望 count=4: core + websearch + multiagent + memory
```

- **`core`**（2026-09-14 起恒在，#193）：**内置工具集**的声明，不是插件。
  `surfaces` = `chat`/`timeline`/`changes`/`terminal` = true、`artifacts` = false。
  前端中心列「文件/改动」（`changes`）与「输出」（`terminal`）两个面**靠它才出现**——
  这两个面由内置工具（`write`/`edit`/`apply_patch`/`bash`）产出，不由任何插件产出；
  在此之前（端点只投影插件 descriptor）保守默认把它们恒置 false，两个面在**所有**真实
  部署里都被 `centerTabs` 滤掉。`artifacts` 为 false 是如实的：外置产物要部署配了 store
  才读得到（没配读接口 503），不是无条件能力。
- **"声明为假就不出现"的边界**（#193 反例守卫的正确读法）：前端对多条条目取**并集**，
  而 core 恒在——插件写 `changes: false` **不会**让「文件/改动」面消失。那是"这个插件不
  产出它"，不是"这个会话产不出它"（内置工具确实产出）。要验闸门语义只能用**不含 core 的
  载荷**：`capabilities: []` → 只剩「Chat」（前端 `workspace-modes.spec.ts` 的"能力目录
  真的为空"一条）。真实端点不会返回空列表，这条路径只在"老后端 / 端点被裁剪"的降级场景出现。
- **声明是部署级的，不是 profile 级**：本端点没有 session 上下文，读不到某个 `agent_profile`
  的 `tool_scope`。若某 profile 把 `bash` 收窄掉，「输出」面仍会出现（空态）而不是消失——
  如实的空面优于按 profile 猜。profile 级声明需要另一张票。
- **`websearch`**：`web_search` 工具、Context Provider 目录等。
- **`multiagent`**：**`delegate` 工具**。缺它则委派/子会话整块前端 UI **按设计不渲染**
  （零伪造，符合不变量 #21），于是这 5 个控件不可达：委派行展开、`复制子会话 ID`、
  `Inspect 子会话`、`打开子会话`、child 视图 `Run` 返回。
- **`memory`**：`memory` Context Provider + 「记忆管理」面板（`GET /api/memories`）。
  2026-09-13 复核：本部署实际返回 **3**（SID-03 修正；此前本文写 count=2，
  是 #159 MEM-4 接入 `memory` **之前**的旧口径）。缺它则记忆面板按设计不渲染。

**插件** capability 当前都只声明 `surfaces: {chat, timeline}`、`actions: {}`
（无 permissions/stop/retry/resume）——验收时不要拿"某个 capability 没给 stop 动作"当缺陷，
那是如实声明（不变量 #21）。但 **core 条目的 `actions` 是声明了的**：
`permissions`/`stop`/`resume` = true（路由分别在 `POST /api/sessions/{id}/approve` /
`cancel` / `resume`），`retry` = false（后端确实没有该入口）——这是如实值，不是缺省值。

## 3. 两个 worktree 的 `.env` 差异（本文件存在的原因）

`.env` 按 AGENTS.md §13.1.6 属**不在 worktree 之间同步**的本地文件，所以能力集天然可能不同。
2026-09-11 实测：

| worktree | `CAPABILITIES` |
| --- | --- |
| `D:\intelligence-agent`（main） | `websearch` + `multiagent`（enabled） |
| `D:\intelligence-agent-backend`（feat/backend） | **已对齐为** `websearch` + `multiagent`（2026-09-11 改，原为仅 `websearch`） |

**已做**：把 `feat/backend` 的 `CAPABILITIES` 逐字节对齐到 main 的值（取 main 的那一行原样写入，
不用 sed 拼 JSON）。理由是**车道必须验当前分支的代码**——本会话已有实证：main 的后端**没有**
`feat/backend` 的 `trace_url` 改动（`/api/sessions` 不返回该字段），当时必须杀掉它换成本分支后端，
否则 ARCH-4b 的前端契约锁在真机上根本验不了。用 main 后端还有一个更隐蔽的代价：
**main 落后于本分支的修复时会「真机通过」，制造假阴性**。

## 4. 想复现前几轮的语料怎么办

前几轮的部分结论建立在 **main 后端**的语料上（例如第三轮「加载更早 200→410」用的是
410 事件的 fork child `1fdac9b9`；委派/子会话的真机结论同理）。feat/backend 的语料是另一套
（2026-09-11 时为 11 个会话、最大 35 事件）。

**切换步骤**（任选一侧，注意一次只能有一个进程占 `:8000`）：

```bash
# 1) 停掉当前占用者
PID=$(netstat -ano | grep LISTENING | grep ":8000" | head -1 | awk '{print $NF}'); taskkill //F //PID $PID

# 2A) 换 main 后端（大语料：70+ 会话，含 410 事件 child）
cd /d/intelligence-agent && uv run uvicorn agent_harness.web.app:create_app --factory --host 127.0.0.1 --port 8000

# 2B) 换回本分支后端（**验当前分支代码时用这个**）
cd /d/intelligence-agent-backend && uv run uvicorn agent_harness.web.app:create_app --factory --host 127.0.0.1 --port 8000
```

⚠️ `.env` 改动与两个后端的差异**都不会进 Git**（`.env` 本地文件），所以**换后端后必须重新查
§2 的 `/api/capabilities`**，不能凭记忆假设能力集。

## 5. 验收前的三条检查

1. `:8000` 上跑的是**你想验的那个分支**吗？（验 feat/backend → 用 `D:\intelligence-agent-backend`）
2. `/api/capabilities` 是否符合 §2 期望？不符合就先修 `.env` 再启动，别把「配置缺能力」记成产品缺陷。
3. 会话语料够不够触发你要验的条件？（`加载更早 N 条` 需 >200 事件；委派需 `multiagent`；
   Trace 三件套需 Langfuse 启用——本部署未配，因此那三项**恒不渲染**且属正确行为。）

## 6. 相关记录

- `docs/FRONTEND_ISSUES_LOG.md` 第六轮：`OBS-016`（委派/子会话为配置不可达的完整证据链）、
  `BUG-008`（前端修复）、`BUG-009`（后端 P1：非流式 run 的回退在带闸时必崩）。
- `docs/ACCEPTANCE_CONTROL_INVENTORY.md`：110 控件清单（含各自的渲染条件）。
