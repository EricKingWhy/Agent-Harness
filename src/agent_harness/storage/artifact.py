"""ArtifactStore：大输出的持久化边界（content-hash 寻址）。

为什么独立成 artifact.py：
- ToolResult 的主输出字段溢出时，原始内容存到这里，模型只拿截断摘要 + artifact_ref。
- 与 SessionEvent（对话历史）和 Operation Ledger（操作状态）不同种类的事实：
  SessionEvent 记"对话发生了什么"，Ledger 记"每次调用现在什么状态"，
  ArtifactStore 记"大输出本身存在哪、怎么找回"。

为什么 content-hash 寻址：
- 同一内容自动去重（两个 Tool 产出相同的 stdout 只存一份）；
- 寻址不需要额外 ID 生成器——hash 就是 ID；
- 跨 Session 理论上可共享（相同内容同 hash），但 Phase 5 按 session 隔离 key。

物理位置：Runtime 域存储，不经过 Sandbox（spec 06 §3 + ADR-0006）。
默认 Provider：LocalArtifactStore（spec 06 §3：Local filesystem，开发/小型部署）。
远端 Provider：S3ArtifactStore（七牛云 Kodo S3 兼容）/ MinioArtifactStore。
测试 Provider：FakeArtifactStore（内存 dict）。
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod

from pydantic import BaseModel

#: artifact_id 的唯一形态：`sha256(content)[:16]`，16 位小写十六进制。
#: 两个远端 provider（S3 / MinIO）与 web 读接口共用这一份定义——此前 S3 内联正则、
#: MinIO 干脆不校验，两边行为不一致（#185 AC3）。
ARTIFACT_ID_PATTERN = re.compile(r"[0-9a-f]{16}")

#: artifact 存储键里 session 段的安全形态：**单个名字段，不是路径**。
#: 三个 Provider 的键都是 `{session_id}/{artifact_id}`；本地 Provider 要把它拼进文件
#: 系统路径，不校验时 `..` / 反斜杠段 / 盘符段都能越出 artifact 根目录（ADR-0029 D2
#: 的"路径穿越防护"同款问题）。
#: 规则本体放这里而不是 session 层：`session/service.py` 的 `_SESSION_ID_PATTERN`
#: 注释写的就是"字符集与 S3ArtifactStore 的 key 段规则一致"——同一条规则，一份定义。
SESSION_KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


class Artifact(BaseModel):
    """一个 Artifact 的元数据 + 可选内容。"""

    artifact_id: str
    session_id: str
    size: int
    mime_type: str
    # 元数据"缺失即 None"，不得伪造成空串/默认值（#185 AC4）：MinIO 实现的 save 不
    # 持久化这三项，load 也无从恢复——填 "" 会让调用方以为"产物来自某工具，只是 id
    # 为空"。None 才是"本存储没存这一项"的如实表达。
    source_tool: str | None = None
    tool_call_id: str | None = None
    created_at: str | None = None
    content: str | None = None  # load() 时填充；inspect() 不填充


class ArtifactSlice(BaseModel):
    """inspect() 的局部读取结果。

    truncated 含义是"返回内容不完整"的并集：行数截断或字符截断任一发生即为 True。
    单行超长时该行按 max_chars 截断，原文始终完整保留在 Artifact 里，
    模型可凭 line_number 重新定位（spec 06 §4：大 Artifact 不完整灌回 Context）。
    """

    artifact_id: str
    lines: list[dict[str, int | str | bool]]
    total_lines: int
    returned_lines: int
    truncated: bool
    query: dict[str, int | str | None]


class ArtifactStore(ABC):
    """Artifact 的持久化边界（async ABC）。"""

    @abstractmethod
    async def save(
        self,
        session_id: str,
        content: str,
        *,
        mime_type: str,
        source_tool: str,
        tool_call_id: str,
    ) -> Artifact:
        """存内容，返回带 artifact_id (content-hash) 的 Artifact 元数据。"""

    @abstractmethod
    async def load(self, artifact_id: str) -> Artifact:
        """完整加载一个 Artifact（内容 + 元数据）。"""

    @abstractmethod
    async def inspect(
        self,
        artifact_id: str,
        *,
        start_line: int | None = None,
        end_line: int | None = None,
        keyword: str | None = None,
        max_lines: int = 200,
        max_chars_per_line: int = 2000,
    ) -> ArtifactSlice:
        """按行范围或关键词读取局部内容。

        max_chars_per_line 限制单行返回字符数，防止单条超长行灌爆 Context；
        截断行额外携带 truncated=True 与 full_length，原文始终保留在 Artifact 里。
        """


def compute_artifact_id(content: str) -> str:
    """content-hash 寻址：SHA-256 前 16 字符作为 artifact_id。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def slice_lines(
    all_lines: list[str],
    *,
    start_line: int | None,
    end_line: int | None,
    keyword: str | None,
    max_lines: int,
    max_chars_per_line: int = 2000,
) -> tuple[list[dict[str, int | str | bool]], bool]:
    """通用行切片逻辑：**artifact 的四个 Provider（Fake / S3 / MinIO / Local）+ Web 工作区文件读取**共用这一份。

    （原为模块私有 `_slice_lines`；#191 的 `GET .../workspace/file` 需要同一套
    "从第 N 行起 / 最多 N 行 / 单行超长怎么标"的语义 ⇒ 提升为公开函数——
    与其在 web 层再写一份切片，不如让两处消费同一个实现。）

    返回 (行列表, truncated)。truncated 是行数截断与字符截断的并集——
    任一发生即 True（spec 06 §4：大 Artifact 不完整灌回 Context）。

    每个超长行按 max_chars_per_line 截断，原文始终完整保留在 Artifact / 文件里。
    截断行额外携带 truncated=True 与 full_length 字段，调用方可凭 line_number
    重新定位（如经 max_chars_per_line 参数放宽上限继续读）。
    """
    indexed = [{"line_number": i + 1, "text": line} for i, line in enumerate(all_lines)]

    if keyword:
        filtered = [entry for entry in indexed if keyword in entry["text"]]
    else:
        s = (start_line or 1) - 1  # 转 0-based
        e = end_line if end_line is not None else len(indexed)
        filtered = indexed[s:e]

    char_truncated = False
    capped: list[dict[str, int | str | bool]] = []
    for entry in filtered:
        text = entry["text"]
        if len(text) > max_chars_per_line:
            char_truncated = True
            capped.append({
                "line_number": entry["line_number"],
                "text": text[:max_chars_per_line],
                "truncated": True,
                "full_length": len(text),
            })
        else:
            capped.append(entry)

    truncated = char_truncated or len(filtered) > max_lines
    return capped[:max_lines], truncated


