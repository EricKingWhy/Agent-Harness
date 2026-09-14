# BUG-011 / P0-002 集成提示词（集成 AI 执行手册）

> **收件人**：集成 AI（Git Integrator 角色，AGENTS.md §14）
> **任务**：把 `feat/backend` 与 `feat/frontend` 的本次跨端修复合入 `main` 并完成验证
> **红线**：永不 force-push / rebase / reset --hard；凭据零泄漏（`.env` 值不进任何输出/提交）；
> 每次合并动作前确认 worktree 与分支（§14.2）；冲突后**立即停止**自动解决并按 §14.7 逐文件分析；
> **一次只合一个分支**（§14.9：先 backend → main 验证完，再重新 fetch/diff/merge-base 分析 frontend）。
> **本文件状态**：**两半均已完成**（后端 `feat/backend` + 前端 `feat/frontend`），均未 push（集成 AI 执行合并）。

## 本批总表

| 项 | issue | 后端 commit | 前端 commit | 状态 |
| --- | --- | --- | --- | --- |
| BUG-011 / P0-002 双击模型项 → 重复 seq → 续聊永久 404 | —（无对应 issue，见 §7） | `4b8eee4` + `6008fb9`/`c657158`（docs） | `71e605b`（代码）+ `949d4ad`/`f06cfbd`（docs） | ✅ 跨端完成 |

**这是一次真实用户报障的修复**（用户报「续聊失败：Send failed: 404」），不是计划内 ticket：
用户批准后按「① 后端串行化写入 + seq 守卫 → ② 后端冲突独立语义（409）→ ③ 前端双击不发第二个请求
→ ④ 两侧回归锁」四步实施。修复前用户已确认把损坏会话 `dd983104` 删除（删前逐字节记录在
`D:\intelligence-agent-frontend\docs\FRONTEND_ISSUES_LOG.md` 第八轮章节）。

---

## 0. 机器现状（以 `git -C <path> log -1` 为准，合并前必须复核）

| 用途 | 目录 | 分支 | 本批 tip |
| --- | --- | --- | --- |
| 集成主战场 | `D:\intelligence-agent` | `main` | 以实际为准 |
| 后端施工区 | `D:\intelligence-agent-backend` | `feat/backend` | `4b8eee4` + 本文件的 docs commit |
| 前端施工区 | `D:\intelligence-agent-frontend` | `feat/frontend` | `949d4ad`（`71e605b` 的 docs 后续） |

- **前端 clone 拓扑**：`D:\intelligence-agent-frontend` 是**独立 clone**（自带 `.git`），不是 worktree；
  `D:\intelligence-agent-backend` 才是 worktree。**前端**合入后重新 `fetch`/`diff`/`merge-base` 再判。
- **两侧改动文件集不相交**：后端只动 `src/agent_harness/**` + `tests/**`；前端只动 `web/src/components/`、
  `web/src/hooks/`、`web/e2e/` 与会话 docs。预期无冲突。
- **⚠ 必须按顺序合并（§14.9）**：后端 seq 守卫是**安全网**（即使前端漏发也不会再写坏日志），
  前端去重是**堵源头**。两者独立可用，但先合后端能让前端在缺陷复发时不再损坏会话。

---

## 1. 问题（真机现场与根因）

**现象**：真实浏览器里模型项被**双击** → 两个并发 `POST /api/sessions/{id}/model` → 该会话此后
**任何续聊恒 404**（`续聊失败：Send failed: 404`），且**日志已永久损坏**。

**证据链（独立取证，已写入前端登记簿第八轮）**：
- 浏览器历史网络记录里两个相邻的 `POST /model` reqid；
- 会话 JSONL 里**两条 `seq=5`**、payload 完全相同、`from_*: null`（证明两次写入都基于同一份**改前**快照）；
- 只读本地复现：对副本调 `Session.load` → `ValueError`，原文件未被改动。

**根因（两处叠加）**：
1. **并发写无序列化**：`seq` 分配在内存聚合根（`Session._next_seq = max(seq) + 1`），而 JSONL 文件是共享真相；
   两个聚合来自同一快照 → 取到同一个号。`fsync`（~30ms）阻塞事件循环正是窗口。实测窗口：
   间隔 0ms → 3/3 次重复；20ms → 1/3；≥50ms → 0/3。
   **关键**：写者跨线程——`recovery/scan._mark_interrupted` 的读+append 在**工作线程**里跑，
   所以 `asyncio.Lock` 串不住，串行化点必须在 store 层用 `threading.Lock`。
