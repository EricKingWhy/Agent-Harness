# 集成提示词：自主 SDD 批次（#150 / #161–#168 / #149–#160）

> **写给集成 AI**。本文件按票累积追加，每票一节：改了什么 / 验证证据 / 集成注意。
> 分支：`feat/backend`（本 Agent 只做本地 commit，**不 push、不 merge**）。
> 权威进度账本：`docs/PHASE_STATUS.md`。执行协议锚点：`docs/AUTONOMOUS_SDD_PROGRESS.md`。

---

## 0. 批次状态（滚动更新）

| 票 | 状态 | commit |
| --- | --- | --- |
| #150 ARCH-7 单实例锁 | DONE | `9a45a20`（+ 流程锚点 `f3224d9`） |
| #161 PromptRegistry T1 | DONE | `36fd7ef` + `a51fde2` |
| #162 PromptRegistry T2 | DONE | `af6cf44` |
| #163 PromptRegistry T3 | DONE | `aa40fc3` |
| #164 PromptRegistry T4 | DONE | `2c77c3b` |
| #165–#168 | TODO | |
| #149 / #151–#160 | TODO | |

---

## 1. #150 ARCH-7 启动期单实例锁

**commit**：`9a45a20`（流程锚点文档 `f3224d9`）

### 改了什么

- 新增 `src/agent_harness/instance_lock.py`：`InstanceLock(root).acquire()/release()`，
  OS 级 advisory lock（POSIX `fcntl.flock(LOCK_EX|LOCK_NB)` / Windows
  `msvcrt.locking(LK_NBLCK)`），进程内幂等 + 引用计数 + 线程安全。
- 新增 `tests/test_instance_lock.py`（11 条，多数为真实子进程）。
- `src/agent_harness/web/app.py`：`create_app` 的 `lifespan` 取锁（**在
  `setup_logging` 之后**），外层 `finally` 在 `state.shutdown()` 与
  `flush_process_sink()` 之后释放。
- `src/agent_harness/cli.py`：`main()` 取锁后才 dispatch；`--help`/`-h` 豁免取锁
  但仍走 flush 契约；`InstanceLockError` → stderr + `SystemExit(2)`。
- 新增 `docs/AUTONOMOUS_SDD_PROGRESS.md`（流程锚点，非产品文档）。

### 行为变化（**会直接影响集成方的启动方式**）

1. **同一 `WORKSPACE_DIR` 同时只能跑一个进程**。CLI 与 Web 并发被**有意拒绝**
   （#150 AC5）——这不是 bug。集成时若同时开 dev server 和 CLI 命令（例如
   `agent-harness sessions`），第二条会以 rc=2 响亮失败。
2. `--help` / `-h` 不取锁（它不触碰该根）。
3. 逃生门 `ALLOW_SHARED_ROOT=1`：占用时降级为 WARNING 放行，且该 WARNING 会落进
   `${WORKSPACE_DIR}/../logs/agent.jsonl`。**默认关闭**。
4. 锁文件 `${WORKSPACE_DIR}/.instance.lock` 只用于诊断（写 pid / started_at）。
   进程被杀后文件会残留，**内容陈旧不影响取锁**（OS 已释放）。

### 验证证据

- 真实双进程：CLI 第二进程 rc=2，stderr 点名锁路径 + 占用者 pid；
  真实 `uvicorn` 第二实例 `Application startup failed. Exiting.`；
  `taskkill` 持有者后 2s 内新实例起得来（证明 OS 释放锁、残留文件无影响）；
  `ALLOW_SHARED_ROOT=1` rc=0 且 WARNING 出现在 `logs/agent.jsonl`。
- 门禁：ruff clean；全量 pytest `1655 passed / 10 skipped / 39 deselected / 0 failed`
  （含同批 T1 的 26 条）。
- code-review 两轴修复项已收口：注册表 key 改 `realpath+normcase`（避免 Windows
  大小写 / 8.3 短名导致同进程"自锁假阳性"）、线程安全、`--help` 豁免、
  移除死表面（`filename` 参数 / `path` 属性 / `_degraded`）。

### 集成注意

- **Windows mandatory 区间锁**：锁区间取在载荷之外的偏移（`1 << 20`）。若把它改回
  byte 0，锁文件里的 pid 诊断信息会连同进程一起读不出来（错误信息退化为"未知占用者"）。
- 若集成方在 `D:\intelligence-agent`（main worktree）同时跑后端测试与 dev server，
  注意两者共用 `.agent/workspace` 时会互斥；测试用 tmp workspace_dir 不受影响。

---

## 2. #161 PromptRegistry T1 注册表骨架

**commit**：`36fd7ef` + `a51fde2`（code-review 收口）

### 改了什么

新增 `src/agent_harness/prompt/` 包（**纯新增，未触碰任何现有生产路径**）：

| 文件 | 内容 |
| --- | --- |
| `errors.py` | `PromptError(message, *, code)`——形制照抄 `CapabilityError` |
| `template.py` | `_scan` / `render` / `extract_variables`——单趟扫描，不 `re.sub`、不重扫替换值 |
| `section.py` | `Target`（三值）/ `SECTION_ORDERS`（14 键）/ `PromptSection`（`requires` 为 property） |
| `registry.py` | `PromptRegistry`（register / variable / sections / available / declared_variables）+ `AssembledPrompt` |
| `__init__.py` | 按 PRD §10.2 导出，**暂不含 `DEFAULT_REGISTRY`**（T3 加） |

新增 `tests/prompt/`（27 条：模板器 13 + 注册表 14）。

### 关键约束（后续票必须守住）

- **`"*"` 只覆盖 `profile:<name>`**，不匹配 `aux:*` / `frame:*` / `runtime:*`
  （结构性前缀判定）。`test_sections_excludes_wildcard_for_aux_scope` 是那道闸。
- 模板器替换值**原样写入、不再扫描**——注入面从算法上堵死。
- 全部错误走单一 `PromptError` + `code`，测试按 `code` 断言。

### ⚠ 规格冲突（需集成方/T2 决策，本 Agent 未自行改 PRD/ADR）

PRD `docs/PRD_PROMPT_REGISTRY.md` **§10.7** 的 `AssembledPrompt` 代码块只有
`system_text` / `meta_user_text` 两字段；但 §10.4 明确写「`FRAGMENT` 的消费者用
`.fragment_text`（与 `.system_text` / `.meta_user_text` 并列）」，交接文档 §4.2 亦
为三段。T1 按**三段**实现（`system_text` / `meta_user_text` / `fragment_text`）。
**§10.7 视为过期待 T2 修正**——T2 实现 `assemble` 时必须产出 `fragment_text` 段
（否则 FRAGMENT section 无处落），并建议顺手把 §10.7 的代码块补齐。

另一处票面笔误（无需动作）：#161 AC 写「7 个文件按 §10.1/§10.2 创建」，其自身清单
为 8 个；已按清单创建 8 个。

### 验证证据

- `tests/prompt/` 27 passed；ruff clean；`git diff --check` clean。
- 全量 pytest `1655 passed / 10 skipped / 39 deselected / 0 failed`。
- code-review 两轴：Standards 零硬违规（§10.5 正则、§10.6 算法、§10.4 表逐项核对通过）、
  Spec 零缺项（12 条模板测试 + 13 条注册表测试逐条存在且断言符合票面）。
  收口两条 judgement call：scope 校验单点化、补孤立 `}}` 前置分支测试。

---

## 3. #162 PromptRegistry T2 组装与校验管线

**commit**：`af6cf44`

### 改了什么（仍为**纯新增**，未碰生产路径）

- `registry.py` 追加 `PromptRegistry.assemble(scope, variables)` 与模块级
  `run_self_check(registry, scopes)`；`__init__.py` 增加两者导出。
- 新增 `tests/prompt/test_assemble.py`（15）、`tests/prompt/test_self_check.py`（6）。

### 必须守住的语义

- **单 section 时产物 = 原文逐字节**（`"\n\n".join([x]) == x`）。T3 的「零行为变化」
  全靠这一条——迁移后的 prompt 文本必须与原内联字符串 `repr` 相等。
- 分隔符固定 `"\n\n"`；三个 `Target` **各自独立分区**，空段是 `""` 而非 `None`。
- **R4 不在 `assemble` 内重复实现**（`render` 已抛 `missing_variable`）。
- R5 只对 `profile:` 前缀 scope 要求 identity。
- `run_self_check` **不吞异常**（fail-fast 是它的全部意义），变量按 `requires`
  自动填空串——**不能改成传 `{}`**，否则 T4 的 `aux:fork_tail`（含 `{{tail_text}}`）
  会在 import 期误报 `missing_variable`。

### ⚠ 三条给 T3 的交接要点

1. **`builtin` 必须走 `registry.register(...)`**：§10.8 把"模板语法"列为自检职责，
   但实际由 `register`（R3a）承担——坏模板进不了 `_sections`，自检单独发现不了语法错误。
2. **T3 需自建 scope 集推导**（「注册表里所有非 `*` 的 scope」）。T2 的
   `run_self_check` 签名按票面冻结为接收 `scopes` 参数，未提供 `_declared_scopes`。
3. PRD 需随 T3 补齐两处：§10.7 的 `AssembledPrompt` 代码块（补 `fragment_text`）、
   §10.2 导出清单（补 `run_self_check`、`DEFAULT_REGISTRY`）。

### 两条票面测试因结构不可达而改形（**已报告，非偷工**）

1. `test_assemble_duplicate_identity_raises`：`_sections` 以 section 名为 key 且 R1
   拒重名 → 「两条同名 identity」构造不出来，`len(ids)` 只可能 0 或 1，R5 的 `!= 1`
   实际退化为 `== 0`。代码**保留 `!= 1`**（PRD §10.7 逐行照抄 + 防将来换分层注册时
   静默放行），改为新增 `test_duplicate_identity_section_cannot_be_registered`
   锁住该不可达性的**成因**（重名注册必抛 `duplicate_section`）。
2. `test_self_check_still_raises_on_bad_template_syntax`：语法错误在 register 期已拦，
   改名 `test_bad_template_rejected_at_registration`。**若谁把 register 的语法校验去掉，
   这两条会红**，提醒职责必须补回自检。

### 验证证据

- 真实 Python 会话跑通组装管线：单 section `repr` 等价 `True`、三段互不混装、
  空段 `== ""` 且 `is not None`、缺 identity 自检 fail-fast 抛 `missing_identity`、
  含变量 scope 自检不误报。
- `tests/prompt/` 48 passed；ruff clean；`git diff --check` clean。
- 全量 pytest `1676 passed / 10 skipped / 39 deselected / 0 failed`。

---

## 4. #163 PromptRegistry T3 三类 profile 迁移（逐字节相同）

**commit**：`aa40fc3`

### 改了什么

- **新建** `src/agent_harness/prompt/builtin.py`：三条 `profile:*:identity` section
  （文本与迁移前逐字节相同）、公开的 `build_registry()`、`_DECLARED_VARIABLES`、
  `_declared_scopes()`、`DEFAULT_REGISTRY`，以及 import 期的 `run_self_check`。
- `prompt/__init__.py`：导出 `DEFAULT_REGISTRY`。
- `agent/profiles.py`：**只在 `_builtin_prompt(name)` 一处接线**（ADR-0023 D12）。
  diff 仅 import + helper + 三处 `system_prompt=`，其余字段逐字未动。
- **`assembly.py` / `agent/factory.py` 零改动**；既有契约测试断言未改。
- 新增 `tests/prompt/test_profiles_migration.py`（9）、`test_builtin_registry.py`（8）。

### 为什么是单点接线（别在集成时"改回 PRD 字面"）

`agent/profiles.py` 一处接注册表后：parent 走 `assembly.py` 的
`profile_spec.system_prompt`、child 走 `factory.py` 的 `spec.system_prompt`，
两条路径**零改动**即一致，不存在两个调用点漂移的可能。若改成"在 factory 里按
`spec.name` 查注册表"，自定义 `AgentSpec`（B2 契约）与
`multiagent/provider.py` 传入的自定义 profiles 字典会被内置文案覆盖。

### ⚠ 给 T5 的关键约束（本 Agent 此前注释写错，已修正）

交接文档 **§4.4**：`DEFAULT_REGISTRY = build_registry()` **永不读环境变量**；
persona 由装配点 `build_registry(persona=…)` 注入。因此 `_builtin_prompt` 读
`DEFAULT_REGISTRY` 拿到的永远是**不含 persona 的 base 文本**——profile 的逐字节
断言在 T5 之后依然成立。**不要**把 persona 塞进 `DEFAULT_REGISTRY`：那会让
`profile:*:identity` 的等价断言在设了 `AGENT_PERSONA` 的机器上红。
`test_default_registry_equals_build_registry_in_p0` 就是这条不变量的机器化表达。

### 给 T4 的交接

