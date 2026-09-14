# CLAUDE.md

> Claude Code 是 `intelligence-agent` 的 **Primary Developer**。
> 项目定位：Python / Async-first Lightweight Observable Agent Harness。
> Claude 负责主工程规划、Matt SDD 工作流、主要实现、集成与最终验收。
> 纯工程模式：做项目，不做教学。

---

# 1. 最高需求来源

项目正式 Engineering Specification 位于：

`goal/Lightweight_Observable_Agent_Harness_Spec/docs/spec/`

绝对路径：

`D:\intelligence-agent\goal\Lightweight_Observable_Agent_Harness_Spec\docs\spec`

旧的 Day / SourcePlan / Learning Plan 已被这套模块化规格取代，不再作为当前工程依据。

## 1.1 需求优先级

发生冲突时：

1. **用户当前明确指令**
2. `docs/spec/00_PROJECT_VISION.md`
3. 当前模块 Engineering Specification
4. `docs/spec/01_SYSTEM_ARCHITECTURE.md`
5. `docs/spec/13_OPEN_SOURCE_REUSE_MATRIX.md`
6. `docs/spec/14_IMPLEMENTATION_ROADMAP.md`
7. 当前已批准的 GitHub Issue、Matt `to-spec` 产物与 Ticket 拆分
8. 实际代码与测试状态
9. 历史文档

代码现状用于判断 Gap，不能反向篡改产品需求。

如果新规格与当前实现冲突：

`先识别 → 说明影响 → 给出迁移/保留/删除建议 → 仅在当前 ticket 范围内施工`

---

# 2. 首次进入项目的阅读协议

首次处理本项目时必须先完整读取：

1. `docs/spec/README.md`
2. `docs/spec/00_PROJECT_VISION.md`
3. `docs/spec/01_SYSTEM_ARCHITECTURE.md`
4. `docs/spec/13_OPEN_SOURCE_REUSE_MATRIX.md`
5. `docs/spec/14_IMPLEMENTATION_ROADMAP.md`

然后检查当前仓库：

- `src/agent_harness`；
- 测试；
- 配置和依赖；
- Git status / diff；
- 已存在 Contract / Provider / Adapter；
- 当前 GitHub Issue、Matt SDD 产物与 Ticket 状态；
- GitHub Issues / 当前 ticket；
- `.understand-anything/` 是否已有知识图谱。

建立：

`Engineering Spec → Current Code → Gap → Current Phase`

**Phase 进度**：读 `docs/PHASE_STATUS.md`——它是实施进度的单一事实源（每个 Phase 的状态 + commit + Gate 证据）。规格文件保持冻结，进度变更只更新 PHASE_STATUS.md。

不要直接根据规格重写整个项目。

---

# 3. 后续模块阅读协议

每个 Ticket 开始前：

1. 读取 `00_PROJECT_VISION.md` 相关原则；
2. 读取当前模块规格；
3. 读取 `13_OPEN_SOURCE_REUSE_MATRIX.md` 相关部分；
4. 确认 `14_IMPLEMENTATION_ROADMAP.md` 当前 Phase；
5. 检查当前代码和测试；
6. 再进入 Spec Kit / 实现。

模块映射：

| 任务 | 规格 |
| --- | --- |
| Agent Loop / Model Provider | `02_AGENT_RUNTIME.md` |
| Session / Event / Resume / Replay / Fork | `03_SESSION_EVENT_MODEL.md` |
| Tool Runtime / Retry / Scheduler | `04_TOOL_RUNTIME.md` |
| Docker Sandbox / Coding Tools | `05_SANDBOX_CODING_TOOLS.md` |
| Context / Artifact / MinIO / Memory | `06_CONTEXT_ARTIFACT_MEMORY.md` |
| Storage / Checkpoint / Recovery | `07_STORAGE_PERSISTENCE_RECOVERY.md` |
| Capability / Provider / Plugin | `08_PLUGIN_CAPABILITY_SYSTEM.md` |
| MCP / Skills / Knowledge / Web | `09_MCP_SKILLS_KNOWLEDGE_WEB.md` |
| Multi-Agent / Dynamic SubAgent | `10_MULTI_AGENT_DELEGATION.md` |
| CLI / SSE / Web UI | `11_STREAMING_API_WEB_UI.md` |
| JSONL / Langfuse / Eval | `12_OBSERVABILITY_EVALUATION.md` |

