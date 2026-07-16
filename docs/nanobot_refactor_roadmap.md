# Nanobot-Inspired Refactor Roadmap and Progress Log

Last updated: 2026-07-15

This document records the agreed local plan for borrowing engineering mechanisms
from `nanobot` while preserving this project's core course-agent architecture.
Update the **Progress Log** whenever a roadmap item is completed or materially
changed.

## Non-negotiable boundaries

- Do **not** replace or weaken `QueryPipeline` (`Preprocessor -> Rewriter -> Router`).
- Do **not** replace the `LearningEvent` domain model.
- Do **not** convert the Vue frontend to React.
- Do **not** import nanobot's generic-agent surface wholesale:
  `MessageBus`, `channels`, MCP management, multi-provider UI, voice features,
  CLI app integrations, and generic templates are out of scope.
- Prefer staged, testable changes over large rewrites.

## What to learn from nanobot

1. **Tool contracts and registry**
   - Add metadata such as `read_only`, `side_effect`, `concurrency_safe`,
     `exclusive`, and `cost_class`.
   - Use metadata later for safe parallelism and UI tool progress.

2. **Context governance**
   - Enforce context budgets from estimated tokens, not message counts.
   - Check both before a turn and before each LLM call.
   - Keep summary as marked `SystemMessage`; do not pretend old context never
     existed.

3. **Tool result normalization/offload**
   - Large tool outputs should be persisted under `var/artifacts/tool_results/`.
   - LLM-visible messages should contain compact placeholders/references.
   - First version may only record warnings and trace fields before automatic
     replacement is enabled.

4. **Atomic session/history writes**
   - Write to temporary files and use `os.replace`.
   - Add per-session locks for concurrent FastAPI requests.

5. **Typed streaming events**
   - Upgrade SSE events from only `delta/final` toward
     `progress`, `delta`, `stream_end`, and `turn_end`.
   - Keep WebSocket as a later option, not a first-step dependency.

6. **Markdown and code rendering UX**
   - Add sanitizer, code highlighting, copy button, route/source/latency badges.

## Final execution order

1. **Condition RetrievalGuard**
   - Avoid automatic second RAG on optional/generic routes.
   - Trigger forced grounding only when policy requires it and retrieval was not
     used.

2. **Latency harness and query trace report**
   - Use fixed queries and existing `query_trace.py`.
   - Track total latency, TTFB, route, retrieve/rerank/LLM spans, forced RAG
     rate, source count, and empty responses.

3. **ContextGovernor**
   - Pre-turn check: `system_prompt + old_history + current_user_message`.
   - Pre-LLM check: every actual LLM call, especially after tool results.
   - Use `CHAT_SUMMARY_MODEL`/cheap summary model if available; fallback to the
     existing deterministic extractive summary.

4. **History durability**
   - Write user message before the LLM call.
   - Preserve current-turn message construction as
     `old_history + HumanMessage(current_input)`.
   - Use atomic writes and per-session locking.

5. **Tool result normalization/offload**
   - Add size thresholds, artifact paths, trace logging, and warning-only mode.
   - Later enable automatic replacement of old large tool results.

6. **SSE progress events**
   - Emit progress phases: routing, preparing context, retrieving, generating,
     postprocessing.
   - Reserve `stream_id`/`resuming` fields for future multi-segment turns.

7. **Small caches**
   - Add in-process cache for normalized query, concept mapping, and other pure
     deterministic steps where safe.

8. **Tool registry and metadata**
   - Split `rag/tools.py` gradually.
   - Use a lightweight registry/dataclass first, not a large abstract framework.

9. **Hooks plus route handlers**
   - Define lifecycle events:
     - `before_route(state)`
     - `after_route(state, decision)`
     - `before_llm(messages)`
     - `after_llm(result)`
     - `after_tool(name, result)`
     - `after_turn(state, result)`
     - `on_session_end(session_id)`
   - Move `LearningEventHook`, `RetrievalGuardHook`, and
     `ClarificationDetectorHook` out of `AgentService`.
   - Move route execution from `if/elif` into route handler classes in the same
     refactor wave.

10. **Pydantic config and shared LLM factory**
    - Introduce `shared/config/schema.py` and `shared/config/loader.py`.
    - Preserve existing module-level aliases for compatibility.
    - Move duplicated `get_chat_model()` into `shared/llm.py`.

11. **Frontend polish**
    - Add DOMPurify, code highlighting, code-copy buttons, route badges, source
      chips, latency badges, and progress timeline.

12. **Later advanced work**
    - WebSocket multiplexing if needed.
    - Dream-lite profile consolidation.
    - Subagent-style code review sandbox for complex code-analysis flows.

## Initial validation targets

- `python -m pytest tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py -q`
- API streaming tests after SSE changes:
  `python -m pytest tests/integration/api/test_chat_stream.py -q`