- `_declared_scopes()` 自动覆盖 `aux:*`（不含 `*`），所以 T4 新增 aux section 后
  自检自动覆盖，**无需维护豁免名单**。
- 新 section 只要正文含 `{{var}}`，**必须**先登记进 `_DECLARED_VARIABLES`
  （先 `variable()` 后 `register()`），否则 import 期抛 `undefined_variable`。

### 验证证据

- **逐字节等价**：基线取自 `git show HEAD:src/agent_harness/agent/profiles.py`
  的 `ast` 抽取（**非手抄**），main(143) / coding(93) / research_review(87) 三条
  与注册表组装产物 `==` 为 True（`——`、全角 `（）`、拼接处空格全保留）；
  两轴 code-review 独立复算通过。
- **真实端到端**：装配真实 runtime → 跑真实 turn → 捕获**模型实际收到的
  SystemMessage** → 与注册表文本比对，三条 profile 全部 `True`。
- 三条冻结契约测试 16 passed 且未出现在 diff 中；ruff clean；`git diff --check` clean。
- 全量 pytest `1693 passed / 10 skipped / 39 deselected / 0 failed`。

---

## 5. #164 PromptRegistry T4 三条辅助 prompt 迁移

**commit**：`2c77c3b`

### 改了什么（三处调用点各只改 1 处）

| 现状 | 迁移后 |
| --- | --- |
| `context/compactor.py` 模块常量 `_SIX_SECTION_PROMPT`（**已删**） | `assemble("aux:compaction").system_text`（SYSTEM，**保留结尾 `\n`**） |
| `memory/extractor.py` 内联 SystemMessage 正文 | `assemble("aux:memory_extraction").system_text`（SYSTEM） |
| `session/fork.py` f-string | `assemble("aux:fork_tail", {"tail_text": …}).meta_user_text`（**META_USER**） |

`builtin.py` 追加 `_AUX_SECTIONS` 三条 + `_DECLARED_VARIABLES` 登记 `tail_text`。
新增 `tests/prompt/test_aux_prompts.py`（13）。

### 必须守住的三点（集成时别"顺手修"）

1. `aux:memory_extraction` 正文里的 `[{scope, content, importance}]` 是**单层花括号
   字面量**，不是模板变量。改成 `{{…}}` 会凭空引入一个无人赋值的必填变量 →
   **import 期就崩**。
2. `aux:compaction` 正文**结尾有一个 `\n`**（组装不做 strip）。删掉它，"逐字节相同"
   就是假的；`test_compaction_prompt_preserves_trailing_newline` 专门盯这个
   （T3 的 profile 正文首尾无空白，测不出这类 bug）。
3. `aux:fork_tail` 是 `META_USER`（现状是单条 `HumanMessage`）。target 的判据是
   **消息角色**，与"是否持久化"无关。

### 既有测试改动 3 条（票面只预告 1 条，另 2 条是同类强制改动）

全在 `tests/prompt/`，**均不在 PRD §10.9 保护清单内**；都是 T3 写下、pinned 到 P0
状态的断言，T4 后必然变化，且改后**更严格**：
`test_builtin_registry_has_three_profile_sections`（→ 按 `profile:` 前缀过滤，不再钉总数）、
`test_declared_variables_is_empty_in_p0`（→ 精确集合 `{tail_text}`）、
`test_declared_scopes_excludes_wildcard_and_covers_all_profiles`（→ 精确列表 6 项）。
三条保护清单测试**未出现在 diff 中**。

**⚠ 注意**：`test_builtin_registry_has_six_sections`（精确 6）是票面要求的，
后续每张票加 section 都会顶到它。若集成方觉得摩擦大，可放宽为按 scope 前缀分类计数
——但那是改票面要求，需你决定。

### AC 字面偏差（如实记录，未擅自"补齐"）

票面 AC 要求 `grep -rn "_SIX_SECTION_PROMPT" src/ tests/` 为空；实际返回 2 行
**注释**（`builtin.py` 与 `test_aux_prompts.py` 各一处，写明该文本迁移前的出处）。
**无任何代码残留或依赖**，故保留这两处 provenance 注释。若集成方坚持字面达标，
删掉这两行注释即可。

### 验证证据

- **逐字节等价**：三条 `LEGACY_*` 基线取自 `git show HEAD:<path>` 的 ast 抽取
  （非手抄、非反向拷贝）——compaction 263 字符且尾 `\n` 保留 / extraction 256 /
  fork head 93 + 变量；两轴 review 独立复算全部 PASS。
- **真实端到端**（真类 + 脚本化模型）：`TailSummarizer.summarize` 单条 HumanMessage
  等价；`MemoryExtractor.extract` SystemMessage 等价且花括号保留；
  `ContextCompactor.compact` **真实触发压缩**（`fallback_used=False`、产出摘要），
  发给模型的 system 指令等价且尾换行保留。
- `tests/prompt/` 77 passed；ruff clean；`git diff --check` clean。
- 全量 pytest `1706 passed / 10 skipped / 39 deselected / 0 failed`。

### 既有 flaky（与本批无关，别算到本批头上）

`tests/test_web_api.py::test_disconnect_leaves_run_running_and_cancel_stops_it`
被独立审查者在**同一份代码**上 5 跑 2 失败，clean HEAD 亦通过，且该文件不在本批
任何 diff 内。已按 §8 记入 `docs/FRONTEND_ISSUES_LOG.md` **OBS-9.3**，未顺手修。

---

## §6 T5 — #165 Persona 环境覆盖（commit `2638d68`）

### 做了什么

新增一层 **persona 覆盖**：`AGENT_PERSONA` 环境变量（JSON）可给 system prompt 加前缀/后缀，parent 与 child 一致。

| 文件 | 变化 |
| --- | --- |
| `src/agent_harness/prompt/persona.py` | **新增**：`PersonaConfig` / `parse_persona_config` / `persona_sections` / `apply_persona` |
| `src/agent_harness/prompt/builtin.py` | `build_registry(persona=None)` 注入 `persona:prefix`(0) / `persona:suffix`(10200) |
| `src/agent_harness/assembly.py` | 解析 env → registry 组装父 prompt → persona 透传 Factory |
| `src/agent_harness/agent/factory.py` | `create()` 用 `apply_persona(spec.system_prompt, persona)` 包裹 child prompt |
| `src/agent_harness/config.py` | 新增 `agent_persona: str = ""`（紧跟 `capabilities`） |
| `tests/prompt/test_persona.py`、`tests/test_assembly_persona.py` | **新增**：约 32 个用例 |

### 集成方【不要】做的事

1. **不要给 `DEFAULT_REGISTRY` 加 persona 读取**。它是**零配置基线**，永远不读环境。persona 只经 `build_registry(persona)` 这条显式路径进入。测试同时断言它「等于零配置构建」且「不等于 persona 构建」——两向都锁了。
2. **不要把 config 默认值从 `""` 改成 `None`**。`agent_persona` 与 `capabilities` 同形制（原始 `str`），`parse_persona_config("")` 即空 persona。
3. **不要用 `apply_persona` 去处理 aux prompt**。`"*"` scope 只匹配 `profile:<name>`，这是**结构性边界**（保护压缩/记忆提取等辅助调用不被 persona 污染）。若把 aux 也包上 persona，是在破坏规格而非修 bug。
4. **不要为了「统一」把 `apply_persona` 改名成 `compose_agent_prompt`**。交接文档 §4.5 的旧名与三参签名已过期；票面 prescribed `apply_persona(base, persona)`。
5. **T6 加 tool guidance 时不要改 `apply_persona`**。guidance 的 order(2000) 在 persona 后缀(10200) 之前，且 `apply_persona` 包裹的是**已组装完**的 profile 文本，顺序天然正确。

### 证据

- 门禁：`ruff` clean；全量 pytest **1739 passed / 10 skipped / 39 deselected / 0 failed**；`git diff --check` clean。
- 不动点：零配置产物逐字节等于 T3/T4 迁移后文本；K1/K2/K3 冻结契约与 profile 接线用例**零改动**通过。
- 真实验证：真实 `.env` → `Settings` → `assembly` 四场景（空/前缀/前后缀/坏键），坏键响亮失败不降级。

### 前向兼容注意

- `.env` 新增项 `AGENT_PERSONA`（默认空）——集成方需在真实 `.env` 里同步（若需要），空值零影响。
- 已知边界 OBS-9.6：`harness:identity`(order −1000) 若将来注册，会与 `persona:prefix`(0) 产生顺序歧义，届时漂移守卫会先变红，需先决策再注册。**当前无该 section，行为不受影响。**

---

## §7 T6 — #166 工具 guidance 归集（commit `ef64d44`）

### 做了什么

建立第三条 prompt 通道：**工具自带 guidance**，只在工具确实注册时才进 system prompt（ADR-0023 D11）。

| 文件 | 变化 |
| --- | --- |
| `src/agent_harness/tooling/contract.py` | `Tool` 加可选 property `prompt_guidance`（默认 `None`） |
| `src/agent_harness/prompt/tool_sections.py` | **新增**：`tool_guidance_sections` + `join_guidance` |
| `src/agent_harness/prompt/builtin.py` | `build_registry(persona=None, *, tool_sections=())` |
| `src/agent_harness/prompt/persona.py` | **新增** `compose_agent_prompt`；`apply_persona` 转薄封装 |
| `src/agent_harness/assembly.py` | 注入收窄后 registry 的 guidance；factory 传 `include_tool_guidance=True` |
| `src/agent_harness/agent/factory.py` | `include_tool_guidance`（默认 `False`），guidance 取 `child_registry` |
| `src/agent_harness/multiagent/tools.py` | `DelegateTool.prompt_guidance` |
| 3 个新测试文件 | 30 个用例 |

### 集成方【不要】做的事

1. **不要给 `include_tool_guidance` 改默认值为 `True`**。B2 契约（`tests/agent/test_system_prompt_wiring.py`）断言 `child.system_prompt == spec.system_prompt`；默认开启会让它变成"靠 `ReadTool` 恰好没有 guidance 才绿"。生产装配点已显式传 `True`，改动默认值只会破坏契约而不增加功能。
2. **不要让 child 的 guidance 改读 `source_registry`**。必须是 `child_registry`（已按 `spec.tool_scope` 收窄），否则 child 会看到它无权使用的工具的操作说明（越权信息泄漏）。
3. **不要给任何工具 guidance 写 `{{x}}`**。注册表的变量声明是模块级的（`_DECLARED_VARIABLES`），工具 guidance 无处声明变量，含 `{{x}}` 会在装配期抛 `undefined_variable`。需要动态内容就用 property 动态生成**整段**文本（`DelegateTool` 就是先例：f-string 注入 `_max_delegations`）。
4. **不要把 `prompt/tool_sections.py` 改成 import `agent_harness.tooling`**。它用 `Protocol` 结构类型接工具，是为保持 prompt 包无下游依赖（有测试 `test_tool_sections_does_not_import_tooling` 固定）。
5. **不要为了"省一次计算"给 `profile_spec is None` 分支加条件**。该分支也构建 `prompt_registry`（虽只用它的 `join_guidance` 那条），是工单骨架的刻意形状，开销可忽略。
6. **不要用 `join_guidance` 的返回值判空后再拼**。它无 guidance 时返回 `None`，这是刻意的——返回 `""` 会让 prompt 多出一个空段落，破坏逐字节断言。

### 证据

- 门禁：`ruff` clean；全量 pytest **1769 passed / 10 skipped / 39 deselected / 0 failed**；`git diff --check` clean。
- 冻结契约：`git diff HEAD -- tests/agent/test_system_prompt_wiring.py tests/test_assembly_agent_profile.py tests/context/test_builder_system_prompt.py` **输出为空**（断言逐字未改）。
- 真实验证：真实装配链 + 真实 `AgentRuntime` 跑真 turn（含真实 delegate 委派，3 次模型调用），父提示含「委派须知」且在身份文本之后，child（coding）不含，guidance 未进 tool schema。

### 前向兼容注意

- **无新 env / 配置项**：`include_tool_guidance` 是构造参数，装配点固定传 `True`；集成方无需改 `.env`。
- **待用户裁定的文本重复**（已上报 #166，**不是 bug，不要顺手删**）：`子代理看不到你们的对话历史` 出现在 4 处（`profile:main:identity`、`DelegateTool.prompt_guidance`、`_DelegateArgs.task` description、`DelegateTool.description`）。删除方案已列在 issue comment，动 profile 正文会连带改 T3 逐字节基线。
- T7（运行时上下文快照，order 9500）与 T8（纠偏/框架消息，order 9000~9200）都会往同一张 order 表加 section，**在 persona 后缀 10200 之前**，与本票的 2000 无冲突。

---

## §8 T7 — #167 运行时上下文快照（commit `1a4c41f`）

### 做了什么

把「当前工作目录 / 操作系统 / 日期 / 模型 / 可用工具」（PRD Q19=C）作为**非持久化** `meta_user` 段注入，位置在**当前用户消息之前**。

