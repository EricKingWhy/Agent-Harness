# 前端同步交接 — feat/backend 硬化批次（Round 5-8 + 用户拍板批）

> 交给：前端 AI（D:\intelligence-agent-frontend，feat/frontend）
> 后端基线：`feat/backend` HEAD `5d30fb7`（714 passed，ruff clean）
> 你的边界：只在前端 worktree 工作；不合并 main；不修改后端代码；
> 后端 API 事实以下述内容为准（如需实证，起本地后端联调验证）。

## 1. 本批后端对前端的全部影响（无破坏性缺口，均为增量）

### 1.1 新端点：POST /api/sessions/{session_id}/recover

恢复一个崩溃/中断的 session（修复 dangling tool_call、按 Ledger 回填结果）。

- `200` → 返回该 session 的**全部事件数组**（与 `GET /api/sessions/{id}/events` 同构）
  ——前端拿到后直接整表重建视图即可（与刷新路径同一渲染管线）。
- `404` → session 不存在（`{"detail": "session '...' not found"}`）。
- `409` → 存在需要**人工裁决**的高风险操作（`detail` 说明原因，不变量 #14：
  不伪造、不盲跑）。UI 应展示"需要人工裁决"状态，本期不需要实现裁决交互
  （裁决是 WebSocket/pending queue 的后续 ticket）。
- **幂等**：重复调用安全（已修复项自动跳过）。
- 建议 UI：Session 详情页加"恢复"入口（可见条件：最后事件非 run/completed），
  409 时显示不可恢复原因。恢复后的新事件以 `session/resumed` 事件为界。

### 1.2 认证语义变更（fail-closed，⚠️ 需要前端适配）

后端 `auth_seam` 行为分两种模式：

- **配置了 `JWT_SECRET`**（生产/共享部署）：
  - 所有 `/api/*` 请求**必须**携带 `Authorization: Bearer <HS256 token>`；
  - 匿名请求 → `401 {"detail": "Missing identity token"}`；
  - token claims：`tenant_id`、`user_id` 必填，`scopes` 可选（默认 ["user","session"]），
    **`exp` 必填且未过期**（无 exp 的合法签名 token 也 401）。
  - 前端需要：token 获取/存储/刷新策略的接缝（本期可先做"配置 token"的开发者设置项）。
- **未配置 `JWT_SECRET`**（本地开发）：一切照旧，无 token 可用（本地信任模式），
  后端启动时会打告警日志。

注意：`GET /api/sessions/{id}/events` 现在对非法 session_id（含路径字符）返回 422。

### 1.3 工具结果新形状（StepDetail / Trace 渲染相关）

- **read 工具**（`tool_result.data`）：
  - 大文件截断：`content` 尾部带标记
    `[Showing lines 1-2000 of 5000. Use offset=2001 to continue.]`，
    并新增 `total_lines` 字段；`offset` 是 read 的新参数（1-based 起始行）。
    UI 可把标记渲染成"续读"提示/按钮（填充下一次 tool call 的 offset）。
  - 超长单行：`[Line N truncated at 51200 bytes. …]`（不可续读）。**解析只认前缀
    `[Line {n} truncated at {bytes} bytes` 与结尾 `]`，中间措辞可变**——OBS-016 后
    正文已改为解释器无关的表述（旧文案教模型用 `sed`/`head -c`，在 Windows cmd.exe
    下不存在）；而**历史会话里仍是旧文案**，`LINE_TRUNCATED_RE` 的 `[^\]]*` 必须
    同时容忍两种。
  - 空文件：`content: ""` + `total_lines: 0`（正常成功）。
- **grep 工具**：匹配行可能以 `... [truncated]` 结尾（单行 >500 字符被截）。
- **bash 工具**：`data` 可能新增 `"cancelled": true`（命令被超时/断连取消，
  进程树已终止）——渲染为"已取消"状态而非普通失败。
- run/completed 语义收紧：模型零产出（内容过滤/上游静默失败）现在以
  `model/failed` + `run/failed` 收尾（不再出现"成功但空回答"）——
  失败原因展示已有管线可直接复用。
- `memory/degraded` 事件现在带 `run_id`（可归因到具体 run）。

### 1.4 后端内部（前端无感，但联调时可能注意到）

- 新增 `harness.db`（SQLite，三张表：operations/checkpoints/session_meta）——
  若从旧版本升级启动报错，删除该文件即可（后端会响亮提示）。
- bash 子进程默认以环境变量白名单运行（前端若在 UI 提供环境变量文档需同步）。

## 2. 建议任务清单（按优先级）

1. **Auth 接缝**：开发者设置项配置 Bearer token；所有 fetch/SSE 调用统一注入
   `Authorization` 头；401 全局处理（提示配置 token）。
2. **Recover 入口**：详情页"恢复"按钮 + 200/404/409 三态渲染。
3. **工具结果标记消费**：read 续读提示（offset 填充）、bash cancelled 态、
   grep 截断尾巴的省略渲染。
4. 其余前端 backlog 不变（以你们 INTEGRATION_NOTES.md 为准）。

## 3. 验收标准

- 本地（无 JWT_SECRET）全功能回归通过；
- 配置 JWT_SECRET 后：无 token 全部 401 且 UI 有清晰引导，带合法 token 全功能可用；
- recover 三态（200 重建 / 404 / 409）可见；
- 不引入第二套会话真相（不变量 #22：一切以事件流投影）。
