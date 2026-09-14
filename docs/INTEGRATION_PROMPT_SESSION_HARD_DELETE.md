# 集成提示词 —— 会话硬删 #172 / ADR-0029（**后端半已完成，前端半待做**）

> 生成时间：2026-09-13 · 分支 `feat/backend` · commit `4109b08`
> 关联：#172（跨端票，**不要关单**）、ADR-0029、#171（归档，另一刀，两者并存）

---

## 0. 一句话状态

后端半已实现并通过门禁：`DELETE /api/sessions/{session_id}`（硬删，不可恢复、无墓碑）。
**前端半尚未开始**（不可逆二次确认 + 硬删入口）——这是**用户明确要求的分工**：用户 2026-09-13
裁决「我同意硬删除。你先做你的吧，你做完了我再让前端ai动手做他的，这样就不会冲突了」。
因此：两端**串行**做，前端 AI 在后端半合入 `main` 之后再动手。

---

## 1. 给集成 AI（合并 `feat/backend` → `main`）

### 1.1 事实

| 项 | 值 |
| --- | --- |
| 分支 / commit | `feat/backend` → `4109b08`（父 `a126378`，`main` = `b28e856`，已含 `a126378`） |
| 改动规模 | 18 文件，+1120 / −9 |
| 门禁 | `ruff check src/ tests/` clean；全量 pytest **2125 passed / 10 skipped / 42 deselected / 0 failed**（`main` 基线 2109 passed，+16 = 15 条硬删契约测试 + 1 条 store 单测） |
| 两轴 code-review | Standards + Spec，共 5 轮收敛到**零 finding** |
| 关单 | **否** —— §14.12 跨端票，前端半未做 |

改动面（按职责）：

```
docs/adr/0029-session-hard-delete.md      新增 ADR（D1–D8，含安全否决与偏离理由）
src/agent_harness/session/service.py      SessionService.delete_session + SessionDeletionStats
src/agent_harness/session/store.py        JsonlSessionStore.delete_session
src/agent_harness/session/errors.py       SessionHasChildren
src/agent_harness/sandbox/registry.py     WorkspaceRegistry.discard_session_artifacts（不读映射）
src/agent_harness/storage/{operation,checkpoint,session_meta}.py  delete_for_session ×2 + clear_delegation_parent
src/agent_harness/storage/sqlite.py       三个方法的 SQLite 实现
src/agent_harness/workspace/index.py      detach_session 返回值 None → int（实际摘掉的账本数）
src/agent_harness/web/app.py              DELETE 端点 + SessionDeleted 响应模型
src/agent_harness/web/domain_errors.py    SessionHasChildren → 409 + 审计表行
src/agent_harness/web/runmanager.py       RunManager.is_busy
src/agent_harness/logging.py              session_delete 事件类型
tests/web/test_session_delete_api.py      15 条契约测试（含 cwd 回归锁）
tests/{storage,workspace,web}/...         3 个测试文件的小幅追加
```

### 1.2 合并顺序（§13.3 / §14.6「先回后正」）

```bash
git -C D:/intelligence-agent-backend fetch origin --prune
git -C D:/intelligence-agent-backend merge origin/main        # 先同步，冲突在此解决
# 在 feat/backend 跑到全绿
git -C D:/intelligence-agent  merge feat/backend              # 再合入本地 main
# main 上启动完整项目 + 全量测试 + 真机验收（§4），最后才 push origin main
```

### 1.3 可预期冲突面

1. **`docs/PHASE_STATUS.md`** —— 两端都会追加记录，**冲突时两侧都要保留**（谁都不许删别人的行）。
   本票追加的那条以 `- 2026-09-13：**ticket #172` 开头。
2. **`docs/adr/0029-session-hard-delete.md`** —— 新增文件，理论上零冲突；若 `main` 上已有同名文件，
   说明另一端也在写同一号 ADR，**停下来问用户**（§14.7），不要机械 `ours/theirs`。
3. **`web/**`（前端）** —— 本分支**未触碰**任何前端文件；前端半是独立的下一次改动。
4. `docs/INTEGRATION_PROMPT_*.md` —— 多为新增文件；同号重复时按 §14.7 处理。

合并后必跑：`pytest tests/web/test_session_delete_api.py tests/storage/test_session_meta_lineage.py`
（31 passed）。

---

## 2. 给前端 AI（前端半，等后端半合入 `main` 后再动手）

### 2.1 API 契约（已冻结，**不要改后端响应形状**）

```http
DELETE /api/sessions/{session_id}
```

| 结果 | 含义 |
| --- | --- |
| 200 `{"id": "...", "deleted": true, "events": 42, "detached_from_projects": 1}` | 真删了。`events` = 删除前日志里的事件数，`detached_from_projects` = 本次从几个项目账本里摘掉了它（正常 0/1） |
| 404 | 这个会话不存在（**第二次删除就是这个**，不伪装成"又删了一次"） |
| 409 | ① 有在途 run，② 有挂起审批，③ 有 **fork** 子会话（`detail` 形如 `session 'x' is the fork parent of 2 session(s): delete the child session(s) first`） |
| 422 | `session_id` 形态非法（前端正常不会触发） |
| 403 | 非本机 `Origin`（本地信任模式的来源闸；dev server 5173 / `localhost` / `127.0.0.1` 都放行） |

要点：

- `deleted` 恒为 `true`：走到 200 就是真删了，没有"半删"状态可表达。
- **409 的三种原因只能靠 `detail` 文案区分**（状态码相同）。建议：把 `detail` 原样展示，
  不要自己编一套文案——尤其"有 fork 子会话"那条已经带了数量。
