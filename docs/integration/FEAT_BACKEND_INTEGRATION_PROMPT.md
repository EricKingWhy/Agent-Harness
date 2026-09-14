# Integration Prompt — feat/backend → main

> **给集成 AI（Git Integrator）的执行提示词。**
> 按 AGENTS.md §14 集成规则执行；merge / push 需用户明确批准。

---

## 0. 任务

将 `feat/backend` 分支合入 `main`。

**内容**：2 个 commit，25 files, +1058/-66

| commit | 内容 |
| --- | --- |
| `1b3179d` | T5 #135 — MinIO 大产物外置 + fail-open overflow |
| `a731563` | context_providers runtime consumption (Ticket B2, ADR-0021) |

### Commit 1: T5 #135 — MinIO 大产物外置 + fail-open overflow

- 新事件类型 `ARTIFACT_EXTERNALIZED`（artifact/externalized）：tool result 超阈值时原始内容外置到 MinIO（或 S3 兼容存储），session 里留摘要 + artifact_ref
- `ArtifactOverflowHandler.maybe_overflow` 改为 fail-open：存储不可用时不抛异常，保留原始未截断 tool result 在 session 中
- 新增 `ReadArtifactTool`：模型凭 artifact_ref 用 read_artifact 工具按需读取局部内容（offset/limit 切片）
- 新增 `MinioArtifactStore`：MinIO 作为大产物外置对象存储
- Settings 新增 `minio_*` 配置字段（endpoint/access_key/secret_key/bucket）
- assembly.py build_runtime 注册 ReadArtifactTool（minio_* 配置时）
- multiagent/provider.py collect_result_fields 同时收集 artifact/created 和 artifact/externalized 的 artifact_id
- cli.py render_replay_event 支持 ARTIFACT_EXTERNALIZED 渲染
- web/src/generated/event-types.ts 同步新增事件类型
- 测试更新：artifact/created → artifact/externalized；test_parallel_batch_logs_secondary_exceptions_when_first_raises 用自定义 OverflowHandler 子类直接 raise（绕过 T5 fail-open）

### Commit 2: context_providers runtime consumption (Ticket B2, ADR-0021)

让用户通过 web 层提交的 `context_providers: list[str]` 真正影响 runtime 装配的 provider 集合。这是 RUNTIME 子批次的最后一个字段（`agent_profile` 和 `reasoning_effort` 已分别在 ADR-0020a / `79e2860` 落地）。

四项改动：

1. **wiring 加 id→provider 映射**（`capability/wiring.py`）：
   - 新增 `ContextProviderEntry` dataclass（id / provider / display_name / description）
   - 新增 `register_context_provider()` 单一注册入口（同时更新 dict 和兼容 list）
   - `CapabilityWiring` 新增 `context_provider_entries: dict[str, ContextProviderEntry]`
   - `_wire_memory` 注册 id=`"memory"`，`_wire_skills` 注册 id=`"skills"`
   - 保留 `context_providers: list[Any]` 向后兼容

2. **build_runtime 消费用户 context_providers**（`assembly.py`）：
   - `None` → wiring 全集（向后兼容）
   - `[]` → 空集（用户显式选了不启用任何 provider）
   - `["memory", ...]` → 子集（按用户顺序）
   - 未知 id（config 降级）→ 跳过 + WARNING 日志，不崩溃

3. **GET /api/context-providers 返真实清单**（`web/app.py`）：
   - 从 `wiring.context_provider_entries` 投影 `{id, display_name, description}`
   - 惰性装配 wiring（与其他依赖 wiring 的端点一致）
   - bare config（无 capabilities）→ 空 list

4. **handler-level 422 校验**（`web/app.py` create_session）：
   - 未知 id → HTTPException(422) with available set in detail
   - 与 model 字段相同的 handler-level 校验模式（Pydantic validator 无法访问 runtime wiring state）

---

## 1. 分支映射

| 项 | 值 |
| --- | --- |
| 源 worktree | `D:\intelligence-agent-backend` |
| 源分支 | `feat/backend` |
| 源 HEAD | `a731563` |
| 目标 worktree | `D:\intelligence-agent` |
| 目标分支 | `main` |
| merge-base | `d7cb1c7` |
| commits ahead | **2** |
| diff stat | 25 files, +1058 / −66 |

---

## 2. 预检（只读，§14.3）

