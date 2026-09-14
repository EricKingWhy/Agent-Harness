"""请求身份在异步任务之间隔离。"""

import asyncio
from dataclasses import FrozenInstanceError

import jwt
import pytest
from fastapi.testclient import TestClient

from agent_harness.config import Settings
from agent_harness.identity import (
    IdentityContext,
    get_identity_context,
    identity_context_var,
    set_identity_context,
)
from agent_harness.web.app import create_app


def test_default_identity_when_contextvar_unset():
    assert get_identity_context() == IdentityContext("local", "local", ["user", "session"])


@pytest.mark.asyncio
async def test_contextvar_isolated_across_async_tasks():
    async def read_as(user):
        token = set_identity_context(IdentityContext("acme", user, ["user"]))
        try:
            await asyncio.sleep(0)
            async def child():
                return get_identity_context().user_id
            return await asyncio.create_task(child())
        finally:
            identity_context_var.reset(token)

    assert await asyncio.gather(read_as("alice"), read_as("bob")) == ["alice", "bob"]
    assert get_identity_context().user_id == "local"


def test_identity_is_immutable():
    identity = IdentityContext("acme", "alice", ["user"])
    with pytest.raises(FrozenInstanceError):
        identity.user_id = "bob"


def test_child_cannot_mutate_inherited_scope_permissions():
    scopes = ["user"]
    identity = IdentityContext("acme", "alice", scopes)
    scopes.append("session")
    assert list(identity.scopes) == ["user"]
    with pytest.raises((AttributeError, TypeError)):
        identity.scopes.append("session")


def test_auth_seam_sets_contextvar(tmp_path):
    """配置密钥后的认证链（R6-4/R8-3 契约修订：fail-closed + 强制 exp）——
    合法 token 绑定身份；匿名/坏 token/过期 token/无 exp token 一律 401。"""
    from datetime import UTC, datetime

    secret = "test-signing-secret-at-least-32-characters"
    app = create_app(Settings(_env_file=None, workspace_dir=str(tmp_path), jwt_secret=secret))

    @app.get("/identity-probe")
    async def probe():
        return get_identity_context()

    encoded = jwt.encode({"tenant_id": "acme", "user_id": "alice", "scopes": ["user"],
                          "exp": int(datetime.now(UTC).timestamp()) + 600}, secret)
    with TestClient(app) as client:
        response = client.get("/identity-probe", headers={"Authorization": f"Bearer {encoded}"})
        assert response.json() == {"tenant_id": "acme", "user_id": "alice", "scopes": ["user"]}
        # fail-closed：匿名不再降级 local，直接 401
        assert client.get("/identity-probe").status_code == 401
        assert client.get("/identity-probe", headers={"Authorization": "Bearer invalid"}).status_code == 401
        expired = jwt.encode({"tenant_id": "acme", "user_id": "alice", "exp": 1}, secret)
        assert client.get("/identity-probe", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
        forged = jwt.encode({"tenant_id": "acme", "user_id": "alice"}, "other-secret-at-least-32-characters")
        assert client.get("/identity-probe", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    assert get_identity_context().user_id == "local"


def test_no_secret_does_not_trust_bearer_identity(tmp_path):
    app = create_app(Settings(_env_file=None, workspace_dir=str(tmp_path)))

    @app.get("/identity-probe")
    async def probe():
        return get_identity_context()

    with TestClient(app) as client:
        assert client.get("/identity-probe", headers={"Authorization": "Bearer untrusted"}).json()["user_id"] == "local"


# ── A 组（R6-4 + R8-3，用户拍板 fail-closed）：配置密钥即强制认证 ──


def test_auth_fail_closed_when_secret_configured(tmp_path):
    """配置了 JWT_SECRET 后：匿名请求 401、无 exp 的合法签名 token 401。

    此前匿名请求拿 trusted local 身份（fail-open）+ 无 exp token 永不过期
    ——配合 CORS * 等于把 agent API（含 bash 工具）开放给任意网页。
    """
    from datetime import UTC, datetime

    secret = "test-signing-secret-at-least-32-characters"
    app = create_app(Settings(_env_file=None, workspace_dir=str(tmp_path), jwt_secret=secret))

    @app.get("/identity-probe")
    async def probe():
        return get_identity_context()

    with TestClient(app) as client:
        # 匿名 → 401（不再静默降级为 local）
        resp = client.get("/identity-probe")
        assert resp.status_code == 401
        # 带未来 exp 的合法 token → 通过
        live = jwt.encode({"tenant_id": "acme", "user_id": "alice",
                           "exp": int(datetime.now(UTC).timestamp()) + 600}, secret)
        assert client.get("/identity-probe", headers={"Authorization": f"Bearer {live}"}).json()["user_id"] == "alice"
        # 无 exp 的合法签名 token → 401（强制过期语义）
        no_exp = jwt.encode({"tenant_id": "acme", "user_id": "alice"}, secret)
        assert client.get("/identity-probe", headers={"Authorization": f"Bearer {no_exp}"}).status_code == 401


def test_auth_unset_secret_warns_loudly(tmp_path, caplog):
    """未配置 JWT_SECRET = 本地信任模式：请求照常放行，但 create_app 必须
    发出响亮的启动告警——静默 fail-open 是 R6-4 的核心危害。"""
    import logging

    app = create_app(Settings(_env_file=None, workspace_dir=str(tmp_path)))

    @app.get("/identity-probe")
    async def probe():
        return get_identity_context()

    with TestClient(app) as client:
        assert client.get("/identity-probe").json()["user_id"] == "local"
    assert any(r.levelno >= logging.WARNING and "JWT" in r.getMessage()
               for r in caplog.records), "未配置密钥必须有启动告警"


def test_cors_preflight_survives_auth_when_secret_configured(tmp_path):
    """CORS 中间件必须在认证层外层：浏览器预检（OPTIONS）天然不携带 Bearer，
    预检 401 = 配置 JWT_SECRET 后 Vite dev 跨域模式整体失效。预检放行不削弱
    认证——真实数据请求仍逐个过认证层（预检通过 ≠ 数据可匿名访问）。"""
    from datetime import UTC, datetime

    secret = "test-signing-secret-at-least-32-characters"
    app = create_app(Settings(_env_file=None, workspace_dir=str(tmp_path), jwt_secret=secret))
    with TestClient(app) as client:
        preflight = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert preflight.status_code == 200, "预检请求不得被认证层拦截"
        assert preflight.headers["access-control-allow-origin"] == "*"
        # 数据面不受影响：匿名 GET 依然 401（fail-closed 契约不变）
        assert client.get("/api/health").status_code == 401
        live = jwt.encode({"tenant_id": "acme", "user_id": "alice",
                           "exp": int(datetime.now(UTC).timestamp()) + 600}, secret)
        assert client.get("/api/health",
                          headers={"Authorization": f"Bearer {live}"}).status_code == 200
