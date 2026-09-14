# 交接手册 — 后端问题 OBS-008 ~ OBS-015（前端真机巡检产出）

> **来源**：前端「刷新一致性 + 控制面清点 + 审批卡覆盖」批次的真机巡检（真实后端 `127.0.0.1:8000` + 真实浏览器 CDP + 真实模型）。
> **原始登记簿**：`docs/FRONTEND_ISSUES_LOG.md`（含完整证据链与 45 个按钮的清点表）。
> **交接时间**：2026-09-11，由集成 AI（Git Integrator）整理并**逐条核验 file:line**（不是照抄）。
> **给谁**：后端 AI（用户指示「全让后端做了」）。
> **前提**：所有条目均已在 `main`（`876bdf2` 之后的 tip）上复核过行号，可直接开工。

---

## 0. 一句话总览

| # | 级别 | 一句话 | 归属 | 文件 |
| --- | --- | --- | --- | --- |
| **OBS-011** | **P2** | cmd.exe 的 GBK 输出被按 UTF-8 硬解 → **乱码固化进 append-only JSONL** | 后端 sandbox | `src/agent_harness/sandbox/local.py:161,166-167`；同模式 `docker.py:140-141` |
| **OBS-012** | **P2** | `bash` 工具在 Windows 上实为 cmd.exe（`shell=True`）——工具名与语义不符 | 后端 sandbox | `src/agent_harness/sandbox/local.py:161` |
| **OBS-013** | **P2** | provider 退化重复：一轮 2,868 个 `text/delta` / 186,507 字符无限重复，始终不调工具 | provider / 后端 | 无源码行；见事件证据 |
| **OBS-008** | 观察 | 工具成功后 `model/failed: RuntimeError`（`glm-5.3-flash`） | provider / 后端 | 无源码行；异常被吞，建议落 traceback |
| **OBS-009 / OBS-014** | 观察 | bash 工具 **10.0s 硬超时**且 `retryable:false`（同族，014 补实证） | 后端 Tool Runtime | 超时策略/常量 |
| **OBS-010** | 观察（低） | `GET /api/sessions` 的 `trace_id` **从来没有值**（事件里有） | 后端 web 端点 | 会话列表端点未回填 |
| **OBS-015** | **P2** | 审批卡 `catch` 把**任何**错误都翻成「已批准/已拒绝」——注释与行为相反 | **前端文件** + 需产品决策 | `web/src/components/ApprovalCard.tsx:22-33` |

**优先级建议**：OBS-011 > OBS-015 > OBS-012 > OBS-013 > OBS-009/014 > OBS-008/OBS-010。

---

## 1. OBS-011（P2）子进程输出按 UTF-8 解码，而 cmd.exe 输出 GBK → 乱码落盘

### 现象

工具输出在 **UI 与落盘事件中都乱码**。两次实证：`��ʱ��Ӧ�� i��`（cmd 的「此时不应有 i。」）、`���� Ping 127.0.0.1 …`。

### 铁证（区分前后端的关键）

读某会话 `events.jsonl` 的**原始字节**，delta 为：

```
\xef\xbf\xbd\xef\xbf\xbd\xca\xb1\xef\xbf\xbd…
```

即 **U+FFFD（`\xef\xbf\xbd`）与「侥幸合法的 UTF-8 双字节」混杂**：`\xca\xb1` 被解成 U+02B1（ʱ）、`\xd3\xa6` 被解成 U+04E6（Ӧ）。GBK 的「时」「应」两字节恰好构成合法 UTF-8 序列 → 剩下非法处变 U+FFFD。文件本身是**合法 UTF-8**、含 **24 个 U+FFFD**。

**结论：乱码发生在事件落盘之前**，前端只是忠实渲染磁盘内容。

### 根因（已核验行号）

`src/agent_harness/sandbox/local.py`：

```python
process = subprocess.Popen(
    command,
    shell=True,                      # ← 161（见 OBS-012）
    ...
    encoding="utf-8",                # ← 166
    errors="replace",                # ← 167
)
```