2. **错误语义错配**：重复 seq 让所有构造 `Session` 聚合的路径抛 `ValueError`，被
   `service.py` 的 `except ValueError → SessionNotFound` 一刀切映射成 **404「会话不存在」**——
   真实情况是「日志损坏」，不是「会话不存在」，用户看到的是**误导性**提示且无从恢复。

---

## 2. 后端改动（`D:\intelligence-agent-backend` @ `feat/backend`）—— commit `4b8eee4`

### 2.1 改动清单

| 文件 | 改动 |
| --- | --- |
| `src/agent_harness/session/errors.py` | 新增领域异常 `SeqConflict(SessionServiceError)`（写时冲突可重试 / 读时冲突不可自愈，消息区分两者，状态码同为 409） |
| `src/agent_harness/session/store.py` | `append_event` 增加**每会话写锁**（`threading.Lock`）+ **seq 单调性守卫**：落盘前校验 `event.seq > 已落盘最大 seq`，违反抛 `SeqConflict`；`_last_seq_on_disk` 带 stamp 校验的缓存 |
| `src/agent_harness/session/session.py` | 新增模块级 `validate_event_seq`（seq 严格递增校验的**唯一 owner**）；`Session.append_event` / `Session.load` 空日志抛 `SessionNotFound`、seq 异常抛 `SeqConflict` |
| `src/agent_harness/session/service.py` | `change_model` 写时冲突**有界重试**（`_WRITE_CONFLICT_ATTEMPTS = 3`）；**删除** `except ValueError → SessionNotFound` 一刀切；`resume_and_launch` 同步收紧 |
| `src/agent_harness/web/domain_errors.py` | `SeqConflict: 409` 进 `_DOMAIN_ERROR_STATUS`；`/resume`·`/recover`·`/model`·`/messages`·`/queue/{qid}/cancel` 审计表行更新 |
| `src/agent_harness/web/app.py` | 上述 5 个端点的 `except` 元组加入 `SeqConflict`（ARCH-5 机制要求：不加就变 500） |

### 2.2 测试（新增/更新）

- `tests/session/test_event_store.py`：`TestSeqMonotonicityGuard` 8 例（含 `test_append_event_is_mutually_exclusive_per_session`）；
- `tests/session/test_model_change.py`：`TestConcurrentModelChange`（冻结前两次 `read_events` 强制两个写者落在同一快照 + 有界 3 次重试断言）；
- `tests/web/test_web_seq_conflict.py`（新）：4 例含对照组；
- 更新 `tests/session/test_session.py`、`test_session_robustness.py`（新增重复 seq 用例）、`test_fork.py`、`tests/web/test_domain_error_mapping.py`。

### 2.3 门禁与变异验证

- 门禁：`ruff check` clean；全量 `pytest` **1596 passed / 0 failed**。
- 变异验证（**4 组，全部已还原**）：去掉守卫 / 去掉重试 / 去掉 `validate_event_seq` / 去掉写锁 →
  **每组都确定性转红**（不是靠调度运气：并发用例先冻结前两次读取，强制两个写者同为同一快照）。

### 2.4 已知边界（如实标注，非缺陷）

- **跨进程并发写未加文件锁**（多进程共享同一 JSONL 仍可能撞号）——`store.py` 文档已写明该边界；
- **读时发现的既有损坏不自愈**：历史遗留的重复/回退 seq 直接 409（不自动重编号，不静默吞）；
- 因此「已损坏的旧会话」本次修复后**仍不可用**（这正是用户删除 `dd983104` 的原因）。

---

## 3. 前端改动（`D:\intelligence-agent-frontend` @ `feat/frontend`）—— commit `71e605b`

### 3.1 改动清单

| 文件 | 改动 |
| --- | --- |
| `web/src/components/ModelPicker.tsx` | 新增 `commitSelection` 作为两处 `onSelect`（默认链 + 目录项）的**统一入口**：**弹层已关（`!open`）即丢弃选中** |
| `web/src/hooks/useSession.ts` | 仅注释变化（指明真正的 seam 在选档入口，防止后人把守卫加错层） |
| `web/e2e/fixtures.ts` | 新增 `onModelPost` 注入点 + `POST /model` 缺省 200 处理器（计数 / 延迟响应用） |
| `web/e2e/q-model-dedupe.spec.ts`（新） | 3 条锁 × 2 视口 |

