# #20 — Phase 3 Spec: Session-scoped Sandbox 生命周期（WorkspaceRegistry + 映射持久化 + resume 恢复）

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T13:42:04Z
- **Closed**: 2026-09-03T14:20:12Z
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/20

---

## Problem Statement

Phase 3 的 Coding Tools 和 Sandbox 后端已全部落地，但 Session 与 Sandbox 之间没有绑定关系。`DockerSandbox` 在构造时生成随机 uuid 命名容器和 volume，只存内存——进程重启后无法根据 session_id 找回对应的 Sandbox。`05_SANDBOX_CODING_TOOLS.md` §2 和 `07_STORAGE_PERSISTENCE_RECOVERY.md` §9 要求的恢复顺序（load Session → load sandbox mapping → ensure sandbox started → ... → resume）在第二步就断了：没有 sandbox mapping 可以 load。

`Session.resume()` 目前只修复 dangling tool_call 的消息链，不恢复 workspace。如果 Agent 在 DockerSandbox 里创建了文件然后进程崩溃，重启 resume 后 workspace 可能丢失（取决于容器是否还在），Agent 无法继续之前的工作。

## Solution

引入 `WorkspaceRegistry`——一个持久化的 Session↔Sandbox 映射表，记录每个 session 对应的 sandbox 元数据（后端类型、workspace_root 路径、Docker 容器名、volume 名）。Session 创建时注册映射，resume 时查回映射并重建 Sandbox 实例（复用已有容器/volume）。LocalSubprocessSandbox 的 workspace 是真实目录，天然持久；DockerSandbox 的容器可能在退出后停止但 volume 持久，resume 时重新启动容器即可恢复 workspace。

这样 Session 的生命周期就与 Sandbox 绑定：start → 创建/注册 sandbox，resume → 查回/重启 sandbox，stop → 可选清理。恢复顺序的第二步（load sandbox mapping）不再是断点。

**本 Spec 明确范围限定**：只实现 Session↔Sandbox 绑定 + 映射持久化 + resume 时 workspace 恢复。完整的 Operation Ledger / Checkpoint / reconcile / kill tests 属于 Phase 4 后续工作，依赖 Storage 抽象（SQLite/Postgres），不在本 Spec 范围。

## User Stories

1. 作为 Agent Runtime，当一个新 Session 开始时，我想自动创建/注册一个 Sandbox 实例并记录映射，这样这个 Session 的所有 Tool 调用都绑定到同一个 workspace。
2. 作为 Agent Runtime，当一个 Session resume 时，我想根据 session_id 查回之前的 Sandbox 映射并重建 Sandbox 实例，这样 workspace 里之前创建的文件还在。
3. 作为开发者，我想 WorkspaceRegistry 的映射持久化到磁盘（JSON 文件，与 Session JSONL 同级），这样进程重启后映射不丢。
4. 作为开发者，我想 LocalSubprocessSandbox 的 workspace 在 resume 时天然恢复（目录就在磁盘上），这样本地开发不需要额外恢复逻辑。
5. 作为开发者，我想 DockerSandbox 的容器在 resume 时被重新启动（如果已停止）并复用原有 volume，这样容器内的 workspace 文件不丢。
6. 作为开发者，我想 DockerSandbox 的容器名和 volume 名是确定性的（基于 session_id 而非随机 uuid），这样映射表能用 session_id 查回正确的容器。
7. 作为配置者，我想能选择 Sandbox 后端（local 或 docker），这样开发时用 local、生产用 docker。
8. 作为开发者，当一个 Session 显式结束时，我想能选择是否清理 Sandbox（保留 volume 还是删除），这样 workspace 可以跨 session 复用或按需清理。
9. 作为开发者，我想 WorkspaceRegistry 的接口足够简洁（create / get / stop / delete），这样未来 Phase 4 的 Operation Ledger 和 reconcile 能建立在它之上。

## Implementation Decisions

### WorkspaceRegistry

