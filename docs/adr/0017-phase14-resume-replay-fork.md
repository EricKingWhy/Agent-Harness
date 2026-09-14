# ADR-0017: Phase 14 Resume / Replay / Fork 完整化

- 状态：Accepted
- 日期：2026-09-06
- 关联：spec 03_SESSION_EVENT_MODEL §6-§8 §10 / 14_IMPLEMENTATION_ROADMAP Phase 14 / ADR-0004（storage 分层）/ ADR-0015（Multi-Agent——delegation 边是 lineage 的一类）/ 不变量 #3 #4 #5 #6 #22
- 上游调研：pi（钦定：sessions / session-format）/ Claude Code（checkpointing）/ LangGraph（time-travel）/ oh-my-pi（checkpoint / rewind）——底稿 `.scratch/phase14-research.md`（grill 时随 ADR 入库为 docs/PHASE14_RESEARCH.md）
- 协作注记：本 ADR 产自独立 worktree `D:\intelligence-agent-phase14`（feat/phase14）——`feat/backend` 同时由后端 B AI 做流式 UI 改造（其 ADR 取 **0016**，本文件取 0017，避免双编号）。共享文件纪律：`session/event.py` 两侧纯加法；本阶段 Web 端点进独立 router 文件、票序最后；`runtime.py` 归流式改造，本阶段零触碰。

## 背景

Phase 13 交付了 spawn 型 child（全新上下文）与 delegation lineage 边（child_session_id 事件）。规格 §6/§7/§8 冻结了 Replay（逻辑回放、tool result 冻结）/ Fork（新 lineage、父子独立、UI 树）/ Compaction 交互（fork 到 compaction 前仍可解释）的语义，roadmap Phase 14 要求六件套：replay projector / fork boundary / lineage tree / child session seed / UI+CLI commands / artifact-workspace fork policy。事件词表中 `session/forked` 已列名未实装。

## 决策（grill 两轮逐项拍板，用户确认）

### 形态与边界（Round 1）

1. **file-per-lineage（守宪法）**：fork = 新 session 文件。每个 session 的 JSONL 保持 append-only **线性**；树是文件之上的**元数据关系**，不进事件文件。pi 的 tree-in-file（单文件 id/parentId + active leaf）被否——它要改掉 Session 线性 append-only 不变量与全部既有恢复链；pi 式「原地探索」的 UX 用 lineage 视图近似。父文件 fork 后一字不改（§7 字面）。
2. **fork boundary = run 完整边界，UX 按用户消息表达**：机制上前缀 MUST 止于 run/completed 或 run/failed 之后（否则 child 文件以悬空 run 开头，破坏 session 不变量）；选择器 = 「从第 N 条用户消息分叉」（与 pi `/fork`、Claude `/branch` 一致），两条用户消息之间天然是 run 完整点，机制与 UX 互咬。
3. **seed = 事件前缀逐字复制**：child 文件自包含（§10「Fork 后父子 Session 独立」的直接推论——不依赖父文件存活）。前缀事件重编 seq（child 局部单调不变量），**保留原 event_id 与全部数据**（tool_call 配对、时间线可追溯）；复制原始事件天然满足 §8「fork 到 compaction 之前仍可解释」（pre-compaction 原文随前缀带走）。parent identity + fork point 仅作 provenance，不参与 child 的上下文推导。
4. **replay V1 = CLI 命令 + 冻结契约，重新执行式 DEFER**：`replay <session>` 终端只读重放（复用 StreamRenderer 语义，tool result 渲染冻结终态）；「逻辑回放冻结副作用」写成显式契约 + 测试。LangGraph 式真重跑（LLM/API 副作用真实发生）= 规格 §6 要求显式授权的「重新执行式」，本期 DEFER（需求未出现，复杂度跳级）；步进式 TUI 同 DEFER。Web inspector（Phase 9/10）已是逻辑回放的可视面，本阶段只补 lineage 维度。
5. **sandbox fork = copy-on-fork**：fork 时父 workspace 整目录复制为 child 的（fork 点世界快照，child 随意改不伤父）；物理策略独立于事件 fork（§7 字面）。Artifact 不复制——全局 store 内容寻址 ref 直接复用（规格「Artifact Ref 按权限复用」）。
6. **V1 命令面**：CLI `fork`（从第 N 条用户消息开新会话）/ `replay`（决策 4）/ `sessions --tree`（lineage 树列表）；Web = 只读 lineage 视图（inspector 显示 fork/delegation 树、节点跳转），**Web 端点进独立 router 文件**（`web/lineage.py`）并票序排最后——`web/app.py` 由流式改造（ADR-0016）重刀，避免碰撞。Web 发起 fork（创建端点 + 按钮）DEFER。