### 3.2 机制（实测驱动，与最初设想不同，务必知悉）

拦截点是**选档入口一层**：第一次选中后浮层进入 `--dur-out`（150ms）退出动画，节点仍在 DOM 中
可被命中，第二次 `click` 会被 `!open` 丢弃。

**曾试过再加一层**「`useSession.changeModel` 同目标在途复用 Promise」——探针实测该层**永不生效**：
`dblclick()`（一次手势两下点击）与 `page.mouse.click` ×2 都是「两次 click 之间 React 已提交
`open=false`」，第二个请求根本到不了 hook；删掉该层前后探针结果完全相同（`dblclick=1` / `mouseclick_x2=1`）。
结论：**测不到的死层不留**，只保留有效的一层（等价于原方案里「弹层关闭后立即 `pointer-events:none`」）。

### 3.3 门禁与变异验证

- 门禁（§16.6 全量）：`tsc -b` ✓ / `vitest` **519 passed**（29 文件）/ `oxlint` **37w 0e**（基线持平）/
  `playwright --workers=2` **130 passed** / `vite build` ✓。
- 变异验证（已还原）：去掉 `!open` 守卫 → 两条测试**全红**，且失败信息就是原始 bug 指纹
  （`Expected: 1 / Received: 2`；另一例 `Received length: 3`，三个 payload 完全相同）——
  证明绿不是「第二次点击根本没落到节点上」。

---

## 4. 验收标准核对（对照用户批准的四步）

| 步 | 要求 | 结果 | 证据 |
| --- | --- | --- | --- |
| ① | 后端按会话串行化 append，并发写不再撞号 | ✅ | `store.append_event` 每会话 `threading.Lock` + 守卫；`test_append_event_is_mutually_exclusive_per_session` |
| ② | 撞号给独立错误语义（不再是 404） | ✅ | `SeqConflict → 409` + 有界重试 3 次；`tests/web/test_web_seq_conflict.py`；`test_domain_error_mapping.py` 双向钉住 |
| ③ | 前端双击不再发第二个请求 | ✅ | `ModelPicker.commitSelection` 的 `!open` 守卫；真机实测 dblclick 与 ≤120ms 双击都只发 1 个 |
| ④ | 两侧回归锁（服务端并发不重复 seq / 前端双击只允许一个 POST） | ✅ | 后端 pytest 并发用例（红→绿，冻结快照法）；前端 e2e 3 条 × 2 视口（红→绿，变异验证敏感性） |

---

## 5. 集成顺序与后合并验证

### 5.1 顺序（§14.9 一次一个分支）

```text
feat/backend  → 本地 main → 后端门禁 → 真机端到端验收（§5.2）
              → 重新 fetch/diff/merge-base 分析 feat/frontend
feat/frontend → 本地 main → 前端门禁 → 同一真机验收复跑
              → git push origin main
```

### 5.2 建议的端到端验收（**这是本次修复的最终判据，务必做**）

```bash
# 1) 起后端（D:\intelligence-agent，main）
uv run uvicorn agent_harness.web.app:app --host 127.0.0.1 --port 8000
# 2) 起前端（D:\intelligence-agent-frontend\web 或 main 的 web/）
npm run dev
```

在浏览器里：
1. **双击**模型项切换模型 → DevTools Network 只应有 **1 个 `POST /model`**（修复前是 2 个）；
2. 用该会话**续聊**一句 → 应正常流式返回，**不得**出现 `续聊失败：Send failed: 404`；
3. 检查该会话 JSONL（`~/.agent_harness/sessions/<id>.jsonl` 或项目配置的 session root）：
   **seq 严格递增、无重复**；
4. （可选，验证 ②）直接对已损坏的历史会话发续聊 → 应返回 **409**（并在 UI 显示为冲突/损坏语义），
   而**不是** 404「会话不存在」。

### 5.3 后合并回归命令