```python
class WorkspaceRegistry:
    """Session ↔ Sandbox 映射表的持久化管理。"""

    def __init__(self, root: Path, backend: str = "local"):
        """root 是映射表和 workspace 的根目录。backend='local'|'docker'。"""

    def create(self, session_id: str) -> Sandbox:
        """为新 session 创建 Sandbox 实例，持久化映射，返回已 ensure_started 的 Sandbox。"""

    def get(self, session_id: str) -> Sandbox:
        """查回 session 的 Sandbox 实例（必要时重建并 ensure_started）。"""

    def stop(self, session_id: str) -> None:
        """停止 session 的 Sandbox（容器停但不删 volume）。幂等。"""

    def delete(self, session_id: str) -> None:
        """彻底清理 session 的 Sandbox 和映射。幂等。"""

    def exists(self, session_id: str) -> bool:
        """检查 session 是否有映射记录。"""
```

### 映射持久化格式

映射表存为 `<root>/workspaces/<session_id>.json`：

```json
{
    "session_id": "sess_xxx",
    "backend": "local",
    "workspace_root": "/path/to/workspaces/sess_xxx",
    "container_name": null,
    "volume_name": null,
    "created_at": "2026-09-03T..."
}
```

LocalSubprocessSandbox：workspace_root 是真实路径，container_name/volume_name 为 null。
DockerSandbox：container_name 和 volume_name 基于 session_id 确定性生成（如 `agent-harness-{session_id}`）。

### DockerSandbox 命名确定性化

DockerSandbox 的 `__init__` 从接受随机 uuid 改为接受确定性名称（由 WorkspaceRegistry 传入基于 session_id 的名称）。已有的随机命名行为保留为 fallback（直接构造 DockerSandbox 不经过 Registry 时仍可用）。

### Session 集成

`Session.start()` 和 `Session.resume()` 新增可选参数 `workspace_registry: WorkspaceRegistry | None`：
- 提供 registry 时：start 调 registry.create()，resume 调 registry.get()，Session 持有 Sandbox 引用。
- 不提供时：行为不变（向后兼容，现有测试不受影响）。

Session 不直接管理 Sandbox 的完整生命周期（stop/delete 是 Registry 的职责），但 Session 提供 `sandbox` 属性供 Runtime 访问。

### AgentRuntime 集成

AgentRuntime 的 Sandbox 注入方式不变（构造时传入）。当通过 WorkspaceRegistry 管理 Sandbox 时，由调用方（CLI 或上层编排）负责从 Registry 获取 Sandbox 并传给 Runtime。本 Spec 不改 Runtime 内部——只提供 Registry 基础设施。

### 目录结构

```
<root>/
├── sessions/
│   └── <session_id>/
│       └── events.jsonl          # 已有：JsonlSessionStore
└── workspaces/
    ├── <session_id>.json         # 新增：WorkspaceRegistry 映射
    └── <session_id>/             # 新增：LocalSubprocessSandbox workspace 目录
        └── ... (Agent 创建的文件)
```

### 不改的东西

- Sandbox ABC 契约不变（已有 7 个方法足够）。
- Tool 契约不变。
- ToolExecutor 不变。
- Session 的 events.jsonl 读写逻辑不变。
- JsonlSessionStore 不变。

## Testing Decisions

### 测试缝

复用现有测试缝 + 新增 WorkspaceRegistry 直接测试：
- `tests/sandbox/test_workspace_registry.py`：直接调 Registry API + 断言 Sandbox 行为。
- `tests/session/test_session_workspace.py`：Session + Registry 集成（start/resume 绑定 sandbox）。

### 什么算好测试

- **映射持久化**：create 后 JSON 文件存在且内容正确；进程重启后（模拟：新 Registry 实例同 root）get 能查回。
- **workspace 恢复**：create → 在 workspace 写文件 → 新 Registry 实例 get → 文件还在。
- **确定性命名**：同一 session_id 两次 create 产生的 Docker 容器名相同（不测真实 Docker，测名称生成逻辑）。
- **幂等性**：stop/delete 多次不报错。
- **向后兼容**：不传 registry 时 Session 行为完全不变（现有测试全绿）。

