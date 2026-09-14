# 集成 AI 提示词

后端 `feat/backend` 新增两个 commit（基于 `fefc31f`），请合并到 `main`：

## commit 1：`e8281d6` — fix(artifact): cap inspect_artifact per-line char volume

- **问题**：`_slice_lines` 只按行数截断，单条超长行（十万字符）直接灌爆 Context
- **修复**：`_slice_lines` 新增 `max_chars_per_line=2000`；截断行携带 `truncated=True` + `full_length`，原文不动；`InspectArtifactTool` 暴露 `max_chars_per_line` 参数供模型放宽升级
- **触碰文件**：`storage/artifact.py`、`storage/s3_artifact.py`、`tools/inspect_artifact.py`、两份测试
- **契约变更**：`ArtifactSlice.lines` 字典新增可选 `truncated` / `full_length` 字段（仅超长行出现）；`truncated` 语义改为「行数截断 ∪ 字符截断」

## commit 2：`95da7d9` — refactor(agent): centralize SessionEvent → AgentEvent mapping

- **问题**：`runtime._drive` 在 11 处手拼 `AgentEvent`，字段演进要改 11 次
- **修复**：新增 `to_agent_event(event: SessionEvent) -> AgentEvent`（`agent/types.py`），11 个镜像点统一调用；`model/started` / `model/delta` 纯流式信号按设计不走映射
- **触碰文件**：`agent/types.py`、`agent/runtime.py`、`agent/__init__.py`、一份新测试

## 验收

- 后端 451 passed, 8 skipped, ruff clean
- 合并后建议跑前端 `time` 字段相关回归（项 2 是为后续 `time` 透传留单一入口，本次未加 `time` 字段）

## 注意

- 后端未碰 `main`，未碰前端，未碰其他 worktree
- `ArtifactSlice.lines` 形状变化若前端有反序列化校验，需同步放宽