```bash
# 后端（D:\intelligence-agent 或 backend worktree）
uv run ruff check . && uv run pytest -q
# 期望：ruff clean；1596 passed（含本批 13 个文件里的新增用例）

# 前端
cd web && npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build
# 期望：0 error（oxlint 37 warning 为既有基线）；vitest 519 passed；playwright 130 passed
```

### 5.4 真机端到端验收结果（**本批已实测**，2026-09-11）

用**真实 uvicorn**（`WORKSPACE_DIR` 指向临时目录，**未触碰任何真实会话**）+ 项目自身 API 造的会话实测：

| 步骤 | 命令/做法 | 结果 |
| --- | --- | --- |
| 并发写（复原后） | 同一会话 **6 路并发** `POST /model`（原始触发形状） | 6×`200`；落盘 seq `0..9` **严格递增、无重复**（事件流 `session/started, user/message, run/started, run/completed, model/changed ×5`） |
| 并发写（**去掉守卫**的变异对照） | 同一 6 路并发 | **落盘出现重复 `seq=6`**（`0..6,6`，非严格递增），另有 2 个请求 409（读时发现冲突）→ **证明该检查不是空转**（已还原） |
| ② 语义（用户实际报障端点） | 手工注入重复 seq 后 `POST /api/sessions/{id}/messages`（续聊） | **409** + `{"detail":"Session '…' 事件 seq 重复: 3"}`（修复前是误导性的 **404**） |
| ② 语义（换模型端点） | 同一损坏会话 `POST /model` | **409** + 同一 detail |
| ② 语义（对照：非目录内模型） | `POST /model` 传 catalog 外的 provider/model_id | **422**（catalog 校验仍生效，未被本次改动波及） |

结论：**①（不再写坏日志）②（损坏/冲突给出独立语义而非伪装 404）在真实服务端均成立**；
③④ 由前端 e2e（真实浏览器 + 变异验证）覆盖。

**顺带确认的边界（Scope 外，仅报告）**：会话**有 JSONL 但缺 workspace 映射文件**时，
`Session.resume → load → registry.get` 抛 `KeyError`（发生在 seq 校验**之前**）→ **500**，
不走 409/404。正常会话不会进入该状态（`Session.start` 会同时写两份），只有手工构造或半删除才会；
属另一张票，本次未改（已记入前端登记簿）。

---

## 6. PHASE_STATUS 登记

本批的后端 `PHASE_STATUS.md` 条目已由**后端**在 `feat/backend` 上追加（含前端半的 commit 与集成顺序）。
前端侧按该 clone 的协议（`docs/SDD_TICKET_TRACKER.md`「已识别但未做的协议项」）**未写 PHASE_STATUS.md**，
其批次记录在 `D:\intelligence-agent-frontend\docs\SDD_TICKET_TRACKER.md`「最近一批」；
**合入后无需重复追加**——后端条目已把跨端两半写在一起。

---

## 7. 关单与追踪

- **无对应 GitHub issue**：BUG-011 是真实用户报障后现场定位的缺陷，未开 issue（同 OBS-* 批次的
  先例：「无对应 GitHub issue，关单不适用」）。追踪载体是：
  - 前端问题登记簿 `docs/FRONTEND_ISSUES_LOG.md`（BUG-011 条目 + 第八轮完整证据链）；
  - 本文件 + `docs/PHASE_STATUS.md` 条目。
- 如需正式关单，请由集成 AI 或用户开 issue 后按 §14.12 关闭（comment 引用上表两 commit 与门禁证据）。

## 8. 风险与未决（仅报告）

1. **跨进程并发写**：本次只在**进程内**串行化（`threading.Lock`）。若部署为多 worker / 多进程共享
   同一 session root，仍可能撞号——需要文件锁或单写者模型，属独立设计议题（未做）。
2. **旧损坏会话不自愈**：本次修复只防再犯，不修复历史损坏数据（用户已删除 `dd983104`）。
3. **`/recover` 与 `/queue/{qid}/cancel` 的 `except` 元组新增项**：这是 ARCH-5 机制的要求
   （新异常必须在每个可能抛它的端点显式登记，否则变 500），不是 scope creep。
4. **前端拦截依赖 Popover 的受控 `open` 状态**：若未来把 `ModelPicker` 换成非受控 / 无退出动画的
   容器，需重跑 `q-model-dedupe.spec.ts`（它就是为此存在的回归锁）。
