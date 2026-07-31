# Learning Routing Follow-ups

Status: deferred after the 2026-07-31 routing-convergence implementation.

The current change removes the production semantic-router LLM call, introduces
the unified `LEARNING_ANSWER` execution mode, keeps teaching style as a typed
non-authoritative hint, and prevents ambiguous learning requests from entering
the generic tool agent.

## Deferred validation and improvements

1. Run a real-model A/B benchmark comparing the previous semantic-router path
   with the unified learning-answer path. Record answer quality, groundedness,
   LLM-call count, retrieval count, and p50/p95 latency.
2. Expand optional-retrieval integration coverage for:
   - retrieval failure followed by direct-model fallback;
   - empty retrieval followed by direct-model fallback;
   - streaming fallback emitting no duplicate answer segment.
3. Calibrate which broad in-scope learning requests should use
   `RetrievalPolicy.OPTIONAL` versus `REQUIRED` using benchmark evidence rather
   than adding query-specific exceptions.
4. Run the complete test suite again after any follow-up changes. The focused
   routing/RAG suite and route harness remain the mandatory gate for each
   follow-up.