| 文件 | 变化 |
| --- | --- |
| `src/agent_harness/prompt/builtin.py` | 新增 section `runtime:context_snapshot`（META_USER / 9500 / 非 `*`）+ 五个变量声明 |
| `src/agent_harness/context/builder.py` | 新增 `runtime_context_provider`（默认 `None`）+ `_inject_runtime_context()` |
| `src/agent_harness/assembly.py` | 渲染闭包 `_render_runtime_context()` |
| 3 个新测试文件 | 30 个用例（含污染边界与防假绿对照） |

### 集成方【不要】做的事

1. **不要在 `_inject_runtime_context` 里加 `session.append`**（哪怕"顺手记一笔好排查"）。这一条会同时复活三个污染面：JSONL 永久滞留、`derive_messages` 每轮重放累积、`memory/extractor.py` 的 `has_user_message` 降级保护失效（注入内容可被洗成跨会话 USER 记忆）。这是本票唯一绝对不能犯的错。
2. **不要给 `memory/extractor.py` 加"过滤注入内容"的过滤器**。本设计用"快照不在 events 里"从根上避免；加过滤器是**错的**方向（那是 T8 针对既有 `injected_by` 事件的另一件事）。
3. **不要把快照改成 `SystemMessage` 或拼进 `system_prompt`**。前者会让易变日期毁掉 system-role 的 prefix cache；后者会破坏 T5/T6 与 C4/C5/C7 的逐字节契约。
4. **不要改 `ContextBuilder` 既有参数的名称与位置**。`runtime_context_provider` 是 `*` 之后的 keyword-only、默认 `None`；改成位置参数会影响大量既有构造点。
5. **不要把 `tools` 改成全量 registry**。快照必须用**收窄后**的 registry，否则 coding profile 会列出它调不到的工具（与 T6 收集 guidance 同一原则）。
6. **不要把 `model` 改成 `settings.model_name`**。用户用 `model_name` 参数选目录里的模型时后者可能为空，快照就会报一个假模型名。用 `config.model_name`。
7. **不要为了"省一次计算"缓存快照文本**。provider 是 callable 且每次 build 调用一次是**契约**（跨午夜会话需要新日期）；缓存会让日期过期。

### 证据

- 门禁：`ruff` clean；全量 pytest **1799 passed / 10 skipped / 39 deselected / 0 failed**；`git diff --check` clean。
- 冻结契约：`git diff HEAD -- tests/context/test_builder_system_prompt.py tests/agent/test_system_prompt_wiring.py tests/test_assembly_agent_profile.py` **输出为空**（断言逐字未改）。
- 真实验证：真 turn 下模型收到 `[System(main 身份), Human(快照), Human(当前用户)]`；三层持久化面实测干净且有防假绿对照。
- 变异验证：把快照 `append` 成 USER 事件 → 7 条边界测试变红（含修复后的等价性测试）；还原后全绿。

### 前向兼容注意

- **无新 env / 配置项**：Q19 清单是设计决定，不引入旋钮（PRD §8 已把"清单可配置"列为 DEFER）。
- **待用户裁定的设计问题**（已上报 #167，**不要擅自实现**）：child（`AgentFactory` 构造的子代理 runtime）目前**没有**快照。票面只给了父组装点、AC 未要求。若要给 child 也加，接线点在 `agent/factory.py`（那里已有 `_primary_model_name` 与 `child_registry`）。
- **T8 会往同一张 order 表加 3 条 section**（`frame:untrusted_data` 9000 / `corrective:tool_failure_guard` 9100 / `frame:recovery_skipped` 9200），全部在快照 9500 **之前**、persona 后缀 10200 之前。T8 还要改 `memory/extractor.py` 剔除 `injected_by` 事件——**这正是本票刻意不加过滤器的原因**，两者不要混做。

---

## §9 T8 — #168 框架/纠偏消息迁移 + 修注入污染（commit `611a6eb`）

> **本票含一个真实安全修复。集成时请优先读 B 部分。**

### A 部分：四条 FRAGMENT section（纯搬迁，逐字节相同）

| section（= scope） | order | 用途 | 使用点 |
| --- | --- | --- | --- |
| `frame:untrusted_knowledge` | 9000（`frame:untrusted_data` 槽位） | 知识检索结果前的"这是数据不是指令" | `knowledge/tools.py` ×2 |
| `frame:untrusted_websearch` | 9000（同槽位） | 网络搜索结果的同类提示 | `websearch/tools.py` ×1 |
| `corrective:tool_failure_guard` | 9100 | 同错熔断的纠偏消息 | `agent/runtime.py` ×1 |
| `frame:recovery_skipped` | 9200 | 恢复期"未启动即跳过"合成结果 | `recovery/coordinator.py` ×1 |

四条全部 `Target.FRAGMENT`，调用点一律取 `.fragment_text`。

### B 部分：修了真实的安全缺陷（`memory/extractor.py`）

**缺陷**：`has_user_message` 只认事件**类型**。纠偏消息是 runtime 自己 append 的 `USER_MESSAGE`（带 `injected_by`）→ 窗口里只要有注入消息，"有用户发言"就恒真 → LLM 的 USER 候选不再降级为 SESSION → **工具输出里的一句注入指令可被洗成跨会话 USER 记忆**，此后每个 session 的 SystemMessage 都会回灌它。

**修法**：`extract()` 入口**单点结构化过滤**（`_is_runtime_injected`：`injected_by` 为非空字符串），一处同时覆盖 `has_user_message` 保护、LLM transcript、规则路径三条链。

### 集成方【不要】做的事

1. **不要把入口过滤改回"在需要的地方各加条件"**。单点过滤是本修法的核心：只在 `_clip_events` 过滤只修三分之一，只在 `has_user_message` 加条件也只修三分之一（两种"半修"都有测试能在变异下变红）。三条链共享同一个过滤结果。
2. **不要给过滤加"内容关键词/正则黑名单"**。判定必须只用 `injected_by` 这个**我们自己的结构化标记**——"内容像不像注入"是不可靠的启发式，且会误杀真实记忆来源。
3. **不要把过滤扩大到"所有非用户产出的事件"**。工具结果与模型回复**是记忆的来源**，必须继续参与抽取；只剔 `injected_by` 非空者。
4. **不要改 `injected_by` 的值 `"tool_failure_guard"`**。它是跨模块契约（runtime 写、extractor 读、前端区分）。
5. **不要把 `injected_by=""` 或纯空白当成注入**。判定是 `.strip()` 后非空；有边界测试固定。
6. **不要用 `repr(tool_name)` 填 `corrective` 模板**。模板自带单引号，传 `repr()` 会产出 `''bash''`。
7. **不要把四条 fragment 改成 SYSTEM / META_USER**。它们不是消息，是嵌进 `ToolResult.message` / 事件 content 的文本；改成消息类 target 后调用点会拿到空串（组装分区互不混装）。
8. **不要把两条 untrusted 提示合并成一个 section**（同族但模块不同；合并会让"改网络搜索提示要动知识模块"）。

### 证据

- 门禁：`ruff` clean；全量 pytest **1827 passed / 10 skipped / 39 deselected / 0 failed**；`git diff --check` clean；既有 `tests/memory/` 断言零改动（`git diff HEAD` 为空）。
- 真实熔断：真 turn + 真实 `read` 工具同参连失败 3 次触发真实 SOFT 熔断，注入消息与**从 git HEAD 源码 AST 提取并渲染**的迁移前 f-string 逐字节相同（61 字符）。
- 真实抽取：注入指令未被洗成 USER 记忆（降级 SESSION + provenance）；反向对照（放回真实用户消息）USER 保持 USER。
- 真实恢复：skip 文案与 HEAD 渲染逐字节相同，`CANCELLED` / `retryable=False` 未变。
- AST 提取比对：knowledge / websearch 两条提示 == HEAD 源码常量。
- 变异：删入口过滤 → 7 条红；两种"半修" → 各 5 条红；"键存在即注入" → 4 条红。

### 前向兼容注意

- **无新 env / 配置项**。
- **两处 AC 字面偏差已上报 issue，等用户裁定**（集成时不要"顺手修"）：
  1. AC 要求 `grep -rn "_RESULT_DATA_UNTRUSTED_NOTE" src/ tests/` 无输出，实际 2 行命中，**均为 `prompt/builtin.py` 的 provenance 注释**（常量与使用确已删除）。
  2. 票面测试表一行自相矛盾（单条注入事件过滤后即空集），实现按实际语义拆成两条测试。
- **仅报告未改的潜在不一致**：`session.py:366` 的 `user_turn_count` 用真值判定 `not e.data.get("injected_by")`，本票 extractor 用 `.strip()`；对 `injected_by="  "` 语义不同（当前无产出点）。集成方若要统一，需另行批准。
- **#158（MEM-3 冲突消解 retrieve-before-write）现在可以开工**：它依赖 `memory/extractor.py`，而本票对该文件的改动已收口（改动面：新增 `_is_runtime_injected` + `extract()` 入口两处，其余零改动）。

---

## PromptRegistry 组完成（#161–#168）

| 票 | commit | 主题 |
| --- | --- | --- |
| #161 T1 | `36fd7ef` + `a51fde2` | 注册表骨架（section/template/registry/errors） |
| #162 T2 | `af6cf44` | assemble + R4/R5/R7 + 启动自检 |
| #163 T3 | `aa40fc3` | 三类 profile 迁移（逐字节） |
| #164 T4 | `2c77c3b` | 三条辅助 LLM prompt 迁移（逐字节） |
| #165 T5 | `2638d68` | Persona 环境覆盖（`AGENT_PERSONA`） |
| #166 T6 | `ef64d44` | 工具 guidance 归集（`Tool.prompt_guidance`） |
| #167 T7 | `1a4c41f` | 运行时上下文快照（meta_user，非持久化） |
| #168 T8 | `611a6eb` | 框架/纠偏消息迁移 + 修注入污染 |

全量门禁 1655 → **1827 passed**（+172 用例），全程 0 failed。8 张 issue 全部关闭。

### 组级集成注意（跨票）

- **`.env` 新增项仅 `AGENT_PERSONA`**（T5，默认空 = 零行为变化）。其余票无新配置。
- **注册表现状**：11 条 section（3 profile + 3 aux + 1 快照 + 4 框架/纠偏），8 个声明变量（`tail_text`/`cwd`/`os`/`date`/`model`/`tools`/`tool_name`/`consecutive_failures`）。
- **冻结契约**（全程断言未改）：`tests/agent/test_system_prompt_wiring.py` B1/B2、`tests/test_assembly_agent_profile.py` C1–C7、`tests/context/test_builder_system_prompt.py` G1–G4。
- **两条待用户裁定的设计/内容问题**（已在各票 issue 记录）：①T6 的 guidance 与 `profile:main:identity` 存在逐字重复；②T7 的 child（子代理 runtime）没有运行时快照。

---

## §10 ARCH-6 — #149 记忆 provider seam（commit `4a4372f`）

### 做了什么

让 `provider` 配置**名副其实**：新增 per-provider 分派表，`build_memory_components` 按 provider
分派，装配期白名单从分派表派生，未知 provider 装配期硬失败。并修掉一个 AC6 暴露的真实缺陷
（装配方伸手调 `components.relay.start()`，使不带 `.relay` 的 provider 静默降级成"没有记忆"）。

| 文件 | 改动 |
| --- | --- |
| `src/agent_harness/capability/factories.py` | `_MEMORY_PROVIDER_FACTORIES` 分派表、`memory_provider_names()`、`build_memory_components(settings, *, provider="builtin")`；原函数体整体改名 `build_builtin_memory_components`（**逐字节不变**）；`_DEPRECATED_MEMORY_PROVIDERS`；`MemoryComponents.initialize()` 现在负责 `relay.start()` |
| `src/agent_harness/capability/wiring.py` | `_KNOWN_PROVIDERS` → `_STATIC_KNOWN_PROVIDERS`（memory 移出）+ `_known_providers()`（memory 查分派表）；`_wire_memory` 传 `provider=cfg.provider` 且**不再**碰 `components.relay` |
| `docs/adr/0024-memory-provider-seam.md` | 新增 ADR：seam 选 A（整个 `MemoryComponents` 包）、命名收口、生命周期归 provider |
| `tests/capability/test_memory_provider_seam.py` | 新增 15 例 |
| `tests/capability/test_wiring.py`、`test_phase7_gate.py` | 三处 fake 摘掉 relay 脚手架 + 4 处 monkeypatch 适配新关键字参数 |

### 集成方【不要】做的事

- **不要**改 `_STATIC_KNOWN_PROVIDERS` 来加 memory 的 provider——memory 的白名单**派生**自
  `factories._MEMORY_PROVIDER_FACTORIES`；往静态表里塞 `"memory"` 只会被忽略（并可能误导下一个人）。
