"""Phase 5 同一验收场景，Store 由离线测试或真实七牛测试提供。"""

import json
import os
import shlex
import subprocess
import sys

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from agent_harness.agent import AgentRuntime
from agent_harness.context.builder import ContextBuilder
from agent_harness.sandbox import LocalSubprocessSandbox
from agent_harness.session import (
    MODEL_COMPLETED,
    USER_MESSAGE,
    JsonlSessionStore,
    Session,
)
from agent_harness.storage import SqliteOperationLedger
from agent_harness.storage.artifact import compute_artifact_id
from agent_harness.tooling import PermissionPolicy, ToolExecutor, ToolRegistry
from agent_harness.tooling.overflow import ArtifactOverflowHandler
from agent_harness.tools import BashTool, InspectArtifactTool
from tests.scripted_model import ScriptedModel

RAW_OUTPUT = "".join(f"output {i:04d}\n" for i in range(5000))
ARTIFACT_ID = compute_artifact_id(RAW_OUTPUT)


async def run_phase5_scenario(tmp_path, session, artifact_store, *, stream=True):
    sandbox = LocalSubprocessSandbox(tmp_path / "workspace")
    sandbox.write_text("output.py", "for i in range(5000):\n    print(f'output {i:04d}')\n")
    command = (subprocess.list2cmdline([sys.executable, "output.py"]) if os.name == "nt"
               else shlex.join([sys.executable, "output.py"]))
    # T4 (#134)：auto_compact_threshold 默认升到 0.80，需要更大的初始消息
    # 才能触发压缩（8000 * 0.80 = 6400；"old " * 6500 ≈ 6500 > 6400）。
    # 不能用太大的 N：summary request (prompt + transcript) 必须小于
    # hard_guard (8000 * 0.90 = 7200)，否则 compactor 走 fallback，
    # 不调 model.ainvoke，ScriptedModel 剧本错位。
    session.append(USER_MESSAGE, {"content": "old " * 6500})
    session.append(MODEL_COMPLETED, {"content": "previous turn complete"})
    before = session.events
    summary = AIMessage(content=json.dumps({
        "facts": ["previous turn complete"], "decisions": [], "constraints": [],
        "failed_attempts": [], "unresolved": [], "artifact_refs": [],
        "citations": [], "tool_outcomes": [],
    }))
    # T4 (#134)：bracket 行下压缩只在首次 build 触发一次（derive_messages
    # 跳过 shadowed 事件），后续 build 的 token estimate 远低于 auto threshold。
    # 因此 ScriptedModel 只需 1 条 summary（compactor 消费）+ 3 条 runtime 响应。
    model = ScriptedModel([
        summary,
        AIMessage(content="", tool_calls=[{"id": "bash-1", "name": "bash",
                                           "args": {"command": command}}]),
        AIMessage(content="", tool_calls=[{"id": "inspect-1", "name": "inspect_artifact",
            "args": {"artifact_id": ARTIFACT_ID, "start_line": 2501, "end_line": 2501}}]),
        AIMessage(content="verified output 2500"),
    ])
    registry = ToolRegistry()
    registry.register(BashTool(sandbox))
    registry.register(InspectArtifactTool(artifact_store))
    ledger = SqliteOperationLedger(tmp_path / "ledger.db")
    await ledger.initialize()
    runtime = AgentRuntime(model, registry, ToolExecutor(
        registry, policy=PermissionPolicy.DANGER_FULL_ACCESS, operation_ledger=ledger,
        overflow_handler=ArtifactOverflowHandler(artifact_store),
    ), context_builder=ContextBuilder(model, max_context_tokens=8000))
    if stream:
        emitted = [event async for event in runtime.run_stream(session, "produce then inspect output")]
        assert [(e.type, e.seq, e.data) for e in emitted if e.is_durable] == [
            (e.type, e.seq, e.data) for e in session.events[len(before):]
        ]
    else:
        result = await runtime.run(session, "produce then inspect output")
        assert result.completed and result.steps == 3
    assert session.events[-1].type == "run/completed"
    assert session.events[:len(before)] == before
    assert any(e.type == "artifact/externalized" for e in session.events)
    assert any(e.type == "context/compacted" for e in session.events)
    assert (await artifact_store.load(ARTIFACT_ID)).content == RAW_OUTPUT
    operation = await ledger.get(session.session_id, "bash-1")
    assert operation.artifact_ref == ARTIFACT_ID
    stored_result = json.loads(operation.result_json)
    assert len(stored_result["data"]["stdout"]) <= 2000
    assert stored_result["data"]["exit_code"] == 0
    for snapshot in model.snapshots:
        assert all(RAW_OUTPUT not in str(message.content) for message in snapshot.messages)
    final_messages = model.snapshots[-1].messages
    assert isinstance(final_messages[0], SystemMessage)
    detail = next(m for m in final_messages if isinstance(m, ToolMessage) and m.tool_call_id == "inspect-1")
    assert json.loads(detail.content)["data"]["lines"] == [{"line_number": 2501, "text": "output 2500"}]
    # 新 Store/Session 实例重建全部持久事件，刷新不依赖 Runtime 内存。
    disk_store = JsonlSessionStore(tmp_path / "sessions")
    events = disk_store.read_events(session.session_id)
    assert events == session.events
    reloaded = Session(session.session_id, disk_store, events)
    assert reloaded.derive_messages() == session.derive_messages()
