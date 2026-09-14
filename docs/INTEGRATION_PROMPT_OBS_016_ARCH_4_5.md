# OBS-016 + ARCH-4/4b/5 集成提示词（集成 AI 执行手册）

> **收件人**：集成 AI（Git Integrator 角色，AGENTS.md §14）
> **任务**：把 `feat/backend` 与 `feat/frontend` 的本批成果合入 `main` 并完成验证
> **红线**：永不 force-push / rebase / reset --hard；凭据零泄漏（`.env` 值不进任何输出/提交）；
> 每次合并动作前确认 worktree 与分支（§14.2）；冲突后**立即停止**自动解决并按 §14.7 逐文件分析；
> 一次只合一个分支（§14.9：先 backend → main 验证完，再重新分析 frontend）。
> **本文件状态**：**4 票全部完成**（OBS-016 / ARCH-4 / ARCH-4b / ARCH-5），全部已关单、
> 全部未 push（集成 AI 执行合并）。逐票细节见 §1–§4；集成顺序见 §5。

## 本批总表

| 票 | issue | 后端 commit | 前端 commit | 状态 |
| --- | --- | --- | --- | --- |
| OBS-016 read 超长单行提示去 POSIX 专有命令 | #141 | `aa29562` | `1fac807` + `43b9ffd` | ✅ 跨端完成 |
| ARCH-4 `list_sessions` 返回领域 dataclass | #143 | `2ea83d4` | —（纯后端） | ✅ 完成 |
| ARCH-4b `/api/sessions` 补 `trace_url` | #142 | `a0f86a4` | `4c38c69` + `ef3f7c8` | ✅ 跨端完成 |
| ARCH-5 领域异常→HTTP 映射单源化 | #144 | `87fc388` | —（纯后端） | ✅ 完成 |

（另有各票的 docs commit：PHASE_STATUS / 本文件 / 前端 tracker，见各 § 末尾。）

---

## 0. 机器现状（以 `git -C <path> log -1` 为准，合并前复核）

| 用途 | 目录 | 分支 | 本批 tip |
| --- | --- | --- | --- |
| 集成主战场 | `D:\intelligence-agent` | `main` | 以实际为准 |
| 后端施工区 | `D:\intelligence-agent-backend` | `feat/backend` | 以移交时 `git log -1` 为准（本批最后一票 `87fc388` + docs commit） |
| 前端施工区 | `D:\intelligence-agent-frontend` | `feat/frontend` | 以移交时 `git log -1` 为准（本批最后一票 `ef3f7c8`） |

- **拓扑**：`D:\intelligence-agent-frontend` 是**独立 clone**（自带 `.git`），不是 worktree；`D:\intelligence-agent-backend` 才是 worktree。
- **origin/main 基线**：本批开始时两 clone 都看到 `63db650`。
- **前端相对 `origin/main`**：基线 `274afcf` 是 `63db650` 的**严格祖先**；本批在其上加 4 commits（OBS-016 两个 + ARCH-4b 两个）。两边**改动文件集不相交**（main 那 18 个 commit 只动 backend 与 `docs/PHASE_STATUS.md`，本批前端只动 `web/src/lib/`、`web/e2e/*.spec.ts` 与会话 docs）→ 合并预期零冲突，但**仍需按 §14.9 顺序做，且后端合入后重新 `fetch`/`diff`/`merge-base` 再判前端**。
- **⚠ 后端内部的重叠改动**：ARCH-4（#143）与 ARCH-4b（#142）都改 `session/store.py` + `web/app.py` 的同一区域
  （「改返回类型」与「增加字段」正交）。两票已在 `feat/backend` 上先后提交、**无冲突**；集成 AI 只需按顺序
  快进即可，但若单独 cherry-pick 其中一票，需注意另一票的上下文依赖。

---

## 1. OBS-016（#141）：read 超长单行提示去掉 POSIX 专有命令 —— ✅ 已完成（跨端）