源码注释已自承认「Windows 中文系统默认 GBK…用 `errors=replace` 保证不崩」——代价是把乱码固化进 append-only 事件日志。**同一模式**见 `src/agent_harness/sandbox/docker.py:140-141`（`decode("utf-8", errors="replace")`）。

### 为什么必须修

JSONL 是本项目可观测性的**单一事实源**——回放、eval、Langfuse 都读它。乱码一旦落盘**不可逆**，且会让「模型看到的工具输出」与真相不一致。这是不变量 #3（append-only typed SessionEvent）与 §7「Event ≠ Diagnostic Log」的直接冲突面。

### 建议修法（二选一，推荐 A）

- **A（推荐）**：按平台/代码页解码，而不是硬编码 UTF-8。
  - Windows：用 `locale.getpreferredencoding(False)` 或显式取 `chcp` 对应的代码页，并对 `errors` 采用可回退策略（先按首选编码解，失败再回退 `utf-8` + `replace`）。
  - POSIX：保持 `utf-8`。
  - 关键点：**把"解码方式"作为一次决策记录下来**（例如 delta 里带 `encoding` 元数据），让"这次解码是否可信"可审计。
- **B（最小改动）**：改 `errors="replace"` 为 `errors="backslashreplace"`——至少让不可解字节**可见可定位**（`\xca` 而不是 U+FFFD），不会伪装成合法字符。

> ⚠ 无论选哪种，**不要**把已落盘的乱码"就地改写"——append-only 是宪法。历史会话的修复只能是独立的一次性迁移工具（参照 `scripts/migrate_legacy_step_id.py` 的 dry-run 默认 + 备份模式），且需要用户明确批准。

### 验收标准

1. **先复现**：写一个测试，用 GBK 字节序列走 sandbox 输出路径，断言落盘 JSONL 里**没有 U+FFFD**（当前必然失败 = 红）。
2. **修后绿**：同一测试通过，且中文输出可读。
3. **跨平台**：POSIX 分支行为不变（回归锁）。
4. **边界**：混合编码 / 纯二进制输出不崩、不产生非法 UTF-8 文件（文件必须是合法 UTF-8）。
5. `docker.py` 同模式一并核（DockerSandbox 输出路径）。

---

## 2. OBS-012（P2）`bash` 工具在 Windows 上不是 bash

### 现象

- `for i in $(seq 1 10); do …; done` **41ms 内**以 `exit_code=1` 失败，stderr 为 cmd.exe 的「此时不应有 i。」。
- 同会话 `1fdac9b9`：`echo "Current user: $(whoami)"` 的输出里 `$(whoami)` 被**原样回显**——cmd.exe 不做命令替换。
- 而 `ls -la` 却能工作（PATH 里有 Unix 工具）——**部分可用**，失败是间歇性的，模型因此反复试错。

### 根因（已核验行号）

`src/agent_harness/sandbox/local.py:161` 的 `shell=True` → Windows 下走 `COMSPEC`（cmd.exe）。

### 影响

工具名与语义不符，会诱导模型（与人类）按 bash 语法写命令并莫名失败。实证：该会话 **4 次 `model/fallback`、7 次工具调用、2 次工具失败**——直接拉高 token 与失败率，且与 OBS-013 的退化循环形成组合失效。

### 建议修法（需产品/架构决策，见下）

1. **最小且诚实**：若短期不接真 bash，则**改工具描述/名称**（例如在 tool description 明确「Windows 宿主下为 cmd.exe，请用 cmd 语法」），让模型不再误用 bash 语法。这是零风险改动，先做。
2. **正确但较大**：Windows 上优先探测 `bash.exe`（Git for Windows / WSL），存在则用它并保留 POSIX 语义；不存在再回落 cmd.exe 并**显式声明**。
3. 注意 §14 边界：这是 **Sandbox 边界**的语义问题，修法不得让工具绕过统一 ToolExecutor（不变量 #7），也不得用 Prompt 替代 Runtime 事实（不变量 #11）。

### 验收标准

