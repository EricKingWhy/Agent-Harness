# 交接文档：Prompt Registry Phase（GitHub #161–#168）

> **写给接手的实现 AI**（在 `feat/backend` 分支、`D:\intelligence-agent-backend` worktree 工作）。
> 本 Phase 的设计与票面由前一会话（ZCode）完成、经用户逐问批准后定稿，**实现尚未开始**，现整体移交给你。
> 本文档是地图：东西在哪、按什么顺序做、哪些设计决定不许动。
> **票面本身才是可执行规格**——每张票 8k–18k 字符，含逐文件动作表、分步实现、逐条命名测试、反 Scope-Lock 清单、常见陷阱。按票干活，不要凭票名猜。

---

## 1. 交接范围

| 票 | 标题 | 依赖 |
| --- | --- | --- |
| #161 | PromptRegistry T1: 注册表骨架（PromptSection 模型 + 集中 order 表 + 严格模板器） | 无（起点） |
| #162 | PromptRegistry T2: 组装与校验管线（scope 筛选 + assemble + R4/R5/R7 + 启动自检） | T1（硬依赖） |
| #163 | PromptRegistry T3: 迁移三类 profile 到注册表（逐字节相同，零行为变化） | T2（硬依赖） |
| #164 | PromptRegistry T4: 辅助 LLM prompt 迁移（压缩六段式 / 记忆抽取 / fork tail） | T3 |
| #165 | PromptRegistry T5: Persona env 覆盖（AGENT_PERSONA JSON 前缀/后缀） | T3 |
| #166 | PromptRegistry T6: 工具 guidance 归集（Tool 契约加 prompt_guidance 元数据） | T3 |
| #167 | PromptRegistry T7: 运行时上下文快照（meta_user 非持久化注入 + 污染边界测试） | T2（建议 T3 后做） |
| #168 | PromptRegistry T8: 纠偏/框架消息迁移 + 顺带修记忆抽取的注入污染 | T3（**必须最后做**） |

- 硬链：**#161 → #162 → #163**。T3 之后按 #164 → #165 → #166 → #167 → #168 顺序做最稳（T8 放最后：它夹带一个真实安全缺陷修复，需要前面全部就位后做全量回归）。
- 两张票的 label 都是 `phase-prompt-registry` + `ready-for-agent`，在 GitHub 上按 label 可过滤。

## 2. 规格文件在哪（按优先级读）

1. **GitHub 票面 #161–#168** —— 可执行规格（怎么改、改哪些文件、每条测试断言什么、常见陷阱）。
2. `docs/PRD_PROMPT_REGISTRY.md` —— 产品需求；**§10 是契约终稿**：§10.4 Target 枚举、§10.5 scope 语义、§10.8 自检终稿 + SECTION_ORDERS 全表（14 键，含 `frame:recovery_skipped: 9200`）+ 错误码表（含 `invalid_persona_config`）。票面若与 §10 冲突，**以 §10 为准并报告**，不要自行改两边。
3. `docs/adr/0023-prompt-registry.md` —— D1–D12 决策记录；**D3 的通配边界段、D12 的实现期修正段**是纸面推演后补写的，必读。
4. 本文档 §4 红线。

设计已冻结（用户批准）。不要重新 grilling、不要改 PRD/ADR 的设计决定；发现规格实质冲突时停下报告（AGENTS.md §9.1）。

## 3. 当前仓库状态（2026-09-12 交接时点）

- 分支 `feat/backend` @ `dd90ae3`，working tree clean。
- 设计文档已在分支上：`docs/PRD_PROMPT_REGISTRY.md`、`docs/adr/0023-prompt-registry.md`、`CONTEXT.md`（已含 prompt-registry 术语）、本交接文档。
- 集成状态：本地 main（`D:\intelligence-agent`）= `4daa179` 已包含本分支此前全部在途批次；GitHub `origin/main` = `bf81346` 尚未 push（集成 AI 职责，与你无关）。
- 基线门禁参考（合并 main 前的批次实测）：**1618 passed / 10 skipped / 39 deselected / 0 failed**（约 157s），ruff clean。你开工前先自己跑一遍全量 pytest 确认起点基线，以实测为准。
- 工作协议：AGENTS.md §16 SDD 循环（见本文档 §6）。

## 4. 红线：这些设计决定不许动（票面已有，此处集中重申）

### 4.1 `*` 通配边界（ADR-0023 D3，最容易做错的一处）

`"*"` **只匹配 `profile:<name>` scope**，不匹配 `aux:*` / `frame:*` / `runtime:*`：

