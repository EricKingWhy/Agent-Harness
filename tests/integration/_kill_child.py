"""Kill 集成测试的子进程入口（#32）。

由 test_kill_resume.py 以真实子进程方式启动：构造 session → 创建 workspace →
经 ToolExecutor（带 kill_hook）执行真实 Tool → 在精确注入点 os._exit，
模拟"状态已落盘、后续步骤未发生"的真实崩溃。

不是 pytest 收集对象（文件名不带 test_ 前缀）。
argv[1] 是 JSON 配置：
    root:           沙盘根目录（sessions/ state.db ws/ 都建在其下）
    calls:          [{"id", "name", "args"}, ...]（顺序执行）
    kill_stage:     注入点（pending | running | terminal）
    kill_call_id:   对哪个 tool_call 注入
hook 未触发时正常退出并打印 NO_KILL（测试用 returncode 检测配置错误）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from agent_harness.sandbox.registry import WorkspaceRegistry
from agent_harness.session import (
    MODEL_COMPLETED,
    TOOL_CALL,
    USER_MESSAGE,
    JsonlSessionStore,
    Session,
)
from agent_harness.storage import OperationContext, SqliteOperationLedger
from agent_harness.tooling import ApprovalResponse, ToolExecutor, ToolRegistry
from agent_harness.tooling.approval import ApprovalRequest
from agent_harness.tools import BashTool, WriteTool


async def _approve_all(_req: ApprovalRequest) -> ApprovalResponse:
    """bash 是 DANGER 级：需要审批 callback 显式放行（Kill 测试需要到注入点）。"""
    return ApprovalResponse(approved=True)


async def main() -> None:
    config = json.loads(sys.argv[1])
    root = Path(config["root"])
    calls = config["calls"]
    kill_stage = config["kill_stage"]
    kill_call_id = config["kill_call_id"]
    kill_delay = config.get("kill_delay_seconds", 0.0)

    store = JsonlSessionStore(root / "sessions")
    ledger = SqliteOperationLedger(root / "state.db")
    await ledger.initialize()
    # Phase 16 T4（ADR-0019 D4/D5）：默认 local，config 可选 backend="docker"
    # 支持 Docker sandbox kill/restore 分段。缺省走 local 不影响 Phase 4 调用方。
    backend = config.get("backend", "local")
    workspaces = WorkspaceRegistry(root / "ws", backend=backend)

    session = Session.start(store)
    sandbox = workspaces.create(session.session_id)  # 崩溃前创建 workspace 映射
    session.append(USER_MESSAGE, {"content": "do the work"})
    session.append(
        MODEL_COMPLETED,
        {
            "content": "",
            "tool_calls": [
                {"id": call["id"], "name": call["name"], "args": call["args"]}
                for call in calls
            ],
        },
        run_id="run-1",
        step_id=1,
    )
    for call in calls:
        session.append(
            TOOL_CALL,
            {
                "tool_call_id": call["id"],
                "tool_name": call["name"],
                "args": call["args"],
            },
            run_id="run-1",
            step_id=1,
        )

    def kill_hook(stage: str, call_id: str) -> None:
        if stage == kill_stage and call_id == kill_call_id:
            if kill_delay:
                # 延迟退出：hook 触发后工具继续真实执行，delay 秒后进程在
                # 【执行中途】死亡——bash RUNNING 场景（#33）的 mid-flight 崩溃。
                import threading

                threading.Timer(kill_delay, os._exit, args=(137,)).start()
            else:
                os._exit(137)  # 真实崩溃：不跑清理、不 flush、直接终止进程

    registry = ToolRegistry()
    registry.register(WriteTool(sandbox))
    registry.register(BashTool(sandbox))
    executor = ToolExecutor(
        registry,
        operation_ledger=ledger,
        # bash 是 DANGER 级：无审批回调时会在 Ledger 写入【之前】被拒，
        # 注入点永远到不了——Kill 测试需要显式放行（模拟已获批准的调用）。
        approval_callback=_approve_all,
        kill_hook=kill_hook,
    )
    for call in calls:
        await executor.execute(
            {"id": call["id"], "name": call["name"], "args": call["args"]},
            operation_context=OperationContext(
                session_id=session.session_id, run_id="run-1", agent_id="default"
            ),
        )

    print("NO_KILL")  # hook 未触发 → 配置错误，测试以 returncode==137 检测


if __name__ == "__main__":
    asyncio.run(main())
