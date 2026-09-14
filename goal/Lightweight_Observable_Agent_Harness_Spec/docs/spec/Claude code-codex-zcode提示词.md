你现在开始参与 `intelligence-agent` 项目的正式开发。

项目规格文档位于：

`D:\intelligence-agent\goal\Lightweight_Observable_Agent_Harness_Spec\docs\spec`

这套文档是当前项目的**最高优先级需求与架构规格**。它已经取代之前所有按 Day 划分的教学计划。后续开发不再以“学习 Day”推进，而是按照模块依赖和 Implementation Roadmap 推进。

# 一、先读文档，不要直接写代码

首次进入项目时，必须按下面顺序阅读。

## 第一层：必须完整阅读

按顺序：

1. `README.md`
    
2. `00_PROJECT_VISION.md`
    
3. `01_SYSTEM_ARCHITECTURE.md`
    
4. `13_OPEN_SOURCE_REUSE_MATRIX.md`
    
5. `14_IMPLEMENTATION_ROADMAP.md`
    

其中：

- `00_PROJECT_VISION.md` 是项目宪法，优先级最高。
    
- `01_SYSTEM_ARCHITECTURE.md` 冻结总体架构、模块边界和依赖方向。
    
- `13_OPEN_SOURCE_REUSE_MATRIX.md` 决定什么应该直接复用、什么只借设计、什么才允许自研。
    
- `14_IMPLEMENTATION_ROADMAP.md` 决定开发顺序。
    

如果后续实现方案与 `00_PROJECT_VISION.md` 冲突，以 `00_PROJECT_VISION.md` 为准。

---

# 二、再根据当前任务阅读对应模块

不要每次把全部文档重新读一遍。

当前要开发哪个模块，就额外完整读取对应规格：

- Agent Loop / Model Provider  
    → `02_AGENT_RUNTIME.md`
    
- Session / Event / Resume / Replay / Fork  
    → `03_SESSION_EVENT_MODEL.md`
    
- Tool Contract / Registry / Executor / Retry / Scheduler  
    → `04_TOOL_RUNTIME.md`
    
- Docker Sandbox / Coding Tools / Approval  
    → `05_SANDBOX_CODING_TOOLS.md`
    
- Context / Compaction / Artifact / MinIO / Memory  
    → `06_CONTEXT_ARTIFACT_MEMORY.md`
    
- SQLite / PostgreSQL / Checkpoint / Operation Ledger / Recovery  
    → `07_STORAGE_PERSISTENCE_RECOVERY.md`
    
- Capability / Provider / Plugin 架构  
    → `08_PLUGIN_CAPABILITY_SYSTEM.md`
    
- MCP / Skills / Knowledge / RAG / Web Search  
    → `09_MCP_SKILLS_KNOWLEDGE_WEB.md`
    
- Multi-Agent / AgentProfile / AgentFactory / Supervisor / Dynamic SubAgent  
    → `10_MULTI_AGENT_DELEGATION.md`
    
- CLI / AgentEvent / FastAPI SSE / Web UI  
    → `11_STREAMING_API_WEB_UI.md`
    
- JSONL / Langfuse / Evaluation / EvalScope  
    → `12_OBSERVABILITY_EVALUATION.md`
    

如果一个任务横跨多个模块，就读取所有相关模块，不要只看其中一篇。

---

# 三、SOURCE_TRACEABILITY 的用途

`SOURCE_TRACEABILITY.md` 只是用于说明这些规格是如何从旧教学计划重构而来的。

正常开发不需要优先阅读。

只有当你需要追查“某个需求原来为什么存在”时再查看。

---

# 四、开发前必须检查当前代码

读完规格以后，不要直接按照文档假设项目当前状态。

必须先检查仓库现状：

1. 当前目录结构；
    
2. 已实现模块；
    
3. 已存在 Contract / Interface；
    
4. 当前测试；
    
5. 当前配置；
    
6. 已安装依赖；
    
7. Git 状态；
    
8. 是否已经存在同功能实现。
    

然后建立：

