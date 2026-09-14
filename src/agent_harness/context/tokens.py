"""固定 cl100k_base 文本计数；其他模型的原生 token 数可能不同。"""

import tiktoken
from langchain_core.messages import AnyMessage


def estimate_tokens(text: str) -> int:
    """估算文本 token 数（编码由 tiktoken 缓存）。"""
    return len(tiktoken.get_encoding("cl100k_base").encode_ordinary(text))


def estimate_message_tokens(messages: list[AnyMessage]) -> int:
    """计入消息结构和 tool_calls；与文本估算使用同一个编码。"""
    return sum(estimate_tokens(message.model_dump_json()) for message in messages)
