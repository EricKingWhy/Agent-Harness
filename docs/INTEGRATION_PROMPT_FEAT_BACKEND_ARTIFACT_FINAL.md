# 集成提示词：`feat/backend` 后端 artifact 批次（#185 / #192 / #186 后端半）→ `main`

**一句话**：这条分支让 artifact **真的能用**——补上规格 06 §3 要求的默认 Provider
`LocalArtifactStore`、把外置写入接成 S3 → MinIO → Local、把**读**能力暴露成 HTTP 接口，
并让外置摘要点名"本 store 配对的读回工具"。此后没有对象存储的部署也能外置产物，
前端 #186 的"查看完整内容"才有东西可看。

工作区：`D:\intelligence-agent-backend`，分支 `feat/backend`。
**只动后端**（`src/` + `tests/` + `docs/`），`web/**` 零改动。

---

## 1. 先看这一条：**合并顺序**

`#185` 的读接口路由 `GET /api/sessions/{session_id}/artifacts/{artifact_id}` **只存在于本分支**。
前端的"查看完整内容"依赖它。因此：

```text
feat/backend → main   （先）
feat/frontend → main  （后）
```

反序合并会让前端在 `main` 上打 404。

---

## 2. 本轮 commit（`0296956` 之后）

| commit | 内容 |
| --- | --- |
| `a38767d` | #185 读接口 + 存储层校验对齐（AC3/AC4） |
| `2c658a2` | #185 AC4：MinIO `load` 不再伪造元数据（缺啥返回 `None`） |
| `b31b9f3` | #192 `LocalArtifactStore` + 写入接线 S3→MinIO→Local |
| `0296956` | #192 进度登记 + `INTEGRATION_PROMPT_ARTIFACT_192.md` |
| `9086642` | 批 1 审查修复：选择器收敛为一份 + 补两条端到端证据 |
| `21e6f55` | 批 1 审查记录 + ADR-0029 D6/Non-Goals 与落地对齐 |
| `d925899` | #186 AC4：外置摘要点名与本 store 配对的读回工具 |
| `228ed8c` | **总门禁**修复：可选依赖缺失 fail-open + `inspect` 收敛为一份 |

---

## 3. 交付内容

### 3.1 `#185` 读接口（AC1–AC8）

- 新路由 `GET /api/sessions/{sid}/artifacts/{aid}`，把模型侧唯一读入口
  `ArtifactStore.inspect` 暴露给 Web（spec `05_BACKEND_SDD.md:159-163` 的
  "expose lazy-fetch endpoint"）。
- 状态码：**422** 形态非法（`session_id`/`artifact_id`/行号 <1）；**404** 会话不存在
  或该 artifact 不在本会话命名空间（**别的会话的产物同样走 404**：`artifact_id` 是内容哈希、
  跨会话可重复，把"不存在"与"存在但不可读"分开会让归属变成可探测信息）；**503** 本部署
  没有可读存储；**200** 切片 + 如实的 `truncated` / `total_lines`。
- **AC3**：`ARTIFACT_ID_PATTERN` 抽到 `storage/artifact.py`，S3 / MinIO / web 共用——
  此前 S3 内联正则、**MinIO 完全不校验**，畸形 id 会以 SDK 异常形状外泄；MinIO 顺带补齐
  `NoSuchKey` / `UnicodeDecodeError` → `KeyError`（此前真实 MinIO 部署下"产物不存在"是 500 不是 404）。
- **AC4**：`Artifact` 的 `source_tool` / `tool_call_id` / `created_at` 改 `str | None = None`。
  MinIO `save` 从不持久化这三项、`load` 却填 `""`——那是假值。爆炸半径已核对：生产代码
  无人读 `load` 得到的这三个字段，本路由只返回 `ArtifactSlice`，对外契约不变。

### 3.2 `#192` 写入侧（AC1–AC10）

- 新增 `LocalArtifactStore`（`storage/local_artifact.py`）：落盘
  `<artifact_dir>/<session_id>/<artifact_id>`，与对象存储键 `{sid}/{aid}` 逐段同构；
  旁挂元数据走 suffix 文件（内容必须逐字节等于模型产出，否则 `compute_artifact_id` 对不上）。
- 新 setting `artifact_dir`，默认 `.agent/artifacts`（`.gitignore` 已整目录忽略 `.agent/`）。
- 写入接线改为 **S3 → MinIO → Local**；修掉 MinIO 分支"只有读工具、没有写入者"的半截接线。
- 硬删会话连带丢弃本地 artifact 目录（窄方法 `discard_local_artifacts`，**不读映射**、
  只删自拼路径 —— ADR-0029 D2）。
- **不做**：自动 TTL / 体积清理 / 远端对象删除（ADR-0004 + ADR-0029 Non-Goals）。

### 3.3 `#186` 后端半（AC4）

外置摘要 marker 从写死的 `inspect_artifact` 改为**点名本 store 配对的读回工具**
（S3 → `inspect_artifact`，MinIO / Local → `read_artifact`，配对表在 `storage/artifact_select.py`），
`ArtifactOverflowHandler` 由装配层注入 `read_tool_name`。前端认两种拼写并按 marker 透传。

---

## 4. 门禁证据

| 项 | 结果 |
| --- | --- |
| `ruff check src tests` | All checks passed |
| 全量 `pytest` | **2206 passed / 10 skipped / 42 deselected / 0 failed**（190.74s） |
| 关键负向用例 | `test_missing_artifact_extra_does_not_break_session_creation` 等 3 条 fail-open 用例，**变异验证**过（还原捕获面 → 2 红） |
| 跨会话隔离 | `test_local_artifact_of_another_session_is_404`（默认 Provider 上真隔离） |
| 端到端落盘链路 | `test_runtime_overflow_writes_a_readable_artifact`（真 runtime → 磁盘逐字节原件 → HTTP 200 读回） |

**已知门禁现象（非本票引入，仅登记）**：`docs/FRONTEND_ISSUES_LOG.md` OBS-11.1 ——
同一份代码连跑多次时，偶发一次 22 个 web 用例（`test_web_stream` / `test_web_ws_relay` 等）
间歇失败，聚焦重跑与全量重跑均全绿。

---

## 5. 集成前请注意

1. **顺序**：本节 §1，backend 先。
2. `artifact_dir` 默认 `.agent/artifacts` 是**相对路径**，相对 CWD —— 与
   `workspace_dir` 同族；不需要在 `main` 的 `.env` 里加任何键即生效（这是 #192 的
   目的：没有对象存储的部署也能外置）。如果要显式关掉本地落盘，把 `ARTIFACT_DIR` 置空
   （已测试：建会话照常成功，只是不外置）。
3. **本分支不动 `docs/PHASE_STATUS.md` 以外的共享文件**，未触碰 `web/**`，
   与 `feat/frontend` 无同文件冲突预期。
4. 合并后建议冒烟：建会话 → 触发一次大输出（>2000 字符）→ 确认
   `GET .../artifacts/{id}` 返回 200 且内容完整 → 硬删会话 → 确认
   `.agent/artifacts/<sid>/` 目录消失。
