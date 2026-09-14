"""Reuse the existing OpenAI-compatible SDK for text embeddings."""

from langchain_openai import OpenAIEmbeddings

from agent_harness.config import Settings


def create_embeddings(settings: Settings) -> OpenAIEmbeddings:
    if not all((settings.embedding_model, settings.embedding_base_url,
                settings.embedding_api_key.get_secret_value())):
        raise ValueError("Embedding configuration is incomplete")
    return OpenAIEmbeddings(
        model=settings.embedding_model, base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key, check_embedding_ctx_length=False,
        dimensions=settings.embedding_dimensions,
        # BUG-014：max_retries 0→2——openai SDK 自带指数退避，只对 429/5xx/连接
        # 错误重试（4xx 认证/参数错不重试，不浪费 quota）。此前 0 = 上游一次瞬时
        # 500 就让该次检索/写入失败（真机会话 13 次 memory/degraded 的成因之一）。
        request_timeout=15, max_retries=2,
    )
