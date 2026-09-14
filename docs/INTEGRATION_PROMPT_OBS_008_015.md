# 集成提示词：OBS-008 … OBS-015 批次（feat/backend）

> 来源：集成 AI 的 `docs/HANDOFF_BACKEND_OBS_008_015.md`（该文件只在 `main`，本 worktree 未同步）。
> 本文件是**批次单一入口**：每完成一项就更新下表 + 对应小节，集成 AI 只看这一个文件即可。
> 约束：**本分支不 push**（§16.4）。集成由集成 AI 执行。

## 0. 可执行摘要（给集成 AI）

```bash
# 1) 合并前自检（本分支）
git -C D:\intelligence-agent-backend log --oneline -8
git -C D:\intelligence-agent-backend diff main...feat/backend --stat

# 2) 合并后门禁（集成 worktree：D:\intelligence-agent）
uv run ruff check src/ tests/
uv run pytest -q

# 3) 只针对本批次改动的聚焦回归
uv run pytest tests/sandbox/test_output_encoding.py -q      # OBS-011（22 个）
uv run pytest tests/agent/test_phase5_runtime.py -q         # OBS-011 的连带回归
```

合并顺序与冲突面（随批次推进更新——本批次已从纯 sandbox 扩到 runtime/executor/session 多层）：

- **OBS-011**：sandbox 解码路径 + 测试。`LocalSubprocessSandbox` 构造签名新增可选参数
  `fallback_encoding`（默认 `None` → 自动探测），既有调用方无需改动。
- **OBS-012 + 深化候选 3**：`sandbox/base.py` 新增非抽象 property
  **`shell_environment`**（返回 `ShellEnvironment(name, family)`，不进冻结的
  6 个抽象契约）+ local/docker 覆写 + `tools/bash.py` 按 `family` 分支。
  第三方 Sandbox 后端不覆写也能实例化（基类默认 `("sh", POSIX_SH)`）。
  ⚠ **该 property 在深化提交 `9fe0809` 里由 `shell_description: str` 改名而来**
  （两步都在本分支内、均未合入 main，故无外部消费方）——若你手上是旧版交接单/旧
  分支，请以 `shell_environment` 为准。
- **OBS-009/014**：`tooling/executor.py` 超时文案分支（纯文案，无重试行为变化）。
- **OBS-008**：`agent/runtime.py` 的 `_log` 新增 keyword-only `exc_info`（12 处调用
  已核零碰撞）+ 三处失败臂传 `True`。
- **OBS-010**：`session/store.py` 的 `SessionSummaryStats` 末尾新增带默认值的
  `trace_id` 字段（既有 5 个位置参数构造不受影响）+ `session/service.py` 与
  `web/app.py` 各透传一处。

**不碰前端**（OBS-015 除外，其改动在 `feat/frontend`）。API 形状只增不改：`/api/sessions`
每行新增 `trace_id` 字段（前端类型早已声明该字段，本次是让后端真的返回值）。

## 1. 状态总表

| 项 | 优先级 | 状态 | commit | 一句话 |
| --- | --- | --- | --- | --- |
| OBS-011 | P2 | ✅ 完成 | `d4eb17e` | 子进程输出按产出方编码解码，GBK 乱码不再固化进 JSONL |
| OBS-015 | P2 | ✅ 完成 | `cb0e008`+`4580a69`+`274afcf`（**feat/frontend**） | 审批卡 catch 不再乐观翻转；404 语义订正 + fail-safe 回归锁 |
| OBS-012 | P2 | ✅ 完成 | `d9bef3a` | bash 工具描述声明真实解释器（POSIX/容器=sh，Windows=cmd.exe），不再谎称 bash |
| OBS-016 | P2 | 🆕 待定 | — | **本轮新发现（同源缺陷，Scope 外）**：`tools/read.py:140` 超长行提示仍教模型用 POSIX 专有 `sed`/`head -c`/`tail -c` |
| OBS-013 | P2 | ✅ 已评估（登记风险） | — | 限时护栏已存在/启用/已测（600s total）；无代码改动 |
| OBS-009/014 | — | ✅ 完成 | `9807928` | 超时文案与实际 `retryable` 对齐（MUTATING 不再教盲重跑）；纯文案 |
| OBS-008 | — | ✅ 完成 | `0fceccc` | 模型调用失败的调用栈落结构化日志（durable 事件仍只带类型名） |
| OBS-010 | low | ✅ 完成 | `499dc3d` | `GET /api/sessions` 的 `trace_id` 从恒 null 改为回填末条 run 终结事件 |

---

## 2. OBS-011：GBK 输出被按 UTF-8 硬解 → 乱码固化进 append-only JSONL

**状态**：✅ 完成，commit `d4eb17e`（分支 `feat/backend`，未 push）。

### 根因

`LocalSubprocessSandbox.exec()` 把子进程输出**硬编码**按 `utf-8 + errors="replace"` 解码。
中文 Windows 上 cmd.exe 的报错/内建命令输出是宿主控制台代码页（本机 **cp936/GBK**），
于是被解成 U+FFFD 乱码。乱码一旦写进 append-only JSONL 就**不可逆**：回放 / eval /
Langfuse 都读它，且模型看到的工具输出与真相不一致。

### 修法

新增 `src/agent_harness/sandbox/decoding.py::StreamDecoder`，`Popen` 改 `text=False` 走字节流：

1. 先按 UTF-8 **严格**增量试探（跨 chunk 缓冲不完整序列），上限 `PROBE_LIMIT = 64 KiB`；
2. 遇到确凿非法序列 → 判定整条流为兜底编码，并**重解已缓冲的全部字节**（不丢前缀）；
   判定粘性，同一条流不反复横跳；
3. 攒满 64 KiB 合法 UTF-8 → 判定 UTF-8；
4. 兜底编码取 `ctypes.windll.kernel32.GetOEMCP()`（本机 936）。
   ⚠ **不能用 `locale.getpreferredencoding()`**：本环境 `PYTHONUTF8=1` 会让它返回
   `utf-8`，正好丢掉要的信息；