### 1.1 问题

`ReadTool` 在「单行本身超 50KiB 字节帽」时给出的续读指引是：

```text
[Line {n} truncated at 51200 bytes. Use bash with 'sed -n '{n}p' <file> | head -c 51200' plus 'tail -c +N' to read further segments.]
```

本机真实解释器是 cmd.exe（Windows；见 OBS-012），`sed` / `head -c` / `tail -c` **都不存在** ——
模型照提示做会拿到 `'sed' is not recognized`，整次工具调用作废。与 OBS-012 同一缺陷类
（模型可见文案描述了一个不存在的解释器环境）。规范面：`05_SANDBOX_CODING_TOOLS.md` 对提示
文案无要求 → 代码诚实性问题，**非规格冲突**。

### 1.2 跨端契约（本票的关键约束）

标记前缀 `[Line {n} truncated at {bytes} bytes` 与结尾 `]` 是前端解析契约：

```ts
// web/src/lib/toolShapes.ts:30
const LINE_TRUNCATED_RE = /\[Line (\d+) truncated at (\d+) bytes[^\]]*\]\s*$/;
```

`[^\]]*` 吞掉尾部 → **改措辞不破坏解析**，需要同步的只是 fixture 与文档，不是解析逻辑。
因此本票**未改** `toolShapes.ts` 的任何逻辑。

### 1.3 后端改动（`D:\intelligence-agent-backend` @ `feat/backend`）

**commit `aa29562`**

| 文件 | 改动 |
| --- | --- |
| `src/agent_harness/tools/read.py` | `giant_line` 分支正文改为**点名真实存在的工具标识符**（`bash` / `grep`），不点名任何命令：解释器与其陷阱由各工具自己的描述声明（OBS-012）。同分支的陈旧注释（写「标记改用 bash 建议…（sed/head 取片段）」）一并订正。 |
| `tests/tools/test_coding_tools.py` | 新增三条断言：① 前端解析契约（正则取 `(line, bytes) == (1, 51200)` + 结尾 `]`）；② 词边界 `\b(sed|head|tail)\b` 不得出现（避免误伤 `used`/`closed`/`based`）；③ 必须点名至少一个真实工具标识符（`bash|grep`）。 |

新正文（`{start}` 为行号，`_READ_MAX_BYTES` = 51200）：

```text
[Line {start} truncated at 51200 bytes. This single line alone exceeds the read limit, so it cannot be returned in full. Use the bash tool to read a further byte range, or the grep tool to locate the part you need.]
```

**⚠ code-review 抓到并已修的坑（初版缺陷）**：初版写成 `"Use the shell tool ..."` —— 仓库里
**没有名为 `shell` 的工具**（注册名是 `bash`，见 `tools/bash.py:40`；`grep` 见 `tools/grep.py:45`）。
这等于把模型指向不存在的东西，**正是本票要修的缺陷类**。两轴 review 各自独立发现，已改为
`"the bash tool"` / `"the grep tool"`，并加断言锁死（第 ③ 条）。

- 有意**不做**：不给 read 加 byte-offset 参数（另一张票）；不改
  `[Showing lines X-Y of N. Use offset=Z to continue.]`（本就解释器无关）。
- 门禁：`ruff check src/ tests/` ✓；全量 `pytest` **1563 passed / 10 skipped / 39 deselected / 0 failed**。
- 变异验证（均转红后还原）：① 文案回退成 sed 示例 → `\bsed\b` 断言红；② 前缀改成
  `[Line {n} truncated {bytes}` → 解析契约断言红；③ 正文不含 `bash`/`grep` → 真实工具断言红。
  （第 ②/③ 项最初在「未还原前一次变异」的状态下跑，红色归因不成立，已重跑隔离验证。）

### 1.4 前端改动（`D:\intelligence-agent-frontend` @ `feat/frontend`）

