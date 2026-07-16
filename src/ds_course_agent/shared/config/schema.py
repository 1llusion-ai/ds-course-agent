"""Typed configuration schema for the course agent."""

from __future__ import annotations

import os
from pathlib import Path

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
    EMBEDDING_MODEL: str = "BAAI/bge-large-zh-v1.5"

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

    # Lightweight in-process caches.
    QUERY_CACHE_ENABLED: bool = True
    QUERY_CACHE_SIZE: int = 512

    COURSE_NAME: str = "数据科学导论"
    COURSE_DESCRIPTION: str = "概念答疑、课程资料问答、学习建议"
    COURSE_COLLECTION_NAME: str = ""

    CHROMA_PERSIST_DIR: str = "var/chroma_db"
    CHAT_HISTORY_DIR: str = "var/chat_history"
    MD5_RECORD_FILE: str = "md5.text"

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

    # Tool/RAG large-result artifact storage.
    TOOL_RESULT_ARTIFACTS_ENABLED: bool = True
    TOOL_RESULT_ARTIFACT_DIR: str = "var/artifacts/tool_results"
    TOOL_RESULT_INLINE_MAX_CHARS: int = 3000

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

    @field_validator(
        "CHROMA_PERSIST_DIR",
        "CHAT_HISTORY_DIR",
        "MD5_RECORD_FILE",
        "TOOL_RESULT_ARTIFACT_DIR",
    )
    @classmethod
    def _resolve_project_paths(cls, value: str) -> str:
        return _project_path(value)

    @model_validator(mode="after")
    def _apply_derived_values(self) -> "Settings":
        if self.COURSE_COLLECTION_NAME:
            self.COLLECTION_NAME = self.COURSE_COLLECTION_NAME
        return self


__all__ = ["Settings"]