1. **先复现**：单测断言「Windows 上 `$(...)` 不被替换 / bash 语法失败」当前为红。
2. 修后：要么 bash 语法可用（真 bash），要么工具描述明确声明 cmd 语义（并有一条测试锁住该声明存在）。
3. **不得**改变 POSIX 上的行为与既有工具契约测试。

---

## 3. OBS-013（P2）provider 退化重复循环 + 频繁 fallback

### 现象

会话 `7d5a6f24` 一轮生成 **2,868 个 `text/delta`、共 186,507 字符**，内容为 `"Let me run the command."` 的无限重复，**始终没有发出工具调用**，持续 **3.5 分钟**后由用户点「停止」收口（`model/failed: model call cancelled`）。

全语料另有多次：`model/fallback: deepseek-v4-flash-0731 → glm-4.5-air · InternalServerError`。

### 归因

provider / 后端。**前端表现正确**（脉冲「思考中」、文本持续流入、停止可用）。

### 建议（评估项，不一定是代码 bug）

1. provider 是否有 **重复惩罚 / 最大生成长度护栏**？该模型是否可配 `frequency_penalty` 一类参数（注意：参数映射属 provider 线格式适配，参照刚合入的 `reasoning_effort` 翻译模式——**单一翻译点**，不要散落）。
2. 「长时间无工具调用的大段自重复」是否可作为**可观测信号**提前暴露（例如 idle 看门狗已有 `ModelStallError`，但它是按"无 token"判定；这里 token 一直在流，**现有看门狗抓不到**）。
   - 可考虑：字符级重复率检测 → 触发 `MODEL_FALLBACK` 或 end_run(failed)，而不是等用户手点停止。
3. 与 OBS-009/014 组合会出现「想跑长命令 → 超时 → 反复重试/退化」的失效链——修 013 时请一并评估。

### 验收标准

1. 若加护栏：有测试证明「重复 N 次后触发熔断/fallback」，且**不得**误伤正常的长推理输出。
2. 若判定为 provider 侧不可控：登记为已知风险并给出**用户可用的止损路径**（现有「停止」按钮已可用——需确认它不依赖前端在途状态）。

---

## 4. OBS-008（观察）工具成功后 `model/failed: RuntimeError`

### 事件真值（会话 `1fdac9b9`，seq 404–409）

```
404 tool/call          bash {"command": "sleep 8 && echo proof-8842"}
405 tool/output_delta  stdout: "proof-8842\n"
406 model/completed    model=glm-5.3-flash usage=9521  tool_calls=[bash]
407 tool/result        {"ok": true, "exit_code": 0, "stdout": "proof-8842\n", "duration_ms": 8115.9}
408 model/failed       "model call failed: RuntimeError"
409 run/failed
```

### 判读

工具**成功**（`ok:true, exit_code=0`），随后**模型调用**抛 `RuntimeError` → run 收口 failed。UI 渲染忠实，**不是前端 bug**。

### 归因与建议

后端 / provider。与既有 OBS-001 同族（同一模型 `glm-5.3-flash` 此前返回 400 `BadRequestError`），本次是 `RuntimeError`。

**核心问题**：`model call failed: RuntimeError` 把**原始异常吞成一句无 traceback 的字符串**。本 P0 级别的问题（选「标准/深度」必 400）之所以拖了三天，正是因为日志里没有可检索的结构化记录（该条经验已促成 `reasoning_effort` 修复改用 `log_event` 结构化事件）。

**建议**：把原始异常类型 + traceback 落进结构化日志（`log_event`，component=model_provider）与/或 JSONL 诊断行，使同类问题下次可直接检索定位。

### 验收标准

1. 模型调用失败时，日志含**异常类型 + traceback**（结构化字段，非纯字符串拼接）。
2. 有测试锁住该日志形状。

---

## 5. OBS-009 / OBS-014（观察）bash 工具 10.0s 硬超时且 `retryable:false`

### 证据（两处独立复现）