- **不要**把 `components.relay.start()` 之类的调用搬回 `_wire_memory`——契约是"装配方只调
  `initialize()` / `close()`"。这条现在有测试守着（`TestBuiltinProviderOwnLifecycle`）。
- **不要**为了让"AC 字面更漂亮"而删掉 `langmem` 别名：它是**已弃用但接受**的别名，删掉会把
  既有 `.env` 的升级变成装配期硬失败。

### 证据

- 门禁：ruff clean；全量 pytest **1842 passed / 10 skipped / 39 deselected / 0 failed**；
  `git diff --check` clean。
- 七组变异（各目标用例均变红、源码逐字节还原）：白名单硬编码化 / 装配层丢 `provider` /
  去 warning / 去未知 provider 硬失败 / `relay.start` 搬回装配方 / `builtin` 不启动 relay /
  close 顺序反转。
- 真机（真 `.env` + 真 Milvus + 真 embedding，走 `assemble_wiring`）：`builtin` 与 `langmem`
  注册成功且描述符 `provider_name` 分别为 `builtin`/`langmem`；`langmem` 实打弃用 warning；
  `mem0` 装配期 `CapabilityError(init_failed)` 且零网络请求；`enabled=false` 零注册。
  真 web app（uvicorn :8791）lifespan 启停干净。
- 双轴独立审查：Spec 轴 AC 1–6 **全部 met**；Standards 轴修后**零硬违规**。

### 前向兼容注意

- **新增 provider 的正确做法**：`_MEMORY_PROVIDER_FACTORIES` 加一行 + 写一个返回
  `MemoryComponents` 形态（含 `capability` / `writeback` / `initialize()` / `close()`）的 builder。
  装配侧零改动，白名单自动接受。
- **新错误码**：factory 层未知 provider 用 `init_failed`（复用 ADR-0010 Q3 冻结的四个码）；
  装配层先是白名单拦截（同样是 `init_failed`）。
- **`.env` 无新增项**；若集成方本地 `.env` 的 `CAPABILITIES` 写着 `"provider": "langmem"`，
  启动时会看到一条弃用 warning（预期行为，建议改为 `"builtin"`，两者行为完全相同）。
- **无行为变化**：`builtin`（含缺省）路径与原实现逐字节相同，relay 启动时机不变
  （仍在两个存储就绪之后），只是执行位置从装配方挪进 provider。

## §11 WS-1 — #151 会话归属锚：规范化 cwd 写进 `session/started`（commit `9144631`）

### 一句话

会话多了一个**不可变的会话侧工作目录锚**（`session/started` 的 `cwd` 字段，规范化绝对
路径），fork 与 SubAgent 子会话显式继承；从此"这个会话属于哪个项目"不必只信 sandbox
映射表。本票只做**写侧 + 派生侧**，没有新的 HTTP 契约、没有新配置项、没有事件模型重构。

### 新增 / 改动

| 位置 | 内容 |
| --- | --- |
| `src/agent_harness/sandbox/paths.py`（新） | `canonical_workspace_path()`——唯一一套规范化（`os.path.realpath` 语义） |
| `src/agent_harness/session/cwd.py`（新） | `cwd_event_data()`（写侧构造）/ `session_cwd()`（读侧派生） |
| `Session.start(..., cwd=)` | 由创建者赋予；`started_data` 夹带的 `cwd` 被丢弃并记 warning |
| `WorkspaceRegistry.create` | 落盘 `workspace_root` 前走同一个规范化函数（与事件侧同源） |
| `session/service.py`、`cli.py` | 把 `workspace` 作为 `cwd` 传给创建者 |
| `session/fork.py`、`multiagent/provider.py` | 子会话显式继承父的已存 header cwd |

### 集成方需要知道的行为

- **新增了一个事件字段**：`session/started.data.cwd`（字符串，绝对路径）。老会话没有该字段
  → 读出 `None`（= 未分组）。**这是加法式变更**，但如果有下游对 `session/started.data`
  做**严格 schema 校验 / 全字段断言**，需要放行这个新键；导出/回放的事件流里会多出它。
- **映射文件里的 `workspace_root` 现在是规范化的**（解析尾斜杠 / `..` / 链接）。
  若某处曾依赖"映射里的原始写法"，会看到盘上值变化——这是 AC5 的必然结果。
- **fork / SubAgent 子会话的映射与事件 cwd 故意不同**：事件里是**父的项目**（项目归属），
  映射里是 child 自己那份 copy-on-fork 目录（sandbox 物理隔离）。不要把两者相等当成不变量。
- **`.env` / 依赖 / 迁移**：零新增、零删除。空串 `cwd` 现在按"未分组"处理（不写字段）。

### 门禁与验收

- `ruff check` clean；`git diff --check` clean；全量 pytest **1871 passed / 10 skipped /
  39 deselected / 0 failed**；16 组单行变异全被杀（逐字节还原）。
- 真机（真 `.env` / 真模型 / 真 uvicorn :8792）：建会话后盘上 `started.data.cwd` 与映射
  `workspace_root` **逐字符相等**；真 fork 继承且 child sandbox 独立；真续聊后 started
  首行**逐字节未变**；真 delegate 子会话（`agent=coding`）cwd == 父 cwd。

### 交接给 #152（WS-2）的硬约束

1. 路径规范化**必须复用** `canonical_workspace_path`，不要另起 `Path.resolve()`。
2. 成员资格只能读**第一条 `session/started` 的 `cwd`**；**不得**信 sandbox 映射表
   （fork child 的映射是复制目录、SubAgent child 根本没有映射）。
3. 已存的 header cwd **照字面比较**，不要在成员校验时重新 realpath（目录被移动/链接被
   重指不应追溯改写归属）。
4. `session_cwd` 只做形状宽松判定（非字符串/空串 → `None`），绝对性校验由 #152 自己加。
5. 内部子会话（fork / SubAgent child）会因继承而落进父的项目分组 → #152 要明确
   **过滤还是纳入**（SubAgent child 没有用户可见身份）。
6. `attachSession` 必须用已存 header cwd 重新校验，绝不信任映射（`service.py` 已有注释）。

### 残留（范围外，仅报告）

- `AppState._wiring` 是进程级缓存，`InProcessSubagentProvider` 在多会话并发启动下会被
  反复 `activate()`——既有形状，非本票引入。


---

## §12 WS-2 — #152 Workspace 实体 + 有序账本 + 意图日志原子性 + 首次引导（commit `e3b81a6` + review 收口）

### 一句话

「项目 → 多会话」从**存储层能跑**升级为**可见、可枚举、可重建索引**：新增 Workspace 实体
（uuid id + 规范路径）与每个项目的有序会话账本（手工序、活动时间永不重排），用**意图日志**
保证 create/delete 两次写入之间崩溃可恢复，并在首次启动时**仅凭会话 header** 把历史会话按
目录归组。**没有新 HTTP 端点、没有新事件类型、没有新配置项、模型不可见。**

### 新增 / 改动

| 位置 | 内容 |
| --- | --- |
| `src/agent_harness/workspace/`（新包） | `WorkspaceIndex`（语义层）、`SqliteWorkspaceStore`（持久层）、`Workspace`/`StartedHeader`（模型） |
| `harness.db` 新 5 张表 | `workspaces` / `workspace_order` / `workspace_sessions` / `workspace_changes` / `workspace_meta` |
| `session/header.py`（新）、`session/store.py` | `StartedHeader` + `JsonlSessionStore.read_started_header()`（读到第一条 `session/started` 即停，**不读事件正文**） |
| `assembly.py` | `RecoveryStores.workspace_index`（**可选**）；`initialize_stores` 顺带完成首次引导 |
| `web/app.py`、`cli.py` | 各建一份 `WorkspaceIndex`（持有内存缓存） |
| `session/service.py` | 命名 workspace 的会话创建后 `create + attach`；`fork` 的 child 也 attach |
| `docs/adr/0025-workspace-entity-registry.md`（新，Accepted） | 授权模型 / 账本=索引 / 5 张表 / 意图日志 / 引导 / 命名 / 路径校验替换计划 |

### 集成方需要知道的行为

- **`POST /api/sessions` 的既有契约不变**：`workspace` 仍是**单段名字**（旧校验原样保留），
  只是创建后多了一步"注册进账本 + 前插会话"。任意路径的注册（`create(path)`）属于 #154 的
  `POST /api/projects`，本票只在领域层提供能力。
- **首次启动会写 `harness.db`**：第一次成功启动时执行一次性 bootstrap（读所有会话 header，
  按目录建项目、写账本、最后写 `bootstrap_done` 标记）。中断可安全续跑，之后只读标记。
- **未分组会话照旧存在**：无 cwd 的历史会话、未命名 workspace 的会话都不进任何项目。
- **两处显式 AC14 收窄（ADR-0025 D6，需集成方知悉）**：
  1. **默认每会话目录**（目录名 == 会话 id，即 `workspaces_root/<session_id>`）不归组；
  2. **内部子代理子会话**（`session/started.agent_id != "default"`，如 `coding`）不算项目
     成员，也不会让它所在的目录成为项目。判据只看 header 信封，不读正文。
  反向开关都是**一个具名谓词**（`_collect_header_groups` / `_filter_visible` 里各一处），
  产品若要"子代理会话也进项目列表"，删掉即可。
- **损坏时拒绝启动**：没有待定标记却出现"记录无顺序 / 顺序无记录 / 有账本无记录"→ 抛
  `WorkspaceRegistryCorrupt` 拒绝启动（AC13 有意为之，不静默修补）。若线上真撞上，需要人工
  检查 `harness.db` 的三张表，而不是让服务带病运行。
- **`.env` / 依赖**：零新增、零删除。

### 门禁与验收

- `ruff check` clean；`git diff --check` clean；全量 pytest **1932 passed / 10 skipped /
  39 deselected**（唯一 1 failed 是既有 flake，见下）。
- **27 组单行变异**（原 18 组 + 本轮 9 组：写锁 / 纯 INSERT / 孤立账本 / 未初始化闸 /
  header 降级 / touch 失败 / 子代会话排除×2）全部被目标用例杀死，源码逐字节还原。
- 真机（真 `.env` / 真 uvicorn）：bootstrap 对真实历史会话只建出既有项目、账本每条 header
  cwd 都等于项目 path、同名 workspace 复用同一项目、未命名不建项目、真 fork 加入父项目、
  软删除后目录与会话日志逐字节不变、重启不重复引导。
- **已知 flake（既有，非本票引入）**：`tests/test_web_api.py::test_disconnect_leaves_run_
  running_and_cancel_stops_it` —— SSE 断连被 `EventSourceResponse` 翻译成 producer 取消的
  时序竞争，5s 预算内偶发悬挂。实测：把本票新增的 index 初始化关掉后**仍会失败**
  （4/5 通过），本票新增的启动开销只有 **≈54ms**（冷启动 `initialize_stores`），
  与 5s 超时不在一个量级；随机器负载变化。**不属于 #152，也未在本票修改。**

### 交接给 #153（WS-3 列表契约）的硬约束

1. 有序读用 `WorkspaceIndex.list()[i].session_ids`（已按成员资格过滤 + 手工序），
   **不要**再按活动时间排序（AC4 会因此丢用户拖过的顺序）。
2. `workspace_of_session()` 是 O(项目数 × 账本长度)；N 条摘要请**先调一次 `list()`** 建
   `{session_id: workspace}` 映射，不要对每条摘要各调一次。
3. `RecoveryStores.workspace_index` 是**可选**的（CLI / 无 header 的装配为 `None`）→ 契约里
   `workspace` 必须是 `null` 而不是崩。
4. 读之前先 `ensure_stores()`：未初始化的 `WorkspaceIndex` 现在**响亮失败**（不是返回空）。
5. 成员资格只能走 index（header cwd），**不得**读 sandbox 的 `WorkspaceRegistry` 映射表。

### 交接给 #154（WS-4 项目 CRUD）的硬约束

1. 领域操作已齐备（`create/get/list/set_title/attach_session/detach_session/
   insert_session_before/delete/resolve_by_path`），需要把 `UnknownWorkspace` /
   `UnknownLedgerEntry` / `FileNotFoundError` / `NotADirectoryError` /
   `WorkspaceRegistryCorrupt` 映射进 `domain_errors.py`，否则会成为 500。
2. `attach_session()` 对"会话不存在/无 header/无 cwd"与"cwd 不匹配任何项目"都返回 `None`
   → AC7 要求前者**报错**，端点需要先校验再调用。
3. `_validate_workspace_name` 的替换：删 `web/app.py` 死副本 + 收窄 `service.py`，并把
   `create(path)` 暴露成端点。
4. **暴露 `POST /api/projects` 之前必须先解决来源可信性**（ADR-0025 D1 末尾）：当前默认
   部署是"未配置 `jwt_secret` 即本地信任 + CORS `*`"，等于把 agent API 开放给任意网页。
   要么鉴权、要么同源/CSRF、要么明确 localhost-only 部署约束。
