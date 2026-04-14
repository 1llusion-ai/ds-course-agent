# Codebase Concerns

**Analysis Date:** 2026-04-14

## Tech Debt

**Hardcoded SSL Certificate Path:**
- Issue: `core/agent.py` lines 12-15 use a hardcoded Windows path `D:\Anaconda\envs\RAG\Library\ssl\cacert.pem` for SSL configuration
- Files: `core/agent.py`
- Impact: Code will fail on non-Windows systems or if Anaconda is installed in a different location
- Fix approach: Use `certifi.where()` like `apps/api/app/core_bridge.py` does (lines 12-22) - already resolved there but not in core/agent.py

**Dual Package Structures (packages/ vs root level):**
- Issue: Core functionality exists both at `core/` and `packages/rag_core/` with similar names
- Files: `core/*.py`, `packages/rag_core/*.py`, `packages/kb_pipeline/*.py`
- Impact: Confusion about which module is authoritative, potential import issues
- Fix approach: Consolidate to one location, deprecate the duplicate

**Global Mutable State in Multiple Modules:**
- Issue: Extensive use of global variables for service singletons
- Files: `core/agent.py:1152`, `core/tools.py:71`, `core/memory_core.py:388`, `core/skill_system.py:397`, `apps/api/app/state.py:210,247`, `apps/api/app/core_bridge.py:61,70`
- Impact: Difficult to test, not thread-safe, state persists across requests unexpectedly
- Fix approach: Use dependency injection or proper singleton patterns with async-safe initialization

**Duplicate RAGService Instantiation:**
- Issue: Both `core/rag.py` and `core/tools.py` create `RAGService` instances independently
- Files: `core/rag.py`, `core/tools.py`
- Impact: Multiple ChromaDB connections, inconsistent state
- Fix approach: Share single RAGService instance via `get_rag_service()` pattern

## Known Bugs

**RAGService Chain Incompatibility:**
- Issue: In `core/rag.py:106-110`, when `use_hybrid=True`, `_build_chain()` returns `None`, but the chain is still used in some code paths
- Files: `core/rag.py`
- Trigger: Calling RAGService methods when use_hybrid=True may not properly use the hybrid retriever
- Workaround: The hybrid retriever path is handled separately in `retrieve()` method

**HybridRetriever Vector Search Fails When Document Content Truncated:**
- Issue: In `core/hybrid_retriever.py:175`, comparison uses `doc.page_content[:200] == doc_text[:200]` which can cause mismatches
- Files: `core/hybrid_retriever.py:175`
- Trigger: When document content has identical first 200 characters but differ later
- Workaround: Primary matching uses full content, fallback to prefix match

**Skill Executor Import Caching:**
- Issue: `core/skill_system.py:349` caches modules by `(skill.key, relative_path)`, but if the file changes, the cached version is still used
- Files: `core/skill_system.py:365`
- Impact: Skill executors require server restart after code changes
- Workaround: Restart the server

**Chapter Start Pages Fallback to Hardcoded Values:**
- Issue: `core/tools.py:39-50` has hardcoded chapter page mappings as fallback
- Files: `core/tools.py`
- Impact: If TOC parser fails or structure changes, wrong page numbers returned
- Fix approach: Fail loudly rather than silently using incorrect defaults

## Security Considerations

**Student ID as Session ID Default:**
- Issue: In `core/agent.py:868` and `apps/api/app/routers/chat.py:166`, when student_id is not provided, session_id is used as student_id
- Files: `core/agent.py:868`, `apps/api/app/routers/chat.py:166`
- Current mitigation: Session isolation depends on session_id uniqueness
- Recommendations: Validate student_id format, add authentication middleware

**API Key in Environment Variables:**
- Issue: API keys stored in `.env` file (not committed per .gitignore)
- Files: `utils/config.py`, `.env`
- Current mitigation: `.env` is in `.gitignore`
- Recommendations: Use proper secrets management in production (environment-specific)

**No Input Sanitization on User Messages:**
- Issue: User messages go directly into prompts and tool invocations
- Files: `core/agent.py`, `core/tools.py`
- Risk: Prompt injection if malicious content passed as user input
- Current mitigation: LLM provides some inherent protection
- Recommendations: Add input validation/sanitization layer

**Path Traversal in Legacy Session File Loading:**
- Issue: `apps/api/app/state.py:77-79` derives file paths from session_id without validation
- Files: `apps/api/app/state.py:77-79`
- Risk: A crafted session_id could access arbitrary files
- Recommendations: Validate session_id format with `_UUID_PATTERN`

## Performance Bottlenecks

**BM25 Index Rebuild on Every HybridRetriever Init:**
- Issue: `core/hybrid_retriever.py:136-152` loads ALL documents from ChromaDB into memory for BM25 indexing on each initialization
- Files: `core/hybrid_retriever.py`
- Cause: No caching of BM25 index, rebuilt on every RAGService creation
- Impact: Slow startup, high memory usage with large knowledge bases
- Improvement path: Pre-compute and persist BM25 index

**Memory Profile Cache Never Invalidated:**
- Issue: `core/memory_core.py:68-80` caches profiles indefinitely, only invalidated on explicit save
- Files: `core/memory_core.py`
- Impact: Stale profile data served after aggregation updates
- Improvement path: Add TTL-based cache invalidation

