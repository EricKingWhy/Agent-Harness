# 前端 → 后端：P1 修复收到，回三条

> 日期：2026-09-09 ｜ 分支：`feat/frontend` ｜ 回应 `HANDOFF_FRONTEND_TECH_DEBT.md`
> §3.1 / §5 P1 / §5 P2 / §6 更新版。

## ① T1 / T2 进度

**T1（续聊透传 amend）— 完成**

| 文件 | 改动 |
| --- | --- |
| `web/src/lib/api.ts` | `SendMessagePayload` 增 `model` / `agent_profile` / `reasoning_effort` / `context_providers`；`sendMessage` 兜底归一化（空值 / 空数组不发键） |
| `web/src/hooks/useSession.ts` | `sendFollowUp` 增可选 `amend`（类型 `Omit<SendMessagePayload, 'content' \| 'mode' \| 'max_steps'>`） |
| `web/src/App.tsx` | 续聊分支按「有值才带」传入选档；`permission_mode` 不在 `/messages` 契约内，未传 |

**T2（过期注释）— 完成**：`StartSessionPayload` docstring 改为现状（四项均运行时消费）。
顺带修正：`reasoning_effort` 的引用原写 `(ADR-0018 D7)`（ADR-0018 是 Langfuse 观测），
改为落地 commit `79e2860`。**注意：这条误引同样存在于冻结规格**
`docs/spec/Observable_Agent_Workspace_SDD/03_RUNTIME_EVENT_CONTRACT.md:617` 与
`08_DECISION_LOG.md:136`，前端注释原本是照抄——建议后端侧一并勘误。

**测试**：`tsc -b` clean、`vitest` 377 passed、`oxlint` 0 error、`playwright` 44 passed
（含 4 条续聊 amend e2e：四项有值 / 部分有值 / `context_providers` 选中进 payload /
queued JSON 确认不误报）。commit：`a518d3f`（T1+T2）、`5e5c1e1`、`2be274d`、`af0a270`、`88548af`（三轮 code-review 修复）。

## ② 第 3 条（422 提示）— 选「统一提示」

采用统一文案，**不做 `detail` 子串区分**，理由三条：

1. 仓库既有标准明确反对跨模块魔法子串耦合——`useSession.ts` 的
   `UNKNOWN_MODEL_ERROR_TEXT` + `isUnknownModelError` 这对常量/判定函数就是为此引入的；
   按 `detail` 区分会把前端绑到后端文案上。
2. `detail` 不是契约文本，且形状不统一：Pydantic 校验是结构化数组，
   `HTTPException` 是字符串——同一状态码下两种形状。
3. 四种成因对用户的下一步动作相同（刷新选项后重试）。

实现：新增 `CONTINUE_PARAMS_ERROR_TEXT = '续聊参数无效（422）：请刷新选项后重试'`，
`sendFollowUp` 的 422 改抛它；新增 e2e 断言错误条含「续聊参数无效」且不含「模型不可用」。
create 路径的 `UNKNOWN_MODEL_ERROR_TEXT` 不动。

**实现过程中发现并修复了一个既有 bug（否则新文案根本看不见）**：`useSession.ts` 的
viewing-mode 历史加载 effect 无条件 `setError(null)`，而 `sendFollowUp` 的 catch 是
「先 `setMode(viewing)` 再 `setError(...)`」——同一批次里 error 被 effect 立刻抹掉，
**所有续聊失败（含网络错误）此前都是静默的**。重连 give-up（`连接中断…`）与重连 404
（`会话不存在（404）`）走同一模式，同样被抹。修复：只在真的切换会话（或首次加载）时清错误
（复用既有 `shouldShowHistoryLoading(conversation, sid)` 判定），live→viewing 自迁移不再清。

**若将来希望「失效引用类 id → 自动刷新目录」**，建议后端给 422 加一个机器可读的
`code` 字段（如 `unknown_model` / `unknown_context_provider`），前端按 code 分支——
这比 `detail` 子串稳定，也不需要前端解析中文。

## ③ 手册与实现的一致性核查

**核对了，未发现实质不一致。** 逐条对过：

- §3.1 校验语义 ↔ `web/app.py:422-438 _validate_amend_for_existing_session`
  （`context_providers` 对照 wiring、`model` 走 `from_catalog` → 422）与
  `app.py:139-175` 的静态 `@field_validator`（`check_fields=False`，三个请求体共用）。一致。
- §3.1「`/messages` 仅 idle→launched 才校验、queued/steer 忽略」↔ `app.py:1162-1183`
  （非该路径直接 `amend = AmendOptions()`）。一致。
- §5 P1「不再有 500」↔ `tests/web/test_web_amend_validation.py` 已锁定 422 语义。一致。
- §6 第 2 条（P1 已完成）↔ 本地 main `3a662a9`。一致。

**两处非实质偏差**：

1. §5 P2 引用的 `useSession.ts:663` 已漂移——T1 改动后该 422 分支现在在 `:685`。行号引用会随
   改动过期，建议手册少引行号、多引函数名。
2. 前端侧一个**既有 bug**（非本批引入，**只报告不改**）：App.tsx 的「422 → 刷新目录并清死选中值」
   实际从未触发——`isUnknownModelError` 是**精确相等**判定，而 `useSession` 的 catch 一律把
   文案包成 `提交失败：${msg}` / `续聊失败：${msg}`，前缀导致永远匹配不上。要恢复该自愈路径，
   需二选一：catch 不包前缀，或判定改为「包含」。**这属于既有代码，不在本批 scope**，请知悉即可。

   （与上面 ② 里已修的「viewing effect 抹掉错误」是两个独立缺陷：那个影响错误**可见性**，
   这个影响 422 后的**自动刷新**行为。）

## 附：本批前端 commit

`a518d3f` → `5e5c1e1` → `2be274d` → `af0a270` → `88548af`（均在 `feat/frontend`，未 merge / 未 push）。
