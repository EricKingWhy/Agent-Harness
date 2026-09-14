# 集成提示词：#186 artifact 内容可见 + 就地展开（跨端）→ `main`

**一句话**：网页端终于能看到 artifact 里的内容了——Artifacts 清单可就地展开，被归档/截断的
那一处（diff、命令输出）也有同一个就地展开入口；顺带修掉一处**两端对不上**的 marker 缺陷
（正是它让"归档"这条路径在生产里一直是死的）。

工作区分两个：后端 `D:\intelligence-agent-backend`（`feat/backend`），
前端 `D:\intelligence-agent-frontend`（`feat/frontend`）。

---

## 0. ⚠ 集成顺序（先看这条）

`#185` 的内容路由 `GET /api/sessions/{sid}/artifacts/{aid}` **只在 `feat/backend` 上，
`main` 上还没有**（main 的最新提交自己写着"backend 在途 #185 不并入"）。所以必须：

```text
feat/backend  → main     ← 先合：#185 路由 + #192 外置链路 + marker 配对修复
feat/frontend → main     ← 后合：#186 消费侧（内容面板/就地展开/marker 解析）
```

**顺序反了的后果**：前端的"查看内容"按钮会 404（端点不存在）。那不是前端 bug。
按 §14.9"一次只合一条分支"：backend 合完并验证后，重新分析 frontend。

---

## 1. 本轮 commit

| 分支 | commit | 内容 |
| --- | --- | --- |
| `feat/backend` | `d925899` | 外置摘要点名**与本 store 配对**的读回工具（AC4 的后端半） |
| `feat/frontend` | `169251c` | marker 两个名字都认 + 工具名原样透传（AC4 的前端半） |
| `feat/frontend` | `179d46a` | 内容可见 + 就地展开 + 元数据不再伪造（AC1/AC2/AC5/AC6/AC7） |
| `feat/frontend` | （随后一条） | tracker § 第二十轮 + 本提示词 |

批 2 审查的修复 `868e05e`（含 AC3：diff 收敛为唯一渲染器）也在这条分支上，**未合入 main**。

---

## 2. 为什么 AC4 是跨端的（不是"文案偏好"）

后端摘要在 `tooling/overflow.py` 里写死 `use read_artifact(<id>)`，前端
`lib/toolShapes.ts` 只认 `use inspect_artifact\(...\)`。**两端都对不上**：

```text
parseArtifactMarker → null ⇒ diff.archived / artifactId 永不置上
⇒ DiffBlock 的归档占位、#189 面板的"统计不可得" 在生产里全是死路径
```

（这套 UI 此前只在 e2e 里"活着"——fixture 用的是前端自己那个拼法。）

**根因不只是文案**：读回工具是**与 store 成对**的，配对表在
`storage/artifact_select.py`：

```text
S3    → inspect_artifact
MinIO → read_artifact
Local → read_artifact     （Local 是 spec 06 §3 的默认 Provider）
```

所以"统一成一个名字"是**错的**——S3 部署上摘要会指向一个没注册的工具名。正确做法是
**让摘要点名它自己那个部署配对的工具**，前端两个名字都认、并把名字**原样**带下去：

- 后端：`ArtifactOverflowHandler(read_tool_name=...)`，`assembly.py` 从选择器**实例化出的
  那个工具**取 `.name`（不在 assembly 再写字面量，否则配对知识有了第二处）。
- 前端：`parseArtifactMarker` 返回 `{artifactId, toolName}`；`toolName` 经
  projection → `tool.diff.artifactTool` → `changedFiles` → `DiffBlock` 透传；归档提示与
  复制按钮用 marker 里的名字（前端不知道、也不该猜这个部署用哪个 store）。

回归守卫：`tests/test_assembly.py` 三个 Provider 分支各断言摘要点名的工具名；S3 那条已在
本地做**变异验证**（把 marker 改回写死 `read_artifact` → 用例失败）。

---

## 3. 改了什么（前端）

