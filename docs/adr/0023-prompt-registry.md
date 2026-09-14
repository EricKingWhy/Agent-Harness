# ADR-0023 — Prompt 注册表：集中管理 + 严格模板化 + 组装期筛选

**Status**: Proposed（待用户批准 PRD 后转 Accepted）
**Date**: 2026-09-12
**Related**: ADR-0020a（`agent_profile` 运行时消费 — system_prompt 注入纪律）、
ADR-0010（CapabilityRegistry）、ADR-0011（Skills 渐进披露）、
ADR-0015（Multi-Agent / AgentFactory）、ADR-0018（Langfuse 旁路观测）
**Supersedes**: 无（新增能力）

---

## Context

### 现状：prompt 散落且在代码里

全仓库模型可见的自然语言文本散落在 **15+ 处**、跨 8 个模块：

| 类别 | 位置 |
|---|---|
| Agent profile system prompt | `agent/profiles.py:65,79,90` |
| 压缩摘要 prompt | `context/compactor.py:39` |
| 记忆抽取 prompt | `memory/extractor.py:141-143` |
| Fork tail 摘要 prompt | `session/fork.py:97-102` |
| 技能目录框架 | `skills/context_provider.py:16` |
| 记忆注入框架 | `memory/context_provider.py:46` |
| 工具失败纠偏（注入式 user 消息） | `agent/runtime.py:928-942` |
| Recovery 裁决消息 | `recovery/coordinator.py` |
| 知识库 untrusted 框架 | `knowledge/tools.py:27` |
| 工具 description / `Field(description=)` | 全部 `tools/*.py`、`websearch/`、`skills/tool.py`、`knowledge/tools.py`、`multiagent/tools.py:89` |

由此产生三个具体痛点：

1. **没有单一入口**——想知道"这个 agent 到底看到哪些 prompt、按什么顺序"，需要在 8 个模块间来回跳。
2. **无法组装**——重复要求无法共享。实证：`output:summary` 式要求（"结束时给出简明总结…以及任何未解决事项"）在 `coding` 与 `research_review` 两条 prompt 里重复出现、措辞已漂移。
3. **修改成本高**——调一句文案必须打开对应的 `.py`、读懂上下文、改完跑测试确认没碰坏别的逻辑。

### 关键约束：注入式 user 消息**只被部分保护**

设计过程中验证发现（证据见下），`injected_by` 标记目前**只有一个消费者**：

| 链路 | 是否被保护 | 证据 |
|---|---|---|
| `user_turn_count` 计数 | ✅ | `session/session.py:357-367` 检查 `data.get("injected_by")` |
| 持久化到 JSONL | ❌ 照样落盘 | `runtime.py:930-942` 走 `session.append(USER_MESSAGE, ...)` |
| `derive_messages()` 回放 | ❌ 无条件投影成 `HumanMessage` | `derive.py:144-146` 无标记检查 |
| 记忆抽取 | ❌ 无过滤；**单独一条注入消息即令 `has_user_message` 为真** | `extractor.py:152`，使 LLM 抽取的 USER 候选**不被降级为 SESSION** |

推论：**运行时上下文绝不能作为持久 `user/message` 注入**——否则会被落盘、每轮回放、并被抽取成跨会话用户偏好。它必须走与 `system_prompt` 相同的纪律（ADR-0020a：运行时装配上下文，不落 JSONL）。

### 上游参考

| 维度 | DeepSeek Harness | pi-mono / oh-my-pi | ZCode |
|---|---|---|---|
| 单一入口 | `ctx.systemPrompt` 注册表服务 | `buildSystemPrompt()` 单函数 | `ContextBuilder` + 每 section 一个 builder |
| 正文存储 | inline TS + `prompt.ts` | pi inline；oh-my-pi `prompts/*.md` | 核心在 bundle；扩展 `.md` |
| 模板 | 自研，严格 `{{var}}`，未知即抛 | Handlebars（非严格：未知渲染为空） | 无插值（slash 命令 `$1`，未知静默为空） |
| 排序 | 集中 `SECTION_ORDERS`（-1000…10200） | 固定阶段顺序 | push 顺序 + 按 (target, 稳定性) 重排 |
| 作用域 | global vs scoped 分层（覆盖） | profile / 子代理独立文件 | 模式 + 子代理独立 prompt |
| Persona | YAML prefix/suffix + preset | `personality` + `PERSONALITY.md` | config 对象；自定义**整体替换** Identity |
| 校验 | ✅ 专用 invariant 插件 | 弱 | 弱 |
| 组件自注册 | ✅ 工具 schema 同管线 | ✅ 每工具导出 `{snippet, guidelines}` | ✅ `addSection()` |

