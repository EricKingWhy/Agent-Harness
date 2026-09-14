"""测试共用夹具：SessionEvent 测试便利 + Settings 环境密封。"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_harness.config import Settings
from agent_harness.session import JsonlSessionStore, Session


def make_session(tmp_path: str | Path) -> Session:
    """构造 ephemeral Session（用 tmp_path 做 SessionStore 根目录）。

    测试用：把"构造 Session + tmp_path JsonlStore"压成一行，让现有测试
    能批量替换为 event-sourced 版本。
    """
    store = JsonlSessionStore(root=tmp_path)
    return Session.start(store)


@pytest.fixture(autouse=True)
def _clean_settings_env(request: pytest.FixtureRequest) -> Iterator[None]:
    """Settings 相关环境变量清洗（集成 AI 移交发现，2026-09-05）。

    `uv run` 默认把 .env 装进进程环境——pydantic-settings 的优先级是
    init kwargs > os.environ > env_file，`_env_file=None` 只屏蔽文件、
    屏蔽不了环境变量。于是任何 .env 带模型配置的机器上，构造
    Settings(_env_file=None) 的单测会读到真实 MODEL_*/MILVUS_* 而假失败
    （preset 断言、缺 model_name 快速失败等全部漂移）。

    autouse 清洗所有 Settings 字段对应的大写环境变量；豁免 qiniu 标记的
    真实集成测试（它们显式依赖真实凭证）。deliberate setenv 的测试不受
    影响（monkeypatch.setenv 发生在本 fixture 之后的测试体内）。
    """
    if "qiniu" in request.keywords:
        yield
        return
    settings_keys = {name.upper() for name in Settings.model_fields}
    saved: dict[str, str] = {}
    for key in list(os.environ):
        if key.upper() in settings_keys:
            saved[key] = os.environ.pop(key)
    try:
        yield
    finally:
        os.environ.update(saved)
