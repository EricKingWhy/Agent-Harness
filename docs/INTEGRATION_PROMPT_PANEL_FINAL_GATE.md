# 集成提示词：整批工作区面板（后端 artifact #185/#192/#186 后端半 + 前端 #182/#183/#184/#189/#190/#186）→ `main`

**一句话**：本批让 artifact **真的能用**（写入接线 + 读接口 + 界面可见），并落地面板
的一批新面与 Inspector 升级。**代码完成、两侧门禁全绿、未合入 main、未 push**。

两个工作区：

| 工作区 | 分支 | 交付 commit（末条） |
| --- | --- | --- |
| `D:\intelligence-agent-backend` | `feat/backend` | `af61acd`（+ `228ed8c` 修复） |
| `D:\intelligence-agent-frontend` | `feat/frontend` | `09afbe5`（+ 本文件 commit） |

---

## 1. 合并顺序（**必须**）

```text
feat/backend  → main     ← 先
feat/frontend → main     ← 后
```

理由：`GET /api/sessions/{sid}/artifacts/{aid}` **只存在于 `feat/backend`**
（`#185`）。反序合并时前端的「查看完整内容」在 `main` 上会 404。

冒烟命令（合并后，在 `D:\intelligence-agent`）：

```bash
git -C D:/intelligence-agent fetch origin --prune
git -C D:/intelligence-agent diff --stat main...origin/feat/backend
git -C D:/intelligence-agent diff --stat main...origin/feat/frontend
```

（`feat/*` 未 push，若要从远端合先 push；按 §14.6「先回后正」也可本地直接合。）

---

## 2. 交付内容

### 2.1 后端（`feat/backend`）

| 票 | 内容 |
| --- | --- |
| #185 | `GET /api/sessions/{sid}/artifacts/{aid}`（422/404/503/200 语义 + `ARTIFACT_ID_PATTERN` 收敛 + MinIO 不再伪造元数据） |
| #192 | `LocalArtifactStore`（spec 06 §3 的**默认** Provider，此前从未实装）+ 写入接线 **S3 → MinIO → Local** + 修 MinIO"只读半截"接线；硬删会话连带丢弃本地 artifact 目录 |
| #186 后端半 | 外置摘要 marker **点名本 store 配对的读回工具**（S3 → `inspect_artifact`，MinIO/Local → `read_artifact`），由装配层从选择器实例化出的那个工具取名 |
| 总门禁 | 可选依赖缺失 **fail-open**（不变量 21：配好对象存储但没装 `[artifact]` extra 的部署，此前**每次建会话 500**）+ `inspect()` 信封四份收敛为一份 |

门禁：`ruff check src tests` 通过；全量 pytest **2206 passed / 10 skipped / 42 deselected / 0 failed**。

### 2.2 前端（`feat/frontend`）

| 票 | 内容 |
| --- | --- |
| #182 | 删 Split/Preview；中心列 tab 集 = Chat + **能力声明为 true 且已实现**的面（`lib/capabilities.ts`） |
| #183 | Inspector 清单+详情同框（peek 升级链：Esc/Space/↑↓/钉住/整页/拖宽） |
| #184 | Inspector 补 PERMISSION 段 |
| #189 | 中心列「文件/改动」面（会话改动文件清单 + 逐文件 net diff，同一路径聚合） |
| #190 | 中心列「输出」面（Terminal 改名；只读如实，无输入类元素） |
| #186 前端半 | artifact 内容可见 + 就地展开（`ArtifactViewer`）+ marker 两种拼写都认 + 元数据缺失不伪造 |
| 总门禁 | Inspector「Output」段取数反转修复 / 解析不再伪造 0 行 / 重试存活门 / 命令判据收敛 / legacy CSS token 换回原始 token |

门禁：`tsc -b` 干净 · vitest **813 passed / 48 files** · oxlint **0 error**（44 warnings）·
playwright `--workers=2` **302 passed** · `vite build` 绿。

---

## 3. ⚠ 合并前必须知道的一件事：两个新面在真实部署里**看不到**（issue #193）

`centerTabs` 的闸门是"**能力声明为 true** **且** 已实现"。实现侧两半都在，但**声明侧
永远不为 true**：

- `src/agent_harness/web/app.py:918-927`：descriptor 未声明 `surfaces` ⇒
  `changes` / `terminal` / `artifacts` 一律 **false**；
