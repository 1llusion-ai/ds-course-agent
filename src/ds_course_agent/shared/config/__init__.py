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
    "EMBEDDING_TIMEOUT_SECONDS",
    "EMBEDDING_MAX_RETRIES",
    "EMBEDDING_QUERY_CACHE_SIZE",
    "EMBEDDING_CIRCUIT_BREAKER_SECONDS",
    "CHAT_MODEL",
    "CHAT_BASE_URL",
    "USE_REMOTE_LLM",
    "REMOTE_MODEL_NAME",
    "CHAT_MAX_TOKENS",
    "CHAT_TIMEOUT_SECONDS",
    "CHAT_MAX_RETRIES",
    "CHAT_DISABLE_THINKING",
    "CHAT_SYSTEM_SUFFIX",
    "API_CHAT_MAX_CONCURRENT",
    "API_CHAT_MAX_PER_STUDENT",
    "ASSESSMENT_GENERATOR_MODEL_NAME",
    "ASSESSMENT_VERIFIER_MODEL_NAME",
    "ASSESSMENT_MAX_TOKENS",
    "ASSESSMENT_TIMEOUT_SECONDS",
    "ASSESSMENT_TEMPERATURE",
    "ASSESSMENT_CONTEXT_MAX_CHARS",
    "ASSESSMENT_DB_PATH",
    "ROUTER_MODEL_NAME",
    "ROUTER_MAX_TOKENS",
    "ROUTER_TIMEOUT_SECONDS",
    "ROUTER_MAX_RETRIES",
    "ROUTER_RECENT_CONTEXT_MAX_CHARS",
    "ROUTER_MIN_CONFIDENCE",
    "QUERY_CACHE_ENABLED",
    "QUERY_CACHE_SIZE",
    "CONCEPT_MAP_EMBEDDING_MODE",
    "CONCEPT_MAP_QUERY_EMBEDDING_TIMEOUT_SECONDS",
    "CONCEPT_MAP_SKIP_EMBEDDING_IF_RULE_MATCH",
    "CONCEPT_MAP_MIN_RULE_MATCHES_TO_SKIP",
    "CONCEPT_MAP_ONLINE_PRECOMPUTE_ENABLED",
    "COURSE_NAME",
    "COURSE_DESCRIPTION",
    "COURSE_COLLECTION_NAME",
    "CHROMA_PERSIST_DIR",
    "CHAT_HISTORY_DIR",
    "MD5_RECORD_FILE",
    "APP_ENV",
    "AUTH_SECRET_KEY",
    "AUTH_SESSION_TTL_HOURS",
    "AUTH_COOKIE_SECURE",
    "AUTH_DB_PATH",
    "AUTH_LOGIN_WINDOW_SECONDS",
    "AUTH_LOGIN_MAX_PER_ACCOUNT",
    "AUTH_LOGIN_MAX_PER_IP",
    "CORS_ALLOW_ORIGINS",
    "COLLECTION_NAME",
    "SIMILARITY_TOP_K",
    "SHORT_MEMORY_RECENT_MESSAGES",
    "SHORT_MEMORY_SUMMARIZE_AFTER_MESSAGES",
    "SHORT_MEMORY_SUMMARY_MAX_CHARS",
    "CONTEXT_WINDOW_TOKENS",
    "CONTEXT_BUDGET_RATIO",
    "CONTEXT_LARGE_MESSAGE_TOKENS",
    "CONTEXT_SEMANTIC_SUMMARY_ENABLED",
    "CONTEXT_SEMANTIC_SUMMARY_TIMEOUT_SECONDS",
    "RAG_CANDIDATE_DEPTH",
    "RAG_CONTEXT_MAX_TOKENS",
    "RAG_CONTEXT_TOKENIZER_POLICY",
    "RAG_CONTEXT_DEDUPLICATION_MODE",
    "RAG_CONTEXT_OVERFLOW_POLICY",
    "RAG_CONTEXT_HEADER_POLICY",
    "RAG_INDEX_MANIFEST_PATH",
    "RAG_ANSWER_MAX_TOKENS",
    "RAG_ANSWER_TIMEOUT_SECONDS",
    "RAG_ANSWER_CACHE_ENABLED",
    "RAG_ANSWER_CACHE_TTL_SECONDS",
    "RAG_ANSWER_CACHE_SIZE",
    "RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS",
    "RAG_RETRIEVAL_CACHE_ENABLED",
    "RAG_RETRIEVAL_CACHE_TTL_SECONDS",
    "RAG_RETRIEVAL_CACHE_SIZE",
    "TOOL_RESULT_ARTIFACTS_ENABLED",
    "TOOL_RESULT_ARTIFACT_DIR",
    "TOOL_RESULT_INLINE_MAX_CHARS",
    "SCOPE_GUARD_ENABLED",
    "WEB_SEARCH_ENABLED",
    "WEB_SEARCH_PROVIDER",
    "WEB_SEARCH_API_KEY",
    "WEB_SEARCH_TOP_K",
    "WEB_SEARCH_MIN_TOP_K",
    "WEB_SEARCH_MAX_TOP_K",
    "WEB_SEARCH_TIMEOUT_SECONDS",
    "WEB_SEARCH_CONTEXT_MAX_CHARS",
    "WEB_SEARCH_SNIPPET_MAX_CHARS",
    "WEB_SEARCH_TEACHING_SCOPE_ENABLED",
    "WEB_FETCH_ENABLED",
    "WEB_FETCH_ADAPTIVE_ENABLED",
    "WEB_FETCH_TOP_N",
    "WEB_FETCH_MAX_ATTEMPTS",
    "WEB_FETCH_MAX_WORKERS",
    "WEB_FETCH_TOTAL_TIMEOUT_SECONDS",
    "WEB_FETCH_TIMEOUT_SECONDS",
    "WEB_FETCH_MAX_BYTES",
    "WEB_FETCH_MAX_CHARS_PER_PAGE",
    "WEB_FETCH_CONTEXT_MAX_CHARS",
    "WEB_FETCH_USE_JINA_READER",
    "PYTHON_EXEC_ENABLED",
    "PYTHON_EXEC_BACKEND",
    "PYTHON_EXEC_ALLOW_HOST_FALLBACK",
    "PYTHON_EXEC_DOCKER_IMAGE",
    "PYTHON_EXEC_DOCKER_AVAILABILITY_TTL_SECONDS",
    "PYTHON_EXEC_TIMEOUT_SECONDS",
    "PYTHON_EXEC_MAX_CONCURRENT",
    "PYTHON_EXEC_BUSY_TIMEOUT_SECONDS",
    "PYTHON_EXEC_MAX_OUTPUT_CHARS",
    "PYTHON_EXEC_MEMORY_MB",
    "PYTHON_EXEC_CPUS",
    "PYTHON_EXEC_TMPFS_MB",
    "PYTHON_EXEC_PIDS_LIMIT",
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
router_model_name = ROUTER_MODEL_NAME
router_max_tokens = ROUTER_MAX_TOKENS
router_timeout_seconds = ROUTER_TIMEOUT_SECONDS
router_max_retries = ROUTER_MAX_RETRIES
router_recent_context_max_chars = ROUTER_RECENT_CONTEXT_MAX_CHARS
router_min_confidence = ROUTER_MIN_CONFIDENCE
query_cache_enabled = QUERY_CACHE_ENABLED
query_cache_size = QUERY_CACHE_SIZE
concept_map_embedding_mode = CONCEPT_MAP_EMBEDDING_MODE
concept_map_query_embedding_timeout_seconds = CONCEPT_MAP_QUERY_EMBEDDING_TIMEOUT_SECONDS
concept_map_skip_embedding_if_rule_match = CONCEPT_MAP_SKIP_EMBEDDING_IF_RULE_MATCH
concept_map_min_rule_matches_to_skip = CONCEPT_MAP_MIN_RULE_MATCHES_TO_SKIP
concept_map_online_precompute_enabled = CONCEPT_MAP_ONLINE_PRECOMPUTE_ENABLED
embedding_timeout_seconds = EMBEDDING_TIMEOUT_SECONDS
embedding_max_retries = EMBEDDING_MAX_RETRIES
embedding_query_cache_size = EMBEDDING_QUERY_CACHE_SIZE
embedding_circuit_breaker_seconds = EMBEDDING_CIRCUIT_BREAKER_SECONDS
context_window_tokens = CONTEXT_WINDOW_TOKENS
context_budget_ratio = CONTEXT_BUDGET_RATIO
context_large_message_tokens = CONTEXT_LARGE_MESSAGE_TOKENS
context_semantic_summary_enabled = CONTEXT_SEMANTIC_SUMMARY_ENABLED
context_semantic_summary_timeout_seconds = CONTEXT_SEMANTIC_SUMMARY_TIMEOUT_SECONDS
rag_candidate_depth = RAG_CANDIDATE_DEPTH
rag_context_max_tokens = RAG_CONTEXT_MAX_TOKENS
rag_context_tokenizer_policy = RAG_CONTEXT_TOKENIZER_POLICY
rag_context_deduplication_mode = RAG_CONTEXT_DEDUPLICATION_MODE
rag_context_overflow_policy = RAG_CONTEXT_OVERFLOW_POLICY
rag_context_header_policy = RAG_CONTEXT_HEADER_POLICY
rag_index_manifest_path = RAG_INDEX_MANIFEST_PATH
rag_answer_max_tokens = RAG_ANSWER_MAX_TOKENS
rag_answer_timeout_seconds = RAG_ANSWER_TIMEOUT_SECONDS
rag_answer_cache_enabled = RAG_ANSWER_CACHE_ENABLED
rag_answer_cache_ttl_seconds = RAG_ANSWER_CACHE_TTL_SECONDS
rag_answer_cache_size = RAG_ANSWER_CACHE_SIZE
rag_retrieval_embedding_timeout_seconds = RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS
rag_retrieval_cache_enabled = RAG_RETRIEVAL_CACHE_ENABLED
rag_retrieval_cache_ttl_seconds = RAG_RETRIEVAL_CACHE_TTL_SECONDS
rag_retrieval_cache_size = RAG_RETRIEVAL_CACHE_SIZE
tool_result_artifacts_enabled = TOOL_RESULT_ARTIFACTS_ENABLED
tool_result_artifact_dir = TOOL_RESULT_ARTIFACT_DIR
tool_result_inline_max_chars = TOOL_RESULT_INLINE_MAX_CHARS
scope_guard_enabled = SCOPE_GUARD_ENABLED
web_search_enabled = WEB_SEARCH_ENABLED
web_search_provider = WEB_SEARCH_PROVIDER
web_search_api_key = WEB_SEARCH_API_KEY
web_search_top_k = WEB_SEARCH_TOP_K
web_search_min_top_k = WEB_SEARCH_MIN_TOP_K
web_search_max_top_k = WEB_SEARCH_MAX_TOP_K
web_search_timeout_seconds = WEB_SEARCH_TIMEOUT_SECONDS
web_search_context_max_chars = WEB_SEARCH_CONTEXT_MAX_CHARS
web_search_snippet_max_chars = WEB_SEARCH_SNIPPET_MAX_CHARS
web_search_teaching_scope_enabled = WEB_SEARCH_TEACHING_SCOPE_ENABLED
web_fetch_enabled = WEB_FETCH_ENABLED
web_fetch_adaptive_enabled = WEB_FETCH_ADAPTIVE_ENABLED
web_fetch_top_n = WEB_FETCH_TOP_N
web_fetch_max_attempts = WEB_FETCH_MAX_ATTEMPTS
web_fetch_max_workers = WEB_FETCH_MAX_WORKERS
web_fetch_total_timeout_seconds = WEB_FETCH_TOTAL_TIMEOUT_SECONDS
web_fetch_timeout_seconds = WEB_FETCH_TIMEOUT_SECONDS
web_fetch_max_bytes = WEB_FETCH_MAX_BYTES
web_fetch_max_chars_per_page = WEB_FETCH_MAX_CHARS_PER_PAGE
web_fetch_context_max_chars = WEB_FETCH_CONTEXT_MAX_CHARS
web_fetch_use_jina_reader = WEB_FETCH_USE_JINA_READER
python_exec_enabled = PYTHON_EXEC_ENABLED
python_exec_backend = PYTHON_EXEC_BACKEND
python_exec_allow_host_fallback = PYTHON_EXEC_ALLOW_HOST_FALLBACK
python_exec_docker_image = PYTHON_EXEC_DOCKER_IMAGE
python_exec_docker_availability_ttl_seconds = PYTHON_EXEC_DOCKER_AVAILABILITY_TTL_SECONDS
python_exec_timeout_seconds = PYTHON_EXEC_TIMEOUT_SECONDS
python_exec_max_concurrent = PYTHON_EXEC_MAX_CONCURRENT
python_exec_busy_timeout_seconds = PYTHON_EXEC_BUSY_TIMEOUT_SECONDS
python_exec_max_output_chars = PYTHON_EXEC_MAX_OUTPUT_CHARS
python_exec_memory_mb = PYTHON_EXEC_MEMORY_MB
python_exec_cpus = PYTHON_EXEC_CPUS
python_exec_tmpfs_mb = PYTHON_EXEC_TMPFS_MB
python_exec_pids_limit = PYTHON_EXEC_PIDS_LIMIT
auth_secret_key = AUTH_SECRET_KEY
auth_session_ttl_hours = AUTH_SESSION_TTL_HOURS
auth_cookie_secure = AUTH_COOKIE_SECURE
auth_db_path = AUTH_DB_PATH
assessment_db_path = ASSESSMENT_DB_PATH
cors_allow_origins = CORS_ALLOW_ORIGINS

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
    "router_model_name",
    "router_max_tokens",
    "router_timeout_seconds",
    "router_max_retries",
    "router_recent_context_max_chars",
    "router_min_confidence",
    "query_cache_enabled",
    "query_cache_size",
    "concept_map_embedding_mode",
    "concept_map_query_embedding_timeout_seconds",
    "concept_map_skip_embedding_if_rule_match",
    "concept_map_min_rule_matches_to_skip",
    "concept_map_online_precompute_enabled",
    "embedding_timeout_seconds",
    "embedding_max_retries",
    "embedding_query_cache_size",
    "embedding_circuit_breaker_seconds",
    "context_window_tokens",
    "context_budget_ratio",
    "context_large_message_tokens",
    "context_semantic_summary_enabled",
    "context_semantic_summary_timeout_seconds",
    "rag_candidate_depth",
    "rag_context_max_tokens",
    "rag_context_tokenizer_policy",
    "rag_context_deduplication_mode",
    "rag_context_overflow_policy",
    "rag_context_header_policy",
    "rag_index_manifest_path",
    "rag_answer_max_tokens",
    "rag_answer_timeout_seconds",
    "rag_answer_cache_enabled",
    "rag_answer_cache_ttl_seconds",
    "rag_answer_cache_size",
    "rag_retrieval_embedding_timeout_seconds",
    "rag_retrieval_cache_enabled",
    "rag_retrieval_cache_ttl_seconds",
    "rag_retrieval_cache_size",
    "tool_result_artifacts_enabled",
    "tool_result_artifact_dir",
    "tool_result_inline_max_chars",
    "scope_guard_enabled",
    "web_search_enabled",
    "web_search_provider",
    "web_search_api_key",
    "web_search_top_k",
    "web_search_timeout_seconds",
    "web_search_context_max_chars",
    "web_search_snippet_max_chars",
    "web_search_teaching_scope_enabled",
    "web_fetch_enabled",
    "web_fetch_adaptive_enabled",
    "web_fetch_top_n",
    "web_fetch_max_attempts",
    "web_fetch_max_workers",
    "web_fetch_total_timeout_seconds",
    "web_fetch_timeout_seconds",
    "web_fetch_max_bytes",
    "web_fetch_max_chars_per_page",
    "web_fetch_context_max_chars",
    "web_fetch_use_jina_reader",
    "python_exec_enabled",
    "python_exec_backend",
    "python_exec_allow_host_fallback",
    "python_exec_docker_image",
    "python_exec_docker_availability_ttl_seconds",
    "python_exec_timeout_seconds",
    "python_exec_max_concurrent",
    "python_exec_busy_timeout_seconds",
    "python_exec_max_output_chars",
    "python_exec_memory_mb",
    "python_exec_cpus",
    "python_exec_tmpfs_mb",
    "python_exec_pids_limit",
    "auth_secret_key",
    "auth_session_ttl_hours",
    "auth_cookie_secure",
    "auth_db_path",
    "assessment_db_path",
    "cors_allow_origins",
    *_SETTING_NAMES,
]