`规格要求 → 当前实现 → 缺口`

的对应关系。

禁止因为规格写着某个模块，就重新实现一个仓库里已经存在的版本。

---

# 五、Reuse First，禁止无意义造轮子

这是本项目最高级工程原则之一：

**Reuse First, Build Second。**

每次准备实现一个较大的模块前，必须先查看：

`13_OPEN_SOURCE_REUSE_MATRIX.md`

然后明确判断：

- `REUSE`
    
- `ADAPT`
    
- `PORT DESIGN`
    
- `BUILD`
    
- `DEFER`
    

属于哪一种。

尤其是：

Pi：  
`https://github.com/badlogic/pi-mono`

DeepSeek Harness：  
`https://github.com/deepseek-ai/deepseek-harness`

如果 Pi、DeepSeek Harness 或成熟开源库已经存在合适设计，不要自己重新脑补一套。

可以：

- 直接复用成熟 SDK；
    
- 使用 Adapter；
    
- 借鉴其数据模型；
    
- 借鉴其执行 Pipeline；
    
- 借鉴其 Session / Fork / Compaction / Capability / SubAgent 设计；
    
- 将成熟 TypeScript 设计 Port 成符合本项目 Python 架构的实现。
    

但不要为了复用而破坏本项目自己的 Core Runtime。

如果实质复制或移植开源代码，必须检查 License，并保留必要的版权和来源信息。

---

# 六、Core 不能被框架反向绑架

必须始终保持：

`Agent Runtime 是我们自己的。`

以下组件只能作为 Provider / Adapter / Capability / Orchestration Layer：

- LangChain
    
- LangGraph
    
- LangMem
    
- Milvus
    
- MinIO
    
- MCP
    
- Langfuse
    
- EvalScope
    

禁止：

`为了接某个框架 → 重写整个 Agent Runtime`

例如 LangGraph 只能：

`Graph Node → 调用 existing AgentRuntime`

不能把我们的 Tool Runtime、Recovery、Operation Ledger、Context 等重新实现成另一套 LangGraph 专属系统。

---

# 七、Memory 特别注意

Memory 必须保持：

`Memory Capability + Memory Context Provider`

Core 禁止直接绑定 LangMem。

结构应该允许：

`LangMemProvider`

未来替换成：

`Mem0Provider`

或者：

`CustomMemoryProvider`

而 Agent Core 不需要修改。

LangMem 是当前默认实现，不是架构本身。

---

# 八、所有 Tool 必须只有一条执行路径

无论 Tool 来自哪里：

- Coding Tool
    
- Knowledge Tool
    
- Web Tool
    
- MCP Tool
    
- Memory Tool
    
- SubAgent Tool
    
- 未来 Finance Tool
    

都必须进入统一：

`Tool Contract`  
→ `ToolRegistry`  
→ `Validation`  
→ `Permission`  
→ `Dependency-aware Scheduler`  
→ `ToolExecutor`  
→ `Operation Ledger（需要时）`  
→ `ToolResult`  
→ `SessionEvent`

禁止出现第二套隐藏 Tool Runtime。

---

# 九、开发过程中保持模块边界

不要为了方便跨层调用。

尤其禁止：

- Core 直接 import LangMem concrete implementation；
    
- Core 直接 import Milvus Client；
    
- Core 直接依赖 MinIO；
    
- AgentLoop 写 RAG 特殊 if/else；
    
- AgentLoop 写 Coding 特殊逻辑；
    
- MCP Tool 绕过 ToolExecutor；
    
- LangGraph Checkpoint 替代 Operation Ledger；
    
- Web UI 自己维护第二套 Session 真相；
    
- Langfuse 成为唯一日志；
    
- Context Compaction 删除原始 Session History。
    

遇到边界不清楚时，优先回看：

`00_PROJECT_VISION.md`  
和  
`01_SYSTEM_ARCHITECTURE.md`

---

# 十、后续每次开始一个开发任务时

不要重复全套规格。

默认执行流程：

1. 读取 `00_PROJECT_VISION.md` 中相关原则；
    