```
seq 6  tool/call   bash {"command": "sleep 10 && echo MARKER-A1"}
seq 8  tool/result {"ok":false,
                    "message":"工具 'bash' 执行超时（上限 10.0 秒）…",
                    "error_code":"TIMEOUT","retryable":false,
                    "metadata":{"attempt":1,"max_attempts":3,"duration_ms":10002.6}}
```

- `sleep 10` 与上限 10.0s 贴边 → **必然越界**。
- OBS-014 补实证：`sleep 30 && echo resume-test-done`、`ping -n 45 127.0.0.1` 均 `TIMEOUT`（`retryable:false`）；`ping -n 4` / `sleep 9` 正常。即**单条命令上限 10.0s**。

### 判读

前端渲染**正确**（Timeline 显示 `TIMEOUT` 失败，同一 run 的 pulse 仍「已完成」——因为工具失败可被模型恢复：工具失败 ≠ run 失败）。本例模型自行改写为 `sleep 1 && echo MARKER-A1` 后成功。

### 建议（两点需后端确认）

1. **`retryable:false` 与不变量 #8 的取舍**：若 TIMEOUT 一律不重试，则瞬时超时只能靠模型自己重发（本例如此——但这**不是引擎的重试语义**，而是模型行为，语义上可疑）。请对照 `04_TOOL_RUNTIME.md` 确认 TIMEOUT 的分类到底是「不可重试的确定性失败」还是「可重试的瞬时失败」。
2. **10s 上限偏紧**且**错误文案自相矛盾**：文案写「可稍后重试」却标 `retryable:false`——二者读起来冲突。要么改文案，要么改 `retryable`。

### 验收标准

1. 明确 TIMEOUT 的 `retryable` 语义并在**测试中锁定**（含"重试只由 ToolExecutor 负责"不变量 #8）。
2. 文案与 `retryable` 一致；上限值若可配，写明配置来源。

---

## 6. OBS-010（观察 · 低）`GET /api/sessions` 的 `trace_id` 恒为 null

> ⚠ **本条曾误判并已由前端自行订正**：初版写成「70 个会话 trace_id 全为 null → Copy Trace ID / Open Trace 永不出现」，**结论是错的**（只查了列表端点，没查事件）。

### 实测（2026-09-11）

- `GET /api/sessions`：70 个会话，`trace_id` **全部为 null**。
- 但**事件里有**：会话 `f181c5ce` 的 `run/failed`（seq 33）携带
  `trace_id: 2482fcee980f20ad111e3d19289043b1` + 对应 Langfuse `trace_url`。
- 命令面板两条 trace 命令**确实出现且工作**（`clipboard.writeText` 实参、`window.open` URL 均已拦截取证）。

### 判读

Langfuse **已接入**。前端两条命令的可见性取自 `conversation.trace_id` / `conversation.trace_url`（由 `projection` 从 run 终态事件抽取，契约 `2d7f87a`），**不依赖会话列表**——列表 `trace_id` 为 null 完全不影响它们。

**真正剩下的后端小观察**：`GET /api/sessions` 的 `trace_id` 字段**从来没有值**（不是"本部署没接 Langfuse"，是该端点没回填）。

### 影响与建议

当前前端不用它 → **无用户可见影响**。但若将来想在**会话行**上直接标 trace，必须先把该字段回填。建议：要么回填（从会话最后终态事件派生），要么**显式从响应模型里删掉**该字段（避免"永远是 null 的字段"误导后来的消费者）。

### 验收标准

二者取一：① 字段有值（含测试）；② 字段被删除（含 API 契约测试更新）。**不要**保持"永远 null 但看起来像能用的字段"。

---

## 7. OBS-015（P2）审批卡 `catch` 把「任何错误」都当成已决

> ⚠ **归属提醒**：本条修改的是 **前端文件** `web/src/components/ApprovalCard.tsx`。按 `AGENTS.md §13.1`，前端改动应在 `D:\intelligence-agent-frontend`（`feat/frontend`）进行，不在后端 worktree。用户已指示「全让后端做」——执行时请**只在这个文件上**遵守该边界，或明确向用户确认由哪个 worktree 承载。

### 位置（已核验）

`web/src/components/ApprovalCard.tsx:22-33`：

