"""本地 JSONL 结构化日志。

Console 给人快速看，JSONL 用来还原一次 Agent 运行的完整执行链路。
业务代码应使用 :func:`log_event` 写稳定事件；普通/第三方日志统一归为
``system_log``，不会再把任意消息误当作 ``event_type``。
"""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4

SCHEMA_VERSION = "1.0"
SHANGHAI_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")

EVENT_TYPES = frozenset(
    {
        "session_start",
        "task_start",
        "agent_start",
        "agent_decision",
        "llm_call",
        "tool_operation",
        "checkpoint_saved",
        "retry",
        "error",
        "task_completed",
        "task_failed",
        # 记忆内容变更的审计（#159）：记忆是 Capability，变更痕迹只落结构化日志，
        # 不进 SessionEvent（ADR-0026 / 不变量 #16、#22）。
        "memory_forget",
        # 冲突消解的额外开销观测（#158）：检索了几次/取回几条/截断几条/决策花了多久。
        # 同样是诊断词汇而非会话事件（记忆不是会话真相）。
        "memory_consolidated",
        # 会话硬删的审计（#172 / ADR-0029）：会话被真正销毁后领域数据里**不留墓碑**
        # （与 ADR-0026 同款选择），"它曾经存在过"只在结构化日志里可查。只带 id 与
        # 计数，不带任何会话内容。删除**不进 SessionEvent**——那时已没有会话可挂。
        "session_delete",
        # 会话归档 / 取消归档的审计（#171）：归档只改列表可见性（`session_meta.archived`
        # 一列），事件日志一字不改，所以它**不是会话真相**，痕迹只落结构化日志
        # （不变量 #16/#22）。同样只带 id 与动作（archived / entry_point）——会话正文
        # 是用户数据，进日志只是多余的泄露面（`memory/audit.py` 同款）。
        "session_archive",
        "system_log",
    }
)

# 这些字段是打开 JSONL 后最值得先看的执行主线。后缀只用于展示层；
# 业务代码仍使用普通字段名，避免后缀污染 Python 调用接口。
_DISPLAY_KEYS = {
    # —— 主线字段（按出现顺序） ——
    "timestamp": "timestamp(时间戳)",
    "level": "level(级别)",
    "event_type": "event_type(事件类型)",
    "message": "message(消息)",
    "step": "step(步骤)",
    "outcome": "outcome(结果)",
    # —— 链路追踪 ——
    "node_name": "node_name(节点)",
    "span_id": "span_id(跨度ID)",
    "parent_span_id": "parent_span_id(父跨度ID)",
    "trace_id": "trace_id(追踪ID)",
    "session_id": "session_id(会话ID)",
    "task_id": "task_id(任务ID)",
    "run_id": "run_id(运行ID)",
    # —— 模型调用 ——
    "provider": "provider(模型提供商)",
    "model_id": "model_id(模型名)",
    "stream": "stream(流式)",
    "llm_input": "llm_input(模型输入)",
    "llm_output": "llm_output(模型输出)",
    "token_usage": "token_usage(Token用量)",
    "finish_reason": "finish_reason(结束原因)",
    "provider_request_id": "provider_request_id(提供商请求ID)",
    "attempt": "attempt(尝试次数)",
    "max_attempts": "max_attempts(最大尝试)",
    "duration_ms": "duration_ms(耗时毫秒)",
    # —— Agent 决策 ——
    "decision": "decision(决策)",
    "requested_tools": "requested_tools(请求工具)",
    "execution_mode": "execution_mode(执行模式)",
    "remaining_steps": "remaining_steps(剩余步骤)",
    "reason": "reason(原因)",
    # —— 错误 ——
    "error_type": "error_type(错误类型)",
    "error_message": "error_message(错误消息)",
    "error_code": "error_code(错误码)",
    "retryable": "retryable(可重试)",
    "stack_trace": "stack_trace(调用栈)",
    # —— 上下文 ——
    "service": "service(服务名)",
    "env": "env(环境)",
    "agent_name": "agent_name(Agent名)",
    "user_id": "user_id(用户ID)",
    # —— 系统字段 ——
    "schema_version": "schema_version(协议版本)",
}

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}
_STRUCTURED_INTERNAL = {"event_type", "schema_version"}
_runtime_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "jsonl_runtime_context", default=None
)


def new_span_id() -> str:
    """生成适合作为本地 trace span 的 16 位十六进制 ID。"""

    return secrets.token_hex(8)


@dataclass(frozen=True, slots=True)
class LogContext:
    """一次任务共享的关联字段。没有值的字段不会在日志中出现。"""

    service: str
    env: str
    session_id: str
    task_id: str
    run_id: str
    trace_id: str
    agent_name: str
    user_id: str | None = None

    @classmethod
    def create(
        cls,
        *,
        service: str = "agent-harness",
        env: str = "local",
        agent_name: str = "agent_harness",
        user_id: str | None = None,
    ) -> LogContext:
        """为一次 CLI 任务创建关联 ID；已有 ID 时应直接构造并复用。"""

        return cls(
            service=service,
            env=env,
            session_id=str(uuid4()),
            task_id=str(uuid4()),
            run_id=str(uuid4()),
            trace_id=uuid4().hex,
            agent_name=agent_name,
            user_id=user_id,
        )

    def fields(self) -> dict[str, Any]:
        return _drop_none(asdict(self))