5. `delete(id)` 是**软删除**：响应必须说明"会话没被删除、只是回到未分组"，并通过 #153 的
   契约让它们仍可见。

---

## 13. #153（WS-3）会话列表契约补 `workspace` + 按项目列会话

### 交付

| 文件 | 变化 |
| --- | --- |
| `session/store.py` | `WorkspaceRef(id, title)` 值对象；`SessionSummaryStats.workspace` |
| `session/service.py` | `list_sessions(*, workspace_id=None)`；项目视图走账本手工序；两处索引读 `anyio.to_thread.run_sync` |
| `session/errors.py` | `WorkspaceNotFound` |
| `web/app.py` | `SessionSummary.workspace`（**必填**，无默认值）；`GET /api/sessions?workspace_id=` |
| `web/domain_errors.py` | `WorkspaceNotFound → 404`；审计表补 `GET /api/sessions` 行 |
| `tests/web/test_session_list_workspace.py`（新，8 条） | 契约值 / 必填 / 404 / 序 / 空串边界 / 索引读不在事件循环 |
| 前端 `web/src/types.ts` | `WorkspaceRef` + `workspace: WorkspaceRef \| null`（非可选） |
| 前端 `web/src/lib/api.test.ts` | canonical fixture 用类型注解（删键 → `tsc` TS2741）+ 2 条运行时断言 |

`§12 交接给 #153 的 5 条硬约束全部落地`：账本手工序不重排 ✓、先一次 `list()` 建映射 ✓、
索引可选时 `null` 而非崩 ✓、读前 `ensure_stores()` ✓、成员资格只走 index（不读 sandbox 映射表）✓。

### 集成方需要知道的行为

- **`GET /api/sessions` 的响应多了一个必填字段**：`workspace: {id, title} | null`。对严格校验
  响应 schema 的客户端，这是**破坏性变更**（字段恒发送，变化的是"必填"语义）；本仓所有消费者
  （CLI / Web / 测试）已核对无破坏。
- **`?workspace_id=<未注册 id>` → 404**（不是空列表）。"项目存在但会话日志都没了"才是 `[]`。
- **默认列表顺序不变**（最近活动倒序）；项目视图是**账本手工序**，从不按活动时间重排。
- **索引不存在**（CLI 装配）→ 全部 `null`，不报错、不伪造。
- 这是**读出**能力，**不写任何 SessionEvent**（workspace 对模型不可见）。
- **`.env` / 依赖**：零新增、零删除。

### 门禁与验收

- `ruff check` clean；`git diff --check` clean；全量 pytest **1941 passed / 10 skipped /
  39 deselected / 0 failed**。
- **10 组单行变异**全部被目标用例杀死并逐字节还原（sha256）。其中"所有会话都报第一个项目的
  引用"首轮**存活**——暴露的正是项目视图用例的构造弱点（只有一个项目、没有未分组会话），
  加固后才被杀；如实记录，不粉饰。
- 真机（真 `.env` / 真 uvicorn / 真业务数据）：28 行全带 `workspace`；8 行归入 `ws1-e2e` /
  `ws2-e2e`；20 行为 `null` 且**仍在列表里**；项目视图顺序 == `workspace_sessions.position`；
  未注册 id / 空 `workspace_id=` → 404；OpenAPI `SessionSummary.required` 含 `workspace`。
- 前端门禁（该 revision 实测 sha256 `83156433e14b` / `f98fa7b312f8`）：`tsc -b` 0 错、
  vitest 521 passed、oxlint 0 error、playwright 130/130（`--workers=2`）、`vite build` ✓。

### 需要后续票知悉

1. **内部子代理子会话怎么显示**：#152 的 AC14 收窄②使 `agent_id != "default"` 的子会话不进
   项目账本，因此它在**项目视图里不出现**、却仍在**默认列表里以未分组出现**（真机已复现，
   该子会话 `agent_id == "coding"`）。**#155（前端分组 UI）需决定显示口径**。
2. **每次列表请求新增 O(账本) 次 header 读**：`WorkspaceIndex._read_header` 有意不缓存（AC6），
   默认列表路径因此每请求读一遍账本内候选的首行。已卸载到 worker 线程、不阻塞事件循环；
   若将来成为热点，正确方向是 index 内部缓存，**不是**放弃 AC6。
3. `AppState.ensure_stores()` 是列表读的**前置**（否则索引未初始化 → 每行都被判成未分组）。
   这是 load-bearing，不是防御性代码。

---

## 14. #154（WS-4）项目 CRUD API（软删除语义）

### 交付

| 文件 | 变化 |
| --- | --- |
| `session/projects.py`（新） | `ProjectService`：装配前置（`ensure_stores` + 索引存在性）、AC7 前置校验、把 workspace 词汇翻译成会话层词汇 |
| `web/projects.py`（新） | 9 条端点 + `require_trusted_origin` 来源闸 + 绝对路径校验 + Pydantic 契约模型 |
| `session/errors.py` | `WorkspaceMoveInvalid`（409）——无 cwd 锚 / cwd 不属于该项目 / 重排目标不在该项目账本 |
| `web/domain_errors.py` | 第二张表 `_WORKSPACE_ERROR_STATUS` + `workspace_http_error`（404 / 409 / 422 / 403），审计表 + 覆盖测试同步 |
| `web/app.py` | 注册项目 router（一行接入）；**删除**死副本 `_validate_workspace_name`（#152 交接项 3 的下半） |
| `workspace/index.py` | `attach_session`/`detach_session`/`insert_session_before` 的同步 header 读卸载到 worker（#153 review 同款标准）；写方法返回值改用**提交后**视图 |
| `tests/web/test_projects_api.py`（新，26 条） | AC1–AC7 + 来源闸（逐端点）+ 路径形态 + 幂等严格性 + 日志字节不变 |
| `tests/workspace/test_view_freshness.py`（新，1 条） | 写方法的返回值 == 随后 `get()`（`updated_at` 不陈旧） |
| `tests/web/test_domain_error_mapping.py` | 第二张表：覆盖 `WorkspaceError` 子类 + OS 错误 + 逐条状态码契约 |
| `docs/adr/0025-workspace-entity-registry.md` | D1 落实记录（(b) 来源闸 / 绝对路径 / loopback 前提 / 残留） |

### 端点集（9 条，全部过来源闸）

| 方法 + 路径 | 语义 |
| --- | --- |
| `POST /api/projects` | 注册**已存在**的目录（**绝对路径**）；同一规范路径幂等返回既有实体；不存在 → 404、不是目录 → 422、非法字符/超长 → 422、无权访问 → 403 |
| `GET /api/projects` | 全部项目，**注册表顺序**（新建前插） |
| `POST /api/projects/resolve` | 按路径解析，**不注册**；未注册 → 404 |
| `GET /api/projects/{id}` | 单个项目；未知 id → 404 |
| `PATCH /api/projects/{id}` | `setTitle`（空/纯空白标题 → 422） |
| `DELETE /api/projects/{id}` | **软删除**；响应含 `sessions_detached` 与明确文案"目录、用户文件与会话日志均未删除" |
| `POST /api/projects/{id}/sessions` | attach（AC7：会话须存在且 cwd 指向本项目；已是成员 → 直接返回，不重排） |
| `DELETE /api/projects/{id}/sessions/{sid}` | detach（幂等；URL 项目不是归属 → 无操作，不动别人账本） |
| `POST /api/projects/{id}/sessions/{sid}/order` | 账本内重排（`before=null` → 追加尾部；`before==sid` → no-op；跨项目 → 409） |

### 集成方需要知道的行为

- **来源闸覆盖读端点**：未配 `jwt_secret` 时，`Origin` hostname 不是 `localhost` /
  `127.0.0.1` / `::1` → **403**（读也 403——响应里是用户的绝对路径）。本机 Vite dev
  （5173）与同源部署照常；**无 `Origin`** 的 CLI/curl 照常。**部署前提：服务只绑 loopback**
  （对外暴露必须配 `jwt_secret`，那时闸自动让位给认证层）。
- **`create` 只收绝对路径**：`""` / 空白 / `.` / `..` / 相对写法 / NUL → 422。这是新增校验：
  放行的话 `realpath(".")` 会把"注册项目"变成"注册服务器碰巧启动的目录"。
- **软删除可逆**：删除后同一目录可重新注册（得到**新 id**），会话回到未分组且日志逐字节未变。
- **`create` 不回溯 attach**：注册一个目录**不会**把"cwd 已指向该目录"的历史会话自动接进项目
  （真机实测：注册后 `session_ids` 为空，需显式 attach）。首次启动的 bootstrap 扫描是唯一
  一次自动归组。**#155 若希望"注册后目录里的老会话自动出现"，需要在 UI 侧决定是否批量 attach。**
- **`POST /api/sessions` 的 `workspace` 名字语义不变**（单段名 → `workspaces_root/<name>`）；
  路径形态走 `/api/projects`。`web/app.py` 删掉的是**死副本**（活实现一直在 `SessionService`）。
- **`.env` / 依赖**：零新增、零删除。

### 门禁与验收

- `ruff check .` clean；`git diff --check` clean；全量 pytest **1972 passed / 10 skipped /
  39 deselected / 0 failed**。
- **25 组单行变异**：22 被杀、3 个预期存活（等价性已写进脚本与本节：服务层锚点校验与索引
  内部拒法同为 409；`UnknownWorkspace` 登记在当前路径不可达；rename 两层各自都能给 404）。
  另重跑 #152 的 18+11 组、#153 的 10 组，全部按预期处置（2 处 anchor 随本次 index 改动更新）。
- 真机（真 `.env` / 真 uvicorn :8792 / 真 `harness.db` / 真 JSONL / 真业务数据 28 会话）：
  注册/幂等/解析/404/422、跨源 403 与本机 200、attach（日志 sha 未变）、AC7 负例 409、
  detach（日志 sha 未变 + 列表变未分组 + 幂等）、reorder（真改序 + 追加复原到与原始序**完全一致**
  + 跨项目 409 且另一项目账本未动）、软删除（目录/文件/日志逐字节不变、会话仍可见且
  `workspace: null`、`GET` → 404、`workspaces`/`workspace_order`/`workspace_sessions`/
  `workspace_changes` 该 id 行数**全为 0**）。测试后已把运行时状态还原到测试前基线。
- **双轴 review 的收口**：Spec 轴 LOOKS-GOOD（6 条 P2）、Standards 轴 NEEDS-FIX（1 条 P1 +
  4 条 P2）。全部已修并复验，其中三条值得集成方知悉：
  1. **P1 路径必须是绝对路径**（Standards 实测 `{"path": "."}` → 200 且注册了进程 CWD、
     `{"path": ".."}` → 注册盘根）→ 新增 `_require_absolute_path`（含 NUL / 空白 / 相对写法）。
  2. **裸 `OSError` → 500**（`C:\bad<name>`、超长路径：`os.stat` 抛 EINVAL / ENAMETOOLONG）
     → 表里加 `OSError: 422`、`PermissionError: 403`，并把 `OSError` 加进 `_translated` 的捕获
     元组（只加表不加捕获是**到不了的**——首轮修复就踩了这个坑，靠变异 M18/M19 抓出来）。
  3. **`attach` 不是真幂等**（重复 attach 把用户拖过的位置重置到队首）+ **索引返回值
     `updated_at` 陈旧**（`_persist_ledger` 后仍用旧 `record` 建视图）→ 分别加真幂等短路与
     `get()` 重取；两条都补了判别性用例（后者暴露了"重 attach 队首会话"这种**弱构造**：
     前插队首本来就不改变顺序，变异存活后才改成重 attach 队尾）。

### 需要后续票知悉（范围外，未修）

1. **既有 CORS `*` 洞仍在**：`allow_origins=["*"]` + 未配 `jwt_secret` ⇒ 任意网页可调
   **既有**端点。review 独立实测：跨源 `POST /api/sessions`（带合法 body）→ **200 且起 run**。
   严重度高于本票，属既有问题（ADR-0025 D1 已记录），**应独立开票**（收紧 CORS 或默认 fail-closed）。
2. `WorkspaceRegistry.delete` / `LocalSubprocessSandbox.delete` 的 `shutil.rmtree(workspace_root)`
   在"任意已存在目录"模型下范围无界；本票的 `DELETE` 是**软删除**，**不碰**这条路径。
3. 盘根/家目录可以注册（AC2 字面允许的"任意已存在目录"）——沙箱根会随之变成整块盘；
   review 建议评估显式拒绝，本票**评估后保留**（是用户的显式动作 + 软删除不破坏数据），
   已写入 ADR D1 补充。

---

## 15. #155（WS-5）项目分组 UI —— 跨端票的**前端半**（代码 `f015a60` → review 修复 `8db0e5f`；文档 `c224724` + `637bc89`）

