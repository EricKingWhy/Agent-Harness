# #1 — Day05 切片 1：Sandbox 抽象 + read/write/bash Coding Tools

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T07:34:19Z
- **Closed**: 2026-09-03T13:04:30Z
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/1

---

# Day05 切片 1：Sandbox 抽象 + read/write/bash Coding Tools

## Problem Statement

Agent 目前只能调用 `add` / `boom` 这类演示工具，无法在隔离工作空间内真正完成 Coding 任务。要让 Agent 真正"会写代码"，它必须能读文件、写文件、在受控环境里跑 shell 命令（如 pytest），并基于命令结果继续决策。这些操作必须在一个有明确安全边界的 Sandbox 内执行，而非直接在用户宿主机上裸跑。

## Solution

引入 `Sandbox` 抽象契约（6 个方法：`ensure_started / exec / read_text / write_text / copy_in / stop`），切片 1 同时实现两个后端：`LocalSubprocessSandbox`（本机子进程，开发/测试默认、零外部依赖）和 `DockerSandbox`（生产隔离，基于 docker-py）。在 Sandbox 之上实现三个 Coding Tool（`read` / `write` / `bash`），按现有 `Tool` 契约暴露给模型，接入 AgentRuntime 的 ToolExecutor 执行链。Agent 能在 workspace 内完成"写测试文件 → 跑 pytest → 读失败 → 给回答"的真实闭环。

## User Stories

1. 作为 Agent 开发者，我想要一个 Sandbox 抽象层，这样read/write/bash 等Coding Tool 不绑定具体执行环境（本地或 Docker）。
2. 作为 Agent 开发者，我想要一个 LocalSubprocessSandbox，这样开发和测试时不需要 Docker daemon 也能跑通完整工具链。
3. 作为 Agent 开发者，我想要一个 DockerSandbox，这样生产环境下 Agent 的命令执行有真正的容器级隔离。
4. 作为 Agent，我想要一个 read 工具，这样我能读取 workspace 内的文本文件以理解项目现状。
5. 作为 Agent，我想要一个 write 工具，这样我能覆盖写入文件来创建或修改代码。
6. 作为 Agent，我想要一个 bash 工具，这样我能在 workspace 内执行 shell 命令（如 pytest、ls、cat）并获得 exit_code / stdout / stderr。
7. 作为 Agent，当我用 bash 跑 pytest 且测试失败（exit_code=1）时，我希望 ToolResult.ok=True 且 exit_code 在 data 里，这样我能读到 stdout/stderr 自主决定下一步，而不是被 ToolExecutor 当成可重试错误自动重试。
8. 作为 Agent 开发者，我希望 Sandbox 统一强制 workspace 路径边界，这样即使模型尝试访问 workspace 外的宿主机敏感路径（如 `../../etc/passwd`），也会被拒绝而非静默执行。
9. 作为 Agent 开发者，我希望默认测试套不依赖 Docker daemon，这样 CI 和本地开发永远绿。
10. 作为 Agent 开发者，我希望 Docker 真容器测试在 daemon 不可用时自动跳过，这样不影响默认套。
11. 作为 Agent 开发者，我希望 `docker` 依赖是懒加载的（不进 pyproject.toml 硬依赖），这样只用 LocalSubprocessSandbox 的用户不需要装 docker-py。
12. 作为 Agent 开发者，我想要一个真实 LLM 驱动的端到端集成测试，这样能验证 Agent 真的能在 sandbox 里完成 Coding 闭环（非剧本驱动的确定性测试）。
13. 作为 Agent 开发者，我希望集成测试在无 API key 时自动跳过，这样默认套不烧 token、不挂。

## Implementation Decisions

