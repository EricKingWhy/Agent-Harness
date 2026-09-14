# PRD: 统一 Prompt 注册表与模板化组装

> 状态：决策已收敛（grilling 20 问全部锁定），待用户批准
> 日期：2026-09-12
> 作者：ZCode + 用户共同决策
> 依据：
> - ADR-0023（本设计的决策记录，`docs/adr/0023-prompt-registry.md`）
> - ADR-0020a（`agent_profile` 运行时消费 — system_prompt 注入纪律）
> - ADR-0010（CapabilityRegistry）、ADR-0011（Skills 渐进披露）、ADR-0015（AgentFactory）
> - 上游参考：DeepSeek Harness / pi-mono / oh-my-pi / ZCode（对照表见 ADR-0023 Context）
> - 架构不变量 #1–#22（`AGENTS.md` §7）
> - 工程规格 `goal/Lightweight_Observable_Agent_Harness_Spec/docs/spec/`

---

## 0. 背景与根因

全仓库模型可见的自然语言文本散落在 **15+ 处、跨 8 个模块**（完整清单见 ADR-0023 Context）。由此产生三个具体痛点：

1. **没有单一入口**——想知道"这个 agent 到底看到哪些 prompt、按什么顺序"，需要在 8 个模块间来回跳。
2. **无法动态组装**——重复要求无法共享。实证：`coding` 与 `research_review` 两条 profile prompt 里都有"结束时给出简明总结…以及任何未解决事项"，**措辞已经漂移**。
3. **修改成本高**——调一句文案必须打开对应 `.py`、读懂上下文、改完跑测试确认没碰坏别的逻辑。

本 PRD 只补 prompt 管理层，**不改 Agent Loop、不改事件模型、不改 ContextProvider 检索语义**。

---

## 1. 目标与非目标

### 目标

1. **单一入口**：一处可查看全部 prompt section 及其最终组装顺序。
2. **严格模板化**：`{{variable}}` 插值，未声明 / 未提供 / 格式非法**一律抛错**（绝不静默渲染为空）。
3. **可组装**：section 按 scope 筛选组合；共享 section 消除重复；工具 guidance 自动归集。
4. **显式排序**：集中 order 表，一处看清全序。
5. **作用域**：不同 profile / agent 拿到不同的 section 组合。
6. **Persona 可配置**：env JSON 覆盖内置前后缀，不改代码。
7. **不变量校验**：R1–R7 + 进程启动自检，超出全部参考实现。
8. **修改成本降低**：改 profile/辅助 prompt 文案 = 开 1 个文件；改工具 guidance = 就地改工具元数据。

### 非目标（明确排除）

- **ContextProvider 的检索内容**（memory / skills 结果）——有界检索 + token 预算 + 失败降级 + `MEMORY_DEGRADED` 事件是它的核心语义，纳入注册表会破坏这些（不变量 #16/#21）。
- **历史事实回放**（`derive.py` 的压缩摘要）——那是过去事件的**数据**，不是我们创作的 prompt。
- **外部 SDK 的 prompt**（langmem 内部指令）。
- **Prompt 版本化 / A-B 实验**——四份参考实现都没有；git 提交即版本。
- **模板的条件 / 循环 / 继承**——四份参考实现都没有这个需求；自研替换器不支持。
- **`.md` 文件化存储**——项目无包内数据文件先例，`uv_build` 打包行为未证实；集中到 Python 模块已解决主要痛点。

---

## 2. 已锁定决策（20 项）