> **集成前请以最新 commit 为准**：`f015a60` 是初版；两轴 code-review 后有一轮修复
> **`8db0e5f`**（+ 前端文档 `637bc89`）。下面「review 修复」一节列出的都是**语义级**变化
> （mock 顺序、`workspace` 消费、422 detail、竞态守卫），集成时不要只看初版。

### 交付位置

**全部在 `D:\intelligence-agent-frontend`（feat/frontend）**：本票没有后端改动。
后端半是已交付的 #153（列表 `workspace` 契约）与 #154（项目 CRUD API），二者在
`feat/backend`，**尚未合入 main** —— 所以 `#155` 按 §14.12 **不关单**（跨端票只完成一端）。

| 文件 | 内容 |
| --- | --- |
| `web/src/types.ts` | `Project` / `ProjectStatus` / `ProjectDeleted`（与 `web/projects.py::Project` 逐字段对齐） |
| `web/src/lib/api.ts` | 7 个项目端点 + `ProjectError(status, message)` + `describeProjectError` + 窄化解析 |
| `web/src/lib/projects.ts`（新） | 纯函数：`buildRailModel`（分组投影）/ `moveAnchor` / `dropAnchor`（insertBefore 锚点） |
| `web/src/lib/projects.test.ts`（新） | 18 条：账本序 vs 活动序、孤儿行不丢、重复 id、锚点边界 |
| `web/src/hooks/useProjects.ts`（新） | 项目列表 + 8 动作；写后重拉（失败也重拉） |
| `web/src/components/SessionList.tsx` | 改版：项目块（折叠/行内重命名/菜单）+ 行（点选/菜单/拖拽）+ 未分组区 |
| `web/src/components/ProjectDialogs.tsx`（新） | 新建 / 删除确认（明示只解除分组）/ 加入项目 + 行内重命名 |
| `web/src/App.tsx` | 接线 + "会话列表刷新即重拉项目"（新会话/fork/recover 都可能顺带改归属） |
| `web/src/styles/app.css` | 纯新增 562 行（层级导轨 / 菜单 / 拖放落点 / 错误条 / 浮层） |
| `web/e2e/r-project-groups.spec.ts`（新） | 6 用例 × 2 视口（AC1–AC5 + 端点失败降级） |
| `web/e2e/fixtures.ts` | 项目端点的**有状态** mock |
| `web/e2e-live/project-groups-live.spec.ts`（新） | 无 mock 真机流程 + 基线逐字段比对 |

### 三条契约/语义决定（前端侧）

1. **不维护第二套成员名单**：分组只由 `GET /api/projects.session_ids`（账本手工序）派生；
   `GET /api/sessions.workspace` **不参与判定归属**，只用于解释孤儿行（自称属于某项目、
   但该项目不在当前列表里 → 该行落未分组并带 `staleProject` 注解）。**绝不因为分组丢掉
   任何一行**——未出现在账本里的会话（含子代理子会话）一律落到「未分组」区。
2. **内部子代理子会话**（#152 AC14 收窄②、第九轮登记待 #155 决策）**如实显示在未分组区**：
   后端给它的 `workspace` 就是 `null`（它确实不属于项目），前端不折叠、不隐藏、不从
   id/标题猜 `agent_id`。若将来要在视觉上区分，正确路径是**先加契约字段**
   （`SessionSummary.agent_id` / `parent_session_id`）再改 UI。
3. **注册项目不批量回溯 attach**：`attach` 校验「会话 cwd == 项目路径」，而
   `SessionSummary` 不暴露会话 cwd → 前端**无法判定**哪些未分组会话属于该目录，
   盲 attach 只会得到一堆 409。改为逐行「加入项目…」，后端 409 的 `detail` 原样显示。

### 门禁（末次实跑，最终 revision = `8db0e5f`）

`npx tsc -b` ✅ · `npx vitest run` **561 passed**（30 文件；本票 +41）·
`npx oxlint` **0 errors**（37 warnings 全为既有规则，本票 10 文件 0 warning）·
`npx playwright test --workers=2` **144 passed**（本票 +14）· `npx vite build` ✅ ·
`impeccable detect` 对改动文件 **0 findings**（`app.css` 的 4 条 `side-tab` 全在既有行号）。

### review 修复（commit `8db0e5f`；两轴独立只读 review 的发现，零 finding 后才收）

**两条会在真机/流式下真实发生的 P2**：

1. **e2e mock 的 attach 顺序与真实后端相反**——mock 推队尾，后端 `attach_session` 写的是
   `[session_id, *kept]`（**前插**；`tests/web/test_projects_api.py` 锁着）。也就是说那条
   AC4 用例在真机后端下**必然失败**。已把 mock（`unshift`）与断言（`['s3','s1','s2']`）改为前插。
   *教训*：hermetic e2e 的绿灯只证明"前端与假后端一致"；凡由后端定义的**顺序/归属/幂等**
   语义，mock 必须逐条对着后端源码与后端测试写。
2. **`App.tsx` 的 `onRetryProjects` 是内联箭头**→ `SessionList`（`memo`）props 每帧都变，
   流式 delta 期间整片 Session Rail 重渲染（本仓库对同名字段有明文规则）。已 `useCallback`。

**其余（P3，逐条已修）**：`SessionSummary.workspace` 由"只在注释里被消费"变成真的消费
（项目不在当前列表里时未分组行带 `staleProject` 注解，并把注释改写成真实分工：成员/顺序只认
账本）；**Pydantic 422 的 `detail` 是数组**，只认字符串会把「path must be an absolute path」
降级成「注册项目失败（422）」→ `readErrorDetail` 两种形状都认并剥掉 `Value error, ` 前缀，
输入补 `maxLength`（后端 200 / path 4096）；`useProjects` 补乱序响应 generation 守卫 +
in-flight 合并（写后 `refetch` 有意绕过合并）；拖拽落点只在来源项目内亮；Enter 提交补
`pending` 守卫；删掉 rail/选择列表上不成立的 `role=list`、折叠时的悬空 `aria-controls`、
`<p>` 里塞 `<ul>` 的非法 HTML；空项目提示删掉一条**不可达**引导；mock 的 order 端点补
自锚点 no-op（缺它会插错账本位置）；删掉不可达的 `/api/projects/resolve` mock 分支与
无人使用的 `onProjectPost`；AC3 断言改打在**后端原始串**（`WinError 3` + 路径）上以证明透传；
**新增 409 e2e**（`onAttachPost` 拦截口：cwd 不一致 → 后端原因就地显示、归属不变）；
`playwright.config.ts` 固定 `workers: 2`（§16.6）；`gui-test-screenshots/` 进 `.gitignore`。

### 真机验收（真 uvicorn 8000 + 真 `.env`/`harness.db` + 真浏览器 5173，无 mock）

注册临时目录 → 行内重命名 → 软删除（0 会话）；注册真实目录 `workspaces/ws-delete-me`
→ attach 真会话（cwd 相等放行）→ detach → 再 attach → **软删除（1 会话）**：会话回到
未分组、目录仍在盘上；真项目内重排（上移/下移，读 API 验证账本序变化与**精确还原**）；
结束时会话归属与项目账本与开测前**逐字段相等**（30 条会话）。截图
`web/gui-test-screenshots/ws5/`（本地留存、未入库）。

### 需要后续票知悉

1. **`POST /api/sessions` 仍只接受单段 workspace 名**（`SessionService._validate_workspace_name`
   拒绝绝对路径）→ 用户注册的任意目录项目**拿不到"新建会话"入口**（只有 fork 子会话能继承
   cwd 进入）。这是用户原始诉求（"一个项目下多个会话"）的**最后一块缺口**，需后端契约变更：
   让 create 接受绝对路径并把 cwd 定为该目录（写侧唯一规范化 `sandbox/paths.py:canonical_workspace_path`
   已存在）。**建议单独立票**。
2. **CORS `*`**（#154 集成提示词已登记的既有洞）在本票真机验收里再次可见：项目端点已过
   来源闸，会话端点没有。
3. 窄屏 56px 折叠轨看不见会话行（`.session-item-dot` / `.session-item-body` 的
   `display:none` 是既有规则，本票只把项目 chrome 追加进同一 hide 列表）。
4. `e2e-live/approval-live.spec.ts` 的「LIVE 拒绝」用例本轮连续失败（非门禁、结果非确定）：
   后端 `/approve` 返回 200 且决策落库、工具如实 failed，但 UI 卡片未在 10s 内翻到「已拒绝」；
   判断为真实模型在同一 run 内**再次请求审批**导致定位到新的 pending 卡片。与本票 diff 无关
   （未触碰 `ApprovalCard` / `postApproval` / 投影），门禁内 `n-approval-card.spec.ts` 全绿。

---

## 16. #156（MEM-1）记忆生命周期契约与机制 —— 纯后端，无前端改动

**提交**（均在本 worktree 的 `feat/backend`，未 push）：`61abcb6` 实现 → `aa775d8` review 一轮 →
`f70ebe7` review 二轮 → `fad0e3c` review 三轮。ADR：`docs/adr/0026-memory-lifecycle-hard-delete-outbox-operations.md`（新）。

### 16.1 集成分歧点：**本票会改已存在的 `memory.db` 磁盘 schema**

`memory_outbox` 从 `(memory_id, revision)` 升到 `(memory_id, revision, operation, tenant_id, user_id, scope, namespace)`。
升级发生在 `SqliteMemoryRecordStore.initialize()`（装配期，无需人工迁移脚本）：
逐列补缺（SQLite 的 DDL 不参与驱动事务，所以判据是"列缺不缺 + 路由列有没有空值"，**可重入**）、
从 `memory_records` 回填路由事实、**不可路由的孤儿行丢弃并带 id 告警**（老库里若留下这类行，日志里会看到
`Dropped N unroutable legacy memory outbox row(s)`——这是预期行为，不是错误）。
`operation` 的 CHECK 只在**本次补列**时装上（SQLite 不能给既有列追加约束）；无 CHECK 的老库靠代码自愈兜底。

**集成时若已有开发库**：直接启动即可（自动迁移）。若要复现"零迁移"路径，删掉本地 `memory.db` 让它重建。
**没有任何 workspace / SessionEvent 变更**（不变量 #16/#22：记忆是 Capability，不进会话真相）。

### 16.2 契约变化（都被契约测试与三个 fake 同步锁住）

- `MemoryCapability` 新增 `update(memory_id, scope, content, metadata) -> str`（**按 id 覆盖写 = upsert by id**：
  id 不存在即新建；"该不该更新、更新哪一条"是 #158 的策略，本层只给机制）与 `forget(memory_id) -> bool`（**硬删**：
  id 不存在 → 幂等 `False`；跨 namespace → `PermissionError`；SESSION 绑定不符 → `PermissionError`，无绑定 → `ValueError`，
  且**仅当这条记忆确实存在时**才做归属/绑定校验）。
- `MemoryRecordStore` 新增 `delete(memory_id, identity) -> bool`：同一 `BEGIN IMMEDIATE` 事务里"摘记录行 + 写一条删除意图"。
- `VectorIndexStore` 协议加 `delete` 与 `get`（`get` 是"无残留"的验收入口；`search` 只能证明检索不到）。
- **并发语义（写进 `record_store.py` 模块 docstring）**：内容在 namespace 内 last-write-wins；outbox 的 `revision` 是
  **索引同步的乐观令牌**（ack 只清它同步的那个 revision，陈旧 ack 吞不掉新版本）；**刻意不加** `updated_at`/`version`。
- **outbox = 每个 id 一行的"索引期望状态"**（不是事件日志）：要读待同步变更请用 `pending()`/`acknowledge()`，
  不要假设 outbox 里能重放历史。

### 16.3 验收证据（都在本 worktree 可复跑）

- **真机（真 Zilliz + 真 embedding + 真 count）22/22 全绿**：`.scratch/run_forget_gate.py`（一次性脚本，**不入库**）。
  要点：`forget` 前后**真实 count 1 → 0**、对照组恒 1（证明 filter 与清理范围正确）、`vectors.get` → `None`、
  重复 forget 幂等；**SESSION scope 单独一组**（另一条带 `session_id` 的路由）：跨 session 不可见、删除被
  `PermissionError` 拒绝且被拒的删除没改动任何东西。
  *踩坑记录*：真实向量检索返回 `limit` 个最近邻、**没有相似度下限**，"命中"只能按 id 成员断言。
- **integration 用例**（默认 deselected，`-m integration` 且 `.env` 指向 `memory_gate_test` 才跑）：
  `tests/integration/test_phase6_memory_e2e.py::test_real_forget_propagates_to_milvus_and_a_real_count_confirms_no_residue`
  （USER + SESSION 两段；判定残留用 `query(output_fields=["count(*)"])`，**不用** `get_collection_stats`）。
- **变异验证 15/15 KILLED**（`.scratch/mutate156.py`，逐字节 sha256 还原）：含"pending 退回 JOIN 驱动"、
  "delete 不记意图"、"ack 丢 revision"、"迁移哨兵回退"、"脏 operation 不自愈"、"自愈方向翻回删除"。