三条结论：**严格插值是稀缺品**（4 家中仅 dsh 做到，另两家静默渲染为空——正是本项目要避免的故障模式）；**工具自注册片段是"可组装"的价值来源**；**不变量校验是普遍短板**（本设计要做，即是超出全部参考实现的地方）。

### 项目既有约束

- **无包内数据文件先例**：`find src/agent_harness -type f ! -name '*.py'` = 0；`uv_build` 后端无 `package-data` 配置。随包分发 `.md` 的可行性**未经证实**。
- **无配置文件机制**：`Settings(BaseSettings)` 只读 `.env`/环境变量；复杂配置是**环境变量里的 JSON 字符串**（`CAPABILITIES`、`AGENT_MODELS`）。ADR-0012a 仅为运维文档模板，无运行时 preset 加载器。
- **运行时上下文注入是空白**：今天无任何 cwd / 模型名 / 日期 / 工具清单注入。
- **`CapabilityRegistry` 是扁平的**：`capability/base.py:62`，重名**直接抛错、绝不静默覆盖**，无作用域层。

---

## Decision

### D1 — 存储形态：集中到专用 Python 模块

Prompt 正文集中到 `src/agent_harness/prompt/` 下的专用模块（如 `sections.py`），不再分散于各功能模块。

**为什么不文件化**：探索过 `prompts/*.md`，但项目**无包内数据文件先例**、`uv_build` 打包行为未经证实，在未验证的打包假设上盖楼风险过高。集中到单一模块已把"翻 8 个模块"降为"开 1 个文件"。

_Avoid_: 依赖未验证的打包行为；把 prompt 与业务逻辑混在同一模块。

### D2 — 模板引擎：自研极简严格替换器

`{{name}}`，其中 `name` 匹配 `^[a-z][a-z0-9_]*$`。**未声明 / 未提供值 / 格式非法一律抛错**。替换值**不再二次扫描**（无递归插值）。

**为什么不用 Jinja2**：模板可能来自配置（persona 覆盖），Jinja2 的属性访问与方法调用是**注入攻击面**；且条件/循环/继承一个都不需要。

_Avoid_: 未知变量静默渲染为空（pi / ZCode 的行为，正是要避免的故障模式）；引入模板执行能力。

### D3 — 作用域：扁平注册表 + **组装期筛选**

注册表**扁平**、重名即抛错（与 `CapabilityRegistry` 同构）。每个 section 自带 scope 标签（如 `profile:coding`），`assemble(scope)` 时**筛选**而非覆盖。

**为什么不分层覆盖**：`CapabilityRegistry` 的契约是"重名即抛错"，而 scoped-overrides-global 需要允许重名——两套语义不能在项目里共存。作用域的真实需求只是"不同 agent 拿不同 section 组合"，筛选即可满足，且不引入"同名谁赢"的歧义。

**通配 `"*"` 只匹配 `profile:<name>` scope**，不匹配 `aux:*` 等辅助/基础设施 scope。`*` 的语义是"所有 agent profile"——`aux:*` 是辅助 LLM 的一次性指令，不是 agent 身份；若 `*` 覆盖全部 scope，则设了 persona 就会改掉压缩/抽取 prompt 的文本，P1 的"文本等价搬迁"破产。这条边界靠 scope 前缀判定，是**结构性**的：新增辅助 prompt 的人不可能忘记排除 persona。需要进入 `aux:*` 的 section 必须显式写出该 scope 名。

_Avoid_: 覆盖层语义（与既有注册表契约冲突）；把 prompt 当安全边界；让 `*` 覆盖一切（persona/框架段会静默泄漏进摘要器与抽取器的指令）。

### D4 — 边界：管理"我们创作的、模型可见的自然语言文本"

**纳入**：① profile system prompt；② 工具 description 与 guidance；③ 运行时上下文；④ 辅助 LLM prompt（压缩 / 抽取 / fork tail）；⑤ 纠偏与框架消息。

**排除**：⑥ ContextProvider 的**检索内容**（memory / skills 结果——有界检索 + token 预算 + 失败降级 + `MEMORY_DEGRADED` 事件，不变量 #16/#21）；⑦ **历史事实回放**（`derive.py:132` 的压缩摘要是过去事件的**数据**，非我们创作的 prompt）；⑧ 外部 SDK 的 prompt（langmem）。

_Avoid_: 把检索内容塞进注册表（破坏其预算与降级语义）；把历史数据当 prompt 管理。