| # | 决策点 | 选择 |
|---|--------|------|
| Q1 | 正文存储 | **A** 集中到专用 Python 模块（`prompt/sections.py` 等） |
| Q2 | 模板引擎 | **A** 自研极简严格替换器（`{{name}}`，未知即抛，无递归） |
| Q3 | 作用域模型 | **A** 扁平注册表（重名抛错，同 `CapabilityRegistry`）+ **组装期筛选** |
| Q4 | 管理边界 | **C** 管 profile / 工具 guidance / 运行时上下文 / 辅助 LLM prompt / 纠偏框架；排除检索内容、历史回放、外部 SDK |
| Q5 | 落地节奏 | **B** 分三阶段 P0 / P1 / P2 |
| Q6 | Persona 配置 | **B** 环境变量 JSON（`AGENT_PERSONA`），沿用既有"复杂配置=env JSON"约定 |
| Q7 | 校验规则 | **D** R1–R5 + R7 完整规则集 + **进程启动自检**（R6 由稳定排序保证，非校验） |
| Q8 | 命名与排序 | **(a)+(i)** 冒号命名空间 + **集中 `SECTION_ORDERS` 常量表** |
| Q9 | 变量模型 | **B** section 声明 `requires`（从模板**自动推导**）+ 全局变量池 |
| Q10 | 注入目标 | **C** `system` + `meta_user` 两段 |
| Q11 | 装配点 | **A** 注册表作为 `ContextBuilder` 上游（P0 零契约变更） |
| Q12 | P0 section 组织 | **a** 单条搬运，组装产物与现有字符串**逐字节相同**（零行为变化） |
| Q13 | R5 必需项 | **a** 只要求 `identity`（`main` 无"结束总结"要求，故 `output` 不能设为必需） |
| Q14 | 变量声明 | **A** 变量名**预声明**（否则 R3/R4 注册期校验无法实现） |
| Q15 | P0 票数 | **A** 3 票；工作区 `feat/backend`；产物 ADR-0023 + 本 PRD |
| Q16 | 快照载体 | **b** 非持久化、运行时组装，注入在**当前用户消息之前** |
| Q17 | 工具 guidance 归属 | **C** 工具自带 `prompt_guidance` 元数据 + 注册时归集；其余集中 |
| Q18 | 总票数 | **B** 8 票（P0 三 + P1 二 + P2 三） |
| Q19 | 快照内容 | **C** cwd + 日期 + 模型名 + 可用工具清单 + OS |
| Q20 | 既有注入污染 | **B** 在 P2 的"纠偏/框架消息"票内顺带修 extractor 过滤 |

---

## 3. 架构设计

### 3.1 Section 数据模型

```
PromptSection
├── name: str              # 冒号命名空间，如 "profile:coding:identity"
├── order: int             # 取自集中 SECTION_ORDERS 表，非手写散值
├── scopes: frozenset[str] # 该 section 参与哪些 scope（如 {"profile:coding"}）
├── target: Target         # SYSTEM | META_USER
├── text: str              # 模板正文（含 {{var}}）
├── requires: frozenset[str]  # 从 text 自动扫描推导
└── description: str       # 供 available() 视图与文档
```

### 3.2 注册表 API

```
PromptRegistry
├── register(section) -> None        # R1 名唯一 / R2 scope 合法 / R3 变量名合法
├── variable(name, description)      # 预声明变量名（Q14=A）
├── sections(scope) -> list[Section] # 按 scope 筛选，按 (order, name) 稳定排序
├── available() -> list[Section]     # 全量视图（"一处看全貌"）
└── assemble(scope, variables) -> AssembledPrompt
                                     # R4 变量有值 / R5 identity 存在 / R7 非空
```

`AssembledPrompt` 按 `target` 分组产出两段文本（system / meta_user），供 `ContextBuilder` 分别注入。

### 3.3 模板器（自研，严格）

- 只识别 `{{name}}`，`name` 匹配 `^[a-z][a-z0-9_]*$`（不允许内部空格）。
- **未声明 / 未提供值 / 语法非法** → 抛错，绝不留空。
- 替换值**不再二次扫描**（无递归插值）。
- 约 50 行，零依赖，无属性访问 / 方法调用能力（无注入面）。

### 3.4 组装管线

```
注册（模块 import 时声明全部 section + 变量）
    ↓  R1/R2/R3 注册期校验
进程启动自检：对全部 scope 跑一次空组装（fail-fast）
    ↓
assemble(scope, variables)
    ↓  筛选 scopes ∋ scope → 稳定排序 (order, name)
    ↓  R4 变量有值 / R5 identity 存在 / R7 非空
    ↓  按 target 分组渲染
AssembledPrompt { system_text, meta_user_text }
    ↓
ContextBuilder
    ├── system_text  → prepend 为列表首条 SystemMessage（既有路径，ADR-0020a）
    └── meta_user_text → 运行时组装，插在**当前用户消息之前**，**永不落盘**
```

