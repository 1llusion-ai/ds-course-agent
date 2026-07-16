"""Typed runtime configuration.

The old single-file config module has been replaced by a package with a typed
Pydantic settings object. This module intentionally remains the public import
path (`ds_course_agent.shared.config`) and exports the project constants used by
the rest of the codebase.
"""

from __future__ import annotations

from ds_course_agent.shared.config.loader import load_settings, reload_settings
from ds_course_agent.shared.config.schema import Settings

settings = load_settings()

_SETTING_NAMES = [
    "DATALAB_API_KEY",
    "EMBEDDING_API_KEY",
    "EMBEDDING_BASE_URL",
    "EMBEDDING_MODEL",
    "CHAT_MODEL",
    "CHAT_BASE_URL",
    "USE_REMOTE_LLM",
    "REMOTE_MODEL_NAME",
    "CHAT_MAX_TOKENS",
    "CHAT_TIMEOUT_SECONDS",
    "CHAT_MAX_RETRIES",
    "CHAT_DISABLE_THINKING",
    "CHAT_SYSTEM_SUFFIX",
    "QUERY_CACHE_ENABLED",
    "QUERY_CACHE_SIZE",
    "COURSE_NAME",
    "COURSE_DESCRIPTION",
    "COURSE_COLLECTION_NAME",
    "CHROMA_PERSIST_DIR",
    "CHAT_HISTORY_DIR",
    "MD5_RECORD_FILE",
    "COLLECTION_NAME",
    "SIMILARITY_TOP_K",
    "SHORT_MEMORY_RECENT_MESSAGES",
    "SHORT_MEMORY_SUMMARIZE_AFTER_MESSAGES",
    "SHORT_MEMORY_SUMMARY_MAX_CHARS",
    "CONTEXT_WINDOW_TOKENS",
    "CONTEXT_BUDGET_RATIO",
    "CONTEXT_LARGE_MESSAGE_TOKENS",
    "TOOL_RESULT_ARTIFACTS_ENABLED",
    "TOOL_RESULT_ARTIFACT_DIR",
    "TOOL_RESULT_INLINE_MAX_CHARS",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "MAX_SPLIT_CHAR_NUMBER",
    "ENABLE_RERANK",
    "RERANK_MODEL",
    "RERANK_TOP_K",
    "RERANK_BATCH_SIZE",
    "RERANK_DEVICE",
    "SEPARATORS",
    "DEFAULT_SESSION_ID",
    "LOG_LEVEL",
]

globals().update({name: getattr(settings, name) for name in _SETTING_NAMES})

session_config = {
    "configurable": {
        "session_id": DEFAULT_SESSION_ID,
    }
}

# Domain aliases used throughout the existing codebase.
API_KEY = EMBEDDING_API_KEY
BASE_URL = EMBEDDING_BASE_URL
MODEL_EMBEDDING = EMBEDDING_MODEL
MODEL_CHAT = CHAT_MODEL
BASE_URL_CHAT = CHAT_BASE_URL

# Lowercase aliases kept as the stable config API, backed by the typed settings
# object above rather than a second implementation.
persist_directory = CHROMA_PERSIST_DIR
storage_path = CHAT_HISTORY_DIR
md5_path = MD5_RECORD_FILE
collection_name = COLLECTION_NAME
similarity_top_k = SIMILARITY_TOP_K
chunk_size = CHUNK_SIZE
chunk_overlap = CHUNK_OVERLAP
max_split_char_number = MAX_SPLIT_CHAR_NUMBER
enable_rerank = ENABLE_RERANK
rerank_model = RERANK_MODEL
rerank_top_k = RERANK_TOP_K
rerank_batch_size = RERANK_BATCH_SIZE
rerank_device = RERANK_DEVICE
chat_max_tokens = CHAT_MAX_TOKENS
chat_timeout_seconds = CHAT_TIMEOUT_SECONDS
chat_max_retries = CHAT_MAX_RETRIES
chat_disable_thinking = CHAT_DISABLE_THINKING
chat_system_suffix = CHAT_SYSTEM_SUFFIX
query_cache_enabled = QUERY_CACHE_ENABLED
query_cache_size = QUERY_CACHE_SIZE
context_window_tokens = CONTEXT_WINDOW_TOKENS
context_budget_ratio = CONTEXT_BUDGET_RATIO
context_large_message_tokens = CONTEXT_LARGE_MESSAGE_TOKENS
tool_result_artifacts_enabled = TOOL_RESULT_ARTIFACTS_ENABLED
tool_result_artifact_dir = TOOL_RESULT_ARTIFACT_DIR
tool_result_inline_max_chars = TOOL_RESULT_INLINE_MAX_CHARS

__all__ = [
    "Settings",
    "load_settings",
    "reload_settings",
    "settings",
    "session_config",
    "API_KEY",
    "BASE_URL",
    "MODEL_EMBEDDING",
    "MODEL_CHAT",
    "BASE_URL_CHAT",
    "persist_directory",
    "storage_path",
    "md5_path",
    "collection_name",
    "similarity_top_k",
    "chunk_size",
    "chunk_overlap",
    "max_split_char_number",
    "enable_rerank",
    "rerank_model",
    "rerank_top_k",
    "rerank_batch_size",
    "rerank_device",
    "chat_max_tokens",
    "chat_timeout_seconds",
    "chat_max_retries",
    "chat_disable_thinking",
    "chat_system_suffix",
    "query_cache_enabled",
    "query_cache_size",
    "context_window_tokens",
    "context_budget_ratio",
    "context_large_message_tokens",
    "tool_result_artifacts_enabled",
    "tool_result_artifact_dir",
    "tool_result_inline_max_chars",
    *_SETTING_NAMES,
]
