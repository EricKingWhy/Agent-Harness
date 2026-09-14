"""T7 (#137) web 契约：``POST /api/sessions/{id}/model`` + ``POST /api/sessions/{id}/forks``。

契约：`docs/integration/PRD_PHASE_MULTITURN_TOTAL.md` §2.3 / §2.4。
service 层语义见 `tests/session/test_model_change.py`。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_harness.config import Settings
from agent_harness.session.event import (
    MODEL_CHANGED,
    RUN_COMPLETED,
    RUN_STARTED,
    USER_MESSAGE,
)
from agent_harness.session.session import Session
from agent_harness.web.app import create_app

_CATALOG_JSON = (
    '[{"name": "gpt-4o", "provider": "deepseek", "model_name": "gpt-4o-mini"},'
    ' {"name": "glm-4.5", "provider": "zhipu", "model_name": "glm-4.5"}]'
)


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        _env_file=None,
        workspace_dir=str(tmp_path),
        model_api_key="sk-test",
        model_provider="deepseek",
        model_name="deepseek-chat",
        agent_models=_CATALOG_JSON,
    )
    return TestClient(create_app(settings, enable_cors=False))


def _seed(client, session_id: str = "sid-1") -> None:
    Session.start(
        client.app.state.agent.store,
        session_id=session_id,
        workspace_registry=client.app.state.agent.workspace_registry,
        started_data={"provider": "deepseek", "model_id": "gpt-4o"},
    )


def _seed_forkable(client, session_id: str = "sid-1") -> None:
    session = Session.start(
        client.app.state.agent.store,
        session_id=session_id,
        workspace_registry=client.app.state.agent.workspace_registry,
        started_data={"provider": "deepseek", "model_id": "gpt-4o"},
    )
    session.append(USER_MESSAGE, {"content": "first"})
    session.append(RUN_STARTED, {})
    session.append(RUN_COMPLETED, {})


class TestModelEndpoint:
    def test_change_model_returns_changed(self, client):
        _seed(client)

        resp = client.post(
            "/api/sessions/sid-1/model", json={"provider": "zhipu", "model_id": "glm-4.5"}
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "status": "changed",
            "provider": "zhipu",
            "model_id": "glm-4.5",
        }
        events = client.app.state.agent.store.read_events("sid-1")
        assert events[-1].type == MODEL_CHANGED

    def test_unknown_model_422(self, client):
        _seed(client)

        resp = client.post(
            "/api/sessions/sid-1/model", json={"provider": "zhipu", "model_id": "nope"}
        )

        assert resp.status_code == 422

    def test_missing_session_404(self, client):
        resp = client.post(
            "/api/sessions/nope/model", json={"provider": "zhipu", "model_id": "glm-4.5"}
        )

        assert resp.status_code == 404

    def test_blank_model_id_422(self, client):
        _seed(client)

        resp = client.post(
            "/api/sessions/sid-1/model", json={"provider": "zhipu", "model_id": ""}
        )

        assert resp.status_code == 422

    def test_response_returns_canonical_entry_name(self, client):
        """请求给上游 model_name，响应回 catalog 条目名（与事件 / GET /api/models 对齐）。"""
        _seed(client)

        resp = client.post(
            "/api/sessions/sid-1/model",
            json={"provider": "deepseek", "model_id": "gpt-4o-mini"},
        )

        assert resp.status_code == 200
        assert resp.json()["model_id"] == "gpt-4o"
        events = client.app.state.agent.store.read_events("sid-1")
        assert events[-1].data["to_model_id"] == "gpt-4o"

    def test_default_entry_returns_default_model_name_and_clears_override(self, client):
        _seed(client)

        resp = client.post(
            "/api/sessions/sid-1/model",
            json={"provider": "deepseek", "model_id": "deepseek-chat"},
        )

        assert resp.status_code == 200
        assert resp.json()["model_id"] == "deepseek-chat"
        events = client.app.state.agent.store.read_events("sid-1")
        assert events[-1].data["to_model_id"] is None


class TestForkEndpoint:
    def test_fork_returns_child_session_id(self, client):
        _seed_forkable(client)

        resp = client.post("/api/sessions/sid-1/forks", json={"from_seq": 1})

        assert resp.status_code == 200
        body = resp.json()
        assert body["from_seq"] == 1
        assert body["session_id"] != "sid-1"
        assert client.app.state.agent.store.read_events(body["session_id"])

    def test_missing_session_404(self, client):
        resp = client.post("/api/sessions/nope/forks", json={"from_seq": 0})

        assert resp.status_code == 404

    def test_invalid_boundary_422(self, client):
        _seed(client)

        resp = client.post("/api/sessions/sid-1/forks", json={"from_seq": 999})

        assert resp.status_code == 422

    def test_negative_from_seq_422(self, client):
        _seed(client)

        resp = client.post("/api/sessions/sid-1/forks", json={"from_seq": -1})

        assert resp.status_code == 422


class TestModelsEndpointShadowing:
    def test_entry_shadowed_by_default_is_not_listed(self):
        """catalog 条目与默认条目同 provider + 同名 → POST /model 会解析成默认链，
        列表里不该出现这个选不中的死选项。"""
        settings = Settings(
            _env_file=None,
            workspace_dir="/tmp/x",
            model_api_key="sk-test",
            model_provider="deepseek",
            model_name="deepseek-chat",
            agent_models=(
                '[{"name": "deepseek-chat", "provider": "deepseek",'
                ' "model_name": "deepseek-reasoner"},'
                ' {"name": "gpt-4o", "provider": "deepseek",'
                ' "model_name": "gpt-4o-mini"}]'
            ),
        )
        client = TestClient(create_app(settings, enable_cors=False))

        ids = [m["id"] for m in client.get("/api/models").json()["models"]]

        assert ids == ["deepseek-chat", "gpt-4o"]
