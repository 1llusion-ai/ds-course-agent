"""Typed configuration schema for the course agent."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ds_course_agent.shared.paths import PROJECT_ROOT


def _project_path(value: str) -> str:
    path = Path(str(value))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path)


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and ``.env``.

    Field names intentionally match the environment keys. This keeps the public
    config surface explicit while allowing ``shared.config`` to export constants
    derived from one typed settings object.
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    DATALAB_API_KEY: str = ""

    EMBEDDING_API_KEY: str = ""
    EMBEDDING_BASE_URL: str = "https://api.siliconflow.cn/v1"
    EMBEDDING_MODEL: str = "Qwen/Qwen3-Embedding-8B"
    EMBEDDING_TIMEOUT_SECONDS: float = 8.0
    EMBEDDING_MAX_RETRIES: int = 0
    EMBEDDING_QUERY_CACHE_SIZE: int = 512
    EMBEDDING_CIRCUIT_BREAKER_SECONDS: float = 60.0

    # LLM configuration.
    CHAT_MODEL: str = "qwen3:8b"
    CHAT_BASE_URL: str = "http://localhost:11434"
    USE_REMOTE_LLM: bool = False
    REMOTE_MODEL_NAME: str = "Qwen/Qwen3-8B"
    CHAT_MAX_TOKENS: int = 512
    CHAT_TIMEOUT_SECONDS: float = 45
    CHAT_MAX_RETRIES: int = 2
    CHAT_DISABLE_THINKING: bool = True
    CHAT_SYSTEM_SUFFIX: str = "/no_think"

    # Assessment author and verifier may use different models while sharing the
    # same provider connection and bounded call budget.
    ASSESSMENT_GENERATOR_MODEL_NAME: str = ""
    ASSESSMENT_VERIFIER_MODEL_NAME: str = ""
    ASSESSMENT_MAX_TOKENS: int = Field(default=4096, ge=256, le=32768)
    ASSESSMENT_TIMEOUT_SECONDS: float = Field(default=60.0, gt=0.0, le=300.0, allow_inf_nan=False)
    ASSESSMENT_TEMPERATURE: float = Field(default=0.2, ge=0.0, le=1.0, allow_inf_nan=False)
    ASSESSMENT_CONTEXT_MAX_CHARS: int = Field(default=6000, ge=256, le=32000)
    ASSESSMENT_DB_PATH: str = "var/assessment.db"

    # Learning semantic router.  An empty model name reuses the active chat
    # model for the selected local/remote backend.
    ROUTER_MODEL_NAME: str = ""
    ROUTER_MAX_TOKENS: int = Field(default=128, ge=16)
    ROUTER_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0.0)
    ROUTER_MAX_RETRIES: int = Field(default=0, ge=0)
    ROUTER_RECENT_CONTEXT_MAX_CHARS: int = Field(default=1200, ge=0)
    ROUTER_MIN_CONFIDENCE: float = Field(default=0.65, ge=0.0, le=1.0)

    # Lightweight in-process caches.
    QUERY_CACHE_ENABLED: bool = True
    QUERY_CACHE_SIZE: int = 512

    # Concept mapping.  Concept embeddings should be precomputed offline and
    # loaded from ``data/knowledge_graph_embeddings.json`` in request paths.
    # Query embedding is only a short-timeout semantic fallback after exact/regex
    # matching fails to find enough concepts.
    CONCEPT_MAP_EMBEDDING_MODE: str = "offline_first"
    CONCEPT_MAP_QUERY_EMBEDDING_TIMEOUT_SECONDS: float = 0.5
    CONCEPT_MAP_SKIP_EMBEDDING_IF_RULE_MATCH: bool = True
    CONCEPT_MAP_MIN_RULE_MATCHES_TO_SKIP: int = 1
    CONCEPT_MAP_ONLINE_PRECOMPUTE_ENABLED: bool = False

    COURSE_NAME: str = "数据科学导论"
    COURSE_DESCRIPTION: str = "概念答疑、课程资料问答、学习建议"
    COURSE_COLLECTION_NAME: str = ""

    CHROMA_PERSIST_DIR: str = "var/chroma_db"
    CHAT_HISTORY_DIR: str = "var/chat_history"
    MD5_RECORD_FILE: str = "md5.text"

    # Local login / cookie session authentication.
    AUTH_SECRET_KEY: str = ""
    AUTH_SESSION_TTL_HOURS: int = 12
    AUTH_COOKIE_SECURE: bool = False
    AUTH_DB_PATH: str = "var/auth.db"
    CORS_ALLOW_ORIGINS: str = ""

    COLLECTION_NAME: str = "rag_knowledge_base"
    SIMILARITY_TOP_K: int = 3

    # Short-term memory.
    SHORT_MEMORY_RECENT_MESSAGES: int = 12
    SHORT_MEMORY_SUMMARIZE_AFTER_MESSAGES: int = 20
    SHORT_MEMORY_SUMMARY_MAX_CHARS: int = 2000

    # Context governance.
    CONTEXT_WINDOW_TOKENS: int = 8192
    CONTEXT_BUDGET_RATIO: float = 0.70
    CONTEXT_LARGE_MESSAGE_TOKENS: int = 2048
    CONTEXT_SEMANTIC_SUMMARY_ENABLED: bool = False
    CONTEXT_SEMANTIC_SUMMARY_TIMEOUT_SECONDS: float = 3.0

    # Frozen production retrieval/context policy. Retrieved chunks require exact
    # source intervals and are assembled once in raw vector rank order.
    RAG_CANDIDATE_DEPTH: int = Field(default=10, ge=1)
    RAG_CONTEXT_MAX_TOKENS: int = Field(default=4096, ge=1)
    RAG_CONTEXT_TOKENIZER_POLICY: Literal["cl100k_base_v1"] = "cl100k_base_v1"
    RAG_CONTEXT_DEDUPLICATION_MODE: Literal["exact_source_interval_v1"] = "exact_source_interval_v1"
    RAG_CONTEXT_OVERFLOW_POLICY: Literal["stop_v1"] = "stop_v1"
    RAG_CONTEXT_HEADER_POLICY: Literal["compact_page_v1"] = "compact_page_v1"
    RAG_INDEX_MANIFEST_PATH: str = ""
    RAG_ANSWER_MAX_TOKENS: int = 768
    RAG_ANSWER_TIMEOUT_SECONDS: float = 30.0
    RAG_ANSWER_CACHE_ENABLED: bool = True
    RAG_ANSWER_CACHE_TTL_SECONDS: float = 900.0
    RAG_ANSWER_CACHE_SIZE: int = 128
    RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS: float = 5.0
    RAG_RETRIEVAL_CACHE_ENABLED: bool = True
    RAG_RETRIEVAL_CACHE_TTL_SECONDS: float = 600.0
    RAG_RETRIEVAL_CACHE_SIZE: int = 128

    # Tool/RAG large-result artifact storage.
    TOOL_RESULT_ARTIFACTS_ENABLED: bool = True
    TOOL_RESULT_ARTIFACT_DIR: str = "var/artifacts/tool_results"
    TOOL_RESULT_INLINE_MAX_CHARS: int = 3000

    # Product/domain scope guard.  Keeps the course assistant from acting as a
    # general-purpose search/Q&A bot while still allowing data-science framing
    # of real-world topics.
    SCOPE_GUARD_ENABLED: bool = True

    # Explicit user-triggered web search.  Disabled by default so the assistant
    # never reaches external networks unless the deployment config and request
    # both opt in.
    WEB_SEARCH_ENABLED: bool = False
    WEB_SEARCH_PROVIDER: str = "tavily"
    WEB_SEARCH_API_KEY: str = ""
    WEB_SEARCH_TOP_K: int = 0
    WEB_SEARCH_MIN_TOP_K: int = 8
    WEB_SEARCH_MAX_TOP_K: int = 16
    WEB_SEARCH_TIMEOUT_SECONDS: float = 12.0
    WEB_SEARCH_CONTEXT_MAX_CHARS: int = 2500
    WEB_SEARCH_SNIPPET_MAX_CHARS: int = 300
    WEB_SEARCH_TEACHING_SCOPE_ENABLED: bool = True
    WEB_FETCH_ENABLED: bool = False
    WEB_FETCH_ADAPTIVE_ENABLED: bool = True
    WEB_FETCH_TOP_N: int = 4
    WEB_FETCH_MAX_ATTEMPTS: int = 10
    WEB_FETCH_MAX_WORKERS: int = 4
    WEB_FETCH_TOTAL_TIMEOUT_SECONDS: float = 0.0
    WEB_FETCH_TIMEOUT_SECONDS: float = 6.0
    WEB_FETCH_MAX_BYTES: int = 1_000_000
    WEB_FETCH_MAX_CHARS_PER_PAGE: int = 3500
    WEB_FETCH_CONTEXT_MAX_CHARS: int = 4500
    WEB_FETCH_USE_JINA_READER: bool = True

    # Explicit Python execution sandbox.  Docker is the safe default; host
    # subprocess execution is only for trusted local development/tests and must
    # be opted into explicitly.
    PYTHON_EXEC_ENABLED: bool = True
    PYTHON_EXEC_BACKEND: str = "docker"
    PYTHON_EXEC_ALLOW_HOST_FALLBACK: bool = False
    PYTHON_EXEC_DOCKER_IMAGE: str = "python:3.11-slim"
    PYTHON_EXEC_DOCKER_AVAILABILITY_TTL_SECONDS: float = Field(default=5.0, ge=0.0)
    PYTHON_EXEC_TIMEOUT_SECONDS: int = 5
    PYTHON_EXEC_MAX_CONCURRENT: int = Field(default=2, ge=1)
    PYTHON_EXEC_BUSY_TIMEOUT_SECONDS: float = Field(default=0.0, ge=0.0)
    PYTHON_EXEC_MAX_OUTPUT_CHARS: int = 4000
    PYTHON_EXEC_MEMORY_MB: int = 256
    PYTHON_EXEC_CPUS: float = 0.5
    PYTHON_EXEC_TMPFS_MB: int = 64
    PYTHON_EXEC_PIDS_LIMIT: int = 64

    CHUNK_SIZE: int = 1300
    CHUNK_OVERLAP: int = 300
    MAX_SPLIT_CHAR_NUMBER: int = 1500

    # Reranker.
    ENABLE_RERANK: bool = False
    RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3"
    RERANK_TOP_K: int = 20
    RERANK_BATCH_SIZE: int = 8
    RERANK_DEVICE: str = "auto"

    SEPARATORS: list[str] = Field(
        default_factory=lambda: ["\n\n", "\n", " ", "", ".", "?", "!", ",", "，", "。", "？", "！"]
    )

    DEFAULT_SESSION_ID: str = "user_001"
    LOG_LEVEL: str = "INFO"

    @field_validator("LOG_LEVEL")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        return str(value or "INFO").upper()

    @field_validator("PYTHON_EXEC_BACKEND")
    @classmethod
    def _normalize_python_exec_backend(cls, value: str) -> str:
        return str(value or "docker").strip().lower()

    @field_validator(
        "CHROMA_PERSIST_DIR",
        "CHAT_HISTORY_DIR",
        "MD5_RECORD_FILE",
        "TOOL_RESULT_ARTIFACT_DIR",
        "AUTH_DB_PATH",
        "ASSESSMENT_DB_PATH",
    )
    @classmethod
    def _resolve_project_paths(cls, value: str) -> str:
        return _project_path(value)

    @model_validator(mode="after")
    def _apply_derived_values(self) -> Settings:
        if self.COURSE_COLLECTION_NAME:
            self.COLLECTION_NAME = self.COURSE_COLLECTION_NAME
        return self


__all__ = ["Settings"]