```text
§10.5：section 被纳入 assemble(scope=X) 当且仅当
  X in section.scopes，或 ("*" in section.scopes 且 X 以 "profile:" 开头)
```

为什么：否则用户一设 `AGENT_PERSONA`，压缩/抽取/fork tail 等辅助 prompt 文本全被改掉，T3/T4 的「逐字节等价搬迁」当场破产。这是**结构性防线**，不许靠测试数据凑巧绕过。

### 4.2 Target 三值与判据

```python
class Target(str, Enum):
    SYSTEM = "system"        # 装进 system-role 消息（SystemMessage）
    META_USER = "meta_user"  # 装进 user-role 消息（HumanMessage）
    FRAGMENT = "fragment"    # 非消息文本片段：嵌入位置由调用方决定
```

`AssembledPrompt` 三段：`system_text` / `meta_user_text` / `fragment_text`。判据是**消息角色**，与是否持久化无关。FRAGMENT 若并入 META_USER，非消息文本会被当成 user 消息持久化/抽取，污染边界失守。

### 4.3 T3 接线点：只准 `agent/profiles.py` 单点

`BUILTIN_PROFILES.system_prompt` 经 `_builtin_prompt(name)` 从注册表取——parent/child 两条路径零改动即一致（child 走 `AgentFactory.create` → `spec.system_prompt`，见 `agent/factory.py:105`）。

**禁止**在 `assembly.py` 与 `agent/factory.py` 各调一次 `assemble()`（ADR-0023 D12 Avoid 清单明令）。这同时保护 B2 契约与用户自定义 profile。

### 4.4 DEFAULT_REGISTRY 不读环境

`DEFAULT_REGISTRY = build_registry()` **永不读环境变量**（Settings 是注入式的）。persona 由装配点 `build_registry(persona=…)` 注入。

### 4.5 Persona（T5）

- `AGENT_PERSONA` env JSON；解析形制照抄 `capability/config.py` 的 `parse_capabilities_config`（显式失败，绝不静默吞）。
- 错误：`PromptError(code="invalid_persona_config")`；`PersonaConfig(strict=True, extra="forbid")`；prefix/suffix 各 ≤2000 字符。
- 拼接顺序：前缀(0) → base(100) → guidance(2000) → 后缀(10200)；`compose_agent_prompt(base, persona, guidance_text)` 与注册表组装的顺序由漂移守卫测试绑定。
- **未配置 persona 时行为逐字保持现状**（C4 契约）；用户显式配置时 persona 可独自产生 system prompt（覆盖无 system_prompt 的 profile 档位）。

### 4.6 Tool guidance（T6）

- `Tool.prompt_guidance: str | None` 可选 property，默认 `None`；**禁含 `{{}}`**（变量声明无处可放）。
- child 侧 `include_tool_guidance` 默认 `False`——让 B2 契约的成立与工具数据无关（结构性，不靠测试数据凑巧）。

### 4.7 运行时上下文快照（T7）

`ContextBuilder.runtime_context_provider: Callable[[], str] | None`：

- 每次 build 取值一次；插在最后一条 HumanMessage 之前；token 计入估算；压缩路径必须补回。
- **非持久化四不**：不 `session.append`、不进 derive、不进记忆抽取、不落 JSONL。
- 这是污染边界，由 `tests/memory/test_snapshot_not_extracted.py`、`tests/context/test_runtime_context_persistence.py` 锁死。

### 4.8 T8 顺带修的真实安全缺陷

`memory/extractor.py:152` 的 `has_user_message = any(e.type == USER_MESSAGE for e in events)` 会被 runtime 注入的 USER_MESSAGE（带 `injected_by`，注入点在 `agent/runtime.py` 约 959–972 的纠偏消息）点亮 → 注入内容可被洗成跨会话 USER 记忆。

修法：`extract()` 入口**单点**剔除 `_is_runtime_injected` 事件（票面有精确 spec 与测试清单）。这是安全修复，**不许**因为「难写测试」砍掉语义（§8 Scope Lock）。

### 4.9 冻结测试：断言一个字都不许改

- `tests/agent/test_system_prompt_wiring.py`（3 条）
- `tests/context/test_builder_system_prompt.py`（6 条）
- `tests/test_assembly_agent_profile.py` C1–C7

迁移后这些测试必须**原样**通过——它们就是「零行为变化」的裁判。

### 4.10 字节等价是验收标准

T3/T4/T8 的文本迁移全部要求**逐字节等价**。交接前已对三条 aux 文本与 T8 两条模板用 repr 法实测等价（corrective / recovery identical: True）。你迁移完成后必须用同样方法自证：

```bash
uv run python -c "分别 repr 旧内联文本与注册表组装文本，逐对断言相等"
```

