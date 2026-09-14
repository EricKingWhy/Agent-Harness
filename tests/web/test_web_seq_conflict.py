"""BUG-011：seq 冲突的 HTTP 语义——409（冲突）而不是 404（不存在）。

真机现场（会话 `dd983104`）：模型项被双击 → 两个并发 ``POST /model`` 各自基于同一
快照取号 → 日志里两条 seq=5 → 此后 ``POST /messages`` 返回 **404** + detail
「事件 seq 重复: 5」——把**数据完整性**问题谎报成「会话不存在」，前端只能显示
``续聊失败：Send failed: 404``。契约：seq 冲突 → **409**，detail 说明是 seq 冲突。

为什么 409 而不是 500：409 = 请求与资源当前状态冲突（并发写者抢先落盘 / 日志已
不满足单调性），这是可判读的领域冲突，不是未处理的内部错误。写时冲突可重试
（`service.change_model` 会重读快照），读时冲突（日志已损坏）不可自愈。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_harness.config import Settings
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


def _corrupt_log(tmp_path: Path, session_id: str = "sid-1") -> None:
    """制造历史损坏形态：把最后一行复制一份（重复 seq）。

    守卫已禁止新写入重复 seq，故这里直接伪造落盘文件——模拟 BUG-011 之前
    已被写坏的会话，以及「存量损坏日志」这一真实输入。
    """
    path = tmp_path / "sessions" / session_id / "events.jsonl"
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    with path.open("a", encoding="utf-8") as fh:
        fh.write(lines[-1] + "\n")


class TestCorruptLogHttpSemantics:
    def test_continue_returns_409_not_404(self, client, tmp_path):
        _seed(client)
        _corrupt_log(tmp_path)

        res = client.post(
            "/api/sessions/sid-1/messages",
            json={"content": "再问一次", "mode": "queue", "max_steps": 5},
        )

        assert res.status_code == 409, res.text
        detail = res.json()["detail"]
        assert "seq" in detail, detail
        assert "not found" not in detail, "数据完整性问题被谎报成「会话不存在」"

    def test_model_change_returns_409_not_200(self, client, tmp_path):
        """损坏日志上继续切换模型也会掩盖损坏（写成功、会话依旧不可 resume）。"""
        _seed(client)
        _corrupt_log(tmp_path)

        res = client.post(
            "/api/sessions/sid-1/model",
            json={"provider": "deepseek", "model_id": "gpt-4o"},
        )

        assert res.status_code == 409, res.text
        assert "seq" in res.json()["detail"]

    def test_resume_returns_409(self, client, tmp_path):
        _seed(client)
        _corrupt_log(tmp_path)

        res = client.post("/api/sessions/sid-1/resume", json={"task": "继续"})

        assert res.status_code == 409, res.text
        assert "seq" in res.json()["detail"]

    def test_healthy_session_is_unaffected(self, client, tmp_path):
        """对照组：不损坏的会话上，/model 仍 200（守卫不得拦住正常写入）。"""
        _seed(client)

        res = client.post(
            "/api/sessions/sid-1/model",
            json={"provider": "zhipu", "model_id": "glm-4.5"},
        )

        assert res.status_code == 200, res.text
        seqs = [e.seq for e in client.app.state.agent.store.read_events("sid-1")]
        assert seqs == sorted(set(seqs))
