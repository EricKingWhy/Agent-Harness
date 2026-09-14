# 自主 SDD 执行：常驻指令与进度（防指令漂移）

> **本文件是 Agent 的锚点。每完成一张票、每次上下文被摘要后，先读本文件 §1 与 §3。**
> 用户 2026-09-12 授权：全自动执行，不询问、不确认、不做完一张就停，直至全部票完成。

## 1. 常驻指令（原文约束，不许忘）

1. 逐票执行 `/implement` → `/code-review`（发现问题直接修）→ 难解 bug 用 `diagnosing-bugs` 诊断修复后重跑 `/code-review` → 零 finding 才开下一张。
2. **不许做完一张票就停下来**。必须直到全部票处理完才能停。
3. 前端相关工作使用 `impeccable` skill。
4. **真实测试**：不能只用测试代码，要真跑功能，看有没有反应、是不是预期效果。需要浏览器就用（内置浏览器 / MCP）。每个功能都要过一遍。
5. 遇到任何问题**实时写入** `docs/FRONTEND_ISSUES_LOG.md`，标注前端 / 后端归属，修 bug 时照此文档。
6. 最多允许 3 个 subagent 并行。
7. 工作协议仍是 AGENTS.md §16.1 + §14：**只 commit，不 push、不 merge main、不建 PR**。
8. 零凭证泄露：`.env` 值绝不进入任何输出 / commit，日志与文档一律脱敏。

## 2. 交付范围（20 张票，全部归本 Agent）

### A. PromptRegistry 组（label `phase-prompt-registry`，#161–#168）

硬链：**#161 → #162 → #163**，之后 **#164 → #165 → #166 → #167 → #168**，**T8 必须最后**。
可执行规格 = GitHub 票面；契约终稿 = `docs/PRD_PROMPT_REGISTRY.md` §10；决策 = `docs/adr/0023-prompt-registry.md`。
红线见 `docs/HANDOFF_PROMPT_REGISTRY.md` §4（`*` 只匹配 `profile:*`、Target 三值、T3 单点接线 `agent/profiles.py`、DEFAULT_REGISTRY 不读环境、FRAGMENT 不得并入 META_USER、冻结测试断言不许改、T3/T4/T8 逐字节等价）。

### B. Memory / Workspace 组（#149–#160）

| 票 | 标题 | 依赖 |
| --- | --- | --- |
| #150 | ARCH-7 启动期单实例锁 | 独立 |
| #149 | ARCH-6 记忆 provider seam 分派 + ADR | 独立 |
| #151 | WS-1 规范化 cwd 写进 `session/started` | #152 前置 |
| #152 | WS-2 Workspace 实体 + 注册表 + 账本 + bootstrap | #151 |
| #153 | WS-3 列表契约补 workspace + 按项目列会话 | #152 |
| #154 | WS-4 项目 CRUD API（软删除语义） | #152 |
| #155 | WS-5 前端项目分组 UI | #153/#154 |
| #156 | MEM-1 记忆生命周期契约与机制 | 共同前置 |
| #157 | MEM-2 解禁 LangMem 的 update/delete | #156 |
| #158 | MEM-3 冲突消解 retrieve-before-write | #157（且需 #168 先落地，避开 extractor.py 同期改动） |
| #159 | MEM-4 遗忘入口（模型工具 DANGER+审批 / 用户 API） | #156 |
| #160 | MEM-5 前端记忆管理 UI | #159 |

### C. 执行顺序（本 Agent 的排程）

1. **#150**（在飞，卡全量 pytest 收集，先收口）
2. **#161 → #168** 顺序推进（PromptRegistry 组，硬链清晰）
3. **#149 → #151 → #152 →（#153 → #154 → #155）**
4. **#156 → #157 → #159 → #158**
5. **#160**
6. 前端票（#155 / #160）用 `impeccable`，并做真实浏览器验收。

> 交错原则：每票独立走完整 SDD 循环；`memory/extractor.py` 的改动（#164 / #167 / #168）与 #158 必须串行，不允许并行。

## 3. 执行队列（工作草稿）

> **权威进度账本是 `docs/PHASE_STATUS.md`**（AGENTS.md §16.5）。本表只是 Agent
> 自己的执行队列草稿，便于上下文被摘要后立刻找回位置；两者冲突时**以
> `PHASE_STATUS.md` 为准**，本表不承担事实源职责。

