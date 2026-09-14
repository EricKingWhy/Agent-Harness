# intelligence-agent · 轻量可观测 Agent Harness

> 一个 **Python / Async-first、轻量、透明、可恢复、插件化** 的通用 Agent Harness。
> 它不是一个聊天机器人，而是一套**把 Agent 的执行过程变成可查、可对账、可恢复的运行时**。

**核心命题：append-only typed SessionEvent 是唯一真相，界面只是它的投影。**

---

## 🔗 在线 Demo（评委可直接上手）

**链接：** `<发布后填入>`

打开即可用，无需安装、无需注册。首页默认带一份**真实运行数据集**（88 个会话 / 2000+ 条事件，
全部是本项目开发过程中真实跑出来的 agent 轨迹，不是构造的演示数据）。

### 评委 3 分钟体验路径

| 步骤 | 你要做什么 | 你会看到什么 |
|---|---|---|
| ① 打开链接 | 直接进入 | 左栏是会话列表，点任意一条历史会话 |
| ② 看「Agent 干了什么」 | 中间栏 | 连续工作流叙事：思考 → 工具调用 → 结果，每个事件可展开 L0→L3 |
| ③ 看「Runtime 到底发生了什么」 | 右栏 Inspector | 完整 event timeline、Tool Input/Output、Raw event、`seq` / `run_id` / `tool_call_id` 关联 |
| ④ 自己下一个任务 | 底部输入框，例：`把这个项目的测试跑一遍，告诉我失败了哪些` | agent 真机执行：读写文件、跑命令、流式输出，全程可观测 |
| ⑤ 体验「审批闸」 | 新建任务时把权限档从「工作区写入」改成「只读」 | 危险操作原地弹出**审批卡**，批准/拒绝后工具才继续 |
| ⑥ 体验「会话谱系」 | 任意会话右键/顶栏 → Fork / Replay | 从历史某个 turn 分叉出新会话；replay 冻结终态、绝不产生副作用 |

> 提示：Demo 为公开链接，请勿输入含个人隐私或密钥的内容。

---

## 为什么它不是「又一个 Agent Demo」

大多数 agent 项目能跑通任务，但**跑歪了没法查**：日志是字符串、状态在内存里、崩溃即失忆。
本项目把「可观测 / 可恢复」当作架构的第一性问题，并冻结成 22 条架构不变量。四个硬差异：

**1. 事件流是本体，界面是投影（Event Sourcing）**
所有会话事实都是 append-only、类型化的 `SessionEvent`（42 个事件名，有生成器与词表单一事实源）；
`derive_messages()` 是纯函数投影，负责 tool_call / tool_result 配对与 dangling 检测。
Web UI 的每个元素都能指回具体事件，**不维护第二套会话真相**（不变量 #22）。

**2. 崩溃可恢复，且不猜副作用（Recovery + Operation Ledger）**
SessionEvent 记录「对话发生了什么」，Operation Ledger 记录「每次工具调用现在处于什么状态」。
崩溃重启后：先补记 `run/interrupted`（只声明事实，不猜工具终态），再由 RecoveryCoordinator
按各自终态 reconcile——SUCCEEDED 从账本合成恢复结果、FAILED 合成失败、PENDING 可重执行、
**UNKNOWN 一律交人工裁决，绝不盲重跑**（不变量 #12 / #14）。Checkpoint ≠ 副作用恢复。

**3. 工具只有一条执行路径（统一 ToolExecutor）**
read / write / edit / bash / glob / grep / git_* / load_skill / inspect_artifact……无论内置、
Capability 插件、MCP 还是 Skills，全部经**同一条** ToolExecutor 走权限、审批、重试、Ledger、
溢出外置、事件落盘。不存在「旁路调用」（不变量 #7/#8）。

**4. 能力可插拔，Core 不受污染（Capability / Plugin）**
Memory / Skills / MCP / Knowledge / Web Search / Multi-Agent 都是 **Capability + Provider**，
不写进 Agent Loop 的特判分支（不变量 #16/#18）。三档降级（REQUIRED_CORE / OPTIONAL_RUNTIME /
OPTIONAL_OBSERVABILITY）——配错或缺失只会让那项能力缺席，**可选能力的故障拖不垮 Core**（#21）。
实测：本 Demo 就没配 Milvus / Langfuse，Memory 与旁路观测缺席，主流程照常。

---

## 架构一览