@contextmanager
def log_context(context: LogContext | Mapping[str, Any]) -> Iterator[None]:
    """让同一异步任务内的业务日志和第三方日志自动携带关联字段。"""

    fields = context.fields() if isinstance(context, LogContext) else dict(context)
    token = _runtime_context.set(_drop_none(fields))
    try:
        yield
    finally:
        _runtime_context.reset(token)


def log_event(
    logger: logging.Logger,
    event_type: str,
    message: str,
    *,
    level: str = "info",
    exc_info: bool = False,
    **fields: Any,
) -> None:
    """写一条稳定枚举的结构化事件。

    ``fields`` 中值为 ``None`` 的项（包括嵌套字典中的项）会自动省略。
    Tool、Checkpoint、Retry 等未来模块可以直接复用此入口，无需另建日志体系。
    """

    if event_type not in EVENT_TYPES:
        raise ValueError(f"不支持的 event_type: {event_type!r}")
    normalized_level = level.lower()
    level_number = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warn": logging.WARNING,
        "error": logging.ERROR,
    }.get(normalized_level)
    if level_number is None:
        raise ValueError(f"不支持的日志 level: {level!r}")

    extra = _drop_none(fields)
    extra["event_type"] = event_type
    extra["schema_version"] = SCHEMA_VERSION
    logger.log(level_number, message, extra=extra, exc_info=exc_info)


def _drop_none(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _drop_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, (list, tuple)):
        return [_drop_none(item) for item in value if item is not None]
    return value


class JsonlFormatter(logging.Formatter):
    """把每条日志格式化成严格的一行 UTF-8 JSON。"""

    # 已告警过的非法 event_type：formatter 在热路径上，每类型只告警一次。
    _warned_unknown_types: ClassVar[set[str]] = set()

    def format(self, record: logging.LogRecord) -> str:
        event_type = getattr(record, "event_type", "system_log")
        if event_type not in EVENT_TYPES:
            # 旁路写入的拼错 event_type：归一成 system_log，但必须留告警痕迹
            # ——静默改写会让诊断协议被无声旁路（R4-6）。
            if event_type != "system_log" and event_type not in self._warned_unknown_types:
                self._warned_unknown_types.add(event_type)
                logging.getLogger("agent_harness.logging").warning(
                    "未知 event_type %r（未注册白名单），已归一为 system_log；"
                    "请检查是否绕过 log_event 直接写 extra",
                    event_type,
                )
            event_type = "system_log"

        entry: dict[str, Any] = {
            "timestamp": datetime.now(SHANGHAI_TIMEZONE).isoformat(
                timespec="milliseconds"
            ),
            "level": _normalize_level(record.levelno),
            "event_type": event_type,
            "message": record.getMessage(),
            "schema_version": getattr(record, "schema_version", SCHEMA_VERSION),
        }
        # Context 在 extra 字段前合并，使某个事件可显式覆盖 node/span 等局部字段。
        entry.update(_runtime_context.get() or {})
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in _STRUCTURED_INTERNAL:
                entry[key] = value
        if record.exc_info:
            entry["stack_trace"] = self.formatException(record.exc_info)

        cleaned = _drop_none(entry)
        displayed = {_DISPLAY_KEYS.get(key, key): value for key, value in cleaned.items()}
        # json.dumps 默认不会写真实换行，stack trace 中的换行会被转义为 \n。
        return json.dumps(displayed, ensure_ascii=False, default=str, separators=(",", ":"))


def _normalize_level(level_number: int) -> str:
    if level_number >= logging.ERROR:
        return "error"
    if level_number >= logging.WARNING:
        return "warn"
    if level_number >= logging.INFO:
        return "info"
    return "debug"


class ShanghaiConsoleFormatter(logging.Formatter):
    """Console 也显示与 JSONL 一致的上海时间。"""

    def formatTime(
        self, record: logging.LogRecord, datefmt: str | None = None
    ) -> str:
        current = datetime.fromtimestamp(record.created, SHANGHAI_TIMEZONE)
        return current.strftime(datefmt) if datefmt else current.isoformat(timespec="seconds")


def setup_logging(
    level: str = "INFO", workspace_dir: str = ".agent/workspace"
) -> Path:
    """配置 root logger，并返回 append-only JSONL 文件路径。"""

    log_dir = Path(workspace_dir).parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "agent.jsonl"

    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in root.handlers:
        handler.close()
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(
        ShanghaiConsoleFormatter("%(asctime)s %(levelname)s %(message)s")
    )
    root.addHandler(console)

    jsonl = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    jsonl.setFormatter(JsonlFormatter())
    root.addHandler(jsonl)
    return log_path
