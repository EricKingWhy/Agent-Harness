# 10 — Multi-Agent / Delegation

## 1. 定位

Multi-Agent 是正式 V1 能力，但 MUST 建立在 Single AgentRuntime 之上。

默认提供三个 AgentProfile：
- `main`
- `coding`
- `research_review`

架构必须支持未来新增动态 Agent，而不是把三角色写死。

## 2. AgentProfile / AgentSpec

建议字段：

```text
profile_id
role
system_prompt
model_policy
tool_scope
skill_scope
context_policy
sandbox_policy
memory_policy
max_steps
budget
permissions
```

动态创建 Agent 指动态创建/实例化 `AgentSpec`，不是让 LLM 任意生成 Python Agent 类。

## 3. AgentFactory

```text
AgentSpec
→ validate permissions/capabilities
→ AgentFactory.create()
→ existing AgentRuntime
```

SubAgent MUST 复用同一 Agent Loop。

## 4. Supervisor

负责：
- 理解目标；
- 拆分任务；
- 选择/创建合适 SubAgent；
- 控制迭代；
- 判断结果是否足够；
- 最终综合。

结构化 DelegationDecision：

```text
action: delegate | create_agent | finish
target_profile/provider
task
reason
context_refs
constraints
```

`reason` 只需简短可审计理由，不要求完整思维链。

## 5. Dynamic Agent

支持：

```text
create temporary AgentSpec
→ spawn child
→ execute scoped task
→ return structured result
→ optionally continue / dispose
```

V1 需要限制：
- max active children
- max delegations
- max nesting depth
- tool scope
- budget
- sandbox write permission

## 6. SubAgentResult

只返回任务结果：

```text
agent_id
status
summary
artifacts
citations
changed_files
tests
unresolved
```

不得把完整内部 messages 倾倒给 Main。

## 7. Context Boundary

Main → SubAgent：
- 明确 task
- 必要 constraints
- 必要 artifact/file refs
- 最少 Context

SubAgent → Main：
- summary
- evidence/citations
- artifacts
- unresolved

这是 Multi-Agent 的价值之一：收窄 Context 和 Tool Permission。

## 8. Tool Permission

Coding：
- read/write/edit/bash/grep/glob/apply_patch 等；
- 默认不开放不需要的 Web 权限。

Research：
- Knowledge/Web/MCP read-only；
- 默认不开放高风险 write/bash。

动态 Agent 根据 AgentSpec 最小授权。

## 9. Sandbox

同一 Session 默认共用 Session-scoped workspace，以便 Coding 修改后 Review 能看到真实文件。

写操作仍受 dependency/resource lock 约束。

## 10. LangGraph

LangGraph 只可作为 optional orchestration：

```text
Graph State
→ agent node calls existing AgentRuntime
→ result writes back state
```

可用于：
- Supervisor routing
- Subgraph
- interrupt/resume

Graph State 应只含可序列化字段。

Graph Checkpoint MUST NOT 替代 Operation Ledger。

## 11. Spawn vs Fork 子 Agent

参考 DeepSeek Harness SubAgent seam：
- spawn：fresh child context/session；
- fork：从父 Session/Event 前缀 seed child。

Provider Registry SHOULD 允许未来：
- in-process
- fork
- ACP
- Codex
- Claude Code
- other remote agents

V1 可先实现 in-process/fork，并保留 Provider interface。

## 12. Termination

必须同时有：
- Agent `max_steps`
- Supervisor `max_delegations`
- max child depth
- repeated delegation guard

作用域不得混淆。

## 13. Acceptance Criteria

- research task 路由到 Research；
- coding task 路由到 Coding；
- mixed task 可协调；
- 默认三 profile 可运行；
- 可创建第四个临时 AgentSpec 而不改 Core；
- child 只拿最小 Context；
- SubAgentResult 不倾倒完整历史；
- max_delegations 生效；
- kill/resume 时 agent_id/operation/workspace 能恢复；
- LangGraph 未安装时 Single Agent Core 仍可运行。