### 元数据与事件（Round 2）

7. **lineage 双层：事件 = 真相，SessionMetaStore = 索引**：`SessionMeta` 扩列 `parent_session_id` / `origin`（`fork` | `delegation`）| `fork_point_seq`。建树查索引（O(1) 组装），事件流保留完整事实（可审计、可重建索引）。**fork 与 delegation 两类边统一建模**（`origin` 区分），一棵树两个来源；delegation child 的 meta 行在会话创建时写入，**存量 Phase 13 child 查询时惰性回填**。纯事件推导（全库扫描建树）与只索引不落事件（丢审计链）两个极端均被否。
8. **`session/forked` 事件形状**：只落 **child 文件**（父不改），位置在 seed 前缀之后、child 第一条活事件之前；data = `{parent_session_id, fork_point_seq, boundary_user_message_seq?, tail_summary?}`。全部字段可从既有事实导出；workspace 路径等物理细节不进事件词表（决策 5 的物理策略是运行期事）。
9. **Tail Summary（fork 摘要挂接，对齐 pi branch_summary / oh-my-pi rewind-report 精神）**：fork 时对父会话 fork point 之后的 tail 生成**一次 LLM 摘要**，经 `session/forked` 的可选 `tail_summary` 字段落 child（零新事件类型）。语义：「被放弃的那条线得出了什么」——file-per-lineage 下 child 自包含前缀，tail 只存在于父文件，摘要是唯一的信息桥。默认开启、`--no-summary` 可关；**生成失败 = 降级不挂接照常 fork**（optional 能力不拖垮 core，不变量 #21）；摘要文本绝不清算成用户发言（injected 语义，与 Phase 12 纠正消息的 injected_by 纪律同源）。
10. **fork 是用户 CLI 动作**：不是模型可见工具（对照 ADR-0015 决策 10：create_agent 不是 LLM 可见工具的同一逻辑——fork = 权限/上下文的复制面，暴露给模型 = 提升通道）。无审批面（读父 + 复制，无危险副作用）。

### 明确不做（DEFER）

- 重新执行式 replay（规格允许的显式授权模式）——需求出现再立项
- 步进式 TUI replay
- Web 端发起 fork（创建端点 + boundary 选择器 UI）
- tree-in-file / 原地多分支导航（pi `/tree`）——file-per-lineage 下由「多会话 + lineage 视图」承担
- lineage 跨工作区/全局森林视图（V1 树的根 = 每个 root session）

## 后果

- Session 线性 append-only 不变量、既有恢复链、前端投影零破坏；树成本全部收在 SessionMetaStore（SQLite 索引，ADR-0004 既有分层）。
- `session/forked` 进 EVENT_TYPES；`SessionMeta` schema 扩列（SQLite migration，向后兼容：NULL = root）。
- child 文件自包含带来存储重复（前缀复制）——以「独立可读 + 实现简单」换空间，workspace 本地文本量级可接受；如未来成为问题，lazy-seed（引用式）作为演进位。
- 与流式改造（ADR-0016）的合并顺序：本阶段先行文件（session/event.py、session_meta、cli、新 workspace fork 模块）与流式改造交集极小；Web 端点独立文件避免 app.py 冲突。§14.9 集成一次一支：流式改造（已在跑）先，Phase 14 后。