2. 读取当前模块规格；
    
3. 读取 `13_OPEN_SOURCE_REUSE_MATRIX.md` 中相关部分；
    
4. 检查当前代码状态；
    
5. 确认当前属于 `14_IMPLEMENTATION_ROADMAP.md` 哪个 Phase；
    
6. 分析已有实现和规格之间的 Gap；
    
7. 确定哪些复用、哪些 Adapter、哪些才需要自己实现；
    
8. 给出本次最小修改范围；
    
9. 实现；
    
10. 运行对应 Unit / Integration / Failure / Recovery Tests；
    
11. 根据模块 Acceptance Criteria 验收。
    

不要提前跨 Phase 大量实现未来功能。

---

# 十一、一个模块是否完成，以 Acceptance Criteria 为准

不能因为：

“文件已经创建”  
“代码能启动”  
“接口写完了”

就认为模块完成。

必须逐条检查对应规格里的：

`Acceptance Criteria`

尤其重视：

- Failure Case
    
- Crash Recovery
    
- Tool side effect
    
- Retry
    
- Permission
    
- Context overflow
    
- Session consistency
    
- dangling tool_call
    
- duplicate side effect
    

这个项目不是 Demo，核心目标之一就是把 Agent 从黑盒变成**可观察、可恢复、可对账的 Runtime**。

---

# 十二、开发过程中不要删除关键设计来换取简单

这个项目核心价值是：

**Lightweight**  
+  
**Observable**  
+  
**Recoverable**  
+  
**Extensible**  
+  
**Reusable**

“Lightweight”不是少写几个模块。

它指：

**Core 小、边界清晰、能力插件化、成熟能力尽量复用。**

所以不能为了简单而删除：

- SessionEvent
    
- Operation Ledger
    
- Artifact
    
- Reconcile
    
- Resume / Replay / Fork
    
- Capability abstraction
    
- Tool Runtime
    
- 全链路 Observability
    

这些就是项目核心卖点。

---

# 十三、你具有较高自主权，但存在明确停止条件

对于明确的工程实现、重构、测试、修 Bug、选择成熟库等，你可以自主判断并继续。

只有下面情况需要停下来问我：

1. 规格之间存在实质冲突；
    
2. 我的需求存在两个会显著改变架构的合理解释；
    
3. 需要我提供 API Key、账号、权限、服务器等外部资源；
    
4. 涉及不可逆或高风险操作；
    
5. 准备大幅偏离已经冻结的架构；
    
6. 发现现有代码和规格存在重大冲突，需要决定“迁移还是推倒”；
    
7. 需要新增规格中没有的重要基础设施；
    
8. 需要做产品层面的取舍，而不是普通技术实现选择。
    

普通技术细节不要频繁询问我，优先根据规格、成熟实践和当前代码自己判断。

---

# 十四、首次收到这段提示词后你现在要做什么

现在先不要开始大规模写代码。

请执行：

1. 按规定顺序阅读：
    
    - `README.md`
        
    - `00_PROJECT_VISION.md`
        
    - `01_SYSTEM_ARCHITECTURE.md`
        
    - `13_OPEN_SOURCE_REUSE_MATRIX.md`
        
    - `14_IMPLEMENTATION_ROADMAP.md`
        
2. 检查 `D:\intelligence-agent` 当前代码仓库状态。
    
3. 判断：
    
    - 当前项目已经实现到了哪个 Phase；
        
    - 哪些已经符合新规格；
        
    - 哪些属于旧实现但可以保留；
        
    - 哪些与新规格冲突；
        
    - 下一步最合理应该从哪个 Phase 开始。
        
4. 暂时不要为了满足新规格一次性大改整个项目。
    
5. 给我输出一份简洁的：
    

`当前状态 → 与规格差距 → 建议下一 Phase → 需要保留/重构/删除的内容`

然后再开始正式开发。

后续所有实现都以：

`D:\intelligence-agent\goal\Lightweight_Observable_Agent_Harness_Spec\docs\spec`

作为项目正式需求与架构依据。