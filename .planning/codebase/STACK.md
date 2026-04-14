# Technology Stack

**Analysis Date:** 2026-04-14

## Languages

**Primary:**
- Python 3.10+ - Backend API, core RAG logic, agent system, knowledge base building
- JavaScript ES2022+ - Frontend Vue 3 application

**Secondary:**
- HTML/CSS - Frontend templates and styling
- Vue SFC (Single File Component) - Frontend component structure

## Runtime

**Backend Python Runtime:**
- Python 3.11-slim (Docker) / conda environment (local development)
- Package Manager: pip with requirements.txt
- Lockfile: Not detected (pip freeze not used)

**Frontend Node Runtime:**
- Node.js 20-alpine (Docker) / Node 18+ (local dev)
- Package Manager: npm
- Lockfile: `frontend/node_modules` (package-lock.json implied by npm ci)

## Frameworks

**Backend:**
- FastAPI 0.109.0 - REST API framework with SSE streaming support
- Uvicorn 0.27.0 - ASGI server
- Pydantic 2.5.0 - Data validation

**Frontend:**
- Vue 3.4.0 - Progressive JavaScript framework
- Vite 5.0.0 - Build tool and dev server
- Vue Router 4.2.0 - SPA routing
- Pinia 2.1.0 - State management
- Element Plus 2.5.0 - UI component library
- Axios 1.6.0 - HTTP client
- Marked 18.0.0 - Markdown parsing
- KaTeX 0.16.45 - Math rendering

**Agent & RAG:**
- LangChain Core - Agent orchestration and tool definitions
- LangChain OpenAI - Embedding API client
- LangChain Ollama - Local LLM integration (optional)
- LangChain Chroma - Vector store integration
- LangGraph - Agent workflow graph (imported via langchain.agents)

**Retrieval & NLP:**
- ChromaDB - Vector database for embeddings storage
- sentence_transformers (CrossEncoder) - Reranking model
- rank_bm25 - BM25 sparse retrieval
- jieba - Chinese text segmentation
- numpy - Numerical operations

**Testing:**
- pytest 7.4.0 - Backend testing framework
- pytest-asyncio 0.21.0 - Async test support
- httpx 0.26.0 - HTTP client for testing

**Build & DevOps:**
- Docker / Docker Compose - Container orchestration
- nginx:alpine - Frontend production server

## Key Dependencies

**Critical:**
- `langchain-openai` - Embedding and chat model API calls
- `langchain-chroma` - Vector store operations
- `chromadb` - Embedding storage and retrieval
- `fastapi` - API framework
- `sse-starlette` - Server-Sent Events for streaming

**Infrastructure:**
- `python-jose` - JWT token handling (CORS middleware)
- `python-multipart` - Form data parsing
- `uvicorn` - ASGI server

**NLP/ML:**
- `sentence-transformers` - CrossEncoder reranking
- `rank-bm25` - BM25 sparse retrieval
- `jieba` - Chinese word segmentation
- `numpy` - Array operations

**Frontend UI:**
- `element-plus` - Vue 3 component library
- `katex` - LaTeX math rendering
- `marked` - Markdown to HTML

## Configuration

**Environment Variables (from `.env.example`):**
- `EMBEDDING_API_KEY`, `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL` - Embedding service
- `CHAT_MODEL`, `CHAT_BASE_URL`, `USE_REMOTE_LLM`, `REMOTE_MODEL_NAME` - LLM configuration
- `CHROMA_PERSIST_DIR`, `COLLECTION_NAME` - Vector store
- `CHUNK_SIZE`, `CHUNK_OVERLAP` - Text chunking
- `ENABLE_RERANK`, `RERANK_MODEL` - Reranking config
- `COURSE_NAME`, `COURSE_COLLECTION_NAME` - Course settings
- `DEFAULT_SESSION_ID` - Session defaults

**Key Config Files:**
- `pyproject.toml` - Python project metadata and pytest config
- `backend/requirements.txt` - Python dependencies
- `frontend/package.json` - Node dependencies
- `frontend/vite.config.js` - Vite build configuration with proxy
- `docker-compose.yml` - Container orchestration
- `backend/Dockerfile` - Backend container image
- `frontend/Dockerfile` - Frontend multi-stage build

## Platform Requirements

**Development:**
- Python 3.10+ with conda environment "RAG"
- Node.js 18+ for frontend
- Ollama (optional, for local LLM) or remote LLM endpoint
- ChromaDB persistence directory

**Production:**
- Docker and Docker Compose
- 8000/tcp for backend API
- 80/tcp for frontend (nginx)
- Persistent volumes: `chroma_db/`, `chat_history/`, `data/`

---

*Stack analysis: 2026-04-14*