```
                    ┌──────────────── Web UI (React 19 + Vite) ───────────────┐
                    │  Inspector 三栏：Sessions/Runs/Fork Tree │             │
                    │  Conversation+ToolCards │ Step Detail (Raw event)        │
                    └───────────▲───────────────────────────┬──────────────────┘
                        SSE 事件流 (after_seq 续传)          │ REST /approve /cancel /fork
                    ┌───────────┴───────────────────────────▼──────────────────┐
                    │  FastAPI (web/)  · RunManager (detached run + 断连不取消) │
                    └───────────▲───────────────────────────┬──────────────────┘
                                │ AgentEvent                │ SessionEvent (append-only)
        ┌───────────────────────┴─────────────┐   ┌─────────▼──────────────────┐
        │        AgentRuntime (本项目拥有)      │   │ JsonlSessionStore          │
        │  ContextBuilder → Model → ToolExec   │   │  sessions/<id>/events.jsonl│
        │  guards(同错熔断) · fallback · ledger │   └─────────┬──────────────────┘
        └───┬──────────┬──────────┬────────────┘             │
            │          │          │              ┌───────────▼───────────────┐
   ┌────────▼──┐  ┌────▼─────┐  ┌─▼──────────┐  │ SQLite: Operation Ledger  │
   │ModelProvider│  │ Sandbox  │  │ ToolRegistry│ │ Checkpoint · SessionMeta  │
   │ deepseek/  │  │ Local /  │  │ 10 Coding   │ └───────────────────────────┘
   │ qwen/zhipu │  │ Docker   │  │ Tools + 插件 │
   └───────────┘  └──────────┘  └─────────────┘
        Capability 层（可装卸）: Memory · Skills · MCP · Knowledge · WebSearch · MultiAgent
```

**分层纪律：**模型层不得拥有 Agent Loop；LangGraph 只是 optional orchestration，**不替代** Tool
Runtime / Operation Ledger；LangMem / Milvus / MinIO / Langfuse / MCP 全部经 Provider / Adapter
接入（不变量 #17/#20）。

---

## 本地运行（3 步）

```bash
# 1) 后端依赖（Python ≥ 3.11）
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -r requirements.txt

# 2) 配置模型
cp .env.example .env && 编辑填入 MODEL_API_KEY

# 3) 启动（后端同时提供 API 与前端静态资源，单端口）
bash start.sh          # 默认 8000；云上会自动读 $PORT
# 打开 http://127.0.0.1:8000
```

前端要改代码时：

```bash
cd web && pnpm install && pnpm dev   # :5173，/api 反代到 :8000
pnpm build                           # 产物落在 web/dist，由后端静态服务
```

---

## 目录结构

```
src/agent_harness/
├── agent/          AgentRuntime：loop / run_stream / guards / 单终态收尾
├── session/        Session 聚合根 · SessionEvent · JSONL Store · fork / replay
├── tooling/        统一 ToolExecutor · Tool 契约 · 重试 · 调度 · 输出流
├── tools/          10 个 Coding Tool（read/write/edit/bash/glob/grep/git_*/load_skill/inspect_artifact）
├── model/          Provider 预设 · fallback 策略 · 流式守卫 · ScriptedModel（评测替身）
├── context/        ContextBuilder · token 估算 · 三层降级 Compaction
├── storage/        Operation Ledger · Checkpoint · SessionMeta（SQLite）
├── recovery/       RecoveryCoordinator（8 步恢复）· PendingPolicy · 启动中断扫描
├── capability/     能力注册表 / descriptor / 三档降级 / 插件装配
├── memory/  knowledge/  websearch/  mcp/  skills/  multiagent/   ← 全部可装卸
├── observability/  Langfuse 旁路（故障不拖垮主流程）
├── prompt/         版本化 Prompt Section 注册表（严格模板插值 · 启动自检）
└── web/            FastAPI · SSE · RunManager · 40+ REST 端点

web/                React 19 前端（42 组件 · 38 个 e2e spec · 双主题对比度门禁）
tests/              按域组织的测试（含 ScriptedModel 确定性 Runtime 测试）
docs/spec/          冻结的工程规格（16 个 Phase + ADR 决策记录）
evaluation/         Golden Case · Deterministic Assertion · Eval Runner
```

---

## 工程与验证

- **规格驱动**：`docs/spec/` 是冻结的工程规格（Phase 0→16 + ADR），实现以票为单位推进，
  进度记录在 `docs/PHASE_STATUS.md`（单一事实源）。
- **测试**：后端 `pytest`（含 ScriptedModel 驱动的确定性 Runtime 测试：resume / recovery /
  kill / replay / fork / 同错熔断 / model fallback）、前端 `vitest` + `playwright` e2e。
- **可验证而非口号**：`citation` 可追溯、`dangling tool_call = 0`、`duplicate confirmed = 0`、
  权限越权必须被拦而合法调用必须放行、弱证据如实标记 `is_sufficient=false` 而不是编答案。
- **诚实边界**：拿不到的数据显示 `—` / `Unavailable`，不填占位数字、不伪造指标。

---

## License

见 [LICENSE](LICENSE)。
