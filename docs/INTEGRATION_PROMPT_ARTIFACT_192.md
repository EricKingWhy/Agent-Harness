# 集成提示词：#192 接通 artifact 外置写入（后端）→ `main`

**一句话**：补上 spec 06 §3 要求的**默认** Provider `LocalArtifactStore`，并把外置写入
接成 **S3 → MinIO → Local**；同时修掉 MinIO 分支"只有读工具、没有写入者"的半截接线。
此后**没有对象存储的部署也能外置产物**——#185 的读取接口与 #186 的界面因此真正可用。

工作区：`D:\intelligence-agent-backend`，分支 `feat/backend`，基线 `0296956`（= #185 的
文档 commit）。**只动后端**。

---

## 1. 本轮 commit

| commit | 内容 |
| --- | --- |
| `b31b9f3` | `feat(artifact): #192` 实现 + 测试（11 文件，+850 / −27） |
| （随后一条） | `docs(#192)` 进度登记（`PHASE_STATUS.md`）+ 本提示词 |

---

## 2. 修的是什么（Gap 的完整链条）

1. 生产里唯一的外置写入者是 `ArtifactOverflowHandler`，而它只在 `assembly.py` 的
   `artifact_store_*`（S3）分支被创建；
2. `minio_*` 分支只注册**读**工具 `ReadArtifactTool`——没有写入者，与 `config.py`
   自己的注释（"MinIO 用于 tool result 外置"）相反；
3. 规格 06 §3 写明的默认 Provider「Local filesystem：开发/小型部署」**从未实现**；
4. ⇒ 任何没有对象存储的部署什么都不外置 ⇒ `#185` 的读接口恒 503、`#186` 的界面
   永远看不到内容（`D:\intelligence-agent` 的 `.env` 正是这种情形）。

---

## 3. 改了什么

| 文件 | 改动 |
| --- | --- |
| `storage/local_artifact.py`（新） | `LocalArtifactStore`（save/load/inspect）+ `discard_local_artifacts` 窄清理方法 |
| `config.py` | 新 setting `artifact_dir`，默认 `.agent/artifacts` |
| `storage/artifact.py` | 新增 `SESSION_KEY_PATTERN`（存储键 session 段的唯一形态定义） |
| `assembly.py` | 写入接线 **S3 → MinIO → Local**；写入者与读回工具指向同一 store |
| `web/artifacts.py` | 读路径同优先级补 Local 兜底；503 语义收窄 |
| `session/service.py` | 硬删第 ⑦ 步连带丢弃本地 artifact 目录；session 键段规则改用共享定义 |
| 测试（5 文件） | +46：Local 契约 33 / 读 store 选择 5 / 装配接线 4 / 外置落盘链路 1 / 硬删 2 |

---

## 4. AC 对照（票面 10 条）

| AC | 状态 | 证据 |
| --- | --- | --- |
| 1 `LocalArtifactStore` 实现 ABC，落盘 `<artifact_dir>/<session_id>/<artifact_id>` | ✅ | `test_content_hash_id_and_layout` 断言真实路径 |
| 2 新 setting `artifact_dir` 默认 `.agent/artifacts` | ✅ | `config.py`；`Settings()` 默认值 |
| 3 契约与既有实现一致（not-found/非法 id → `KeyError`；切片复用 `_slice_lines`） | ✅ | `TestLoadContract`（含篡改内容 → hash mismatch、非 UTF-8） |
| 4 元数据"缺失即 `None`" | ✅ | 旁挂元数据缺失/损坏/空串三种情形各一条 |
| 5 写入接线 S3 → MinIO → Local，写入者与读回工具成对 | ✅ | `test_local_store_is_the_default_externalizer` 等 4 条装配测试 |
| 6 修 MinIO 半截接线 | ✅ | `test_minio_config_gets_a_writer_too` |
| 7 读接口在 Local 兜底下可用 | ✅ | `TestBuildReadArtifactStoreSelection` 5 条，含写→读往返 |
| 8 硬删连带丢弃本地 artifact 目录（窄方法、不读映射） | ✅ | `test_hard_delete_discards_local_artifacts`（含"同 id 不同会话不受影响"） |
| 9 测试齐备，既有实现不回归 | ✅ | 全量 **2198 passed / 10 skipped / 0 failed** |
| 10 不做自动 TTL / 体积清理 / 远端删除 | ✅ | 无相关代码；边界写进 `discard_local_artifacts` docstring |

---

## 5. 三个设计问题的决定与依据（**用户授权自行决定，要求有依据**）

### 5.1 落盘位置：`.agent/artifacts/<session_id>/<artifact_id>`

- 与对象存储的键约定 `{session_id}/{artifact_id}` **逐段同构** ⇒ 三个 Provider 同形，
  `#185` 的读取接口保持 Provider 无关；
- `.gitignore` 已整目录忽略 `.agent/`（注释原文："运行时产物（日志、工作区）"）；
- 与 `workspace_dir` 默认值 `.agent/workspace` 同族；
- **绝不能放 `workspace_root` 底下**：ADR-0027 之后它可能是**用户的真实仓库**，而
  ADR-0029 D2 禁止 harness 删除任何不是它自己拼出来的路径——放进去要么删不掉（孤儿
  残留），要么会删到用户仓库；