### 3.5 校验规则

| 规则 | 内容 | 时机 |
|---|---|---|
| R1 | section 名非空且唯一 | 注册期 |
| R2 | scope 标签合法 | 注册期 |
| R3 | 变量名合法 | 注册期 |
| R4 | 模板引用变量在组装时有值 | 组装期 |
| R5 | 每个 scope 恰有一条 `identity` | 组装期 |
| R6 | 排序确定性（`(order, name)` 稳定排序） | 设计保证 |
| R7 | 组装产物非空 | 组装期 |
| — | 全 scope 空组装演练 | **进程启动自检** |

### 3.6 集中 order 表

```
-1000  harness:identity              （预留，P0 不启用）
    0  persona:prefix                （env 覆盖前缀）
  100  profile:<name>:identity
  200  profile:<name>:*              （profile 专属补充段）
 1000  output:summary                （共享产出要求）
 2000+ tool:<name>                   （工具 guidance，order 再按名）
 3000  aux:compaction
 3100  aux:memory_extraction
 3200  aux:fork_tail
 9000  frame:untrusted_data           （槽位：knowledge / websearch 共用）
 9100  corrective:tool_failure_guard
 9200  frame:recovery_skipped
 9500  runtime:context_snapshot      （meta_user 目标）
10200  persona:suffix                （env 覆盖后缀）
```

### 3.7 `meta_user` 快照的纪律（本设计最关键的安全边界）

已验证事实：`injected_by` 标记**只**被 `user_turn_count` 消费；持久化、`derive_messages()` 回放、记忆抽取**三条链路全部不设防**，且单独一条注入消息即令 `has_user_message` 为真、使 LLM 抽取的 USER 候选**不被降级为 SESSION**。

因此 `meta_user` 快照：

1. **不调用 `session.append`**——不落 JSONL；
2. **不进 `derive_messages()` 的事件投影**——因为不在 session events 里；
3. **不进记忆抽取**——因为抽取的输入来自 session events；
4. 由 `ContextBuilder` 在每次 build 时**运行时组装**，插在当前用户消息之前（列表内永远只有一份，旧的不累积）。

结果：三个污染面一次性消失，**不需要新增任何过滤器**。

---

## 4. 参考实现对照（摘要）

完整表见 ADR-0023。三条关键结论：

1. **严格插值是稀缺品**——四家中只有 DeepSeek Harness 做到未知变量抛错；pi 与 ZCode 静默渲染为空。本设计选严格。
2. **工具自注册片段是可组装的价值来源**——pi 的每工具 `{snippet, guidelines}` 即 D11 的原型。
3. **不变量校验是普遍短板**——只有 dsh 有专用 invariant 插件且仅覆盖 R1/R3 类；本设计的 R1–R7 + 启动自检超出全部参考实现。

---

## 5. 迁移范围

| 阶段 | 迁移对象 | 行为变化 |
|---|---|---|
| **P0** | `agent/profiles.py` 三条 profile system prompt | **零**（逐字节相同） |
| **P1** | `context/compactor.py:39` 六段式 / `memory/extractor.py:141` 抽取 / `session/fork.py:97` tail 摘要 + persona env 覆盖 | 文本等价搬迁；persona 是新增能力 |
| **P2** | 工具 `description`/guidance / 运行时上下文快照 / `runtime.py:928` 纠偏 + `knowledge/tools.py:27` untrusted 框架 + `recovery/coordinator.py` 裁决 | 前两者新增能力；第三者纯搬迁 + 顺带修 extractor 过滤 |

---

## 6. 票拆分（8 票）

### P0（机制，零行为变化）

