"""工具侧 diff 数据辅助（Phase 9 / Web UI 用）。

EditTool / ApplyPatchTool / WriteTool 成功后，把 before/after 文本塞进
ToolResult.data，让前端能渲染 diff 双栏视图（Q12=B 决策）。

设计：
- 直接存完整文本（不在这里算 unified diff）——diff 是视图层职责，后端只给原料。
- 超过 _DIFF_MAX_BYTES 的文件只存前后各 _DIFF_HEAD_BYTES 的截断 + truncated=True
  标记，避免 ToolResult 膨胀成 MB 级（spec 12 §2：oversized output 不进单条日志）。
- before 对新文件（write 创建）是空字符串。
"""

from __future__ import annotations

_DIFF_MAX_BYTES = 50_000
_DIFF_HEAD_BYTES = 5_000


def diff_data(before: str, after: str) -> dict:
    """构造 {before, after, truncated} 给 ToolResult.data 合并用。

    小文件（≤ _DIFF_MAX_BYTES）原样返回；大文件只存前后截断 + truncated=True。
    """
    if len(before) <= _DIFF_MAX_BYTES and len(after) <= _DIFF_MAX_BYTES:
        return {"before": before, "after": after, "truncated": False}
    return {
        "before": before[:_DIFF_HEAD_BYTES],
        "after": after[:_DIFF_HEAD_BYTES],
        "truncated": True,
    }
