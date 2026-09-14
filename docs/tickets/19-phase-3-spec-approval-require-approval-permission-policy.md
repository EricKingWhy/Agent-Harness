# #19 — Phase 3 Spec: Approval / REQUIRE_APPROVAL 机制（Permission Policy + 审批关卡）

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T13:42:01Z
- **Closed**: 2026-09-03T14:20:08Z
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/19

---

## Problem Statement

Phase 3 的 9 个 Coding Tool 已全部落地，但 `05_SANDBOX_CODING_TOOLS.md` §6 要求的三层 Permission Policy（read-only / workspace-write / danger-full-access）和 REQUIRE_APPROVAL 机制尚未实现。当前 ToolExecutor 的验证链只有 lookup → validate → execute，没有任何授权关卡。模型的 bash 调用（可能是 `rm -rf` 或网络命令）与 read 调用走完全相同的路径——没有机制让高风险操作在执行前请求人类批准。

## Solution

在 ToolExecutor 的验证链中插入一个 Approval 关卡（validate → **approval gate** → execute），由 PermissionPolicy 和 ApprovalRequest/ApprovalResponse 类型驱动。每个 Tool 声明自己的 permission 要求（默认 read-only），ToolExecutor 在执行前检查 Session 的当前 PermissionPolicy 是否允许；如果不允许或操作被标记为 REQUIRE_APPROVAL，则产生一个 ApprovalRequest，由可插拔的 ApprovalCallback 决定批准或拒绝。批准只针对当次 Tool Call，不永久放开后续命令。

## User Stories

1. 作为配置者，我想给 Session 设定一个 PermissionPolicy（read-only / workspace-write / danger-full-access），这样我能控制 Agent 在这个 Session 里的最大权限边界。
2. 作为配置者，当 Policy 是 read-only 时，任何写操作（write/edit/apply_patch/bash）都会被拒绝，这样我能保证 Agent 不意外修改文件。
3. 作为配置者，当 Policy 是 workspace-write 时，读和写操作都被允许，但危险操作（如某些 bash 命令）仍需要审批，这样我能让 Agent 自由工作但拦截高风险动作。
4. 作为配置者，当 Policy 是 danger-full-access 时，所有操作都被允许且不需要审批，这样我能在可信环境里让 Agent 全自动运行。
5. 作为人类审查者，当一个高风险 Tool Call 需要审批时，我想收到一个 ApprovalRequest（包含工具名、参数、风险原因），这样我能判断是否批准。
6. 作为人类审查者，当我批准一次 Tool Call 时，批准只对这一次调用生效，下次同样的命令仍需要重新审批，这样不会有"一次批准永久开放"的安全漏洞。
7. 作为人类审查者，当我拒绝一次 Tool Call 时，Agent 收到一个 PERMISSION_DENIED 的 ToolResult 并能据此调整策略。
8. 作为开发者，我想提供一个自定义的 ApprovalCallback（如 CLI 交互、Web UI 弹窗、自动批准测试环境），这样审批接口能适配不同部署形态。
9. 作为开发者，当没有提供 ApprovalCallback 时，REQUIRE_APPROVAL 的工具默认被拒绝（安全默认值），这样系统不会因为缺回调而静默放行危险操作。
10. 作为开发者，我想 Tool 声明 permission 级别通过一个新属性而非复用 side_effect，因为 side_effect 是调度分类（并发/串行），permission 是授权分类——它们是正交关注点。
11. 作为开发者，我想所有 Tool（内置、未来 MCP、未来 Plugin）都经过同一个 Approval 关卡，这样没有工具能绕过授权（不变量 #7 的延伸）。

## Implementation Decisions

### 新增 PermissionPolicy 枚举

```python
class PermissionPolicy(str, Enum):
    READ_ONLY = "read-only"              # 只允许 read-only 工具
    WORKSPACE_WRITE = "workspace-write"  # 允许 read + workspace-write，danger 需审批
    DANGER_FULL_ACCESS = "danger-full-access"  # 全部允许，不需审批
```

### 新增 ToolPermission 枚举（Tool 的授权分类，正交于 side_effect）

```python
class ToolPermission(str, Enum):
    READ_ONLY = "read-only"            # 读操作：read/grep/glob/git_status/git_diff
    WORKSPACE_WRITE = "workspace-write" # workspace 内写：write/edit/apply_patch
    DANGER = "danger"                   # 高风险：bash（可配网络/系统副作用）
```

### Tool 契约扩展

Tool ABC 新增可选属性 `permission`，默认返回 `ToolPermission.WORKSPACE_WRITE`（安全偏高，避免新工具默认 DANGER）。已有工具覆写：
- read/grep/glob/git_status/git_diff → READ_ONLY
- write/edit/apply_patch → WORKSPACE_WRITE
- bash → DANGER

side_effect 和 permission 是正交的：side_effect 驱动调度（并发/串行），permission 驱动授权（允许/审批/拒绝）。

### ApprovalRequest / ApprovalResponse

```python
@dataclass(frozen=True)
class ApprovalRequest:
    tool_name: str
    args: dict
    permission: ToolPermission
    policy: PermissionPolicy
    reason: str  # 为什么需要审批（如 "bash 命令属于 DANGER 级别"）

@dataclass(frozen=True)
class ApprovalResponse:
    approved: bool
    reason: str = ""
```

### ApprovalCallback 类型

```python
ApprovalCallback = Callable[[ApprovalRequest], ApprovalResponse]
```

可插拔：CLI 交互、Web UI、自动批准、自动拒绝。不提供时默认拒绝（安全默认值）。