| 票 | 标题 | Blocked by |
|---|---|---|
| T1 | **Prompt 注册表骨架** — `PromptSection` 数据模型 + `PromptRegistry`（register / variable / available，重名抛错）+ 集中 `SECTION_ORDERS` 表 + 自研严格模板器 + R1/R2/R3 注册期校验 | 无 |
| T2 | **组装与校验管线** — `sections(scope)` 筛选 + `assemble(scope, variables)` + `requires` 自动推导 + R4/R5/R7 + 进程启动自检 | T1 |
| T3 | **迁移三类 profile 到注册表** — 三条 system prompt 逐字迁入 `builtin.py`；`BUILTIN_PROFILES` 的 `system_prompt` 改为经 `_builtin_prompt(name)` 从注册表取（**单点接线**，见下方 D12 修正）；组装产物与迁移前**逐字节相同**断言；既有 3 个契约测试保持绿；新增 scoping / 校验测试 | T2 |

> **T3 对 D12 接线的修正（实现前发现，已采纳）**：D12 原文是「`assembly.py` 调 `registry.assemble()`」。实际接线点应放在 `agent/profiles.py`——`BUILTIN_PROFILES` 的 `system_prompt` 从注册表取，则 parent（`assembly.py:280` 读 `profile_spec.system_prompt`）与 child（`agent/factory.py:105` 读 `spec.system_prompt`）两条路径**零改动**自动一致，不存在两处调用点漂移；同时保留 `AgentSpec.system_prompt` 的普通字段语义，自定义 profile（`multiagent/provider.py:149` 允许注入）与 `tests/agent/test_system_prompt_wiring.py` 的 B2 契约都不被破坏。代价是 `agent` → `prompt` 新增一条单向依赖（`builtin.py` 内禁止 import `agent.*` 以防成环）。D12 的**意图**（注册表是唯一来源、P0 零行为变化）不变。

### P1（辅助 prompt + persona）

| 票 | 标题 | Blocked by |
|---|---|---|
| T4 | **辅助 LLM prompt 迁移** — 压缩六段式 / 记忆抽取 / fork tail 三处迁为 section；引入 `tail_text` 等变量；断言渲染结果与原文等价 | T3 |
| T5 | **Persona env 覆盖** — `AGENT_PERSONA` JSON 解析 + prefix/suffix 覆盖语义 + 非法 JSON / 未知键 / 超长值的失败处理与测试 | T3 |

### P2（工具 guidance + 运行时上下文 + 框架消息）

| 票 | 标题 | Blocked by |
|---|---|---|
| T6 | **工具 guidance 归集** — `Tool` 契约加 `prompt_guidance`（与 `side_effect`/`permission`/`reconcile_hint` 同构）；注册时自动归集为 `tool:<name>` section | T3 |
| T7 | **运行时上下文快照** — 非持久化运行时组装 + `meta_user` 注入路径（当前用户消息之前）+ Q19 内容清单 + prefix cache 稳定性测试 + **非持久化不变量测试**（断言快照不落 JSONL、不进 derive、不被抽取） | T3 |
| T8 | **纠偏/框架消息迁移 + 注入污染修复** — `runtime.py:959` 纠偏 / `knowledge/tools.py:27` + `websearch/tools.py:25` untrusted 框架（**同族两处**）/ `recovery/coordinator.py:146` 恢复跳过文案迁为 `FRAGMENT` section；**顺带修** extractor 入口剔除 `injected_by` 事件（恢复 USER→SESSION 降级保护）+ 正反向回归 | T3 / T4 / T7 |

### 依赖图

```
T1 → T2 → T3 ─┬→ T4 ─┐
              ├→ T5 ─┼→ T8
              ├→ T6  │
              └→ T7 ─┘
```
（T8 依赖 T4 的单 section 逐字节形制与 T7 的"不污染抽取"测试形制；T5/T6 只提供 `build_registry` 的最终形状，不阻塞 T8 开写。）

T4–T8 之间无依赖，可并行。

---

## 7. 验收与门禁

### 每票门禁

1. TDD：先红后绿。
2. `uv run pytest`（该票新增 + 相邻回归）。
3. `uv run ruff check src/ tests/` 干净。
4. `git diff --check` 干净。
5. code-review 双轴（Standards + Spec），零 finding 后 commit。
6. commit 消息含票号与 ADR-0023。

### P0 专项验收（关键）