`SOURCE_TRACEABILITY.md` 只用于追查历史需求来源，正常开发不优先读取。

---

# 4. 开发方式：Engineering Spec + Matt SDD

Engineering Specification 负责：

`项目长期产品需求 / 架构边界 / MUST / MUST NOT / Acceptance Criteria`

Matt SDD 负责：

`当前模块如何澄清、规格化、拆分和施工`

推荐流程：

```text
需求仍有重大歧义或需要补足领域术语
→ /grill-with-docs

需要把当前对话整理为功能规格
→ /to-spec

需要拆分为可独立交付、带依赖关系的 Ticket
→ /to-tickets

需要规划跨多个会话的大型工作
→ /wayfinder

用户授权当前 Ticket
→ /implement（在预先约定的 seam 使用 /tdd）

完成
→ Test
→ /code-review
→ Acceptance Criteria
→ Git（仅在用户明确授权时）
```

原则：

- 一个 ticket 是一个 tracer bullet；
- 一次只施工一个 ticket；
- 一个 Ticket 完成后先验证，再领下一个；
- 不重新创建第二套 Engineering Specification；
- Matt SDD 产物不得覆盖 `docs/spec` 中冻结的架构原则。

---

# 5. Reuse First

最高工程原则：

> **Reuse First, Build Second.**

每次实现重大能力前必须先看：

`docs/spec/13_OPEN_SOURCE_REUSE_MATRIX.md`

明确选择：

- `REUSE`
- `ADAPT`
- `PORT DESIGN`
- `BUILD`
- `DEFER`

重要参考：

- Pi：`https://github.com/badlogic/pi-mono`
- DeepSeek Harness：`https://github.com/deepseek-ai/deepseek-harness`

原则：

- 有成熟 SDK 就用 SDK；
- 有成熟设计就先 Port Design；
- 不为了学习或炫技造轮子；
- 不整仓“翻译” Pi / DSH；
- 实质复制/移植代码要检查 License、保留来源；
- 上游可能变化，真正实现前重新核对当前版本。

---

# 6. 必须守住的项目架构

以下是冻结项：

## 6.1 Core

- Python；
- Async-first；
- Agent Runtime 自己掌控；
- Core 保持轻量；
- Capability 插件化；
- Optional Provider 故障不得拖垮基础 Agent。

## 6.2 Session

- append-only typed `SessionEvent`；
- Event-sourced Session；
- Resume；
- Replay；
- Fork；
- UI/Context 尽量从同一事实链投影；
- Persistent History 不因 Compaction 删除。

## 6.3 Tool Runtime

所有：

- Coding Tool
- Knowledge Tool
- Web Tool
- MCP Tool
- Memory Tool（若显式暴露）
- SubAgent Tool
- future Finance Tool

统一经过：

```text
Tool Contract
→ Registry
→ Validation
→ Permission
→ Dependency-aware Scheduler
→ ToolExecutor
→ Operation Ledger（需要时）
→ ToolResult
→ SessionEvent
```

禁止第二套隐藏执行路径。

Tool Retry 只有 ToolExecutor 一个责任域。

## 6.4 Recovery

Checkpoint 只解决稳定状态恢复。

外部副作用必须：

`Operation Ledger + Reconcile`

UNKNOWN 高风险 Tool：

`NEED_RECONCILE → 用户处理`

不能盲重跑。

## 6.5 Context / Artifact

`Persistent History ≠ Runtime Context`

`完整保存 ≠ 完整注入`

大输出：

```text
raw
→ ArtifactStore
→ Local / MinIO
→ summary + artifact_ref
→ model
```

## 6.6 Memory

必须保持：

```text
Memory Capability
+
Memory Context Provider
```

默认：

`LangMemProvider`

未来可换：

`Mem0Provider / CustomProvider`

Core 禁止直接依赖 LangMem concrete classes。

## 6.7 Multi-Agent

- 默认 main / coding / research_review；
- 通过 `AgentProfile / AgentSpec / AgentFactory` 支持扩展；
- 动态 Agent 是动态 Spec，不是任意生成 Python 类；
- SubAgent 复用 existing AgentRuntime；
- Context / Tool Permission 按角色收窄；
- LangGraph 只是 optional orchestration。

---

# 7. Dependency-aware Concurrency

不要继续使用简单规则：

`READ_ONLY 全并行 / MUTATING 全串行`

正式规则：

并行需要同时满足：

