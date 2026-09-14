# 交接单：/improve-codebase-architecture（参考扫描结果）+ 分支拓扑审计

> **给 Codex。你有两个任务。**
>
> **任务一（§B）是重点**：分支拓扑审计——用户用 6 个并行会话（3 后端 + 3 前端 +
> 1 merge）开发，自己控制分支集成，已经出现过平行实现撞车（B2 冲突）。需要你
> 全面审计当前分支状态，找出孤儿 commit、未集成工作、平行实现、失控的迹象。
>
> **任务二（§C）**：`/improve-codebase-architecture` 全仓扫描——下面是我做过的
> 一次扫描发现，作为参考输入，不是结论。请独立全仓扫描，交叉验证。

---

## §A 背景你先知道

用户的工作模式：

- **6 个并行 AI 会话**：3 个做后端、3 个做前端、1 个做 merge（Git Integrator）
- **每个会话在独立 worktree 工作**，分支各自分叉
- **用户自己做分支管理和 merge 决策**，有时候控制不好
- **已知后果**：B2（context_providers）有两个会话各写了一套独立实现，撞车了
  （ADR-0020b vs ADR-0021），最后靠集成 AI 裁决用混合方案解决
- **用户的痛点原话**："有时候我控制不好可能会导致分支混乱错误的问题，甚至有的
  计划有没有被执行我都不记得了"

已知 worktree 布局（截至最近一次确认，可能已变）：

| Worktree | 分支 | 用途 |
| --- | --- | --- |
| `D:\intelligence-agent` | `main` | 最终集成 |
| `D:\intelligence-agent-backend` | `feat/backend` | 后端开发 |
| `D:\intelligence-agent-frontend` | `feat/frontend` 或 `feat/frontend-context-providers` | 前端开发 |
| `D:\intelligence-agent-runtime` | `feat/runtime-context-providers` 等 | 后端 RUNTIME 子批次 |
| `D:\intelligence-agent-phase14` | `feat/phase14` | Phase 14 |
| `D:\intelligence-agent-phase15` | `feat/phase15` | Phase 15 |
| `D:\intelligence-agent-phase16` | `feat/phase16` | Phase 16 |

---

## §B 任务一（重点）：分支拓扑审计

### 要查什么

这是**只读审计任务**——不改任何分支、不 push、不 merge、不删任何东西。只产出报告。

#### B1. 全 worktree 盘点

```bash
git worktree list --porcelain
```

对每个 worktree，记录：
- 当前分支 + HEAD
- 工作区是否 dirty（有未提交改动）
- 相对 `origin/main` 领先/落后多少 commit

#### B2. 每个分支的集成状态

对每个本地分支（含已 merge 的历史分支），查：

- **是否已集成入 main**？（`git merge-base --is-ancestor <branch> main`）
- 如果没集成：**领先 main 多少 commit**？那些 commit 是什么？
- 如果已集成：**main 是否有分支没有的 commit**？（分支落后于 main，可能是集成后
  main 又推进了，分支该废弃了）
- **分支的 merge-base 是什么**？如果 merge-base 很深（很多 commit 前），说明分支
  长时间没和 main 同步，集成时冲突风险高

#### B3. 孤儿 commit / 孤儿分支

- 有没有分支上的 commit **既不在 main 里，也不在任何活跃分支的 tip 上**？
  （用 `git log --all --oneline` + `git log main --oneline` 对比）
- 有没有分支**已经废弃但没删**？（worktree 还在但分支已 merge 入 main 且落后很多）
- 有没有**同名测试文件在不同分支有不同实现**？（B2 冲突的征兆——
  `test_assembly_context_providers.py` 就是这样）

#### B4. 平行实现 / 重复劳动

这是最危险的失控信号。重点查：

- **同一个功能在多个分支各有一套实现**？怎么查：
  - 搜 ADR 文件：同一个主题有没有多个 ADR 编号？（比如 ADR-0020b 和 ADR-0021
    都是 context_providers runtime consumption——这就是平行实现）
  - 搜 commit message：同一个 ticket 号 / 功能名出现在多个分支？
  - 搜代码：同一个函数 / 类名在不同分支有不同实现？
- **已集成入 main 的功能，在其他分支又重新实现了一遍**？（分支分叉太早，
  不知道 main 已经有了）

#### B5. 计划执行状态核对

用户说"有的计划有没有被执行我都不记得了"。查：

