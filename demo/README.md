# Live Agent Demo

把项目已造好的零件（`AgentRuntime` + 9 个 Coding Tools + `LocalSubprocessSandbox` + `SessionEvent` 持久化）接成一只**你能用眼睛看见的 agent**：终端里输入任务，看它一轮轮思考、调工具、被审批拦、给最终回答。

这个 demo 只读取/复用项目现有 API，**不修改任何框架代码、不影响 spec / roadmap**。GitHub Issues 仍是事实源。

## 前置

`.env` 里配好模型（和集成测试一样）：

```
MODEL_NAME=qwen3.8-flash
MODEL_API_KEY=...
```

依赖：`uv sync` 会装上 `rich`（dev 依赖）。

## 跑

```bash
# 交互模式：每输一行就是一个任务，:q 退出
uv run python demo/live_agent.py

# 单次任务
uv run python demo/live_agent.py --task "在 workspace 建个 hello.py 跑一下"

# 指定 workspace / session 存放目录 / 最大轮数
uv run python demo/live_agent.py --workspace ./_demo_workspace --store ./_demo_sessions --max-steps 10
```

## 审批模式（默认安全 vs 放手干）

Phase 3 的 Approval 机制默认安全：`bash` 这种 `DANGER` 级工具在 `WORKSPACE_WRITE` 策略下会被审批关卡拦住。Demo 给两个旋钮：

| 模式 | 命令 | 行为 |
|---|---|---|
| **自动批准**（默认） | `uv run python demo/live_agent.py` | `WORKSPACE_WRITE` 策略 + 自动批准回调。每次危险操作触发审批，回调自动放行。能看见审批被触发又被批准。 |
| **手动审批** | `--approve ask` | 同上策略，但每次危险操作停下来问你 `y/n`。 |
| **全放行（yolo）** | `--yolo` | `DANGER_FULL_ACCESS` 策略，完全绕过审批关卡。任何工具直接执行。 |

## 你会看到什么

每跑一次任务，demo 把这次产生的每个 `SessionEvent` 渲染成一个彩色面板，按 seq 顺序实时滚出：

- 🟢 `user/message` —— 你的任务
- 🔵 `run/started` —— Agent Loop 开始
- 🟣 `model/completed` —— 模型这一轮的思考（要么是最终回答，要么列出要调的工具 + 参数）
- 🟡 `tool/call` + `tool/result` —— 工具调用与结果（带 ✓ ok / ✗ PERMISSION_DENIED 标记）
- 🔵 `run/completed` —— 最终回答 + 状态

末尾会指出本次 session 的 JSONL 事件事实源路径——这是 Phase 1 的 event-sourced 恢复锚点，进程重启后能从这里 resume。

## 为什么有这个 demo

这个项目是 Agent Harness（框架），不是终端应用；zcode/codex 把能力全造好了，但没有面向人的入口——`src/agent_harness/cli.py` 还是早期占位，没接 `AgentRuntime`、没接 9 个工具。这个 demo 让你今天就能看见 agent 在干活，不用等 Phase 10 的 Web UI。

如果你想把 `cli.py` 也升级到能交互（不只是 demo），或提前做 Phase 10 的 Web Inspector，那是另外的 scope——告诉我再开。