**commit `1fac807`（功能+文档）/ `43b9ffd`（tracker）**

| 文件 | 改动 |
| --- | --- |
| `web/src/lib/toolShapes.test.ts` | 新增「新文案（OBS-016）」用例；原用例改标「旧文案（历史会话已落盘）」并**保留**——历史 JSONL 事件里仍是旧文案，两种都必须能解，注释明写「别删旧用例」。 |
| `docs/HANDOFF_FRONTEND_SYNC.md` §1.3 | 订正为「形状契约 + 明示措辞可变 + 历史文案兼容要求」。 |
| `docs/SDD_TICKET_TRACKER.md` | 登记本批门禁、变异验证、跨端配对与「未做 merge」的理由。 |

- **解析逻辑零改动**（`LINE_TRUNCATED_RE` 本就吞尾部）。
- 门禁：`tsc -b` ✓ / `vitest` **502 passed（28 文件）** / `oxlint` **35 warnings 0 errors**（与基线持平）/
  `playwright --workers=2` **118 passed** / `vite build` ✓。
- 变异验证：把 `LINE_TRUNCATED_RE` 改成仅匹配旧文案（追加 `\. Use bash`）→「新文案」用例红、
  「旧文案」用例仍绿（已还原）→ 证明新用例非空转、且旧用例仍锁住向后兼容。

### 1.5 验收标准核对

| # | 标准 | 状态 |
| --- | --- | --- |
| 1 | 后端提示不再出现 `sed` / `head -c` / `tail -c` | ✅ 词边界断言锁定 |
| 2 | 前缀/结尾形状不变；`parseReadShape` 对旧、新两种文案都能解出 `{line, bytes}` | ✅ 新增新文案用例 + 保留旧文案用例 |
| 3 | `docs/HANDOFF_FRONTEND_SYNC.md:46` 同步订正 | ✅ |
| 4 | 后端 ruff + 全量 pytest 绿；前端五项门禁绿 | ✅ |

### 1.6 合并与验证要点

- 后端：`feat/backend` → `main`，预期无冲突（本票只碰 `tools/read.py` + 一个测试文件）。
- 前端：`feat/frontend` → `main`，预期无冲突（只碰 `web/src/lib/toolShapes.test.ts` + 两处 docs）；
  **main 侧 `toolShapes.ts` 与 `toolShapes.test.ts` 自 `274afcf` 起零改动**（已核）。
- 合并后建议的验证（`main` 上实跑）：
  - 后端：`uv run ruff check src/ tests/ && uv run python -X utf8 -m pytest -q`
  - 前端：`cd web && npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build`
  - 契约抽查（真机）：让模型 `read` 一个单行 >50KiB 的文件，断言返回的标记能解析出
    `{line, bytes}` 且正文不含 POSIX 专有命令；再回放一条**历史**会话（旧文案）确认前端仍解析。

### 1.7 关单

GitHub issue **#141 已关闭**（§14.12，comment 内含两个 clone 的分支与 commit、门禁与变异证据，
并注明「尚未合入 main，集成由集成 AI 执行」）。

---

## 2. ARCH-4b（#142）：`/api/sessions` 补 `trace_url` —— ✅ 已完成（跨端）

### 2.1 问题

前端 `types.ts::SessionSummary` 把 `trace_url` 声明为**非可选** `string | null`（契约
`2d7f87a` / ADR-0018 D7），但后端列表 `SessionSummary` 从不返回该键 → 运行时 `undefined`，
违反自己声明的类型。当前无可见影响（`SessionList.tsx` 未消费 trace 字段）→ **潜伏**漂移。
根因：`2d7f87a` 只把 `trace_url` 落到 **run 终结事件**（`data.trace_url`），列表页从未接线；
OBS-010 只补了 `trace_id`。

### 2.2 后端改动（`D:\intelligence-agent-backend` @ `feat/backend`）—— commit `a0f86a4`

