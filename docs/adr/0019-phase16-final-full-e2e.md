# ADR-0019 — Phase 16：Final Full E2E（端到端集成验收）

日期：2026-09-07 ｜ 状态：Accepted（grill 三轮逐项拍板，用户确认） ｜ 关联：spec 14 Roadmap Phase 16、ADR-0003/0004/0006/0007/0014/0017/0018

## 背景

Phase 0-15 全部 COMPLETED 并在 main（tip `0ac49f3`）。Roadmap Phase 16「Final Full E2E」要求一条完整场景链串联所有核心能力（historical → research → KB insufficient → web → citation → coding → edit/test failure → retry → mutating tool → kill → restart → sandbox restore → operation reconcile → continue → tests pass → review → final → replay → fork → Langfuse trace → Eval report），最终 Gate 6 项指标（duplicate confirmed side effect=0 / dangling tool call=0 / core recovery=100% / citation validity=100% / permission violation=0 / Full E2E reproducible）。

上游调研确认设计同构成熟实践：pi-mono 用 `describe.skipIf(!API_KEY)` + mock model runtime（`model-runtime-test-utils.ts`）跑 deterministic 测试，真 API key 测试用同一套 fixture 跑集成；deepseek-harness 用多层 vitest 配置（e2e/stress/web 分离）。本项目的 ScriptedModel + probe-gated skip + 分层 marker 与之同构。

用户定调：**生产级、上线级、高性能、强鲁棒**——设计必须能扛未来真实生产环境。

## 决策（grill 三轮逐项拍板，用户确认）

### D1 链路驱动形态：分段独立断言 + 薄编排层

Roadmap 场景链有 20 个节点。不做单链路连续真跑（ScriptedModel 编排 20 步剧本维护成本过高，单步偏离全链崩，CI 信号噪声比极差）。采用**分段独立断言**：每个链路段独立触发 + 独立断言（research/KB/web/citation 段、coding/edit/test-failure 段、kill/restart/reconcile 段、replay/fork 段、Langfuse/Eval 段），各段可独立失败/修复/重跑。加一个**薄编排层**（单 test function，ScriptedModel 5-6 轮简化链路 research → KB insufficient → web → coding → final）证明关键路径可串。

**拒绝的替代**：单链路连续真跑——维护成本远超收益，且真实场景一个 run 不会自然走过所有状态（research → KB 不足 → web 合理，但 kill 在一个 run 里自然发生概率极低）。

### D2 模型层：双层（ScriptedModel CI + 真模型手动）

同 Phase 15 ADR-0018 D10 模式：CI 用 ScriptedModel 保证 deterministic/零 token/零外部依赖；真模型留手动入口（evaluation driver 或 CLI），在有凭证环境跑一次真链路验证。复用既有模式，零架构新增。

### D3 外部依赖：全 fake 进 CI + 真依赖手动车道

KB（Milvus/Zilliz）、Web（Tavily）、Memory（Zilliz + SiliconFlow）、Langfuse（云）全部用既有 fake provider（FakeRetrievalProvider / FakeWebSearchProvider / FakeEmbeddingProvider / FakeLangfuseClient）进 CI。真依赖的 E2E 验证留手动车道（同 Phase 6/11/12/15 真云 Gate 模式）。理由：CI 必须满足 deterministic + reproducible，真依赖违反该原则（凭证 + 网络 + 烧 token）。

### D4 kill/恢复/对账真实性：真子进程 kill + 真 Ledger reconcile

复用 Phase 4 `tests/integration/test_kill_resume.py` + `test_bash_reconcile.py` 的真子进程 kill 模式。kill → restart 后断言：(1) SessionStore derive 出完整对话历史；(2) WorkspaceRegistry 映射恢复（sandbox 重绑）；(3) RecoveryCoordinator 跑完后所有 PENDING 操作被裁决（confirmed 或 rolled-back，无 UNKNOWN 残留）；(4) run 从恢复点继续到 terminal。编排进 E2E 链路上下文（前有 coding/edit/test failure，后有 continue/tests pass）。

### D5 sandbox restore：Docker probe-gated integration 车道

**Docker 沙箱是重要设计环节，不推到手动验收。** 复用现有 `tests/sandbox/test_docker_sandbox.py` 的 `_docker_available() + pytest.mark.skipif` 探测模式：Docker daemon 在 → 真启动容器 → exec 改文件 → kill → restart → 验证容器重建 + WorkspaceRegistry 重绑 + 文件状态；不在 → skip 并登记原因（不算失败）。

**与 Phase 3 的区别**：Phase 3 的 Docker 验收是手动验收清单（`docs/PHASE8_MANUAL_ACCEPTANCE.md` 模式）；Phase 16 的 Docker restore 是 probe-gated 自动 integration 测试——有 Docker 自动跑，没有自动 skip。这是 Docker 验收从"手动"升级到"自动探测"的形态变化。

LocalSubprocessSandbox 用于 kill/reconcile 分段（Ledger reconcile 逻辑与 sandbox 后端无关）。

### D6 mutating tool 语义：coding 工具副作用 + Ledger 对账验证

"mutating tool running" 理解为 coding 工具（edit/write/bash）的副作用——不是 DANGER 级权限审批关卡（Phase 3 已覆盖）。Phase 16 验证 mutating tool 的副作用在 kill/restart 后能被 Ledger 正确对账（PENDING → confirmed/rolled-back）。"mutating tool → kill → restart → reconcile" 形成连贯的 Ledger 对账验证链。