- Frontend build after UI changes:
  `cd web && npm run build`

## Progress Log

| Date | Item | Status | Evidence / Notes |
| --- | --- | --- | --- |
| 2026-07-15 | Roadmap recorded locally | Done | Created this file. |
| 2026-07-15 | Condition RetrievalGuard | Done | Added `AgentService._retrieval_guard_skip_reason()` and trace events `retrieval_guard.skip` / `retrieval_guard.force`; added regression test for `GENERIC_AGENT + optional` skipping forced RAG. Validation: `python -m pytest tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py -q` -> 44 passed, 1 warning. |
| 2026-07-15 | Latency harness scaffold | Done | Subagent `Kepler` added `benchmarks/latency_harness.py`. Reviewed locally. Validation: `python -m py_compile benchmarks/latency_harness.py` -> pass; `python benchmarks/latency_harness.py --help` -> pass; `python benchmarks/latency_harness.py --limit 0 --output /tmp/latency_harness_report.json` -> pass and writes a zero-query report without LLM/RAG calls. |
| 2026-07-15 | ContextGovernor/tool-result insertion audit | Done | Subagent `Pascal` completed read-only audit. Key insertion points confirmed: pre-turn in `AgentService._prepare_query_route`, pre-LLM via model wrapper in `_create_agent`, large tool-result warnings at tool return boundaries, RAG context boundary in `RAGService.retrieve`, and persistence warning in `FileChatMessageHistory.add_messages`. |
| 2026-07-15 | ContextGovernor warning-only v1 | Done | Added `shared/context_governor.py` with heuristic token estimation and warning-only trace/log events. Inserted checks at `AgentService._prepare_query_route`, `AgentService.chat` before LLM calls, and `FileChatMessageHistory.add_messages`. Validation: `python -m py_compile src/ds_course_agent/shared/context_governor.py src/ds_course_agent/rag/agent.py src/ds_course_agent/shared/history.py` -> pass; `python -m pytest tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py tests/test_short_term_memory.py tests/test_context_governor.py tests/test_agent_smoke.py -q` -> 78 passed, 4 skipped, 1 warning. |
| 2026-07-15 | History durability | Done | `FileChatMessageHistory` now uses per-session `threading.RLock` and temp-file + `os.replace` atomic JSON writes. `chat_with_history` and `stream_chat_with_history` persist `HumanMessage` before LLM/route execution, then append only the assistant response. Validation: `python -m py_compile src/ds_course_agent/shared/history.py src/ds_course_agent/rag/agent.py` -> pass; `python -m pytest tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py tests/test_short_term_memory.py tests/test_context_governor.py tests/test_agent_smoke.py -q` -> 81 passed, 4 skipped, 1 warning. |
| 2026-07-15 | Tool/RAG large payload warning-only telemetry | Done | Added `warn_if_large_text_payload()` and inserted warning-only checks at `course_rag_tool`, `python_exec_tool`, schedule/datetime/status tools, `RAGService.retrieve`, `RAGService.answer_with_context`, and `RAGService.stream_answer_with_context`. No content is replaced/offloaded yet. Validation: `python -m py_compile src/ds_course_agent/shared/context_governor.py src/ds_course_agent/rag/tools.py src/ds_course_agent/rag/rag.py` -> pass; `python -m pytest tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py tests/test_short_term_memory.py tests/test_context_governor.py tests/test_agent_smoke.py tests/test_rag_tool.py -q` -> 95 passed, 5 skipped, 1 warning. |
| 2026-07-15 | Structured LLM error classification + backoff | Done | Replaced scattered string matching in `AgentService.chat()` with retryable/permanent/degradable classification. Retryable errors use exponential backoff 1s/2s/4s; 401/402/auth/billing errors do not retry; 400/bad request degrades to basic RAG fallback. `CHAT_MAX_RETRIES` default changed to 2. Validation: `python -m py_compile src/ds_course_agent/rag/agent.py src/ds_course_agent/shared/config.py` -> pass; `python -m pytest tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py tests/test_short_term_memory.py tests/test_context_governor.py tests/test_agent_smoke.py tests/test_rag_tool.py -q` -> 98 passed, 5 skipped, 1 warning. |
| 2026-07-15 | SSE progress events | Done | Streaming now emits `progress` events for routing/context/retrieval/generation/postprocess, and includes reserved `stream_id`/`resuming` fields on progress/delta events. API router forwards progress SSE events; Vue store records progress on pending assistant messages and `ChatMessage` displays the current phase. Validation: `python -m py_compile src/ds_course_agent/rag/agent.py src/ds_course_agent/api/core_bridge.py src/ds_course_agent/api/routers/chat.py` -> pass; `python -m pytest tests/test_agent_grounded_fallback.py tests/test_query_pipeline.py tests/test_short_term_memory.py tests/test_context_governor.py tests/test_agent_smoke.py tests/test_rag_tool.py tests/test_core_bridge_trace.py tests/integration/api/test_chat_stream.py -q` -> 102 passed, 5 skipped, 1 warning; `cd web && npm run build` -> pass. |
| 2026-07-15 | Real latency baseline | Done | Ran `python benchmarks/latency_harness.py --limit 20` with network access. Report path: `var/artifacts/benchmarks/latency_harness_report.json` (gitignored). Summary: 20/20 completed, 0 errors, p50 `16075.444 ms`, p95 `125785.697 ms`, max `149079.176 ms`, avg `30244.96 ms`; routes: `grounded_rag=19`, `generic_agent=1`; retrieval rate `95%`; avg sources `2.4`; `agent_force_grounded_count=17`, `retrieval_guard_force_count=17`. Slowest: `multi_003#turn1` `149079 ms`, `multi_002#turn2` `124560 ms`. |
| 2026-07-15 | Phase 1 review fixes | Done | Addressed six review findings: stream pre-delta retry now falls back to blocking `invoke`, Ollama error classification is limited to connectivity failures, generic optional streaming yields real agent chunks directly, duplicate `chat()` context-budget warning was removed, retrieval guard trace now distinguishes `force` from `force_empty`, and atomic write failure semantics are documented. Validation: `python -m py_compile src/ds_course_agent/rag/agent.py src/ds_course_agent/shared/history.py` -> pass; `python -m pytest tests/test_agent_smoke.py tests/test_query_pipeline.py -q` -> 73 passed, 4 skipped, 1 warning; broader Phase 1 set -> 104 passed, 5 skipped, 1 warning; full suite -> 275 passed, 6 skipped, 2 warnings. |
| 2026-07-15 | Phase 2 latency slice 1 | Done | Grounded RAG sync route now bypasses generic-agent LLM and calls `course_rag_tool` directly with the rewritten grounded query; RetrievalGuard skips already-executed grounded results. Added in-process LRU caches for query normalization and `map_question_to_concepts` with `QUERY_CACHE_ENABLED` / `QUERY_CACHE_SIZE`. Validation: py_compile passed; `tests/test_query_cache.py tests/test_knowledge_mapper.py tests/test_query_pipeline.py -q` -> 65 passed, 1 warning; broader Phase 1/2 set -> 127 passed, 5 skipped, 1 warning; full suite -> 277 passed, 6 skipped, 2 warnings. Real harness smoke `--limit 5`: p50 `5008.289 ms`, p95 `12458.089 ms`, avg `6788.235 ms`, force counts 0. |
| 2026-07-15 | Phase 2 tool registry metadata | Done | Added `src/ds_course_agent/tools/registry.py` with lightweight `ToolSpec` / `ToolRegistry` metadata (`read_only`, `side_effect`, `concurrency_safe`, `cost_class`, `progress_label`, `expose_to_agent`, `result_policy`). `AgentService` now derives `self.tools` from one registry source; `record_misconception_event` is registered but not exposed to the generic agent. QueryPipeline `required_tools` now use registry names, and SSE progress events pass through `tool`. Validation: py_compile passed; `tests/test_tool_registry.py -q` -> 6 passed, 1 warning; affected paths -> 110 passed, 5 skipped, 1 warning; full suite -> 283 passed, 6 skipped, 2 warnings. |
| 2026-07-15 | Phase 2 tool/RAG result artifacts | Done | Added `shared/tool_result_store.py` to persist large tool/RAG payload snapshots under `var/artifacts/tool_results/` with JSON sidecar metadata and `tool_result.artifact` trace events. Existing tool/RAG outputs remain inline for now; this is the safe precursor to future placeholder compaction. Added `TOOL_RESULT_ARTIFACTS_ENABLED`, `TOOL_RESULT_ARTIFACT_DIR`, and `TOOL_RESULT_INLINE_MAX_CHARS`. Validation: py_compile passed; `tests/test_tool_result_store.py tests/test_context_governor.py tests/test_rag_tool.py -q` -> 21 passed, 1 skipped, 1 warning; affected paths -> 101 passed, 5 skipped, 1 warning; full suite -> 286 passed, 6 skipped, 2 warnings. |
| 2026-07-15 | Phase 2 hooks + route handlers skeleton | Done | Added `hooks/HookManager` lifecycle methods and `RetrievalGuardHook`; extracted `_execute_route` if/elif body into first-match route handlers in `rag/route_handlers.py`. `AgentService` now dispatches through handlers and applies retrieval guard as an `after_llm` hook, while preserving existing QueryPipeline/LearningEvent behavior and monkeypatch-compatible private methods. Validation: py_compile passed; targeted -> 80 passed, 4 skipped, 1 warning; affected paths -> 109 passed, 5 skipped, 1 warning; full suite -> 291 passed, 6 skipped, 2 warnings. |
