"""Q1 spec test: validate_session_id 对合法/非法输入的行为。

spec 要求（docs/TECH_DEBT_FIX_SPEC.md §Q1）：
  新增 1 个测试：验证 ``validate_session_id`` 对合法/非法输入的行为
  （合法返回原值；非法抛 ``InvalidSessionId``）。
"""

from __future__ import annotations

import pytest

from agent_harness.session.service import InvalidSessionId, validate_session_id


class TestValidateSessionId:
    """``validate_session_id`` 合法 / 非法输入行为。"""

    @pytest.mark.parametrize(
        "sid",
        [
            "abc123",
            "session-uuid-2026",
            "A_B-C-D",
            "a",
            "0",
            "-_",
        ],
    )
    def test_legal_session_id_returns_original(self, sid: str) -> None:
        """合法 session_id 原值返回。"""
        assert validate_session_id(sid) == sid

    @pytest.mark.parametrize(
        "sid",
        [
            "",          # 空串
            "a/b",       # 正斜杠
            "a\\b",      # 反斜杠
            "a.b",       # 点号
            "a b",       # 空格
            "..",        # 目录穿越
            "a*b",       # 通配符
        ],
    )
    def test_illegal_session_id_raises(self, sid: str) -> None:
        """非法 session_id 抛 ``InvalidSessionId``。"""
        with pytest.raises(InvalidSessionId):
            validate_session_id(sid)