**ChromaDB Connection Per Query:**
- Issue: `core/hybrid_retriever.py:139,159` creates new ChromaDB client on each search operation
- Files: `core/hybrid_retriever.py:139,159`
- Impact: Connection overhead on every retrieval
- Improvement path: Reuse client instance

**No Async in Core Modules:**
- Issue: All core modules (`core/agent.py`, `core/tools.py`, `core/rag.py`) use synchronous code
- Files: `core/*.py`
- Impact: Thread pool exhaustion under high load
- Improvement path: Convert to async where possible

## Fragile Areas

**Agent Service Initialization Order:**
- Files: `core/agent.py:57-71`
- Why fragile: Constructor calls `_check_ollama_connection()` which raises if Ollama unavailable, but `skill_loader.load_executor()` is called after, so skills fail to load if LLM connection fails first
- Safe modification: Separate LLM connection check from service initialization

**State Persistence Race Conditions:**
- Files: `apps/api/app/state.py:246-267`
- Why fragile: `_save_lock` is a boolean (not a proper lock), and the comment says "if saving, return immediately" - this can lose writes
- Safe modification: Use `asyncio.Lock` for async context, proper file locking for sync

**Course Schedule Parsing with Multiple Aliases:**
- Files: `core/tools.py:333-350`
- Why fragile: Day name aliases stored in dict, if a new alias is needed, code must be modified
- Safe modification: Externalize aliases to configuration

**Hardcoded Semester Start Date Logic:**
- Files: `core/tools.py:257-259`
- Why fragile: Semester start is loaded from JSON config, but calculation assumes continuous semester
- Safe modification: Add validation for date ranges

## Scaling Limits

**File-Based Chat History:**
- Current capacity: Single `backend_state.json` grows unbounded
- Limit: File size, memory when loading entire history
- Scaling path: Use database (SQLite/PostgreSQL) for chat history, implement pagination

**In-Memory Session State:**
- Current capacity: All sessions held in memory (`_chat_history` dict)
- Limit: Memory exhaustion with many/large sessions
- Scaling path: Lazy load session history from database

**Knowledge Base Chunk Storage:**
- Current capacity: ChromaDB with no sharding
- Limit: Vector search latency degrades with millions of vectors
- Scaling path: ChromaDB supports collection sharding, or migrate to dedicated vector DB

**Event Store JSONL Growth:**
- Current capacity: One JSONL file per student (`{student_id}_events.jsonl`)
- Limit: File size, read performance degrades as file grows
- Scaling path: Implement log rotation, periodic archival, or database storage

## Dependencies at Risk

**LangChain Version Pinning:**
- Risk: `langchain-core`, `langchain-openai` etc. have breaking changes between minor versions
- Impact: Upgrade could break agent/tools functionality
- Migration plan: Pin exact versions, test upgrades in isolation

**Jieba Chinese Tokenization:**
- Risk: Dictionary-based, no custom dictionary management
- Impact: Domain-specific terms may be poorly tokenized
- Mitigation: Add custom dictionary entries for course terminology

**BM25Okapi - Not Designed for Chinese:**
- Risk: Character-based tokenization may not capture semantic meaning
- Impact: BM25 retrieval quality for Chinese text suboptimal
- Migration plan: Consider Jieba-based BM25 or alternative like TF-IDF with proper Chinese preprocessing

## Missing Critical Features

**No Request Timeout Configuration:**
- Problem: No timeout on LLM calls, agent invokes, or retrieval operations
- Blocks: Production deployments, graceful degradation under load
- Priority: High

**No Rate Limiting:**
- Problem: No throttling on API endpoints
- Blocks: Abuse prevention, cost control
- Priority: Medium

**No Health Check Endpoint:**
- Problem: No `/health` or `/ready` endpoint for container orchestration
- Blocks: Kubernetes deployment, load balancer health checks
- Priority: Medium

**No Request ID / Correlation ID:**
- Problem: No way to trace a request across services
- Blocks: Debugging production issues, log correlation
- Priority: Medium

## Test Coverage Gaps

**Agent.chat() Not Fully Tested:**
- What's not tested: Retry logic paths (lines 148-210 in `core/agent.py`), stream mode fallback behavior
- Files: `core/agent.py`
- Risk: Retry/fallback logic could silently fail
- Priority: High

**Hybrid Retriever Scoring:**
- What's not tested: RRF fusion scoring, reranking threshold behavior
- Files: `core/hybrid_retriever.py`
- Risk: Incorrect ranking could produce poor results
- Priority: Medium

**Memory Core Event Parsing:**
- What's not tested: `BaseEvent.from_dict()` error handling, corrupted JSONL lines
- Files: `core/memory_core.py:53-62`
- Risk: One bad event line could crash event loading
- Priority: Medium

**Skill System Keyword Matching:**
- What's not tested: Score calculation edge cases, avoid_keywords blocking
- Files: `core/skill_system.py:291-339`
- Risk: Wrong skill selected or blocked incorrectly
- Priority: Low

**API State Persistence:**
- What's not tested: `_save_lock` race condition, concurrent session updates
- Files: `apps/api/app/state.py`
- Risk: Data loss under concurrent access
- Priority: High

---

*Concerns audit: 2026-04-14*
