"""MemoryNamespace 值对象（A3 深化）：namespace 形状 + 授权 + session 绑定收进一处。"""

from __future__ import annotations

import json

import pytest

from agent_harness.identity import IdentityContext
from agent_harness.memory.types import (
    MemoryNamespace,
    MemoryScope,
    memory_session_var,
    scope_to_namespace,
)


def test_of_user_scope_shape():
    ns = MemoryNamespace.of(MemoryScope.USER, IdentityContext("acme", "alice", ["user"]))
    assert ns.as_tuple() == ("memories", "acme", "alice", "user")
    assert ns.scope is MemoryScope.USER
    assert ns.session_id is None
    # 存储兼容：与旧 scope_to_namespace 的 JSON 序列化逐字节一致。
    assert ns.as_json() == json.dumps(scope_to_namespace(MemoryScope.USER, IdentityContext("acme", "alice", ["user"])))


def test_of_session_scope_with_explicit_session_id():
    """显式 session_id 优先，ContextVar 未绑定时也能构造——依赖从隐藏变可见。"""
    ns = MemoryNamespace.of(
        MemoryScope.SESSION, IdentityContext("acme", "alice", ["session"]), session_id="s-42",
    )
    assert ns.as_tuple() == ("memories", "acme", "alice", "session", "s-42")
    assert ns.session_id == "s-42"


def test_of_session_scope_without_binding_raises():
    ns_id = IdentityContext("acme", "alice", ["session"])
    with pytest.raises(ValueError, match="session binding"):
        MemoryNamespace.of(MemoryScope.SESSION, ns_id)


def test_of_rejects_unauthorized_and_unimplemented_scopes():
    with pytest.raises(PermissionError):
        MemoryNamespace.of(MemoryScope.SESSION, IdentityContext("acme", "alice", ["user"]))
    with pytest.raises(NotImplementedError):
        MemoryNamespace.of(MemoryScope.GLOBAL, IdentityContext("acme", "alice", ["global"]))


def test_pk_parts_are_stable():
    ns = MemoryNamespace.of(MemoryScope.USER, IdentityContext("acme", "alice", ["user"]))
    assert ns.pk_parts("m1") == ["memories", "acme", "alice", "user", "m1"]


def test_authorize_accepts_own_namespace():
    identity = IdentityContext("acme", "alice", ["user", "session"])
    ns = MemoryNamespace.authorize(("memories", "acme", "alice", "user"), identity)
    assert ns.scope is MemoryScope.USER
    # SESSION 归属校验沿用 ADR-0009 语义：contextvar 绑定的可信 session。
    token = memory_session_var.set("s-1")
    try:
        ns = MemoryNamespace.authorize(
            ("memories", "acme", "alice", "session", "s-1"), identity,
        )
        assert ns.session_id == "s-1"
    finally:
        memory_session_var.reset(token)


def test_authorize_rejects_foreign_or_malformed():
    identity = IdentityContext("acme", "alice", ["user"])
    with pytest.raises(PermissionError):
        MemoryNamespace.authorize(("memories", "other", "alice", "user"), identity)
    with pytest.raises(PermissionError):
        MemoryNamespace.authorize(("memories", "acme", "bob", "user"), identity)
    with pytest.raises(PermissionError):
        MemoryNamespace.authorize(("memories", "acme", "alice"), identity)
    with pytest.raises(PermissionError):
        MemoryNamespace.authorize(("not-root", "acme", "alice", "user"), identity)
    # 未实现的 scope 沿用 of() 的 NotImplementedError（与旧 adapter 行为一致）。
    with pytest.raises(NotImplementedError):
        MemoryNamespace.authorize(("memories", "acme", "alice", "global"), identity)
