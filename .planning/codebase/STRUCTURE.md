# Codebase Structure

**Analysis Date:** 2026-04-14

## Directory Layout

```
RAG_System/
├── apps/                    # FastAPI application
│   ├── api/app/             # Active API implementation
│   │   ├── main.py          # FastAPI app entry
│   │   ├── core_bridge.py   # Core module integration
│   │   ├── state.py         # Session/history persistence
│   │   ├── routers/         # API route handlers
│   │   │   ├── chat.py      # /api/chat endpoints
│   │   │   ├── profile.py    # /api/profile endpoints
│   │   │   └── sessions.py   # /api/sessions endpoints
│   │   └── schemas/         # Pydantic models
│   └── web/                 # (unused/placeholder)
├── backend/                  # Legacy API wrapper (points to apps/api/)
│   ├── app/
│   │   ├── main.py          # Re-exports apps/api/app/main.py
│   │   └── core_bridge.py    # Re-exports core_bridge
│   └── tests/
├── core/                    # Agent runtime, RAG, memory, skills
│   ├── agent.py             # AgentService + get_chat_model
│   ├── rag.py               # RAGService (retrieval + QA)
│   ├── hybrid_retriever.py  # BM25 + vector fusion
│   ├── reranker.py          # Cross-encoder reranking
│   ├── memory_core.py       # Student profile + event log
│   ├── skill_system.py       # Skill discovery + registry
│   ├── tools.py             # @tool decorated functions
│   ├── events.py            # Event type definitions
│   ├── knowledge_mapper.py   # Concept mapping
│   └── prompt.py            # System prompt loader
├── kb_builder/              # Knowledge base build pipeline
│   ├── parser.py            # PDF parsing
│   ├── chunker.py           # Text chunking
│   ├── cleaner.py           # Text cleaning
│   ├── store.py             # ChromaDB storage
│   └── toc_parser.py        # Table of contents
├── packages/                # Modular package wrappers
│   ├── rag_core/            # Core RAG package
│   │   ├── agent.py         # Re-exports core/agent.py
│   │   ├── rag.py
│   │   ├── hybrid_retriever.py
│   │   ├── memory_core.py
│   │   ├── tools.py
│   │   └── ...
│   ├── kb_pipeline/         # KB build package
│   ├── shared/              # Shared utilities package
│   │   ├── config.py        # Configuration
│   │   ├── vector_store.py  # Vector store wrapper
│   │   └── history.py       # Chat history helpers
│   └── ...
├── skills/                  # Teaching strategy skills
│   ├── learning-path/       # Learning path skill
│   │   ├── SKILL.md         # YAML frontmatter + docs
│   │   └── scripts/
│   │       └── executor.py  # Skill executor
│   ├── personalized-explanation/
│   └── misconception-handling/
├── scripts/                 # CLI and build scripts
│   ├── cli.py               # Main CLI entry
│   ├── build_kb.py          # KB build script
│   ├── rebuild_kb_full.py   # Full rebuild
│   └── run_api.py           # API runner
├── frontend/                # Vue 3 SPA
│   ├── src/
│   │   ├── main.js          # Vue entry
│   │   ├── App.vue
│   │   ├── router/          # Vue Router
│   │   ├── stores/           # Pinia stores
│   │   ├── views/            # Page components
│   │   ├── components/       # Shared components
│   │   └── utils/            # Frontend utilities
│   └── public/
├── utils/                   # Standalone utilities
│   ├── config.py
│   ├── vector_store.py
│   └── history.py
├── tests/                  # Root-level tests
├── chat_history/           # Runtime data
│   ├── backend_state.json   # Sessions + chat history
│   ├── learning_events/     # Per-student .jsonl event logs
│   └── profiles/            # Per-student .json profiles
├── data/                   # Source textbooks PDFs
├── chroma_db/              # ChromaDB persistent storage
├── main.py                 # CLI wrapper entry point
├── pyproject.toml          # Project config + pytest
└── conftest.py             # Root pytest fixtures
```

## Directory Purposes

**apps/api/app/:**
- Purpose: Active FastAPI application
- Contains: Main app, routers, schemas, state
- Key files: `main.py`, `core_bridge.py`, `state.py`, `routers/chat.py`

**core/:**
- Purpose: Agent runtime and business logic
- Contains: Agent, RAG, retrieval, memory, skills, tools
- Key files: `agent.py`, `rag.py`, `tools.py`, `skill_system.py`, `memory_core.py`

**kb_builder/:**
- Purpose: Build pipeline for knowledge base
- Contains: PDF parsing, chunking, cleaning, storing
- Key files: `parser.py`, `chunker.py`, `store.py`, `toc_parser.py`

**skills/:**
- Purpose: Pluggable teaching strategies
- Contains: SKILL.md manifests, executor scripts
- Key files: `{skill}/SKILL.md`, `{skill}/scripts/executor.py`