同一个 run 终结事件里 `trace_id` 与 `trace_url` 本就并列（`session.end_run` 对称写入，
`session.py:399-400`），所以列表取值路径与 OBS-010 **完全同源**：

| 文件 | 改动 |
| --- | --- |
| `session/store.py` | `SessionSummaryStats` 增加 `trace_url`；`_terminal_trace_id(event)` → **`_terminal_trace_field(event, key)`**——两个键共用**同一套守卫**（非终结类型 / 缺键 / null / 空串 / 非字符串 → None），共用实现而非两份约定对齐，故不会一个漏填。`key` 收窄为 `Literal["trace_id","trace_url"]`（写错键名是类型错误，不是静默 None）。 |
| `web/app.py` | `SessionSummary` 增加 `trace_url` + 端点映射 `trace_url=s.trace_url`。 |
| `session/service.py` | **零改动** —— #143 的 dataclass 直通让新增字段自动透传（ARCH-4 的收益）。 |

- 门禁：ruff clean；全量 pytest **1575 passed / 10 skipped / 39 deselected / 0 failed**（= 1564 基线 + 11 新增）。
- 变异验证（均隔离复跑并还原）：①去掉 web 映射 → web 用例红（值是 null）；②交叉接线
  （trace_url 读 `"trace_id"` 键）→ 8 例红（含同源锁与两路径同口径）；③去掉守卫 → 8 例红；
  ④键名打错成 `"trac_url"` → web 值断言红（`Literal` 同时让它是类型错误）。
- 两轴 code-review：Standards 轴无 hard violation，采纳其 `Literal` 加固；有意不采纳
  NamedTuple 返回对（两处相邻两行未到抽取阈值，「同事件」已由共享 helper + 测试锁住）。
  Spec 轴认定 AC1/2/3/5 满足、零 scope creep，并指出 **AC#3 值断言缺口**（原只有
  `trace_id` 被锁）——已补 `test_trace_id_none_when_terminal_is_not_last_event` 对
  `trace_url` 的值断言。

### 2.3 前端改动（`D:\intelligence-agent-frontend` @ `feat/frontend`）—— commit `4c38c69`

| 文件 | 改动 |
| --- | --- |
| `web/src/lib/api.test.ts` | 新增 `listSessions` 契约块（`trace_url` 原样透传 + 未追踪保持 null）；canonical fixture 用 `SessionSummary` **类型注解**锁编译期一致性——类型新增必填字段 → fixture 缺键 → `tsc -b` 红；fixture 多出未声明键 → 多余属性检查红。 |
| `web/e2e/*.spec.ts`（6 文件 10 行） | 会话行 mock 补 `trace_url: null`，与真实后端 payload 对齐——旧 mock 照抄了「后端不返回该键」的坏形状，会让前端永远看不到它。 |

- **`types.ts` 零改动**（本就声明正确）。
- 门禁：tsc ✓ / vitest **504 passed**（28 文件）/ oxlint **35w 0e** / playwright **118 passed**
  （`--workers=2`）/ vite build ✓。
- 变异验证：从 canonical fixture 删掉必填 `trace_url` → `tsc -b` 报 **TS2741** 红（已还原）。
- 后端侧权威锁（断言**值**，能抓「键在但值是 null」的漏映射）：
  `tests/test_web_api.py::test_list_sessions_carries_terminal_trace_url`。

### 2.4 验收标准核对

| # | 标准 | 状态 |
| --- | --- | --- |
| 1 | Langfuse 开启时 `trace_url` 与同一 run 的 `run/completed.data.trace_url` 同值 | ✅ 值断言 + 回填用例 |
| 2 | Langfuse 未启用时两者都为 null | ✅ robustness + web 两侧 |
| 3 | 末事件非 run 终结时两者都为 null | ✅ 已补 `trace_url` 值断言（Spec 轴发现的缺口） |
| 4 | 前端 `types.ts` 声明与运行时一致 | ✅ 类型零改动 + 编译期注解锁 + 透传锁 + e2e mock 对齐 |
| 5 | 后端 ruff + 全量 pytest 绿；前端门禁绿 | ✅ |