## 5. 已知落点速查（省你重新翻代码）

行号以撰写时点为准，可能因合并微移；票面里都有函数名/锚点，以票面为准。

| 内容 | 位置 |
| --- | --- |
| 压缩六段式 | `context/compactor.py:38-62`（`_SIX_SECTION_PROMPT`），调用点 :105 |
| 记忆抽取 prompt | `memory/extractor.py:141-143` |
| fork tail summarizer | `session/fork.py:95-104`（`TailSummarizer.summarize`） |
| 纠偏消息（注入点） | `agent/runtime.py:959-972`（`injected_by`） |
| untrusted 提示两处 | `knowledge/tools.py` + **`websearch/tools.py:25`**（PRD 初稿只写了 knowledge，review 发现的第二处，T4 覆盖） |
| recovery 框架消息 | `recovery/coordinator.py:146-154` |
| profile_spec / ContextBuilder 构造 | `assembly.py` |
| persona 解析形制参照 | `capability/config.py`（`parse_capabilities_config`） |
| 能力配置 env 入口 | `config.py`（`capabilities: str = ""`） |
| Tool 契约元数据区 | `tooling/contract.py:187-215`（T6 在此加 `prompt_guidance`） |

新模块布局：`src/agent_harness/prompt/`（`registry.py` / `section.py` / `template.py` / `builtin.py` / `persona.py` / `errors.py` / `tool_sections.py`），测试在 `tests/prompt/`。

## 6. 你的 SDD 循环（AGENTS.md §16，逐票执行）

```text
1. 读票面 + 本文档 §4/§5 + PRD §10（不必重读全部 spec）
2. /implement（TDD 先红后绿）
3. /code-review 两轴（Standards + Spec）零 finding 才过；有问题 → 修复 → 再 review
4. ruff check + 全量 pytest
5. git add <本票相关文件> && git commit
6. 关单：gh issue close <n> --comment "验证证据：commit / 测试结果 / 关键文件"
7. 追加 docs/PHASE_STATUS.md（§16.5 格式）
```

- **只 commit，不 push / 不 merge / 不建 PR**（§13.2、§16.4；push 是集成 AI 的事）。
- commit message 风格沿用仓库现状：`feat(prompt): …（#16x）` / `test(prompt): …` / `docs(prompt): …`。
- 每张票完成即关单（§14.12：做完的必须立即关掉，不留 OPEN）。

## 7. 推演时修过的坑（票面已吸收，列出防你再踩）

1. `*` 通配若无 `profile:` 前缀限定 → persona 泄漏进 aux prompt（§4.1）。
2. T3 若接线到 assembly.py + factory.py 两处 → 双路径漂移 + B2 破坏（§4.3）。
3. 自检若「传 `{}` 直接 assemble」→ `aux:fork_tail` 等带 `requires` 的 scope 在 import 期误崩。终稿见 PRD §10.8：按各 scope 的 `requires` 并集自动填空串占位，且覆盖注册表**全部非 `*` scope**。
4. FRAGMENT 若并入 META_USER → 非消息文本被持久化/抽取（§4.2/§4.7）。
5. extractor 注入污染（§4.8）——设计推演发现的**真实安全缺陷**，T8 必须带上。
6. `websearch/tools.py:25` 是 untrusted 同族第二处，PRD 初稿漏了（§5）。

## 8. 与另一组票 #149–#160 的关系（冲突核查已完成，不必重做）

另一组票 #149–#160（memory/workspace phase，label 无 `phase-prompt-registry`）也由你实现，与本组票**已在文件级比对过，几乎零重叠**：

- 唯一可能同文件的点：`assembly.py`（#151 只引用 `:175` 作证据）与 `tooling/contract.py`（#159 只引用 `:94-108` 作参考）；`memory/extractor.py` #158 仅引用范例、不改。不同 hunk，合并无碍。
- ADR 编号无赛跑：#149–#160 更新已有的 ADR-0008，本组是 ADR-0023（已在 main）。
- 两组票都会追加 `docs/PHASE_STATUS.md`：条目里写清楚票号区间即可区分，合并时机械去重。
- 两组票的施工顺序由用户/协调方决定；若交错施工，每张票独立走完整 SDD 循环，互不阻塞。

## 9. 遇到不确定怎么办

- 票面之间或票面与 PRD §10 冲突 → **停下报告，不要自行裁决**（§9.1）。
- 发现规格外的 bug / 改进 → 只报告，不顺手修（§8 Scope Lock）。
- 交接方（前一会话）自本文档 commit 起不再产生任何提交，仓库归你独占。