- **逐字节相同断言**：`assemble(profile=X).system_text` 与迁移前 `BUILTIN_PROFILES[X].system_prompt` **完全相等**——这是"零行为变化"的机器可验证证据。
- **既有契约测试保持绿**：`tests/agent/test_system_prompt_wiring.py`（3）、`tests/context/test_builder_system_prompt.py`（5+）。
- **scoping 可证伪**：`assemble("profile:coding")` 不含 `main` 的 section，反之亦然。
- **严格性可证伪**：模板引用未声明变量 → 抛错（而非空串）。
- **启动自检生效**：人为破坏一条 section 使某 scope 缺 identity → import 时 fail-fast；自检覆盖注册表里**所有**非 `*` scope（含 P1/P2 新增的 `aux:*`）。

### 阶段门禁

每阶段结束跑全量 `uv run pytest -q`，零失败。

---

## 8. 风险与未决

| 风险 | 等级 | 缓解 |
|---|---|---|
| P0 迁移引入行为漂移 | 低 | 逐字节相同断言 + 既有契约测试保持绿 |
| `meta_user` 快照污染历史/记忆 | 中 | 非持久化纪律（§3.7）+ T7 的专项不变量测试 |
| 自研模板器的边界（嵌套 `{{`、未闭合） | 低 | T1 覆盖非法语法用例 |
| 快照含工具清单的 token 冗余 | 低 | 已接受；Q19=C 清单可配置，后续可测 |
| 工具 guidance 分两处作者位置 | 低 | D11 刻意的取舍，换取工具内聚 |
| `requires` 自动推导对复杂模板的准确性 | 低 | 只支持 `{{name}}` 单一语法，无嵌套，扫描确定 |

### 未决（不阻塞 P0）

- `meta_user` 段在**多步 run 内**（工具调用中途）的注入位置精确定义——需在 T7 实现时确定并测试（候选：最后一条 `HumanMessage` 之前）。
- prefix cache 命中率的实测验证（当前是设计推理，非测量）。

---

## 9. 附：票外发现（仅报告，不在本 PRD 范围）

1. **`pyyaml` 未声明依赖**——`skills/discovery.py:95` 使用 `yaml.safe_load`，但 `pyproject.toml` 未声明 `pyyaml`，目前靠传递依赖侥幸可用。若未来引入 YAML 配置需先修。
2. **`injected_by` 保护不完整**——详见 §3.7。本设计的 T8 顺带修 extractor 侧，但 `derive_messages()` 回放侧**未修**（因为从投影里过滤会让模型看不见该消息，需单独评估）。
3. **运行时上下文注入此前完全空白**——T7 是首次引入，无历史包袱也无既有测试保护。

---

## 10. 实现约定（全部 8 票共享，勿在各票内重复发明）

> 本章是**规范性的**。实现时照此执行；若发现本章与具体票冲突，以本章为准并在 commit 中说明。

### 10.1 文件布局（新增包）

```
src/agent_harness/prompt/
├── __init__.py       # 公开导出（见 §10.2）
├── errors.py         # PromptError（T1 建）
├── section.py        # Target / PromptSection / SECTION_ORDERS（T1 建）
├── template.py       # extract_variables / render（T1 建）
├── registry.py       # PromptRegistry / AssembledPrompt（T1 建 register 侧，T2 加 assemble）
└── builtin.py        # 内置 section 正文——改 prompt 文案只开这一个文件（T3 建）
```

**`builtin.py` 是 prompt 正文的唯一集散地**（工具 guidance 除外，见 D11）。P0 只放三条 profile；P1/P2 在此文件继续追加。这是"改文案开 1 个文件"这一承诺的物理落点。

```
tests/prompt/
├── __init__.py                     # T1 建（tests/ 下各目录都有 __init__.py，照办）
├── test_template.py                # T1
├── test_registry.py                # T1
├── test_assemble.py                # T2
├── test_self_check.py              # T2
├── test_profiles_migration.py      # T3
├── test_builtin_registry.py        # T3（默认注册表的 scoping/校验）
├── test_aux_prompts.py             # T4
├── test_persona.py                 # T5
├── test_tool_guidance.py           # T6
├── test_runtime_snapshot.py        # T7
└── test_frames_migration.py        # T8
```

### 10.2 公开导出（`prompt/__init__.py`）

