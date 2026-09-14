from agent_harness.config import Settings
from agent_harness.memory.embeddings import create_embeddings


def test_openai_compatible_embedding_settings():
    settings = Settings(_env_file=None, embedding_model="Qwen/Qwen3-Embedding-8B",
                        embedding_base_url="https://api.siliconflow.cn/v1", embedding_api_key="test-only")
    embeddings = create_embeddings(settings)
    assert embeddings.model == "Qwen/Qwen3-Embedding-8B"
    assert embeddings.openai_api_base == "https://api.siliconflow.cn/v1"
    assert embeddings.check_embedding_ctx_length is False
    assert embeddings.dimensions == 1024
    assert "test-only" not in repr(settings.embedding_api_key)
