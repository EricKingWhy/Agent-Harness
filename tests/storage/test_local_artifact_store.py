"""LocalArtifactStore 契约测试（#192）。

本地 Provider 是 spec 06 §3 的**默认** Provider。这里锁的不只是"能存能读"，还有
四条与远端 Provider 逐条对齐的契约（不一致就会让读取接口按部署方式给出不同行为）：

1. not-found / 非法 id / 内容被外部改动 → 统一 `KeyError`（三实现同契约，#185 AC3）；
2. 元数据"缺失即 None"，不伪造成空串（#185 AC4）；
3. 落盘形态 `{session_id}/{artifact_id}` 与对象存储键逐段同构；
4. 写入是原子的——半写文件会被 hash 校验判死，一个正常写入的 artifact 会变成永久不可读。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_harness.config import Settings
from agent_harness.storage.artifact import compute_artifact_id
from agent_harness.storage.local_artifact import (
    LocalArtifactStore,
    discard_local_artifacts,
)

SESSION = "sess-local-1"
CONTENT = "line-1\nline-2\nline-3\n"


def settings(tmp_path: Path, *, artifact_dir: str | None = None) -> Settings:
    return Settings(artifact_dir=artifact_dir if artifact_dir is not None else str(tmp_path / "artifacts"))


def store(tmp_path: Path, session_id: str = SESSION) -> LocalArtifactStore:
    return LocalArtifactStore(settings(tmp_path), session_id=session_id)


@pytest.mark.asyncio
class TestSave:
    async def test_content_hash_id_and_layout(self, tmp_path: Path) -> None:
        s = store(tmp_path)
        artifact = await s.save(
            SESSION, CONTENT, mime_type="text/plain", source_tool="bash", tool_call_id="tc-1"
        )
        assert artifact.artifact_id == compute_artifact_id(CONTENT)
        assert artifact.size == len(CONTENT.encode("utf-8"))
        # 落盘形态与对象存储的键 {session_id}/{artifact_id} 逐段同构
        assert (tmp_path / "artifacts" / SESSION / artifact.artifact_id).read_text(
            encoding="utf-8"
        ) == CONTENT

    async def test_metadata_roundtrips(self, tmp_path: Path) -> None:
        s = store(tmp_path)
        saved = await s.save(
            SESSION, CONTENT, mime_type="text/plain", source_tool="bash", tool_call_id="tc-1"
        )
        loaded = await s.load(saved.artifact_id)
        assert loaded.content == CONTENT
        assert loaded.mime_type == "text/plain"
        # 远端 Provider 存不下这三项只能给 None；本地存得下，就必须给真值
        assert loaded.source_tool == "bash"
        assert loaded.tool_call_id == "tc-1"
        assert loaded.created_at is not None

    async def test_save_rejects_foreign_session(self, tmp_path: Path) -> None:
        s = store(tmp_path)
        with pytest.raises(ValueError, match="must match the store namespace"):
            await s.save("other", CONTENT, mime_type="text/plain", source_tool="bash", tool_call_id="tc-1")

    async def test_no_temp_files_left_behind(self, tmp_path: Path) -> None:
        s = store(tmp_path)
        await s.save(SESSION, CONTENT, mime_type="text/plain", source_tool="bash", tool_call_id="tc-1")
        # 原子写的临时文件必须被 os.replace 消费或清掉——残留会污染会话目录（并且
        # 未来任何"按目录清理"的实现都会把它们当成 artifact）。
        leftovers = [p.name for p in (tmp_path / "artifacts" / SESSION).iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []


@pytest.mark.asyncio
class TestLoadContract:
    async def test_unknown_id_raises_key_error(self, tmp_path: Path) -> None:
        with pytest.raises(KeyError):
            await store(tmp_path).load("0" * 16)

    @pytest.mark.parametrize("bad", ["../../etc/passwd", "ZZZZZZZZZZZZZZZZ", "short", "", "0" * 15])
    async def test_malformed_id_raises_key_error(self, tmp_path: Path, bad: str) -> None:
        # 形态校验必须先于路径拼接（畸形 id 不得进入文件系统）
        with pytest.raises(KeyError):
            await store(tmp_path).load(bad)

    async def test_tampered_content_raises_key_error(self, tmp_path: Path) -> None:
        s = store(tmp_path)
        artifact = await s.save(
            SESSION, CONTENT, mime_type="text/plain", source_tool="bash", tool_call_id="tc-1"
        )
        (tmp_path / "artifacts" / SESSION / artifact.artifact_id).write_text("tampered", encoding="utf-8")
        # content-hash 自证：外改过的内容不得当成合法内容返回（与远端同口径 → 404）
        with pytest.raises(KeyError, match="hash mismatch"):
            await s.load(artifact.artifact_id)

    async def test_non_utf8_raises_key_error(self, tmp_path: Path) -> None:
        s = store(tmp_path)
        artifact = await s.save(
            SESSION, CONTENT, mime_type="text/plain", source_tool="bash", tool_call_id="tc-1"
        )
        (tmp_path / "artifacts" / SESSION / artifact.artifact_id).write_bytes(b"\xff\xfe\x00")
        with pytest.raises(KeyError, match="not valid UTF-8"):
            await s.load(artifact.artifact_id)

    async def test_missing_sidecar_yields_none_metadata(self, tmp_path: Path) -> None:
        s = store(tmp_path)
        artifact = await s.save(
            SESSION, CONTENT, mime_type="text/plain", source_tool="bash", tool_call_id="tc-1"
        )
        # 崩溃窗口的真实形态：内容已落盘、元数据未写。内容仍可读，元数据如实为 None。
        (tmp_path / "artifacts" / SESSION / f"{artifact.artifact_id}.json").unlink()
        loaded = await s.load(artifact.artifact_id)
        assert loaded.content == CONTENT
        assert loaded.source_tool is None
        assert loaded.tool_call_id is None
        assert loaded.created_at is None

    async def test_corrupt_sidecar_yields_none_metadata(self, tmp_path: Path) -> None:
        s = store(tmp_path)
        artifact = await s.save(
            SESSION, CONTENT, mime_type="text/plain", source_tool="bash", tool_call_id="tc-1"
        )
        (tmp_path / "artifacts" / SESSION / f"{artifact.artifact_id}.json").write_text("{not json", encoding="utf-8")
        loaded = await s.load(artifact.artifact_id)
        assert loaded.content == CONTENT
        assert loaded.source_tool is None

    async def test_metadata_values_are_not_faked_as_empty_string(self, tmp_path: Path) -> None:
        """元数据里存了空串 → 读出来是 None（空串不是"有值"，是缺失的伪装）。"""
        s = store(tmp_path)
        artifact = await s.save(
            SESSION, CONTENT, mime_type="text/plain", source_tool="bash", tool_call_id="tc-1"
        )
        meta_path = tmp_path / "artifacts" / SESSION / f"{artifact.artifact_id}.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["source_tool"] = ""
        meta["created_at"] = None  # 类型也不对
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        loaded = await s.load(artifact.artifact_id)
        assert loaded.source_tool is None
        assert loaded.created_at is None


@pytest.mark.asyncio
class TestInspect:
    async def test_slice_by_line_range_and_counts(self, tmp_path: Path) -> None:
        s = store(tmp_path)
        artifact = await s.save(
            SESSION, CONTENT, mime_type="text/plain", source_tool="bash", tool_call_id="tc-1"
        )
        sl = await s.inspect(artifact.artifact_id, start_line=2, end_line=3)
        assert [entry["text"] for entry in sl.lines] == ["line-2", "line-3"]
        assert sl.total_lines == 3
        assert sl.returned_lines == 2
        assert sl.truncated is False

    async def test_keyword_filter(self, tmp_path: Path) -> None:
        s = store(tmp_path)
        artifact = await s.save(
            SESSION, CONTENT, mime_type="text/plain", source_tool="bash", tool_call_id="tc-1"
        )
        sl = await s.inspect(artifact.artifact_id, keyword="line-2")
        assert [entry["line_number"] for entry in sl.lines] == [2]

    async def test_long_line_truncation_carries_full_length(self, tmp_path: Path) -> None:
        # 与 slice_lines 共享实现：超长单行被截断并携带 truncated/full_length
        long_line = "x" * 5000
        s = store(tmp_path)
        artifact = await s.save(
            SESSION, long_line, mime_type="text/plain", source_tool="bash", tool_call_id="tc-1"
        )
        sl = await s.inspect(artifact.artifact_id, max_chars_per_line=100)
        assert sl.lines[0]["truncated"] is True
        assert sl.lines[0]["full_length"] == 5000
        assert sl.truncated is True

    async def test_inspect_missing_artifact_raises_key_error(self, tmp_path: Path) -> None:
        with pytest.raises(KeyError):
            await store(tmp_path).inspect("0" * 16)


class TestConstructorGuards:
    def test_blank_artifact_dir_rejected(self) -> None:
        # artifact_dir 为空 = 显式关掉本地落盘；无法构造实例（读取接口据此回 503）
        with pytest.raises(ValueError, match="requires artifact_dir"):
            LocalArtifactStore(Settings(artifact_dir="   "), session_id=SESSION)

    @pytest.mark.parametrize("bad", ["../escape", "a/b", "a\\b", "", "C:", ".."])
    def test_path_traversal_session_id_rejected(self, tmp_path: Path, bad: str) -> None:
        """session 段会被拼进文件系统路径——不是名字段就必须在构造期拒绝。"""
        with pytest.raises(ValueError, match="single safe name segment"):
            LocalArtifactStore(settings(tmp_path), session_id=bad)


class TestDiscardLocalArtifacts:
    def test_removes_only_that_session(self, tmp_path: Path) -> None:
        root = tmp_path / "artifacts"
        (root / "sess-a").mkdir(parents=True)
        (root / "sess-a" / "abc").write_text("x", encoding="utf-8")
        (root / "sess-b").mkdir(parents=True)
        (root / "sess-b" / "abc").write_text("y", encoding="utf-8")

        discard_local_artifacts(Settings(artifact_dir=str(root)), "sess-a")

        assert not (root / "sess-a").exists()
        # 同内容跨会话是两个对象（键带 session 前缀）——删一个绝不影响另一个
        assert (root / "sess-b" / "abc").read_text(encoding="utf-8") == "y"

    def test_idempotent_on_missing_and_absent_root(self, tmp_path: Path) -> None:
        cfg = Settings(artifact_dir=str(tmp_path / "nope"))
        discard_local_artifacts(cfg, "sess-a")
        discard_local_artifacts(cfg, "sess-a")

    @pytest.mark.parametrize("bad", ["../escape", "a/b", "..", ""])
    def test_unsafe_session_id_is_noop(self, tmp_path: Path, bad: str) -> None:
        """只允许删"自己拼得出的路径"——非法 id 一律不动手（纵深防御）。"""
        root = tmp_path / "artifacts"
        root.mkdir(parents=True)
        (tmp_path / "secret.txt").write_text("must survive", encoding="utf-8")
        discard_local_artifacts(Settings(artifact_dir=str(root)), bad)
        assert (tmp_path / "secret.txt").read_text(encoding="utf-8") == "must survive"
        assert root.exists()

    def test_blank_artifact_dir_is_noop(self, tmp_path: Path) -> None:
        discard_local_artifacts(Settings(artifact_dir=""), "sess-a")