5. 保留 `text=True` 时代的通用换行归一（`\r\n` / 孤立 `\r` → `\n`，含跨 chunk 切分、
   文件末尾孤立 `\r`）——改字节流后不会自动发生，丢掉会让每条 Windows 工具输出多一个
   `\r` 进入模型上下文与 JSONL，**并改变内容哈希**（曾使 `test_phase5_runtime` 挂在
   `KeyError: Artifact ... does not exist`）。
6. `docker.py` **刻意**保持固定 UTF-8 并注明理由（容器输出源自 Linux 进程，与宿主机
   控制台代码页无关）。→ 这是有意的**不对称**，不是漏改。

### 关键不变量（改动时务必守住）

> **判定后绝不能再抛。** `_drain_stream` 用宽 `except Exception` 兜异常，
> 解码器抛错会被吞掉并**无声明地截断整条流的剩余部分**。

据此：判定后的解码器一律 `errors="replace"`；`_commit_utf8` **不接管**严格探测解码器
（它持有严格语义，之后遇杂散非法字节会抛），而是按已消费字节数把余量交给宽松解码器。

### 文件

| 文件 | 性质 |
| --- | --- |
| `src/agent_harness/sandbox/decoding.py` | 新增（`platform_fallback_encoding` + `StreamDecoder`） |
| `src/agent_harness/sandbox/local.py` | 改：`text=False`、每流一个解码器、`_drain_stream` 解码后入 cap、记录判定日志 |
| `src/agent_harness/sandbox/docker.py` | 仅注释（说明为何保持 UTF-8） |
| `tests/sandbox/test_output_encoding.py` | 新增 22 测试 |

### 验收对照（HANDOFF 的 5 条）

| 验收 | 落点 |
| --- | --- |
| 1. 先复现（GBK 字节走 sandbox 输出路径，落盘 JSONL 无 U+FFFD，当前必红） | `TestDurablePathHasNoMojibake`（红→绿：首跑 `ModuleNotFoundError`，修后 0 个 U+FFFD） |
| 2. 修后绿 | 全文件 22 passed；全量 1528 passed / 9 skipped |
| 3. 跨平台 | 兜底编码可注入（测试缝 `fallback_encoding="cp936"`），非 Windows 用 utf-8 |
| 4. 边界 | 多字节跨 chunk / 提交点切在汉字中间 / 判定后坏字节 / 末尾不完整序列 / 纯二进制 / 非法编码名 |
| 5. `docker.py` 同模式一并核 | 已核：**有意保持** UTF-8，注释说明理由 |

### 测试清单（22）

真实子进程路径（非 mock）：GBK 可读且无 U+FFFD、UTF-8 与原行为一致、纯二进制不崩、
**晚到坏字节不截断流**（70000×A + `\xff` + 尾标）、耐久面 JSONL 0 个 U+FFFD。
单元面：UTF-8 优先 / 非法序列回退 / 粘性 / 多字节跨 chunk / 提交点切在汉字中间 /
判定后坏字节保留剩余 / flush 收尾不丢尾字节 / 通用换行归一 5 例 / 非法编码名构造即报错 /
`_DRAIN_CHUNK_BYTES <= PROBE_LIMIT` 耦合锁。

### 证据强度（为什么可以信）

- **独立 code-review 复核**：P0/P1/P2 **零 finding**；4 项 P3 已全部闭环。
  复核用差分模糊测试（4000 组合法流 + 4000 组非法流与整串归一对拍，0 不一致）、
  穷举多字节跨界（`é`/`中`/`€`/`😀` 全偏移）、真实子进程跑通。
- **两次变异测试**，证明新回归锁非空洞：
  - 回退 P1 修复（判定后交回严格探测解码器）→ **3 个测试变红**；
  - 把 OEM 代码页退化成 `utf-8` → **1 个测试变红**（旧断言是空洞的，
    `codecs.lookup` 抛错而非返回 `None`，任何合法名字都能过）。

### 风险 / 未决

- **无已知数据迁移**：本次只保证**新增**输出不再乱码。**历史 JSONL 里已经固化的乱码**
  不在本次范围——按 HANDOFF 约定，若要修复必须是**独立的一次性迁移工具**
  （默认 dry-run + 备份），且需用户明确批准，**不得就地重写 JSONL**。
- `StreamDecoder.feed()` 的判定顺序依赖 `_DRAIN_CHUNK_BYTES <= PROBE_LIMIT`（已加注释 +
  测试锁）。若将来调大读取块，需同步调整，否则「已满上限的合法 UTF-8 + 同段坏字节」的
  判定会取决于坏字节落在哪一段。
- 本次**未**给 `ExecResult` 加「本次解码用的是什么编码」字段（只落了 debug 日志），
  以免扩大 API 形状。若集成 AI 希望 Web UI 能显示「本次输出解码可信度」，那是另一张票。

### 集成后建议核对

```bash
# 中文 Windows 上跑一次真实 cmd 报错，确认事件里没有 U+FFFD
uv run pytest tests/sandbox/test_output_encoding.py -q
# 内容哈希敏感的回归（新换行归一必须保持原样）
uv run pytest tests/agent/test_phase5_runtime.py -q
```

---

## 3. OBS-015：审批卡的 `catch` 乐观翻转（**feat/frontend**，非本分支）

**状态**：✅ 完成。**改动在 `feat/frontend`**，不在 `feat/backend`：
`cb0e008`（实现）+ `4580a69`（code-review 收尾：`.approval-error` CSS / tracker / 注释）
+ `274afcf`（本次收尾：404 语义订正 + 404 fail-safe 回归锁）。

### ⚠️ 重要：交接单里 OBS-015 的前提是**错的**，请勿按原文"修回"

