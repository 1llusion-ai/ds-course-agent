"""
配置管理模块
从环境变量加载配置，支持 .env 文件
"""
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.resolve()

load_dotenv(PROJECT_ROOT / ".env")


def _get_env(key: str, default: str = None) -> str:
    value = os.getenv(key, default)
    if value is None:
        raise ValueError(f"Environment variable {key} is required but not set")
    return value


def _get_path_env(key: str, default: str) -> str:
    path = os.getenv(key, default)
    if not os.path.isabs(path):
        path = str(PROJECT_ROOT / path)
    return path


EMBEDDING_API_KEY = _get_env("EMBEDDING_API_KEY", "")
EMBEDDING_BASE_URL = _get_env("EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1")
EMBEDDING_MODEL = _get_env("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")

# === LLM Configuration ===
# 本地Ollama配置
CHAT_MODEL = _get_env("CHAT_MODEL", "qwen3:8b")
CHAT_BASE_URL = _get_env("CHAT_BASE_URL", "http://localhost:11434")

# 远程API配置（如硅基流动）
USE_REMOTE_LLM = _get_env("USE_REMOTE_LLM", "false").lower() == "true"
REMOTE_MODEL_NAME = _get_env("REMOTE_MODEL_NAME", "Pro/deepseek-ai/DeepSeek-V3")

COURSE_NAME = _get_env("COURSE_NAME", "数据科学导论")
COURSE_DESCRIPTION = _get_env("COURSE_DESCRIPTION", "概念答疑、课程资料问答、学习建议")
COURSE_COLLECTION_NAME = _get_env("COURSE_COLLECTION_NAME", "")

CHROMA_PERSIST_DIR = _get_path_env("CHROMA_PERSIST_DIR", "chroma_db")
CHAT_HISTORY_DIR = _get_path_env("CHAT_HISTORY_DIR", "chat_history")
MD5_RECORD_FILE = _get_path_env("MD5_RECORD_FILE", "md5.text")

# 优先使用课程集合名称，否则使用默认集合名称
COLLECTION_NAME = COURSE_COLLECTION_NAME if COURSE_COLLECTION_NAME else _get_env("COLLECTION_NAME", "rag_knowledge_base")
SIMILARITY_TOP_K = int(_get_env("SIMILARITY_TOP_K", "3"))

CHUNK_SIZE = int(_get_env("CHUNK_SIZE", "1300"))
CHUNK_OVERLAP = int(_get_env("CHUNK_OVERLAP", "300"))
MAX_SPLIT_CHAR_NUMBER = int(_get_env("MAX_SPLIT_CHAR_NUMBER", "1500"))

# === Reranker Configuration ===
ENABLE_RERANK = _get_env("ENABLE_RERANK", "false").lower() == "true"
RERANK_MODEL = _get_env("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
RERANK_TOP_K = int(_get_env("RERANK_TOP_K", "20"))
RERANK_BATCH_SIZE = int(_get_env("RERANK_BATCH_SIZE", "8"))
RERANK_DEVICE = _get_env("RERANK_DEVICE", "auto")

SEPARATORS = ["\n\n", "\n", " ", "", ".", "?", "!", ",", "，", "。", "？", "！"]

DEFAULT_SESSION_ID = _get_env("DEFAULT_SESSION_ID", "user_001")

session_config = {
    "configurable": {
        "session_id": DEFAULT_SESSION_ID
    }
}

API_KEY = EMBEDDING_API_KEY
BASE_URL = EMBEDDING_BASE_URL
MODEL_EMBEDDING = EMBEDDING_MODEL
MODEL_CHAT = CHAT_MODEL
BASE_URL_CHAT = CHAT_BASE_URL
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
