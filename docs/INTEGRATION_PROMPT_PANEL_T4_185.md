# 集成提示词：#185 外置 artifact 内容只读接口（面板 T4）→ `main`

**一句话**：#185 让 Web **第一次有了读产物内容的路径**——此前只有模型工具
（`inspect_artifact` / `read_artifact`）能读，前端拿不到，所以界面上永远看不到
artifact 里有东西；spec `05_BACKEND_SDD.md:159-163` 的 "expose lazy-fetch endpoint"
正是本条。

工作区：`D:\intelligence-agent-backend`，分支 `feat/backend`，基线 `9727344`。

---

## 1. 本轮要合的 commit

| commit | 内容 |
| --- | --- |
| `a38767d` | `feat(web): #185` 路由本体 + 存储层校验对齐 + 17 条用例 |
| `2c658a2` | `fix(artifact): #185 AC4` MinIO `load` 不再伪造元数据 |

本轮**只动后端**，无前端改动；`feat/frontend` 无需同步（本票不依赖 `feat/frontend` 的
新代码，前端接线在 #186）。

---

## 2. 改了什么（按文件）

| 文件 | 改动 |
| --- | --- |
| `src/agent_harness/web/artifacts.py`（新） | 读侧 store 构造接缝 `build_read_artifact_store`（S3 优先 → MinIO 兜底 → `None`）＋服务端上限常量 `MAX_LINES_CAP=1000` / `MAX_CHARS_PER_LINE_CAP=2000` ＋ `clamp_to_cap`。单独成模块是为了让测试能替换这一处接缝 |
| `src/agent_harness/web/app.py` | 新增 `GET /api/sessions/{session_id}/artifacts/{artifact_id}`（注册在 `mount_static` 之前） |
| `src/agent_harness/storage/artifact.py` | 抽出 `ARTIFACT_ID_PATTERN`（S3/MinIO/web 共用）；`Artifact` 的 `source_tool`/`tool_call_id`/`created_at` 改为 `str \| None = None` |
| `src/agent_harness/storage/s3_artifact.py` | 改用共享 pattern（行为不变） |
| `src/agent_harness/storage/minio_artifact.py` | 补 artifact_id 形态校验；`NoSuchKey` → `KeyError`、`UnicodeDecodeError` → `KeyError`；`load` 元数据如实给 `None` |
| `tests/web/test_artifacts_api.py`（新，17 例） | 见 §3 |

### 状态码语义（改动后）

| 条件 | 状态码 | 理由 |
| --- | --- | --- |
| `session_id` / `artifact_id` 形态非法；`start_line`/`end_line` < 1 | **422** | 客户端 bug，不是"不存在" |
| 会话不存在 | **404** | 与既有 DELETE 会话同口径 |
| artifact 不在本会话命名空间（含"属于别的会话"） | **404** | `artifact_id` 是内容哈希、**跨会话可重复**；区分"不存在"与"存在但不可读"会把归属变成可探测信息 |
| 本部署未配置 artifact 存储 | **503** | 如实上报；伪装 404 会让用户以为"这个产物不存在" |
| 正常 | **200** | 切片 + 如实的 `truncated` / `total_lines` / `returned_lines` / `query` |

---

## 3. AC 对照（票面 8 条）

| AC | 状态 | 证据 |
| --- | --- | --- |
| 1 只读路由 + 复用 `inspect` + 可选参数 + 如实截断标记 | ✅ | `app.py:1229`；`test_reads_slice_and_reports_truncation` |
| 2 归属校验（URL 的 session_id 构造 store；非本会话不可读）+ 404/403 分层理由 | ✅ | `test_store_is_built_with_the_url_session_id`（路由层接缝）+ `test_minio_load_namespaces_key_by_store_session`（**真实请求 key == `{session_id}/{artifact_id}`**）+ 路由 docstring 写明 404 而非 403 的理由 |
| 3 穿越防御：`session_id` → 422；**`artifact_id` 形态校验补齐**，两 provider 一致 | ✅ | `ARTIFACT_ID_PATTERN` 三处共用；`test_artifact_id_shape_is_rejected`、`test_minio_store_rejects_malformed_artifact_id_without_network`（5 组参数） |
| 4 元数据如实（缺失即 null，不得伪造空串） | ✅ | `2c658a2`：MinIO `load` 给 `None`；`test_minio_load_namespaces_key_by_store_session` 断言三者均 `None` |
| 5 状态码 + 内部异常不外泄 | ✅ | 上表；领域异常走 `http_error`，`KeyError` 显式转 404。**未做**的：存储不可达（如 S3 网络故障）会冒泡成不透明的 500——不做 502 映射是因为那会把编码错误也伪装成运维故障（见 §6） |
| 6 路由注册顺序在 `mount_static` 之前 | ✅ | `app.py:1229` vs `mount_static`（~1448） |
| 7 测试：跨会话被拒 / 非法 id 422 / 不存在 404 / 正常读 / 截断 / keyword / 三实现一致 | ✅ | 17 例全绿 |
| 8 不新增 SessionEvent、不改 Tool 执行路径、不改 `ArtifactStore` 语义 | ✅ | 抽象与 `inspect` 签名零改动；`Artifact` 只是字段可选化（爆炸半径已核对：无生产消费方） |