### ToolExecutor 集成

`ToolExecutor.execute()` 在 validate 之后、execute 之前插入 approval gate：
1. 取 tool.permission 和 session 当前 policy。
2. 如果 policy == DANGER_FULL_ACCESS → 放行。
3. 如果 tool.permission 级别 <= policy 级别 → 放行（READ_ONLY <= WORKSPACE_WRITE <= DANGER）。
4. 否则（tool.permission 超出 policy 或两者都是 DANGER 级别但 policy 是 WORKSPACE_WRITE）→ 需要 approval：
   - 无 callback → PERMISSION_DENIED（安全默认）。
   - 有 callback → 调 callback；approved → 放行；denied → PERMISSION_DENIED。
5. 批准只影响当次 execute 调用，不存储任何状态（per-call scoping 由设计保证——每次 execute 都独立检查）。

### ToolExecutor 构造变化

```python
class ToolExecutor:
    def __init__(self, registry, *, policy=PermissionPolicy.WORKSPACE_WRITE, approval_callback=None):
        ...
```

policy 和 approval_callback 是可选的，有安全默认值（policy=WORKSPACE_WRITE，callback=None→拒绝 danger）。

### 不改的东西

- ToolResult / ErrorCode 不新增码——审批拒绝映射现有 PERMISSION_DENIED。
- Tool 契约的 side_effect / args_schema / execute 签名不变——只新增可选属性。
- 批次调度（execute_batch）不变——approval gate 在单 tool execute 层，batch 只是对 execute 的并发/串行包装。

## Testing Decisions

### 测试缝

复用现有唯一测试缝：`LocalSubprocessSandbox` + `ToolRegistry` + `ToolExecutor.execute(tool_call dict)` + 断言 `ToolResult`。

### 什么算好测试

- **不变量优先**：per-call scoping（连续两次同样的 danger 调用，第二次仍需审批）、安全默认值（无 callback → danger 被拒绝）、policy 级别层级（READ_ONLY 工具在 READ_ONLY policy 下放行）。
- **审批回调**：提供 auto-approve callback → danger 工具执行成功；提供 auto-deny → PERMISSION_DENIED。
- **已有工具分类**：read=READ_ONLY, write=WORKSPACE_WRITE, bash=DANGER。
- **回归**：现有 202 个测试不受影响（默认 policy=WORKSPACE_WRITE 时，read/write 正常工作，只有 bash 需要 approval——需要确认现有测试中 bash 的使用不会被审批拦截）。

### 具体测试

- `tests/tooling/test_permission.py`：
  - PermissionPolicy + ToolPermission 级别比较。
  - Tool ABC 默认 permission = WORKSPACE_WRITE。
  - 各 Coding Tool 的 permission 断言（read=READ_ONLY, write=WORKSPACE_WRITE, edit=WORKSPACE_WRITE, bash=DANGER, glob=READ_ONLY, grep=READ_ONLY, git_status=READ_ONLY, git_diff=READ_ONLY, apply_patch=WORKSPACE_WRITE）。
- `tests/tooling/test_approval_gate.py`：
  - DANGER_FULL_ACCESS policy → bash 无审批放行。
  - WORKSPACE_WRITE policy + bash(DANGER) + 无 callback → PERMISSION_DENIED。
  - WORKSPACE_WRITE policy + bash(DANGER) + auto-approve callback → 执行成功。
  - WORKSPACE_WRITE policy + bash(DANGER) + auto-deny callback → PERMISSION_DENIED。
  - READ_ONLY policy + write(WORKSPACE_WRITE) → PERMISSION_DENIED（超级别）。
  - READ_ONLY policy + read(READ_ONLY) → 放行。
  - WORKSPACE_WRITE policy + read(READ_ONLY) → 放行。
  - WORKSPACE_WRITE policy + write(WORKSPACE_WRITE) → 放行。
  - **per-call scoping**：连续两次 bash(DANGER) + auto-approve → 两次都成功（callback 被调用两次，不是一次批准后第二次跳过）。

## Out of Scope

- **Dangerous bash 命令模式匹配**（如检测 `rm -rf` / `curl` / `wget`）：V1 把整个 bash 工具标记为 DANGER，不做命令内容级分类。后者作为未来增强。
- **审批事件的 SessionEvent 持久化**（approval/requested, approval/granted, approval/denied 事件）：属 Phase 4 Operation Ledger / 审计日志范畴，本 Spec 不实现。审批是运行时内存决策。
- **Web UI / CLI 审批界面**：本 Spec 只定义 ApprovalCallback 接口和 ApprovalRequest/Response 类型，不实现具体 UI。测试用 auto-approve/auto-deny callback。
- **MCP / Plugin 工具的 permission 声明**：Phase 7/8 的工具如何声明 permission 留待那些 Phase 解决；本 Spec 只保证 Tool ABC 有默认值，所有经过 ToolExecutor 的工具都过 approval gate。

## Further Notes

- **架构不变量守护**：所有工具经过统一 ToolExecutor 路径（#7），approval gate 加在这条路径上，没有旁路。Prompt 不替代 Runtime 权限（#11 的延伸）：approval 是代码级关卡，不靠 prompt 约束模型。
- **与 Phase 4 的关系**：审批是运行时内存决策，不持久化。如果 Phase 4 要做审批审计，可以在 approval gate 里追加 SessionEvent append，但本 Spec 不做。
- **安全默认值原则**：无 callback → 拒绝（不放行）；新工具默认 WORKSPACE_WRITE（不默认 DANGER）；默认 policy = WORKSPACE_WRITE（不给 danger-full-access）。