- `src/agent_harness/capability/wiring.py` 的 7 个 descriptor
  （memory/skills/mcp/knowledge/multiagent/websearch/ticker）**没有一个填 `surfaces`**；
- `ProviderConfig`（`capability/config.py:13-19`）是 `strict` 模型、无该字段 ⇒ 配置路径也填不进。

⇒ 任何真实部署 `GET /api/capabilities` 都返回 `changes:false, terminal:false`，
`centerTabs` = `['Chat']`。e2e 之所以看得到，是因为它们**注入了 `changes/terminal: true`**
（后端发不出这种载荷）。

**这不是本批的实现缺陷**（票面 AC 只要求"声明为真 → 出现"，已逐条满足），缺的是
**声明侧**，原属 `PHASE_STATUS.md` 记为延后到 **Phase 6** 的 "capability surfaces 装配"。
已开票 **#193**（含两个候选方向 + 验收建议）。

⇒ **合并本批 ≠ 用户能看见「文件/改动」与「输出」。** 集成后如需可见，先做 #193。

---

## 4. 合并后建议冒烟

### 4.1 后端 / artifact（#185 + #192 + #186）

1. 不配任何 `ARTIFACT_*` / `MINIO_*` / `S3_*`（默认即 Local）建会话；
2. 触发一次 >2000 字符的大输出 → 会话里应出现 `artifact/externalized` 事件，
   工具结果被换成"摘要 + `use read_artifact(<id>) to view]`"；
3. `GET /api/sessions/{sid}/artifacts/{id}` → **200** 且内容逐字节完整；
4. 显式 `ARTIFACT_DIR=""` → 建会话**照常成功**（不外置），读接口 **503**；
   对象存储**半配置**（配 endpoint 不配 bucket）→ 读接口 **503**（不静默降级到本地）；
5. 硬删会话 → `.agent/artifacts/<sid>/` 目录消失；
6. 配了对象存储但**没装** `[artifact]` extra → 建会话**照常成功**（这是总门禁修的 P1）。

### 4.2 前端

1. 起 `web` + 真后端，打开一个真会话：Inspector 五个 tab、peek 升级链
   （Esc/Space/↑↓/钉住/整页/拖宽）逐项点一遍；
2. 触发一次被截断的大输出 → 工具卡 L2 与 Inspector 都出现「查看完整内容」，
   点开能读到完整切片（**合并顺序错了这里就是 404**）；
3. 中心列只应有 `Chat`（原因见 §3——这是当前事实，不是故障）；
4. 暗/亮两色各看一遍新增面（本批新增 CSS 已全部用原始 token，无 §15 双份同步问题）。

---

## 5. 已知未决 / 移交项

| 项 | 状态 |
| --- | --- |
| **#193** 后端声明 `surfaces`（两新面对用户可见的前提） | **OPEN**，本批不做（Phase 6 范畴） |
| #183 AC9 残余：非命令工具的 Output 段仍是"树 vs 文本"两种呈现 | 登记在 tracker 第二十一轮，未改（理由见该节） |
| #173 spec 03 §3 事件表与实现对齐 | OPEN（另一批工作，与本批无关） |
| #191 后端开放工作区文件读取（列文件/读内容/git 状态） | OPEN，票面写明"本批只登记不实现" |
| #181 窄屏 ⋯ 菜单依赖 hover，触摸设备可能不可达 | OPEN（前端，另票） |
| #171 会话归档 | OPEN（另票） |

---

## 6. 关单状态

| 票 | 状态 | 说明 |
| --- | --- | --- |
| #185 | 已关 | 后端，已合入 main 的历史批次 |
| #192 | 已关 | 后端，代码完成 + 门禁绿（本批） |
| #183 / #186 / #189 | 见 GitHub comment | 代码完成 + 门禁绿，**未合入 main**；关单 comment 写明分支与 commit 及集成方 |
| #193 | **OPEN** | 本批新开，声明侧缺口 |

`docs/PHASE_STATUS.md`（单一事实源）已在 `feat/backend` 侧追加后端总门禁记录；
前端侧的记录在 `feat/frontend` 的 `docs/SDD_TICKET_TRACKER.md` 第二十一轮，
**合并后请由集成方在 `main` 上补一条 PHASE_STATUS 汇总行**。