### 2.5 合并要点

- 本票与 §3（ARCH-4）落在**同一处代码**（`session/store.py` + `web/app.py` 的重叠区域）。
  若两票分两次合入，第二次遇冲突属预期内，需按 §14.7 逐文件分析（**不是**机械取一侧）：
  两者是「增加字段」与「改返回类型」的正交改动，正确合并结果应同时保留。
- **关单**：GitHub issue #142 已关闭。

---

## 3. ARCH-4（#143）：`list_sessions` 去 dict 中转 —— ✅ 已完成

**commit `2ea83d4`**（`feat/backend`）

同一个 summary 事实原本有三种形状在传递：store 的 frozen dataclass
`SessionSummaryStats` → service 的 `dict[str, Any]`（纯机械复述、无校验无行为）→ web 的
Pydantic `SessionSummary`。中间那层 untyped dict 是前端契约静默漂移逃过类型检查的位点。

| 文件 | 改动 |
| --- | --- |
| `session/store.py` | `SessionSummaryStats` 增加 `session_id: str`（行的身份，与统计字段同属列表页所需）；3 个构造点（快路径 + fallback 两处）补字段。 |
| `session/service.py` | `list_sessions` 签名 `list[dict[str, Any]]` → `list[SessionSummaryStats]`，删除 dict 拼装。 |
| `web/app.py` | `/api/sessions` 改读 dataclass 属性（显式映射保留）。 |
| `tests/session/test_service.py` | 4 处 dict 下标改属性访问 + 新增 `test_returns_domain_dataclass_not_dict`。 |

**前提说明**：`SessionSummaryStats` 原本没有 `session_id`（issue 的「影响面」未列出）——
行身份必须随行携带才能去掉 dict，故加在**既有** dataclass 上（未引入新类型，符合边界）。

- 行为不变证据：`tests/test_web_api.py` **零改动通过**（走 HTTP 的列表契约用例）。
- 门禁：ruff clean；全量 pytest **1564 passed / 10 skipped / 39 deselected / 0 failed**。
- 变异验证：`summaries.append(stats)` → `vars(stats)` → **7 例转红**（含新锁与 3 个 web 列表契约用例），已还原。
- 两轴 code-review：Spec 轴四条件全满足、零 scope creep；Standards 轴 5 项 judgement call，
  采纳 3（去前向引用叙事、删冗余断言），未采纳 2 并留理由（不改名 `SessionSummaryRow`；
  不用 `model_validate(from_attributes=True)`——显式映射字段漂移时响亮失败）。
- **未改**：`get_events` 的返回；未引入新类型别名/包装类。
- **关单**：GitHub issue #143 已关闭。

**⚠ 合并注意**：本票把 `/api/sessions` 的字段定义收拢到领域 dataclass。§2 的 ARCH-4b
（`trace_url`）落在**同一处**，两票都会改 `session/store.py` + `session/service.py` + `web/app.py`
的重叠区域——若两票分两次合入，第二次遇到冲突属预期内，需按 §14.7 逐文件分析（不是机械取一侧）。

---

## 4. ARCH-5（#144）：领域异常→HTTP 映射单源化 —— ✅ 已完成

**commit `87fc388`**（`feat/backend`）

### 4.1 问题

11 个 handler（`app.py` 10 + `lineage.py` 1）各自重述同一段「领域异常 → status + detail」
阶梯，共 **37 个 except 臂**。后果：新增一个领域异常要改每一处；同一个异常在不同 handler
给出不同状态码不会被任何检查发现（翻译层事实存在，却没有 home）。

### 4.2 审计结论（AC#3）