状态：`TODO` / `WIP` / `DONE`（DONE = 已 commit + 关单 + PHASE_STATUS 已追加）

| 票 | 状态 | commit | 关单 |
| --- | --- | --- | --- |
| #150 | DONE | `9a45a20` | 是 |
| #161 | DONE | `36fd7ef`+`a51fde2` | 是 |
| #162 | DONE | `af6cf44` | 是 |
| #163 | DONE | `aa40fc3` | 是 |
| #164 | DONE | `2c77c3b` | 是 |
| #165 | DONE | `2638d68` | 是 |
| #166 | DONE | `ef64d44` | 是 |
| #167 | DONE | `1a4c41f` | 是 |
| #168 | DONE | `611a6eb` | 是 |
| #149 | DONE | `4a4372f` | 是 |
| #151 | DONE | `9144631` | 是（AC6 写侧 met，attach 半交 #152） |
| #152 | DONE | `e3b81a6`+review 收口 | 是（两处 AC14 收窄 + validator 替换延后 #154 已记录） |
| #153 | DONE | `bacd20f`(后端)+`5650f43`(前端类型) | 是（两轴 review 收口；子代理子会话显示口径交 #155） |
| #154 | DONE | `711ea3e` | 是（两轴 review 收口：P1 绝对路径闸门 + 6 条 P2；CORS `*` 洞另立票） |
| #155 | 前端半 DONE（不关单，跨端） | `f015a60`+`8db0e5f`(前端代码)+`c224724`+`637bc89`(前端文档)，均在 feat/frontend | 否——后端半 #153/#154 未合入 main（§14.12）；comment 记录已完成部分 + 4 项后续票候选 |
| #156 | DONE | `61abcb6`+`aa775d8`+`f70ebe7`+`fad0e3c` | 是（两轴三轮 review，终验双轴 zero findings；真机 22/22；变异 15/15） |
| #157 | DONE | `ff57700`+`f3c80de`+`faf525f`+`090f07c` | 是（两轴四轮 review 终验：Spec 五 AC 全 met、Standards zero findings；真机 gate 16/16；真 Milvus 集成 5/5；变异 9/9） |
| #158 | DONE | `b687804`+`5276777`+`c6cbd12` | 是（三轴轮次收口：首轮 Standards 抓 P0 截断投影回写、次轮 P0 读失败仍写投影 + 4 条 P2、Spec 轴抓出"AC7-1 未达成"的真因（没传 `query_model`）——已修并真机复验；Spec 终验 AC1–AC6 met、AC7-1 真机达成、AC7-2 实测收敛但记为 provider 概率行为；31/31 变异 KILLED；真机 gate 16/16 PASS） |
| #159 | DONE | `af3db7a`+`19d51fc`+`d0647fa` | 是（两轴：首轮同一 major 被独立复现——客户端输入冒 500；二轮 2 条文档/一致性 minor 全修；Spec 终验 9 AC met、Standards zero findings；20/20 变异 KILLED；真机 gate 19/19；真 Milvus 集成 6/6） |
| #160 | TODO | | |

## 4. 门禁（每票必跑）

```bash
uv run ruff check .
uv run pytest -q                      # 后端全量（含基线 1618 passed / 10 skipped 上下）
cd web && npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build
```

## 5. 真实测试要求（用户强调）

- 后端：除单测外，真起服务（`uvicorn`），真发请求，真看 SQLite / JSONL / Milvus 落盘结果。
- 前端：真开浏览器（内置浏览器或 MCP），点真按钮，看真事件流；mock e2e 不算验收。
- 每个功能都要走一遍并记录「预期 vs 实际」。
- 问题实时写 `docs/FRONTEND_ISSUES_LOG.md`（含归属：前端 / 后端 / 未知）。

## 6. 已知遗留（开工前存在，需收口）

- `tests/test_instance_lock.py` + `src/agent_harness/instance_lock.py`：上一轮遗留，模块未验证、未接入启动点 → 由 #150 收口。
- `feat/FixBUG` 是历史遗留 ref（删除需 §14.4 批准，不做）。
- `.env` 本地文件不跨 worktree 同步：Langfuse / `CAPABILITIES.memory` / `MILVUS_COLLECTION` 需集成时手工核对。
