"""Q2 spec tests: amend 字段透传（service 层）。

spec 要求（docs/TECH_DEBT_FIX_SPEC.md §Q2）：
  - 新增测试：验证 ``resume_and_launch`` 透传 amend 字段到 ``build_runtime``
    （mock build_runtime，断言参数传递）
  - 新增测试：验证 ``send_message`` idle 分支带 amend 字段时正确透传

端点层（``POST /api/sessions/{id}/resume`` 请求体 → AmendOptions）见
tests/web/test_web_amend_passthrough.py。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from agent_harness.config import Settings
from agent_harness.session.service import AmendOptions, SessionService


def _make_state(tmp_path):
    """构造最小 AppState mock。"""
    settings = Settings(
        workspace_dir=str(tmp_path),
        model_api_key="test-key",
        model_name="test-model",
        model_provider="openai",
    )
    state = MagicMock()
    state.settings = settings
    state.store = MagicMock()
    state.run_manager = MagicMock()
    # launch 返回 (run, subscriber) tuple
    fake_run = MagicMock()
    fake_sub = MagicMock()
    state.run_manager.launch = MagicMock(return_value=(fake_run, fake_sub))
    state.workspace_registry = MagicMock()
    state.workspaces_root = tmp_path
    state.get_wiring = AsyncMock(return_value=(MagicMock(), MagicMock()))
    state.ensure_stores = AsyncMock()
    state.stores = MagicMock()
    return state


class TestResumeAndLaunchPassthrough:
    """``resume_and_launch`` 透传 amend 字段到 ``build_runtime``。"""

    def test_resume_and_launch_passes_amend_fields(self, tmp_path):
        """reasoning_effort / agent_profile / context_providers / model
        全部透传给 build_runtime。"""
        state = _make_state(tmp_path)

        # store.read_events 返回非空列表 → session 存在
        from agent_harness.session.event import SESSION_STARTED, SessionEvent

        existing_event = SessionEvent(
            seq=0,
            type=SESSION_STARTED,
            session_id="test-sid",
            data={},
        )
        state.store.read_events = MagicMock(return_value=[existing_event])
        state.run_manager.get_active = MagicMock(return_value=None)

        # Session.resume 需要 store + workspace_registry
        from agent_harness.sandbox.base import Sandbox

        sandbox = MagicMock(spec=Sandbox)
        state.workspace_registry.get = MagicMock(return_value=sandbox)

        with (
            patch(
                "agent_harness.session.service.build_runtime",
                new_callable=AsyncMock,
            ) as mock_build,
            patch("agent_harness.session.service.Session") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session.session_id = "test-sid"
            mock_session_cls.resume = MagicMock(return_value=mock_session)

            service = SessionService(state)
            asyncio.run(
                service.resume_and_launch(
                    session_id="test-sid",
                    task="hello",
                    max_steps=5,
                    amend=AmendOptions(
                        reasoning_effort="deep",
                        agent_profile="coding",
                        context_providers=["memory"],
                        model="gpt-4o",
                    ),
                )
            )

        # 断言 build_runtime 收到了全部 amend 字段
        call_kwargs = mock_build.call_args.kwargs
        assert call_kwargs["model_name"] == "gpt-4o"
        assert call_kwargs["reasoning_effort"] == "deep"
        assert call_kwargs["agent_profile"] == "coding"
        assert call_kwargs["context_providers"] == ["memory"]

    def test_resume_and_launch_defaults_none(self, tmp_path):
        """不传 amend 字段时，build_runtime 收到 None（当前行为不变）。"""
        state = _make_state(tmp_path)

        from agent_harness.session.event import SESSION_STARTED, SessionEvent

        existing_event = SessionEvent(
            seq=0,
            type=SESSION_STARTED,
            session_id="test-sid",
            data={},
        )
        state.store.read_events = MagicMock(return_value=[existing_event])
        state.run_manager.get_active = MagicMock(return_value=None)

        from agent_harness.sandbox.base import Sandbox

        sandbox = MagicMock(spec=Sandbox)
        state.workspace_registry.get = MagicMock(return_value=sandbox)

        with (
            patch(
                "agent_harness.session.service.build_runtime",
                new_callable=AsyncMock,
            ) as mock_build,
            patch("agent_harness.session.service.Session") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session.session_id = "test-sid"
            mock_session_cls.resume = MagicMock(return_value=mock_session)

            service = SessionService(state)
            asyncio.run(
                service.resume_and_launch(
                    session_id="test-sid",
                    task="hello",
                    max_steps=5,
                )
            )

        call_kwargs = mock_build.call_args.kwargs
        assert call_kwargs["model_name"] is None
        assert call_kwargs["reasoning_effort"] is None
        assert call_kwargs["agent_profile"] is None
        assert call_kwargs["context_providers"] is None


class TestSendMessageIdlePassthrough:
    """``send_message`` idle 分支把 amend 透传给 ``resume_and_launch``。"""

    def test_send_message_idle_forwards_amend(self, tmp_path):
        """idle（无在途 run）→ resume_and_launch 收到完整 amend 对象。"""
        state = _make_state(tmp_path)
        state.run_manager.get_active = MagicMock(return_value=None)

        amend = AmendOptions(
            reasoning_effort="deep",
            agent_profile="coding",
            context_providers=["memory"],
            model="gpt-4o",
        )
        launched = MagicMock()
        launched.session.session_id = "test-sid"
        launched.run = MagicMock()
        launched.subscriber = MagicMock()

        service = SessionService(state)
        with (
            patch.object(
                SessionService, "has_session", new_callable=AsyncMock
            ) as mock_has,
            patch.object(
                SessionService, "resume_and_launch", new_callable=AsyncMock
            ) as mock_resume,
        ):
            mock_has.return_value = True
            mock_resume.return_value = launched
            result = asyncio.run(
                service.send_message(
                    session_id="test-sid",
                    content="继续",
                    mode="queue",
                    amend=amend,
                )
            )

        assert result.status == "launched"
        assert mock_resume.call_args.kwargs["task"] == "继续"
        assert mock_resume.call_args.kwargs["amend"] is amend
