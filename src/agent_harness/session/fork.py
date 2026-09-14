"""Fork：从父 Session 事件前缀派生新独立会话（Phase 14, ADR-0017）。

file-per-lineage（决策 1）：fork = 新 session 文件；每个 session 保持
append-only 线性 JSONL，树是 SessionMetaStore 索引层的元数据关系。

- boundary（决策 2）：机制上 seed 前缀必须止于 run 终态之后（child 文件
  绝不以悬空 run 开头）；UX 选择器 = 「从第 N 条用户消息分叉」——锚点
  消息本身不进 seed（child 侧由用户重新发送，pi /fork 同款语义）。
- seed（决策 3）：事件前缀逐字复制进 child（Session.adopt_history 重编
  seq、保留原 event_id），child 自包含可读，不依赖父文件存活。
- provenance（决策 8）：session/forked 只落 child 文件，父文件一字不改
  （父会话以 store.read_events 只读加载——绝不能 resume，那会写父）。
- 索引（决策 7）：fork 同时 upsert SessionMeta（origin=fork）。
"""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from langchain_core.messages import HumanMessage

from agent_harness.prompt import DEFAULT_REGISTRY
from agent_harness.session.cwd import session_cwd
from agent_harness.session.event import (
    AGENT_DELEGATION_FINISHED,
    MODEL_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    RUN_TERMINAL_TYPES,
    SESSION_FORKED,
    SESSION_STARTED,
    TOOL_CALL,
    TOOL_RESULT,
    USER_MESSAGE,
    SessionEvent,
)
from agent_harness.session.session import Session
from agent_harness.storage.session_meta import SessionMeta

if TYPE_CHECKING:
    from agent_harness.sandbox.registry import WorkspaceRegistry
    from agent_harness.session.store import JsonlSessionStore
    from agent_harness.storage.session_meta import SessionMetaStore

logger = logging.getLogger("agent_harness.session.fork")

#: tail 摘要输入的字符上限（尾部截断）——保护摘要调用不被超长会话打爆。
_MAX_TAIL_CHARS = 8000


class TailSummarizerProtocol(Protocol):
    """tail 摘要 seam：任何提供 async summarize(text)->str 的对象可用。"""

    async def summarize(self, text: str) -> str: ...


def render_tail_transcript(tail_events: list[SessionEvent]) -> str:
    """把 fork 点之后的事件渲染成有界可读文本（摘要器的输入）。"""
    lines: list[str] = []
    for event in tail_events:
        if event.type == USER_MESSAGE:
            lines.append(f"[user] {event.data.get('content', '')}")
        elif event.type == MODEL_COMPLETED:
            lines.append(f"[assistant] {event.data.get('content', '')}")
        elif event.type == TOOL_CALL:
            lines.append(f"[tool] {event.data.get('tool_name', '')}")
        elif event.type == TOOL_RESULT:
            content = str(event.data.get("content", ""))[:200]
            lines.append(f"[tool-result] {content}")
        elif event.type == RUN_FAILED:
            lines.append(
                f"[run] failed（{event.data.get('reason', 'unspecified')}）"
            )
        elif event.type == AGENT_DELEGATION_FINISHED:
            lines.append(
                f"[delegation] {event.data.get('target', '')}"
                f" → {event.data.get('status', '')}"
            )
    return "\n".join(lines)[-_MAX_TAIL_CHARS:]


class TailSummarizer:
    """tail 摘要器（ADR-0017 决策 9）：任何 ainvoke(messages)->AIMessage 的模型可用。

    pi branch_summary / oh-my-pi rewind-report 的 file-per-lineage 对应物：
    把「被放弃的线得出了什么」压缩成一段可携带的上下文。恰好一次调用，
    无重试放大；失败由调用方降级（fork 照常）。
    """

    def __init__(self, model, *, max_tail_chars: int = _MAX_TAIL_CHARS) -> None:
        self._model = model
        self._max_tail_chars = max_tail_chars

    async def summarize(self, tail_text: str) -> str:
        tail_text = tail_text[-self._max_tail_chars :]
        prompt = DEFAULT_REGISTRY.assemble(
            "aux:fork_tail", {"tail_text": tail_text}
        ).meta_user_text
        response = await self._model.ainvoke([HumanMessage(content=prompt)])
        return str(response.content)


class ForkBoundaryError(ValueError):
    """非法 fork 边界：锚点不存在 / 不是用户消息 / 前缀含未终态 run。"""


def find_fork_boundaries(events: list[SessionEvent]) -> list[int]:
    """列出合法 fork 锚点（用户消息 seq，锚点语义：seed = [0, seq)）。

    规则：锚点处的 seed 前缀必须 run 完整——逐事件跟踪 run/started 与
    run 终态（`RUN_TERMINAL_TYPES`：completed / failed / interrupted）的
    开合计数，计数为 0 时遇到的用户消息才是合法切点。
    """
    boundaries: list[int] = []
    open_runs = 0
    for event in events:
        if event.type == RUN_STARTED:
            open_runs += 1
        elif event.type in RUN_TERMINAL_TYPES:
            open_runs -= 1
        elif event.type == USER_MESSAGE and open_runs == 0:
            boundaries.append(event.seq)
    return boundaries