def slice_artifact(
    artifact_id: str,
    content: str,
    *,
    start_line: int | None = None,
    end_line: int | None = None,
    keyword: str | None = None,
    max_lines: int = 200,
    max_chars_per_line: int = 2000,
) -> ArtifactSlice:
    """`inspect()` 的整段实现：切片 + 组装 ArtifactSlice。

    四个 Provider 的 `inspect()` 差别只在"怎么拿到 content"（内存 dict / S3 / MinIO /
    本地文件），拿到之后这一段逐字相同。此前四份各自复制，`query` 回显字段与
    `total_lines` 的语义就有四处各自演化的空间——现在只有这里一份，
    Provider 只负责 `load()` 后把 content 交进来。
    """
    all_lines = content.splitlines()
    lines, truncated = slice_lines(
        all_lines,
        start_line=start_line,
        end_line=end_line,
        keyword=keyword,
        max_lines=max_lines,
        max_chars_per_line=max_chars_per_line,
    )
    return ArtifactSlice(
        artifact_id=artifact_id,
        lines=lines,
        total_lines=len(all_lines),
        returned_lines=len(lines),
        truncated=truncated,
        query={
            "start_line": start_line,
            "end_line": end_line,
            "keyword": keyword,
            "max_lines": max_lines,
        },
    )


class FakeArtifactStore(ArtifactStore):
    """内存 dict 实现——给单元测试用。不碰网络。"""

    def __init__(self) -> None:
        self._artifacts: dict[str, tuple[Artifact, str]] = {}  # id → (meta, content)

    async def save(
        self,
        session_id: str,
        content: str,
        *,
        mime_type: str,
        source_tool: str,
        tool_call_id: str,
    ) -> Artifact:
        from agent_harness.storage.sqlite import _utc_now_iso

        artifact_id = compute_artifact_id(content)
        artifact = Artifact(
            artifact_id=artifact_id,
            session_id=session_id,
            size=len(content.encode("utf-8")),
            mime_type=mime_type,
            source_tool=source_tool,
            tool_call_id=tool_call_id,
            created_at=_utc_now_iso(),
        )
        self._artifacts[artifact_id] = (artifact, content)
        return artifact

    async def load(self, artifact_id: str) -> Artifact:
        if artifact_id not in self._artifacts:
            raise KeyError(f"Artifact '{artifact_id}' does not exist")
        meta, content = self._artifacts[artifact_id]
        return meta.model_copy(update={"content": content})

    async def inspect(
        self,
        artifact_id: str,
        *,
        start_line: int | None = None,
        end_line: int | None = None,
        keyword: str | None = None,
        max_lines: int = 200,
        max_chars_per_line: int = 2000,
    ) -> ArtifactSlice:
        if artifact_id not in self._artifacts:
            raise KeyError(f"Artifact '{artifact_id}' does not exist")
        _meta, content = self._artifacts[artifact_id]
        return slice_artifact(
            artifact_id,
            content,
            start_line=start_line,
            end_line=end_line,
            keyword=keyword,
            max_lines=max_lines,
            max_chars_per_line=max_chars_per_line,
        )
