"""Phase 2 只读端点测试（SDD 03 §10 + §17）。

覆盖：
- GET /api/permission-modes：返回三个真实 PermissionPolicy + 描述；
- GET /api/capabilities：**core 条目恒在**（内置工具集的声明，见 #193）——
  默认配置下也声明 `changes`/`terminal`，否则前端 `centerTabs` 会把两个面滤掉；
- GET /api/capabilities：注入 fake descriptor → 投影 manifest（含 surfaces 默认值）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_harness.capability.base import (
    CapabilityDescriptor,
    CapabilityRegistry,
    Degradation,
)
from agent_harness.capability.manifest import CORE_CAPABILITY_ID
from agent_harness.config import Settings
from agent_harness.web.app import create_app


@pytest.fixture
def bare_client(tmp_path):
    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path),
        model_api_key="sk-test", enable_cors=False,
    )
    return TestClient(create_app(settings, enable_cors=False))


# ── GET /api/permission-modes ──

class TestPermissionModes:
    def test_lists_real_policies(self, bare_client):
        """返回三个真实 PermissionPolicy + 人类可读描述。"""
        resp = bare_client.get("/api/permission-modes")
        assert resp.status_code == 200
        body = resp.json()
        modes = body["modes"]
        ids = [m["id"] for m in modes]
        assert ids == ["read-only", "workspace-write", "danger-full-access"]
        for m in modes:
            assert m["display_name"], "每个 mode 必须有 display_name"
            assert m["description"], "每个 mode 必须有 description"


# ── GET /api/capabilities ──

class TestCapabilities:
    def test_core_manifest_is_always_there(self, bare_client):
        """默认 `CAPABILITIES=""`（零插件）也返回 **core 条目**，并声明核心能产出的面。

        为什么这条是硬要求（#193）：前端 `centerTabs` 的判据是"能力声明为 true **且**已实现"。
        `changes`（「文件/改动」）与 `terminal`（「输出」）由**内置工具**产出——
        `write`/`edit`/`apply_patch`（改动）与 `bash`（命令输出），它们在
        `assembly.build_runtime` 里**无条件注册**，不由任何插件 capability 产出。
        此前端点只投影插件 descriptor，而 7 个 descriptor 都没填 `surfaces` ⇒ 保守默认
        给出 `changes/terminal = false` ⇒ 两个面在**任何真实部署**里都被滤掉（e2e 之所以
        能看到，是因为它们注入了 `true`——后端发不出那种载荷）。
        """
        resp = bare_client.get("/api/capabilities")
        assert resp.status_code == 200
        caps = resp.json()["capabilities"]

        core = [c for c in caps if c["id"] == CORE_CAPABILITY_ID]
        assert len(core) == 1, f"core 条目必须恒在且唯一：{[c['id'] for c in caps]}"
        entry = core[0]
        assert entry["display_name"], "manifest 条目必须有 display_name"
        assert entry["surfaces"] == {
            "chat": True, "timeline": True,
            "changes": True, "terminal": True,
            # artifacts 不在 core 的声明里：外置产物取决于**部署是否配了 store**
            # （没配就 503），不是内置工具集无条件产出的东西。
            "artifacts": False,
        }
        # 交付判据（#193 AC1）——前端取**并集**，所以真正要成立的是"至少一条声明为真"
        assert any(c["surfaces"]["changes"] for c in caps)
        assert any(c["surfaces"]["terminal"] for c in caps)

    def test_core_actions_match_really_wired_entry_points(self, bare_client):
        """core 的 `actions` 如实声明：三个有路由、`retry` 没有。

        不写"保守全 false"是因为那对本条目就是**假话**（路由明明在）：
        `permissions` → `POST /api/sessions/{id}/approve`，
        `stop` → `POST /api/sessions/{id}/cancel`，
        `resume` → `POST /api/sessions/{id}/resume`。
        `retry` 没有任何后端入口 ⇒ false（前端当前不消费 actions，但声明本身要真）。
        """
        caps = bare_client.get("/api/capabilities").json()["capabilities"]
        actions = next(c for c in caps if c["id"] == CORE_CAPABILITY_ID)["actions"]
        assert actions == {
            "permissions": True, "stop": True, "retry": False, "resume": True,
        }

    def test_reflects_registry_and_keeps_core_first(self, tmp_path, monkeypatch):
        """core 与插件 descriptor 并存；插件条目仍走**它自己的**保守默认。

        条目级不做并集（那是前端的 `deriveSurfaces` 的活）：这里只保证两件事——
        core 在、插件条目的投影逐字段不变（既有契约不回归）。
        """
        fake_descriptor = CapabilityDescriptor(
            name="memory",
            version="1.0.0",
            provider_name="builtin",
            degradation=Degradation.OPTIONAL_RUNTIME,
        )
        fake_registry = CapabilityRegistry()
        fake_registry.register(fake_descriptor, provider=object())

        settings = Settings(
            _env_file=None, workspace_dir=str(tmp_path),
            model_api_key="sk-test", enable_cors=False,
            # 用一个真实 capability 配置触发装配（但我们会替换 registry）
            capabilities='{"memory": {"provider": "builtin"}}',
        )
        app = create_app(settings, enable_cors=False)

        # 注入 fake registry：绕过真实装配，直接替换 get_wiring 的产物。
        async def stub_get_wiring():
            app.state.agent._registry = fake_registry
            # wiring 字段必须非 None 才能跳过真实装配路径
            from agent_harness.capability.wiring import CapabilityWiring
            app.state.agent._wiring = CapabilityWiring()
            return app.state.agent._registry, app.state.agent._wiring

        app.state.agent.get_wiring = stub_get_wiring
        client = TestClient(app)

        resp = client.get("/api/capabilities")
        assert resp.status_code == 200
        caps = resp.json()["capabilities"]
        assert [c["id"] for c in caps] == [CORE_CAPABILITY_ID, "memory"]
        cap = caps[1]
        assert cap["id"] == "memory"
        assert cap["display_name"] == "memory"  # display_name 缺省回落 name
        assert cap["version"] == "1.0.0"
        assert cap["provider_name"] == "builtin"
        # 未声明 surfaces → 保守默认：chat/timeline=true，余=false
        assert cap["surfaces"] == {
            "chat": True, "timeline": True,
            "changes": False, "terminal": False, "artifacts": False,
        }
        # 未声明 actions → 全 false
        assert cap["actions"] == {
            "permissions": False, "stop": False,
            "retry": False, "resume": False,
        }

    def test_descriptor_surfaces_override_default(self, tmp_path):
        """descriptor 显式声明 surfaces → 以声明为准（不替换为默认）。"""
        fake_descriptor = CapabilityDescriptor(
            name="memory",
            version="1.0.0",
            provider_name="builtin",
            degradation=Degradation.OPTIONAL_RUNTIME,
            surfaces={"chat": True, "timeline": False, "artifacts": True},
        )
        fake_registry = CapabilityRegistry()
        fake_registry.register(fake_descriptor, provider=object())

        settings = Settings(
            _env_file=None, workspace_dir=str(tmp_path),
            model_api_key="sk-test", enable_cors=False,
            capabilities='{"memory": {"provider": "builtin"}}',
        )
        app = create_app(settings, enable_cors=False)

        async def stub_get_wiring():
            from agent_harness.capability.wiring import CapabilityWiring
            app.state.agent._registry = fake_registry
            app.state.agent._wiring = CapabilityWiring()
            return app.state.agent._registry, app.state.agent._wiring

        app.state.agent.get_wiring = stub_get_wiring
        client = TestClient(app)

        resp = client.get("/api/capabilities")
        body = resp.json()
        # 按 id 取插件条目：core 条目恒在最前（见上面两条用例），位置断言会脆。
        cap = next(c for c in body["capabilities"] if c["id"] == "memory")
        # 显式声明覆盖默认：timeline=false（而非默认 true），artifacts=true
        assert cap["surfaces"]["timeline"] is False
        assert cap["surfaces"]["artifacts"] is True
        # 未声明的键（changes/terminal）仍回落保守默认 false
        assert cap["surfaces"]["changes"] is False
        assert cap["surfaces"]["terminal"] is False
