"""事件序列化共享层（Q4b，2026-09-09 技术债修复）。

SSE 与 WS 两条流式通道此前各自手搓近乎相同的 payload dict
（app.py 的 _event_to_sse_dict / websocket.py 的 _event_to_ws_dict）
——envelope 结构变更时必须两处同步改，漂移风险高。本模块是
RuntimeEvent 信封（SDD 03 §3）的单一构建点：

- build_event_payload(event, session_id)：AgentEvent → 信封 dict；
- build_session_event_payload(event, session_id)：SessionEvent → 信封 dict。

传输层差异（SSE 包 {"data": json} / WS 直接 dict）留在各自的包装函数里。
"""

from __future__ import annotations

from typing import Any

from agent_harness.agent import AgentEvent
from agent_harness.session import SessionEvent


def _envelope(event: Any, session_id: str, durability: str) -> dict[str, Any]:
    """RuntimeEvent 信封（SDD 03 §3）的单一构建点。

    session_id 由 endpoint 注入——runtime 内部事件不知道自己属于哪个 session，
    但前端需要它在第一帧就能切换 selectedId。
    seq 是幂等投影键，block_id 聚合同一段流式块（ADR-0016 §2.3）。
    schema_version + durability 始终携带；block_id / capability 仅在非 None
    时携带（可选字段不进信封，避免前端拿到无意义 null）。
    """
    payload: dict[str, Any] = {
        "type": event.type,
        "data": event.data,
        "seq": event.seq,
        "run_id": event.run_id,
        "step_id": event.step_id,
        "session_id": session_id,
        "time": event.time,
        "schema_version": event.schema_version,
        "durability": durability,
    }
    if event.block_id is not None:
        payload["block_id"] = event.block_id
    if event.capability is not None:
        payload["capability"] = event.capability
    return payload


def build_event_payload(event: AgentEvent, session_id: str) -> dict[str, Any]:
    """AgentEvent → 信封 payload（SSE live 通道 / WS 共用）。

    durability 取自事件自身（live 事件可能是 ephemeral）。
    """
    return _envelope(event, session_id, event.durability)


def build_session_event_payload(
    event: SessionEvent, session_id: str
) -> dict[str, Any]:
    """SessionEvent → 信封 payload（SSE 重放通道 / WS 共用）。

    帧形状与 live 通道严格同形——客户端对两条通道做同一 seq 幂等投影，
    无需区分帧来源（event_id 仅存于 JSONL/全量接口）。
    durability 恒 "durable"（SessionEvent 已通过 append 词汇表校验）。
    """
    return _envelope(event, session_id, "durable")
