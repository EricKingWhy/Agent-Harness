"""FakeArtifactStore + compute_artifact_id + slice_lines 单元测试。

验证 ArtifactStore 契约：
- save → load 往返（content-hash 寻址正确）
- inspect 按行范围
- inspect 按关键词
- max_lines 截断
- 去重（同内容同 ID）
- max_chars_per_line 单行体积上限（防止单条超长行灌爆 Context）
"""

from __future__ import annotations

import pytest

from agent_harness.storage.artifact import (
    ArtifactSlice,
    ArtifactStore,
    FakeArtifactStore,
    compute_artifact_id,
    slice_lines,
)


class TestComputeArtifactId:
    def test_deterministic(self) -> None:
        assert compute_artifact_id("hello") == compute_artifact_id("hello")

    def test_different_content_different_id(self) -> None:
        assert compute_artifact_id("hello") != compute_artifact_id("world")

    def test_id_length(self) -> None:
        assert len(compute_artifact_id("anything")) == 16


class TestFakeArtifactStoreSave:
    @pytest.mark.asyncio
    async def test_save_returns_artifact_with_correct_id(self) -> None:
        store = FakeArtifactStore()
        content = "line1\nline2\nline3"
        artifact = await store.save(
            "session-1", content,
            mime_type="text/plain",
            source_tool="bash",
            tool_call_id="call-1",
        )
        assert artifact.artifact_id == compute_artifact_id(content)
        assert artifact.session_id == "session-1"
        assert artifact.size == len(content.encode("utf-8"))
        assert artifact.mime_type == "text/plain"
        assert artifact.source_tool == "bash"
        assert artifact.tool_call_id == "call-1"
        assert artifact.created_at  # non-empty ISO string
        assert artifact.content is None  # save 不填充 content

    @pytest.mark.asyncio
    async def test_save_dedup_same_content_same_id(self) -> None:
        store = FakeArtifactStore()
        a1 = await store.save("s1", "same", mime_type="text/plain", source_tool="bash", tool_call_id="c1")
        a2 = await store.save("s2", "same", mime_type="text/plain", source_tool="read", tool_call_id="c2")
        assert a1.artifact_id == a2.artifact_id


class TestFakeArtifactStoreLoad:
    @pytest.mark.asyncio
    async def test_load_returns_content(self) -> None:
        store = FakeArtifactStore()
        content = "hello\nworld"
        artifact = await store.save("s1", content, mime_type="text/plain", source_tool="bash", tool_call_id="c1")
        loaded = await store.load(artifact.artifact_id)
        assert loaded.content == content
        assert loaded.artifact_id == artifact.artifact_id

    @pytest.mark.asyncio
    async def test_load_nonexistent_raises(self) -> None:
        store = FakeArtifactStore()
        with pytest.raises(KeyError):
            await store.load("nonexistent")


class TestFakeArtifactStoreInspect:
    @staticmethod
    async def _make_store() -> tuple[FakeArtifactStore, str]:
        store = FakeArtifactStore()
        lines = [f"line {i}" for i in range(1, 101)]  # 100 行
        content = "\n".join(lines)
        artifact = await store.save("s1", content, mime_type="text/plain", source_tool="bash", tool_call_id="c1")
        return store, artifact.artifact_id

    @pytest.mark.asyncio
    async def test_inspect_default_returns_first_200_lines(self) -> None:
        store, artifact_id = await self._make_store()
        result = await store.inspect(artifact_id)
        assert isinstance(result, ArtifactSlice)
        assert result.total_lines == 100
        assert result.returned_lines == 100  # 100 < 200，不截断
        assert result.truncated is False
        assert result.lines[0] == {"line_number": 1, "text": "line 1"}
        assert result.lines[99] == {"line_number": 100, "text": "line 100"}

    @pytest.mark.asyncio
    async def test_inspect_line_range(self) -> None:
        store, artifact_id = await self._make_store()
        result = await store.inspect(artifact_id, start_line=10, end_line=20)
        assert result.returned_lines == 11
        assert result.lines[0] == {"line_number": 10, "text": "line 10"}
        assert result.lines[-1] == {"line_number": 20, "text": "line 20"}

    @pytest.mark.asyncio
    async def test_inspect_keyword_filter(self) -> None:
        store, artifact_id = await self._make_store()
        result = await store.inspect(artifact_id, keyword="5")
        # line 5, 15, 25, ..., 95 → 含 "5" 的行
        assert all("5" in entry["text"] for entry in result.lines)
        assert result.returned_lines == len(result.lines)

    @pytest.mark.asyncio
    async def test_inspect_max_lines_truncation(self) -> None:
        store, artifact_id = await self._make_store()
        result = await store.inspect(artifact_id, max_lines=10)
        assert result.returned_lines == 10
        assert result.truncated is True

    @pytest.mark.asyncio
    async def test_inspect_nonexistent_raises(self) -> None:
        store, _ = await self._make_store()
        with pytest.raises(KeyError):
            await store.inspect("nonexistent")