```python
from agent_harness.prompt.errors import PromptError
from agent_harness.prompt.section import SECTION_ORDERS, PromptSection, Target
from agent_harness.prompt.template import extract_variables, render
from agent_harness.prompt.registry import AssembledPrompt, PromptRegistry
from agent_harness.prompt.builtin import DEFAULT_REGISTRY   # T3 起

__all__ = [
    "AssembledPrompt", "DEFAULT_REGISTRY", "PromptError", "PromptRegistry",
    "PromptSection", "SECTION_ORDERS", "Target", "extract_variables", "render",
]
```

### 10.3 错误类型：单一异常 + `code` 字段

**照抄 `capability/base.py:23-28` 的 `CapabilityError` 模式**（项目既有约定，勿自创多异常类）：

```python
# src/agent_harness/prompt/errors.py
class PromptError(RuntimeError):
    """Prompt 域显式错误词汇表。所有校验失败都走它 + code 区分。"""
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
```

`code` 取值范围（测试按 `code` 断言，不按 exception 类型断言）：

| code | 触发 | 规则 |
|---|---|---|
| `duplicate_section` | 重名注册 | R1 |
| `invalid_section_name` | 名不符合 §10.5 命名式 | R1 |
| `invalid_scope` | scope 不符合 §10.5 | R2 |
| `invalid_variable_name` | 变量名不符合 `^[a-z][a-z0-9_]*$` | R3 |
| `undefined_variable` | 模板引用了**未预声明**的变量 | R3 |
| `template_syntax` | `{{` 未闭合 / 名非法 / 孤立 `}}` | R3 |
| `missing_variable` | 变量已声明但本次**未提供值** | R4 |
| `missing_identity` | 该 scope 缺 `identity` section 或存在多条 | R5 |
| `empty_assembly` | 筛选后无任何 section | R7 |
| `invalid_persona_config` | `AGENT_PERSONA` 不是合法 JSON / 含未知键 / 类型错 / 超长（T5，形制照抄 `CapabilityError("init_failed")`） | — |

### 10.4 数据模型（精确签名，照此实现）

```python
# src/agent_harness/prompt/section.py
class Target(str, Enum):
    SYSTEM = "system"        # 装进 system-role 消息（SystemMessage）
    META_USER = "meta_user"  # 装进 user-role 消息（HumanMessage）
    FRAGMENT = "fragment"    # 独立文本片段：由调用方决定嵌入位置（非消息）
```

**`target` 的判据只有一个：这条 section 的产物要装进哪里**，与"是否持久化"无关（持久化纪律是 `runtime:context_snapshot` 这个具体 section 的要求，见 T7，不是 `META_USER` 的定义）。按此判据：

- `aux:compaction` / `aux:memory_extraction` → `SYSTEM`（现状即 `SystemMessage`）；
- `aux:fork_tail` → `META_USER`（现状即 `HumanMessage`，T4 首个消费者）；
- `runtime:context_snapshot` → `META_USER`（T7，唯一带"不落盘"额外约束的 section）；
- `frame:untrusted_*` / `corrective:tool_failure_guard` / `frame:recovery_skipped` → `FRAGMENT`（T8）。这三类文本**不是消息**：分别嵌进工具结果内容（`knowledge/tools.py`、`websearch/tools.py`）、注入的会话事件内容（`agent/runtime.py` 纠偏）、合成 ToolResult（`recovery/coordinator.py`）。给它们标 `SYSTEM`/`META_USER` 是假信息——调用方据此去装 SystemMessage/HumanMessage 就会装错。

**`FRAGMENT` 的消费者用 `.fragment_text`**（与 `.system_text` / `.meta_user_text` 并列）。`FRAGMENT` section 受同样的 R1/R2/R3 校验，scope 照样参与筛选与启动自检；`"*"` 同样不匹配非 `profile:` scope，所以 persona / 工具 guidance **不会**漏进这些片段。

