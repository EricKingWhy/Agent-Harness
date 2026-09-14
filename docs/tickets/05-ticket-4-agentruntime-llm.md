# #5 — Ticket 4: AgentRuntime 端到端集成（真实 LLM）

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T07:40:37Z
- **Closed**: 2026-09-03T13:04:26Z
- **Parent**: #1
- **Blocked by**: #4
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/5

---

## Parent

#1 (Day05 切片 1：Sandbox 抽象 + read/write/bash Coding Tools)

## What to build

真实 qwen LLM 驱动的端到端集成测试：构造 AgentRuntime（真实模型 + LocalSubprocessSandbox + 注册了 read/write/bash 的 ToolRegistry + ToolExecutor），让 Agent 在 workspace 里完成一次真实 Coding 闭环——收到指令（如"在 workspace 写一个会失败的 pytest 测试文件，然后跑 pytest 看结果"），真实调用 write 写文件、bash 跑 pytest、read 读失败日志、给最终回答。

测试用 `@pytest.mark.skipif(无 API key)` 守护，默认套不跑、不烧 token。同时把 qwen 的 key/url/name 配进 `.env`（不进 git）。

## Acceptance criteria

- [ ] `.env` 配好 qwen 模型（MODEL_API_KEY / MODEL_BASE_URL / MODEL_NAME），.gitignore 已忽略
- [ ] 集成测试构造完整 AgentRuntime（真实模型 + LocalSubprocessSandbox + read/write/bash Registry）
- [ ] Agent 真实调用 write 写文件到 workspace，文件确实存在
- [ ] Agent 真实调用 bash 跑 pytest，拿到 exit_code/stdout/stderr
- [ ] Agent 最终 status == COMPLETED，给出了有意义的回答
- [ ] `@pytest.mark.skipif(无 API key)` 守护，无 key 时跳过，默认套全绿
- [ ] ruff 通过

## Blocked by

- #4 (Ticket 3: Coding Tools（read / write / bash）)