交接单写的是「409/**404** 幂等已决 vs 其它错误保持 pending」。**404 不是幂等已决。**
后端 approve 端点的 404 有四个来源，全部**无法**与「已解析且已出队」区分
（`src/agent_harness/web/app.py:1157-1166`）：

| 后端异常 | HTTP | 含义 |
| --- | --- | --- |
| `ApprovalAlreadyResolved` | **409** | **幂等已决**（决策已生效）→ 唯一可翻卡片的错误码 |
| `SessionNotFound` | 404 | 会话不存在 |
| `ApprovalQueueMissing` | 404 | 审批队列缺失（run 已结束等） |
| `ApprovalRequestMissing` | 404 | `approval_id` 不在队列（可能是过期事件，也可能是已出队——**不可区分**） |
| `InvalidDecision` | 422 | 决策不在 `allowed_decisions` 内 |

把 404 当成功 = 决策其实**没有**生效却显示「已批准」——正是 OBS-015 本身要消灭的安全假象。
所以正确语义是：**只有 409 → 翻卡片；404/5xx/网络失败 → 保持 pending + 错误提示 + 可重试。**
「已经决」的真正兜底不靠错误码，而是 `permission/resolved` 投影事件把卡片移出待决队列。

### 本次收尾做了什么（零产品行为改动）

1. `web/src/lib/api.ts`：`postApproval` 的 docstring 原写「404 with "already resolved"
   detail = same semantics → AlreadyResolvedError」，与代码相反 → 已按上表改写。
2. `web/e2e/n-approval-card.spec.ts`：+1 用例 ×2 视口「**POST 404 → 保持『需要审批』**
   + 错误文案含 404 + 按钮仍可重试」。此前 404 路径**零覆盖**；变异验证（注入
   `if (404) throw AlreadyResolvedError`）→ 两视口变红，还原后全绿。
3. `docs/PROMPT_FRONTEND_NEXT_BATCH.md`：原文把错误前提写进任务与验收标准 → 加
   2026-09-11 订正块（保留原文 + 明确 404 不走已决）。

### 既有批次已锁定的部分（无需重复做）

- `ApprovalCard.tsx` catch：`AlreadyResolvedError` → 翻卡片；其它错误 → 保持 pending +
  `role="alert"` 提示 + 按钮重新可用（可重试）。
- e2e `n-approval-card.spec.ts`：**POST 500 → 保持 pending + 可重试（连点两次）**、
  **POST 409 → 翻「已批准」**、200 → 翻、`permission/resolved` → 移除卡片。
- 单测 `api.test.ts`：200/409/500/422 四例。
- 变异验证：还原旧「任何错误都翻卡片」→ 500 用例变红；禁用 `AlreadyResolvedError`
  分支 → 409 用例变红。

### 集成后建议核对

```bash
cd D:\intelligence-agent-frontend/web
npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build
# 门禁基线：vitest 501 passed / oxlint 35 warnings 0 errors / playwright 118 passed
```

---

## 4. OBS-012：`bash` 工具实为 cmd.exe / sh——工具描述诚实化

**状态**：✅ 完成，commit `d9bef3a`（分支 `feat/backend`，未 push）。

### 根因

工具名 `bash` 是历史名称，**没有任何后端真的调 bash**：

| 后端 | 实际机制 | 真实解释器 |
| --- | --- | --- |
| `LocalSubprocessSandbox`（Windows） | `Popen(shell=True)` → CPython 用 `%COMSPEC%` | `cmd.exe` |
| `LocalSubprocessSandbox`（POSIX） | `Popen(shell=True)` → CPython 用 `/bin/sh` | `/bin/sh` |
| `DockerSandbox` | 硬编码 `["/bin/sh", "-lc", command]` | `/bin/sh` |

模型按工具名写 bash 语法，会被真实解释器**直接拒绝**：本机实证 cmd.exe 对 bash 语法报
「此时不应有 i。」——OBS-011 的乱码复现正是这条报错，整次工具调用作废。

规范面：`05_SANDBOX_CODING_TOOLS.md` §117 只规定 bash 工具返回 exit_code/stdout/stderr，
**对 Windows/shell 选择无任何要求** → 这是代码诚实性问题，不是规格冲突。

### 修法（不改执行语义，只让声明与真相一致）

> ⚠ 本节最初写的是 property `shell_description: str`（commit `d9bef3a`）。**深化提交
> `9fe0809` 已把它改名为 `shell_environment: ShellEnvironment(name, family)`**——名字
> 与语法家族必须一起声明，否则消费方只能靠 `"cmd" in name` 子串嗅探重新推导行为
> （知识漏过 seam），且「名字是 cmd、家族按 POSIX」的不一致无法表达。下面按**最终**
> 形状记录；历史形状见 `d9bef3a`。

1. `Sandbox` 新增**非抽象** property `shell_environment`（**不进 ADR-0001 冻结的
   6 个抽象方法契约**——抽象化会让既有/第三方后端无法实例化）。基类保守默认
   `ShellEnvironment(name="sh", family=ShellFamily.POSIX_SH)`。
2. `LocalSubprocessSandbox` → `%COMSPEC%` 的 basename（剥离可能的引号、空值回落
   `cmd.exe`）+ `family=CMD`；`DockerSandbox` → `("/bin/sh", POSIX_SH)`（与 exec 一致）。
3. `BashTool.description` 按 Sandbox 的声明如实写出解释器名并否认 bash；**按
   `family is CMD`（不是子串）**追加 cmd 专有陷阱（单引号非引用符 / `$VAR` 不展开 /
   `cat`·`ls` 不可用 / `2>/dev/null` 无效）。
   **不用 `os.name` 猜**：宿主是 Windows 时 Docker 容器内仍是 sh。

### 交付物

| 文件 | 性质 |
| --- | --- |
| `src/agent_harness/sandbox/base.py` | 新增 `ShellFamily` / `ShellEnvironment` + 非抽象 property `shell_environment` |
| `src/agent_harness/sandbox/local.py` | 覆写：COMSPEC basename + `CMD` / `("/bin/sh", POSIX_SH)` |
| `src/agent_harness/sandbox/docker.py` | 覆写：`("/bin/sh", POSIX_SH)` |
| `src/agent_harness/sandbox/__init__.py` | 包级导出 `ShellEnvironment` / `ShellFamily` |
| `src/agent_harness/tools/bash.py` | `description` 按 `family` 合成（含 cmd 陷阱） |
| `tests/tools/test_coding_tools.py` | `TestBashToolShellHonesty`（11 例，1 例平台跳过，含 family-not-name 锁） |
| `tests/agent/test_context_runtime.py` | `Mock(spec=Sandbox)` 显式声明 shell（假件补全） |

### 门禁与证据

- ruff clean；全量 pytest **1537 passed / 10 skipped / 39 deselected / 0 failed**。
- 变异验证：① 还原旧描述 → **3 个用例变红**；② 把 Local 硬编码成 `"cmd.exe"` →
  「取自 COMSPEC」用例变红（该用例注入**带引号的独有值** `"C:\opt\weird\mystery-shell.exe"`，
  同时锁住引号剥离——初版断言「与 COMSPEC 相等」在本机无法区分硬编码，已按独立复核意见加强）。
- 独立 code-review：**SOUND / approve，零 P0/P1/P2（本 scope 内）**。复核实证
  `shell=True` 在本机确实走 cmd.exe（`echo %OS%`→`Windows_NT`、`ver`→Windows 版本串），
  并确认改描述**不破坏任何工具 schema/提示快照**（无测试断言该文本）。

### 有意未做（附理由）

- **不真去调 bash**（不探测 Git Bash / WSL）：宿主依赖强、Alpine/Debian 精简镜像无 bash、
  且属执行/安全语义变更，超出 OBS-012 scope。
- **不改工具名 `bash`**：`"bash"` 是载荷（`profiles.py:_CODING_TOOLS`、前端
  `ToolCard`/`StepDetail` 按 `tool.name === 'bash'` 渲染、审批/权限测试、已落库 SessionEvent
  工具名）——改名是跨端破坏性变更。
- 两项 P3 保留（已在提交说明与复核中记录理由）：基类默认 `"sh"` 可能被忘记覆写的第三方
  后端误用（有 docstring 声明，且当前两个具体后端都覆写）；`"cmd" in shell.lower()` 是宽松
  子串门（`tccmd.exe` 误触发无害；COMSPEC 指向 PowerShell 时描述诚实但无语法提示）。

## 5. OBS-016（本轮新发现，**未修**，Scope 外）：`ReadTool` 的超长行提示仍教模型用 POSIX 专有命令

**位置**：`src/agent_harness/tools/read.py:140`。

单行超过 `_READ_MAX_BYTES` 时，ReadTool 往模型可见的 `content` 里追加：

```text
Use bash with 'sed -n '{start}p' <file> | head -c {_READ_MAX_BYTES}' plus 'tail -c +N' to read further segments.
```

在本机（Windows 本机 → cmd.exe）`sed` / `head -c` / `tail -c` **都不存在**，cmd.exe 会回
`'sed' is not recognized...`。这与 OBS-012 是**同一类缺陷**（模型可见文案描述了一个不存在的
解释器环境），目标场景同样会复现。

**为什么本轮未顺手修**：① 属另一个工具（ReadTool），不在 OBS-012（bash 工具描述）scope 内
（AGENTS.md §8 Scope Lock）；② 该字符串被前端 handoff 文档 `docs/HANDOFF_FRONTEND_SYNC.md:46`
当作契约引用，改它需要跨端同步。**独立复核也建议只报告不修**。

**建议的最小修法**（交给集成 AI 排期）：把该提示改成后端无关的表述（如「用 shell 工具按
字节/行切片读取后续内容」），或按 `sandbox.shell_environment`（`name` 显示 / `family`
决定语法）给对应平台的示例；若采用后者，
需同步 `docs/HANDOFF_FRONTEND_SYNC.md:46`。

---

## 6. OBS-013：模型退化重复循环（**登记为已知风险，无代码改动**）

**状态**：✅ 评估完成 → **登记为已知风险**（交接单给的第二个选项：「或登记为已知风险 +
用户可见停止路径」）。**本轮无产品代码改动**，故无 ruff/pytest/code-review 适用于本项——
这里给出的是证据化的结论与建议，不伪造门禁。

### 现象（原始记录，`docs/FRONTEND_ISSUES_LOG.md` OBS-013）

会话 `7d5a6f24` 一轮生成 **2,868 个 `text/delta`、共 186,507 字符**，内容为
`"Let me run the command."` 的无限重复，**始终未发出工具调用**，持续 **3.5 分钟**后由用户
点「停止」收口（`model/failed: model call cancelled`）。同语料另有多次
`model/fallback: deepseek-v4-flash-0731 → glm-4.5-air · InternalServerError`。

### 评估结论：**限时护栏已存在、已启用、且已按同一病理测过**——本次没触发是因为没到阈值

| 问题 | 证据 |
| --- | --- |
| 有无限长护栏？ | **有**。`model/stall.py::stream_with_stall_guard` 双守卫：`idle`（N 秒无新 chunk）与 **`total`（整条流总时限）**。模块 docstring 明确写了 `total` 就是为「chunk 间隔只有 ~2s、idle 永远不触发」的慢滴漏而设。 |
| 生产启用了吗？ | **是**。`config.py:31-32` 默认 `model_stream_idle_timeout=60.0`、**`model_stream_total_timeout=600.0`**；`assembly.py:251-252,284-285` 注入 `AgentFactory` 与 `AgentRuntime`（生产装配路径，非测试专供）。 |
| 为什么这次没拦住？ | **3.5 分钟（210s）< 600s**。退化重复是**持续有 chunk 到达**的流，所以 60s 的 idle 永不触发（每个 delta 都重置它），只有 600s 的 total 能治——它没到期，用户先手动停了。 |
| 这个病理测过吗？ | **测过，且正是同一形状**。`tests/model/test_stall_watchdog.py::TestTotalDeadlineGuard`：`test_slow_drip_hits_total_deadline`（每 0.05s 滴一个 chunk、永不结束 → total 到期抛 `ModelStallError(kind="total")`）、`test_slow_drip_primary_switches_to_fallback`（**断流后 fallback 接管，transition reason=ModelStallError**）。 |
| 有用户可见停止路径吗？ | **有，且本次实测有效**：用户点「停止」→ run 以 `model/failed: model call cancelled` 收口。Web 侧走 `POST /api/sessions/{id}/cancel`。 |
| 有可观测信号吗？ | **有**：`MODEL_FALLBACK` 是 durable 事件；stall 中断会记 fallback transition（`reason=ModelStallError`），JSONL 可检索。 |

**因此暴露面是有界的**：最坏情况 = 至多 600s 的退化输出，然后 total 到期 → 判为瞬时 →
**fallback 接管**（换模型，对「退化重复」恰好是对症的——另一个模型通常不会同样复读）；
若 fallback 链也退化到超时，run 以失败收口。期间用户随时可停。

### 为什么不按「重复护栏」实现一个内容级启发式

1. **误杀风险**：合法的长输出天然含重复模式（大表格、重复样板代码、逐行日志）。按「重复率」
   中断会误杀正常生成，而这类误杀的代价（截断用户要的产物）通常高于一次可手动停止的复读。
2. **层次错误**：退化重复是 **provider/模型行为**，在 Agent Loop 里加内容特判违反本项目
   「不为 provider 行为在 Loop 里开特判」的一贯原则（不变量 #18 同族）。
3. **已有更对的层**：真要收紧，位置是 provider 请求参数（见下），不是 Loop 启发式。

### 唯一确认的**真实缺口**（建议，未实施——需产品/运维决策）

`create_chat_model`（`model/provider.py:106-113`）显式声明了 `request_timeout=300`、
`max_retries=0`，但**全仓没有任何 `max_tokens`**（`grep max_tokens src/` 为空）。即：
**生成长度本身无上限**，唯一的界是 600s 的**时间**上限。

- 可选加固：给 `create_chat_model` 传 `max_tokens`（最好来自 Settings，缺省不设 = 行为不变）。
- **为什么不当场改**：① 需要按模型选值（各 provider 语义/上限不同，`max_tokens` 与
  `max_completion_tokens` 还不通用）；② 值定小了会把「写一个长文件」这类**合法**长输出截断，
  属产品行为变更；③ 属 §9.1「显著改变行为」的决策，应由用户/集成 AI 拍板，不在本项 scope 内
  顺手加。
- 另一个可选旋钮：把 `model_stream_total_timeout` 从 600s 调低（纯配置，无需改代码）——
  代价同样是可能打断合法长生成（这正是 V1 明确不做 ainvoke 总时限的原因，见 `stall.py`
  docstring；流式路径才选了 600s 这个折中）。**不建议默认调低**，建议留给运维按需覆盖。

### 记录在案的副作用（非缺陷）

退化输出会被**持久化**：`TEXT_DELTA` 在 `EVENT_TYPES` 内（ADR-0016 §3.1 把「合帧后的
text/delta」定为 durable，禁止的是 per-token 行）。所以一次退化 run 会往 append-only JSONL
写入约 O(100KB) 的重复文本，且**不可逆**。这是**有意设计**（回放保真，不变量 #22：不制造
第二套不可对账的真相），不是 bug；它的界同样只有 600s 超时。若要避免，应连同上面的
「长度上限」一起决策，而不是单独截断 durable 事件（那会破坏回放对账）。

### 给集成 AI 的行动项

1. **接受本项为已知风险登记**（无需改代码）；把「≤600s + 自动 fallback + 用户可停」写进
   已知风险清单。
2. 若要进一步收紧：**单独立项**决定 `max_tokens`（含按模型选值与截断策略），不要塞进本批次。

---

## 7. OBS-009/014：TIMEOUT 的 `retryable` 语义 + 文案矛盾

**状态**：✅ 完成，commit `9807928`（分支 `feat/backend`，未 push）。**纯文案修复，零重试行为改动。**

### 现象（前端实机记录 OBS-009/014）

`bash {"command": "sleep 10 && echo MARKER-A1"}` → `tool/result`：
`{"ok":false,"error_code":"TIMEOUT","retryable":false,"metadata":{"attempt":1,"max_attempts":3,"duration_ms":10002.6}}`。
`sleep 10` 与 `Tool.timeout_seconds` 默认 **10.0s** 贴边，必然越界。前端指出两点：
① `retryable:false` 对超时是否合适；② message 写「可稍后重试」而 `retryable:false`，「读起来略冲突」。

### 结论一：`retryable` 语义**本来就是对的**，且**已被既有测试锁定**（无需改）

`retryable = tool.side_effect is not ToolSideEffect.MUTATING`（`executor.py`）：

| 工具类型 | 超时后 `retryable` | 理由 |
| --- | --- | --- |
| READ_ONLY | **True** | 超时是暂时的，重跑无副作用风险 |
| MUTATING（bash 即此类） | **False** | 第 1 次尝试的**副作用状态未知**（进程可能仍在跑、写可能已落盘）→ 不盲重跑（不变量 #14） |

既有用例 `tests/tooling/test_executor.py::test_mutating_tool_timeout_is_not_auto_retried`
已断言「MUTATING → False 且 `attempt==1`」「READ_ONLY → True」。所以前端的第一点是**设计取舍，
不是缺陷**：TIMEOUT 并非「一律不重试」，而是按副作用分类。

### 结论二：真正的缺陷是**文案**——已修

旧文案对 MUTATING 也说「可稍后重试」，而 `retryable=False`。这不只是「读起来冲突」：它是
**模型可见的指令**，等于教模型盲重跑一个副作用状态未知的命令（违反不变量 #14）。实机观测到的
「长命令超时 → 反复重试 / 退化」正被这句话推动（与 OBS-013 组合失效）。

修法（`executor.py` 的 `except TimeoutError`）：

- READ_ONLY（可重试）→ 保留「可能是外部依赖暂时无响应，可稍后重试。」
- MUTATING（不可重试）→ 改为：该工具被判定为**有副作用**（bash 无法静态区分只读、远端工具的
  影响也可能不在 workspace 内）、本次执行的**副作用状态未知**（命令可能仍在运行，或已部分
  生效）、**不要直接重跑**，并给安全纠错路径（先确认当前状态，或把操作拆成不超过 `limit` 秒的
  更短步骤）。`limit` 用变量插值，将来调超时会自动跟着更新。
- 措辞**不写死「会改动 workspace」**：MUTATING 是保守分类（bash 即使 `ls` 也是 MUTATING），
  且 MCP 工具的副作用可能在远端（如 GitHub）——对本机只读命令与远端工具都是假陈述
  （按独立复核 P3-1 修正）。
- 注释里对 Recovery 的类比也修正了：run 内超时按终态 `FAILED` 落盘、**不**产生
  `NEED_RECONCILE`；`UNKNOWN` / `ReconcileCallback` 是**崩溃恢复**侧的对应机制（同源不同触发面）。

### 交付物与门禁

| 项 | 内容 |
| --- | --- |
| `src/agent_harness/tooling/executor.py` | 超时文案按 `retryable` 分支（唯一产品改动） |
| `tests/tooling/test_executor.py` | 新增 `test_timeout_message_matches_the_retry_decision`；只读对照组提升为模块级 `_SlowReadTimeoutTool`（消重） |
| 门禁 | ruff clean；全量 pytest **1538 passed / 10 skipped / 39 deselected / 0 failed** |

**变异验证**：把 hint 改成不分支（还原旧行为）→ 新用例变红。独立复核另跑两向变异（只读文案
无条件化 / MUTATING 文案无条件化）均变红，并验证强制 `retryable=True` 会让两个超时用例同时变红。

**独立 code-review**：**SOUND / 零 P0/P1/P2**。确认 message-only（无重试行为变化）、文案无下游
依赖（前端 `toolShapes.ts` / `projection.ts` 只读 `error_code`，不解析 message），并确认
`retryable=False` 是正确设计而非缺陷。3 项 P3 处置 2 项（措辞 + 注释），第 3 项即本文档收尾。

### 未改（Scope 外，建议单独立项）

**`Tool.timeout_seconds` 默认 10.0s 与 sandbox `DEFAULT_EXEC_TIMEOUT` 60.0s 不一致，且前者生效**
（`asyncio.timeout(tool.timeout_seconds)` 包住 `execute`，sandbox 的 60s 对 bash 经 Executor 实际不可达）。
对安装/构建/`pytest` 这类合法长命令**偏紧**——一个 coding agent 跑不了超过 10 秒的测试是真实能力限制。
但放宽会拉长挂死命令的最坏停顿（且 MUTATING 调用会串行化整批），属**产品/行为决策**，
应单独立项（`BashTool.timeout_seconds` 覆写为多少、是否随 sandbox 走），不塞进本次文案修复。
取消路径本身是安全的（`bash.py` 在 `CancelledError` 时置 `cancel_event`，`local.py` 击杀进程树）。

---

## 8. OBS-008：模型调用失败吞掉 traceback

**状态**：✅ 完成，commit `0fceccc`（分支 `feat/backend`，未 push）。

### 根因

设计上 durable 的 `model/failed` 事件**只带异常类型名**（`"model call failed: TimeoutError"`）
——这是脱敏不变量：provider 回显的文本不得进 append-only SessionEvent 历史。
代码 docstring 声称「完整消息只进结构化日志」，**但顶层失败臂实际只记了
`error=str(error)` + `error_type`，从不记 traceback**。于是排障信息只剩一个类型名：
「哪一帧、哪个 SDK 调用挂的」全丢。docstring 与实现不符。

### 修法（`src/agent_harness/agent/runtime.py`）

1. `_log()` 增加显式 keyword-only `exc_info: bool = False` 并转发给 `log_event`
   ——`logging.py::JsonlFormatter` **早已**支持 `record.exc_info` → `stack_trace(调用栈)`，
   只是从没有人传过这个旗标（一个「机制齐备、接线缺失」的典型）。
2. 顶层失败臂 `Agent Loop 异常终止` 传 `exc_info=True`。
3. 同类收尾：两处「取消收尾 / 失败兜底事件写入失败（存储故障？）」也补 `exc_info=True`
   （独立复核 P3：同属「吞 traceback」缺陷类；两处都在 except 块内，捕获的是正确异常）。
4. 两处 docstring 的「完整消息只进结构化日志」改为「完整消息**与调用栈**」，与实现一致。

### 实测证据（真实 `cli.run` + `FailingModel.astream` 抛 `TimeoutError` → 读 `logs/agent.jsonl`）

日志出现完整调用链，19 行 `stack_trace(调用栈)`：

```text
File "...\src\agent_harness\agent\runtime.py", line 633, in _drive
File "...\src\agent_harness\model\fallback.py", line 188, in astream
File "...\src\agent_harness\model\concurrency.py", line 45, in gated
File "...\src\agent_harness\model\stall.py", line 87, in stream_with_stall_guard
File "...\Lib\asyncio\tasks.py", line 507, in wait_for
TimeoutError: 模型请求超时
```

durable 事件仍严格是 `{"message": "model call failed: TimeoutError"}`（脱敏不变量完好）。

### 交付物与门禁

| 项 | 内容 |
| --- | --- |
| `src/agent_harness/agent/runtime.py` | `_log` 转发 `exc_info`；顶层失败臂 + 两处收尾臂传 `exc_info=True`；docstring 对齐 |
| `tests/test_structured_logging.py` | 扩展 `test_minimal_agent_failure_chain`：断言 `stack_trace(调用栈)` 非空且含 `Traceback (most recent call last)` / `TimeoutError` |
| 门禁 | ruff clean；全量 pytest **1538 passed / 10 skipped / 39 deselected / 0 failed** |
| 变异验证 | 去掉 `exc_info=True` → 该用例立即变红（`stack_trace` 为 `None`） |

**独立 code-review**：**SOUND / 零 P0/P1/P2**。复核独立复现并给出完整帧链，并确认：
① durable 事件脱敏不变量完好（provider 回显密文只进诊断日志，不进 SessionEvent /
Langfuse / Web UI）；② Python traceback **不**捕获局部变量；③ `_log` 签名变更零碰撞
（12 处调用无一把 `exc_info` 当数据字段，无 `**` splat）；④ 生产两个入口
（`cli.py` 8 处 `setup_logging`、`web/app.py` lifespan）都配了 handler。

### ⚠ 集成时须知（复核 P3-1）

调用栈会带**绝对路径（含宿主用户名）、源码行、以及链式异常（`__cause__`/`__context__`）
的消息**——比原先多。诊断 JSONL 是本地未脱敏详情汇聚处（不变量 #4：Event ≠ Diagnostic Log），
但**不要原样附到 issue / 上传**；需外发先脱敏。已在 `_log` docstring 注明。

### 复核提出但核实为**非问题**（记录以免重复怀疑）

`runtime.py:571` 把 `str(error)` 写进 durable 的 `RUN_FAILED` 事件，看起来像脱敏不一致。
已核实：该错误是 `ContextWindowExceededError`，消息全部**本地拼装**（token 计数、
`"No complete early turn can be compacted"`、`"Summary request exceeds hard guard"`），
**不含 provider 回显**，写进事件既安全又有用（token 数字解释了失败原因）。不登记为问题。

---

## 9. OBS-010：`GET /api/sessions` 的 `trace_id` 恒 null

**状态**：✅ 完成，commit `499dc3d`（分支 `feat/backend`，未 push）。

### 根因

`SessionSummary.trace_id` 是 Gap 2 契约，前端 `types.ts` 也早已声明该字段——但
**没有任何后端代码从事件流里取值**。而 Langfuse 开启时 run 终结事件的
`data.trace_id` 一直是真实值（ADR-0018 D7：`run/completed.data.trace_id` 回填真实
Langfuse trace id）。字段存在、真值存在，中间缺一根接线：列表页恒 null，
「点击跳 Langfuse」入口是死的。

### 修法

| 文件 | 改动 |
| --- | --- |
| `session/store.py` | `SessionSummaryStats` 新增 `trace_id`；新增 `_terminal_trace_id`（取值 + 守卫，快路径与 `_summary_fallback` **共用**）——深化提交 `08d92f5` 又删掉了临时的 `_terminal_trace_id_from_tail` / `_last_event_time_from_tail`（前者被共用方法取代，后者不可达），并把末行解析收敛为一次 |
| `session/service.py` | `list_sessions` 每行透传 `trace_id` |
| `web/app.py` | `SessionSummary.trace_id` 映射 + docstring 订正 |

取值规则：**末事件恰为 run 终结事件**（`run/completed|failed|interrupted`）时取
`data.trace_id`；非终结类型 / `null` / 空串 / 非字符串 → `None`（不把磁盘上被改坏的
值塞进 API 契约）。

### 两条路径同口径（不变量：扫描与全量严格一致）

- 快路径：末行**只解析一次**得到 `last_event`，`last_event_time` 与 `trace_id`
  同源于它（`08d92f5` 起）。
- 全量回退 `_summary_fallback`：取 `events[-1]`（`read_events` 已剔除坏行）。
- `trace_id` 的规则由单一方法 `_terminal_trace_id` 拥有，两条路径各自把末事件传给
  它——所以**该规则**的一致性是结构性的（`test_fast_path_agrees_with_full_parse_on_clean_session`
  与 `test_each_line_is_parsed_at_most_once` 直接锁住）。
  `last_event_time` 仍是两条独立取值路径（各自取「末事件的时间」），由同一个测试
  断言其相等，而非共用实现——不要把它读成「所有字段都结构共享」。
- 两者都只认**末事件**，这是有意的（见下）。

### ⚠ 已知边界 = 有意的性能取舍（**不要「顺手修」成全量扫描**）

只认末事件、不向历史回溯，因为回溯要逐行 `json.loads` 到 EOF，正好抵消
`read_session_summary` 的快路径（列表页从秒级全量解析压到几十 ms）。后果：

| 情形 | `trace_id` | 说明 |
| --- | --- | --- |
| 末事件是 `run/completed/failed` 且带 trace | 真实 id | 主路径 |
| 上一轮已 completed，本轮的 `user/message`/`run/started` 垫在末尾 | `null` | 在途 run 尚无最终 trace，显示「未追踪」属诚实降级 |
| `run/interrupted`（recovery 补记，data 只有 `interrupted_seq`+`reason`） | `null` | 崩在半途的 run 在 Langfuse 没有可跳转的最终 trace，不伪造（不变量 #21） |
| Langfuse 未启用（终结事件 `trace_id` 本就是 null） | `null` | 预期降级，前端显示「未追踪」灰字 |

第二行是两轴 code-review 共同指出的张力点：若产品希望「上一轮的 trace 在新轮期间
仍可点」，需要一张**独立**的票来权衡（把快路径改回全量解析，或引入每会话末次
trace 的侧车存储）——**不要**在 OBS-010 里偷偷改成回溯扫描。取舍已写进
`_terminal_trace_id` docstring（`08d92f5` 起该方法即唯一 owner）与对应测试注释。

### 测试（15 例）

- `tests/session/test_session_robustness.py` +12：completed/failed 回填、Langfuse
  未启用、末事件非终结、非终结类型带 trace、`run/interrupted` 真实形状、非字符串
  5 参数（`123`/`""`/`None`/list/dict）、头部损坏触发 fallback 时同口径。
- `tests/session/test_service.py` +2：服务层透传 / 无 run 终态为 `None`。
- `tests/test_web_api.py` +1：`/api/sessions` payload 回填 + 在途为 `null`。

### 门禁与变异验证

- ruff clean；全量 pytest **1553 passed / 10 skipped / 39 deselected / 0 failed**
  （= 1538 基线 + 15 新增）。
- 变异验证 5 组（全部已还原）：
  1. 快路径返回 `None` → 4 用例红（含 service/web）；
  2. `_terminal_trace_id` 返回 `None` → 5 用例红（含 fallback 口径锁）；
  3. 去掉字符串/空值守卫 → 4 参数用例红；
  4. 去掉终结类型守卫 → 非终结类型用例红；
  5. 向历史回溯找带 trace 的终结事件 → 「末事件非终结」用例红。

### 双轴 code-review 结论

- **Spec**：无 scope creep；`run/interrupted` → `None` 与「不伪造」一致（已核实
  `recovery/scan.py:163` 确实不写 `trace_id`）；跨轮可用性是判断项，已按上表取舍
  并文档化，可另立票。
- **Standards**：无硬性违规；两项 judgement call 保留——末行多解析 1 次（复用会
  加宽 helper 签名）、`trace_id` 是 `SessionSummaryStats` 唯一带默认值的字段
  （默认 `None` 语义正确，且三处构造均已接线）。

### 未决（Scope 外，仅报告）

前端 `types.ts::SessionSummary` 还声明了 `trace_url: string | null`（契约 `2d7f87a`），
但后端列表 `SessionSummary` **未返回**该字段 → 运行时为 `undefined`。当前前端
`SessionList` 未消费该字段，无可见影响；属 OBS-010 scope 外的另一张票
（OBS-010 行只要求 `trace_id`；`BACKEND_PROMPT_TRACE_URL.md` 是 per-run 事件契约，
不覆盖列表）。

### 集成后建议核对

```bash
# 聚焦回归（15 例）
uv run pytest tests/session/test_session_robustness.py tests/session/test_service.py tests/test_web_api.py -q -k "trace_id"
# 或全量
uv run ruff check src/ tests/ && uv run pytest -q
```

---

## 10. 架构深化三连（批次收尾时新增，**纯结构重构、行为不变**）

**状态**：✅ 三项全部完成，✅ **已同步 `origin/main`，等待集成**。

同步记录（§14.6 先回后正）：`origin/main`（`63db650`，35 个提交）已合入
feat/backend，**零冲突**，merge commit **`f9c3675`**。合并后门禁逐字不变：
ruff clean、pytest **1563 passed / 10 skipped / 39 deselected / 0 failed**；依赖未变
（无需 `uv sync`）；main 侧未改任何 `src/` 文件 → 三个重构与集成基线无源码交集。
**集成方请以 `f9c3675` 为合并对象**（而非 `81c5633`）。

来源是批次收尾的架构扫描（报告为临时产物，未入库）。三项都是
behavior-preserving 重构，**不改任何线上契约**。

| 候选 | commit | 改动 | 一句话 |
| --- | --- | --- | --- |
| 1. summary 快路径的末行只解析一次 | `08d92f5` | `session/store.py`（+ `web/app.py` 1 行注释） | 删掉不可达的 `reversed(tail)` 分支与 `deque(maxlen=2)`；`_terminal_trace_id` 成为唯一取值 owner |
| 3. 执行环境事实 = (名字, 家族) | `9fe0809` | `sandbox/{base,local,docker,__init__}.py` + `tools/bash.py` | `shell_description: str` → `shell_environment: ShellEnvironment`；BashTool 不再子串嗅探 |
| 2. 失败映射收成值对象 | `7113d06` | `tooling/executor.py` | `_ToolFailure`（error_code+retryable+message 同源）；重试循环两个 except 臂各一行 |

**合并冲突面**：候选 3 **改了一个 property 名**（`shell_description` →
`shell_environment`，新类型 `ShellFamily` / `ShellEnvironment` 从 `sandbox` 包级导出）。
两步（`d9bef3a` 引入 / `9fe0809` 改名）都在本分支内、**均未合入 main**，所以不存在
外部消费方；但若你的交接单/笔记里写的是 `shell_description`，以 `shell_environment`
为准（本文件 §0/§4/§5 已同步订正）。

**门禁**：ruff clean；三连之后全量 pytest **1563 passed / 10 skipped / 39 deselected /
0 failed**（= OBS 批次基线 1553 + 候选1 两例 + 候选3 一例 + 候选2 七例）。

**双轴 code-review 结论（Standards + Spec 独立子代理）**：**零 P0/P1/P2**；
`message` 文案逐字节不变、`error_code`/`retryable` 取值不变、既有用例零改动通过
（这就是「行为不变」的证据）。两条**有意未采纳**的建议在此留痕，避免下轮重复提出：

1. *「失败值对象应连 attempt 记录一起产出」*——**不采纳**：attempt 记录对**每次**
   尝试都写（含成功），失败值对象不覆盖成功路径；且它逐字段复制
   `result.error_code` / `result.retryable`，本身不可能与结果不一致。把计时/观测塞进
   纯映射会把职责搞混。
2. *「应新增 `_TailView` 类」*——**不采纳**：候选的收益（parse-once、删死支、
   两路径同口径可测）已用局部变量 + 共享的 `_terminal_trace_id` 全部拿到，并由
   `test_each_line_is_parsed_at_most_once` / `test_fast_path_agrees_with_full_parse_on_clean_session`
   锁住；再包一个只有两个字段、零行为的类属投机抽象（§9.2）。

**已知边界（候选 1 遗留，非缺陷）**：`last_event_time` 仍是两条各自取值的路径
（快路径取末行时间 / 全量取 `events[-1].time`），只由上面那个「两路径相等」的用例
断言，而非共用实现——不要把 `_terminal_trace_id` 的「结构性一致」误读成所有字段都
结构共享（docstring 已按此措辞订正）。

### 集成后建议核对

```bash
uv run ruff check src/ tests/ && uv run pytest -q
# 深化三连的聚焦回归（108 passed / 1 skipped）
uv run pytest tests/session/test_session_robustness.py tests/tooling/test_executor.py \
  tests/tools/test_coding_tools.py tests/agent/test_context_runtime.py -q
```
