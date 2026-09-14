# AI Worktree 使用指南

只记住三件事：

| 用途 | 在软件中打开的文件夹 | 分支 |
| --- | --- | --- |
| 最终合并和测试 | `D:\intelligence-agent` | `main` |
| 后端开发 | `D:\intelligence-agent-backend` | `feat/backend` |
| 前端开发 | `D:\intelligence-agent-frontend` | `feat/frontend` |

- Codex 或 Zcode 做后端：打开 `D:\intelligence-agent-backend`。
- Codex 或 Zcode 做前端：打开 `D:\intelligence-agent-frontend`。
- 两个 AI 会话不要打开同一个 Worktree，也不要在原始 `main` 目录长期开发。
- 开工前运行 `git branch --show-current`，确认分支正确。
- 完成后先在开发 Worktree 提交，再到 `D:\intelligence-agent` 合并：`git merge feat/backend` 或 `git merge feat/frontend`。
- 合并前查看改动：`git diff main...feat/backend` 或 `git diff main...feat/frontend`。