### D7 交付物形态：单个 gate 测试文件 + helpers

- `tests/integration/test_phase16_gate.py`（同 Phase 11-15 gate 文件模式，所有分段断言在一个文件里用不同 test function）
- `tests/integration/_phase16_helpers.py`（E2E 链路专用 helper：ScriptedModel 剧本构造、fake provider 组合套件，同 `_kill_child.py` 先例）
- 薄编排层 = gate 文件里的一个 `test_critical_path_e2e` test function
- 复用 `tests/integration/_kill_child.py`（真子进程 kill helper）

### D8 Gate 指标精确化

Roadmap 6 项 Gate 模糊指标的精确解读：

| 指标 | 精确定义 |
| --- | --- |
| **duplicate confirmed side effect = 0** | Ledger 里每个 operation_id 只有一个终态（confirmed 或 rolled-back），kill/restart 后 reconcile 只裁决一次，0 条重复确认 |
| **dangling tool call = 0** | 所有 tool_call 都有配对的 tool_result（复用 `evaluation/assertions.py::dangling_tool_call_ids`），kill 后恢复的悬空调用由合成 tool/result 补齐 |
| **core recovery = 100%** | kill → restart 后：(1) SessionStore 事件序列完整可 derive；(2) WorkspaceRegistry 映射恢复；(3) 所有 PENDING 操作裁决无 UNKNOWN 残留；(4) run 从恢复点继续到 terminal。不是百分比，是全或无 |
| **citation validity = 100%** | 所有 citation 格式合法（`kb:<source>#<idx>` / `web:<url>`）+ KB citation 在 fake store 里可查到对应 chunk + web citation URL 格式合法。真模型 citation 幻觉检测留手动车道 |
| **permission violation = 0** | E2E 链路里编排一个显式越权尝试（如 bash 试图读 sandbox 外路径），断言被 PERMISSION_DENIED；其余合法调用全部正常执行。证明边界有效，不是"没遇到边界" |
| **Full E2E reproducible** | 薄编排层 test function 用 ScriptedModel 跑简化链路，deterministic + 可复跑 |

### D9 范围边界：什么不在 Phase 16 核心链路重复测

以下能力已在各自 Phase 深度覆盖并有真实 Gate 通过，**不在 Phase 16 核心链路重复测**（§8 Scope Lock）：

| 能力 | 已覆盖 Phase | 不重复测的理由 |
| --- | --- | --- |
| Multi-Agent delegation | Phase 13（真实 Gate 8 条） | Roadmap 链路未画 delegation |
| Context compaction | Phase 5（三层降级） | Roadmap 链路未画 compaction；链路自然触发时顺带验证 |
| Memory capability | Phase 6（真实 Zilliz Gate） | Roadmap 链路未画 memory tool |
| MCP client | Phase 8（真实 fake server Gate） | Roadmap 链路未画 MCP tool |
| Streaming UI / Web SSE | S-UI（生产级改造完成） | Phase 16 是后端 E2E，不测 web 层 |

如果 E2E 链路自然经过某能力（如 coding 产生大输出触发 compaction），顺带验证但不单独测。

### D10 fixture 策略：混合（单元 fake 复用 + E2E 编排新建）

单元级 fake provider（FakeRetrievalProvider / FakeWebSearchProvider / FakeLangfuseClient 等）从各模块 import 复用。E2E 链路编排剧本（ScriptedModel 多轮预设回复）新建在 `_phase16_helpers.py`。每个分段测试有自己的小剧本（2-3 轮），薄编排层有中等剧本（5-6 轮）。没有"20 步大剧本"（脆化风险过高）。

### D11 性能：只量不裁（记录延迟基线）

记录 E2E 链路 wall clock + 各段耗时到 PHASE16_GATE.md，作为后续性能回归 baseline。不设硬阈值（Roadmap 未要求，ScriptedModel 延迟不代表真实延迟，硬阈值无参考价值）。真性能优化是独立 Phase（需 profiling + bottleneck 分析），不混入 Final E2E。

### D12 Langfuse trace + Eval report 角色：Gate（结构完整性）

Langfuse trace 结构完整性在 fake client 上断言（agent-run 根 + generation/tool/span 观测齐全，复用 Phase 15 best-practices checklist 形状）。Eval report 复用 `evaluation/runner.py` + `assertions.py`，断言 dangling=0 / duplicate=0 / recovery=1.0。真云 Langfuse 可视化验证留手动车道（同 Phase 15）。

## Consequences

- Phase 16 是最后一个 Phase，交付后 Phase 0-16 全闭合。
- "分段独立断言 + 薄编排层"意味着 "Full E2E reproducible" Gate 由薄编排层承担（简化链路），不是 20 步全链路——这是对 Roadmap 字面意义的工程化解读，记录于此 ADR 防止误解。
- Docker probe-gated integration 是 Docker 验收从手动升级到自动探测的起点——后续 Phase 3 的手动验收清单可逐步迁移到这个模式（不在 Phase 16 做）。
- Gate 指标精确化（D8）是 Roadmap 模糊性的必要解读，未来指标口径变更需修订本 ADR。