- 错误体是 FastAPI 的 `{"detail": "..."}`；前端已有的错误处理路径直接复用。
- **委派子会话（内部子 Agent）不阻止删除**；只有用户可见的 fork 子会话阻止。
- 删除成功后后端已顺手清掉委派子会话指向它的父链接，所以家谱图不会再出现
  `(parent missing)` 悬空链接——前端**不需要**为此做任何兼容。

### 2.2 前端必须实现的（ADR-0029 把责任明确放在入口层）

1. **不可逆二次确认**：ADR-0029 Consequences 逐字写着「误删不可逆，且没有任何技术兜底
   （无墓碑 / 无回收站）。风险全部由**入口层的显式确认**承担」——确认弹窗必须写明
   "不可恢复"（用词不要只写"删除"），并显示会话标识（标题/首条消息 + id 片段）。
   这是本票前端 AC 的硬要求，不是可选项。
2. **成功后的状态收敛**（缺一项都会留下"删了还看得见"的假象）：
   - 侧栏列表移除该行（或重新拉一次 `GET /api/sessions`）；
   - 若被删的正是当前打开/正在流式输出的会话 → 断开其 SSE 订阅、清空对话区、别把 URL
     留在死 id 上；
   - 若它在某个项目里 → 该项目的 `session_ids` 已不再包含它（`GET /api/projects/{id}` 为准）；
   - **不要**乐观地把带 fork 子会话的删除当成成功：409 时列表必须保持原样。
3. 用 `events` / `detached_from_projects` 写确认回执（"已删除 N 条事件记录，并从 M 个项目解除"）。

### 2.3 前端门禁与坑（§16.6 同款）

```bash
cd web && npx tsc -b && npx vitest run && npx oxlint \
  && npx playwright test --workers=2 && npx vite build
```

- **5173 复用坑**：跑 playwright 前先确认那个端口上跑的是**哪个 worktree 的 dev server**
  （`reuseExistingServer: !CI` 会静默复用别人的），否则测的是别的分支的产物。
- **不要跨 worktree 并发跑重门禁**：实测在另一处跑全量 pytest / vitest 时会出现成片假失败
  （超时类），不要把负载型抖动当成回归。
- 真机测试**不要对着默认的真实 workspace 删会话**（那是用户的真实数据目录）；用临时目录
  （`workspace_dir` 指到 temp）或先备份 `harness.db`。

---

## 3. 已知边界 / 本票非目标（前端不必等，也不要顺手补）

- Memory / Artifact **不级联**（ADR-0029 D6）：删会话后 SESSION 记忆成为不可达残留、
  artifact 可能有悬空引用；级联要另开票（memory 需要新查询 + 索引，artifact 需要先给
  `ArtifactStore` 加 delete）。
- 无回收站 / undo / 墓碑；不做自动清理、TTL、批量删除（ADR-0004 明确不自动 TTL）。
- 单删（一次一个 id）；不做批量选择删除。
- 启动期一致性检查**不做**，理由写在 ADR-0029 D3（它防的崩溃方向已被"先 DB 后文件"排除；
  而"有日志无 `session_meta` 行"是正常状态，检查只会对 86 个历史会话误报）。
- `WorkspaceRegistry.delete()` 继续**零生产调用方**（它会 `rmtree` 用户仓库，ADR-0029 D2 硬性否决）。

---

## 4. 真机验收清单（两端齐备后，集成 AI 执行）

前置：备份 `harness.db`；用**临时 workspace** 或先确认待删会话不是要留的。

1. 建 3 个会话（其中 1 个放进项目 A），`GET /api/sessions` 看到 3 条；记下各自 `events` 数。
2. 删第 1 个 → 200 且 `events` 与删除前 `GET /api/sessions/{id}/events` 的长度一致；列表变 2 条；
   `sessions/<id>/`、`workspaces/<id>.json`、`workspaces/<id>/` 三个路径都没了；
   `harness.db` 里四张表（`session_meta` / `checkpoints` / `operations` / `workspace_sessions`）
   查不到该 id。
3. 再删同一个 id → **404**。
4. 删项目 A 里那个 → 200 且 `detached_from_projects = 1`；`GET /api/projects/{A}` 的
   `session_ids` 不再含它，**项目目录一个字没动**。
5. 造一个 `cwd` 指向**临时真实目录**（内有文件）的会话 → 删除后该目录与文件内容**逐字节不变**
   （这条是安全红线，已有自动化测试 `test_cwd_session_delete_never_touches_the_user_directory`）。
6. 有在途 run 的会话 → 409（文案是"has a run in flight"），且日志目录仍在。
7. fork 出一个子会话，删父 → 409 且 `detail` 里的数量是**真实数量**。
8. 用过子 Agent（委派）的会话 → 可正常删除；删完打开家谱图，不应出现 `(parent missing)`。
9. 跨源请求（`Origin: http://evil.example`）→ 403。
10. 审计：`agent.jsonl` 里有 `session_delete` 事件，字段只有 id 与计数（无会话内容）。

---

## 5. 关单纪律

- **#172 现在不关**：跨端票，前端半（二次确认 + 入口）未做。
- 后端半的事实已作为 comment 落在 #172 上（分支 + commit + 门禁数字 + 前端待做项）。
- 两端齐备、各自门禁通过、且合入 `main` 后，才按 §14.12 关单。