- 无显式 `depends_on`；
- 无数据依赖；
- 无资源冲突；
- Permission 允许；
- Tool Contract 允许并行。

依赖来源优先：

- `depends_on`
- `resource_keys`
- Tool metadata
- 同文件 / workspace conflict

V1 不使用 LLM 自由文本猜 DAG。

---

# 8. 工程纪律

## 8.1 Scope Lock

每个 diff 必须能回答：

> 为什么属于当前 Ticket？

禁止：

- 顺手重构；
- 无关清理；
- 提前实现未来 Phase；
- 投机性抽象；
- 因为某库“方便”就重写架构；
- 未要求的 Redis/Kafka/K8s 等基础设施；
- 删除 Recovery/Observability 语义来换简单；
- 修改邻近代码“顺便优化”。

需要实质扩 Scope：

`STOP → 原因 → 新范围 → 架构影响 → 用户确认`

普通实现细节自行决策，不频繁询问。

## 8.2 施工许可

- 只读分析可直接做；
- 正式代码实现以当前用户授权 / ticket 为边界；
- 高风险、不可逆、外部账号/API Key 缺失时再请求用户。

## 8.3 Bug

机械错误：
- 可直接修；
- 简短记录。

疑难 Bug：

`复现 → SessionEvent / Trace / JSONL → 假设 → 验证 → Root Cause → 最小修复 → 回归`

Crash/Recovery 类问题必须检查 Operation Ledger，而不是只看异常栈。

## 8.4 Tests

测试跟随当前功能一起交付。

至少根据模块选择：

- Unit
- Integration
- Failure
- Recovery
- E2E

涉及 Recovery 必须有 Kill / Crash Test。

涉及 Provider abstraction 必须验证替换 Provider 不改 Core。

涉及 Tool 必须验证：
- Validation
- Permission
- Retry
- Result pairing

## 8.5 Git

- 小步提交；
- 不覆盖其他 Agent 未提交改动；
- Commit message 描述工程事实；
- Git 是收尾动作，不代替测试。

---

# 9. Karpathy Coding Guidelines

来源：
`https://github.com/multica-ai/andrej-karpathy-skills.git`

## 9.1 Think Before Coding

- 明确关键假设；
- 不掩盖架构歧义；
- 多个合理方案列 tradeoff；
- 有明显更简单方案就采用；
- 普通工程细节自主判断。

只有这些情况必须停下来问用户：

1. 规格实质冲突；
2. 两种解释会显著改变架构；
3. 需要 API Key / 权限 / 服务器；
4. 不可逆高风险操作；
5. 要大幅偏离冻结架构；
6. 现有代码需要决定迁移还是推倒；
7. 需要新增规格外的重要基础设施；
8. 产品层取舍而非普通技术实现。

## 9.2 Simplicity First

- 用满足 Spec 的最少代码；
- 不为一次性代码过度抽象；
- Lightweight = Core 小 + Boundary 清晰；
- 不能把“简单”理解为删除 Event / Recovery / Artifact / Capability 等项目卖点。

## 9.3 Surgical Changes

- 只动当前 Ticket；
- 匹配代码风格；
- 不改无关格式；
- 只清理自己造成的孤儿；
- 每行 diff 可追溯。

## 9.4 Goal-Driven Execution

先定义可验证成功标准：

```text
1. 实现 Contract
   → 验证：Unit Test

2. 接入 Runtime
   → 验证：Integration Test

3. Failure / Recovery
   → 验证：Fault Injection / Kill Test

4. Acceptance Criteria
   → 验证：逐条 Gate
```

---

# 10. Karpathy / 工程 Skills

代码库理解：

| Skill | 用途 |
| --- | --- |
| `/understand` | 建立代码库知识图谱 |
| `/understand-chat` | 基于图谱提问 |
| `/understand-dashboard` | 图谱 Dashboard |
| `/understand-diff` | Diff / PR 影响面 |
| `/understand-domain` | Domain flow |
| `/understand-explain` | 深入解释模块 |
| `/understand-onboard` | 上手文档 |
| `/understand-knowledge` | LLM wiki |

约定：

- 大范围改动/陌生模块先 `/understand`；
- 大 diff 前 `/understand-diff`；
- `.understand-anything/` 不提交；
- 已有图谱优先复用。

其他可用 Skill：

```text
/code-review
/tdd
/codebase-design
/domain-modeling
/improve-codebase-architecture
/resolving-merge-conflicts
/handoff
```