```ts
const decide = async (approved: boolean) => {
  if (busy) return;
  setBusy(true);
  try {
    await postApproval(sessionId, approval.approval_id, approved);
    setDecision(approved ? 'approved' : 'denied');
  } catch {
    // 409 = already resolved (idempotent success); other errors leave card pending
    setDecision(approved ? 'approved' : 'denied');   // ← 注释说的是 A，代码做的是 B
  } finally {
    setBusy(false);
  }
};
```

### 问题

注释写「其它错误保持 pending」，**代码却把任何错误都翻成「已批准/已拒绝」**。

后果：审批 POST 真的失败（网络抖动、404、403、后端未接线）时，用户看到「已批准/已拒绝」的**乐观假象**，而 run 实际**仍卡在等审批**（直到 300s fail-closed 超时）。

**对安全相关的审批交互，这个方向的假象比「转圈不响应」更危险**：用户以为放行了。

### 证据

把 `/approve` 改成**恒返回 404**，UI 依旧显示「已批准」、按钮消失、请求体依旧正确——**只有查后端 `permission/resolved` 才能区分真假**。故前端联调车道的判决断言已改为轮询后端事件（`web/e2e-live/approval-live.spec.ts`）。

### 建议修法

区分两类错误：

| 情况 | 期望行为 |
| --- | --- |
| `409` / `404`（已决，幂等成功） | 翻「已批准/已拒绝」（当前行为，保留） |
| **其它**（网络、5xx、403…） | **保持 pending + 显示错误提示**，允许用户重试 |

至少应先把**注释改成与代码一致**，避免下一个人再被误导（若产品决定保持乐观语义，也必须写清"这是有意的乐观 UI"）。

### 回归锁现状

`web/e2e/n-approval-card.spec.ts` **只覆盖成功路径**（mock 返回 200）。**失败路径无覆盖**——修 OBS-015 时**必须补**一条「POST 500 → 卡片保持 pending」的用例。

### 验收标准

1. **先复现**：新测「POST 500 / 网络错误 → 卡片仍 pending 且有错误提示」当前为红（因为当前会翻已决）。
2. 修后绿；成功路径与 409/404 幂等路径**既有行为不变**（回归锁）。
3. 注释与代码一致。

---

## 8. 集成/交付注意

1. **不要动 `docs/FRONTEND_ISSUES_LOG.md` 里前端已写入的实施记录**——那是证据。
2. OBS-011 的历史乱码修复若要做，必须是**独立的一次性迁移工具**（dry-run 默认 + 备份），且需用户明确批准；不得就地改写 JSONL。
3. 每项修复完成后按 `AGENTS.md §16` 走：`/code-review` → `ruff check` + 全量 `pytest` → commit → 更新 `docs/PHASE_STATUS.md`。**push 需用户单独批准**。
4. 若某条判定为"不修/需产品决策"，请在 PHASE_STATUS 或本文件追加**结论行**，不要静默跳过——本批 OBS-015 就是前一轮静默留给后来的。

---

## 9. 附：本次交接的核验记录（集成 AI 侧）

| 条目 | 声称的 file:line | 实际核验结果 |
| --- | --- | --- |
| OBS-011 | `sandbox/local.py:166-167` = `encoding="utf-8", errors="replace"` | ✅ 逐字命中 |
| OBS-011 | `sandbox/docker.py:140-141` = 同模式 decode | ✅ 逐字命中 |
| OBS-012 | `sandbox/local.py:161` = `shell=True` | ✅ 逐字命中 |
| OBS-015 | `ApprovalCard.tsx:26-33` catch 块 | ✅ 命中（`decide` 函数体 22-33，catch 28-30，±2 行内） |
| OBS-010 | `web/app.py:594` fail-open 令牌校验 | 见 `FRONTEND_ISSUES_LOG.md` 原始登记 |
| OBS-015 归属 | `session/service.py:348` 的 `permission_mode_explicit` 才是审批的门 | ✅ 前端已用真机点击证伪「产品不可达」，本手册沿用该订正 |
