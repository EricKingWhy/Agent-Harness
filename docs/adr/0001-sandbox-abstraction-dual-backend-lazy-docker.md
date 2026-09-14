# Sandbox 抽象 + 双后端 + Docker 懒加载

定义 `Sandbox` 契约（`ensure_started / exec / read_text / write_text / copy_in / stop`）一次定全，
切片 1 同时实现两个后端：`LocalSubprocessSandbox`（本机子进程，开发/测试默认、零外部依赖）和
`DockerSandbox`（生产/隔离，基于 docker-py）。`docker` 不进 `pyproject.toml` 硬依赖，
`DockerSandbox.__init__` 内懒加载 `import docker`，失败抛 `RuntimeError`。

**Considered Options**:
- 单 Docker 后端（被否）：测试被 daemon 绑死，破坏"默认套零外部依赖"的工程传统；
  开发循环每次都要启 Docker Desktop，启动开销真实。
- 引入 autogen-ext 执行器（被否）：其 `execute_code_blocks(CodeBlock)` 抽象是"执行代码块"，
  与我们的 `Tool` 契约（结构化参数 → `ToolResult`）是两种世界观，硬接会污染 Day4 的执行域，
  且把 AutoGen 整套框架依赖拖进来。

**Consequences**:
- 默认测试套永远绿、零 Docker 依赖；Docker 真容器测试单独 `skipif` 标记。
- 未来加第三种后端（远程 VM / gVisor / OCI 直跑）零成本，只需实现 `Sandbox` 契约。
- 代价：多一层抽象、两个后端要分别维护；切片 1 工程量比"只做 Docker"大。
