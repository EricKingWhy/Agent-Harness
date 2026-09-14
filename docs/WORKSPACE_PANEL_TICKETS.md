# Tickets — Workspace Panel

> 母 PRD：`docs/WORKSPACE_PANEL_PRD.md`。
> 工作区：**前端票在 `D:\intelligence-agent-frontend`（feat/frontend）**；**后端票在 `D:\intelligence-agent-backend`（feat/backend）**。
> 门禁：前端 `cd web && npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build`；后端 `uv run ruff check . && uv run pytest -q`。
> 建议顺序：**#185 → #182 → #190 → #184 → #183 → #189 → #186**。
> （原写的 `#185 → #190 → … → #182 → …` 与下面的依赖图矛盾：**#190 / #189 都依赖 #182**
> 的能力显隐骨架——先做内容面会得到一个"没有 tab 可挂"的面板，或先把 tab 条写一遍再被
> #182 取代。以依赖图为准。）

---

## #182 · 删 Split/Preview + 能力声明显隐骨架

- **工作区**：前端 ｜ **依赖**：无 ｜ **PRD**：§2、§3.2
- **改动面**：`web/src/App.tsx`、`web/src/styles/app.css`、`web/src/lib/`（capabilities 拉取与降级）、`web/e2e/workspace-modes.spec.ts`

**AC**

1. `Split` / `Preview` 及 `reserved` / `RESERVED_MODE_NOTE` 残留**全部删除**；`workspace-modes.spec.ts` 改写为"不再存在禁用占位"的守卫。
2. 中心列 tab 集 = `Chat`（**恒存在**）+ 能力 `surfaces` 为 true 的面。
3. 能力数据不可得时降级为 PRD 缺省（`chat`+`timeline`）；**Chat 永不消失**。
4. 声明为 false 的面**不渲染**；面的名称与声明键的对应关系在代码里**显式登记**（禁止"声明 terminal、却渲染成 Terminal 面板"这类名不符实）。
5. `aria-selected` 如实、可 Tab 到达、方向键可在 tab 间移动。
6. 新增 e2e：capabilities mock 两组（真/假）各断言 tab 集**恰好**符合声明。
   - **骨架期口径（交付时如实记）**：今天没有任何非 Chat 的面有实现，所以"符合声明"的
     可观测形式是「声明为真**且有实现** → 出现」。用例把真/假两组并排断言，差别只在
     `implemented` 标记；**完整的"声明为真 → 出现"必须等 #189 / #190**（它们落地时
     要翻转 `e2e/workspace-modes.spec.ts` 的骨架期守卫，票面已记）。
   - 另有一条**不能靠 tab 集回答**的断言：三种 mock（空目录 / 声明为真 / 端点 404）
     渲染出的 tab 集都是 `['Chat']`，所以"前端压根没调这个端点"会让整套用例照绿——
     `onCapabilitiesGet` 计数把"端点确实被消费且没有请求循环"钉住。
7. 不改三区几何（`app.css:35` 的 `240px | 1fr | 320px`）与 Conversation/Composer 行为。

---

## #183 · Inspector 升级：清单 + 详情 + peek 升级链

- **工作区**：前端 ｜ **依赖**：无 ｜ **PRD**：§3.0、§3.1
- **改动面**：`web/src/App.tsx`、`web/src/components/StepDetail.tsx`、`web/src/styles/app.css`、`web/e2e/`

**AC**

1. 清单内移动选中项时详情**实时跟随**（不重新挂载、不丢滚动位置）。
2. 键盘：`↑`/`↓` 移动；`Esc` 关闭（**不卸载**）；`Space` 快按=保持打开 / 按住=松手关闭。
3. 鼠标点击即选中即预览（默认可用，**不做键盘唯一**）。
4. **钉住**：钉住后切换会话/选中不自动收起；钉住是视图状态，**不持久化**（不变量 #22）。
5. **整页打开**：长 trace / 大 diff 可整页宽读并可退回；入口为面板按钮 + 命令面板项（键位实现时定）。
6. 可拖宽 320→480，**不持久化**，不得压垮中心列最小宽度。
7. 钉住/整页/关闭均键盘可达且 `aria-*` 如实。
8. 新增 e2e：↑↓ / Esc / Space 三条 + 钉住跨会话 + 整页往返 + 拖宽不持久化。
9. 不得出现同一数据在 Inspector 与中心列的**两份独立渲染**。

---

## #184 · 补 Inspector 的 PERMISSION 段

- **工作区**：前端 ｜ **依赖**：无 ｜ **PRD**：§3.6
- **改动面**：`web/src/components/StepDetail.tsx`、`web/src/lib/projection.ts`（如需派生）、`web/src/styles/app.css`

**AC**

1. PERMISSION 段显示：权限档 + **待审批请求**（`tool/approval-requested`）+ **裁决结果**（`permission/resolved`）。
2. 无待审批时**如实显示"无待审批"**，而不是整段消失。
3. **不新增 ARTIFACTS run 级段**（由既有清单 tab 承担，见 #186）；CHECKPOINT 保持诚实占位——不得为"填满八段"伪造或隐藏。
4. 不可得数据 → `—` / `Unavailable` / 省略，不得填 0 或占位数字。
5. 新增 vitest（projection 派生）+ 至少一条 e2e：有待审批时该段出现且能进审批面。
6. 不改 `POST /approve` 契约语义。

