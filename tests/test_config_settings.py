from pathlib import Path

from ds_course_agent.shared.config import (
    MODEL_CHAT,
    RAG_ANSWER_CACHE_ENABLED,
    RAG_ANSWER_CACHE_SIZE,
    RAG_ANSWER_CACHE_TTL_SECONDS,
    RAG_ANSWER_MAX_TOKENS,
    RAG_ANSWER_TIMEOUT_SECONDS,
    RAG_CONTEXT_DOC_MAX_CHARS,
    RAG_CONTEXT_MAX_CHARS,
    RAG_CONTEXT_TRIM_ENABLED,
    RAG_RETRIEVAL_CACHE_ENABLED,
    RAG_RETRIEVAL_CACHE_SIZE,
    RAG_RETRIEVAL_CACHE_TTL_SECONDS,
    RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS,
    rag_answer_cache_enabled,
    rag_answer_cache_size,
    rag_answer_cache_ttl_seconds,
    rag_answer_max_tokens,
    rag_answer_timeout_seconds,
    rag_context_doc_max_chars,
    rag_context_max_chars,
    rag_context_trim_enabled,
    rag_retrieval_cache_enabled,
    rag_retrieval_cache_size,
    rag_retrieval_cache_ttl_seconds,
    rag_retrieval_embedding_timeout_seconds,
    settings,
)
from ds_course_agent.shared.config.schema import Settings
from ds_course_agent.shared.paths import PROJECT_ROOT


def test_settings_exports_typed_singleton_and_aliases():
    assert isinstance(settings, Settings)
    assert MODEL_CHAT == settings.CHAT_MODEL


def test_settings_resolves_project_relative_paths():
    value = Settings(CHROMA_PERSIST_DIR="var/example_chroma").CHROMA_PERSIST_DIR
    assert Path(value).is_absolute()
    assert value == str(PROJECT_ROOT / "var/example_chroma")


def test_course_collection_name_overrides_default_collection():
    cfg = Settings(COURSE_COLLECTION_NAME="course_custom", COLLECTION_NAME="fallback")
    assert cfg.COLLECTION_NAME == "course_custom"


def test_rag_context_trim_settings_are_exported():
    cfg = Settings(
        RAG_CONTEXT_TRIM_ENABLED=False,
        RAG_CONTEXT_MAX_CHARS=1234,
        RAG_CONTEXT_DOC_MAX_CHARS=456,
        RAG_ANSWER_MAX_TOKENS=321,
        RAG_ANSWER_TIMEOUT_SECONDS=7.5,
        RAG_ANSWER_CACHE_ENABLED=False,
        RAG_ANSWER_CACHE_TTL_SECONDS=123.0,
        RAG_ANSWER_CACHE_SIZE=17,
        RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS=1.5,
        RAG_RETRIEVAL_CACHE_ENABLED=False,
        RAG_RETRIEVAL_CACHE_TTL_SECONDS=456.0,
        RAG_RETRIEVAL_CACHE_SIZE=19,
    )
    assert cfg.RAG_CONTEXT_TRIM_ENABLED is False
    assert cfg.RAG_CONTEXT_MAX_CHARS == 1234
    assert cfg.RAG_CONTEXT_DOC_MAX_CHARS == 456
    assert cfg.RAG_ANSWER_MAX_TOKENS == 321
    assert cfg.RAG_ANSWER_TIMEOUT_SECONDS == 7.5
    assert cfg.RAG_ANSWER_CACHE_ENABLED is False
    assert cfg.RAG_ANSWER_CACHE_TTL_SECONDS == 123.0
    assert cfg.RAG_ANSWER_CACHE_SIZE == 17
    assert cfg.RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS == 1.5
    assert cfg.RAG_RETRIEVAL_CACHE_ENABLED is False
    assert cfg.RAG_RETRIEVAL_CACHE_TTL_SECONDS == 456.0
    assert cfg.RAG_RETRIEVAL_CACHE_SIZE == 19

    assert RAG_CONTEXT_TRIM_ENABLED == settings.RAG_CONTEXT_TRIM_ENABLED
    assert RAG_CONTEXT_MAX_CHARS == settings.RAG_CONTEXT_MAX_CHARS
    assert RAG_CONTEXT_DOC_MAX_CHARS == settings.RAG_CONTEXT_DOC_MAX_CHARS
    assert RAG_ANSWER_MAX_TOKENS == settings.RAG_ANSWER_MAX_TOKENS
    assert RAG_ANSWER_TIMEOUT_SECONDS == settings.RAG_ANSWER_TIMEOUT_SECONDS
    assert RAG_ANSWER_CACHE_ENABLED == settings.RAG_ANSWER_CACHE_ENABLED
    assert RAG_ANSWER_CACHE_TTL_SECONDS == settings.RAG_ANSWER_CACHE_TTL_SECONDS
    assert RAG_ANSWER_CACHE_SIZE == settings.RAG_ANSWER_CACHE_SIZE
    assert RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS == settings.RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS
    assert RAG_RETRIEVAL_CACHE_ENABLED == settings.RAG_RETRIEVAL_CACHE_ENABLED
    assert RAG_RETRIEVAL_CACHE_TTL_SECONDS == settings.RAG_RETRIEVAL_CACHE_TTL_SECONDS
    assert RAG_RETRIEVAL_CACHE_SIZE == settings.RAG_RETRIEVAL_CACHE_SIZE
    assert rag_context_trim_enabled == settings.RAG_CONTEXT_TRIM_ENABLED
    assert rag_context_max_chars == settings.RAG_CONTEXT_MAX_CHARS
    assert rag_context_doc_max_chars == settings.RAG_CONTEXT_DOC_MAX_CHARS
    assert rag_answer_max_tokens == settings.RAG_ANSWER_MAX_TOKENS
    assert rag_answer_timeout_seconds == settings.RAG_ANSWER_TIMEOUT_SECONDS
    assert rag_answer_cache_enabled == settings.RAG_ANSWER_CACHE_ENABLED
    assert rag_answer_cache_ttl_seconds == settings.RAG_ANSWER_CACHE_TTL_SECONDS
    assert rag_answer_cache_size == settings.RAG_ANSWER_CACHE_SIZE
    assert rag_retrieval_embedding_timeout_seconds == settings.RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS
    assert rag_retrieval_cache_enabled == settings.RAG_RETRIEVAL_CACHE_ENABLED
    assert rag_retrieval_cache_ttl_seconds == settings.RAG_RETRIEVAL_CACHE_TTL_SECONDS
    assert rag_retrieval_cache_size == settings.RAG_RETRIEVAL_CACHE_SIZE
