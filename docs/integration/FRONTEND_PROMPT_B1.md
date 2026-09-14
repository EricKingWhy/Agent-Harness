# 前端 AI 执行手册 —— Ticket B1 集成后开 F1

> **发件方**：后端 AI（worktree `D:\intelligence-agent-backend`，分支 `feat/backend-d`）
> **收件方**：前端 AI（worktree `D:\intelligence-agent-frontend`，分支 `feat/frontend-d`）
> **日期**：2026-09-08
> **任务来源**：`D:\intelligence-agent\docs\integration\HANDOFF_REMAINING_TICKETS.md` — Ticket F1

---

## 0. 你的角色

你是前端 AI。你的职责是：
1. 等 Git Integrator 把 `feat/backend-d`（Ticket B1）集成入 `main`；
2. 从新 `main` 开 `feat/frontend-d` 分支做 F1（Phase 2b Composer control row）；
3. 完成后写一份集成交接单发给 Git Integrator。

**前置条件（阻塞）**：B1 必须先完成并集成入 main。确认标志：main 上存在 `GET /api/reasoning-efforts` / `GET /api/agent-profiles` / `GET /api/context-providers` 三个端点。

---

## 1. 后端契约（B1 已交付）

### 1.1 GET /api/reasoning-efforts

```json
{
  "efforts": [
    {
      "id": "minimal",
      "display_name": "Minimal",
      "description": "Least reasoning overhead; fastest but least thorough."
    },
    {
      "id": "standard",
      "display_name": "Standard",
      "description": "Balanced reasoning depth for typical tasks (default)."
    },
    {
      "id": "deep",
      "display_name": "Deep",
      "description": "Most reasoning overhead; slower but most thorough."
    }
  ]
}
```

### 1.2 GET /api/agent-profiles

```json
{
  "profiles": [
    {
      "id": "main",
      "display_name": "Main",
      "description": "General-purpose orchestrator agent (default)."
    },
    {
      "id": "coding",
      "display_name": "Coding",
      "description": "Specialized for code editing, debugging, and build tasks."
    },
    {
      "id": "research_review",
      "display_name": "Research & Review",
      "description": "Specialized for research, retrieval, and review tasks."
    }
  ]
}
```

### 1.3 GET /api/context-providers

```json
{
  "providers": []
}
```

当前诚实返空数组（runtime 尚未装配任何 context provider）。与 `/api/capabilities` 空目录降级同原则：空就是空，前端据空列表自行 fallback。

### 1.4 字段 schema 锁定

每个端点的 entry 结构固定为：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `str` | 提交到 `POST /api/sessions` 时用的值 |
| `display_name` | `str` | UI 标签 |
| `description` | `str` | tooltip |

顶层 key 用复数短名：`efforts` / `profiles` / `providers`。

### 1.5 与 POST /api/sessions 的关系

这三个字段在 `POST /api/sessions` 中是 **staged 契约**：
- API 边界验证通过（未知值 → 422）；
- 运行时记一条 INFO 日志后忽略（`received but not yet consumed by runtime`）。

**前端不应断言"已生效"**——控件只提交偏好到 `POST /api/sessions`，运行时是否消费由后端决定（当前 Phase 5 是 staged no-op）。

---

## 2. F1 交付物

在 Composer 区块加一行 control row，含四个选择器：

| 控件 | 数据源 | 当前 main 已有？ |
| --- | --- | --- |
| Model 选择器 | `GET /api/models` | ✅ 已有（Phase 2a ModelPicker 已消费） |
| Permission 模式 | `GET /api/permission-modes` | ✅ 端点已有，UI 待做 |
| Agent Profile | `GET /api/agent-profiles` | ❌ 等 B1（已交付） |
| Reasoning Effort | `GET /api/reasoning-efforts` | ❌ 等 B1（已交付） |
| Context Providers（多选） | `GET /api/context-providers` | ❌ 等 B1（已交付，且可能是空目录） |

### 2.1 约束

- **从新 main 开新 feature branch**（不在已合并的 `feat/frontend-c` 上继续，交接单 §8 明确约束）
- **ModelPicker 已就位，不要重写**：Phase 2a 已把 Model 升级为 Radix DropdownMenu，其余四个控件**复用同模式**（Radix DropdownMenu 或 Combobox + Portal + provider 分组 + 搜索 + 空目录隐藏入口 + Esc/Enter 冒泡满足 §19 + reduced-motion 守护满足 §18/§21）
- **空目录隐藏入口**（同 ModelPicker 原则）：`/api/context-providers` 返 `[]` 时隐藏 Context Providers 控件，不伪造
- **会话内真相仍是模型卡**：控件只提交偏好到 `POST /api/sessions`，运行时是否消费由后端决定（当前 Phase 5 是 staged no-op，UI 不应断言"已生效"）
- **Scope Lock（§8）**：只加 Composer control row，不动 Inspector / Workspace / Conversation 等既有区块
- **测试**：每个控件至少 ① 正常选项 ② 空目录隐藏 ③ 提交 payload 字段名对齐后端契约 三条
- **GUI QA**：6 档宽度（1440/1280/1024/820/768/浅色）回归，确认 control row 不破坏响应式布局

### 2.2 验收标准

- [ ] Composer control row 四个控件落地（Permission / Agent / Reasoning / Context Providers），复用 ModelPicker 模式
- [ ] 空目录隐藏入口行为一致
- [ ] 提交 payload 字段名与后端 `POST /api/sessions` 契约完全对齐
- [ ] tsc 干净 / oxlint 0 errors / Vitest 全绿 / build 成功
- [ ] GUI QA 6 档宽度 + 浅色模式 PASS
- [ ] 写一份集成交接单（变更摘要、验证证据、与 main 的正交性、冲突预测、两轮 code-review 结果）发给 Git Integrator

### 2.3 Worktree

- 前端 worktree：`D:\intelligence-agent-frontend`（或按 §13.1 另开）
- 分支命名：`feat/frontend-d`（或你与用户约定的命名）
- 从 `origin/main`（B1 集成后的新 main HEAD）开分支

---

## 3. 下一步

等待 Git Integrator 审核本交接单，做只读检查（worktree 状态、拓扑核验、merge-tree 冲突预测），然后集成入 main。

集成入 main 后，前端 AI 可从新 main 开 `feat/frontend-d` 分支做 F1（Phase 2b Composer control row）。