- `docs/integration/` 下的所有交接单（`*_HANDOFF.md`、`*_PROMPT.md`）——
  每个交接单对应的分支/commit 是否已集成入 main？
- `docs/spec/14_IMPLEMENTATION_ROADMAP.md` 和 `docs/PHASE_STATUS.md`——
  各 Phase 的声称状态是否和实际 git 历史一致？
- 有没有交接单写了但**没人执行**？有没有**执行了但没写交接单**的 commit？

#### B6. 输出格式

产出一个 Markdown 报告（放 `docs/integration/BRANCH_TOPOLOGY_AUDIT.md`），结构：

```
## 全 worktree 状态表
（worktree | 分支 | HEAD | dirty? | 领先main | 落后main | 状态：活跃/待集成/可废弃）

## 待集成工作
（分支 | commit | 描述 | 风险评估）

## 孤儿 / 可废弃分支
（分支 | 最后活跃时间 | 建议：保留/删除）

## 平行实现 / 重复劳动
（主题 | 分支A 实现 | 分支B 实现 | main 上是哪个 | 建议）

## 计划执行核对
（交接单/Phase | 对应分支 | 已集成? | 差异说明）

## 风险与建议
（按严重程度排序的发现 + 建议）
```

### 审计纪律

- **纯只读**：不 checkout、不 merge、不 rebase、不 push、不删分支、不删 worktree
- **用 `git -C <worktree> <command>`** 操作其他 worktree，不在当前 worktree 里
  随意 checkout 别的分支
- **不确定就报告，不猜测**：比如某个分支"可能是废弃的"——报告你看到的证据，
  让用户决定是否删
- **§14.4**：任何写操作都需要用户明确批准，审计阶段零写操作（除了写报告文件）

---

## §C 任务二：/improve-codebase-architecture 全仓扫描

> 下面是 ZCode 做过的一次架构扫描发现，作为你的**参考输入**——不是结论，不是指令。
> 请独立执行完整的 `/improve-codebase-architecture` 全仓扫描流程，产出你自己的
> 可视化 HTML 报告和你自己的优先级判断。这份参考的唯一作用是交叉验证：
> 如果你扫到了我没扫到的东西，说明那是真信号；如果你扫到的东西和我的重叠，
> 说明高置信；如果你没扫到我列的某些项，按你自己的流程判断，不必迁就。

### 我做了什么