### D5 — 校验：完整规则集 + 启动自检

| 规则 | 内容 | 时机 |
|---|---|---|
| R1 | section 名非空且唯一 | 注册期 |
| R2 | scope 标签合法（拼错即抛） | 注册期 |
| R3 | 变量名合法（`^[a-z][a-z0-9_]*$`） | 注册期 |
| R4 | 模板引用的变量在组装时**有值** | 组装期 |
| R5 | 每个 profile/scope 恰好有一条 `identity` section | 组装期 |
| R6 | 排序确定（按 `(order, name)` 稳定排序——设计保证，非校验） | — |
| R7 | 组装产物非空 | 组装期 |
| — | **进程启动自检**：对全部已声明 scope 跑一次空组装，fail-fast | import 后 |

R5 的清单**刻意最小**：只有 `identity` 是全部 profile 都有的事实（`main` 的 prompt 里并无"结束总结"要求，故不能设 `output` 为必需项）。

_Avoid_: 把 R5 清单拍脑袋堆大；只在组装期才发现悬空引用。

### D6 — 命名与排序：冒号命名空间 + 集中 order 表

命名用冒号分段：`profile:coding:identity`、`tool:bash`、`runtime:context_snapshot`、`aux:compaction`、`frame:untrusted_data`。order 集中在一张常量表：

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
 9000  frame:untrusted_data
 9100  corrective:tool_failure_guard
 9500  runtime:context_snapshot      （meta_user 目标）
