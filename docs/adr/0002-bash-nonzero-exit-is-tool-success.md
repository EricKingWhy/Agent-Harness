# bash 非零 exit_code 归为 Tool 调用成功

bash 工具的 `ToolResult` 永远 `ok=True`（除非 Sandbox 本身崩溃），shell 命令的
`exit_code / stdout / stderr` 放进 `ToolResult.data` 供模型读取。非零 exit_code（如 pytest 不通过）
不是 Tool Runtime 异常——它不进 `ErrorCode` 词汇表、不触发 `ToolExecutor` 的重试层。

**Considered Options**:
- 新增 `ErrorCode.NONZERO_EXIT` 把 exit_code!=0 标为失败（被否）：违背 SourcePlan 核心命题
  "命令业务成功 ≠ Tool 调用成功"，且会让 `ToolExecutor` 的 `retryable` 驱动误把测试失败当
  可重试错误，污染 Day4 已冻结的 `ErrorCode` 语义。

**Consequences**:
- `ErrorCode` 词汇表保持六类不变，命令业务失败的语义在 `data.exit_code` 里读，不在错误码里。
- 模型必须自己读 stdout/stderr 判断"是不是真失败了"——这是预期行为，不是缺陷。
- 未来若要"测试失败自动重跑"，应由 Agent 层决策，不是 ToolExecutor 自动重试。