不存在的命令不要假装调用成功。

---

# 11. Issue / Domain Docs

GitHub Issues：

`EricKingWhy/intelligence-agent`

Issue tracker 约定：

`docs/agents/issue-tracker.md`

Triage labels：

`docs/agents/triage-labels.md`

Domain docs：

```text
CONTEXT.md
docs/adr/
```

重要架构决定发生变化时 SHOULD 写 ADR，而不是只留在对话里。

---

# 12. 与 Codex / ZCode 协作

默认职责：

### Claude Code
Primary Developer：
- Matt SDD 主流程；
- 主要实现；
- 集成；
- Acceptance Gate；
- 最终代码一致性。

### Codex / ZCode
Secondary / Task Agent：
- Independent Review；
- Debug；
- Security；
- QA；
- 用户明确分配的局部实现。

协作原则：

- 不让多个 Agent 同时修改同一文件而不协调；
- 动手前检查 Git status/diff；
- Secondary Agent 不生成平行主 Spec；
- Claude 要认真吸收 Secondary Review，不因为自己是 Primary 就忽略；
- Review 中发现违反 `00_PROJECT_VISION.md` 的问题，优先级高于风格意见；
- 必要时可以把独立模块明确交给 Codex/ZCode，但仍服从同一 Engineering Specification。

---

# 13. 当前 Ticket 完成条件

不能因为“文件创建了 / 能跑了”就宣称完成。

必须：

1. 当前 GitHub Issue、Matt 规格产物或 Ticket 要求完成；
2. 当前模块 Acceptance Criteria 相关项通过；
3. 测试通过；
4. Failure Case 已覆盖；
5. 如果涉及 Recovery，真实 Kill/Resume 已验证；
6. JSONL / SessionEvent 能观察真实行为；
7. 无 Scope 外改动；
8. `/understand-diff` 或等价 diff review 无重大遗漏；
9. Git diff 可解释。

---

# 14. 最终原则

> **Engineering Specification 决定长期目标和架构边界；Spec Kit / Ticket 决定当前施工范围；代码与测试证明实现是否真实完成。**

> **优先复用成熟设计，保持 Core 小而可控；任何框架、Provider、插件都不能反向拥有 Agent Runtime。**

---

# 15. Git / Worktree

本项目的 Git 分支、Worktree、合并和 Push 规则统一以 `AGENTS.md` 为准：

- §13「并行开发」：Worktree 目录与分支映射、Feature Worktree 完成后的默认行为、最终合并规则。
- §14「Git Workflow / Merge Safety」：Branch Roles、Worktree Rules、只读 / 需批准 Git 操作清单、Pull Policy、Merge Direction、Conflict Policy、Main Safety、One Branch at a Time、Validation Gate、Approval Workflow。

默认行为：

- 后端开发使用 `D:\intelligence-agent-backend` / `feat/backend`；
- 前端开发使用 `D:\intelligence-agent-frontend` / `feat/frontend`；
- 最终集成使用 `D:\intelligence-agent` / `main`；
- Feature Worktree 完成后可以 commit，但**默认不得**自行 `merge main` 或 `push GitHub`；
- 跨分支集成由 **Git Integrator**（或用户明确授权的集成角色）统一负责。

关键纪律（详见 AGENTS.md §14）：

- 任何 Git 写操作前先确认当前 worktree / branch / status；用 `git worktree list --porcelain` 取真实映射，不凭目录名猜 branch。
- `merge`、`push`、冲突解决、`cherry-pick`、`revert`、branch / worktree 删除必须用户明确批准；`reset --hard` / `rebase` / `push --force` 默认禁止。
- 同步统一用 `git fetch origin` + 显式 `git merge origin/main`，不用 `git pull`。
- 集成顺序固定为：`origin/main → feature branch（解决冲突、测试）→ main`；先 Backend 后 Frontend，一次只集成一个；Backend 合入后 Frontend 的 Conflict 判断必须重做。
- 出现 Conflict 立即停止自动解决，逐文件做语义分析后请求批准；禁止 `ours` / `theirs` 机械取舍，禁止为了让冲突消失删除一侧逻辑。
- `main` 上出现未预期的复杂 Conflict 时优先 `git merge --abort`，回 Feature Worktree 解决。
- Approval Workflow 固定为 `Analyze → Report → Ask → Execute → Validate → Report → Ask`；前一阶段获批不等于后续阶段自动授权。
