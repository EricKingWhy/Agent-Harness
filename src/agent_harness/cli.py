"""Agent CLI（Phase 9 CLI Renderer）：驱动 AgentRuntime.run_stream 渲染事件流。

CLI 与 SSE 是同一 AgentEvent 流的两个消费端（spec 11 §1）：渲染是事件流的
纯函数，只挑人要看的（流式正文 / 工具行 / 终态），完整事实源是 Session
JSONL；Diagnostic Log 由 runtime 的 _log 统一产出（CLI 只负责 setup_logging，
不再手搓 llm_call 链路）。最小 CLI 不装配工具（registry 为空——模型直接答复）。

渲染约定借鉴 pi-mono / oh-my-pi（均为 MIT License，设计级借用 + 小工具重实现）：
- 状态行语法 `glyph 标题 折叠参数 · meta`（oh-my-pi tui/status-line.ts）
- 参数折叠 key=value、结果尾部预览 + `... +N more lines`（pi renderers/bash.ts）
- 时长徽章、token 用量页脚 + K/M 压缩（pi footer.ts formatTokens/formatDuration）
- ascii 符号路线（oh-my-pi theme/symbols.ts 的 ascii preset）——Windows GBK
  控制台对 ✔/⏳ 等 glyph 会抛 UnicodeEncodeError，ascii 永远可打印。
License 署名：pi-mono © 2025 Mario Zechner（MIT）；oh-my-pi © 2025-2026
Can Bölük、© 2026 Stencil Labs, Inc.（MIT）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from agent_harness.agent import AgentEvent
from agent_harness.assembly import (
    assemble_wiring,
    build_runtime,
    initialize_stores,
    recovery_stores,
)
from agent_harness.config import Settings
from agent_harness.identity import IdentityContext
from agent_harness.instance_lock import InstanceLock, InstanceLockError
from agent_harness.logging import LogContext, log_context, setup_logging
from agent_harness.memory.types import memory_session_var
from agent_harness.model.config import ModelConfig
from agent_harness.observability import flush_process_sink
from agent_harness.sandbox import WorkspaceRegistry
from agent_harness.session import (
    AGENT_DELEGATION_FINISHED,
    AGENT_DELEGATION_STARTED,
    ARTIFACT_CREATED,
    ARTIFACT_EXTERNALIZED,
    CONTEXT_COMPACTED,
    MODEL_COMPLETED,
    MODEL_FAILED,
    MODEL_FALLBACK,
    OPERATION_RECONCILE_REQUIRED,
    RUN_COMPLETED,
    RUN_FAILED,
    SESSION_FORKED,
    TEXT_DELTA,
    TOOL_CALL,
    TOOL_FAILURE_GUARD,
    TOOL_RESULT,
    USER_MESSAGE,
    JsonlSessionStore,
    Session,
    SessionEvent,
)
from agent_harness.session.fork import (
    ForkBoundaryError,
    TailSummarizer,
    fork_session,
)
from agent_harness.session.lineage import (
    build_lineage_index,
    build_lineage_tree,
    render_lineage_tree,
)
from agent_harness.storage.sqlite import SqliteSessionMetaStore

_ARGS_LINE_LIMIT = 120
_PREVIEW_LINES = 3


class StreamRenderer:
    """AgentEvent → 终端文本（事件流的纯函数；write 注入便于测试）。

    行式追加输出（无差分重绘）：delta 原样续写；工具块 = 空行 + 状态行 +
    结果预览；终态行补齐换行。model/completed、user/message 等持久化镜像
    一律静默——终端不是第二份事件日志。
    """

    def __init__(self, write: Callable[[str], None]) -> None:
        self._write = write
        self._delta_open = False  # 流式正文输出中：工具行/终态行前先补换行

    def handle(self, event: AgentEvent) -> None:
        if event.type == TEXT_DELTA:
            self._write(event.data["delta"])
            self._delta_open = True
        elif event.type == TOOL_CALL:
            self._end_delta()
            args = _collapse_args(event.data.get("args") or {})
            suffix = f" {args}" if args else ""
            self._write(f"\n[tool] {event.data['tool_name']}{suffix}\n")
        elif event.type == TOOL_RESULT:
            self._render_result(event.data)
        elif event.type == RUN_COMPLETED:
            self._end_delta()
            self._write("\n")
            usage = event.data.get("usage_total") or {}
            if usage:
                self._write(f"tokens: in {_format_tokens(usage.get('prompt_tokens'))}, "
                            f"out {_format_tokens(usage.get('completion_tokens'))}\n")
        elif event.type == RUN_FAILED:
            self._end_delta()
            reason = event.data.get("reason")
            suffix = f" ({reason})" if reason else ""
            self._write(f"\n[run failed]{suffix}\n")

    def _render_result(self, data: dict) -> None:
        try:
            result = json.loads(data["content"])
        except (KeyError, ValueError):
            self._write("  [fail] (unparseable result)\n")
            return
        status = "[ok]" if result.get("ok") else "[fail]"
        duration = result.get("metadata", {}).get("duration_ms")
        suffix = f" ({duration / 1000:.1f}s)" if isinstance(duration, (int, float)) else ""
        self._write(f"  {status}{suffix}\n")
        message = result.get("message") or ""
        lines = message.splitlines()
        for line in lines[:_PREVIEW_LINES]:
            self._write(f"  {line}\n")
        if len(lines) > _PREVIEW_LINES:
            self._write(f"  ... +{len(lines) - _PREVIEW_LINES} more lines\n")

    def _end_delta(self) -> None:
        if self._delta_open:
            self._write("\n")
            self._delta_open = False


def _collapse_args(args: dict) -> str:
    """一行折叠工具参数：key=value，字符串含空格才加引号；整体超限截断。

    折叠约定借鉴 oh-my-pi formatArgsInline（key=value 预算内联）；嵌套结构
    压成紧凑 JSON（本地快失败用不到嵌套语义，终端只要能认出调用形状）。
    """
    parts: list[str] = []
    for key, value in args.items():
        if isinstance(value, str):
            text = f'"{value}"' if (" " in value or not value) else value
        elif isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False)
        else:
            text = str(value)
        parts.append(f"{key}={text}")
    line = " ".join(parts)
    if len(line) > _ARGS_LINE_LIMIT:
        line = line[:_ARGS_LINE_LIMIT] + "..."
    return line


def _format_tokens(count: int | None) -> str:
    """token 数 → 紧凑文本（借鉴 pi footer.ts formatTokens 的 K/M 压缩）。"""
    if not isinstance(count, int) or count < 0:
        return "?"
    if count < 1000:
        return str(count)
    if count < 1_000_000:
        return f"{count / 1000:.1f}k"
    return f"{count / 1_000_000:.1f}M"


async def run(message: str, *, write: Callable[[str], None] | None = None) -> str:
    """跑一次 Agent Loop：流式渲染到 write，返回最终回答文本。

    与 web 共享 assembly.build_runtime 全栈装配（coding 工具 + Ledger/
    Checkpoint + capability 工具）——CLI 不再是削弱装配，耐久性语义一致。
    失败的 run 不抛异常（runtime 契约：失败事实由 run/failed 终结事件 +
    结构化日志承载）——返回空 final_text，main() 据此转 SystemExit(1)。
    成功的 run final_text 恒非空：空响应在 runtime 被拒为失败（R6-2），
    不存在"成功但空回答"的歧义态。
    """
    settings = Settings()
    setup_logging(settings.log_level, settings.workspace_dir)
    # LogContext 提供 trace_id/task_id 关联列——没有它 runtime 的结构化日志
    # 整条链都缺关联键（一次 CLI 运行 = 一个可对账的 trace）。
    with log_context(LogContext.create(service="agent-harness", env="local")):
        workspace_root = Path(settings.workspace_dir)
        _, wiring = await assemble_wiring(settings)
        store = JsonlSessionStore(root=workspace_root / "sessions")
        # WS-2 / ADR-0025：项目索引必须拿到会话 header 来源，故先建 store 再建 stores
        # （首次 bootstrap 就在 initialize_stores 里发生，AC14–16）。
        stores = recovery_stores(workspace_root / "harness.db", workspace_headers=store)
        await initialize_stores(stores)
        workspace_registry = WorkspaceRegistry(root=workspace_root, backend="local")
        # 崩溃扫描**不**在 CLI 里跑：在途 run 只存在于持有它的进程内存中，
        # 短命命令无法区分「别的进程在跑」与「崩溃遗留」，误标会撞 seq
        # （见 recovery/scan.py 单进程假设）。扫描归属长驻会话宿主（web lifespan）。
        session_id = str(uuid4())
        workspace = workspace_root / "workspaces" / session_id
        runtime = await build_runtime(
            settings=settings, wiring=wiring, stores=stores,
            workspace_registry=workspace_registry,
            session_id=session_id, workspace=workspace,
            max_steps=10, auto_approve=True,
            session_store=store,
        )
        session = Session.start(store, session_id=session_id, cwd=workspace)
        # 与 web event_generator 同一契约：SESSION-scope 记忆 / 会话级工具
        # （ingest_document 的 sandbox 解析）需要可信 session id。
        session_token = memory_session_var.set(session.session_id)
        renderer = StreamRenderer(write if write is not None else sys.stdout.write)
        final_text = ""
        try:
            async for event in runtime.run_stream(session, message):
                renderer.handle(event)
                if event.type == RUN_COMPLETED:
                    final_text = event.data.get("final_text", "")
        finally:
            memory_session_var.reset(session_token)
        return final_text


def main() -> None:
    # ARCH-7（#150）：CLI 与 Web 并发使用同一 session root 被**有意拒绝**——
    # 无保护的跨进程多写者会产出重复 seq / 交错写，且 run 归属共识只在进程内
    # 有效。这里不吞异常：响亮失败 + 明确错误信息（锁路径 / 占用者 / 逃生门）。
    # `--help` / `-h` 不触碰该根（argparse 直接打印帮助退出），不该被锁挡住；
    # 但它仍是"退出路径"，flush 契约（ADR-0018 D3）照旧要守。
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        try:
            _main_dispatch()
        finally:
            flush_process_sink()
        return
    settings = Settings()
    # 先配日志再取锁：逃生门降级时那条 WARNING 才落得进 agent.jsonl（AC7）。
    # setup_logging 幂等（子命令内重复调用只清一次 handlers）。
    setup_logging(settings.log_level, settings.workspace_dir)
    try:
        lock = InstanceLock(settings.workspace_dir).acquire()
    except InstanceLockError as error:
        print(error, file=sys.stderr)
        raise SystemExit(2) from error
    try:
        _main_dispatch()
    finally:
        lock.release()
        # 旁路收尾（ADR-0018 D3）：任何退出路径（正常/异常/SystemExit）都尽力
        # 发送剩余 Langfuse span；未配置/未装配时零开销 no-op。
        flush_process_sink()


def _main_dispatch() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] == "ingest":
        _main_ingest(argv[1:])
        return
    if argv and argv[0] == "fork":
        _main_fork(argv[1:])
        return
    if argv and argv[0] == "sessions":
        _main_sessions(argv[1:])
        return
    if argv and argv[0] == "replay":
        _main_replay(argv[1:])
        return
    parser = argparse.ArgumentParser(description="Agent Harness CLI")
    parser.add_argument("message", help="发送给 Agent 的任务")
    args = parser.parse_args(argv)
    final_text = asyncio.run(run(args.message))
    if not final_text:
        raise SystemExit(1)


def _main_ingest(argv: list[str]) -> None:
    """CLI 建库入口（ADR-0013 决策 6）：与 ingest_document 工具同一服务函数。

    人驱动的宿主路径直读（不走 sandbox 边界——CLI 是人不是模型）；向量库
    配置与 capability 共用同一组 env（MILVUS_* / KNOWLEDGE_COLLECTION /
    EMBEDDING_*），未配置时响亮失败。
    """
    parser = argparse.ArgumentParser(prog="agent-harness ingest")
    parser.add_argument("path", help="要摄入的 UTF-8 文本文件路径（宿主本地）")
    parser.add_argument("--name", default=None, help="语料来源名（缺省取文件名）")
    args = parser.parse_args(argv)

    settings = Settings()
    setup_logging(settings.log_level, settings.workspace_dir)
    from agent_harness.knowledge.milvus_store import MilvusKnowledgeVectorStore
    from agent_harness.knowledge.registry import SqliteKnowledgeSourceRegistry
    from agent_harness.knowledge.service import KnowledgeService
    from agent_harness.memory.embeddings import create_embeddings

    async def _entry() -> None:
        store = MilvusKnowledgeVectorStore(
            settings,
            create_embeddings(settings) if settings.embedding_model else None,
        )
        await store.initialize()
        registry = SqliteKnowledgeSourceRegistry(
            Path(settings.workspace_dir) / "harness.db"
        )
        await registry.initialize()
        service = KnowledgeService(store=store, registry=registry)
        content = Path(args.path).read_text(encoding="utf-8")
        result = await service.ingest(
            text=content, source_name=args.name or Path(args.path).name,
            identity=IdentityContext("local", "local", ["user", "session"]),
        )
        print(f"语料 '{result.source_name}' {result.status}："
              f"{result.chunk_count} 个 chunk 已入索引。")

    asyncio.run(_entry())


def _main_fork(argv: list[str]) -> None:
    """CLI fork 入口（Phase 14 T5, ADR-0017 决策 6/10）：人驱动的分叉动作。

    fork 是用户动作而非模型工具——不注册进任何 ToolRegistry。全链 =
    boundary 校验 + seed + provenance + meta（fork 核心）→ copy-on-fork
    → tail summary（默认开：主模型一次调用；--no-summary 关闭）。
    """
    args = _parse_fork_args(argv)
    settings = Settings()
    setup_logging(settings.log_level, settings.workspace_dir)
    try:
        child_id = asyncio.run(
            fork_command(
                args.session_id, from_message=args.from_message,
                no_summary=args.no_summary,
            )
        )
    except ForkBoundaryError as error:
        print(f"fork 失败：{error}", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"已分叉：child session = {child_id}")
    print(f"（原会话 {args.session_id} 未改动；在新分支重发第 "
          f"{args.from_message} 条用户消息即可继续）")


def _parse_fork_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="agent-harness fork")
    parser.add_argument("session_id", help="要分叉的父会话 id")
    parser.add_argument(
        "--from-message", type=int, required=True, metavar="N",
        help="从父会话的第 N 条用户消息处分叉（该消息不进 seed，由你在新分支重发）",
    )
    parser.add_argument(
        "--no-summary", action="store_true",
        help="跳过 tail summary（默认对被放弃路线生成一次 LLM 摘要挂进新会话）",
    )
    return parser.parse_args(argv)


async def fork_command(
    session_id: str,
    *,
    from_message: int,
    no_summary: bool,
    workspace_dir: str | None = None,
    write: Callable[[str], None] | None = None,
) -> str:
    """fork 命令的可测核心：返回 child session id。

    与 run() 同一装配约定（workspace_dir 缺省取 Settings）；--no-summary
    关闭 tail summary，否则用主模型链跑一次摘要（T4 seam）。
    """
    settings = Settings()
    if workspace_dir is not None:
        settings.workspace_dir = workspace_dir
    setup_logging(settings.log_level, settings.workspace_dir)
    workspace_root = Path(settings.workspace_dir)
    store = JsonlSessionStore(root=workspace_root / "sessions")
    meta_store = SqliteSessionMetaStore(workspace_root / "harness.db")
    await meta_store.initialize()
    workspace_registry = WorkspaceRegistry(root=workspace_root, backend="local")
    summarizer = None
    if not no_summary:
        from agent_harness.model.provider import create_chat_model

        summarizer = TailSummarizer(
            create_chat_model(ModelConfig.from_settings(settings))
        )
    child = await fork_session(
        store, meta_store, session_id,
        boundary_user_message_seq=from_message,
        workspace_registry=workspace_registry,
        summarizer=summarizer, with_tail_summary=not no_summary,
    )
    # child 继承父当前模型（T7 #137：fork seed 不含父 session/started）。
    from agent_harness.session.service import inherit_parent_model

    inherit_parent_model(child, store.read_events(session_id))
    if write is not None:
        write(f"child session: {child.session_id}\n")
    return child.session_id


# ── replay（Phase 14 T8, ADR-0017 决策 4：逻辑回放，零副作用契约）────────────


def render_replay_event(event: SessionEvent) -> str | None:
    """SessionEvent → 终端行（纯函数）。生命周期噪音返回 None 不渲染。

    tool result 一律渲染**冻结终态**（spec 03 §6：逻辑回放不重执行、不产生
    外部副作用）。失败事实（run/failed、model/failed、熔断、fallback）如实
    呈现，绝不美化。
    """
    data = event.data
    if event.type == USER_MESSAGE:
        return f"\n[用户] {data.get('content', '')}"
    if event.type == MODEL_COMPLETED:
        content = data.get("content", "")
        return f"[assistant] {content}" if content else None
    if event.type == TOOL_CALL:
        args = data.get("args", {})
        return f"[工具] {data.get('tool_name', '')}({_collapse_args(args)})"
    if event.type == TOOL_RESULT:
        content = str(data.get("content", ""))
        lines = content.splitlines() or [""]
        preview = "\n".join(f"  │ {line}" for line in lines[:_PREVIEW_LINES])
        more = "" if len(lines) <= _PREVIEW_LINES else f"\n  │ ... +{len(lines) - _PREVIEW_LINES} more lines"
        return f"  → 结果（冻结）:\n{preview}{more}"
    if event.type == RUN_FAILED:
        return f"[run 失败] {data.get('reason', 'unspecified')}"
    if event.type == MODEL_FAILED:
        return f"[模型失败] {data.get('message', '')}"
    if event.type == TOOL_FAILURE_GUARD:
        return (f"[熔断] level={data.get('level', '')}"
                f" consecutive_failures={data.get('consecutive_failures', '')}")
    if event.type == MODEL_FALLBACK:
        return (f"[fallback] {data.get('from_model', '')}→"
                f"{data.get('to_model', '')} ({data.get('reason', '')})")
    if event.type == AGENT_DELEGATION_STARTED:
        return (f"[委派→{data.get('target', '')}] "
                f"child={data.get('child_session_id', '')}")
    if event.type == AGENT_DELEGATION_FINISHED:
        summary = str(data.get("summary", ""))[:200]
        return (f"[委派完成→{data.get('target', '')}] "
                f"{data.get('status', '')}: {summary}")
    if event.type == ARTIFACT_CREATED:
        return f"[artifact] {str(data)[:120]}"
    if event.type == ARTIFACT_EXTERNALIZED:
        return f"[外置产物] artifact_id={data.get('artifact_id', '')} size={data.get('size', 0)}"
    if event.type == SESSION_FORKED:
        return (f"[fork] 来自 {data.get('parent_session_id', '')}"
                f" @{data.get('fork_point_seq')}")
    if event.type == CONTEXT_COMPACTED:
        return "[context 压缩]（早期历史已摘要，原文在 JSONL）"
    if event.type == OPERATION_RECONCILE_REQUIRED:
        return f"[需裁决] {str(data)[:120]}"
    # session/started, session/resumed, run/started, run/completed,
    # memory/degraded：生命周期噪音，不渲染
    return None


async def replay_command(
    session_id: str,
    *,
    workspace_dir: str | None = None,
    write: Callable[[str], None] | None = None,
) -> str:
    """replay 命令的可测核心：返回渲染文本。

    零副作用契约（测试钉死）：只经 store.read_events 只读加载——不走
    Session.resume（那会追加 session/resumed）、不构造 runtime（无模型
    访问）、不触碰 workspace。
    """
    settings = Settings()
    if workspace_dir is not None:
        settings.workspace_dir = workspace_dir
    setup_logging(settings.log_level, settings.workspace_dir)
    store = JsonlSessionStore(root=Path(settings.workspace_dir) / "sessions")
    events = store.read_events(session_id)
    if not events:
        raise ValueError(f"Session '{session_id}' 不存在或事件日志为空")
    lines = [line for line in (render_replay_event(e) for e in events) if line]
    output = "\n".join(lines) if lines else "（无可渲染内容）"
    if write is not None:
        write(output + "\n")
    return output


def _main_replay(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="agent-harness replay")
    parser.add_argument("session_id", help="要回放的历史会话 id")
    args = parser.parse_args(argv)
    settings = Settings()
    setup_logging(settings.log_level, settings.workspace_dir)
    try:
        output = asyncio.run(replay_command(args.session_id))
    except ValueError as error:
        print(f"replay 失败：{error}", file=sys.stderr)
        raise SystemExit(1) from None
    print(output)


def _main_sessions(argv: list[str]) -> None:
    """CLI sessions 入口（Phase 14 T6）：会话列表 / lineage 树视图。"""
    parser = argparse.ArgumentParser(prog="agent-harness sessions")
    parser.add_argument(
        "--tree", action="store_true",
        help="按 lineage 树渲染（fork + delegation 两类边）",
    )
    args = parser.parse_args(argv)
    settings = Settings()
    setup_logging(settings.log_level, settings.workspace_dir)
    output = asyncio.run(sessions_command(tree=args.tree))
    print(output)


async def sessions_command(
    *, tree: bool = False, workspace_dir: str | None = None
) -> str:
    """sessions 命令的可测核心：返回渲染文本（flat 列表或 lineage 树）。"""
    settings = Settings()
    if workspace_dir is not None:
        settings.workspace_dir = workspace_dir
    setup_logging(settings.log_level, settings.workspace_dir)
    workspace_root = Path(settings.workspace_dir)
    store = JsonlSessionStore(root=workspace_root / "sessions")
    meta_store = SqliteSessionMetaStore(workspace_root / "harness.db")
    await meta_store.initialize()
    if not tree:
        metas = await meta_store.list_all()
        if not metas:
            return "（暂无会话）"
        lines = []
        for meta in metas:
            origin = f" [{meta.origin}]" if meta.origin else ""
            lines.append(f"{meta.session_id}{origin}")
        return "\n".join(lines)
    metas = await build_lineage_index(store, meta_store)
    roots = build_lineage_tree(metas)
    if not roots:
        return "（暂无会话）"
    return render_lineage_tree(roots)


if __name__ == "__main__":
    main()
