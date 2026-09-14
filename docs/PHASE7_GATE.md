# Phase 7 Gate 证据 — Capability / Plugin Foundation + Skills

2026-09-05：**PASS。#57-#62 全部交付，Phase 7 COMPLETED。**

## 交付范围

Capability seam 泛化（Phase 6 点对点 Memory seam → 通用机制）+ SKILL.md 渐进披露。
冻结依据：spec 08 全文、spec 09 §2、spec 13 §2/§3/§5（Pi/DSH PORT DESIGN）、spec 14 Phase 7 清单；
设计决策：ADR-0010（registry/config/wiring）、ADR-0011（skills 渐进披露，含用户批准的 when_to_use 扩展）。

Commits（固定点 `8e950e6` 之后，`4548cc2..984f4c9`）：

| Commit | 内容 |
|---|---|
| `4548cc2` | ADR-0010/0011 + CONTEXT.md Phase 7 术语 + tickets snapshot |
| `fe94fab` | T2：CAPABILITIES 配置解析 + wire_capabilities，Memory 走 Registry（#59） |
| `e9b29b3` | T3：SKILL.md 解析 + SkillDiscovery（#60） |
| `f589868` | T4：SkillCapability + 目录注入 + load_skill + when_to_use（#61） |
| `2a84c0e` | T5：TickerCapability demo + factory 失败降级 + Gate 集成（#62） |
| `984f4c9` | 双轴 code-review 修复（见下） |

## Gate 1：新增 demo capability 不改 Agent Loop

- **结构证明**：`git diff 4548cc2~1..HEAD -- src/agent_harness/agent/runtime.py` 为空——Phase 7 全程 AgentRuntime / Agent Loop 零改动。
- **行为证明**：`tests/capability/test_phase7_gate.py::TestTickerCapabilityDemo::test_closed_loop_through_agent_runtime`——`{"ticker": {}}` 纯 config 注册 → ContributesTools 收集 → ToolRegistry → 统一 ToolExecutor → ScriptedModel 两轮闭环，tick 结果按 `tool_call_id` 配对回填，`STATUS_COMPLETED`。
- 新增能力的施工面 = 写 factory + 在 `_BUILTIN_WIRING` 加一行（装配层，非 Agent Loop）。

## Gate 2：Skill 全文不默认进 Context

- `TestGate2SkillsProgressiveDisclosure` 在**模型请求边界**（ScriptedModel snapshots）断言：
  - 默认请求只含目录行 `pdf-export: 导出 PDF 报告的标准流程`（含 `何时用：…` 注入）；
  - 正文唯一标记 `BODY_ONLY_TOKEN` 在默认请求中绝不出现；
  - 显式 `load_skill` 调用后，全文才在第二轮请求的 ToolMessage 中出现，且带「不是运行时指令」数据前缀（防注入框架）。
- load_skill 为 READ_ONLY 工具，走统一 ToolExecutor（Permission/Ledger 零旁路）。

## spec 08 §9 验收逐条

| 验收项 | 证据 |
|---|---|
| 插件不能绕过 Tool Permission / Operation Ledger | 工具贡献只经 `wire_capabilities` → ToolRegistry → ToolExecutor 单一路径；tick 为 READ_ONLY，经 executor 执行断言（`test_tick_is_read_only_through_unified_executor`） |
| Provider 不支持能力时明确报错 | 未知 capability / 未知 provider → `CapabilityError(init_failed)`（`test_unknown_capability_raises_init_failed`、`test_unknown_provider_raises_not_silently_ignored`）；`unsupported` 码为保留词汇，Consumer 侧检查随多 Provider 选择落地（ADR-0010 Q2 补充） |
| Optional Provider 故障可以降级 | factory 抛错 → OPTIONAL 记 warning 跳过装配，`registry.optional()` 返回 None，基础 Agent 照常运行（`TestDegradation`）；REQUIRED_CORE 向上抛。`_BUILTIN_WIRING` 每项带声明降级档位 |
| 切换 Memory Provider 不改 Core | 结构保证：memory 经 Registry + factory 装配，Core 无 LangMem import。V1 仅一个 provider 实现，行为级"切换"验证 DEFER（ADR-0010 Q5 Scope Lock，与 Artifact/MCP/Knowledge 启停一起归后续 Phase） |

## 双轴 Code Review（2026-09-05）与修复

Standards 轴 + Spec 轴并行审查 `4548cc2~1..HEAD`，修复（`984f4c9`）：

1. 重复注册错误码 `not_found` → `init_failed`（ADR-0010 Q2 词汇表语义对齐，测试收紧到精确 code）。
2. `AppState.get_wiring` 并发首请求竞态 → asyncio.Lock 双重检查 once 语义（原实现第二个请求会撞重复注册）。
3. `provider` 字段被静默忽略（08 §5 违规）→ `_KNOWN_PROVIDERS` 装配期校验，未知 provider 显式 `init_failed`（配置错误不走降级）。
4. SkillDiscovery 解析错误在装配边界被丢弃（ADR-0011 Q1"可观察"违规）→ `_wire_skills` 记 warning，`SkillCapability.errors()` 可编程读取。
5. 工具贡献双机制合一：load_skill 改由 `SkillCapability.contributes_tools()` 统一收集。
6. config 校验报错带首条具体字段错误；ADR-0011 `SkillLoadError` 文档漂移修正；测试遗留疑问注释清理。

## Validation

- 全量：`python -X utf8 -m pytest tests/ -q --tb=short` → **585 passed, 8 skipped, 8 deselected**。
- ruff：`ruff check src tests` → **All checks passed**。
- GitHub issues：#57（父）— #62 全部关闭；tickets snapshot 与 `docs/tickets/` 同步。

## Notes

- CAPABILITIES env JSON（pydantic strict）显式配置加载，无 Marketplace / entry-point 扫描（spec 08 §6 V1）。
- Skills 双目录（global `~/.intelligence-agent/skills` 或 `SKILL_GLOBAL_DIR` + 项目 `workspace/skills`）+ options 扩展；一级 `<dir>/<name>/SKILL.md` 扫描，目录扫描有 symlink 越界检查，手动路径视为用户自授权（ADR-0011 Q4）。
- Registry 为进程内单例（AppState 惰性装配 + shutdown 关闭 memory），无跨进程语义——DEFER。
