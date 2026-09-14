"""后台 Memory 抽取：LLM（含非严格 JSON 修复）→ 确定性规则 → 空；取消不吞掉。

**降级必须可见**：每次回退都通过 ``ExtractionOutcome.degraded_reason`` 上报原因
（只带异常类型名，不带原始消息——模型输出可能夹带密钥），由调用方落
``memory/degraded`` 事件。此前回退完全静默，于是中文模型把 JSON 分隔符写成全角
引号（``“scope”``）导致严格校验 100% 失败、抽取无声退回正则（真机连测 5/5，
BUG-012）——记忆质量掉到"关键词 + 终答"水平而无人知道。

三层：LLM → （修复后重校验）→ 纯规则 → 空。修复只做**字符级**规范化
（围栏 / 全角引号 / 尾随逗号），且**修复结果必须重校验通过才采用**——修不好就
老老实实回退，绝不把改坏的文本当候选存下去。
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, TypeAdapter

from agent_harness.memory.types import MemoryScope
from agent_harness.prompt import DEFAULT_REGISTRY
from agent_harness.session import USER_MESSAGE, SessionEvent

logger = logging.getLogger("agent_harness.memory")

_MAX_EXTRACT_EVENT_CHARS = 1000
_MAX_EXTRACT_EVENTS = 50

#: markdown 代码围栏（模型爱把 JSON 包起来），首尾各剥一次。
_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", flags=re.IGNORECASE)
#: 引号族：ASCII 双引号 + 全角/弯引号。全角引号是中文模型写 JSON 分隔符的常态。
_QUOTE_CHARS = frozenset({'"', "\u201c", "\u201d", "\u201e", "\u201f"})


class _Candidate(BaseModel):
    scope: Literal["user", "session"]
    # max_length 与启发式路径的 [:2000] 截断一致：抽取内容是模型自由生成的，
    # 无上限时一段注入的会话内容可被"抽取"成超大候选，逐字持久化进记忆库并在
    # 未来每个 session 的 SystemMessage 里回灌（USER scope 跨会话存活）。
    content: str = Field(min_length=1, max_length=2000)
    importance: float = Field(ge=0, le=1)


@dataclass(frozen=True)
class ExtractionOutcome:
    """一次抽取的结果 + 降级原因（``None`` = LLM 路径成功）。

    ``degraded_reason`` 形如 ``heuristic_fallback: ValidationError``：只有阶段 +
    异常**类型名**。原始异常消息会带上模型原始输出（可能夹带密钥/隐私），不得进入
    事件流——与 writeback 的脱敏不变量一致。
    """

    candidates: list[tuple[MemoryScope, str, dict]] = field(default_factory=list)
    degraded_reason: str | None = None


def _repair_json(text: str) -> str:
    """字符级修复常见的 LLM 非严格 JSON（不保证可解析，调用方必须重校验）。

    **字符串感知**是这里的关键：内容里本来就可能出现 `,]` 或全角引号
    （`"content":"他说“你好”"`）。无差别全局替换会**静默篡改内容**——那正是本修复
    要消灭的失败模式：`"content":"use [1, 2, ] then stop"` 的 `,]` 会被当成尾逗号删掉，
    重校验照样通过，于是改坏的数据被当成功候选存下去（code-review 实测复现）。
    所以：围栏只在首尾剥；引号只在**字符串外**（当分隔符用）转 ASCII；尾逗号只在
    **字符串外**删；字符串内的字符一律逐字保留（含全角引号、逗号、撇号）。

    字符串内出现全角引号时会提前闭合、大概率产出非法 JSON → 回退。
    "修不好就降级"是本函数的契约：宁可回退，不可静默篡改。
    """
    stripped = _JSON_FENCE_RE.sub("", text.strip())
    out: list[str] = []
    in_string = False
    index = 0
    length = len(stripped)
    while index < length:
        ch = stripped[index]
        if in_string:
            if ch == "\\" and index + 1 < length:  # 转义对整体保留
                out.append(ch)
                out.append(stripped[index + 1])
                index += 2
                continue
            if ch in _QUOTE_CHARS:  # 引号族任意一个都视为字符串结束（全角即分隔符）
                out.append('"')
                in_string = False
                index += 1
                continue
            out.append(ch)  # 字符串内容逐字保留
            index += 1
            continue
        if ch in _QUOTE_CHARS:
            out.append('"')
            in_string = True
            index += 1
            continue
        if ch == ",":
            look = index + 1
            while look < length and stripped[look] in " \t\r\n":
                look += 1
            if look < length and stripped[look] in "]}":  # 字符串外的尾随逗号
                index += 1
                continue
        out.append(ch)
        index += 1
    return "".join(out)


def _diagnostic_detail(error: Exception) -> str:
    """异常类型 + （pydantic）schema 层错误码，**绝不含入参或原始消息**。

    规格 12 §2 要求降级原因可诊断，但校验异常的 ``str()`` 里嵌着模型原始输出
    （= 会话内容），不得进事件流/日志（与 reason 脱敏同一不变量）。取
    ``ValidationError.errors()`` 的 ``type`` 字段（如 ``json_invalid`` /
    ``literal_error``）既够定位，又不带一个字符的数据。
    """
    codes = getattr(error, "errors", None)
    if callable(codes):
        try:
            kinds = sorted({str(item.get("type")) for item in codes() if isinstance(item, dict)})
        except Exception:  # noqa: BLE001 — 诊断辅助，取不到就退回类型名
            kinds = []
        if kinds:
            return f"{type(error).__name__}({','.join(kinds)})"
    return type(error).__name__


def _is_runtime_injected(event: SessionEvent) -> bool:
    """事件是否由 runtime 注入（非真实用户/模型产出）。

    标记是 ``data["injected_by"]``：**非空字符串**即视为注入（当前唯一产出点：
    ``agent/runtime.py`` 的同错熔断纠偏，值 ``"tool_failure_guard"``）。
    写成"非空字符串"而不是"等于某常量"，是为了让未来新增的注入点自动获得同一
    保护；``injected_by=""`` 不算标记（键存在 ≠ 是注入）。判定只看我们自己写入的
    结构化字段，不看内容——"内容像不像注入"是不可靠的启发式。
    """
    data = event.data if isinstance(event.data, dict) else {}
    marker = data.get("injected_by")
    return isinstance(marker, str) and bool(marker.strip())


#: 瞬时错误退避重试（BUG-014）：LLM 路径失败后先重试一次再降级。上游 500 大多
#: 瞬时（真机会话 13 次 memory/degraded 显示每轮抽取都因上游 500 零重试直接掉级）。
_RETRY_BACKOFF_SECONDS = 2.0

#: 不可重试的异常类型：认证/参数类 4xx 错误重试无意义（密钥错、请求构造错），
#: 直接降级。判定不了的类型按瞬时处理（宁可多试一次，不多掉一级）。
#: ValidationError 是**解析**错误：同一响应重试结果必然相同，白试一次。
_NON_RETRYABLE_TYPES: tuple[type[BaseException], ...] = (ValueError,)


def _is_retryable(error: BaseException) -> bool:
    """异常是否值得重试：4xx 语义（认证/权限/请求非法）不重试，其余重试。

    上游 SDK 异常形状各异（openai 的 ``status_code``、HTTPStatusError 的
    ``response.status``），用"有无 4xx 状态"判定而不是白名单类型——白名单会
    在换 provider 后静默失效。判定不了（无状态信息）按瞬时处理。
    """
    seen: set[int] = set()
    cause: BaseException | None = error
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, _NON_RETRYABLE_TYPES):
            return False
        status = getattr(cause, "status_code", None) or getattr(cause, "code", None)
        if isinstance(status, int) and 400 <= status < 500:
            return False
        response = getattr(cause, "response", None)
        resp_status = getattr(response, "status_code", None) or getattr(response, "status", None)
        if isinstance(resp_status, int) and 400 <= resp_status < 500:
            return False
        cause = cause.__cause__ if cause.__cause__ is not cause else None
    return True


class MemoryExtractor:
    def __init__(self, model: Any, timeout_seconds: float = 15.0) -> None:
        self._model = model
        self._timeout = timeout_seconds

    async def extract(self, events: list[SessionEvent]) -> ExtractionOutcome:
        # 运行时注入的消息（`data["injected_by"]` 非空）**不是真实用户发言**，
        # 整个剔出——单点过滤同时修三件事：
        #   1) `has_user_message` 不再被注入消息点亮 → USER 候选的降级保护恢复。
        #      否则工具输出里的一句注入指令，只要窗口里存在任何带 `injected_by`
        #      的用户消息（如同错熔断的纠偏消息），LLM 就能把它洗成 USER 作用域
        #      （跨会话存活）的记忆，并在此后每个 session 的 SystemMessage 里回灌。
        #   2) LLM 抽取的 transcript 不再出现运行时样板文本（`_clip_events` 的输入）。
        #   3) 纯规则路径不再可能把样板文案当"用户偏好"抽出。
        # 用**我们自己的结构化标记**判定，不做"内容像不像注入"的启发式猜测。
        events = [e for e in events if not _is_runtime_injected(e)]
        if not events:
            return ExtractionOutcome()
        # BUG-014：瞬时错误退避重试 1 次——4xx 语义（认证/参数）不重试直接降级。
        # 重试计入既有 asyncio.timeout 预算内，不新增外层预算。
        retry_marker = ""
        for attempt in (0, 1):
            try:
                return await self._extract_llm(events)
            except Exception as error:  # noqa: BLE001 — 结构/模型失败可重试/降级。
                if attempt == 0 and _is_retryable(error):
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
                    retry_marker = "after_1_retry"
                    continue
                return self._degrade(events, error, retry_marker)
        raise AssertionError("unreachable")  # pragma: no cover

    async def _extract_llm(self, events: list[SessionEvent]) -> ExtractionOutcome:
        async with asyncio.timeout(self._timeout):
            response = await self._model.ainvoke([
                SystemMessage(
                    content=DEFAULT_REGISTRY.assemble(
                        "aux:memory_extraction"
                    ).system_text
                ),
                HumanMessage(content=json.dumps(self._clip_events(events), ensure_ascii=False)),
            ])
        if getattr(response, "tool_calls", None):
            raise ValueError("Memory extraction cannot call tools")
        candidates = self._parse_candidates(response.content)
        # provenance 约束（C4）：窗口内没有任何 user/message 时，LLM 声明的
        # USER 候选降级为 SESSION——纯工具输出窗口里的注入指令不能被洗成
        # 跨会话（USER）记忆。降级带显式 provenance 标记，可观察、可追溯。
        has_user_message = any(e.type == USER_MESSAGE for e in events)
        results: list[tuple[MemoryScope, str, dict]] = []
        for c in candidates:
            metadata = {"importance": c.importance}
            scope = MemoryScope(c.scope)
            if scope is MemoryScope.USER and not has_user_message:
                scope = MemoryScope.SESSION
                metadata["provenance"] = "demoted_no_user_message"
            results.append((scope, c.content, metadata))
        return ExtractionOutcome(results)

    def _degrade(
        self, events: list[SessionEvent], error: Exception, retry_marker: str,
    ) -> ExtractionOutcome:
        detail = _diagnostic_detail(error)
        if retry_marker:
            detail = f"{detail}({retry_marker})"
        # debug 级：调用方（writeback）会用 warning + memory/degraded 事件上报，
        # 这里再 warning 一次只会让同一次回退在日志里出现两遍。
        logger.debug("Memory extraction degraded to heuristic: %s", detail)
        try:
            return ExtractionOutcome(
                self._heuristic_extract(events), f"heuristic_fallback: {detail}"
            )
        except Exception as heuristic_error:  # 规则路径也失败 → 空结果（不伪造候选）
            # 归因必须指向**规则路径自己**的异常：带上 LLM 阶段的类型名会
            # 把"正则抽不出来"说成"模型输出有问题"，正好毁掉本次修复的可信度。
            logger.exception("Memory heuristic extraction failed")
            return ExtractionOutcome(
                [], f"heuristic_unavailable: {type(heuristic_error).__name__}"
            )

    @staticmethod
    def _parse_candidates(content: Any) -> list[_Candidate]:
        """严格解析；失败则修复后**重校验**，只有重校验通过才采用修复结果。"""
        payload = content if isinstance(content, str) else str(content)
        adapter = TypeAdapter(list[_Candidate])
        try:
            return adapter.validate_json(payload)
        except ValueError as strict_error:
            repaired = _repair_json(payload)
            if repaired == payload:
                raise
            try:
                candidates = adapter.validate_json(repaired)
            except ValueError:
                raise strict_error from None
            logger.info("Memory extraction payload needed JSON repair (model returned non-strict JSON)")
            return candidates

    @staticmethod
    def _clip_events(events: list[SessionEvent]) -> list[dict]:
        """抽取 prompt 输入有界化（R3-4）：单事件 content 截 1000 字符、最多
        50 个事件——超大工具输出不能整段塞进单条 LLM prompt（上下文爆炸 +
        注入面放大），截断带显式标记。"""
        clipped: list[dict] = []
        for event in events[:_MAX_EXTRACT_EVENTS]:
            data = event.data if isinstance(event.data, dict) else {}
            content = data.get("content")
            if isinstance(content, str) and len(content) > _MAX_EXTRACT_EVENT_CHARS:
                data = {**data, "content": content[:_MAX_EXTRACT_EVENT_CHARS] + "…[truncated]"}
            clipped.append({"type": event.type, "data": data})
        return clipped

    @staticmethod
    def _heuristic_extract(events: list[SessionEvent]) -> list[tuple[MemoryScope, str, dict]]:
        candidates = []
        for event in events:
            if event.type == "user/message":
                content = event.data.get("content", "")
                if isinstance(content, str) and any(word in content.casefold() for word in
                                                    ("我喜欢", "我偏好", "i prefer", "i like")):
                    candidates.append((MemoryScope.USER, content[:2000], {"importance": 0.7}))
            elif event.type == "run/completed":
                content = event.data.get("final_text", "")
                if isinstance(content, str) and content.strip():
                    candidates.append((MemoryScope.SESSION, content[:2000], {"importance": 0.5}))
            elif event.type == "tool/result":
                try:
                    result = json.loads(event.data.get("content", ""))
                except (ValueError, TypeError):
                    continue
                if isinstance(result, dict) and result.get("ok") is False:
                    candidates.append((MemoryScope.SESSION, str(result.get("message", "Tool failed"))[:2000],
                                       {"importance": 0.6}))
        return candidates