```python
#: 集中 order 表（PRD §3.6）。每个键对应一个 section 命名前缀。
SECTION_ORDERS: dict[str, int] = {
    "harness:identity": -1000,
    "persona:prefix": 0,
    "profile:identity": 100,     # profile:<name>:identity 用此值
    "profile:extra": 200,        # profile:<name>:<其他> 用此值
    "output:summary": 1000,
    "tool": 2000,                # 工具 guidance 的基准；同 order 内按 section 名排序
    "aux:compaction": 3000,
    "aux:memory_extraction": 3100,
    "aux:fork_tail": 3200,
    "frame:untrusted_data": 9000,       # 槽位：knowledge / websearch 两条 frame section 共用
    "corrective:tool_failure_guard": 9100,
    "frame:recovery_skipped": 9200,     # T8：恢复期"未启动即跳过"的合成 ToolResult 文案
    "runtime:context_snapshot": 9500,
    "persona:suffix": 10200,
}

@dataclass(frozen=True)
class PromptSection:
    name: str
    order: int
    scopes: frozenset[str]     # 显式 scope 名；"*" = 所有 profile:<name> scope（不含 aux:*，见 §10.5）
    target: Target
    text: str
    description: str = ""

    @property
    def requires(self) -> frozenset[str]:
        """从 text 扫描推导——不是构造参数，无状态、无陈旧风险。"""
        return extract_variables(self.text)
```

**注意 `requires` 是 property 而非字段**：不手写、不会与 `text` 失配。

### 10.5 命名规范（R1/R2/R3 的判据）

| 对象 | 正则 | 合法示例 | 非法示例 |
|---|---|---|---|
| section 名 | `^[a-z][a-z0-9_]*(:[a-z][a-z0-9_]*)+$`（**至少两段**） | `profile:coding:identity`、`tool:bash` | `bash`、`Profile:x`、`a:` |
| scope 名 | `^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$`，或字面量 `*` | `profile:coding`、`*` | `coding`、`Profile:x` |
| 变量名 | `^[a-z][a-z0-9_]*$` | `tail_text`、`tool_name` | `TailText`、`tool-name`、`_x` |

**scope 语义**：section 被纳入 `assemble(scope=X)` 当且仅当 `X in section.scopes`，或 `"*" in section.scopes` **且 X 以 `profile:` 开头**。

> **为什么 `*` 不覆盖 `aux:*`（本设计的关键边界）**：`*` 表达的是"所有 agent profile"，即"所有以 agent 身份说话的 system prompt"。`aux:*` 是**辅助 LLM 的一次性指令**（摘要器、抽取器），不是一个 agent 身份——把 persona（"你是 X"）注入摘要器会直接污染它的指令语义。若 `*` 覆盖全部 scope，则 AGENT_PERSONA 一设就会改掉压缩/抽取 prompt 的文本，P1 的"文本等价搬迁"立刻破产。
>
> 边界做成**结构性**的（靠 scope 前缀判定），而不是靠每个 `aux` 调用点自觉传参：新增辅助 prompt 的人**不可能**忘记排除 persona。反过来，若某天确有 section 需要进入 `aux:*`，显式把 `"aux:xxx"` 写进 `scopes` 即可——不会被任何通配静默包含。

### 10.6 模板器（精确算法，照此实现）

```python
_VAR = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
```

`render(text, variables) -> str` **单趟扫描**（绝不整体 `re.sub`，也绝不对替换结果重扫）：

```
i = 0; out = []
while i < len(text):
    start = text.find("{{", i)
    if start == -1:
        tail = text[i:]
        if "}}" in tail: raise PromptError(..., code="template_syntax")   # 孤立 }}
        out.append(tail); break
    before = text[i:start]
    if "}}" in before: raise PromptError(..., code="template_syntax")     # 孤立 }}
    out.append(before)
    m = _VAR.match(text, start)
    if m is None: raise PromptError(..., code="template_syntax")          # {{ 未闭合 / 名非法 / 含空格
    name = m.group(1)
    if name not in variables: raise PromptError(..., code="missing_variable")
    out.append(variables[name])                                          # 原样写入，不再扫描
    i = m.end()
return "".join(out)
```

`extract_variables(text) -> frozenset[str]`：同一趟扫描逻辑，**语法非法同样抛 `template_syntax`**（使注册期就拦住坏模板），返回引用到的变量名集合。