**scripts/:**
- Purpose: CLI commands and build/run scripts
- Key files: `cli.py`, `build_kb.py`, `run_api.py`

## Key File Locations

**Entry Points:**
- `apps/api/app/main.py`: FastAPI app factory (use this for `uvicorn`)
- `scripts/cli.py`: CLI command router (via `main.py`)
- `main.py`: Backward-compatible wrapper for CLI

**Configuration:**
- `pyproject.toml`: Project metadata, pytest config, pythonpath
- `.env`: Environment variables (API keys, model names)
- `.env.example`: Template for `.env`
- `utils/config.py`: Configuration loader (reads `.env`)

**Core Logic:**
- `core/agent.py`: `AgentService` class, `get_chat_model()`
- `core/rag.py`: `RAGService` class
- `core/hybrid_retriever.py`: `HybridRetriever`, `BM25Retriever`
- `core/memory_core.py`: `MemoryCore` class
- `core/skill_system.py`: `Skill`, `SkillRegistry`, `get_skill_loader()`
- `core/tools.py`: `@tool` functions, retrieval trace context

**API Routers:**
- `apps/api/app/routers/chat.py`: Chat send/history/stream endpoints
- `apps/api/app/routers/profile.py`: Student profile endpoints
- `apps/api/app/routers/sessions.py`: Session CRUD endpoints

**State Persistence:**
- `apps/api/app/state.py`: `_sessions`, `_chat_history`, `_save()`, `purge_session()`
- `chat_history/backend_state.json`: Persisted state file
- `chat_history/learning_events/*.jsonl`: Per-student event logs
- `chat_history/profiles/*.json`: Per-student profile snapshots

**Knowledge Base:**
- `kb_builder/store.py`: `CourseKBStore` - ChromaDB wrapper
- `chroma_db/`: ChromaDB persistent storage directories
- `kb_builder/toc_parser.py`: Textbook TOC parsing

**Testing:**
- `tests/`: Root-level pytest tests
- `backend/tests/`: Backend-specific pytest tests
- `conftest.py`: Shared pytest fixtures

## Naming Conventions

**Files:**
- Python modules: `lowercase_with_underscores.py`
- Skill directories: `kebab-case` (e.g., `learning-path`, `personalized-explanation`)
- Pydantic schemas: `PascalCase.py` with `snake_case` field names

**Classes:**
- PascalCase: `AgentService`, `RAGService`, `HybridRetriever`, `MemoryCore`

**Functions:**
- snake_case: `chat_with_history`, `stream_chat_with_history`, `get_agent_service`
- decorated `@tool` functions: `course_rag_tool`, `check_knowledge_base_status`

**Variables:**
- snake_case: `session_id`, `student_id`, `chat_history`
- Private module-level: `_rag_service`, `_memory_core`, `_sessions`

## Where to Add New Code

**New Tool (core/tools.py):**
- Add `@tool` decorated function in `core/tools.py`
- Auto-registered with `AgentService.tools` via `get_rag_tools()`
- Document with docstring for agent context

**New Skill:**
1. Create `skills/{skill-name}/` directory with `SKILL.md`
2. Add YAML frontmatter (name, description, when_to_use, allowed_tools, priority)
3. Optionally add `scripts/executor.py` for custom execution logic
4. Skill auto-discovered by `SkillRegistry` on startup

**New API Router:**
1. Create `apps/api/app/routers/{feature}.py` with `APIRouter()`
2. Define request/response Pydantic models in `schemas/{feature}.py`
3. Register in `apps/api/app/main.py`: `app.include_router({feature}.router, prefix="/api/{feature}")`

**New Package (packages/):**
1. Create `packages/{package_name}/` with `__init__.py`
2. Import and re-export from `core/` or implement new modules
3. Used for modular distribution of capabilities

**Test New Feature:**
- Add tests in `tests/test_{feature}.py` or `backend/tests/test_{feature}.py`
- Follow existing patterns from `tests/test_rag_tool.py`, `backend/tests/test_chat.py`

## Special Directories

**chat_history/:**
- Purpose: Runtime session and profile data
- Generated: Yes (at runtime)
- Committed: `backend_state.json` may be committed, `learning_events/` and `profiles/` are runtime-only

**chroma_db/:**
- Purpose: Persistent vector store
- Generated: Yes (by KB build)
- Committed: Yes (in `.gitignore` typically, but may be present)

**frontend/node_modules/:**
- Purpose: npm dependencies
- Generated: Yes (by `npm install`)
- Committed: No (in `.gitignore`)

**data/:**
- Purpose: Source PDF textbooks
- Generated: No (user-provided)
- Committed: No (in `.gitignore` typically)

---

*Structure analysis: 2026-04-14*
