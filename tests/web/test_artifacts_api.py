"""#185：`GET /api/sessions/{session_id}/artifacts/{artifact_id}` —— 外置内容只读读取。

外置（overflow）产物是**被截断的大工具输出 / 大 diff**，内容落在对象存储里；
模型侧靠 `read_artifact` / `inspect_artifact` 读回，本路由把**同一个读入口**
（`ArtifactStore.inspect`）暴露给 Web。

契约矩阵
--------

| 条件 | 结果 |
| --- | --- |
| `session_id` 形态非法（含 `.` / `/`） | 422 `InvalidSessionId` |
| `artifact_id` 形态非法（非 16 位小写十六进制） | 422 |
| 会话不存在 | 404 `SessionNotFound` |
| **本部署未配置 artifact 存储** | 503（如实：不是"没有这个 artifact"） |
| artifact 不存在（含"它属于别的会话"） | 404 |
| 正常 | 200（`lines`/`total_lines`/`returned_lines`/`truncated`/`query`） |

跨会话隔离的测法
----------------

真实 store（S3 / MinIO）用 `{session_id}/{artifact_id}` 前缀做命名空间，所以隔离性
来自两件事：**用 URL 里的 session_id 构造 store**，以及 **provider 真的把它拼进 key**。

- 前者在路由层测（`test_store_is_built_with_the_url_session_id` 断言工厂收到的参数）；
- 后者在 store 层测（`test_minio_load_namespaces_key_...` 断言发出的请求 key）。

内存替身（`FakeArtifactStore`）不按会话分区，所以在替身上断言"读不到别的会话"只会测出
一个假象——那两条断言都放在了真正承担该职责的那一层。

`max_lines` / `max_chars_per_line` 是**服务端上限**：客户端给多大都会被夹到上限内，
并在 `query` 里回显实际生效值（响应体积可控）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Self
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent_harness.config import Settings
from agent_harness.storage.artifact import FakeArtifactStore, compute_artifact_id
from agent_harness.web.app import create_app
from tests.scripted_model import ScriptedModel

if TYPE_CHECKING:
    from agent_harness.storage.minio_artifact import MinioArtifactStore

_DATA_PREFIX = "data:"

#: 工厂的补丁目标：app.py 通过模块属性调用，才能这样替换（与既有
#: `agent_harness.session.service.build_runtime` 的补丁口径一致）。
_FACTORY = "agent_harness.web.artifacts.build_read_artifact_store"


def _client(tmp_path: Path, **overrides) -> TestClient:
    settings = Settings(
        _env_file=None,
        workspace_dir=str(tmp_path),
        model_api_key="sk-test",
        **overrides,
    )
    return TestClient(create_app(settings, enable_cors=False))


def _create_session(client: TestClient) -> str:
    """建一个真会话（真 runtime + 替身模型），返回 session_id。"""
    with patch(
        "agent_harness.assembly.create_chat_model",
        return_value=ScriptedModel(responses=[AIMessage(content="ok")]),
    ):
        resp = client.post("/api/sessions", json={"task": "hi", "max_steps": 1})
    assert resp.status_code == 200, resp.text
    frames = [
        json.loads(line[len(_DATA_PREFIX) :].strip())
        for line in resp.text.splitlines()
        if line.startswith(_DATA_PREFIX)
    ]
    session_id = next((f["session_id"] for f in frames if f.get("session_id")), None)
    assert session_id, f"SSE 流里没有 session_id：{frames[:3]}"
    return str(session_id)


def _seeded_store(session_id: str, content: str) -> tuple[FakeArtifactStore, str]:
    """把一个外置产物塞进内存 store，返回 (store, artifact_id)。"""
    store = FakeArtifactStore()
    artifact = asyncio.run(
        store.save(
            session_id,
            content,
            mime_type="text/plain",
            source_tool="bash",
            tool_call_id="tc-1",
        )
    )
    return store, artifact.artifact_id


class _SpyFactory:
    """记录工厂被谁调用（守"用 URL 的 session_id 构造 store"这条接缝）。"""

    def __init__(self, store: FakeArtifactStore) -> None:
        self._store = store
        self.calls: list[str] = []

    def __call__(self, settings: Settings, session_id: str) -> FakeArtifactStore:
        self.calls.append(session_id)
        return self._store


def test_reads_slice_and_reports_truncation(tmp_path: Path) -> None:
    """正常读取：返回切片与**如实**的截断标记（不是"给你 2 行还说完整"）。"""
    client = _client(tmp_path)
    session_id = _create_session(client)
    store, artifact_id = _seeded_store(session_id, "l1\nl2\nl3\n")

    with patch(_FACTORY, return_value=store):
        resp = client.get(
            f"/api/sessions/{session_id}/artifacts/{artifact_id}",
            params={"max_lines": 2},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["artifact_id"] == artifact_id
    assert [ln["text"] for ln in body["lines"]] == ["l1", "l2"]
    assert [ln["line_number"] for ln in body["lines"]] == [1, 2]
    assert body["total_lines"] == 3
    assert body["returned_lines"] == 2
    assert body["truncated"] is True
    assert body["query"]["max_lines"] == 2


def test_keyword_filter_selects_matching_lines(tmp_path: Path) -> None:
    client = _client(tmp_path)
    session_id = _create_session(client)
    store, artifact_id = _seeded_store(session_id, "alpha\nbeta\nalpha again\n")

    with patch(_FACTORY, return_value=store):
        resp = client.get(
            f"/api/sessions/{session_id}/artifacts/{artifact_id}",
            params={"keyword": "alpha"},
        )

    assert resp.status_code == 200, resp.text
    contents = [ln["text"] for ln in resp.json()["lines"]]
    assert contents == ["alpha", "alpha again"]
    assert resp.json()["total_lines"] == 3


def test_max_lines_is_capped_by_the_server(tmp_path: Path) -> None:
    """体积上限由服务端兜底：客户端要 10 万行也只给上限，并回显实际值。"""
    client = _client(tmp_path)
    session_id = _create_session(client)
    store, artifact_id = _seeded_store(session_id, "x\n")

    with patch(_FACTORY, return_value=store):
        resp = client.get(
            f"/api/sessions/{session_id}/artifacts/{artifact_id}",
            params={"max_lines": 100_000},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["query"]["max_lines"] == 1000, "传 10 万行的契约就是夹到上限"


def test_session_id_shape_is_rejected(tmp_path: Path) -> None:
    """id 形态非法 → 422（与 DELETE 会话同一口径），不是 404。"""
    client = _client(tmp_path)
    resp = client.get("/api/sessions/bad.id/artifacts/0123456789abcdef")
    assert resp.status_code == 422, resp.text


def test_artifact_id_shape_is_rejected(tmp_path: Path) -> None:
    """artifact_id 必须是 16 位小写十六进制；'ZZZZ…' 这种 → 422。"""
    client = _client(tmp_path)
    session_id = _create_session(client)
    resp = client.get(f"/api/sessions/{session_id}/artifacts/ZZZZZZZZZZZZZZZZ")
    assert resp.status_code == 422, resp.text


def test_unknown_session_is_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.get("/api/sessions/nosuchsession/artifacts/0123456789abcdef")
    assert resp.status_code == 404, resp.text


def test_unknown_artifact_is_404(tmp_path: Path) -> None:
    """store 抛 KeyError（三实现统一的 not-found 契约）→ 404。"""
    client = _client(tmp_path)
    session_id = _create_session(client)
    store, _ = _seeded_store(session_id, "l1\n")

    with patch(_FACTORY, return_value=store):
        resp = client.get(f"/api/sessions/{session_id}/artifacts/0123456789abcdef")

    assert resp.status_code == 404, resp.text


def test_store_is_built_with_the_url_session_id(tmp_path: Path) -> None:
    """隔离接缝的上半截：store 必须用 URL 里的 session_id 构造。

    真实 provider 的命名空间是 `{session_id}/{artifact_id}`，"能不能读到别的会话的
    产物"首先取决于这一点。这里**不断言响应码**：内存替身不按会话分区，它会照样
    返回 200——在替身上断言 200/404 都是在测假象（下半截见下面的 store 层测试）。
    """
    client = _client(tmp_path)
    session_a = _create_session(client)
    session_b = _create_session(client)
    assert session_a != session_b
    store, artifact_id = _seeded_store(session_a, "secret\n")
    spy = _SpyFactory(store)

    with patch(_FACTORY, spy):
        client.get(f"/api/sessions/{session_b}/artifacts/{artifact_id}")

    assert spy.calls == [session_b], (
        "store 必须按 URL 的 session_id 构造，否则真实 provider 会读到别的会话的产物"
    )


def test_line_bounds_below_one_are_rejected(tmp_path: Path) -> None:
    """`start_line=0` / 负值 → 422。

    `slice_lines` 内部是 `s = (start_line or 1) - 1`，放进去就会变成 `indexed[-2:]`
    这类**从尾部倒着读**的切片——静默给错内容的响应比 422 危险得多。
    """
    client = _client(tmp_path)
    session_id = _create_session(client)
    store, artifact_id = _seeded_store(session_id, "l1\nl2\nl3\n")

    with patch(_FACTORY, return_value=store):
        for params in ({"start_line": 0}, {"start_line": -2}, {"end_line": 0}):
            resp = client.get(
                f"/api/sessions/{session_id}/artifacts/{artifact_id}", params=params
            )
            assert resp.status_code == 422, f"{params} → {resp.status_code}"


def test_unconfigured_object_store_now_reads_from_local(tmp_path: Path) -> None:
    """本部署没配对象存储 → 走**本地**默认 Provider，产物不存在就是 404（#192）。

    语义在 #192 变了：此前"没配存储"等于"没有存储"（503）；现在它等于"用本地存储"
    （spec 06 §3 的默认 Provider）。于是同一个请求的诚实答案从"本部署没配好存储"
    变成"这个产物不存在"——本地 store 是**能读**的，只是里面没有这个 id。
    仍然返回 503 的场景见 `test_blank_artifact_dir_returns_503`。
    """
    client = _client(tmp_path)
    session_id = _create_session(client)
    resp = client.get(f"/api/sessions/{session_id}/artifacts/0123456789abcdef")
    assert resp.status_code == 404, resp.text
    assert "不在会话" in resp.json()["detail"]


def test_blank_artifact_dir_returns_503(tmp_path: Path) -> None:
    """`artifact_dir` 显式置空（且无对象存储）→ 503 + 如实说明，**不伪装成 404**。

    这是"这个部署确实没有可读存储"的剩余场景：接口若报 404，用户会以为是
    "产物不存在"，而事实是"这里根本存不下也读不到产物"。
    """
    client = _client(tmp_path, artifact_dir="")
    session_id = _create_session(client)
    resp = client.get(f"/api/sessions/{session_id}/artifacts/0123456789abcdef")
    assert resp.status_code == 503, resp.text
    assert "存储" in resp.json()["detail"]


def test_reads_a_locally_written_artifact_over_http(tmp_path: Path) -> None:
    """真实 Local Provider 的 HTTP 200 通路：**不替换工厂**，东西真落在磁盘上。

    此前所有 200 断言都建立在 `_FACTORY` 补丁上——那只证明"路由层会把切片拼成
    响应"，不证明"默认 Provider 写下去的东西读取接口读得到"。这一条把写路径
    （`LocalArtifactStore.save`，与 `assembly.build_runtime` 同一个 store 类型）
    与读路径接成端到端证据（默认 Provider 就是 Local，见 spec 06 §3）。
    """
    artifact_dir = tmp_path / "artifacts"
    client = _client(tmp_path, artifact_dir=str(artifact_dir))
    session_id = _create_session(client)

    from agent_harness.storage.local_artifact import LocalArtifactStore

    settings = Settings(
        _env_file=None,
        workspace_dir=str(tmp_path),
        model_api_key="sk-test",
        artifact_dir=str(artifact_dir),
    )
    writer = LocalArtifactStore(settings, session_id=session_id)
    artifact = asyncio.run(
        writer.save(
            session_id,
            "alpha\nbeta\n",
            mime_type="text/plain",
            source_tool="bash",
            tool_call_id="tc-1",
        )
    )

    resp = client.get(f"/api/sessions/{session_id}/artifacts/{artifact.artifact_id}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [ln["text"] for ln in body["lines"]] == ["alpha", "beta"]
    assert body["total_lines"] == 2
    assert body["truncated"] is False


def test_local_artifact_of_another_session_is_404(tmp_path: Path) -> None:
    """本地 Provider 上真的跨会话隔离：同一 artifact_id 在另一个会话读不到。

    `FakeArtifactStore` 不按会话分区，所以在替身上断言"读不到别人的"只会测出假象
    （见模块 docstring）。Local 是**默认** Provider，它的 `{session_id}/{artifact_id}`
    布局有没有真的生效，必须在这一层用**真实的两个会话**证明。
    """
    artifact_dir = tmp_path / "artifacts"
    client = _client(tmp_path, artifact_dir=str(artifact_dir))
    session_a = _create_session(client)
    session_b = _create_session(client)
    assert session_a != session_b

    from agent_harness.storage.local_artifact import LocalArtifactStore

    settings = Settings(
        _env_file=None,
        workspace_dir=str(tmp_path),
        model_api_key="sk-test",
        artifact_dir=str(artifact_dir),
    )
    artifact = asyncio.run(
        LocalArtifactStore(settings, session_id=session_a).save(
            session_a, "secret\n", mime_type="text/plain", source_tool="bash",
            tool_call_id="tc-1",
        )
    )

    own = client.get(f"/api/sessions/{session_a}/artifacts/{artifact.artifact_id}")
    other = client.get(f"/api/sessions/{session_b}/artifacts/{artifact.artifact_id}")

    assert own.status_code == 200, own.text
    assert other.status_code == 404, (
        "artifact_id 是内容哈希、跨会话可重复；隔离只能靠 store 的会话前缀"
    )


def test_runtime_overflow_writes_a_readable_artifact(tmp_path: Path) -> None:
    """AC9 端到端：**真 runtime 的溢出**（不是手工 new 一个 handler）落盘并可读回。

    `test_local_store_writes_to_disk_and_reads_back` 是直接构造
    `ArtifactOverflowHandler(LocalArtifactStore(...))`——那证明的是"store 能写"，
    不证明"`build_runtime` 真的把写入者接上了"。两者的差别正是 #192 的病根：
    此前 `ArtifactOverflowHandler` 只在 S3 分支存在，未配对象存储的部署**没有任何
    写入者**，于是产物一个都不产生（界面永远空的，日志里一切正常）。

    这条把整条链路走完：真 workspace 里的大文件 → read 工具 → 真 runtime 溢出 →
    `artifact/externalized` + ToolResult 只带 `artifact_ref`（不变量 #15：模型只拿
    summary + ref）→ 磁盘上有一份**逐字节完整**的原件 → HTTP 200 读得回来。
    """
    artifact_dir = tmp_path / "artifacts"
    # 远超 artifact_overflow_chars（默认 2000），但**同时**在 read 工具的两道预算内
    # （2000 行 / 50KB）——否则工具自己先截断，磁盘上存的就不是原件，这条断言会
    # 退化成"验证两个截断叠在一起"。300 行 × 29 字符 ≈ 8.7KB，落在两者之间。
    body = "HEAD_MARKER\n" + ("x" * 28 + "\n") * 300 + "TAIL_MARKER\n"
    (tmp_path / "big.txt").write_text(body, encoding="utf-8")

    client = _client(tmp_path, artifact_dir=str(artifact_dir))
    script = [
        AIMessage(
            content="",
            tool_calls=[{
                "id": "tc-read-1",
                "name": "read",
                "args": {"path": "big.txt"},
                "type": "tool_call",
            }],
        ),
        AIMessage(content="done"),
    ]
    with patch(
        "agent_harness.assembly.create_chat_model", return_value=ScriptedModel(script)
    ):
        resp = client.post(
            "/api/sessions",
            json={"task": "读大文件", "cwd": str(tmp_path), "max_steps": 4},
        )
    assert resp.status_code == 200, resp.text
    frames = [
        json.loads(line[len(_DATA_PREFIX) :].strip())
        for line in resp.text.splitlines()
        if line.startswith(_DATA_PREFIX)
    ]
    session_id = next((f["session_id"] for f in frames if f.get("session_id")), None)
    assert session_id, f"SSE 流里没有 session_id：{frames[:3]}"

    events = client.get(f"/api/sessions/{session_id}/events").json()
    externalized = [e for e in events if e["type"] == "artifact/externalized"]
    assert externalized, (
        "真 runtime 的溢出没有产出 artifact/externalized——写入者没接上（#192 的病根）"
    )
    data = externalized[0]["data"]
    artifact_id = data["artifact_id"]
    assert data["source_tool"] == "read"
    assert data["tool_call_id"] == "tc-read-1"

    # 模型侧只拿摘要 + ref：完整的 6000 字符不回到事件流里（否则外置等于没做）。
    results = [e for e in events if e["type"] == "tool/result"]
    assert results, "没有 tool/result 事件"
    payload = json.loads(results[0]["data"]["content"])
    assert payload["artifact_ref"] == artifact_id
    assert body not in json.dumps(results[0]["data"]), "完整内容不得留在会话事件里"

    # 磁盘上是**逐字节完整**的原件（"完整保存 ≠ 完整注入"）。
    stored = artifact_dir / session_id / artifact_id
    assert stored.read_text(encoding="utf-8") == body

    got = client.get(f"/api/sessions/{session_id}/artifacts/{artifact_id}")
    assert got.status_code == 200, got.text
    texts = [ln["text"] for ln in got.json()["lines"]]
    assert texts[0] == "HEAD_MARKER"
    assert "TAIL_MARKER" in texts[-1]
    assert got.json()["truncated"] is False


class _FakeBody:
    """最小 S3 body 替身（`async with response["Body"] as stream`）。"""

    def __init__(self, data: bytes) -> None:
        self._data = data

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def read(self) -> bytes:
        return self._data


class _FakeS3Client:
    """记录请求的 s3 客户端替身：不发网络，就能断言真实 key。"""

    def __init__(self, *, error: Exception | None = None, payload: bytes = b"") -> None:
        self.requests: list[dict] = []
        self._error = error
        self._payload = payload

    async def get_object(self, **kwargs: object) -> dict:
        self.requests.append(kwargs)
        if self._error is not None:
            raise self._error
        return {"Body": _FakeBody(self._payload), "ContentType": "text/plain"}


class _FakeSDKSession:
    def __init__(self, client: _FakeS3Client) -> None:
        self._client = client

    def client(self, _service: str, **_kwargs: object):
        client = self._client

        class _ClientCM:
            async def __aenter__(self) -> _FakeS3Client:
                return client

            async def __aexit__(self, *exc: object) -> bool:
                return False

        return _ClientCM()


def _minio_store(session_id: str) -> MinioArtifactStore:
    pytest.importorskip("aioboto3")
    from agent_harness.storage.minio_artifact import MinioArtifactStore

    settings = Settings(
        _env_file=None,
        workspace_dir=".",
        model_api_key="sk-test",
        minio_endpoint="http://127.0.0.1:9000",
        minio_bucket="b",
        minio_access_key="k",
        minio_secret_key="s",
    )
    return MinioArtifactStore(settings, session_id=session_id)


def test_minio_load_namespaces_key_by_store_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离接缝的下半截：读回用的 key 必须是 `{session_id}/{artifact_id}`。

    路由层只能证明"工厂拿到了 URL 的 session_id"；**"读不到别的会话"这件事只有
    在真实 provider 上才成立**，所以断言放在了发出请求的这一层。
    """
    content = "hello\n"
    artifact_id = compute_artifact_id(content)
    store = _minio_store("sess-b")
    client = _FakeS3Client(payload=content.encode())
    monkeypatch.setattr(store, "_sdk_session", _FakeSDKSession(client))

    artifact = asyncio.run(store.load(artifact_id))

    assert artifact.content == content
    assert client.requests[0]["Key"] == f"sess-b/{artifact_id}"
    assert client.requests[0]["Bucket"] == "b"
    # AC4：MinIO 的 save 没有持久化元数据，load 必须如实给 None，不能伪造成空串。
    assert artifact.source_tool is None
    assert artifact.tool_call_id is None
    assert artifact.created_at is None