**必测的边界**（T1 验收）：
`{{name}}` ✓ · `{{ name }}`（含空格）✗ · `{{Name}}`（大写）✗ · `{{}}` ✗ · `{{{name}}}` ✗ · `{{name` ✗ · `name}}` ✗ · 替换值本身含 `{{x}}` → **原样输出，不重扫** ✓

### 10.7 组装语义（精确）

```python
@dataclass(frozen=True)
class AssembledPrompt:
    system_text: str
    meta_user_text: str

class PromptRegistry:
    def assemble(self, scope: str, variables: Mapping[str, str] | None = None) -> AssembledPrompt:
        variables = dict(variables or {})
        included = self.sections(scope)          # 筛选 + 按 (order, name) 稳定排序
        if not included:                          # R7
            raise PromptError(..., code="empty_assembly")
        if scope.startswith("profile:"):          # R5
            ids = [s for s in included if s.name == f"{scope}:identity"]
            if len(ids) != 1:
                raise PromptError(..., code="missing_identity")
        # R4 由 render 抛 missing_variable 兜住
        system_parts = [render(s.text, variables) for s in included if s.target is Target.SYSTEM]
        meta_parts = [render(s.text, variables) for s in included if s.target is Target.META_USER]
        return AssembledPrompt("\n\n".join(system_parts), "\n\n".join(meta_parts))
```

**拼接分隔符固定为 `"\n\n"`**。当 scope 只命中一条 section 时（P0 的 profiles 即如此），产物 = 该 section 的原文，**无多余分隔**——这是 T3"逐字节相同"能成立的前提。

### 10.8 启动自检（T2）

```python
# registry.py 或 builtin.py
def run_self_check(registry: PromptRegistry, scopes: Iterable[str]) -> None:
    """对每个 scope 跑一次组装，fail-fast。配置错误在进程启动暴露。

    变量用空串占位（取自各 section 自动推导的 requires），因此只验证结构完整性
    （命名/scope 合法、identity 唯一、产物非空、模板语法），不验证变量是否会被
    调用方真正提供——后者静态不可判定。
    """
    for scope in scopes:
        names = {n for s in registry.sections(scope) for n in s.requires}
        registry.assemble(scope, dict.fromkeys(names, ""))
```

`builtin.py` 末尾：
```python
DEFAULT_REGISTRY = _build_registry()
run_self_check(DEFAULT_REGISTRY, _declared_scopes(DEFAULT_REGISTRY))
```
自检的 scope 集 = 注册表里**所有非 `*` 的 scope**（从各 section 的 `scopes` 集合并集去重得到）。规则无例外：注册表里出现的每个 scope 都必须能组装成功，新增 section 无需维护豁免名单。

> **修正记录**：初版写的是「自检 scope 集 = 仅 `profile:<name>`」+「传 `{}` 空变量」。T4 引入 `aux:fork_tail`（正文含 `{{tail_text}}`）后，空 `{}` 会让进程 **import 期**抛 `missing_variable`（这不是配置错误）；而把含变量的 scope 排除在自检之外，又会让新增的辅助 prompt 完全失去启动期校验。改为「自动填空串 + 覆盖所有 scope」同时解决两者，且把规则收敛为一句无例外的话。

### 10.9 兼容性纪律（P0 的铁律）

`tests/agent/test_system_prompt_wiring.py`（3 条）、`tests/context/test_builder_system_prompt.py`（6 条）、`tests/test_assembly_agent_profile.py`（7 条）**锁定了既有契约**：

- `system_prompt` 是 runtime 装配期上下文，**不落 JSONL**（不变量 #5）；
- 计入 token 预算，且**缓存复用**；
- 压缩路径也要补回其成本；
- `agent_profile=None` → `ContextBuilder.system_prompt is None`（向后兼容）。

**P0 一律不得修改这些测试的断言。** 若某条断言与注册表接线冲突，**停下来报告**，不要改测试。

### 10.10 每票通用验收命令

```bash
uv run pytest tests/prompt/ -q            # 本票新增
uv run pytest -q                          # 全量回归，零失败
uv run ruff check src/ tests/             # 干净
git diff --check                          # 干净（无空白/冲突标记）
```

commit 消息格式：`feat(prompt): T<n> #<issue> — <一句话>` + 正文说明关键取舍与验证证据。