---

## #185 · 后端：artifact 内容读取 HTTP 接口

- **工作区**：**后端** ｜ **依赖**：无 ｜ **PRD**：§3.4、§6
- **改动面**：`src/agent_harness/web/app.py`、`src/agent_harness/storage/minio_artifact.py`、`tests/web/`（或 `tests/test_web_api.py`）
- **背景（实测）**：产物内容**没有对外读取路径**（只有模型工具 `inspect_artifact`/`read_artifact` 能读）；`ArtifactStore.inspect(artifact_id, *, start_line, end_line, keyword, max_lines, max_chars_per_line) -> ArtifactSlice` 是唯一读入口（`storage/artifact.py:75-90`，三实现签名一致）；key = `{session_id}/{artifact_id}`；**`artifact_id` 是内容哈希** `sha256(content)[:16]`（`storage/artifact.py:93-95`）→ 跨会话可重复。

**AC**

1. 新增只读路由 `GET /api/sessions/{session_id}/artifacts/{artifact_id}`，复用 `ArtifactStore.inspect`；支持可选 `start_line`/`end_line`/`keyword` 与响应体积上限；**JSON 切片**响应（含是否截断、总行数等如实标记）——用户已定不做字节流。
2. **归属校验**：用 URL 的 `session_id` 构造/校验 store 命名空间；**非本会话的 artifact_id 不可读**（内容哈希可跨会话重复，硬要求）；给出 404/403 分层语义与理由（参照 `web/app.py:1196-1226` + `session/service.py:780-828`）。
3. **穿越防御**：`session_id` 走 `validate_session_id`（`session/service.py:131-144`）→ 422；**`artifact_id` 形态校验必须补齐**——`MinioArtifactStore.load` 当前无校验（`storage/minio_artifact.py:103-108`），S3 有 `[0-9a-f]{16}`（`s3_artifact.py:72-73`）；两 provider 行为必须一致并有测试。
4. **元数据如实**：MinIO 不持久化 `source_tool`/`tool_call_id`/`created_at`（`minio_artifact.py:118-127`），S3 有 → 缺失即 `null`/省略，**不得**伪造成空串或默认值。
5. 状态码：artifact 不存在→404；session 不存在→404；`session_id` 非法→422；内部异常不得原样抛出（复用 `http_error`，`web/domain_errors.py:248-258`）。
6. **路由注册顺序**：必须在 `mount_static` 之前（`web/app.py:1448`），否则被静态吞掉。
7. 测试：跨会话被拒、非法 session_id 422、非法 artifact_id 422、不存在 404、正常读取、超限截断、keyword 过滤；三实现校验层一致。
8. 不新增 SessionEvent、不改 Tool 执行路径、不改 `ArtifactStore` 既有语义。

---

## #186 · Artifacts 可读 + 就地展开 + diff 单一渲染 + marker 文案统一

- **工作区**：前端 ｜ **依赖**：**#185** ｜ **PRD**：§3.3、§3.4
- **改动面**：`web/src/components/StepDetail.tsx`、`web/src/components/DiffBlock.tsx`、`web/src/lib/toolShapes.ts`、`web/src/lib/projection.ts`、`web/src/types.ts`
- **背景**：`ArtifactsTab` 只渲染 id/size/mime 且不可点（`StepDetail.tsx:756-789`）；`DiffBlock` archived 态只给复制按钮（`DiffBlock.tsx:13-28`），**没有真实请求**；Inspector `ChangesTab` 自己内联 `.diff-cols`（`StepDetail.tsx:699-708`）不复用 `DiffBlock`；后端外置 marker 是 `use read_artifact(<id>)`（`tooling/overflow.py:115-123`）而前端正则抓 `inspect_artifact\(([^)]+)\)`（`lib/toolShapes.ts:105`）——**两端不一致**。

**AC**

1. **Artifacts 清单保留并可读**（用户决策 C）：调 #185 接口打开内容；加载/失败/不可得三态如实，失败显示后端 detail 原文。
2. **就地展开**：在被截断的那一处（工具卡 / diff）提供**真实可用**的"查看完整内容"入口；与清单位于**同一渲染器**，不得各写一套。
3. **diff 收敛为唯一渲染器**：`ChangesTab` 内联 `.diff-cols` 改为调用 `DiffBlock`，两处行为/视觉一致。
4. **统一 marker 文案**（选定一个方向、两端同步 + 加测试），确保外置 diff 的 `artifactId` 能被提取。
5. `types.ts` 补齐内容接口所需字段（内容、截断标记、元数据可空）。
6. 测试：`StepDetail.test.tsx` / `projection.test.ts` 补内容面板与 marker 提取；**e2e 当前对 artifact/diff 零覆盖**，至少新增一条"外置 diff → 就地展开 → 可见"的端到端用例。
7. 内容面板不得成为"第二真相"：数据来自接口/事件投影，不本地另存可变副本。