- **门禁**：`ruff check src/ tests/` clean；`tests/memory` 128 passed；全量 pytest **2003 passed / 1 failed**。
  那 1 failed 是**既有、与本票无关**的 `tests/test_web_api.py::test_disconnect_leaves_run_running_and_cancel_stops_it`
  ——已用 `git stash` 把本票全部改动拿掉、在**同一 commit** 上复现同样失败；根因是该用例 5s 预算覆盖了
  `/api/sessions` 的冷路径（真实 Milvus 冷 connect 实测 2.01s + langmem 冷 import 实测 1.32s + 其余装配），
  详见 `docs/FRONTEND_ISSUES_LOG.md` **OBS-10.1**。**集成方跑全量前请知道这一条**：它在本机是确定性失败，
  与本票 diff 无关；建议按 OBS-10.1 的方向（计时块外预热 / 密封 `CAPABILITIES`）另行处理，**不要放宽超时**。

### 16.4 本票**未做**（已按 §8 Scope Lock 报告，未顺手改）

1. LangMem 的 update/delete **仍未解禁**（`actions_permitted=("create",)` / `enable_deletes=False` 原样）——那是 #157。
2. 冲突消解策略（retrieve-before-write）——#158；模型工具与用户 API——#159；前端记忆 UI——#160。
3. `metadata`/`namespace` 列若被**带外**写坏，`json.loads` 会抛出 `pending()` 而被 relay 当"outbox 不可用"咽掉
   （outbox 保留、`indexed=FALSE`、向量未动 → **不是静默丢失**；需带外破坏 `NOT NULL` 列才触发）。可选加固，未改。
4. 既有 CORS `*` 洞（#154 已登记为独立票候选）、窄屏折叠轨、`POST /api/sessions` 单段 workspace 三块仍未动。

### 16.5 下一张

#157（MEM-2 解禁 LangMem 的 update/delete）——**前置已完成**：`LangMemMemoryCapability` 的 `update`/`forget` 现在直写权威记录，
#157 要做的是把上游 `manage_memory` 的 `actions_permitted`/`enable_deletes` 打开、经 `base_store_adapter` 把 `PutOp(value=None)` 映射到
`MemoryRecordStore.delete`，并保证"模型发起删除"仍走同一条 outbox/relay 路径（不得绕过）。

---

## 17. #157（MEM-2）解禁 LangMem 的 update/delete —— 纯后端，无前端改动

**提交**（均在本 worktree 的 `feat/backend`，未 push）：`ff57700` 接线 → `f3c80de` review 一轮 →
`faf525f` review 二轮 → `090f07c` review 三轮。ADR 改动：`docs/adr/0026-...md`（重新裁决 Consequences ①，并把"不解禁 LangMem update/delete"这条非目标标记为已由本票交付）。

### 17.1 集成分歧点：**不需要迁移、不动 schema、不动装配契约**

本票只改两个 `src` 文件、且都是**接线**，没有新表/新列/新 SessionEvent。集成时不需要任何手工步骤；
`#156` 的 outbox 磁盘 schema 迁移结论（§16.1）仍然适用，无新增。

- `src/agent_harness/memory/base_store_adapter.py`：`PutOp` 分支现在 **TTL 先拒**（含畸形组合
  `PutOp(ns, key, None, ttl=...)`）→ 再判 `value is None`（LangGraph 的 `adelete` 形状）→ 否则 upsert。
  **行为变化只有一处**：过去 `PutOp(value=None)` 抛 `NotImplementedError("Memory delete/TTL is not enabled")`，
  现在映射到 `MemoryRecordStore.delete`（真删除，走 #156 的 outbox DELETE 意图 → relay 收敛索引）。
- `src/agent_harness/memory/langmem_capability.py`：manager `enable_deletes=True`；manage 工具
  `actions_permitted=("create","update","delete")`；`search()` 容忍"索引里还挂着、记录行已删"的行（`except KeyError: continue`，
  与 adapter 的 SearchOp 分支同构）。
- **对 #156 既有语义零破坏**：`MemoryCapability.update`/`forget`（调用方指定 id 的确定性路径）仍是直写权威记录，
  不经 SDK；LangMem 的自主删除是**另一条**路径（模型决定改/删哪条 → manager → adapter）。

### 17.2 集成方需要知道的**实测语义**（避免写错断言）

`enable_inserts` / `enable_deletes` **改的是施加给模型的工具面（`bind_tools`），不是写路径上的强制**：
实测把 `enable_inserts=False` 时，一个"仍然发出插入工具调用"的模型照样会被 manager 校验并写入。
所以"关掉 insert 就等于不会新增记忆"**不是上游保证**，不要据此写测试或产品假设（本票的开关组合用例只断言
工具面差异 + 观察到的删除行为，见 `TestSwitchCombinations`）。

### 17.3 验收证据（都在本 worktree 可复跑）

- **真机 16/16**：`.scratch/run_langmem_actions_gate.py`（一次性脚本，**不入库**，真 Zilliz + 真 embedding +
  真 trustcall）。要点：脚本化模型发 `RemoveDoc` → 目标**真实 count 1→0**、对照恒 1、`vectors.get` → `None`、
  记录行消失；发 `PatchDoc` → 同 id 覆盖、`indexed` 重置、索引收敛到新内容且 count 仍为 1；
  **跨归属删除两种形状**（同租户另一个 user / 另一个 tenant）都被 `PermissionError` 拒绝且对方记录与索引原样在；
  manager 路径指名删别人的 doc id 也无效（trustcall 校验器只接受本次检索到的 id）。
- **真 Milvus 集成 5/5**：`tests/integration/test_phase6_memory_e2e.py`（`-m integration`）。新增
  `test_real_langmem_manager_delete_and_update_reach_milvus`；**注意该门禁 fixture 要求 `.env` 的
  `MILVUS_COLLECTION=memory_gate_test`**（专用集合，避免动生产集合）——本次验收是临时改 `.env` 一行、
  跑完按 sha256 原样还原。
- **变异 9/9 KILLED**：`.scratch/mutate157.py`（含 M4b 专门钉 TTL/删除的**分支顺序**；跑完 sha256 逐字节还原）。
- **门禁**：`ruff check` clean；`tests/memory` **146 passed**；全量 **2021 passed / 1 failed / 10 skipped /
  41 deselected**，唯一失败是既有负载相关 flaky `tests/test_web_api.py::test_disconnect_leaves_run_running_and_cancel_stops_it`
  （`docs/FRONTEND_ISSUES_LOG.md` OBS-10.1；同一代码连跑 pass/fail/pass、stash 后 pass，与本票无关）。

### 17.4 集成分歧点：**ADR-0026 的删除确认边界被重新裁决**

`#157` 之前 ADR-0026 写着"谁都不许在无确认路径上直接调 `forget`"。现在 writeback 内 LangMem 会**自主硬删**，
故把该条改判为一个**受控例外**：删除目标只可能是 manager 本次检索回来的 id、且必然落在调用者自己的 namespace 内
（两道边界都有真机证据），触发场景是非交互的后台整合路径。**面向用户的显式遗忘入口（#159 的模型工具 DANGER + 审批、
#160 的 UI 二次确认）仍然必须有确认**——集成方不要把这条例外读成"遗忘确认可以省"。

### 17.5 下一张

#159（MEM-4 遗忘入口：模型可调用的遗忘工具 DANGER + 审批 / 用户 API）。#157 已把"删除真的会到达索引"这条
机制验收完毕，#159 只做**入口与确认**；`#158`（retrieve-before-write 冲突消解）排在其后。

## 18. #159（MEM-4）遗忘入口（后端）—— 模型 `forget_memory`（DANGER + 审批）+ 用户遗忘 API

**提交**（均在本 worktree 的 `feat/backend`，未 push）：`af3db7a` 实现 → `19d51fc` 两轴 review 修复轮。
零前端改动（前端记忆管理 UI 是 #160）。新增文件：`memory/tools.py`、`memory/audit.py`、`memory/errors.py`、
`web/memory.py`。

### 18.1 集成分歧点：**不需要迁移**，但有三处契约面变化要知会

无新表/新列/无 SessionEvent（审计刻意走结构化日志）。不需要任何手工步骤。

1. **`MemoryCapability` 契约新增 `list_entries(scope, limit, offset)`**（读权威记录、不走 embedding）。
   三个测试替身（`fake_capability` / `test_memory_provider_seam._InMemoryCapability` / langmem 实现）
   都已实现，seam 测试已钉住——将来加 provider 必须一并实现。
   **命名不是风格问题**：**不能**叫 `list`（在 Protocol 类体里定义会遮蔽内建 `list`，同类体内后续的
   `list[MemoryEntry]` 注解在**类创建期**就 `TypeError`）。集成时若看到别名 `list`，那是错的。
2. **一处语义改判（#156 期行为 → 现在）**：`MemoryRecordStore.get`/`delete` 命中 **SESSION 行**、
   而当前上下文**没有可信会话绑定**时，`delete` 抛出的异常从 `ValueError` 变成 `PermissionError`
   （`row_namespace_matches` 把"这一行的 namespace 解析不出调用方有权操作的那一个"统一判为"不是你的记忆"）；
   `get` 是同一个判据但**口径不同**——读路径把"不是你的"伪装成 `KeyError`（不泄露存在性），
   这条现在也有用例钉住。另外 "缺会话绑定" 已**类型化**为 `SessionBindingMissing(ValueError)`
   （在 `memory/errors.py`，**刻意不是 `MemoryDomainError`**，所以不需要 HTTP 状态码；`of()` 抛它、
   `row_namespace_matches` 只捕获它，不再裸接 `ValueError`——将来 `of()` 里无关的 ValueError 不会被误吞）。
   两条 #156 期 store 层用例的期望随之更新并就地写明理由
   （`tests/memory/test_record_store.py::test_delete_rejects_a_session_bound_from_another_session`、
   `tests/memory/test_memory_lifecycle.py::test_delete_requires_the_bound_session_for_session_scope`）。
   **#156 的 AC2 未被削弱**（它只要求"按 namespace 校验归属、不得跨 tenant/user/scope 删"）；
   `store()` / `list_by_scope()` 在**调用方自己**缺绑定时**依旧** `ValueError`（有测试钉住），
   所以真正的上下文 bug 不会变安静。判据是 **行**的 scope 解析失败 ≠ **调用方**的 scope 解析失败。
3. **`CapabilityWiring.tool_contributors`（新字段）**：memory 的工具贡献走
   **`ContributesTools` 收集循环**的第二来源（描述符注册的仍是契约对象本身，`registry.get("memory")` 不变）。
   `wire_capabilities` 末尾只剩**一个**收集循环（已合并原先两个近似重复的循环）；没有任何地方直接往
   `wiring.tools` append——将来接新能力时保持这条。

### 18.2 集成方需要知道的行为口径

- **用户 API 只暴露 USER scope**：`POST`/`GET` 都不接受 namespace 参数（由身份解析）。
  因此两个"客户端可构造的输入"边界是**明确的 4xx**，集成时不要把它们当 500：
  身份缺 `user` scope → `GET /api/memories` **403**；HTTP 删一条 **SESSION** 记忆（HTTP 没有可信会话绑定）
  → **403** 且记录行完好。两者都由 `row_namespace_matches` 在领域层收口，模型工具侧对应
  `ErrorCode.PERMISSION_DENIED` 的**可读拒绝结果**（不是异常）。
- **删除语义 = 硬删**（继承 MEM-1）：删掉 → 200；未知 id → **404**；别人的 / 本入口删不了的 → **403**
  （**不伪装成 404**，与 MEM-1 的既定取舍一致）。领域层的 `forget` 仍是幂等 `False`（后台路径契约），
  404 是**入口层**对它的显式化。
- **审计**：`memory_forget` 结构化日志（入口 `tool`/`api` + `outcome` 三态 + 身份 + id，**不带记忆正文**），
  **不写 SessionEvent**（不变量 #16/#22）。`logging.EVENT_TYPES` 只新增了日志词汇，**会话事件词汇表未动**
  （有测试守卫：出现 `forget`/`delet`/`memory/update` 类会话事件会红）。

### 18.3 验收证据（都在本 worktree 可复跑）

- **门禁**：`ruff check` clean；全量 pytest **2058 passed / 2 skipped / 42 deselected / 0 failed**。
- **真机 19/19**：`.scratch/run_forget_entry_gate.py`（一次性脚本，**不入库**；真 uvicorn + 真 JWT +
  真 Zilliz + 真 embedding + **真实 count**）。要点：列表只含自己；越权删除 403 且对方真实 count 仍 1；
  **缺 `user` scope 的 GET/DELETE 都 403（非 500）**；**HTTP 删会话记忆 403 且记录行完好**；
  真删 200 且目标真实 count 收敛 0、检索不再命中；重复删除 404；无审批回调被拒且 count 不变；
  审批通过真的删掉。