- 独立 setting 而非从 `workspace_dir` 派生：后者可被部署方指向用户仓库。

### 5.2 保留策略：生命周期 = 会话生命周期，**不做自动 TTL**

- ADR-0004 明确"不做自动 TTL"；ADR-0029 Non-Goals 把"自动清理 / TTL / 按时间或体积
  批量删除"列为非目标；
- spec 06 §1「完整事实记录，不能因模型窗口不足而删除」；
- spec 07：恢复用 `result_json/artifact_ref` 重建 ToolResult——删掉活会话的 artifact
  会造出**悬空引用**，那是正确性故障，而磁盘占用只是成本；
- content-hash + session 前缀 ⇒ 同内容跨会话是两个对象 ⇒ 删一个会话不影响另一个
  （测试钉住了这一点）。

### 5.3 与 #172 硬删的联动

- 用**窄方法** `discard_local_artifacts`，沿用 `WorkspaceRegistry.discard_session_artifacts`
  的既有模式（ADR-0029 D2）：**不读映射**、只删"用 setting + session_id 自己拼出来的
  路径"——这是写死的构造规则，不是"读配置再决定删什么"；
- 不给 `ArtifactStore` ABC 加 `delete`：ADR-0029 D6 说的"级联删除"包含 fork 继承与远端
  对象，超出本票；且 ABC 加 delete 会让 2/3 个实现抛 `NotImplementedError`；
- **两条记录在案的边界**（不在本票修）：① 配了 S3/MinIO 时**远端对象不删**（那些
  Provider 没有 delete）；② fork 子会话**继承**的 artifact 引用在父会话硬删后不可解析
  ——与 ADR-0029 D1/D5/D6 已接受的"删掉就是删掉"一致。

---

## 6. 一条**契约语义变更**（集成时必须知道）

未配对象存储的部署，`GET /api/sessions/{id}/artifacts/{artifact_id}` 的诚实答案从
**503**（"本部署没配好存储"）变成 **404**（"这个产物不存在"）——因为现在它有本地存储
可读，只是里面没有这个 id。

503 只剩两种**真的没有可读存储**的情形：

1. `artifact_dir` 被显式置空（= 关掉本地外置）；
2. 对象存储**半配置**（例如只填了 endpoint 没填 bucket）——**刻意不降级到本地**：
   那会让运维以为产物进了对象存储。

对应测试改名 + 新增：`test_unconfigured_object_store_now_reads_from_local` /
`test_blank_artifact_dir_returns_503`。

---

## 7. 门禁基线（供集成时比对）

- `ruff check src/ tests/` → clean
- 全量 `pytest -q` → **2198 passed, 10 skipped, 42 deselected, 0 failed**（+46）

（前端门禁与另外三票见 `feat/frontend` 的提示词。）

---

## 8. 未交付 / 已知边界（**别当成回归**）

1. **远端对象不随会话硬删消失**（S3/MinIO 无 delete）：删会话后对象存储里会留下孤儿
   对象。要收敛需给远端 Provider 加 delete（含错误语义与批量删除），另开票。
2. **fork 子会话继承的 artifact 引用在父会话硬删后不可解析**（ADR-0029 D6 已记录；
   fork 不复制 artifacts）。
3. **不做自动 TTL / 体积清理**（ADR-0004 + ADR-0029 Non-Goals）。若将来要加，必须先
   解决"活会话的引用必须可解析"这条约束。
4. `artifact_dir` 与 `workspace_dir` 是**两个**独立 setting：把 artifact 落到
   `workspace_dir` 底下的部署会重新引入"删不掉或删到用户仓库"的问题——不要这样配。

---

## 9. 给集成 AI 的动作（沿用 §14 纪律）

1. `git -C D:\intelligence-agent fetch origin --prune`；`git diff main...feat/backend` 应只剩
   #185 / #192 两票的 commit（#185 已关单）。
2. **先回后正**：把 `origin/main` 合进 `feat/backend`，在 feature 分支上解决冲突、跑门禁
   （§7），**再**合 `feat/backend` → 本地 `main`。
3. 冲突处理遵循 §14.7：逐文件分析，**禁止**机械 `ours`/`theirs`。本票与 `feat/frontend`
   的三票（#182 / #190 / #184）**无文件重叠**，预期无冲突。
4. `git push origin main` **需用户明确批准**后再执行。
5. 集成后建议**真机验证一次外置链路**（这是本票的验收本质）：在 `main` 的 `.env` 里
   保持对象存储为空（默认即 Local），跑一条会产出大输出的命令（例如 `pytest -q` 或
   `cat` 一个大文件），然后：
   - `.agent/artifacts/<session_id>/` 下应出现内容文件与旁挂 `.json`；
   - `GET /api/sessions/{id}/artifacts/{artifact_id}` 应返回 200 切片（不再是 503）；
   - 会话事件里应出现 `artifact/externalized`。