---

## #189 · 中心列「文件/改动」面（本次会话改动文件 + 逐文件 diff）

- **工作区**：前端 ｜ **依赖**：**#182**（tab 骨架） ｜ **PRD**：§3.3
- **改动面**：`web/src/`（新组件 + projection 派生）、`web/src/styles/app.css`、`web/e2e/`
- **数据来源（无需新后端接口）**：`write`/`edit`/`apply_patch` 推导的 `changed_files`（`multiagent/provider.py:58-87`）+ `ToolResult.data.{before,after}`（`tools/_diff_data.py`）+ operation ledger（`storage/sqlite.py:45,234`）

**AC**

1. **左侧改动文件列表**（路径 + 改动统计 `+N -M`）、**右侧选中文件的逐文件 diff**；形态对齐 Claude Code 桌面版 / VS Code Changes panel（PRD §3.0）。
2. **同一文件多次修改合并为一行**（按文件聚合，按时间顺序展示各次改动）——不得一个文件出现多行。
3. 范围**限定本次会话**：不做工作区全量浏览、不读当前文件内容、不做 git 状态（属 #191）。
4. **只读**：不提供编辑入口。
5. 长 diff **就地折叠/截断**，不新开导航面；截断处的"查看完整内容"走 #186 的同一渲染器。
6. 无改动时如实显示"本会话未改动任何文件"。
7. 数据必须是事件的投影，不得成为第二真相。
8. e2e：两次改动同一文件 → 断言只有一行且统计正确；点文件名 → diff 可见；无改动 → 空态文案逐字。
   - **落地时必须同时改两处**（只改一处会得到一个空面板）：`lib/capabilities.ts` 登记表的
     `implemented: true`，以及在 `App.tsx` 里为 `changes` 渲染面板内容；并翻转
     `e2e/workspace-modes.spec.ts` 的"骨架期守卫"（见 #182 AC6 与 #190 AC6）。

---

## #190 · 中心列「输出」面（Terminal 改名，只读如实）

- **工作区**：前端 ｜ **依赖**：**#182** ｜ **PRD**：§3.5
- **改动面**：`web/src/components/StepDetail.tsx`（`TerminalTab` 聚合逻辑复用/抽出）、`web/src/`（新面）、`web/e2e/`

**AC**

1. 面命名为**「输出」**（不叫 Terminal），面内**明示**"只读：本项目命令为一次性执行，无交互终端"。
2. 聚合本会话命令输出（复用既有 `TerminalTab` 聚合逻辑）；支持按工具调用分组与复制。
3. 长输出就地折叠；截断处理与 #186 同策略。
4. 能力声明为 false 时**不渲染**（非编码会话）。
5. **不得**出现任何暗示可输入的元素（无输入框、无"运行"按钮、无光标）。
6. e2e：有输出时出现且断言不存在输入类元素；能力为假时不渲染。
   - **落地时必须同时改两处**（只改一处会得到一个空面板）：`lib/capabilities.ts` 登记表的
     `implemented: true`，以及在 `App.tsx` 里为 `terminal` 渲染面板内容。
   - **并翻转 `e2e/workspace-modes.spec.ts` 的"骨架期守卫"**：该用例今天断言"声明为真也
     不渲染"（因为面还没实现），本票落地后要改成"出现"——#182 交付时已把这一条记在这里。
7. 抽出 `TerminalTab` 的聚合逻辑时不得改变 Inspector 侧既有行为（#183 会继续用它）。

---

## #191 · 【后续，本批不做】后端开放工作区文件读取

- **工作区**：后端 ｜ **依赖**：— ｜ **PRD**：§3.3 AC3、§5
- **说明**：本批**只登记不实现**（用户决策：本批只做"本次会话改动过的文件"）。当前状况：后端**没有任何"列文件/读文件内容"的路由**——唯一相关是 `GET /api/host/dirs`，只列一层子目录、只读、明示"不读文件内容、不做搜索/通配、无写语义"（`web/host_dirs.py:9-10,147,165`）；但工具层已具备 `read`（`tools/read.py:42`）、`glob`（`tools/glob.py:31`）、`grep`（`tools/grep.py:45`）、`git_status`/`git_diff`（`tools/git.py:36+`）。

**AC（实现时细化）**

1. 列出工作区文件（受 workspace 边界约束，防穿越、防越界读取）。
2. 读取单个文件内容（大小上限、二进制/编码处理如实）。
3. git 状态 / 单文件 diff（复用 `git_status`/`git_diff` 的既有语义，别再写一套）。
4. 访问控制与 workspace 边界是本票**主要风险面**（AGENTS.md §4.3）。

---

## 依赖图

```
#185(后端 artifact) ──→ #186(可读 + 就地展开 + 收敛)
#182(骨架/能力声明) ──→ #189(文件/改动面)
                    └─→ #190(输出面)
#183 / #184 独立（都动 StepDetail，与 #182/#189/#190 串行更稳）
#191 = 后续票（本批不做）
```
