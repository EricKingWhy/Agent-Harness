# #8 — Ticket B: derive_messages 纯函数 + dangling 处理 + 单元测试

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T12:00:58Z
- **Closed**: 2026-09-03T12:35:25Z
- **Parent**: #6
- **Blocked by**: #7
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/8

---

## Parent

#6 (Phase 1 SessionEvent spec)

## What to build

从 SessionEvent 序列投影出模型可见 messages 列表的纯函数。这是连接事件事实源与模型调用的关键桥梁。

完整垂直切片：给定一段事件序列，产出符合 OpenAI/Anthropic/LangChain 标准的 messages 列表，包括 tool_call/tool_result 配对和 dangling 检测。

## Acceptance criteria

- [ ] `derive_messages(events: list[SessionEvent]) -> list[AnyMessage]` 纯函数，无副作用
- [ ] 纯对话事件（user/message + model/completed）投影成 HumanMessage + AIMessage
- [ ] tool/call + tool/result 按 tool_call_id 配对成 AIMessage(tool_calls=[...]) + ToolMessage
- [ ] 一次 model/completed 带多个 tool_calls 时，投影成一条 AIMessage + 多条 ToolMessage（以 AIMessage 为单位）
- [ ] dangling tool_call（有 tool/call 无匹配 tool/result）检测后注入合成 ToolMessage，content 写明"工具执行被中断，结果未知"
- [ ] 合成 ToolMessage 的 tool_call_id 与原 tool/call 匹配
- [ ] dangling 检测时打印 WARN 日志告知调试者
- [ ] 单元测试覆盖：纯对话、单工具配对、多工具单轮配对、dangling 注入、混合场景
- [ ] ruff clean

## Blocked by

- #7 (Ticket A — 需要 SessionEvent DTO 定义)