**⚠ issue 只列了 9 处（`app.py`），实际是 11 个 handler / 37 个臂 / 13 个异常。**
复核方式：`git diff HEAD | grep -c '^-\s*except '` = 37 → `^+` = 11。多出的两处同形阶梯：

- `POST /api/sessions`（`create_session`：`WorkspaceNameInvalid` + `InvalidDecision`）；
- `lineage.py` 的 `POST /api/sessions/{id}/forks`（4 臂）。

不收进来就谈不上「单一映射源」，故一并处理（同层超集、零契约变化）。

**关键发现：每个异常在所有 handler 里状态码一致** —— 这正是可单源化的前提。

| status | 异常 |
| --- | --- |
| 422 | InvalidSessionId, WorkspaceNameInvalid, InvalidDecision, UnknownModel, InvalidForkBoundary |
| 404 | SessionNotFound, ApprovalQueueMissing, ApprovalRequestMissing, QueueItemNotFound |
| 409 | ActiveRunConflict, RecoveryConflict, ApprovalAlreadyResolved, SteerTargetNotFound |

两个**不得「顺手统一」**的特例（已写进契约）：
- `approve` 的 404 有**三个不可区分来源**（SessionNotFound / ApprovalQueueMissing /
  ApprovalRequestMissing）—— OBS-015；
- `ApprovalAlreadyResolved` 是 **409 幂等已决**（可区分），不是 404。

逐端点异常集合表见 `src/agent_harness/web/domain_errors.py` 模块 docstring。

### 4.3 修法

新增 **`src/agent_harness/web/domain_errors.py`** 作为翻译层的唯一 home：
`_DOMAIN_ERROR_STATUS`（13 条，覆盖全部 `SessionServiceError` 子类）+ `http_error(exc)`。
每个 handler 的阶梯从 N 臂收敛为 **1 臂**：

```python
except (<本端点翻译的异常>) as e:
    raise http_error(e) from e
```

**为什么保留 per-endpoint 的 except 元组**（两个被否决的方案 + 理由）：

| 方案 | 否决理由 |
| --- | --- |
| FastAPI 全局 `exception_handler` | 会把整张表应用到**每个**端点，使本来只会 500 的意外异常突然变成 404/422——issue 边界明确禁止「引入该端点本来不产生的状态码」。每端点用**自己的元组**声明子集，语义不变。 |
| 装饰器 | app.py / lineage.py 都启用 `from __future__ import annotations`，注解是字符串；包装函数定义在别的模块会改变 `__globals__`，FastAPI 的 `get_type_hints` 解析 `ForkRequest`/`ResumeRequest` 这类本模块名会 **NameError**。收益不抵风险。 |

### 4.4 验收标准核对

| # | 标准 | 状态 |
| --- | --- | --- |
| 1 | 阶梯收敛到单一映射源；handler 内只剩传输特有分支 | ✅ 37 臂 → 11 臂 |
| 2 | 所有既有状态码行为不变（既有 web 测试零改动通过即证据） | ✅ `tests/test_web_api.py` + `tests/web/*` 零改动通过（仅新增映射测试文件）；`detail=str(e)` 与 `raise … from e` 链保留 |
| 3 | 审计结论写进代码/文档（含 approve 四来源差异） | ✅ `domain_errors.py` docstring 表（**注意**：issue 说的「9 处」实际为 11 handler / 37 臂，已订正；approve 的表述订正为「三个 404 + 一个可区分 409」） |
| 4 | ruff + 全量 pytest 绿 | ✅ 1578 passed / 10 skipped / 0 failed |

- 变异验证（已还原）：把表里 `SessionNotFound` 改成 418 → **16 个既有用例转红**（跨
  `test_web_api` / `multiturn` / `stream` / `recover`）→ 证明该表是 11 个 handler 的
  **活映射源**（不是文档），且既有测试确实覆盖这些状态码。