def test_artifact_store_is_abstract() -> None:
    """ArtifactStore 是 ABC，不能直接实例化。"""
    with pytest.raises(TypeError):
        ArtifactStore()  # type: ignore[abstract]


class TestSliceLinesCharCap:
    """单行体积上限：防止单条超长行灌爆 Context（spec 06 §4）。"""

    def test_single_long_line_is_truncated(self) -> None:
        """场景 1：单条超长行（十万字符）被默认上限截断，并保留定位信息。"""
        long_line = "x" * 100_000
        lines, truncated = slice_lines(
            [long_line], start_line=None, end_line=None, keyword=None, max_lines=200,
        )
        assert truncated is True
        assert len(lines) == 1
        entry = lines[0]
        assert entry["line_number"] == 1
        assert entry["truncated"] is True
        assert entry["full_length"] == 100_000
        assert len(entry["text"]) == 2000  # 默认 max_chars_per_line
        assert entry["text"] == "x" * 2000

    def test_multiple_medium_lines_each_truncated(self) -> None:
        """场景 2：多条中长行（各自 5000 字符），每条独立截断并标记。"""
        medium_lines = [("y" * 5000) for _ in range(5)]
        lines, truncated = slice_lines(
            medium_lines, start_line=None, end_line=None, keyword=None, max_lines=200,
        )
        assert truncated is True
        assert len(lines) == 5
        for entry in lines:
            assert entry["truncated"] is True
            assert entry["full_length"] == 5000
            assert len(entry["text"]) == 2000

    def test_normal_short_lines_unchanged(self) -> None:
        """场景 3：正常短片段——无 char 截断，无额外字段，回归现有契约。"""
        lines, truncated = slice_lines(
            ["short", "another"], start_line=None, end_line=None, keyword=None, max_lines=200,
        )
        assert truncated is False
        assert lines == [
            {"line_number": 1, "text": "short"},
            {"line_number": 2, "text": "another"},
        ]

    def test_custom_max_chars_per_line(self) -> None:
        """自定义上限：模型可针对特定 artifact 放宽（escalate）以读更多内容。"""
        long_line = "z" * 8000
        lines, _ = slice_lines(
            [long_line], start_line=None, end_line=None, keyword=None,
            max_lines=200, max_chars_per_line=5000,
        )
        assert len(lines[0]["text"]) == 5000
        assert lines[0]["truncated"] is True
        assert lines[0]["full_length"] == 8000

    def test_row_and_char_truncation_combine(self) -> None:
        """行数截断与字符截断并存时 truncated=True，两者都生效。"""
        many_long = [("w" * 3000) for _ in range(20)]
        lines, truncated = slice_lines(
            many_long, start_line=None, end_line=None, keyword=None, max_lines=5,
        )
        assert truncated is True
        assert len(lines) == 5  # 行数上限生效
        assert all(entry["truncated"] for entry in lines)  # 字符上限也生效


class TestFakeArtifactStoreInspectCharCap:
    @pytest.mark.asyncio
    async def test_inspect_single_long_line_truncated(self) -> None:
        """端到端：FakeArtifactStore.inspect 单条超长行受控。"""
        store = FakeArtifactStore()
        long_content = "a" * 100_000
        artifact = await store.save(
            "s1", long_content, mime_type="text/plain", source_tool="bash", tool_call_id="c1",
        )
        result = await store.inspect(artifact.artifact_id)
        assert result.truncated is True
        assert result.returned_lines == 1
        assert result.lines[0]["truncated"] is True
        assert result.lines[0]["full_length"] == 100_000
        assert len(result.lines[0]["text"]) == 2000

    @pytest.mark.asyncio
    async def test_inspect_original_content_preserved(self) -> None:
        """截断不破坏 Artifact 原文——load 仍能取回完整内容（spec 06 §4）。"""
        store = FakeArtifactStore()
        long_content = "b" * 50_000
        artifact = await store.save(
            "s1", long_content, mime_type="text/plain", source_tool="bash", tool_call_id="c1",
        )
        await store.inspect(artifact.artifact_id)
        loaded = await store.load(artifact.artifact_id)
        assert loaded.content == long_content
