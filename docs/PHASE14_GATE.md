# Phase 14 Real Gate — Resume / Replay / Fork 完整化

> **日期**：2026-09-06
> **Ticket**：#115（Phase 14 收尾）
> **决策来源**：ADR-0017（grill 两轮逐项拍板；上游调研 pi / Claude Code / LangGraph / oh-my-pi 见 docs/PHASE14_RESEARCH.md）
> **执行方式**：`uv run pytest tests/integration/test_phase14_gate.py -m integration -v`
> **装配形态**：生产同款——**每会话一个 runtime**（web/CLI 同款；工具实例构造期绑定该会话 workspace）。真实模型 = `.env` 主模型链（primary senseaudio + fallback zhipu，两级异构），凭证零泄漏。
> **上游环境注记**：主上游（senseaudio）Gate 期间再次间歇 500「服务繁忙」；本 Gate 由智谱 fallback 吸收抖动完成（异构两级链首次在 Gate 中实战自愈）。

---

## 结果总览

| Gate | 内容（roadmap Phase 14 验收对照） | 结果 |
| --- | --- | --- |
| Gate 1 | fork 全链：真实两轮会话 → fork → child 独立 runtime 真实续跑，seed 快照可见 | ✅ PASS |
| Gate 2 | tail summary：真实 LLM 摘要挂 `session/forked.tail_summary` | ✅ PASS |
| Gate 3 | copy-on-fork 隔离：快照 + 双向隔离 | ✅ PASS |
| Gate 4 | `sessions --tree`：真实 fork 边渲染（[fork @seq]） | ✅ PASS |
| Gate 5 | replay 冻结契约：真实历史回放 + 零副作用 | ✅ PASS |

最终运行 **5/5 单轮通过（46.79s）**。CI 全量回归：**1089 passed, 9 skipped, 25 deselected**（25 = 本 gate 5 条 + 既有 integration/qiniu 凭证门），ruff clean。

## Gate 1 — fork 全链（真实续跑）

真实两轮会话（第 1 轮 bash 创建 marker.txt 内容 phase14-seed；第 2 轮纯问答）→
在第二条用户消息处 fork → child 独立 runtime 真实续跑「用 bash 查看 marker.txt」→
`run/completed` 且 final_text 含 **phase14-seed**——child 通过 fork 点 workspace
快照看到父的第一轮产物。父文件全程零改动（无 session/forked 等任何追加，§7）。

## Gate 2 — tail summary（真实生成）

父会话（两轮，第 2 轮为「被放弃的路线」）fork 时经真实主模型链一次调用生成摘要 →
`session/forked.tail_summary` 在场且非空。失败降级路径由单测钉死
（tests/session/test_fork.py：异常 → 字段缺席、fork 照常，不变量 #21）。

## Gate 3 — copy-on-fork 隔离

父经 bash 真实创建 iso.txt（"before-fork"）→ fork → **child workspace 含快照文件**；
child 改写自己的副本后父文件原文不动；父 fork 后新写文件不进 child（双向隔离）。
物理策略独立于事件 fork（spec §7）；artifact 为全局 store ref 不复制。

## Gate 4 — lineage 树（真实 fork 边）

真实 fork 后 `sessions --tree`（CLI，惰性回填索引）渲染出父节点 + child 节点，
child 带 `[fork @seq]` 标注——fork 边（origin=fork）与 Phase 13 delegation 边
（origin=delegation，Phase 13 Gate 已实证）共用同一棵树。

## Gate 5 — replay 冻结契约

真实会话（bash echo replay-ok）→ `replay_command` 渲染：`[工具] bash(...)` 与
冻结终态结果（replay-ok）可见；**零副作用**断言：回放前后 store 事件逐字节相等
（连 session/resumed 都没有追加）、无模型调用（不构造 runtime）、workspace 不触碰。
重新执行式 replay 按 ADR-0017 DEFER。

## Gate 抓到的真问题（修复记录）

1. **zhipu 未入册 PROVIDER_PRESETS**（config.py）：Gate 1 首跑在
   `ModelConfig.from_settings` 崩溃——CLI fork 摘要链（T5 引入的真实路径）
   遇 zhipu fallback 即炸；Phase 12 Gate 2 因直构 ModelConfig 绕过校验而未暴露。
   修复 = zhipu preset 入册 + 单测（tests/test_model_provider.py：preset 解析 +
   from_settings 全链含 zhipu fallback）。
2. **测试装配伪影**：初版 gate 用单 runtime 跨父子会话——工具实例构造期绑定
   runtime 级 workspace，child 的 bash 根本不走 fork 复制的快照。修正为生产
   形态（每会话 build_runtime）后 copy-on-fork 才被真实 exercised。该修正同时
   印证了 ADR-0017 的 copy-on-fork 语义与「每会话独立 runtime」生产架构天然咬合。
3. **模型服从波动**：Gate 2 首轮 3 次尝试未全成（上游抖动叠加），复跑通过——
   3 次尝试协议继续有效；Gate 3 的 echo 引号/换行写入改子串断言（语义断言
   不绑定表面格式）。

## 遗留 / DEFER（ADR-0017 已记录）

- 重新执行式 replay（显式授权模式）、步进式 TUI
- Web 端发起 fork（创建端点 + boundary 选择器 UI）
- tree-in-file / 原地多分支导航（pi /tree）——由「多会话 + lineage 视图」承担
- 前端 lineage 树形渲染（API 已就绪 #113；等 B AI 流式改造合入后做前端批，
  避免同窗改 inspector）