10200  persona:suffix                （env 覆盖后缀）
```

集中表的价值：**一处看清全部 prompt 的最终顺序**。

_Avoid_: 每个 section 分散声明 order 数字（无法一眼看全序）。

### D7 — 变量模型：预声明 + `requires` 自动推导

`registry.variable(name, description=…)` 登记变量名；每个 section 的 `requires` 从模板文本**自动扫描推导**（不手写）；注册期校验 `requires ⊆ 已声明集合`；组装期从 context 取值，缺值抛错。

没有预声明，R3/R4 的注册期校验就无法实现（只能退化到组装期才发现），且"系统里有哪些变量"也就无法成为一处可 grep 的清单。

_Avoid_: 全动态变量（失去注册期校验能力）。

### D8 — 注入目标：`system` + `meta_user` 两段

稳定内容进 `system` 前缀；易变的运行时上下文作为 **`meta_user`** 段注入。

**关键纪律（由 Context 节的验证推出）**：`meta_user` 段**运行时组装、永不落盘**——不 `session.append`，不进 JSONL，不进 `derive_messages()` 的事件投影，因而也不进记忆抽取。这样三个污染面一次性消失，**且不需要新增任何过滤器**。这与 ADR-0020a 为 `system_prompt` 立下的纪律一致。

_Avoid_: 把运行时快照持久化为 `user/message`（会落盘、会回放、会被抽成跨会话偏好）；从 `derive_messages` 过滤注入消息（那样模型也看不见了，与注入目的自相矛盾）。

### D9 — 运行时快照的位置：当前用户消息之前

`meta_user` 段插在**当前用户消息之前**（而非紧跟 system 前缀）。

理由：列表里**永远只有一份**快照（旧的从不落盘、不会累积），prompt 前缀 = system + 历史对话保持稳定，只有尾部变化 → prefix cache 命中率最高。若紧跟 system 前缀，则易变内容之后**全部内容失去缓存**。

快照内容：cwd、当前日期、模型名、可用工具清单、OS/平台。

_Avoid_: 把易变内容插在 system 前缀之后（击穿 prefix cache）；让快照在多轮间累积。

### D10 — Persona 配置：环境变量 JSON 覆盖

`AGENT_PERSONA`（JSON，形如 `{"prefix":"…","suffix":"…"}`）覆盖内置 persona 前后缀，与既有 `CAPABILITIES` / `AGENT_MODELS` 的"复杂配置=env 里 JSON 字符串"约定一致，零新机制。

_Avoid_: 为 persona 单独引入配置文件加载器（项目无此先例，且需先修 `pyyaml` 未声明依赖）。

### D11 — 工具 guidance 的归属：工具自带 + 注册表归集

工具的 `prompt_guidance` 作为**工具元数据**声明（与 `side_effect` / `permission` / `reconcile_hint` 完全同构），注册时**自动归集**进 prompt 注册表。`profile` / 辅助 LLM / 框架消息仍集中在 `prompt/` 模块。

**为什么不全集中**：工具 guidance 与工具行为强耦合，强行集中会把"翻代码"问题**反向制造一遍**（改工具 → 去别处找它的 prompt）。"单一入口"的价值在于**查看与组装**，不在于所有文本物理同处一室——注册表提供"一处看全貌"的视图即可。

_Avoid_: 把工具 guidance 集中到 prompt 模块（反向翻代码问题）；让工具 guidance 游离在注册表之外（失去统一视图）。

### D12 — 装配点：注册表作为 `ContextBuilder` 的上游

P0 阶段由注册表产出正文，仍经既有 `ContextBuilder(system_prompt=…)` 注入。

理由：`tests/agent/test_system_prompt_wiring.py` 与 `tests/context/test_builder_system_prompt.py` 已锁定"system_prompt 是 runtime context、计入预算、不落 JSONL"的契约。D12 完整保留这些契约，使 P0 成为**纯文本来源替换、零行为变化**。等 P2 引入 `meta_user` 目标时再评估升级。

**实现期修正（T3 落地前发现）**：接线的**具体位置**由「`assembly.py` 调 `assemble()`」改为「`agent/profiles.py` 里 `BUILTIN_PROFILES` 的 `system_prompt` 从注册表取」。原因：`assembly.py:280`（parent）与 `agent/factory.py:105`（child）都只是转发 `AgentSpec.system_prompt`，把来源接到 `AgentSpec` 的构造处即可让两条路径零改动一致，避免两处调用点漂移；且 `AgentSpec.system_prompt` 仍是普通字段，自定义 profile 与既有 B2 契约不受影响。代价是新增 `agent` → `prompt` 单向依赖（`builtin.py` 内禁止 import `agent.*`）。决策意图不变，仅装配点收敛为一处。

_Avoid_: P0 就改 `ContextBuilder` 构造签名（把机制上线与契约变更耦在一票，回归难归因）；在 `assembly.py` 与 `agent/factory.py` 各调一次 `assemble()`（两个来源，后续必漂移）。

### D13 — 分阶段落地

| 阶段 | 范围 |
|---|---|
| **P0** | 机制（注册表 / 模板器 / 组装 / 校验）+ 迁移三类 profile system prompt（**逐字节相同**，零行为变化） |
| **P1** | 辅助 LLM prompt 迁移（压缩 / 抽取 / fork tail）+ persona env 覆盖 |
| **P2** | 工具 guidance 归集 + 运行时上下文快照 + 纠偏/框架消息迁移 |

P0 刻意**不分解** profile prompt：分解会改变组装后的文本 → 行为微变，与机制上线耦在一票会让回归无法归因。共享 section 的分解留到 P1（迁移辅助 prompt 时自然引入，可用测试证明"改一处、两消费者同时生效"）。

_Avoid_: P0 同时做机制与文案重构。

---

## Consequences

### Positive

- **单一入口达成**：一处可看全部 section 及其最终顺序（集中 order 表 + `available()` 视图）。
- **组装能力落地**：scope 筛选 + 共享 section，消除 profile prompt 间的重复要求。
- **修改成本降低**：改 profile / 辅助 prompt 文案 = 开 1 个文件找 section；改工具 guidance = 就地改工具元数据。
- **严格性可证伪**：未知变量抛错而非静默为空——这是四份参考实现里只有 dsh 做到的。
- **校验超出参考实现**：R1–R7 + 启动自检，覆盖参考实现普遍薄弱的环节。
- **零行为变化迁移**：P0 逐字节一致 + 既有 3 个契约测试保持绿，回归面极小。
- **运行时上下文纪律明确**：快照非持久化，规避了已验证的三个污染面。

### Negative / Trade-offs

- **多一层间接**：读 profile 行为要先跳到 prompt 模块再回来看装配点，而非直接读 `profiles.py`。
- **工具 guidance 分两处作者位置**（prompt 模块 / 工具类）：这是 D11 刻意的取舍，换来工具内聚。
- **快照含工具清单存在冗余**：本项目工具已通过 tool schema 绑定，快照再列一遍是重复 token（决策已接受，理由是显式清单有助于模型的自我定位；若后续测量显示 token 压力，`Q19=C` 的清单是可配置的）。
- **自研模板器**：不支持条件/循环——若将来出现"按环境拼不同段落"的需求，需扩展（当前四份参考实现里也没有这个需求）。

---

## Implementation evidence

（P0 落地后回填）

- 待填：`src/agent_harness/prompt/` 新模块
- 待填：`src/agent_harness/assembly.py` 接线点
- 待填：测试文件清单与数量