- 新增测试 3 例（`tests/web/test_domain_error_mapping.py`）：① `_all_subclasses` 遍历断言
  每个领域异常都已登记（漏登记先红——`http_error` 直接索引不猜）；② 审计契约逐条钉住
  13 个状态码；③ `http_error` 的 status/detail 投影。
- 两轴 code-review：均确认 13 个状态码与改前逐字一致；两轴**各自独立算出臂数是 37**
  （我 docstring 初稿写 35 有误），并指出「approve 四个不可区分 404」措辞自相矛盾——
  两处文档错误已改正（AC#3 要求审计记录准确）。
- **过程记录（如实）**：其中一次全量运行出现 14 个 web 实时流/WS 计时敏感用例失败，
  隔离复跑与紧接着的复跑全绿。本票为纯状态码映射重构、不触及流式与计时路径，与仓库
  既有备案的计时 flake 同类。
- **关单**：GitHub issue #144 已关闭。

---

## 5. 集成顺序（§14.9：一次一个分支）

```text
1. feat/backend → main        （先回后正：先 fetch，再在 feat/backend 侧确认与 origin/main 关系）
2. 在 main 跑后端全量门禁 + 真机契约抽查
3. 重新 fetch / diff / merge-base，重新分析 feat/frontend 的冲突面（后端合入后旧判断全部作废）
4. feat/frontend → main
5. 在 main 跑前端五项门禁
6. 完整起项目联调（前后端同时跑）
7. 最后 git push origin main
```

**每个 merge 动作前单独确认**（§14.11：不得因为上一阶段获批就默认本阶段也获批）。

### 5.1 建议的后合并验证命令

后端（在 `main` worktree）：

```bash
uv run ruff check src/ tests/
uv run python -X utf8 -m pytest -q        # 期望 1578 passed / 10 skipped / 0 failed
uv run python -X utf8 -m pytest tests/web/test_domain_error_mapping.py -q   # ARCH-5 映射契约 3 例
```

前端（在 `main` 的 `web/`）：

```bash
npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build
# 期望：vitest 504 passed / oxlint 35w 0e（基线持平）/ playwright 118 passed
```

契约抽查（真机，建议）：

1. `GET /api/sessions` 每行**含 `trace_url` 键**（Langfuse 关闭 → `null`；开启 → 与
   `run/completed.data.trace_url` 同值）——ARCH-4b；
2. `read` 一个单行 > 50KiB 的文件，返回标记能解析出 `{line, bytes}` 且正文不含
   `sed`/`head -c`/`tail -c`；再回放一条**历史**会话（旧文案）确认前端仍解析——OBS-016；
3. 打一遍既有 404/409/422 场景（如 `POST /api/sessions/{unknown}/cancel` → 404、
   `POST /api/sessions/{id}/approve` 已决 → 409、非法 session_id → 422），确认状态码与
   改前一致——ARCH-5。

### 5.2 本批的风险提示（给集成 AI）

| 风险 | 说明 |
| --- | --- |
| ARCH-4 / ARCH-4b 同区重叠 | 两票改同一文件区域；在 `feat/backend` 上已顺序提交无冲突，集成时按顺序快进即可。 |
| ARCH-5 是纯重构但面广 | 37 臂 → 11 臂，涉及 11 个端点；**唯一行为不变证据是既有 web 测试零改动通过**（`tests/test_web_api.py` + `tests/web/*` 均未改动）。合并后请勿跳过 web 测试。 |
| 计时敏感 flake | 本批施工中出现过一次全量运行 14 个 web 实时流/WS 用例失败、隔离与复跑全绿（仓库既有备案同类）。若合并后遇到，先隔离复跑再判定。 |
| 前端 e2e mock 已补 `trace_url` | 若只合后端不合前端，`web/e2e` 的 mock 仍缺该键（前端 mock 与后端 payload 会短暂不一致）——建议两分支按顺序合完再跑联调。 |