| 文件 | 改动 |
| --- | --- |
| `web/src/lib/api.ts` | `getArtifactContent()` + `ArtifactContentError`（`gone`/`no-storage`/`error`）+ `ArtifactQueryError` + 响应形状校验 |
| `web/src/components/ArtifactViewer.tsx`（新） | `ArtifactContentView`（纯渲染三态）+ `ArtifactViewer`（取数 + 折叠） |
| `web/src/components/DiffBlock.tsx` | 归档态加就地展开（`sessionId` 缺席则不给入口）；提示与复制用 marker 的工具名 |
| `web/src/components/ToolCard.tsx` | L2 内联同一个展开器；判据是投影的 `tool.artifact`；归档 diff 处抑制重复入口 |
| `web/src/components/StepDetail.tsx` | Artifacts 清单接内容面板；元数据缺失显示"未知"；ChangesTab 转 `sessionId` |
| `web/src/components/Conversation.tsx` | `sessionId` 显式透传到 `ChainRenderCtx` → ToolCard |
| `web/src/components/ChangesPanel.tsx`, `web/src/App.tsx` | `sessionId` 转发 |
| `web/src/lib/projection.ts` | marker 两个名字都认并带下工具名；元数据缺失留 `null`（不再填默认值） |
| `web/src/types.ts` | `ArtifactSlice`/`ArtifactSliceLine`；`ArtifactRef` 元数据改可空；`diff.artifactTool` |
| `web/src/styles/app.css` | `.artifact-*` 一套（两处入口共用，只定义一次） |
| `web/e2e/fixtures.ts` | 内容端点 mock（此前 e2e 对 artifact 零覆盖） |

**零新契约**：前端只消费 `#185` 已定义的端点，没有新增/修改任何后端契约。

---

## 4. 门禁（全绿）

```text
# 后端（D:\intelligence-agent-backend）
.\.venv\Scripts\python.exe -m ruff check src tests   # All checks passed
.\.venv\Scripts\python.exe -m pytest -q             # 2203 passed / 10 skipped / 42 deselected

# 前端（D:\intelligence-agent-frontend\web）
npx tsc -b                     # 0
npx vitest run                 # 809 passed
npx oxlint                     # 0 error / 44 warnings（= 基线）
npx playwright test --workers=2  # 302 passed
npx vite build                 # 0
```

**抖动留痕**：全量 e2e 里 `r-project-groups.spec.ts` 的 AC4（项目内重排）偶发失败
（本批见过 2 次）。单独跑该 spec 22/22 通过，重跑全量也通过——已知的 `--workers=2`
资源竞争型抖动，与本次改动无关（改的是 Inspector 内容面与工具卡）。未顺手改该 spec。

---

## 5. 集成时要注意

- **顺序**：见 §0。前端依赖后端先进 main。
- **一处用户可见的变化**：归档 diff 与命令输出外置处现在多一个"查看完整内容"入口；
  Artifacts 清单的元数据缺失时显示"未知"（此前会显示伪造的 `0 B` /
  `application/octet-stream`）。
- **真机联调建议**：本 worktree 无可用后端进程，e2e 全程 mock，内容端点形状以
  `web/app.py:1229-1330` 的 `ArtifactSlice.model_dump()` 为准。合并后在
  `D:\intelligence-agent` 起完整项目时，建议手点一次"外置 diff → 查看完整内容"。
- **未做的相邻项（Scope Lock）**：`tabCounts.terminal` 与 `TerminalTab` 行判据不一致
  （第十八轮留痕）、旧代码里的 legacy CSS 别名用法——都不是本票引入，未动。

---

## 6. 关单状态

**#186 未关单**：代码完成（跨端两半都已 commit）但**尚未合入 `main`**。按 §14.12，
关单 comment 需写明分支与 commit——留给集成 AI 合并后关闭，或由本 AI 在总门禁通过后关。
（`#185` 已 CLOSED；`#183`/`#189` 亦未关单，同样等合并。）
