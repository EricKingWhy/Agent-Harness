# 08 — Plugin / Capability System

## 1. 目标

让 Harness 的业务能力可插拔，使未来增加 Finance 等领域能力时无需修改 Agent Core。

参考 DeepSeek Harness 的 capability seam 思想：

```text
Service Definition
→ Service Provider
→ Consumer
```

本项目采用 Python 化表达。

## 2. Capability Contract

每个 Capability 至少明确：

- Interface / Protocol
- Provider Registry
- Provider lifecycle
- Consumer
- capability descriptor
- health / availability（按需）
- permissions
- error vocabulary

## 3. Provider

Provider 负责具体实现，例如：

```text
MemoryCapability
  └─ LangMemProvider

VectorStoreCapability
  └─ MilvusProvider

ArtifactCapability
  ├─ LocalProvider
  └─ MinIOProvider

WebCapability
  └─ SearchProvider

SubAgentCapability
  ├─ in_process
  └─ future external provider
```

Provider 可多实例共存时使用命名 Registry。

## 4. Consumer

Consumer 可以是：
- 模型 Tool；
- Context Provider；
- AgentRuntime 内部服务；
- API/UI；
- another capability。

例如 Memory：
- `MemoryContextProvider` 是主要 Consumer；
- 可选 `memory_search` Tool 是另一个 Consumer。

## 5. Capability Descriptor

建议：

```text
name
version
provider_name
capabilities[]
risk
supports_streaming
supports_recovery
supports_concurrency
config_schema
```

Consumer 在使用前 SHOULD 检查 Capability 是否真的支持所需能力，不允许“接受但静默忽略”。

## 6. Plugin Discovery

V1 可以先使用显式配置加载：

```yaml
capabilities:
  memory:
    provider: langmem
  artifacts:
    provider: minio
```

后续可扩展 Python entry points / package discovery。

不要一开始实现复杂 Marketplace。

## 7. Graceful Degradation

Capability 分三类：

- REQUIRED_CORE：缺失则 Agent Core 无法启动；
- OPTIONAL_RUNTIME：缺失则功能不可用但基础 Agent 可运行；
- OPTIONAL_OBSERVABILITY：缺失不得影响业务执行。

Memory、Langfuse、Web、Knowledge 默认属于 OPTIONAL。

## 8. Finance 等未来扩展

未来 Finance 插件可以包含：

```text
Finance Capability
├─ tools/
├─ context providers/
├─ skills/
├─ agent profiles/
└─ provider adapters/
```

但 MUST NOT 要求修改 `core/agent_loop.py`。

## 9. Acceptance Criteria

- 切换 Memory Provider 不改 Core；
- 切换 Artifact Provider 不改 ContextBuilder Contract；
- MCP/Knowledge/Web 可以按配置启停；
- Provider 不支持能力时明确报错；
- Optional Provider 故障可以降级；
- 插件不能绕过 Tool Permission / Operation Ledger。
