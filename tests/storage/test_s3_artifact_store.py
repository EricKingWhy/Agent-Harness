"""S3 SDK 边界测试与 Fake/S3 共用契约。"""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agent_harness.config import Settings
from agent_harness.storage.artifact import FakeArtifactStore
from agent_harness.storage.s3_artifact import S3ArtifactStore


@pytest.fixture
def s3_sdk(monkeypatch):
    pytest.importorskip("botocore")
    objects = {}
    client = AsyncMock()

    async def put_object(**kwargs):
        objects[kwargs["Key"]] = kwargs

    async def get_object(**kwargs):
        obj = objects[kwargs["Key"]]
        body = AsyncMock()
        body.read.return_value = obj["Body"]
        body.__aenter__.return_value = body
        client.last_body = body
        return {"Body": body, "Metadata": obj["Metadata"], "ContentType": obj["ContentType"]}

    client.put_object.side_effect = put_object
    client.get_object.side_effect = get_object
    client.__aenter__.return_value = client
    sdk_session = Mock()
    sdk_session.client.return_value = client
    monkeypatch.setitem(sys.modules, "aioboto3", SimpleNamespace(Session=lambda: sdk_session))
    return sdk_session, client, objects


def settings():
    return Settings(
        _env_file=None, artifact_store_endpoint="https://s3.example.test",
        artifact_store_bucket="test-bucket", artifact_store_region="cn-east-1",
        artifact_store_access_key="test-access", artifact_store_secret_key="test-secret",
    )


@pytest.mark.asyncio
async def test_s3_roundtrip_survives_new_provider_instance(s3_sdk):
    sdk_session, client, objects = s3_sdk
    store = S3ArtifactStore(settings(), session_id="s1")
    saved = await store.save("s1", "第一行\nsecond", mime_type="text/plain",
                             source_tool="bash", tool_call_id="c1")
    obj = objects[f"s1/{saved.artifact_id}"]
    assert obj["Bucket"] == "test-bucket"
    assert obj["Body"] == "第一行\nsecond".encode()
    assert saved.content is None
    loaded = await S3ArtifactStore(settings(), session_id="s1").load(saved.artifact_id)
    assert loaded.model_copy(update={"content": None}) == saved
    assert loaded.content == "第一行\nsecond"
    assert sdk_session.client.call_args.kwargs["endpoint_url"] == "https://s3.example.test"
    assert sdk_session.client.call_args.kwargs["aws_secret_access_key"] == "test-secret"
    assert sdk_session.client.call_args.kwargs["region_name"] == "cn-east-1"
    assert sdk_session.client.call_args.kwargs["config"].signature_version == "s3v4"
    assert sdk_session.client.call_args.kwargs["config"].s3 == {"addressing_style": "path"}
    client.get_object.assert_awaited_once_with(Bucket="test-bucket", Key=f"s1/{saved.artifact_id}")
    client.last_body.__aexit__.assert_awaited_once()
    assert client.__aexit__.await_count == 2


@pytest.fixture(params=["fake", "s3"])
def store(request, s3_sdk):
    return (FakeArtifactStore() if request.param == "fake" else
            S3ArtifactStore(settings(), session_id="s1"))


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", "first\n中文\nlast\n"])
async def test_provider_save_load_contract(store, content):
    saved = await store.save("s1", content, mime_type="text/plain",
                             source_tool="工具", tool_call_id="c1")
    loaded = await store.load(saved.artifact_id)
    assert loaded.content == content
    assert loaded.size == len(content.encode())
    assert loaded.model_copy(update={"content": None}) == saved
    duplicate = await store.save("s1", content, mime_type="text/plain",
                                 source_tool="read", tool_call_id="c2")
    assert duplicate.artifact_id == saved.artifact_id
    assert (await store.load(saved.artifact_id)).tool_call_id == "c2"


@pytest.mark.asyncio
async def test_provider_inspect_contract(store):
    saved = await store.save("s1", "first\nneedle\nlast needle", mime_type="text/plain",
                             source_tool="bash", tool_call_id="c1")
    ranged = await store.inspect(saved.artifact_id, start_line=2, end_line=2)
    assert ranged.lines == [{"line_number": 2, "text": "needle"}]
    assert ranged.total_lines == 3 and not ranged.truncated
    selected = await store.inspect(saved.artifact_id, keyword="needle", max_lines=1)
    assert selected.lines == [{"line_number": 2, "text": "needle"}]
    assert selected.truncated and selected.returned_lines == 1


@pytest.mark.asyncio
async def test_s3_missing_key_maps_to_contract_error_but_access_denied_propagates(s3_sdk):
    from botocore.exceptions import ClientError

    _, client, _ = s3_sdk
    store = S3ArtifactStore(settings(), session_id="s1")
    client.get_object.side_effect = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
    with pytest.raises(KeyError):
        await store.load("0" * 16)
    client.get_object.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
    with pytest.raises(ClientError):
        await store.load("0" * 16)


@pytest.mark.asyncio
async def test_session_namespace_cannot_be_changed_or_traversed(s3_sdk):
    _, client, _ = s3_sdk
    store = S3ArtifactStore(settings(), session_id="s1")
    with pytest.raises(ValueError):
        await store.save("s2", "data", mime_type="text/plain", source_tool="bash", tool_call_id="c")
    with pytest.raises(KeyError):
        await store.load("../s2/0123456789abcdef")
    with pytest.raises(ValueError):
        S3ArtifactStore(settings(), session_id="../s2")
    client.put_object.assert_not_awaited()
    client.get_object.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_failure_propagates_without_returning_artifact(s3_sdk):
    _, client, _ = s3_sdk
    client.put_object.side_effect = ConnectionError("offline")
    with pytest.raises(ConnectionError):
        await S3ArtifactStore(settings(), session_id="s1").save(
            "s1", "data", mime_type="text/plain", source_tool="bash", tool_call_id="c",
        )
    client.__aexit__.assert_awaited_once()


def test_optional_sdk_missing_has_actionable_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "aioboto3", None)
    with pytest.raises(RuntimeError, match="intelligence-agent\\[artifact\\]"):
        S3ArtifactStore(settings(), session_id="s1")
