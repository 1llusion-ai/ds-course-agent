# Architecture

**Analysis Date:** 2026-04-14

## Pattern Overview

**Overall:** Layered FastAPI + LangGraph Agent architecture with skill-based teaching strategies

**Key Characteristics:**
- FastAPI backend serves as API gateway with session/chat/profile management
- `core/` module contains agent runtime with LangGraph-based ReAct agent
- Skills system (`skills/`) provides pluggable teaching strategies via SKILL.md manifests
- RAG pipeline for retrieval-augmented generation with BM25 + vector hybrid search
- Memory core tracks student learning events and profiles

## Layers

**API Gateway (apps/api/):**
- Purpose: HTTP API entry point, request routing, session management
- Location: `apps/api/app/`
- Contains: FastAPI routers, Pydantic schemas, chat state persistence
- Depends on: `core/` modules via `core_bridge.py`
- Used by: `frontend/` (Vue 3 SPA)

**Core Bridge (apps/api/app/core_bridge.py):**
- Purpose: Decouple core modules from FastAPI, lazy initialization of singletons
- Location: `apps/api/app/core_bridge.py`
- Contains: `get_agent_service()`, `get_memory_core()`, `chat_with_history()`, `stream_chat_with_history()`
- Depends on: `core/`
- Used by: `apps/api/app/routers/`

**Agent Runtime (core/):**
- Purpose: Main business logic - agent loop, RAG retrieval, memory, skills
- Location: `core/`
- Contains:
  - `agent.py`: `AgentService` (LangGraph ReAct agent), `get_chat_model()`
  - `rag.py`: `RAGService` (retrieval + QA generation)
  - `hybrid_retriever.py`: BM25 + vector fusion with `HybridRetriever`
  - `reranker.py`: Cross-encoder reranking
  - `memory_core.py`: Student profile and learning event storage
  - `skill_system.py`: `Skill`, `SkillRegistry`, skill loader
  - `tools.py`: `@tool` decorated RAG/schedule tools, retrieval tracing
  - `events.py`: Event types (clarification, mastery signals, concept mentions)
  - `knowledge_mapper.py`: Concept mapping and knowledge graph
- Depends on: `utils/`, `kb_builder/`, `packages/shared/`
- Used by: `apps/api/app/core_bridge.py`

**Knowledge Base Pipeline (kb_builder/):**
- Purpose: Parse PDF textbooks, build chunked/split content, populate vector store
- Location: `kb_builder/`
- Contains: `parser.py`, `chunker.py`, `cleaner.py`, `store.py`, `toc_parser.py`
- Depends on: `utils/vector_store.py`, `core/reranker.py`
- Used by: `scripts/build_kb.py`

**Utilities (utils/):**
- Purpose: Shared infrastructure - config, vector store wrapper, chat history
- Location: `utils/`
- Contains: `config.py`, `vector_store.py`, `history.py`
- Used by: `core/`, `kb_builder/`

**Skills (skills/):**
- Purpose: Pluggable teaching strategies with YAML frontmatter + optional Python executors
- Location: `skills/{skill-name}/`
- Contains: `SKILL.md` (YAML frontmatter + strategy doc), `scripts/executor.py`
- Skill examples: `learning-path/`, `personalized-explanation/`, `misconception-handling/`
- Depends on: `core/skill_system.py`, `core/`
- Used by: `core/agent.py` via `AgentService.skill_loader`

## Data Flow

**Chat Request Flow:**

1. `frontend` sends POST to `POST /api/chat/send` or GET `/api/chat/send/stream`
2. `apps/api/app/routers/chat.py` receives `ChatRequest`
3. Calls `core_bridge.chat_with_history()` or `stream_chat_with_history()`
4. `core_bridge.py` delegates to `core.agent.AgentService.chat_with_history()`
5. `AgentService` invokes LangGraph agent with user input + history
6. Agent may call `course_rag_tool` (from `core/tools.py`)
7. `course_rag_tool` calls `RAGService.retrieve()` -> `HybridRetriever.retrieve()`
8. Results flow back through layers to frontend as JSON or SSE stream

**Session/Profile Flow:**

1. Sessions stored in `chat_history/backend_state.json` via `apps/api/app/state.py`
2. Learning events recorded via `core.memory_core.record_event()`
3. Profile aggregation via `core.memory_core.aggregate_profile()`
4. Profile endpoints in `apps/api/app/routers/profile.py` read from memory core

**Skill Execution Flow:**

1. `AgentService` loads skills via `get_skill_loader().load_executor("skill-name")`
2. Skills triggered by keywords in user input or system prompt guidance
3. Executor scripts in `skills/*/scripts/executor.py` can read student profile

## Key Abstractions

**AgentService (core/agent.py):**
- Purpose: Single-agent orchestration with tool binding and skill loading
- Examples: `core/agent.py`
- Pattern: Singleton via `get_agent_service()`, LangChain `create_agent()`

**RAGService (core/rag.py):**
- Purpose: Retrieval-augmented question answering with history
- Examples: `core/rag.py`
- Pattern: LangChain `RunnableWithMessageHistory` with custom prompt template

**HybridRetriever (core/hybrid_retriever.py):**
- Purpose: Combine BM25 sparse + vector dense retrieval via rank fusion
- Examples: `core/hybrid_retriever.py`
- Pattern: RR (Reciprocal Rank) fusion, optional reranking with cross-encoder

**MemoryCore (core/memory_core.py):**
- Purpose: Append-only event log + profile aggregation
- Examples: `core/memory_core.py`
- Pattern: JSONL event log per student, cached in-memory profiles

**Skill + SkillRegistry (core/skill_system.py):**
- Purpose: Discover and execute teaching strategies from `skills/` directory
- Examples: `skills/learning-path/SKILL.md`, `skills/personalized-explanation/SKILL.md`
- Pattern: YAML frontmatter parsed by `skill_system.py`, optional `executor.py` script

## Entry Points

**API Entry:**
- Location: `apps/api/app/main.py`
- Triggers: `uvicorn apps.api.app.main:app` or `python main.py api`
- Responsibilities: FastAPI app setup, CORS middleware, router inclusion

**Legacy API Entry:**
- Location: `backend/app/main.py` (wrapper around `apps/api/app/main.py`)
- Triggers: `python backend/app/main.py`
- Responsibilities: Backward compatibility wrapper

**CLI Entry:**
- Location: `scripts/cli.py` (imported by `main.py`)
- Triggers: `python main.py <command>` or `python -m scripts.cli <command>`
- Responsibilities: Route to `build`, `eval`, `test`, `api` commands

**KB Build Entry:**
- Location: `scripts/build_kb.py`
- Triggers: `python main.py build [data/]`
- Responsibilities: Parse PDFs, chunk, clean, store to ChromaDB

## Error Handling

**Strategy:** Fallback responses with error messages propagated through layers

**Patterns:**
- Agent errors caught in `core_bridge.chat_with_history()` - returns friendly fallback text
- Stream errors caught in `stream_chat_with_history()` - yields error event then final
- HTTP errors raised via `HTTPException` in FastAPI routers
- Retrieval failures handled by `_track_retrieval()` with empty sources

## Cross-Cutting Concerns

**Logging:** `print()` statements scattered in modules (no structured logging framework)

**Validation:** Pydantic schemas for API request/response in `apps/api/app/schemas/`

**Authentication:** Student ID passed via request params, checked against session ownership

**CORS:** Configured in `apps/api/app/main.py` with hardcoded localhost origins

---

*Architecture analysis: 2026-04-14*
