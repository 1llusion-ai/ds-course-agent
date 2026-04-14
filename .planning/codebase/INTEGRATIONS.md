# External Integrations

**Analysis Date:** 2026-04-14

## APIs & External Services

**Embedding Service:**
- SiliconFlow API (default) - Embedding generation
  - Base URL: `https://api.siliconflow.cn/v1`
  - API Key: `EMBEDDING_API_KEY` env var
  - Model: `Qwen/Qwen3-Embedding-8B` (configurable)
  - Used by: `core/rag.py`, `kb_builder/store.py`, `utils/vector_store.py`

**LLM Services:**
- **Local Ollama (default):**
  - Base URL: `http://localhost:11434` (configurable)
  - Model: `qwen3:8b` (configurable via `CHAT_MODEL`)
  - Used by: `core/agent.py` for chat completion

- **Remote API (optional):**
  - Activated when `USE_REMOTE_LLM=true`
  - Model: `Pro/deepseek-ai/DeepSeek-V3` (configurable via `REMOTE_MODEL_NAME`)
  - Same endpoint as embedding service

## Data Storage

**Vector Database:**
- ChromaDB (local filesystem)
  - Persistence: `chroma_db/` directory
  - Collection: `COLLECTION_NAME` env var (default: `rag_knowledge_base`)
  - Client: `langchain_chroma.Chroma`
  - Used by: `core/hybrid_retriever.py`, `kb_builder/store.py`, `utils/vector_store.py`

**Chat History:**
- Local filesystem storage
  - Path: `chat_history/` directory
  - Format: JSON files per session
  - Client: `utils/history.py` (FileChatMessageHistory class)
  - Used by: `core/agent.py` for session persistence

**Course Materials:**
- Local PDF/text files
  - Path: `data/` directory (configured via CLI)
  - Processed by: `kb_builder/parser.py`

## Authentication & Identity

**Session Management:**
- Custom session-based identity (no external auth provider)
- Session ID: `DEFAULT_SESSION_ID` env var (default: `user_001`)
- Stored in: File-based chat history

**CORS Configuration:**
- FastAPI CORSMiddleware
- Allowed origins: `localhost:5173`, `localhost:3000`, `localhost:5174-5176`
- All methods and headers allowed

## Monitoring & Observability

**Error Tracking:**
- Not detected - No external error tracking service (e.g., Sentry)

**Logging:**
- Print statements to stdout
- Key log points:
  - `[START]`/`[STOP]` - Service lifecycle
  - `[Agent]` - Agent decisions and skill usage
  - `[Reranker]` - Model loading and reranking
  - `[KB]` - Knowledge base operations

## CI/CD & Deployment

**Container Orchestration:**
- Docker Compose v3.8
- Services: `backend`, `frontend`
- Network: `rag-network` (bridge driver)

**Backend Deployment:**
- Dockerfile: `backend/Dockerfile`
- Base: `python:3.11-slim`
- Port: `8000`
- Health check: `curl http://localhost:8000/health`

**Frontend Deployment:**
- Multi-stage Dockerfile: `frontend/Dockerfile`
- Build: `node:20-alpine`
- Production: `nginx:alpine`
- Port: `80`

## Environment Configuration

**Required env vars:**
| Variable | Purpose | Default |
|----------|---------|---------|
| `EMBEDDING_API_KEY` | SiliconFlow API key | (required) |
| `EMBEDDING_BASE_URL` | Embedding service endpoint | `https://api.siliconflow.cn/v1` |
| `EMBEDDING_MODEL` | Embedding model name | `Qwen/Qwen3-Embedding-8B` |
| `CHAT_MODEL` | Ollama model name | `qwen3:8b` |
| `CHAT_BASE_URL` | Ollama service URL | `http://localhost:11434` |
| `CHROMA_PERSIST_DIR` | Vector store path | `chroma_db` |
| `COLLECTION_NAME` | ChromaDB collection | `rag_knowledge_base` |
| `USE_REMOTE_LLM` | Use remote vs local LLM | `false` |
| `ENABLE_RERANK` | Enable reranking | `false` |
| `RERANK_MODEL` | CrossEncoder model | `BAAI/bge-reranker-v2-m3` |

**Config Module:**
- `utils/config.py` - Centralized configuration loading from `.env`
- Uses `python-dotenv` for `.env` file loading

## Webhooks & Callbacks

**Incoming:**
- None detected - No webhook endpoints

**Outgoing:**
- SSE (Server-Sent Events) streaming at `/api/chat/send/stream`
- Frontend connects via `EventSource` API

---

*Integration audit: 2026-04-14*