---

## 4. 集成后**必须真机**验证的点（别只看 diff）

1. `GET /api/sessions/{sid}/artifacts/0123456789abcdef` 在 **main 的 `.env`** 下返回
   **503**——这是**预期行为**，不是回归（§6 第 1 条）。
2. 若要让 UI 真看到内容，必须先在 main 的 `.env` 配齐 `ARTIFACT_STORE_*`（或先做
   Local store，见 §6），然后跑一个会产生大工具输出的会话，确认：
   `artifact/externalized` 事件出现 → 用事件里的 `artifact_id` 调本路由 → 200 且有
   `lines`。
3. `ruff check` + 全量 `pytest` 在 main 上复跑一次（本票在 `feat/backend` 上 2152 passed）。

---

## 5. 门禁基线（供集成时比对）

- `uv run ruff check .` → 通过。
- `uv run pytest -q` → **2152 passed / 0 failed / 10 skipped**（同一份代码连跑 5 次，
  4 次如上；**1 次**出现 22 个 web 用例失败，见下）。
- **已知间歇现象 OBS-11.1**（登记于 `docs/FRONTEND_ISSUES_LOG.md`）：某一轮全量跑出现
  22 个 `tests/web` 失败（`test_web_stream` / `test_web_ws_relay` 等），另四轮全绿；
  把这两个文件**单独连跑 3 轮**均通过。**非本票引入**（本票 diff 不触达这些路径），
  复现条件未定位，按 §8 只登记不修。

---

## 6. 未交付 / 已知边界（**别当成回归**）

1. **写入侧是空的，读接口因此可能恒 503**：外置写入只在
   `assembly.build_runtime` 的 **S3 分支**（`artifact_store_*` 配齐）创建
   `ArtifactOverflowHandler`。实测：`D:\intelligence-agent-backend\.env` 五字段齐全；
   **`D:\intelligence-agent`（跑完整项目的 main clone）与 frontend clone 一个都没配**
   → 永不外置 → 本接口返回 503。这是**既有的部署配置缺口**，不是 #185 的缺陷。
2. **规格不变量 #15 的 "Local" 那半从未实装**：仓库里只有 `Fake` / `S3` / `MinIO`
   三个 `ArtifactStore`。要"开箱能看到 artifact"，最小路径是加一个本地文件系统 store
   并在未配对象存储时接上 overflow——**这是待用户决策的事项**（落盘位置、保留期、
   与 #172 会话硬删的交互），本票未做。
3. **没有 "list artifacts" 端点**：spec `05_BACKEND_SDD.md:315-321` 要求
   `list artifacts for Session/Run` + `fetch metadata`，本票只做了 **content fetch**。
   前端目前可由 `artifact/externalized` 事件（带 `artifact_id`/`size`/`mime_type`）
   折叠出清单，以及 `ToolResult.artifact_ref`；若 #186 需要独立列表端点，另开票。
4. **MinIO 分支不接 overflow**：`assembly.py` 里 `minio_*` 分支只注册
   `ReadArtifactTool`（读），外置写入只发生在 S3 分支——即"只有 S3 会真的收到写"。
   这是既有形状，本票未改（本票只统一了两者的**校验与错误契约**）。
5. **存储不可达 → 500**（不透明，不泄漏内部信息）。未做 502/503 映射的理由：需要宽泛
   `except Exception`，会把编码错误吞成"运维故障"，得不偿失。若集成时认为要区分，请
   明确要求，我再加窄口径映射。
6. `s3_artifact.py` 仍保留 `import re`（`__init__` 里 `session_id` 段校验用它），
   **不是**漏删。

---

## 7. 给集成 AI 的动作（沿用 §14 纪律）

1. `git -C D:\intelligence-agent fetch origin --prune`，先看 `git diff main...feat/backend`
   是否只剩本票两个 commit（本轮 `feat/backend` 也在别处同步过 main，若出现其他 commit
   请先核对来源）。
2. **先回后正**：把 `origin/main` 合进 `feat/backend`，在 feature 分支上解决任何冲突、
   跑门禁（§5），**再**合 `feat/backend` → 本地 `main`。
3. 冲突处理遵循 §14.7：逐文件分析，**禁止**机械 `ours`/`theirs`，禁止为了消冲突删一侧逻辑。
4. `git push origin main` **需用户明确批准**后再执行；`feat/backend` 本轮**不需要**推分支。
5. 关单：#185 的 GitHub issue 由本轮交付方关（已关/将关，见 issue 评论）。
