"""ModelProvider：唯一的职责是把 ModelConfig 变成可用的 ChatModel。

不写 HTTP Client、不做重试/缓存——这些都由 langchain-openai 和底层 openai SDK 负责。
"""

import logging
from typing import Any

from langchain_openai import ChatOpenAI

from agent_harness.logging import log_event
from agent_harness.model.config import ModelConfig

logger = logging.getLogger("agent_harness.model")

#: provider 线格式的合法 reasoning_effort 枚举（OpenAI 兼容推理接口字段定义）。
#: 只认这几个字面量——其他值一律 400 invalid_parameter_error（实测）。
WIRE_REASONING_EFFORTS: frozenset[str] = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)

#: harness 语义档位 → 线格式枚举的翻译表（键集 = Web 层
#: REASONING_EFFORT_DESCRIPTIONS，由 tests/model/test_reasoning_effort.py 的
#: G5 漂移守护锁住）。
#:
#: 为什么需要翻译：`minimal | standard | deep` 是**产品词汇**（前端显示
#: 轻量 / 标准 / 深度），不是任何 API 认的字面量。曾经原样透传的后果是
#: 真实会话选「标准 / 深度」后每一次 run 都必然 400 → 零输出（生产日志
#: 2026-09-08 ~ 09-11 反复出现）。这里把两者分开，翻译只做一次、只在此处。
#:
#: 这是 provider 无关的**线格式适配**，不是「按 provider 分别映射参数名」——
#: 所有 OpenAI 兼容推理端点共用同一套枚举。
#:
#: `deep` 落在 `high` 而非 `xhigh`/`max`：枚举里更高的两档只有部分端点支持，
#: `high` 是「深度推理」里兼容面最广的一档。产品文案已随之对齐——catalog 里
#: 该档的描述是「较高推理开销，较慢但更深入」，不再宣称「最多 / 最深入」，
#: 避免 UI 承诺超出实际发出的档位（想改成字面最深入：这一行 + catalog 描述
#: 一起改，并确认目标端点接受 `xhigh`）。
REASONING_EFFORT_WIRE: dict[str, str] = {
    "minimal": "minimal",
    "standard": "medium",
    "deep": "high",
}


class ReasoningChatOpenAI(ChatOpenAI):
    """接出第三方网关思考内容的 ChatOpenAI 子类（D-B① / ADR-0016 §3.4）。

    基类只认 OpenAI 官方字段：DeepSeek/Qwen 系网关在流式 delta 里的
    reasoning_content 会被 _convert_delta_to_message_chunk 静默丢弃
    （基类 docstring 明示「Use a provider-specific subclass」）。本类在
    chunk 转换层把 delta.reasoning_content 抬进 additional_kwargs——
    Runtime 逐 chunk 读取；聚合时 langchain 对同名字符串拼接，聚合消息
    自带完整思考文本但 Runtime 不消费（思考不回灌上下文，D7 隐私边界）。
    """

    def _convert_chunk_to_generation_chunk(
        self, chunk: dict, default_chunk_class: type, base_generation_info: dict | None,
    ):
        reasoning: str | None = None
        if isinstance(chunk, dict):
            choices = chunk.get("choices") or []
            if choices and isinstance(choices[0], dict):
                delta = choices[0].get("delta")
                if isinstance(delta, dict):
                    raw = delta.get("reasoning_content")
                    if isinstance(raw, str) and raw:
                        reasoning = raw
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info,
        )
        if reasoning is not None and generation_chunk is not None:
            message = generation_chunk.message
            if hasattr(message, "additional_kwargs"):
                message.additional_kwargs = {
                    **message.additional_kwargs, "reasoning_content": reasoning,
                }
        return generation_chunk


def create_chat_model(
    config: ModelConfig, *, reasoning_effort: str | None = None,
) -> ReasoningChatOpenAI:
    """根据配置创建 OpenAI 兼容的 ChatModel（DeepSeek/Qwen/OpenAI 通吃）。

    显式声明 request_timeout / max_retries，不吃 SDK 默认（600s × (1+2) 次尝试
    最坏拖 ~30 分钟，且静默重试与 Harness 的 attempt 记账矛盾）：
    - max_retries=0：重试语义由 Harness 单一责任域拥有（不变量 #8/#9），
      与 memory/embeddings.py 同一原则。
    - request_timeout=300：chat 生成 legitimately 比 embedding 慢（长输出可到
      分钟级），300s 覆盖正常长生成、又把挂死调用的最坏代价从 30min 压到 5min。

    reasoning_effort（RUNTIME 子批次）：会话级思考深度控制。传入的是 harness
    语义档位（`REASONING_EFFORT_WIRE` 的 key），此处翻译成 provider 线格式枚举
    后作为构造器参数注入——ChatOpenAI 原生声明该字段，会把它放进请求体。
    不在每次 astream/ainvoke 调用时传递——构造期注入即可。

    翻译表查不到的值、或查到的字面量不在线格式合法枚举内，都**不注入**
    （只记一条 warn）：宁可不传，也不发一个必然 400 的字面量——一次非法参数
    会让整个 run 在第一次模型调用就失败。第二道判定是给翻译表本身的防呆：
    把 `minimal` 误改成 `min` 这类编辑错误不应变成线上 400。
    """
    kwargs: dict[str, Any] = {
        "model": config.model_name,
        "api_key": config.get_secret_value(),
        "base_url": config.base_url,
        "temperature": config.temperature,
        "request_timeout": 300,
        "max_retries": 0,
    }
    if reasoning_effort is not None:
        wire = REASONING_EFFORT_WIRE.get(reasoning_effort)
        if wire is None or wire not in WIRE_REASONING_EFFORTS:
            # 结构化（而非裸 logger.warning）：这一档参数出问题时，运维/事后
            # 排查要在 JSONL 里按 outcome 直接捞出这条——本次 P0 之所以拖了
            # 三天（09-08 ~ 09-11），正是因为非法参数本该留下一条可检索的记录
            # 却什么都没留（logging.py：业务代码用 log_event 写稳定事件）。
            log_event(
                logger, "system_log",
                "reasoning_effort 档位未映射到合法线格式字面量，已跳过注入",
                level="warn",
                component="model_provider",
                outcome="reasoning_effort_not_injected",
                harness_level=reasoning_effort,
                wire_value=wire,
            )
        else:
            kwargs["reasoning_effort"] = wire
    return ReasoningChatOpenAI(**kwargs)
