from pathlib import Path

from ds_course_agent.shared.config import (
    AUTH_COOKIE_SECURE,
    AUTH_DB_PATH,
    AUTH_SECRET_KEY,
    AUTH_SESSION_TTL_HOURS,
    CORS_ALLOW_ORIGINS,
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
    PYTHON_EXEC_ALLOW_HOST_FALLBACK,
    PYTHON_EXEC_BACKEND,
    PYTHON_EXEC_BUSY_TIMEOUT_SECONDS,
    PYTHON_EXEC_DOCKER_AVAILABILITY_TTL_SECONDS,
    PYTHON_EXEC_DOCKER_IMAGE,
    PYTHON_EXEC_ENABLED,
    PYTHON_EXEC_MAX_CONCURRENT,
    CONTEXT_SEMANTIC_SUMMARY_ENABLED,
    CONTEXT_SEMANTIC_SUMMARY_TIMEOUT_SECONDS,
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
    python_exec_allow_host_fallback,
    python_exec_backend,
    python_exec_busy_timeout_seconds,
    python_exec_docker_availability_ttl_seconds,
    python_exec_docker_image,
    python_exec_enabled,
    python_exec_max_concurrent,
    context_semantic_summary_enabled,
    auth_cookie_secure,
    auth_db_path,
    auth_secret_key,
    auth_session_ttl_hours,
    cors_allow_origins,
    context_semantic_summary_timeout_seconds,
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


def test_python_exec_sandbox_settings_are_exported():
    cfg = Settings(
        PYTHON_EXEC_ENABLED=False,
        PYTHON_EXEC_BACKEND="LOCAL",
        PYTHON_EXEC_ALLOW_HOST_FALLBACK=True,
        PYTHON_EXEC_DOCKER_IMAGE="python:test",
        PYTHON_EXEC_DOCKER_AVAILABILITY_TTL_SECONDS=0.5,
        PYTHON_EXEC_MAX_CONCURRENT=3,
        PYTHON_EXEC_BUSY_TIMEOUT_SECONDS=0.25,
    )

    assert cfg.PYTHON_EXEC_ENABLED is False
    assert cfg.PYTHON_EXEC_BACKEND == "local"
    assert cfg.PYTHON_EXEC_ALLOW_HOST_FALLBACK is True
    assert cfg.PYTHON_EXEC_DOCKER_IMAGE == "python:test"
    assert cfg.PYTHON_EXEC_DOCKER_AVAILABILITY_TTL_SECONDS == 0.5
    assert cfg.PYTHON_EXEC_MAX_CONCURRENT == 3
    assert cfg.PYTHON_EXEC_BUSY_TIMEOUT_SECONDS == 0.25
    assert PYTHON_EXEC_ENABLED == settings.PYTHON_EXEC_ENABLED
    assert PYTHON_EXEC_BACKEND == settings.PYTHON_EXEC_BACKEND
    assert PYTHON_EXEC_ALLOW_HOST_FALLBACK == settings.PYTHON_EXEC_ALLOW_HOST_FALLBACK
    assert PYTHON_EXEC_DOCKER_IMAGE == settings.PYTHON_EXEC_DOCKER_IMAGE
    assert PYTHON_EXEC_DOCKER_AVAILABILITY_TTL_SECONDS == settings.PYTHON_EXEC_DOCKER_AVAILABILITY_TTL_SECONDS
    assert PYTHON_EXEC_MAX_CONCURRENT == settings.PYTHON_EXEC_MAX_CONCURRENT
    assert PYTHON_EXEC_BUSY_TIMEOUT_SECONDS == settings.PYTHON_EXEC_BUSY_TIMEOUT_SECONDS
    assert python_exec_enabled == settings.PYTHON_EXEC_ENABLED
    assert python_exec_backend == settings.PYTHON_EXEC_BACKEND
    assert python_exec_allow_host_fallback == settings.PYTHON_EXEC_ALLOW_HOST_FALLBACK
    assert python_exec_docker_image == settings.PYTHON_EXEC_DOCKER_IMAGE
    assert python_exec_docker_availability_ttl_seconds == settings.PYTHON_EXEC_DOCKER_AVAILABILITY_TTL_SECONDS
    assert python_exec_max_concurrent == settings.PYTHON_EXEC_MAX_CONCURRENT
    assert python_exec_busy_timeout_seconds == settings.PYTHON_EXEC_BUSY_TIMEOUT_SECONDS


def test_context_semantic_summary_settings_are_exported():
    cfg = Settings(
        CONTEXT_SEMANTIC_SUMMARY_ENABLED=True,
        CONTEXT_SEMANTIC_SUMMARY_TIMEOUT_SECONDS=1.5,
    )

    assert cfg.CONTEXT_SEMANTIC_SUMMARY_ENABLED is True
    assert cfg.CONTEXT_SEMANTIC_SUMMARY_TIMEOUT_SECONDS == 1.5
    assert CONTEXT_SEMANTIC_SUMMARY_ENABLED == settings.CONTEXT_SEMANTIC_SUMMARY_ENABLED
    assert CONTEXT_SEMANTIC_SUMMARY_TIMEOUT_SECONDS == settings.CONTEXT_SEMANTIC_SUMMARY_TIMEOUT_SECONDS
    assert context_semantic_summary_enabled == settings.CONTEXT_SEMANTIC_SUMMARY_ENABLED
    assert context_semantic_summary_timeout_seconds == settings.CONTEXT_SEMANTIC_SUMMARY_TIMEOUT_SECONDS


def test_auth_settings_are_exported_and_paths_resolved():
    cfg = Settings(
        AUTH_SECRET_KEY="secret",
        AUTH_SESSION_TTL_HOURS=6,
        AUTH_COOKIE_SECURE=True,
        AUTH_DB_PATH="var/custom_auth.db",
        CORS_ALLOW_ORIGINS="https://example.edu",
    )

    assert cfg.AUTH_SECRET_KEY == "secret"
    assert cfg.AUTH_SESSION_TTL_HOURS == 6
    assert cfg.AUTH_COOKIE_SECURE is True
    assert Path(cfg.AUTH_DB_PATH).is_absolute()
    assert cfg.AUTH_DB_PATH == str(PROJECT_ROOT / "var/custom_auth.db")
    assert cfg.CORS_ALLOW_ORIGINS == "https://example.edu"
    assert AUTH_SECRET_KEY == settings.AUTH_SECRET_KEY
    assert AUTH_SESSION_TTL_HOURS == settings.AUTH_SESSION_TTL_HOURS
    assert AUTH_COOKIE_SECURE == settings.AUTH_COOKIE_SECURE
    assert AUTH_DB_PATH == settings.AUTH_DB_PATH
    assert CORS_ALLOW_ORIGINS == settings.CORS_ALLOW_ORIGINS
    assert auth_secret_key == settings.AUTH_SECRET_KEY
    assert auth_session_ttl_hours == settings.AUTH_SESSION_TTL_HOURS
    assert auth_cookie_secure == settings.AUTH_COOKIE_SECURE
    assert auth_db_path == settings.AUTH_DB_PATH
    assert cors_allow_origins == settings.CORS_ALLOW_ORIGINS