### 具体测试

- `tests/sandbox/test_workspace_registry.py`（LocalSubprocessSandbox 后端）：
  - create → 返回已 ensure_started 的 Sandbox，workspace_root 存在。
  - create → 映射 JSON 文件存在。
  - get（同 Registry 实例）→ 返回同一个 Sandbox 实例。
  - get（新 Registry 实例，模拟重启）→ 重建 Sandbox，workspace_root 与之前一致。
  - workspace 恢复：create → write 文件 → 新 Registry get → read 文件内容正确。
  - exists：未 create → False；create → True。
  - stop：调用后幂等（LocalSubprocess 是 no-op）。
  - delete：映射文件删除、workspace 目录可选保留。
  - backend='local' → 返回 LocalSubprocessSandbox 实例。
- `tests/sandbox/test_workspace_registry_docker.py`（DockerSandbox 后端，@integration + skipif Docker）：
  - 容器名/volume 名基于 session_id 确定性。
  - workspace 恢复：create → write → stop → get（重启容器）→ 文件还在。
- `tests/session/test_session_workspace.py`：
  - Session.start(registry) → session.sandbox 不是 None。
  - Session.resume(registry) → session.sandbox 恢复，workspace 文件还在。
  - 不传 registry → session.sandbox 是 None，现有行为不变。

## Out of Scope

- **Operation Ledger**（Phase 4）：per-operation 状态机、args_hash、result_ref、reconcile 元数据——属 Phase 4 Storage 抽象。
- **Checkpoint**（Phase 4）：稳定边界的可恢复事实持久化、event+checkpoint 事务提交——属 Phase 4。
- **Reconcile 逻辑**（Phase 4）：SUCCEEDED-but-missing-result 合成、UNKNOWN/NEED_RECONCILE 处理、tool-specific recovery——属 Phase 4，需要 Operation Ledger。
- **Kill tests**（Phase 4）：真实进程杀死 + 恢复的验收测试——属 Phase 4 Gate。
- **Workspace import 流程**（05 §3）：从宿主项目目录显式 copy 到 Docker volume 的结构化流程——已有 copy_in 原语，完整 import flow 留后续。
- **Multi-agent workspace 共享**（05 §2）：同一 workspace 不同 Tool Permission 的多 Agent——属 Phase 13。
- **SQLite/Postgres 存储**（Phase 4）：本 Spec 映射表用 JSON 文件，足够 Phase 3 的绑定需求。升级到 SQL 存储是 Phase 4 的 Storage 抽象决策。

## Further Notes

- **架构不变量守护**：Sandbox 是 Runtime 安全边界（#11），Registry 只管理 Sandbox 生命周期，不改 Sandbox 路径边界。Checkpoint 不等于副作用恢复（#12）——本 Spec 不引入 Checkpoint，workspace 恢复靠 Sandbox 后端的持久性（Local 目录天然持久，Docker volume 持久），不靠 checkpoint 回放。
- **与 Phase 4 的衔接**：本 Spec 的 WorkspaceRegistry 是 Phase 4 恢复顺序第 2 步（load sandbox mapping）的实现。Phase 4 的 Operation Ledger / Checkpoint / reconcile 在此基础上加层，不需要重构 Registry。
- **Reuse First**：映射表用 JSON 文件（与 SessionStore 的 JSONL 同级技术），不引入 SQLite/Postgres。Docker volume 复用已有 DockerSandbox 的 volume 机制（已实现），只改命名从随机到确定性。
- **安全**：WorkspaceRegistry 不改变 Sandbox 的路径边界强制。workspace 目录在 Registry root 下，Agent 即使尝试路径穿越也被 Sandbox._resolve_within_workspace 拦截。