def test_minio_load_maps_missing_object_to_key_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """对象不存在 → KeyError（与 S3 / Fake 同一契约），不是把 SDK 异常漏成 500。

    此前 MinIO 的 `load` 没有这层转换，真实 MinIO 部署下"产物已被删/从未写过"会
    返回 500 而不是 404。
    """
    store = _minio_store("sess-b")
    missing = store._client_error({"Error": {"Code": "NoSuchKey"}}, "GetObject")
    monkeypatch.setattr(
        store, "_sdk_session", _FakeSDKSession(_FakeS3Client(error=missing))
    )

    with pytest.raises(KeyError):
        asyncio.run(store.load("0123456789abcdef"))


@pytest.mark.parametrize("bad", ["", "zz", "0123456789ABCDEF", "0123456789abcde", "../etc/passwd"])
def test_minio_store_rejects_malformed_artifact_id_without_network(bad: str) -> None:
    """MinIO 实现必须像 S3 一样先校验 id 形态（此前它没有这层校验）。

    校验发生在任何客户端调用之前，所以这条断言在离线也能跑——不会被网络拖成 flaky。
    """
    store = _minio_store("sess")
    with pytest.raises(KeyError):
        asyncio.run(store.load(bad))


class TestBuildReadArtifactStoreSelection:
    """读 store 的选择口径必须与写路径（`assembly.build_runtime`）逐条对应（#192）。

    对不上就会出现"写进了 A、从 B 读"的静默错配：界面永远空着，而日志里一切正常。
    """

    def test_local_is_the_default_when_nothing_is_configured(self, tmp_path: Path) -> None:
        """未配任何对象存储 → Local（spec 06 §3 的默认 Provider），**不是** None。

        这一条就是 #192 的核心：此前未配对象存储的部署读取接口永远 503，
        因为既没有写入者、也没有可读的 store。
        """
        from agent_harness.storage.local_artifact import LocalArtifactStore
        from agent_harness.web.artifacts import build_read_artifact_store

        settings = Settings(
            _env_file=None,
            workspace_dir=str(tmp_path),
            artifact_dir=str(tmp_path / "artifacts"),
        )
        store = build_read_artifact_store(settings, "sess-1")
        assert isinstance(store, LocalArtifactStore)

    def test_blank_artifact_dir_yields_none(self, tmp_path: Path) -> None:
        """artifact_dir 显式置空 = 关掉本地落盘 → 如实 None（路由据此回 503）。"""
        from agent_harness.web.artifacts import build_read_artifact_store

        settings = Settings(_env_file=None, workspace_dir=str(tmp_path), artifact_dir="  ")
        assert build_read_artifact_store(settings, "sess-1") is None

    def test_half_configured_object_store_yields_none_not_local(self, tmp_path: Path) -> None:
        """只填了 S3 endpoint（缺 bucket/密钥）→ None，**不得**降级到本地。

        降级会让运维以为产物进了对象存储——这是"配置错误被伪装成正常工作"。
        """
        from agent_harness.web.artifacts import build_read_artifact_store

        settings = Settings(
            _env_file=None,
            workspace_dir=str(tmp_path),
            artifact_dir=str(tmp_path / "artifacts"),
            artifact_store_endpoint="https://example.invalid",
        )
        assert build_read_artifact_store(settings, "sess-1") is None

    def test_half_configured_minio_yields_none_not_local(self, tmp_path: Path) -> None:
        """MinIO 半配置同样 → None（此前只有 S3 那条被钉住，MinIO 分支没测到）。"""
        from agent_harness.web.artifacts import build_read_artifact_store

        settings = Settings(
            _env_file=None,
            workspace_dir=str(tmp_path),
            artifact_dir=str(tmp_path / "artifacts"),
            minio_endpoint="http://127.0.0.1:9000",
        )
        assert build_read_artifact_store(settings, "sess-1") is None

    def test_missing_artifact_extra_yields_none_not_a_crash(self, tmp_path: Path, monkeypatch) -> None:
        """**可选依赖缺失**必须 fail-open，而不是把建会话一起拖垮（不变量 21）。

        把对象存储配好但没装 `[artifact]` extra 的部署，构造期抛的是 `RuntimeError`
        （不是 `ValueError`）。这个类型此前没被兜住 ⇒ `build_runtime` 把它冒出去 ⇒
        **每次建会话 500**，读接口也是 500 而不是 503。这里直接让构造期抛
        `RuntimeError` 来钉住"可预期的失败都返回 None"这条契约。
        """
        from agent_harness.storage.s3_artifact import S3ArtifactStore
        from agent_harness.web.artifacts import build_read_artifact_store

        def _boom(self, settings, *, session_id=None):
            raise RuntimeError("S3ArtifactStore requires pip install 'intelligence-agent[artifact]'")

        monkeypatch.setattr(S3ArtifactStore, "__init__", _boom)
        settings = Settings(
            _env_file=None,
            workspace_dir=str(tmp_path),
            artifact_dir=str(tmp_path / "artifacts"),
            artifact_store_endpoint="https://s3.invalid",
            artifact_store_bucket="b",
            artifact_store_access_key="k",
            artifact_store_secret_key="s",
        )
        # 读路径：如实说"没有可读存储"（503 的来源），而不是抛出去变 500
        assert build_read_artifact_store(settings, "sess-1") is None

    def test_path_traversal_session_id_yields_none(self, tmp_path: Path) -> None:
        """非法 session 段不得进入路径拼接——构造期就挡住（纵深防御）。"""
        from agent_harness.web.artifacts import build_read_artifact_store

        settings = Settings(
            _env_file=None,
            workspace_dir=str(tmp_path),
            artifact_dir=str(tmp_path / "artifacts"),
        )
        assert build_read_artifact_store(settings, "../../escape") is None

    def test_local_roundtrip_through_the_read_store(self, tmp_path: Path) -> None:
        """写路径落盘 → 读路径读回：端到端证明两侧用的是同一个键约定。"""
        from agent_harness.storage.local_artifact import LocalArtifactStore
        from agent_harness.web.artifacts import build_read_artifact_store

        settings = Settings(
            _env_file=None,
            workspace_dir=str(tmp_path),
            artifact_dir=str(tmp_path / "artifacts"),
        )
        writer = LocalArtifactStore(settings, session_id="sess-1")
        artifact = asyncio.run(
            writer.save(
                "sess-1",
                "alpha\nbeta\n",
                mime_type="text/plain",
                source_tool="bash",
                tool_call_id="tc-1",
            )
        )
        reader = build_read_artifact_store(settings, "sess-1")
        assert reader is not None
        slice_ = asyncio.run(reader.inspect(artifact.artifact_id, start_line=2))
        assert [entry["text"] for entry in slice_.lines] == ["beta"]
