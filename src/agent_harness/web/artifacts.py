"""artifact 内容读取的 web 侧接线（#185）。

**为什么单独一个模块**：路由需要"按 session 构造一个只读 store"，而 store 的构造
口径（配了哪种对象存储、用哪个 session 前缀）原本只存在于 `assembly.build_runtime`
——那是**写路径**的装配点。把"读 store 怎么造"独立出来，路由才有一个可被测试替换的
接缝（与 `assembly.build_runtime` 的补丁口径一致）。

**store 选择口径**：**不在这里判断**——`storage/artifact_select.py::select_artifact_store`
是唯一选择器，写路径（`assembly.build_runtime`）与这里调用的是同一个函数。此前这里与
写路径各有一份 if 级联，审查（#192 批 1）按"必须逐条对应却靠人工保持同步"把它收成一份：
两份级联只要有一处漏改，就会出现"写进了 A、从 B 读"的静默错配。

`None` = 这个部署确实没有可用的 store（未配置对象存储、`artifact_dir` 置空、或对象存储
**半配置**）。调用方据此**如实**返回 503，不得伪装成 404。

**artifact_id 是内容哈希**（`sha256(content)[:16]`），跨会话可重复：所以归属只能由
URL 里的 `session_id` 决定（provider 的 key 前缀是 `{session_id}/{artifact_id}`）。
"""

from __future__ import annotations

from agent_harness.config import Settings
from agent_harness.storage.artifact import ARTIFACT_ID_PATTERN, ArtifactStore
from agent_harness.storage.artifact_select import select_artifact_store

#: 单次响应的服务端上限：客户端给多大都会夹到这个范围内（响应体积可控）。
MAX_LINES_CAP = 1000
MAX_CHARS_PER_LINE_CAP = 2000

__all__ = [
    "ARTIFACT_ID_PATTERN",
    "MAX_CHARS_PER_LINE_CAP",
    "MAX_LINES_CAP",
    "build_read_artifact_store",
    "clamp_to_cap",
]


def build_read_artifact_store(settings: Settings, session_id: str) -> ArtifactStore | None:
    """按会话构造只读 artifact store；本部署没有可用 store 时返回 `None`。

    只取选择器里的 `store`：读路径不注册工具（那是写路径装配的事），所以这里不需要
    `read_tool`。选择逻辑与其优先级/半配置判定全部由 `select_artifact_store` 承担。
    """
    selection = select_artifact_store(settings, session_id)
    return None if selection is None else selection.store


def clamp_to_cap(value: int, cap: int) -> int:
    """把客户端给的行数/字符数夹进 `[1, cap]`（0 或负数没有意义，同样夹到 1）。"""
    return max(1, min(value, cap))
