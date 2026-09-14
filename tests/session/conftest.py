"""SessionService 测试专用 fixtures（T1 / #131）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_harness.config import Settings
from agent_harness.session import Session
from agent_harness.web.app import AppState


@pytest.fixture
def app_state(tmp_path: Path) -> AppState:
    """构造一个隔离的 AppState（用 tmp_path 做 workspace_dir）。

    不装配 Capability 子系统（get_wiring 惰性触发时返回空 wiring 或由
    调用方注入 fake）；RunManager 用默认 grace period。
    """
    settings = Settings(
        _env_file=None,
        workspace_dir=str(tmp_path),
        model_api_key="sk-test",
        enable_cors=False,
    )
    return AppState(settings)


@pytest.fixture
def existing_session(app_state: AppState) -> str:
    """在 app_state.store 里预创建一个 session，返回其 session_id。

    用于需要「session 存在但没有在途 run」的测试场景（审批校验等）。
    """
    session = Session.start(app_state.store)
    return session.session_id
