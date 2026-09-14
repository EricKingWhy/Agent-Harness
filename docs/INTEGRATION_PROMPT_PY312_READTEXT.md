# 集成提示词：sandbox/local.py Python 3.11 兼容性修复

> **收件人**：集成 AI（Git Integrator 角色，AGENTS.md §14）
> **任务**：把 `feat/backend` tip `f17fa49`（1 commit）合入 `main`
> **写于**：2026-09-08
> **红线**：永不 force-push / rebase / reset --hard；凭证零泄漏；每次合并动作前确认 worktree 与分支（§14.2）；冲突后立即停止自动解决（§14.7）

---

## 0. 改了什么

| 文件 | 改动 |
|---|---|
| `src/agent_harness/sandbox/local.py` | `read_text()` 从 `Path.read_text(encoding="utf-8", newline="")` 改为等价 `open(resolved, "r", encoding="utf-8", newline="")` 写法 |
| `tests/tools/test_coding_tools.py` | 新增 `test_crlf_line_endings_preserved_on_read_write_cycle` 回归测试 |
| `docs/integration/BACKEND_PY312_READTEXT_HANDOFF.md` | 交接单 |

## 1. 根因

`pathlib.Path.read_text()` 的 `newline` 关键字参数是 Python 3.12+ 才加入的（PEP 436 backport）。项目声明 `requires-python = ">=3.11"`，在 Python 3.11 上调用会抛：

```
TypeError: Path.read_text() got an unexpected keyword argument 'newline'
```

这导致 56 个 `tests/tools/` 测试在 Python 3.11 上全部失败。同一文件的 `write_text()` 路径已经是 `open()` 写法，不用动。

## 2. 修复

最小修复——把 `local.py:325` 的 `Path.read_text(encoding="utf-8", newline="")` 改为等价的 `open(resolved, "r", encoding="utf-8", newline="")` 写法。`newline=""` 字节透传语义不变（CRLF 不被折叠成 LF）。

回归测试：直接用 `open()` 写入 CRLF 原始字节 → 断言 `sandbox.read_text()` 原样返回 → `write_text → read` 往返也不变。防止有人未来又改回 `Path.read_text()` 导致复发。

## 3. Scope Lock

- 只修这一个 bug（`local.py:325`）
- 不顺手重构 sandbox
- 不改 `requires-python` 或 `.python-version`
- 不改 `newline=""` 的语义
- 不清理其他文件的 `Path.read_text()`（grep 确认 `local.py:325` 是唯一使用 `read_text(newline="")` 的位置）

## 4. 验收

| 检查项 | 结果 |
|---|---|
| `uv run pytest tests/tools/ -q` | **104 passed** |
| `uv run ruff check src/ tests/` | **All checks passed!** |
| `git diff --check` | 干净 |
| 全量 `uv run pytest -q` | **1361 passed / 9 skipped / 39 deselected**，零失败 |

## 5. 集成步骤

```bash
# A. 预检查
cd D:\intelligence-agent
git fetch origin --prune
git -C D:\intelligence-agent-backend status --short   # 必须干净
git worktree list --porcelain

# B. 先回后正
git -C D:\intelligence-agent-backend merge origin/main   # 预期干净
git -C D:\intelligence-agent merge --no-ff feat/backend -m "merge(backend): fix sandbox local.py Python 3.11 compat — Path.read_text(newline='') → open()"

# C. 验证 Gate（main 侧为准）
cd D:\intelligence-agent
uv sync --all-extras
uv run pytest -q              # 基线：1361 passed / 9 skipped / 39 deselected，零失败
uv run ruff check src/ tests/
git diff --check

# D. Push 与收尾
git push origin main
# docs/PHASE_STATUS.md 追加集成记录条目
```

## 6. 冲突预测

**预期零冲突**。本 commit 只改 `src/agent_harness/sandbox/local.py` 和 `tests/tools/test_coding_tools.py`，均为 feat/backend 独有路径，不与 main 交叉。

若出现冲突，最可能在 `docs/PHASE_STATUS.md`（追加行并集）——按 §14.7 逐文件分析，语义并集，不得机械取边。

## 7. 异常处理

- 任何预期外冲突 → 停下报告用户（§14.7）
- 测试失败 → 如实记录失败原因，不得掩盖