```bash
# 确认 worktree 映射
git worktree list --porcelain

# 确认源分支状态
git -C D:/intelligence-agent-backend status
git -C D:/intelligence-agent-backend log --oneline -3

# 确认目标分支状态
git -C D:/intelligence-agent status
git -C D:/intelligence-agent log --oneline -3

# fetch 最新
git -C D:/intelligence-agent fetch origin --prune

# 确认 merge-base
git -C D:/intelligence-agent merge-base main feat/backend

# diff 检查
git -C D:/intelligence-agent diff main...feat/backend --stat
git -C D:/intelligence-agent diff main...feat/backend --check
```

---

## 3. 冲突风险评估

| 文件 | 与 main 近期改动的关系 | 冲突风险 |
| --- | --- | --- |
| `docs/adr/0021-*.md` | 新文件 | 无 |
| `docs/integration/BACKEND_B2_HANDOFF.md` | 新文件 | 无 |
| `src/agent_harness/assembly.py` | main 未改此文件 | 低 |
| `src/agent_harness/capability/wiring.py` | main 未改此文件 | 低 |
| `src/agent_harness/cli.py` | main 未改此文件 | 低 |
| `src/agent_harness/config.py` | main 未改此文件 | 低 |
| `src/agent_harness/multiagent/provider.py` | main 未改此文件 | 低 |
| `src/agent_harness/session/__init__.py` | main 未改此文件 | 低 |
| `src/agent_harness/session/event.py` | main 未改此文件 | 低 |
| `src/agent_harness/storage/minio_artifact.py` | 新文件 | 无 |
| `src/agent_harness/tooling/overflow.py` | main 未改此文件 | 低 |
| `src/agent_harness/tools/__init__.py` | main 未改此文件 | 低 |
| `src/agent_harness/tools/read_artifact.py` | 新文件 | 无 |
| `src/agent_harness/web/app.py` | main 未改此文件 | 低 |
| `tests/**` | main 未改这些文件 | 低 |
| `web/src/generated/event-types.ts` | main 可能已改（前端 F3 合入） | **中** |

**关键风险点**：`web/src/generated/event-types.ts` 可能在前端 ContextProviderPicker 合入 main 时被修改。如果冲突，优先保留 feat/backend 版本（后端 owned 文件），但检查是否有前端新增的事件类型需要合并。

**总体冲突风险：低。**

---

## 4. 集成步骤（需用户批准）

```bash
# 1. 切到目标 worktree
cd D:/intelligence-agent

# 2. 确认在 main 分支
git branch --show-current  # 应为 main

# 3. merge（--no-ff 保留分支拓扑）
git merge --no-ff feat/backend \
  -m "merge(backend): context_providers runtime consumption + MinIO 大产物外置 → main"

# 4. validation gate
cd D:/intelligence-agent
python -m pytest --tb=short -q 2>&1 | tail -20  # 全量测试
ruff check . 2>&1 | tail -5  # lint
```

---

## 5. 验证证据（源分支）

| 门禁 | 结果 |
| --- | --- |
| pytest | 1258 passed / 9 skipped / 3 deselected |
| ruff | clean |
| git diff --check | 干净 |

### 关键测试文件

- `tests/test_assembly_context_providers.py` — 6 条 assembly 筛选测试
- `tests/web/test_web_context_providers_b2.py` — 7 条 web 层验收（GET projection + 422）
- `tests/tooling/test_overflow.py` — fail-open 语义验证
- `tests/tooling/test_overflow_executor.py` — executor 层 fail-open 验证

---

## 6. 集成后验证

```bash
# 全量测试
cd D:/intelligence-agent
python -m pytest --tb=short -q 2>&1 | tail -20

# lint
ruff check . 2>&1 | tail -5

# event-types.ts 一致性检查（如有冲突）
git diff HEAD~1 -- web/src/generated/event-types.ts
```

---

## 7. 风险评估

| 风险 | 等级 | 缓解 |
| --- | --- | --- |
| `event-types.ts` 冲突 | 中 | 后端 owned 文件，优先保留 feat/backend 版本 |
| MinIO 配置缺失 | 无 | minio_* 未配时 ReadArtifactTool 不注册，fail-open 保留原始 result |
| context_providers 三值语义 | 低 | None/[]/[ids] 有完整测试覆盖 |

**总体风险：低。建议集成。**
