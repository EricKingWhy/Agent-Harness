# #3 — Ticket 2: DockerSandbox（docker-py 懒加载）

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T07:39:32Z
- **Closed**: 2026-09-03T11:12:34Z
- **Parent**: #1
- **Blocked by**: #2
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/3

---

## Parent

#1 (Day05 切片 1：Sandbox 抽象 + read/write/bash Coding Tools)

## What to build

实现第二个 Sandbox 后端 `DockerSandbox`：基于 docker-py，镜像默认 `python:3-slim`，容器内 workspace 为 `/workspace`。命令通过 `container.exec_run` 执行，文件读写通过 `docker cp` 或 exec 实现。`docker` 依赖**懒加载**——不进 `pyproject.toml`，`DockerSandbox.__init__` 内 `import docker`，导入失败抛 `RuntimeError("DockerSandbox 需要 pip install docker")`。

测试用 `@pytest.mark.skipif(not _docker_available())` 守护（检查 daemon 可达），默认套自动跳过，不影响无 daemon 环境。

## Acceptance criteria

- [ ] `DockerSandbox` 实现 Sandbox ABC 全部 6 方法
- [ ] `docker` 在 `__init__` 内懒加载 import，不在模块顶层、不进 pyproject.toml
- [ ] 无 docker-py 时构造 DockerSandbox 抛清晰 RuntimeError
- [ ] daemon 开着时，DockerSandbox.exec / read_text / write_text / copy_in 在真实容器里行为正确
- [ ] 路径越界在容器内同样被拒绝（workspace=/workspace 边界）
- [ ] 测试 `@pytest.mark.skipif` 守护，daemon 不可用时跳过，默认套全绿
- [ ] ruff 通过

## Blocked by

- #2 (Ticket 1: Sandbox 契约 + LocalSubprocessSandbox)

