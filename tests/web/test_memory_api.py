"""用户侧记忆 API（#159 B）：列出 / 硬删 / 错误语义 / 归属隔离 / 审计不落 SessionEvent。

装配方式：真 `create_app` + 真 `wire_capabilities`，只把 memory 的**组件工厂**换成 fake
（`FakeMemoryCapability` 的 namespace/归属语义是真的，被替换的只是"要不要连 Zilliz"）。
身份走真 JWT 中间件——AC7 要求的"越权在领域层也被拒"必须在这种端到端形状下才算验过。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

from agent_harness.config import Settings
from agent_harness.identity import (
    IdentityContext,
    identity_context_var,
    set_identity_context,
)
from agent_harness.memory.fake_capability import FakeMemoryCapability
from agent_harness.memory.types import MemoryScope, memory_session_var
from agent_harness.session.event import EVENT_TYPES as SESSION_EVENT_TYPES
from agent_harness.web.app import create_app

_SECRET = "memory-api-test-signing-secret-at-least-32"
_ALICE = IdentityContext("acme", "alice", ["user"])
_BOB = IdentityContext("acme", "bob", ["user"])
#: 认证通过但**没有** "user" scope：`MemoryNamespace.of` 的 scope 授权会拒绝。
_NO_USER_SCOPE = IdentityContext("acme", "carol", ["session"])
#: 带 "session" scope 的 alice：HTTP 请求没有可信 session 绑定（`memory_session_var`
#: 只在 detached run 里设置），所以按 id 去删会话记忆时解析不出该行的 namespace。
_SESSION_ALICE = IdentityContext("acme", "alice", ["user", "session"])


class _FakeMemoryComponents:
    """provider seam 的最小合法产物：capability + writeback + 生命周期。"""

    def __init__(self) -> None:
        self.capability = FakeMemoryCapability()
        self.writeback = object()
        self.initialized = False
        self.closed = False

    async def initialize(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True


def _token(identity: IdentityContext) -> str:
    return jwt.encode(
        {
            "tenant_id": identity.tenant_id,
            "user_id": identity.user_id,
            "scopes": list(identity.scopes),
            "exp": int(datetime.now(UTC).timestamp()) + 600,
        },
        _SECRET,
    )


def _auth(identity: IdentityContext) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(identity)}"}


@pytest.fixture
def memory_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """真 app + fake memory provider；返回 (client, components)。"""
    components = _FakeMemoryComponents()
    monkeypatch.setattr(
        "agent_harness.capability.factories.build_memory_components",
        lambda settings, *, provider="builtin": components,
    )
    settings = Settings(
        _env_file=None,
        workspace_dir=str(tmp_path),
        model_api_key="sk-test",
        jwt_secret=_SECRET,
        capabilities='{"memory": {"provider": "langmem"}}',
    )
    app = create_app(settings, enable_cors=False)
    with TestClient(app) as client:
        yield client, components


async def _seed(components: _FakeMemoryComponents, identity: IdentityContext,
                content: str, metadata: dict | None = None, *,
                scope: MemoryScope = MemoryScope.USER, session_id: str | None = None) -> str:
    """在指定身份下直接经能力写一条记忆（等价于后台抽取写进来的那条）。

    `scope=SESSION` 时必须给 `session_id`：namespace 解析要求可信的会话绑定。
    """
    token = set_identity_context(identity)
    binding = memory_session_var.set(session_id) if session_id is not None else None
    try:
        return await components.capability.store(scope, content, metadata or {})
    finally:
        if binding is not None:
            memory_session_var.reset(binding)
        identity_context_var.reset(token)


async def _contents(components: _FakeMemoryComponents, identity: IdentityContext) -> list[str]:
    token = set_identity_context(identity)
    try:
        return [entry.content for entry in await components.capability.list_entries(MemoryScope.USER, 50)]
    finally:
        identity_context_var.reset(token)


@pytest.mark.asyncio
async def test_list_returns_only_the_callers_memories(memory_app):
    """AC5 + AC7：列出的永远是**自己** namespace 的记忆（身份来自可信入口，不是参数）。"""
    client, components = memory_app
    await _seed(components, _ALICE, "alice 喜欢 TypeScript")
    await _seed(components, _BOB, "bob 的秘密")

    resp = client.get("/api/memories", headers=_auth(_ALICE))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [item["content"] for item in body] == ["alice 喜欢 TypeScript"]
    assert body[0]["scope"] == "user"


@pytest.mark.asyncio
async def test_list_strips_provider_internal_metadata(memory_app):
    """列表给用户看的是自己的 metadata，不含 provider 内部载荷。"""
    client, components = memory_app
    await _seed(components, _ALICE, "alice 的偏好",
                {"importance": 0.8, "_langmem_value": {"kind": "MemoryPayload", "raw": "内部"}})

    [item] = client.get("/api/memories", headers=_auth(_ALICE)).json()

    assert item["metadata"] == {"importance": 0.8}


@pytest.mark.asyncio
async def test_list_paginates_and_clamps(memory_app):
    """分页：offset/limit 切片；越界的 limit 由 FastAPI 422 挡在领域层之前。"""
    client, components = memory_app
    for index in range(3):
        await _seed(components, _ALICE, f"第 {index} 条")

    page = client.get("/api/memories?limit=2&offset=1", headers=_auth(_ALICE)).json()
    full = client.get("/api/memories?limit=50", headers=_auth(_ALICE)).json()
    assert {item["content"] for item in full} == {"第 0 条", "第 1 条", "第 2 条"}
    # 分页 = **同一个倒序口径**的连续切片（写成切片比较而不是硬编码顺序：同一微秒内的
    # 排序 tie-break 是随机 uuid，靠它推出来的固定顺序会变成偶发 flake）。
    assert page == full[1:3]
    # 倒序契约本身：created_at 单调不增。
    stamps = [item["created_at"] for item in full]
    assert stamps == sorted(stamps, reverse=True)

    assert client.get("/api/memories?limit=0", headers=_auth(_ALICE)).status_code == 422
    assert client.get("/api/memories?limit=10000", headers=_auth(_ALICE)).status_code == 422
    assert client.get("/api/memories?offset=-1", headers=_auth(_ALICE)).status_code == 422


@pytest.mark.asyncio
async def test_delete_forgets_then_reports_404(memory_app):
    """AC5/AC6：删掉 → 200；再删同一条 → **404**（"这条已经不在了"要报出来，不是静默 204）。"""
    client, components = memory_app
    memory_id = await _seed(components, _ALICE, "要被遗忘的偏好")

    first = client.delete(f"/api/memories/{memory_id}", headers=_auth(_ALICE))
    assert first.status_code == 200, first.text
    assert first.json() == {"id": memory_id, "deleted": True}
    assert await _contents(components, _ALICE) == []

    second = client.delete(f"/api/memories/{memory_id}", headers=_auth(_ALICE))
    assert second.status_code == 404, second.text
    assert memory_id in second.json()["detail"]


@pytest.mark.asyncio
async def test_unknown_id_is_404(memory_app):
    client, _ = memory_app
    resp = client.delete("/api/memories/never-existed", headers=_auth(_ALICE))
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_deleting_someone_elses_memory_is_403_and_changes_nothing(memory_app):
    """AC7：越权由**领域层**拒绝（不只是查询条件），且对方数据完好。

    这里 alice 直接拿着 bob 的 memory_id 来删——最坏形状。403（而不是伪装成 404），
    因为领域层的归属校验本来就拒绝了，如实上报。
    """
    client, components = memory_app
    bob_memory = await _seed(components, _BOB, "bob 的秘密")

    resp = client.delete(f"/api/memories/{bob_memory}", headers=_auth(_ALICE))

    assert resp.status_code == 403, resp.text
    assert await _contents(components, _BOB) == ["bob 的秘密"]
    assert await _contents(components, _ALICE) == []


@pytest.mark.asyncio
async def test_list_without_user_scope_is_403_not_500(memory_app):
    """AC6：身份认证通过但缺 "user" scope → **403**，不是 500。

    scope 授权由 `MemoryNamespace.of` 拒绝；不翻译就会以未登记领域异常的形状冒成 500，
    正是 AC6 要挡的。归属校验不依赖 "user" scope，所以同一个身份拿别人的 id 去删也是 403
    ——两个入口给出同一类明确状态码，且对方的记忆完好。
    """
    client, components = memory_app
    alice_memory = await _seed(components, _ALICE, "alice 的偏好")

    listing = client.get("/api/memories", headers=_auth(_NO_USER_SCOPE))
    assert listing.status_code == 403, listing.text

    deleting = client.delete(f"/api/memories/{alice_memory}", headers=_auth(_NO_USER_SCOPE))
    assert deleting.status_code == 403, deleting.text
    assert await _contents(components, _ALICE) == ["alice 的偏好"]


@pytest.mark.asyncio
async def test_deleting_a_session_scoped_memory_is_403_not_500(memory_app):
    """AC6：HTTP 入口只暴露 USER scope，会话记忆不能用 500 冒出去，也不能被它删掉。

    alice 的 token 带 "session" scope，但 HTTP 请求没有可信的会话绑定，所以按 id 解析那一行的
    namespace 会失败。领域层的归属比较把"这个上下文解析不出这一行"判定为"不是你能动的" →
    403（跨用户那条也是 403，语义一致）；记忆完好由随后的带绑定读取证明。
    """
    client, components = memory_app
    memory_id = await _seed(components, _SESSION_ALICE, "会话内的临时偏好",
                           scope=MemoryScope.SESSION, session_id="sess-1")

    resp = client.delete(f"/api/memories/{memory_id}", headers=_auth(_SESSION_ALICE))

    assert resp.status_code == 403, resp.text
    token = set_identity_context(_SESSION_ALICE)
    binding = memory_session_var.set("sess-1")
    try:
        remaining = await components.capability.list_entries(MemoryScope.SESSION, 10)
    finally:
        memory_session_var.reset(binding)
        identity_context_var.reset(token)
    assert [entry.content for entry in remaining] == ["会话内的临时偏好"]


@pytest.mark.asyncio
async def test_memory_capability_disabled_is_503(tmp_path: Path):
    """没配 memory 能力时端点无从服务：503（配置状态，不是"资源不存在"）。"""
    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path), model_api_key="sk-test", jwt_secret=_SECRET,
    )
    with TestClient(create_app(settings, enable_cors=False)) as client:
        assert client.get("/api/memories", headers=_auth(_ALICE)).status_code == 503
        assert client.delete("/api/memories/x", headers=_auth(_ALICE)).status_code == 503


@pytest.mark.asyncio
async def test_audit_goes_to_structured_logs_not_session_events(memory_app, caplog):
    """AC8：审计落 memory 侧结构化日志，且**不**进会话事件流。

    两头都断言：日志里有一条 `memory_forget`（入口 api、结果 forgotten），而
    SessionEvent 的词汇表里**不存在**记忆变更事件（有人将来想加，会先撞红这里）。
    """
    client, components = memory_app
    memory_id = await _seed(components, _ALICE, "要被遗忘的偏好")

    with caplog.at_level(logging.INFO, logger="agent_harness.memory.audit"):
        assert client.delete(f"/api/memories/{memory_id}", headers=_auth(_ALICE)).status_code == 200

    [record] = [r for r in caplog.records if getattr(r, "event_type", None) == "memory_forget"]
    assert record.entry_point == "api"
    assert record.outcome == "forgotten"
    assert record.memory_id == memory_id
    assert record.tenant_id == "acme" and record.user_id == "alice"

    # 会话事件流里不得出现"记忆内容变更"类事件——将来有人想加"memory/forget"之类，
    # 会先撞红这里。**注意口径**：`memory/degraded` 是**降级观测**（抽取/写回/检索失败），
    # 不是内容变更，AC8 明说它不构成反例，所以这里不能写成"任何含 memory 的事件都不许有"。
    forbidden = [t for t in SESSION_EVENT_TYPES if any(
        word in t.lower() for word in ("forget", "delet", "memory/update"))]
    assert forbidden == []


def test_origin_gate_is_wired_on_memory_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """本地信任模式下跨源请求被来源闸拒绝（与项目 API 共用同一条规则）。

    这条必须在**没有 jwt_secret** 的 app 上验：配置了 JWT 时认证层才是边界，来源闸直接
    让位（跨源网页拿不到签名 token）——那正是 projects 那条测试的结论。
    """
    components = _FakeMemoryComponents()
    monkeypatch.setattr(
        "agent_harness.capability.factories.build_memory_components",
        lambda settings, *, provider="builtin": components,
    )
    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path), model_api_key="sk-test",
        capabilities='{"memory": {"provider": "langmem"}}',
    )
    with TestClient(create_app(settings, enable_cors=False)) as client:
        cross_origin = client.get("/api/memories", headers={"Origin": "http://evil.example"})
        assert cross_origin.status_code == 403, cross_origin.text
        # 非浏览器发起（无 Origin）放行——本地信任模式的既定口径。
        assert client.get("/api/memories").status_code == 200
