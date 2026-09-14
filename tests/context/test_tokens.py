"""Token 估算的公开接口：固定 cl100k_base，支持任意用户文本。"""

import pytest

from agent_harness.context.tokens import estimate_tokens


@pytest.mark.parametrize(
    ("text", "expected"),
    [("", 0), ("hello world", 2), ("你好世界", 5)],
)
def test_estimate_tokens_known_text(text: str, expected: int):
    assert estimate_tokens(text) == expected


def test_special_token_spelling_is_counted_as_ordinary_user_text():
    assert estimate_tokens("<|endoftext|>") == 7
