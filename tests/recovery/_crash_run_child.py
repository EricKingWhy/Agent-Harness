"""T8 #138 kill 测试子进程：写一个「开着」的 run 然后真崩溃退出。

不是 pytest 收集对象（文件名不带 test_ 前缀）。父进程用 `sys.executable`
启动它，它写完事件后 `os._exit(9)`——模拟「run 进行中进程被杀」，
磁盘上留下 run/started 但没有 run/completed|failed。

argv[1] 是 JSON：{"root": <目录>, "session_id": <str>}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from agent_harness.session import (
    TOOL_CALL,
    USER_MESSAGE,
    JsonlSessionStore,
    Session,
)


def main() -> None:
    config = json.loads(sys.argv[1])
    root = Path(config["root"])
    store = JsonlSessionStore(root / "sessions")
    session = Session.start(store, session_id=config["session_id"])
    run_id, _ = session.begin_run()
    session.append(USER_MESSAGE, {"content": "do the work"}, run_id=run_id)
    session.append(
        TOOL_CALL,
        {
            "tool_call_id": "call-1",
            "tool_name": "bash",
            "args": {"command": "echo hi"},
        },
        run_id=run_id,
        step_id=1,
    )
    sys.stdout.write("READY\n")
    sys.stdout.flush()
    os._exit(9)  # 崩溃：run 无终态


main()
