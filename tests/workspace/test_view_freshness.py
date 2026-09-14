"""WS-2/#152 收口（#154 review）：写方法的返回值必须是**提交后**的视图。

`WorkspaceIndex._persist_ledger` 会替换 `_records[workspace_id]`（新 `updated_at`）；
如果 `attach_session` / `insert_session_before` 复用**调用前**抓到的那份 `record` 建视图，
返回对象的 `updated_at` 就是陈旧的——公共 API 的返回值不自洽（写成功了却报告旧时间戳）。

这条在本票（#154）之前不可观测：HTTP 层会重新 `get` 一次。但"返回值自洽"是索引自身的
契约，且 #154 把这两个方法变成了 HTTP 写路径，所以补上判别性用例，防止将来有人把
`self.get(id)` 换回 `self._view(old_record)`。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from agent_harness.assembly import initialize_stores
from agent_harness.config import Settings
from agent_harness.session.service import SessionService
from agent_harness.web.app import AppState


def _state(tmp_path: Path) -> AppState:
    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path), model_api_key="sk-test",
        enable_cors=False,
    )
    state = AppState(settings)
    state.run_manager = MagicMock()
    state.run_manager.get_active = MagicMock(return_value=None)
    state.run_manager.launch = MagicMock(return_value=(MagicMock(), MagicMock()))
    state.get_wiring = AsyncMock(return_value=(MagicMock(), MagicMock()))
    return state


def _launch(state: AppState, **kwargs) -> str:
    with patch(
        "agent_harness.session.service.build_runtime", new_callable=AsyncMock
    ) as build:
        build.return_value = MagicMock()
        result = asyncio.run(
            SessionService(state).create_and_launch(task="hello", max_steps=1, **kwargs)
        )
    return result.session.session_id  # type: ignore[attr-defined]


def test_write_methods_return_the_post_commit_view(tmp_path: Path) -> None:
    """`attach_session` / `insert_session_before` 的返回值 == 随后的 `get()`。"""
    state = _state(tmp_path)
    asyncio.run(initialize_stores(state))

    first = _launch(state, workspace_name="proj")
    index = state.workspace_index
    project = index.list()[0]
    assert project.session_ids == (first,)

    # 造第二个会话（它属于同一目录 → 能 attach 进同一个项目）
    second = _launch(state, workspace_name="proj")

    attached = asyncio.run(index.attach_session(second))
    assert attached is not None
    # 关键断言：返回值里的 updated_at 必须是**提交后**的（不是持久化前那份 record）
    assert attached.updated_at == index.get(project.id).updated_at
    assert attached.session_ids == index.get(project.id).session_ids

    reordered = asyncio.run(index.insert_session_before(second, before=None))
    assert reordered.updated_at == index.get(project.id).updated_at
    assert reordered.session_ids == index.get(project.id).session_ids
    # append 语义：second 从队首挪到队尾
    assert reordered.session_ids[-1] == second