### Sandbox 抽象契约（一次定全 6 方法）
- `ensure_started() -> None`：惰性启动执行环境（LocalSubprocess 是 no-op；Docker 起容器）。
- `exec(command: str, *, timeout: float | None = None) -> ExecResult`：执行 shell 命令，返回 `ExecResult(exit_code: int, stdout: str, stderr: str, duration_ms: float)`。
- `read_text(path: str) -> str`：读 workspace 内文件，返回文本。
- `write_text(path: str, content: str) -> None`：覆盖写 workspace 内文件。
- `copy_in(host_path: Path, workspace_path: str) -> None`：把宿主文件拷入 workspace（LocalSubprocess 是复制到 workspace 目录；Docker 是 docker cp）。切片 1 的 LocalSubprocessSandbox 实现该方法；DockerSandbox 实现该方法。
- `stop() -> None`：清理执行环境（LocalSubprocess 可选清理；Docker 停容器）。

### ExecResult 是 Sandbox 层的原生返回
- `ExecResult` 是一个 dataclass（`exit_code: int / stdout: str / stderr: str / duration_ms: float`）。
- Sandbox 不感知 `ToolResult`；bash 工具负责 `ExecResult → ToolResult` 映射。

### 双后端实现
- `LocalSubprocessSandbox(workspace_root: Path)`：在本机子进程执行命令（`subprocess.run`），workspace_root 是本机一个真实目录。所有路径 resolve 后校验 `is_relative_to(workspace_root)`，越界拒绝。
- `DockerSandbox(image: str = "python:3-slim", workspace: str = "/workspace", ...)`：基于 docker-py，惰性 `import docker`。容器挂载 workspace volume，命令通过 `container.exec_run` 执行。
- 两个后端都实现完整 6 方法契约。

### docker 依赖懒加载
- `docker` 不进 `pyproject.toml`。
- `DockerSandbox.__init__` 内 `import docker`，导入失败抛 `RuntimeError("DockerSandbox 需要 pip install docker")`。
- `LocalSubprocessSandbox` 不触发 docker import。

### workspace 路径边界在 Sandbox 层强制
- 所有接受路径的方法（`read_text` / `write_text` / `copy_in`）把传入路径 `Path.resolve()` 后校验是否在 workspace 内。
- 越界抛 `PermissionError` 或返回明确拒绝（由 Tool 层捕获映射成 `ErrorCode.PERMISSION_DENIED`）。
- Tool 层不做路径校验（单一职责）。

### 三个 Coding Tool 按现有 Tool 契约实现
- `ReadTool`：`side_effect = READ_ONLY`；`args_schema` 含 `path: str`；execute 调 `sandbox.read_text(path)`，成功返回 `ToolResult.success(data={"content": ...})`。
- `WriteTool`：`side_effect = MUTATING`；`args_schema` 含 `path: str, content: str`；execute 调 `sandbox.write_text(path, content)`，成功返回 `ToolResult.success()`。
- `BashTool`：`side_effect = MUTATING`（默认 mutating，保守）；`args_schema` 含 `command: str`；execute 调 `sandbox.exec(command)`，**无论 exit_code 几**都返回 `ToolResult.ok=True`，`data = {exit_code, stdout, stderr, duration_ms}`。只有 Sandbox 本身抛异常（如容器崩了）才返回 `ToolResult.failure`。

### bash 非零 exit_code 的语义（ADR-0002）
- bash 工具的 `ToolResult.ok` 永远 `True`（除非 Sandbox 崩溃）。
- 非零 exit_code 不是 Tool Runtime 异常，不进 `ErrorCode`，不触发 `ToolExecutor` 重试。
- `exit_code / stdout / stderr / duration_ms` 在 `ToolResult.data` 里供模型读取。

### Sandbox 与 Tool 的接线
- Coding Tool 在构造时绑定一个 `Sandbox` 实例（`ReadTool(sandbox=...)`）。
- AgentRuntime 构造时把 Sandbox 实例注入 Tool 实例，再注册进 ToolRegistry。
- ToolExecutor 不感知 Sandbox（它只调 `tool.execute(validated_args)`）。

### 新增模块结构
- `src/agent_harness/sandbox/__init__.py`
- `src/agent_harness/sandbox/base.py`（`Sandbox` ABC + `ExecResult` dataclass）
- `src/agent_harness/sandbox/local.py`（`LocalSubprocessSandbox`）
- `src/agent_harness/sandbox/docker.py`（`DockerSandbox`）
- `src/agent_harness/tools/__init__.py`
- `src/agent_harness/tools/read.py`（`ReadTool`）
- `src/agent_harness/tools/write.py`（`WriteTool`）
- `src/agent_harness/tools/bash.py`（`BashTool`）

