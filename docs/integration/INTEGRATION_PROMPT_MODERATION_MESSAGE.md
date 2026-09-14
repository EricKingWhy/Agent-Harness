# 集成提示词：data_inspection_failed 可读失败消息（feat/backend，2 个 commit）

> **给 Git Integrator 的批次提示词。** 本单只覆盖「内容审查可读失败消息」这一批。
> `feat/backend` 当前 tip 上还叠着其他会话的批次（见 §5 拓扑），每批有自己的
> `docs/integration/INTEGRATION_PROMPT_*.md`，请逐批对账，不要把本单当成全量执行单。

## 给 Git Integrator 的一句话

`feat/backend` 上本批共 **2 个 commit**（`41cc5de` + review 跟进 `9fe4dd9`）：
provider 内容审查拒绝（阿里云 `data_inspection_failed`）时，失败事件从裸类型名
`BadRequestError` 升级为已分类 reason + 固定可读文案。纯加性改动，无契约破坏。

## 背景（为什么）

用户会话 `a681b07a` 失败，UI 只显示 `model call failed: BadRequestError`，
排障要翻服务端日志才看到真因：阿里云百炼专有端点对含检索网页文本的二次
模型调用返回 400 `data_inspection_failed`（内容安全审查拒绝——维基百科
「戒急用忍」词条涉敏感词面）。

诊断结论（已与用户确认）：

- 会话失败与 Langfuse 无关。Langfuse 无记录是旁路熔断丢写（服务进程网络
  环境连不上 `jp.cloud.langfuse.com`，设计内降级），两件事恰好同时发生。
- fallback 不接管是策略正确（`TwoLevelFallbackPolicy` 对 4xx 不切换）。
- 本次修复只做「失败消息可读化」，不改 fallback 策略（用户明确不选重试
  方案——内容已判罚，重试无意义）。

## 改了什么

| 文件 | 改动 |
| --- | --- |
| `src/agent_harness/agent/runtime.py` | 新增 `_classify_provider_failure()` + 常量 `CONTENT_MODERATION_REASON`/`CONTENT_MODERATION_MESSAGE`；异常臂分类后向 `model/failed` 传 `readable_message`、向 `run/failed` 传 `reason`+`message`。**review 修复（`9fe4dd9`）**：分类前先判 `terminal.model_call_open`（模型调用在途窗口）——顶层异常臂同时兜底工具/执行器异常，工具阶段错误文本不得误标；提取 `moderation_message` 局部变量 |
| `src/agent_harness/session/session.py` | `Session.end_run` 增加 failed 语义的 `message: str \| None = None` 参数（缺省不落键） |
| `docs/BACKEND_CONTRACT_STREAMING_UI.md` | §4 `run/failed.data.reason` 枚举补登记：`provider_content_moderation` + 顺带补记此前漏记的 `identical_tool_failure_loop`、`context_window_exceeded` |
| `tests/agent/test_runtime_failure_paths.py` | +5 测试：run/run_stream 双路径分类断言（含 stream 的 model/failed 镜像断言）、model/failed 可读+脱敏断言（provider 回显原文不得进任何事件）、未分类错误回归锁、**工具阶段含错误码不误判回归锁**（篡改 `session.append` 在 tool/call 写盘时抛含错误码异常） |
| `tests/agent/test_run_finalizer.py` | +2 测试：`append_model_failed` readable_message 覆盖、`failure_terminal` reason+message 成对落盘 |

## 契约变化（加性）

- `run/failed.data.reason` 新增枚举值 `"provider_content_moderation"`
  （既有：`cancelled` / `orphaned` / `identical_tool_failure_loop` /
  `context_window_exceeded`）。**已登记进合同文档 §4**（`9fe4dd9`）。
- `run/failed.data.message` / `model/failed.data.message` 新增已分类故障的
  固定可读文案（中文）。前端 `runState.ts` 只特判 `reason === 'cancelled'`，
  未知 reason 自然落入 failed 分支——**无前端破坏**。
- 后续可选前端票：事件检查器/会话列表把该 message 直接渲染出来（本次只
  做后端，前端未动）。

## 不变量守护（两轴 code-review 已确认）

- 脱敏不变量不松动：事件只带本项目常量，provider 回显原文仍只进结构化
  日志（`_log(exc_info=True)`）。测试断言 `inappropriate` /
  `chatcmpl-*` 不出现在任何持久化事件 data。
- 未分类错误字节级行为不变（类型名消息、run/failed 不落 reason/message 键，
  有回归锁）；取消臂不受影响（`readable_message` 默认 None）。
- 分类限定模型调用在途（`model_call_open`），工具阶段含错误码文本不误判
  （有回归锁）。
- Standards 轴零硬违规；「reason/message 成对未提取为值对象」的 smell 按
  §8 有意推迟到第二类分类出现时（judgement call，非遗留缺陷）。

## 门禁证据

- `ruff check src/ tests/`：All checks passed。
- 全量 pytest：**1618 passed / 10 skipped / 0 failed**（review 修复后第 4 轮）。
  备注：中间 2 轮出现漂移的 web 传输层失败（16/24 个），逐项排查判定为
  **并行 AI 会话共用本 worktree 实时写文件/并发跑测试**造成的负载型 flaky
  （幻影文件名、失败集合逐轮不同、隔离运行全绿、同 commit 收集数漂移），
  非本批引入——集成后建议正常复跑一次全量确认。
- commit：`41cc5de` + `9fe4dd9`（feat/backend，未 push，§16.4 由集成处理）。

## §5 集成拓扑提醒

> **本节的数字已过期，请以批次手册为准**：
> `docs/integration/INTEGRATION_PROMPT_FEAT_BACKEND_PENDING_BATCH.md`（2026-09-12 重新 fetch 后实测）。
> 那份手册覆盖 `feat/backend` 上**全部在途 commit**（含本批这 2 个），并给出实测冲突预测。
>
> 刷新后的关键数字（2026-09-12，fetch 后）：
>
> - `origin/main` = **`bf81346`**（此前本节写的 `63db650` 已过期）
> - `feat/backend` tip = **`81833e7`**
> - `feat/backend` 相对 `origin/main`：**领先 12 / 落后 35**（此前写的"领先 32 / 落后 0"已过期——
>   那 32 个里有 26 个已由集成 AI 合入 main，包含本批 2 个 commit）
> - 实测冲突：**恰好 2 个文档**（`docs/PHASE_STATUS.md` 追加冲突、`docs/RESEARCH_PROJECT_MULTISESSION_AND_MEMORY_PLUGGABILITY.md` add/add），**零源码冲突**
>
> **对象库独立**这一条仍然成立且关键：`D:\intelligence-agent`（main 仓库）不认识 feat/backend 的
> commit（两边 `--git-common-dir` 各自是独立 `.git`，非共享 worktree）。集成时必须先传对象：
> `git -C D:/intelligence-agent fetch D:/intelligence-agent-backend feat/backend:refs/remotes/local/feat-backend`
> （本地路径 fetch，不必 push GitHub），自检 `git -C D:/intelligence-agent cat-file -t 81833e7`。
> 历史先例见 `docs/integration/MERGE_EXECUTION_ORDER.md` §1.1。
>
> merge 与 push 均需用户明确批准（§14.4）；PHASE_STATUS 同位追加冲突按 §14.7「多条全保留」先例处理。
