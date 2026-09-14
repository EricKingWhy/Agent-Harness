"""Live Agent demo — 用眼睛看见 AgentRuntime 真在干活。

为什么有这个文件
----------------
本项目是 Agent Harness（框架），不是终端应用；zcode/codex 把能力全造好了
（AgentRuntime + 9 个 Coding Tools + LocalSandbox + SessionEvent 持久化），
但没有任何"用户可见入口"。这个 demo 把已造好的零件接成一只能看见的 agent：
你在终端输入任务 → 看它一轮轮思考、调工具、拿到结果、给最终回答。

只读取/复用项目现有 API，不修改任何框架代码。GitHub Issues 仍是事实源，
spec 不变，roadmap 不变——这是一份纯可见性 demo。

前置
----
.env 里要有 MODEL_API_KEY 和 MODEL_NAME（和集成测试一样）。没有就退出并提示。

用法
----
    uv run python demo/live_agent.py
    uv run python demo/live_agent.py --task "在 workspace 建个 hello.py 并跑一下"
    uv run python demo/live_agent.py --workspace ./_demo_workspace --max-steps 10

不带 --task 进入交互模式；每输一行就是一次任务，输入 :q 退出。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

# 阿里 MaaS 域名加入 NO_PROXY（与 tests/agent/test_integration_coding.py 同款处理）。
# 必须在 import openai/httpx 之前设好，否则本地代理的 TLS 不兼容会挂。
_MAAS_DOMAIN = "ws-z6pxn1u9u3hqds3j.cn-beijing.maas.aliyuncs.com"
_existing_no_proxy = os.environ.get("NO_PROXY", "")
if _MAAS_DOMAIN not in _existing_no_proxy:
    os.environ["NO_PROXY"] = f"{_existing_no_proxy},{_MAAS_DOMAIN},aliyuncs.com".lstrip(",")
    os.environ["no_proxy"] = os.environ["NO_PROXY"]

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

# 确认能 import 项目本身（uv 已经把 src 装进去了；手动跑也兜底）
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from agent_harness.agent import AgentRuntime
from agent_harness.config import Settings
from agent_harness.model.config import ModelConfig
from agent_harness.model.provider import create_chat_model
from agent_harness.sandbox import LocalSubprocessSandbox
from agent_harness.session import (
    MODEL_COMPLETED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    SESSION_STARTED,
    TOOL_CALL,
    TOOL_RESULT,
    USER_MESSAGE,
    JsonlSessionStore,
    Session,
)
from agent_harness.tooling import ToolExecutor, ToolRegistry
from agent_harness.tooling.approval import (
    ApprovalRequest,
    ApprovalResponse,
)
from agent_harness.tooling.contract import PermissionPolicy
from agent_harness.tools import (
    ApplyPatchTool,
    BashTool,
    EditTool,
    GitDiffTool,
    GitStatusTool,
    GlobTool,
    GrepTool,
    ReadTool,
    WriteTool,
)

console = Console()

# 事件类型 → 面板边框颜色（rich 颜色名）
EVENT_STYLE: dict[str, str] = {
    SESSION_STARTED: "cyan",
    USER_MESSAGE: "green",
    RUN_STARTED: "blue",
    MODEL_COMPLETED: "magenta",
    TOOL_CALL: "yellow",
    TOOL_RESULT: "yellow",
    RUN_COMPLETED: "blue",
    RUN_FAILED: "red",
}


def _build_runtime(
    workspace: Path,
    settings: Settings,
    max_steps: int,
    policy: PermissionPolicy,
    approval_callback,
    model_name: str | None = None,
) -> AgentRuntime:
    """复用 tests/agent/test_integration_coding.py:_make_runtime 的配方。

    与生产代码唯一的差别在审批：demo 要让你看到工具真的执行，
    所以默认配一个自动批准的 approval_callback；加 --yolo 则进一步切到
    DANGER_FULL_ACCESS（绕过审批关卡）。这两种都是 demo 旋钮，不改框架。

    model_name（T7 #137）：catalog 条目名；None = 默认链（settings）。
    """
    config = (ModelConfig.from_settings(settings) if model_name is None
              else ModelConfig.from_catalog(settings, model_name))
    model = create_chat_model(config)

    sandbox = LocalSubprocessSandbox(workspace_root=workspace)
    registry = ToolRegistry()
    for tool_cls in (
        ReadTool, WriteTool, BashTool, EditTool, ApplyPatchTool,
        GlobTool, GrepTool, GitStatusTool, GitDiffTool,
    ):
        registry.register(tool_cls(sandbox))

    return AgentRuntime(
        model=model,
        registry=registry,
        executor=ToolExecutor(
            registry,
            policy=policy,
            approval_callback=approval_callback,
        ),
        max_steps=max_steps,
    )


def _runtime_for_session(
    session: Session,
    store_root: Path,
    workspace: Path,
    settings: Settings,
    max_steps: int,
    policy: PermissionPolicy,
    approval_callback,
) -> AgentRuntime:
    """按 session 派生的当前模型重建 runtime（T7 #137）。

    /model、/resume、/fork 之后必须重建，否则 runtime 会一直沿用上一个会话的
    模型。模型条目已不在 catalog 时回落默认链（demo 不因配置漂移炸掉）。
    """
    from agent_harness.model.config import ConfigError
    from agent_harness.session.service import current_model_selection

    events = JsonlSessionStore(root=store_root).read_events(session.session_id)
    _, model_id = current_model_selection(events)
    if model_id is None:
        return _build_runtime(
            workspace, settings, max_steps, policy, approval_callback
        )
    try:
        return _build_runtime(
            workspace, settings, max_steps, policy, approval_callback,
            model_name=model_id,
        )
    except ConfigError:
        console.print(f"[yellow]会话模型 {model_id} 已不在 catalog，回落默认链[/yellow]")
        return _build_runtime(
            workspace, settings, max_steps, policy, approval_callback
        )


def _make_approval_callback(auto: bool):
    """Demo 用审批回调：auto=True 全部批准（默认），auto=False 每次问你 y/n。"""
    if auto:
        def _auto(_req: ApprovalRequest) -> ApprovalResponse:
            return ApprovalResponse(approved=True, reason="demo auto-approve")
        return _auto

    def _ask(req: ApprovalRequest) -> ApprovalResponse:
        console.print(Panel(
            f"[yellow]{req.tool_name}[/yellow] 需要审批\n"
            f"权限级别: {req.permission.value}  策略: {req.policy.value}\n"
            f"原因: {req.reason}",
            title="[bold]approval request[/bold]", border_style="yellow",
        ))
        try:
            ans = Prompt.ask("批准? [Y/n]", default="y")
        except (EOFError, KeyboardInterrupt):
            return ApprovalResponse(approved=False, reason="user aborted")
        ok = ans.strip().lower() in {"y", "yes", ""}
        return ApprovalResponse(approved=ok, reason="user said " + ("yes" if ok else "no"))
    return _ask


def _new_session(store_root: Path) -> Session:
    store = JsonlSessionStore(root=store_root)
    return Session.start(store)


def _short(text: str, limit: int = 600) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…(+{len(text) - limit} chars truncated)"


def _render_event(event_type: str, data: dict[str, Any], seq: int) -> None:
    """把一条 SessionEvent 渲染成一个 rich 面板，让你一眼看清发生了什么。"""
    color = EVENT_STYLE.get(event_type, "white")
    title = f"[{seq:03d}] {event_type}"

    if event_type == USER_MESSAGE:
        body = Text(data.get("content", ""), style="bold")
        console.print(Panel(body, title=title, border_style=color))

    elif event_type == MODEL_COMPLETED:
        content = data.get("content", "")
        tool_calls = data.get("tool_calls") or []
        pieces: list[str] = []
        if content:
            pieces.append(_short(content))
        if tool_calls:
            pieces.append(f"[dim]→ 请求 {len(tool_calls)} 个工具调用:[/dim]")
            for tc in tool_calls:
                name = tc.get("name", "?")
                args = tc.get("args", {})
                # 工具参数渲染成 JSON 片段，更易读
                import json
                arg_str = json.dumps(args, ensure_ascii=False)
                pieces.append(f"  [yellow]▸ {name}[/yellow]  {arg_str}")
        console.print(Panel("\n".join(pieces) if pieces else "(空)", title=title, border_style=color))

    elif event_type == TOOL_CALL:
        name = data.get("tool_name", "?")
        args = data.get("args", {})
        import json
        console.print(Panel(
            f"[yellow]{name}[/yellow]\n{json.dumps(args, ensure_ascii=False, indent=2)}",
            title=title, border_style=color,
        ))

    elif event_type == TOOL_RESULT:
        content = data.get("content", "")
        # ToolResult 的 content 是 JSON 字符串，尝试抽出关键字段
        try:
            import json
            parsed = json.loads(content)
            ok = parsed.get("ok", True)
            err = parsed.get("error_code")
            out = parsed.get("output") or parsed.get("content") or content
            badge = "[green]✓ ok[/green]" if ok else f"[red]✗ {err or 'failed'}[/red]"
            rendered = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=2)
            # bash/code 输出用 syntax 高亮一下，更像"看见代码"
            body = f"{badge}\n{_short(rendered, 800)}"
        except Exception:  # noqa: BLE001
            body = _short(content, 800)
        console.print(Panel(body, title=title, border_style=color))

    elif event_type == RUN_COMPLETED:
        final = data.get("final_text", "")
        console.print(Panel(
            f"status=[bold green]completed[/bold green]\n{_short(final, 1200)}",
            title=title, border_style="blue",
        ))

    elif event_type == RUN_FAILED:
        final = data.get("final_text", "")
        console.print(Panel(
            f"status=[bold red]failed[/bold red]\n{_short(final, 400)}",
            title=title, border_style="red",
        ))

    else:
        console.print(Panel(_short(str(data), 400), title=title, border_style=color))


async def _run_task(
    runtime: AgentRuntime,
    session: Session,
    task: str,
    store_root: Path,
    session_id: str,
) -> None:
    """跑一次完整 Agent Loop；每产生一个事件就实时渲染。"""
    # 关键：在 run() 之前记录当前 seq，跑完后只渲染新事件——这是实时感来源。
    seen = len(session.events)
    console.rule(f"[bold cyan]任务: {task}[/bold cyan]")

    result = await runtime.run(session, task)

    # 渲染本次 run 期间产生的所有事件，按 seq 顺序实时滚动出来
    for ev in session.events[seen:]:
        _render_event(ev.type, ev.data, ev.seq)

    console.rule(
        f"[bold]done[/bold] — status={result.status}, steps={result.steps}, "
        f"session_id={session_id}, events={len(session.events)}"
    )
    # 指出事件事实源文件位置——崩溃重启后能从这里恢复
    jsonl = store_root / f"{session_id}.jsonl"
    console.print(f"[dim]事件事实源: {jsonl}[/dim]\n")


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task", help="单次任务；省略则进入交互模式")
    parser.add_argument(
        "--workspace", default="./_demo_workspace",
        help="agent 工作的 sandbox 根目录（默认 ./_demo_workspace）",
    )
    parser.add_argument(
        "--store", default="./_demo_sessions",
        help="SessionEvent JSONL 存放目录（默认 ./_demo_sessions）",
    )
    parser.add_argument("--max-steps", type=int, default=10, help="Agent Loop 最大轮数")
    parser.add_argument(
        "--yolo", action="store_true",
        help="DANGER_FULL_ACCESS 策略——绕过审批关卡（任何工具直接放行）",
    )
    parser.add_argument(
        "--approve", choices=("auto", "ask"), default="auto",
        help="审批回调：auto=自动批准（默认），ask=每次问你 y/n",
    )
    args = parser.parse_args()

    settings = Settings()
    if not settings.model_api_key or not settings.model_name:
        console.print("[red]缺少 MODEL_API_KEY / MODEL_NAME。[/red]")
        console.print("把 .env.example 复制成 .env 并填好模型配置再来跑。")
        return 1

    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    store_root = Path(args.store).resolve()
    store_root.mkdir(parents=True, exist_ok=True)

    console.print(Panel.fit(
        f"[bold]Live Agent Demo[/bold]\n"
        f"workspace : {workspace}\n"
        f"sessions  : {store_root}\n"
        f"model     : {settings.model_name}\n"
        f"max_steps : {args.max_steps}\n"
        f"policy    : {'DANGER_FULL_ACCESS (--yolo)' if args.yolo else 'WORKSPACE_WRITE'}\n"
        f"approval  : {'n/a (yolo)' if args.yolo else args.approve}\n"
        f"tools     : read / write / bash / edit / apply_patch / glob / grep / git_status / git_diff",
        border_style="cyan",
    ))

    if args.yolo:
        policy = PermissionPolicy.DANGER_FULL_ACCESS
        approval_callback = None  # 全放行，不需要审批
    else:
        policy = PermissionPolicy.WORKSPACE_WRITE
        approval_callback = _make_approval_callback(auto=(args.approve == "auto"))

    runtime = _build_runtime(workspace, settings, args.max_steps, policy, approval_callback)

    if args.task:
        session = _new_session(store_root)
        await _run_task(runtime, session, args.task, store_root, session.session_id)
        return 0

    # 交互模式：REPL 持有 current_session_id，普通 prompt 在同一 session 上续聊
    console.print("[dim]交互模式：输入任务回车续聊；/help 看命令；:q 退出。[/dim]\n")

    from demo.live_agent_repl import format_help, parse_slash_command

    current_session = _new_session(store_root)
    console.print(f"[dim]current session: {current_session.session_id}[/dim]\n")

    while True:
        try:
            user_input = Prompt.ask("[bold green]你 ›[/bold green]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]bye[/dim]")
            return 0
        if user_input.strip().lower() in {":q", ":quit", ":exit"}:
            console.print("[dim]bye[/dim]")
            return 0
        if not user_input.strip():
            continue

        # slash 命令分发
        parsed = parse_slash_command(user_input)
        if parsed is not None:
            if parsed.name == "help":
                console.print(format_help())
            elif parsed.name == "new":
                current_session = _new_session(store_root)
                console.print(f"[green]新建 session: {current_session.session_id}[/green]")
            elif parsed.name == "clear":
                console.clear()
            elif parsed.name == "history":
                store = JsonlSessionStore(root=store_root)
                ids = store.list_session_ids()
                if not ids:
                    console.print("[dim]（暂无会话）[/dim]")
                else:
                    for sid in ids:
                        marker = " ← current" if sid == current_session.session_id else ""
                        console.print(f"  {sid}{marker}")
            elif parsed.name == "resume":
                store = JsonlSessionStore(root=store_root)
                ids = store.list_session_ids()
                if not ids:
                    console.print("[red]无可恢复的 session[/red]")
                elif parsed.args:
                    target_id = parsed.args[0]
                    if target_id in ids:
                        current_session = Session.resume(
                            store, target_id,
                            workspace_registry=None,
                        )
                        # 恢复的会话可能带着自己的模型（T7 #137）——必须重建
                        # runtime，否则会沿用上一个会话的模型。
                        runtime = _runtime_for_session(
                            current_session, store_root, workspace, settings,
                            args.max_steps, policy, approval_callback,
                        )
                        console.print(f"[green]恢复 session: {target_id}[/green]")
                    else:
                        console.print(f"[red]session 不存在: {target_id}[/red]")
                else:
                    console.print("[dim]可用 session:[/dim]")
                    for i, sid in enumerate(ids):
                        console.print(f"  [{i}] {sid}")
                    console.print("[dim]用 /resume <session_id> 恢复[/dim]")
            elif parsed.name == "compact":
                console.print("[yellow]/compact 尚未实现（T4 压缩 bracket 升级后接线）[/yellow]")
            elif parsed.name == "model":
                if len(parsed.args) < 2:
                    console.print("[red]用法: /model <provider> <model>[/red]")
                else:
                    from agent_harness.session.service import (
                        UnknownModel,
                        append_model_change,
                        assert_model_resolvable,
                        resolve_model_target,
                    )

                    provider, model_id = parsed.args[0], parsed.args[1]
                    target = resolve_model_target(settings, provider, model_id)
                    if target is None:
                        console.print(f"[red]未知模型: {provider}/{model_id}[/red]")
                    else:
                        try:
                            # 与 Web 端点同判据：catalog 命中之外还要装得起来
                            # （provider 已知 + 有可用 key），否则不写事件。
                            assert_model_resolvable(settings, target)
                        except UnknownModel as e:
                            console.print(f"[red]模型不可用: {e}[/red]")
                        else:
                            append_model_change(current_session, target)
                            runtime = _runtime_for_session(
                                current_session, store_root, workspace, settings,
                                args.max_steps, policy, approval_callback,
                            )
                            label = (f"{target.provider}/{target.model_id}"
                                     if target.model_id
                                     else f"{target.provider}/(默认链)")
                            console.print(
                                f"[green]模型已切换: {label}（下一轮生效）[/green]"
                            )
            elif parsed.name == "fork":
                from agent_harness.session.fork import (
                    TailSummarizer,
                    find_fork_boundaries,
                    fork_session,
                )
                from agent_harness.session.service import inherit_parent_model
                from agent_harness.storage.sqlite import SqliteSessionMetaStore

                store = JsonlSessionStore(root=store_root)
                events = store.read_events(current_session.session_id)
                boundaries = find_fork_boundaries(events)
                if not boundaries:
                    console.print("[red]当前会话没有可用的 fork 切点（需完整 run 后的用户消息）[/red]")
                    continue
                if parsed.args:
                    try:
                        from_seq = int(parsed.args[0])
                    except ValueError:
                        console.print("[red]from_seq 必须是整数[/red]")
                        continue
                    if from_seq not in boundaries:
                        console.print(f"[red]非法切点 {from_seq}，可用: {boundaries}[/red]")
                        continue
                else:
                    from_seq = boundaries[-1]

                meta_store = SqliteSessionMetaStore(
                    Path(settings.workspace_dir) / "harness.db"
                )
                await meta_store.initialize()
                # tail 摘要默认开（ADR-0017 决策 9）：被放弃的路线压成一段
                # 上下文挂给 child；摘要模型用默认链，失败自动降级。
                summarizer = TailSummarizer(
                    create_chat_model(ModelConfig.from_settings(settings))
                )
                try:
                    child = await fork_session(
                        store, meta_store,
                        current_session.session_id,
                        boundary_user_message_seq=from_seq,
                        workspace_registry=None,
                        summarizer=summarizer,
                        with_tail_summary=True,
                    )
                except Exception as e:  # noqa: BLE001 - demo 友好提示
                    console.print(f"[red]fork 失败: {e}[/red]")
                else:
                    # child 继承父当前模型（与 Web fork 同语义，T7 #137）。
                    inherit_parent_model(child, events)
                    current_session = child
                    runtime = _runtime_for_session(
                        child, store_root, workspace, settings,
                        args.max_steps, policy, approval_callback,
                    )
                    console.print(
                        f"[green]fork 出 child session: {child.session_id}"
                        f"（切点 seq={from_seq}）[/green]"
                    )
            elif parsed.name == "cancel":
                console.print("[yellow]/cancel 尚未实现（T8 崩溃恢复 + Ledger reconcile 后接线）[/yellow]")
            continue

        # 普通 prompt：在 current_session 上续聊
        try:
            await _run_task(runtime, current_session, user_input, store_root, current_session.session_id)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]任务出错:[/red] {e!r}")


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
