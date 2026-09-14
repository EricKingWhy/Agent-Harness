# 交接单：sandbox/local.py Python 3.12+ 兼容性 bug 修复

## 改了什么

| 文件 | 改动 |
|---|---|
| `src/agent_harness/sandbox/local.py` | `read_text()` 方法从 `Path.read_text(encoding="utf-8", newline="")` 改为等价的 `open(resolved, "r", encoding="utf-8", newline="")` 写法 |
| `tests/tools/test_coding_tools.py` | 新增 `test_crlf_line_endings_preserved_on_read_write_cycle` 回归测试 |

## 根因

`pathlib.Path.read_text()` 的 `newline` 关键字参数是 Python 3.12+ 才加入的（PEP 436 backport）。项目 `pyproject.toml` 声明 `requires-python = ">=3.11"`，在 Python 3.11 上调用 `Path.read_text(encoding="utf-8", newline="")` 会抛：

```
TypeError: Path.read_text() got an unexpected keyword argument 'newline'
```

这导致 56 个 `tests/tools/` 测试在 Python 3.11 上全部失败（edit / grep / apply_patch / git_status / git_diff 五个 Coding Tools 全挂）。

同一文件的 `write_text()` 路径用的是 `open(tmp, "w", encoding="utf-8", newline="")`——这个没问题，`open()` 自古就支持 `newline`。问题只在 read 路径用了 `Path.read_text()`。

## 修复

最小修复：把 `local.py:325` 的

```python
return resolved.read_text(encoding="utf-8", newline="")
```

改为等价的 `open()` 写法：

```python
with open(resolved, "r", encoding="utf-8", newline="") as f:
    return f.read()
```

不改注释语义、不改函数签名、不改 `newline=""` 的行为意图。`local.py:340` 的 write 路径不用动（它已经是 `open()` 写法）。

## 回归测试

新增 `test_crlf_line_endings_preserved_on_read_write_cycle`：
- 直接用 `open()` 写入 CRLF 原始字节，绕过 `sandbox.write_text` 的 `newline=""`
- 断言 `sandbox.read_text()` 原样返回 CRLF
- 断言 `write_text → read` 往返也不变

防止有人未来又改回 `Path.read_text()` 导致复发。

## 验收

| 检查项 | 结果 |
|---|---|
| `uv run pytest tests/tools/ -q` | **104 passed** |
| `uv run ruff check src/ tests/` | **All checks passed!** |
| `git diff --check` | 干净（仅 LF→CRLF Git 警告，无冲突标记） |
| 全量 `uv run pytest -q` | **1361 passed / 9 skipped / 39 deselected**，零失败 |

## Scope Lock

- 只修这一个 bug（`local.py:325`）
- 不顺手重构 sandbox
- 不改 `requires-python` 或 `.python-version`
- 不改 `newline=""` 的语义
- 不清理其他文件的 `Path.read_text()`（grep 确认 `local.py:325` 是唯一使用 `read_text(newline="")` 的位置）

## 影响范围

- **Python 3.11 用户**：修复后 56 个 tools 测试不再失败
- **Python 3.13 用户**：行为不变（`open()` 和 `Path.read_text()` 在 3.13 上语义相同）
- **无 API 变更**：`read_text()` 方法签名和返回值不变