- 在 `D:\intelligence-agent-backend\src\agent_harness\` 核心模块做了文件级和
  函数级扫描（agent/ capability/ context/ session/ tooling/ web/ storage/ model/
  multiagent/）
- 用 "deep module" 词汇找问题：god method/module、shallow wrapper、leaky
  abstraction、duplicated logic、missing seam、untangled concerns
- 基线是 main `83056c8`

## 我扫到的 9 项（仅供参考，不要求采纳）

下面每项附了文件 + 行号，方便你定位时省点时间。但**行号可能在我扫描之后漂移**
——main 还在推进——请以你扫描时的实际代码为准。

### 1. `agent/runtime.py` 的 `_drive` 方法

- 行号：395–1026（方法体）；构造器 255–348
- 我的判断：疑似 god method，混了 streaming / fallback / tracing / checkpoint /
  memory writeback 多个职责；cancel 和 exception 两条终止臂可能重复
- 你来确认：是否真的该拆？拆成什么形状？是否有我看不到的理由它必须是一个函数？

### 2. `web/app.py` 整体

- 行号：全文 ~1269 行
- 我的判断：疑似 god module（AppState + schema + middleware + 15 路由全在
  `create_app` 闭包里）
- 你来确认：是否真的过宽？还是有意为之的单文件部署？

### 3. `session/service.py` 与 web 层的依赖方向

- 行号：44–46（import）、175–202（透传属性）、335（isinstance）
- 我的判断：域服务可能反向依赖了 web 层，边界可能是装饰性的
- 你来确认：这是有意架构妥协还是漏修？

### 4. 路径转义校验重复

- 位置：`web/app.py` 371–418 和 `session/service.py` 683–717
- 我的判断：同一个 PureWindowsPath 安全校验在两层各写了一遍
- 你来确认：是否真的重复？是否有微妙差异是有意的？

### 5. `web/app.py` 的 SSE 序列化

- 位置：`_event_to_sse_dict` 460–486、`_session_event_to_sse_dict` 489–514、
  内联 generator 1186–1189
- 我的判断：三个序列化路径形状可能不一致，疑似潜伏的契约 bug
- 你来确认：这是 bug 还是有意的设计？`/messages` 和 `/sessions` 的 SSE 帧形状
  是否真的不该统一？

### 6. `capability/wiring.py` 的 shim 和 `_wire_*` 重复

- 位置：340–368（三个 ContributesTools shim）、115–449（七个 `_wire_*`）
- 我的判断：三个 shim 逐字节相同；七个 `_wire_*` 结构雷同
- 你来确认：去重是否值得？还是显式重复有利于可读性？

### 7. `AgentRuntime` 构造器

- 位置：255–348，尤其 311–329
- 我的判断：同时接受 `context_builder` 和 `system_prompt` 两个入口说同一件事；
  构造后 mutate builder 内部 list
- 你来确认：双入口是否有历史原因不能删？

### 8. `multiagent/provider.py` 的 `collect_result_fields`

- 位置：58–132
- 我的判断：用字符串匹配 parse tool wire format，知道工具名集合、嵌套 JSON
  结构、中文标记词——疑似 leaky abstraction
- 你来确认：这是否真的该让工具自声明结构化 artifact？

### 9. `storage/sqlite.py`

- 位置：35–484
- 我的判断：三个不相关的 store（OperationLedger / CheckpointStore /
  SessionMetaStore）共享一个文件
- 你来确认：影响是否真的够大值得拆？还是低优先级不碰？

---

## 我没有扫到、你可能要留意的方向

我的扫描可能有盲区。以下是**我没深入看**的地方，你可以自己判断是否需要覆盖：

- `cli.py`（我只看了它对 event 渲染的支持，没做架构扫描）
- `tests/`（测试代码本身的架构通常不在 deepening 范围，但可能有测试可观察性
  的机会——比如某个模块测试特别难写，那本身就说明接口有问题）
- `model/` 目录下的 fallback / config / catalog 逻辑（我扫了 runtime 怎么用
  它们，没扫它们自身的模块形状）
- `observability/`（我只确认了 tracing 在 runtime 里散布，没扫 observability
  包自身是否该加深）
- 前端 `web/src/`（这是 TypeScript，不在本次 Python 扫描范围，但你如果想覆盖
  全栈可以考虑）

---

## §C 扫描对 Codex 的期望

1. **独立全仓扫描**——不要因为我在上面列了 9 项就跳过你自己的发现流程。你的
   扫描应该覆盖面不窄于我，优先级判断也不必和我一致。
2. **产出你自己的 HTML 报告**——`/improve-codebase-architecture` 的标准产物。
3. **和我交叉验证**——在你的报告里标注哪些和我重叠（高置信）、哪些是你独有的
   （新信号）、哪些是我列了但你认为不值得做（低优先级或误判）。
4. **不要迁就我的行号**——main 在推进，行号会漂移，以你扫描时的实际代码为准。

---

## §D 两个任务的优先级与产出

**建议先做 §B（分支拓扑审计），再做 §C（架构扫描）**。理由：如果分支状态失控，
架构扫描的基线可能本身就不可靠（比如你扫到的"问题"其实是某个分支的平行实现，
不是 main 的真实状态）。先确认分支拓扑干净，再在干净的基线上做架构扫描。

产出物：
- `docs/integration/BRANCH_TOPOLOGY_AUDIT.md`——§B 的审计报告
- `/improve-codebase-architecture` 的标准 HTML 报告——§C 的架构扫描报告

两个报告都要交给用户审阅，不要自行执行修复（审计和扫描都是只读任务）。

---

## §E 项目约束提醒（两个任务通用）

- AGENTS.md §8 Scope Lock：每个 deepening 是独立 ticket，不顺手重构无关代码
- AGENTS.md §9.2 Simplicity First：最小改动，不为通用堆无用抽象
- AGENTS.md §9.3 Surgical Changes：只动必须动的，匹配现有风格
- AGENTS.md §14.4：任何写操作（merge / push / rebase / reset / branch 删除 /
  worktree 删除）都需要用户明确批准
- 不变量 #1–22（AGENTS.md §7）：任何重构不能破坏架构不变量
- 工作目录：`D:\intelligence-agent-backend`（feat/backend）；审计其他 worktree
  时用 `git -C <path>` 只读访问，不在那里随意 checkout
- 零密钥泄露（.env 内容绝不打印/提交/复制进文档）