async def fork_session(
    store: JsonlSessionStore,
    meta_store: SessionMetaStore,
    parent_session_id: str,
    *,
    boundary_user_message_seq: int,
    child_session_id: str | None = None,
    agent_id: str = "default",
    workspace_registry: WorkspaceRegistry | None = None,
    summarizer: TailSummarizerProtocol | None = None,
    with_tail_summary: bool = True,
) -> Session:
    """从父会话的第 boundary_user_message_seq 条用户消息处 fork 出 child。

    锚点消息不进 seed；seed = 锚点之前的全部事件（父的 session/started 除
    外——child 写自己的身份事件）。失败时不留任何 child 侧孤儿（先校验后
    落盘）。
    """
    # 父会话只读加载（§7 父不可改：绝不能 Session.resume，那会追加 resumed）
    parent_events = store.read_events(parent_session_id)
    if not parent_events:
        raise ForkBoundaryError(
            f"Session '{parent_session_id}' 不存在或事件日志为空"
        )

    anchor = next(
        (
            e
            for e in parent_events
            if e.seq == boundary_user_message_seq
        ),
        None,
    )
    if anchor is None or anchor.type != USER_MESSAGE:
        available = find_fork_boundaries(parent_events)
        raise ForkBoundaryError(
            f"fork 边界 seq={boundary_user_message_seq} 不是父会话中的用户消息"
            f"（可用边界: {available}）"
        )

    seed = [
        e
        for e in parent_events
        if e.seq < anchor.seq and e.type != SESSION_STARTED
    ]
    _validate_run_complete(seed, parent_session_id)

    # 校验全部通过后才落盘：先建 child，再做 workspace 物理复制，再移植
    # seed 与 provenance/索引（copy 失败属基础设施故障，原样上抛）。
    # WS-1 #151 AC4：child 的 cwd **显式继承自 parent**（不靠"反正目录是复制来的"
    # 隐式成立）。父无 cwd（历史遗留）→ child 也不写该字段，父子的未分组状态一致。
    child = Session.start(
        store, agent_id=agent_id, session_id=child_session_id,
        workspace_registry=workspace_registry,
        cwd=session_cwd(parent_events),
    )
    if workspace_registry is not None:
        _copy_workspace(workspace_registry, parent_session_id, child)
    child.adopt_history(seed)
    fork_point_seq = seed[-1].seq if seed else None

    # tail summary（决策 9）：锚点之后被放弃的路线压缩成一段上下文。
    # 恰好一次调用、无重试；失败降级不挂接，fork 照常（不变量 #21）。
    tail_summary: str | None = None
    tail_events = [e for e in parent_events if e.seq > anchor.seq]
    if summarizer is not None and with_tail_summary and tail_events:
        try:
            tail_summary = await summarizer.summarize(
                render_tail_transcript(tail_events)
            )
        except Exception:
            logger.warning(
                "tail summary 生成失败——降级不挂接（fork 照常完成）", exc_info=True
            )
            tail_summary = None

    forked_data: dict = {
        "parent_session_id": parent_session_id,
        "boundary_user_message_seq": anchor.seq,
        "fork_point_seq": fork_point_seq,
    }
    if tail_summary:
        forked_data["tail_summary"] = tail_summary
    child.append(SESSION_FORKED, forked_data, agent_id=agent_id)

    await meta_store.upsert(
        SessionMeta(
            session_id=child.session_id,
            created_at=datetime.now(UTC).isoformat(timespec="milliseconds"),
            agent_id=agent_id,
            parent_session_id=parent_session_id,
            origin="fork",
            fork_point_seq=fork_point_seq,
        )
    )
    return child


def _copy_workspace(
    registry, parent_session_id: str, child: Session
) -> None:
    """copy-on-fork（ADR-0017 决策 5）：父 workspace 整目录复制为 child 的。

    物理策略独立于事件 fork（spec §7）。父无 workspace / 目录不存在 =
    child 空 workspace（降级）。Artifact 是全局 store 的内容寻址 ref——
    随事件 seed 原样可用，绝不复制（规格「Artifact Ref 按权限复用」）。
    复制失败 = 基础设施故障，原样上抛（fork 不带残缺快照继续）。
    """
    if not registry.exists(parent_session_id):
        return
    parent_root = registry.get(parent_session_id).workspace_root
    child_sandbox = child.sandbox
    if child_sandbox is None:
        return
    if parent_root.is_dir():
        shutil.copytree(
            parent_root, child_sandbox.workspace_root, dirs_exist_ok=True
        )


def _validate_run_complete(
    seed: list[SessionEvent], parent_session_id: str
) -> None:
    open_runs = 0
    for event in seed:
        if event.type == RUN_STARTED:
            open_runs += 1
        elif event.type in RUN_TERMINAL_TYPES:
            open_runs -= 1
        if open_runs < 0:
            raise ForkBoundaryError(
                f"父会话 '{parent_session_id}' 前缀 run 事件序非法（负计数）"
            )
    if open_runs > 0:
        raise ForkBoundaryError(
            f"父会话 '{parent_session_id}' 前缀以未终态 run 结尾"
            "（child 不允许以悬空 run 开头）"
        )
