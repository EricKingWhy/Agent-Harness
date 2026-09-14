"""Phase 5 切片 A：permission_mode 替换 auto_approve（SDD 06 Phase 5）。

验收映射：
- 三档 permission_mode 各发一次 → assembly.build_runtime 拿到正确 PermissionPolicy。
- 旧 auto_approve 字段保留为 deprecated alias（向后兼容）。
- 两者同传 → permission_mode 优先。
- 非法 permission_mode → 422。

策略：monkeypatch assembly.build_runtime 捕获 kwargs，避免触发真实装配。
只验「请求体被正确解析并路由到 build_runtime」，不跑真实 run。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_harness.config import Settings
from agent_harness.session import service as service_module
from agent_harness.tooling.contract import PermissionPolicy
from agent_harness.web.app import create_app


@pytest.fixture
def captured_build(monkeypatch, tmp_path):
    """替换 assembly.build_runtime，捕获 kwargs 并短路返回。

    create_session 在 build_runtime 之后还会调 Session.start 和
    run_manager.launch——为了避免真实 run，我们也截掉 launch。
    返回 (client, calls) 列表，calls 每条是一次 build_runtime 的 kwargs。
    """
    calls: list[dict] = []

    async def _fake_build(**kwargs):
        calls.append(kwargs)
        # 返回一个占位对象；后续 Session.start + launch 会被另一处 patch 拦掉
        return object()

    monkeypatch.setattr(service_module, "build_runtime", _fake_build)
    # launch 同步函数（不 async）；返回带 unsubscribe 的 fake run + 真实 Subscriber
    # （队列里预先塞入 DONE sentinel，event_generator 拿到就立刻干净收尾）。
    from agent_harness.web.runmanager import RunManager, Subscriber

    def _fake_launch(self, session, runtime, user_input):
        sub = Subscriber()
        sub.queue.put_nowait(self.DONE)
        return _FakeRun(), sub

    monkeypatch.setattr(RunManager, "launch", _fake_launch)

    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path),
        model_api_key="sk-test", enable_cors=False,
    )
    client = TestClient(create_app(settings, enable_cors=False))
    return client, calls


class _FakeRun:
    """占位 run：模拟 ManagedRun 最小接口（unsubscribe + task）。"""

    task = None  # ManagedRun.launch 后必设；mock 里永远 None（不触发 GC 回调）

    def unsubscribe(self, _sub):
        pass


def _consume_sse(resp):
    """create_session 返回 SSE 流；读取直到流结束，返回 frame 列表。"""
    import json as _json

    frames = []
    for line in resp.iter_lines():
        if not line or not line.startswith("data:"):
            continue
        try:
            frames.append(_json.loads(line[len("data:"):].strip()))
        except _json.JSONDecodeError:
            continue
    return frames


class TestPermissionModeRouting:
    def test_permission_mode_accepted_and_routing(self, captured_build):
        """三档 mode 各发一次 → build_runtime 收到对应 PermissionPolicy。"""
        client, calls = captured_build
        for mode in ("read-only", "workspace-write", "danger-full-access"):
            calls.clear()
            with client.stream(
                "POST", "/api/sessions",
                json={"task": "t", "permission_mode": mode},
            ) as resp:
                assert resp.status_code == 200
                _consume_sse(resp)
            assert len(calls) == 1, f"mode={mode} 应触发一次 build_runtime"
            assert calls[0]["permission_mode"] == PermissionPolicy(mode)

    def test_auto_approve_backward_compat_true(self, captured_build):
        """只传 auto_approve=true → workspace-write + approval_callback=None
        （build_runtime 默认 auto-approve，旧行为）。"""
        client, calls = captured_build
        with client.stream(
            "POST", "/api/sessions",
            json={"task": "t", "auto_approve": True},
        ) as resp:
            assert resp.status_code == 200
            _consume_sse(resp)
        assert calls[0]["permission_mode"] == PermissionPolicy.WORKSPACE_WRITE
        # auto_approve=true → web 不注入 deny callback → None（assembly 默认 auto-approve）
        assert calls[0]["approval_callback"] is None

    def test_auto_approve_backward_compat_false(self, captured_build):
        """只传 auto_approve=false → workspace-write + deny callback（旧行为）。"""
        client, calls = captured_build
        with client.stream(
            "POST", "/api/sessions",
            json={"task": "t", "auto_approve": False},
        ) as resp:
            assert resp.status_code == 200
            _consume_sse(resp)
        assert calls[0]["permission_mode"] == PermissionPolicy.WORKSPACE_WRITE
        # auto_approve=false → web 注入 deny callback（manual approval not yet wired）
        cb = calls[0]["approval_callback"]
        assert cb is not None
        import asyncio
        result = asyncio.new_event_loop().run_until_complete(cb(None))
        assert result.approved is False

    def test_permission_mode_overrides_auto_approve(self, captured_build):
        """两者同传 → permission_mode 优先。"""
        client, calls = captured_build
        with client.stream(
            "POST", "/api/sessions",
            json={
                "task": "t",
                "permission_mode": "danger-full-access",
                "auto_approve": False,  # 若 auto_approve 赢就会变 deny
            },
        ) as resp:
            assert resp.status_code == 200
            _consume_sse(resp)
        assert calls[0]["permission_mode"] == PermissionPolicy.DANGER_FULL_ACCESS

    def test_default_when_neither_passed(self, captured_build):
        """两个字段都缺省 → workspace-write + approval_callback=None（auto-approve）。"""
        client, calls = captured_build
        with client.stream("POST", "/api/sessions", json={"task": "t"}) as resp:
            assert resp.status_code == 200
            _consume_sse(resp)
        assert calls[0]["permission_mode"] == PermissionPolicy.WORKSPACE_WRITE
        assert calls[0]["approval_callback"] is None

    def test_invalid_permission_mode_422(self, captured_build):
        """非法 mode → 422（FastAPI 自动校验）。"""
        client, calls = captured_build
        resp = client.post(
            "/api/sessions",
            json={"task": "t", "permission_mode": "delete-everything"},
        )
        assert resp.status_code == 422
        assert calls == [], "422 时不应触发 build_runtime"


def _run_cb(cb):
    """sync callback 调用入口（保留为工具函数；切片 B 后所有 callback 为 async）。"""
    return cb(None)