### 模型配置
- 集成测试使用阿里 qwen 模型，配置走现有 `.env`（MODEL_API_KEY / MODEL_BASE_URL / MODEL_NAME）。
- API key 存 `.env`，不进 git。

## Testing Decisions

### 测试哲学
只测外部行为，不测实现细节。复用现有测试结构，最高位缝优先。

### 测试缝 1：Sandbox 抽象层（`tests/sandbox/`）
- 用 `LocalSubprocessSandbox` 跑全部契约测试（零 Docker 依赖）。
- 测：`exec` 返回正确 `ExecResult`；`read_text` / `write_text` 正常读写；**路径越界拒绝**（核心安全不变量，`../../` escape 测试）；`ensure_started` / `stop` 幂等。
- 先例：`tests/tooling/test_executor.py` 的"构造输入 → 调方法 → 断言返回形状"风格。

### 测试缝 2：Coding Tool 层（`tests/tools/`）
- 每个 Tool 单独测：参数 schema 校验（非法参数 → `INVALID_ARGUMENT`）；`side_effect` 分类正确；`ExecResult → ToolResult` 映射正确；bash 非零 exit_code 仍是 `ok=True`（ADR-0002 不变量）；read/write 成功路径。
- 复用现有 `ToolExecutor.execute(tool_call_dict)` 调用方式。
- 先例：`tests/tooling/test_executor.py`。

### 测试缝 3：AgentRuntime 端到端集成（`tests/agent/test_agent_loop_docker_integration.py`）
- 真实 qwen LLM + `LocalSubprocessSandbox` + 注册 read/write/bash 的 Registry + ToolExecutor。
- 验证完整闭环：Agent 收到指令（如"在 workspace 写一个会失败的 pytest 测试文件，然后跑 pytest"），真实写文件、真实跑命令、读到 exit_code=1、给最终回答。
- `@pytest.mark.skipif(无 API key)` 守护，默认套不跑。
- 先例：`tests/agent/test_agent_loop.py`（但用真实模型替代 ScriptedModel）。

### Docker 真容器测试
- `tests/sandbox/test_docker_sandbox.py`：`@pytest.mark.skipif(not _docker_available())` 守护。
- daemon 不可用时自动跳过，不影响默认套。
- 验证 DockerSandbox 的 6 方法在真实容器里行为正确。

### 默认套保证
- 无 Docker daemon、无 API key 时，所有新增测试要么自动 skip、要么用 LocalSubprocessSandbox，默认套永远绿。

## Out of Scope

- **edit 工具**（old_string → new_string 精准替换 + 多匹配 AMBIGUOUS 拒绝）——进切片 2。
- grep / glob / apply_patch 工具。
- git 专用工具。
- Session-scoped Sandbox（跨多次 run 复用容器）。
- MCP 接入。
- Artifact Store（大输出引用）。
- Context Compaction。
- RAG。
- Docker 镜像自定义 / Dockerfile 编写（切片 1 用官方 `python:3-slim`）。
- 并发执行多个 Sandbox 实例的隔离测试。

## Further Notes

- 相关 ADR：`docs/adr/0001-sandbox-abstraction-dual-backend-lazy-docker.md`、`docs/adr/0002-bash-nonzero-exit-is-tool-success.md`。
- 领域词汇表：`CONTEXT.md`（Sandbox / Workspace / Coding Tool / ExecResult / 命令业务失败 等）。
- 历史需求来源：`goal/新计划/Day04-Day14_New_SourcePlans/05_Day05_DockerSandbox_CodingTools_SourcePlan.md`（教学语言已剥离，工程需求提炼为本 spec）。
- docker-py 仓库：https://github.com/docker/docker-py （7.2k★, Docker 官方 SDK, Apache-2.0）。
- 切片 2 预告：edit 工具 + edit 的 AMBIGUOUS 拒绝测试 + DockerSandbox 更深入的故障注入测试。