- **真 Milvus 集成 6/6**：`tests/integration/test_phase6_memory_e2e.py`（`-m integration`；该门禁 fixture
  要求 `.env` 的 `MILVUS_COLLECTION=memory_gate_test`，本次是临时改一行、跑完按 sha256 原样还原）。
- **变异 20/20 KILLED**：`.scratch/mutate159.py`（跑完 sha256 逐字节还原）。M16–M18 钉第一轮修复
  （把"解析不出这一行"当匹配、去掉 GET 的 403 翻译、`public_metadata` 不剥内部载荷），
  M19/M20 钉第二轮的类型化异常两侧（捕获侧漏掉 `SessionBindingMissing` / 抛出侧退回裸 `ValueError`
  ——两条都会让"HTTP 删会话记忆"重新变成 500）。
- **两轴 review**：首轮两轴**各自独立复现同一个 major**（客户端输入冒 500），修复后见 18.1/18.2。

### 18.4 交接给 #160（前端记忆管理 UI）的契约面

- 路由挂载点：`web/app.py` 里 `register_memory_routes(app)`（与 `register_project_routes` 同形）；
  `CAPABILITIES` 无 memory 时两个端点都 **503**（配置状态，不是"资源不存在"）。
- `GET /api/memories?limit=&offset=` → `[{id, content, scope, metadata, created_at}]`；`limit` 1..200
  （默认 50），`offset ≥ 0`，越界 → **422**；倒序口径 = `created_at` 降序（tie-break 是 id，前端**不要**
  依赖同一时间戳内的顺序）。`metadata` 已剥掉 provider 内部载荷。
- `DELETE /api/memories/{id}` → 200 `{id, deleted: true}` / **404**（不在了）/ **403**（不是你的、或本入口删不了）
  / **503**（`CAPABILITIES` 里没有 memory）。
- 两条路由共用项目 API 的 `require_trusted_origin` 来源闸（未配 jwt 时拒绝跨源；配了 jwt 由认证层接管）。
- 二次确认是 UI 的义务（硬删不可逆）；后端不提供 `delete_all` / 软删 / 回收站 / 编辑入口（本票非目标）。

### 18.5 下一张

#158（MEM-3 冲突消解 retrieve-before-write）→ #160（前端记忆管理 UI，跨端票的前端半）。

## 19. #158（MEM-3）冲突消解 retrieve-before-write —— 纯后端，无前端改动

**提交**（均在本 worktree 的 `feat/backend`，未 push）：`b687804` 实现 → `5276777` 两轴 review 修复轮
→ `c6cbd12` 三轮收口（读不到就不许猜 + `query_model` 让 AC7-1 真机达成）。
新增文件：`src/agent_harness/memory/consolidation.py`、`tests/memory/test_consolidation.py`。

### 19.1 集成到 main 的注意点：**不需要迁移**，但有三处契约面变化

无新表 / 新列 / 新 SessionEvent（审计刻意走结构化日志）。不需要任何手工步骤。

1. **`MemoryCapability` 契约新增 `consolidate(scope, content, metadata, *, budget_seconds=None) -> MemoryWriteOutcome`**。
   这是**调用方的写入契约**；`store()` 保留但退为 provider 侧原语（文档已写明它**不带**不丢写保证）。
   实现者：`LangMemMemoryCapability`、`FakeMemoryCapability`；测试替身：`tests/capability/test_memory_provider_seam.py`
   的 `_InMemoryCapability`、`tests/memory/test_writeback.py` 的 `RecordingCapability`（都已补齐）。
   若你手上有别的 worktree 里的 `MemoryCapability` 实现/替身，需要加这个方法（没有它，writeback 会走
   `partial: N/M` 兜底而不是消解降级事件）。
2. **`store()` 新增可选 `budget_seconds`**（关键字参数，默认 `None`）：既有调用点零改动。
3. **生产装配真的把模型喂给了 memory capability**（`factories.build_builtin_memory_components`）。
   行为变化：从此每次记忆写入多一次**检索 + 一次 LLM 决策调用**（实测 2–19s/次，最长 30s 预算），
   并且该模型同时作为 **`query_model`** 传给 manager（AC1 的选项，见 §19.4）——每次写入再多一次
   生成检索 query 的 LLM 调用。这正是本票的目的（质量优先、接受成本），但意味着：**`.env` 的 MODEL
   配置现在也影响记忆写入延迟**；若集成环境模型很慢，写入会按预算降级成"只新增"（有
   `memory_consolidated` 日志与 `memory/degraded` 事件可查）。

### 19.2 票据归因的一处**修正**（请同步到 ADR/文档，已在两处加勘误）

票面（与 ADR-0026 Context ④、PHASE_STATUS 的 #156 条目）说"没传 `query_model`，所以 manager 的
Compare&Update 全程空转"。**前半句不成立**：`langmem/knowledge/extraction.py` 在 `query_model is None`
时走 `else` 分支，用 `get_dialated_windows(...)` 生成的 query 照样 `store.asearch`。真正的缺口是
生产装配**没给 capability 传 `model`**，于是 `store()` 里被 `if self._model is not None` 守卫的 manager
分支从未执行——**传 `model` 是"让决策跑起来"的修复**。

**但三轮 review 补上了后半句的实质**：不传 `query_model` 时，检索用的是"最近消息本身"当 query，
**语义对立的旧记忆召回不到**（真机 `retrieved=0`），AC7-1 的"新旧收敛"因此不成立；传 `query_model`
后按"假想记忆"检索才召回得到（真机 `retrieved≥1` → 最终只剩一条 Go）。所以两件事都要做：
①传 `model` 让决策跑起来；②传 `query_model` 让检索**有效**。不要只做一半。

### 19.3 关键设计（评审与后续改动请先读）

- **只有一条检索路径**：检索发生在 provider 的 manager 内部（`store=BoundedSearchStore`），Core 侧不做
  二次 `recall` 注入；`consolidate` 之后那次 `self.search` 只是 no-op 的复用查找，不喂给决策。
- **不丢写**：检索/决策失败（含超时、含 Milvus 不可用、含预算耗尽）→ 降级为一条无条件写入，
  原因脱敏（只含 `阶段:异常类型名`）。三种形态都有测试 + 真机 gate 覆盖。
- **有界注入（AC4）**：条数 + 每条 1000 字符都在我们的代理里执行（真机实测上游会给回超过条数上界的结果），
  超界丢弃/截断/修复都有计数。
- **截断投影回写的 P0 修复（重要）**：代理不只用于 prompt——manager 把同一批 item 当 patch 基线，
  所以 **任何** 写入经代理回写时都会做"投影 → 全文"还原（`aput`）。不变量：**截断标记永不出现在任何
  权威记录里**（真机 gate 用例 5 扫全部 sqlite 库，单测 `test_a_metadata_only_patch_never_persists_the_truncated_projection` 先红后绿）。
  已知限度：模型**重写**正文时以投影为基线，尾部无从还原（"注入有界"与"允许 provider 改写"共同决定）。
- **预算嵌套**：`CONSOLIDATION_TIMEOUT_SECONDS(30) + _FALLBACK_RESERVE_SECONDS(2) <= WRITEBACK_TIMEOUT_SECONDS(60)`，
  writeback 给每个候选的预算是"外层剩余 − 2s 余量"，所以尾部候选**降级**而不是被取消。改这三个常量请保持该顺序。
- **接线要一起改的三处**（少一处就有真实后果）：`model`（决策跑起来）、`query_model`（检索**有效**，
  否则召回不到语义对立的旧立场 → AC7-1 塌）、`enable_deletes=True`（provider 才能执行 RemoveDoc）。
  三者都由 `test_the_manager_is_wired_with_a_query_model_and_the_limits` 用构造缝钉住（变异 M32/M33）。
- **延迟信号**：真机 case 4（6 条 3000 字既有记忆）里那次决策**用满了 90s 的放宽预算**才降级
  （`retrieved=5 truncated=5`）——生产默认 30s，所以这种形状在生产里会降级成"只新增"（不丢写，AC5）。
  要更快只能调 provider 侧（模型/`max_steps`/检索条数），属性能话题。

### 19.4 AC7-1 / AC7-2 的口径（请按此写集成报告，不要放大）

**AC7-1（TypeScript → Go 最终只剩 Go）：真机达成**——前提是 manager 必须拿到 `query_model`。
不给它时上游用 `get_dialated_windows`（拿最近消息本身当 query），语义对立的旧记忆实测召回不到
（`retrieved=0`），于是新旧并存；给了它（AC1 明确列出的选项），上游改成"先生成一条与当前对话
相关的假想记忆再检索"，真机连续多轮都召回得到旧立场并收敛：

```
[PASS] 1c 检索到旧立场后，旧立场不独立成行 — retrieved=1 stale=[] total=1
       两次写入落到同一个 id（update 路径），最终只剩一条 Go
```

代价是每次写入多一次 LLM 调用（生成 query），用户已决策"质量优先、接受成本"。

**AC7-2（重复记忆不产生重复条目）：实测变好，但仍属 provider 的 LLM 判断，不是我们的确定性保证**：
- 传了 `query_model` 后真机实测"同一偏好写 3 次 → 1 条"（provider 看见了既有记忆并合并）。
- **不保证**：provider 每次改写正文并新建时仍可能是多条（早期轮次实测 3 条）。
  "不产生重复条目"最终取决于 provider 的决策，把它写成"我们保证去重"是过度承诺。
- **为什么不在 Core 加确定性去重**：AC6 明确"策略归 provider"；在 Core 加"包含即去重"会把
  "恰好是候选子串的不同事实"一起吞掉——那是丢写，比重复严重。若要更强去重，应作为 provider 侧
  策略（prompt/规则）另开票。

**AC1 的两处实现选择**（AC1 原文允许实现者选定并写进契约）：①builtin/langmem 路径选"传
`query_model` 让 manager 自己查"；②自研 provider 走 `capability.consolidate`（改写契约面，
见 §19.1 的三处契约变化）。

### 19.5 复现与验收证据（本地）

```bash
.venv/Scripts/python.exe -m ruff check src/ tests/          # clean
.venv/Scripts/python.exe -m pytest -q                       # 全量：2081 passed / 10 skipped / 42 deselected
.venv/Scripts/python.exe .scratch/run_consolidation_gate.py  # 真机：16/16 PASS（真模型 + 真 Zilliz）
.venv/Scripts/python.exe .scratch/mutate158.py               # 变异：33/33 KILLED（自动 sha256 还原）
```

**关于 skipped 数**：末次全量 10 skipped = 8 条 Docker daemon 不可用（`tests/sandbox/*`）+ 1 条 POSIX-only（`tests/tools/test_coding_tools.py:260`）+ 1 条最小 Core 口径（`tests/orchestration/test_seam.py:45`）；Docker 起着的机器上应为 2 skipped。与 #158 的改动无关。

**gate 的取样隔离（第二轮修正）**：脚本每轮用**独立集合名**（`memory_gate_test_<pid>`），
不再依赖"能删掉上一轮"——实测 Zilliz 的 `drop_collection` 会偶发 `Retry timeout: 20s`
（`create`/`list`/`describe` 正常），而残留向量会污染"provider 到底召回了什么"的判断。
收尾清理是**尽力而为**（删不掉只留个空集合，不影响断言）；裸 `memory_gate_test` 留给 pytest 的
真 Milvus 集成测试，脚本只扫 `memory_gate_test_<pid>` 形状的遗留集合。

`run_consolidation_gate.py` **不碰 `.env`、也不碰生产集合 `agent_memory`**（settings 里显式覆盖
collection）。`.scratch/` 不入库。

**gate 的读取口径（重要）**：外部 embedding/Zilliz 实测会间歇性不可用（本票期间断了多轮），脚本已
①bootstrap 重试；②外部依赖生病导致 happy path 降级时**作废该轮**（退出码 3）由 runner 换健康窗口重跑——
断言本身不软化，只是不在生病窗口下取样。用例 1c（"检索到旧立场才断言收敛"）在 provider 真的没召回旧行
时以 `[NOTE]` 呈现，**不硬判**：那是 provider 的检索/决策（AC6 策略归 provider）。用例 2a 只断言
**逐字**不重复——它弱于 AC7-2 原文，条数以测量值打印，不要在集成报告里把它当成"AC7-2 由我们保证"。

**AC3 的观测口径（别读错）**：`queries` 是 **`asearch` 次数**（provider 真的发了几次检索），
**不是** LLM 调用次数；`query_model` 那次"生成检索 query"的 LLM 调用发生在 langmem 内部，
我们的计数里没有它——只能从事件的 `latency_ms` 与"事件确实产生"侧面看出。要精确计 LLM 调用
需要另开票（langmem 不接受鸭子类型代理，`query_model` 必须是真 `BaseChatModel`）。
