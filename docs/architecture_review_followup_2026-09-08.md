# Architecture Review Follow-up

## Fixed: web answer dispatch regression

The runtime extraction removed AgentService.llm. WebResearchPolicy's selector
still checked that field and incorrectly fell back to the tool-agent chat method
without a graph_agent. Both buffered and streaming web answers could fail.

Removed the selector and made both answer paths explicitly call direct_chat.
Updated tests to mock the actual direct-model capability. New tests construct
AgentService with its real ModelRuntime and exercise sync, stream, and empty-stream
recovery with search/model I/O stubbed. They verify output, sources, history, and
absence of tool graph construction/invocation. No live external-provider answer
was verified by these tests.

Validation: 506 passed, 14 skipped, 1 existing optional reranker warning;
Ruff check/format pass; route tests 36 passed; route harness 119/119,
Unexpected RAG 0. Changes remain uncommitted.

## Fixed: Confirmed Follow-up Defects

- Knowledge-base writes publish per-collection revision tokens before/after each
  batch and collection clear, including partially failed writes. Atomic file
  replacement makes tokens visible to other processes. HybridRetriever refreshes
  its collection handle, BM25 corpus and content maps on a new revision; an RLock
  keeps each query's corpus/maps consistent. Empty corpora clear the old BM25 index.
  Retrieval cache keys use the revision captured before retrieval, not the revision
  at insertion, so a concurrent writer cannot tag an old result as new.
- Embedding cache keys bind the actual model client and model settings. Identity
  wrappers hold bounded strong references to prevent recycled object IDs from
  colliding; distinct clients intentionally do not share embeddings.
- A typed internal RouteResultEvent transports buffered handler result facts.
  The turn runner preserves degraded status and source facts from both result and
  retrieval events; the internal result event is never emitted onto SSE.
- Normal chat and continuation close query traces on cancellation. Stream workers
  explicitly close upstream iterators before releasing the operation lock.
- Clearing API history updates session count/time and persists once under the
  existing locks. ISO parsing is shared by state restoration and chat sessions.
  Continuation comparison normalizes to UTC milliseconds; legacy naive values are
  interpreted in the server's local timezone, matching historical datetime.now().
  Malformed history timestamps no longer fail the whole history request; malformed
  continuation identities still fail closed.

Validation: 517 passed, 14 skipped, 1 existing optional-reranker warning. Ruff
check/format pass; route tests 36 passed; route harness 119/119, Unexpected RAG 0.
Eleven new tests cover these repairs, including actual local Chroma collection
recreation and preservation of sources/degraded state through turn finalization.

### Operational Constraints

- Revision publication covers CourseKnowledgeBase.ingest_chunks/clear, which the
  repository build command uses. External scripts modifying Chroma directly must
  also use shared.kb_revision.knowledge_base_write(collection, directory).
- A rebuild is not an atomic snapshot transaction. In-flight reads may see an
  intermediate corpus, but its cache entries expire logically when a write ends.
- Legacy naive timestamps cannot recover the original timezone after a server
  timezone change. Preserve the server timezone when migrating historical data;
  future message-ID-based continuation can remove timestamp identity entirely.
- Corpus locking serializes retrieval calls on a HybridRetriever instance. This
  prioritizes consistent index mappings; concurrent immutable snapshots are a
  separate performance improvement if measured contention warrants them.

## Fixed: KB Refresh Operational Gaps

- Revision-triggered HybridRetriever refresh now retries a temporarily missing
  collection within a bounded window without creating collections from the
  reader. If the collection remains unavailable, it clears the stale collection
  handle, BM25 corpus and content maps, records a degraded trace/log event, and
  returns no evidence until a later write publishes the next revision.
- `scripts/repair_chroma_metadata.py` now wraps each delete-plus-add replacement
  batch in `knowledge_base_write`, so readers observe pre-write and post-write
  revisions even when the replacement add fails.

Validation: 526 passed, 14 skipped, 1 existing optional-reranker warning. Ruff
check/format pass; route tests 36 passed; route harness 119/119,
Unexpected RAG 0. Three focused regression tests cover successful refresh retry,
degraded stale-corpus clearing, and revision publication on repair failure.

## Fixed: Retrieval Semantics and Blank-Stream Replay

- Retrieval state now has two explicit facts throughout the route result, turn
  event, retrieval trace, API message and persisted history contracts:
  `retrieval_attempted` records that retrieval ran, while `used_retrieval`
  records that usable evidence entered the answer. Empty course retrieval no
  longer reports success or emits “found 0 sources”. RetrievalGuard treats an
  unsuccessful attempt as completed work and does not repeat the same expensive
  retrieval.
- API streaming no longer infers evidence use from grounded route mode, progress
  sources or metadata. The frontend consumes the typed fields and shows a small
  no-evidence/degraded notice next to the answer.
- Blank and whitespace-only streams recover inside the already selected handler
  boundary. `turn_runner` no longer calls `execute_route` a second time; source,
  attempt/use and degraded facts from the first pass survive recovery. Counter
  tests lock handler, tool, hooks and finalizer to at most one execution.
- Fresh-interpreter boundary tests use one shared src-layout subprocess helper,
  so the documented bare full-suite command works without relying on an
  inherited `PYTHONPATH`.

Validation: 531 passed, 14 skipped, 1 existing optional-reranker warning. Ruff
check/format pass for 224 files; route tests 37 passed; route harness 119/119,
Unexpected RAG 0; frontend production build passed with existing Sass and chunk
size warnings.

## Fixed: Vector-only Chroma Client Lifecycle

- `VectorStoreService` is now the single owner of the Chroma client and
  collection used by vector-only retrieval. `RAGService.retrieve()` delegates
  collection queries to that owner instead of constructing a new
  `PersistentClient` for every request.
- Initialization closes the client if LangChain vector-store construction
  fails. Explicit cleanup is idempotent and marks the service closed only after
  Chroma releases the client successfully.
- Lifecycle tests issue repeated vector-only queries against a real local
  collection and assert that Chroma's shared-system refcount does not grow;
  cleanup is asserted to release the owned entry exactly once. Adjacent hybrid
  retrieval tests remain unchanged and pass.

Validation: 533 passed, 14 skipped, 1 existing optional-reranker warning. Ruff
check/format pass for 225 files; route harness 119/119, Unexpected RAG 0. The
focused lifecycle, hybrid retrieval, context-trim and repair suites passed 26
tests.

## Fixed: Skill Discovery Invalidation and Registration Conflicts

- Skill registration now normalizes the candidate key before mutation and
  rejects collisions explicitly. Discovery builds a staged registry and only
  publishes it after every root succeeds, so a conflict cannot leave a partial
  catalog behind.
- Discovery cache validity is derived from a bounded signature of the configured
  roots, their known direct entries, candidate manifests, discovered skill
  paths and manifest content digests. Editing a same-length manifest, adding or
  deleting a skill, or activating a pre-existing dormant directory now rebuilds
  the catalog without recursively enumerating directories on stable reads.
- Source-specific clearing invalidates discovery state explicitly; the next
  access rebuilds instead of treating a manually pruned catalog as current.

Validation: 11 loader invariants and 28 adjacent skill tests passed. Ruff
check/format and `git diff --check` pass for the changed skill files.

## Fixed: Route-result and Retrieval-capture Duplication

- `agent/route_executor.py` now owns route-result construction, isolated
  retrieval capture and internal result-event wrapping. Route handlers and the
  web research pipeline no longer carry private copies of those helpers.
- `agent/result_finalizer.py` owns the single projection rule for sources,
  `retrieval_attempted`, `used_retrieval` and `degraded`. Source merging is a
  named shared retrieval operation rather than a cross-module private import.
- `turn_runner` consumes the shared builders and merger instead of maintaining
  another set of booleans and fallback result constructors. Retrieval-end
  event construction is centralized at the typed event boundary.
- Invariants cover single helper ownership, source de-duplication, blank-stream
  recovery and cancellation without a terminal result or leaked retrieval
  trace.

Validation: 60 focused route/finalizer tests passed; route tests 37 passed;
route harness 119/119, Unexpected RAG 0; repository Ruff check/format passed
for 225 files. The combined repository suite after this repair passed 542 tests
with 14 skips and the existing optional-reranker warning.

## Fixed: SSE Serialization Fail-safe

- The SSE encoder keeps the existing JSON fast path and exact frame format for
  valid payloads. If mapping materialization or JSON encoding fails, it emits a
  fixed typed error frame instead of terminating the response iterator.
- Diagnostics contain only a bounded structural path and a coarse value kind;
  arbitrary object representations and exception text are never exposed.
  Nested containers and circular references are handled at this boundary.
- Integration tests verify normal Unicode frame compatibility, safe handling of
  a nested unsupported object, and delivery of subsequent events after one bad
  frame.

Validation: 12 SSE/chat-stream integration tests passed; Ruff check/format and
`git diff --check` passed for the two directly changed files.

## Fixed: Concept-map Cache Identity

- Concept mapping no longer keys cached results by `id(mapper)`. Real
  `KnowledgeMapper` instances use a deterministic fingerprint of the graph
  content consumed by matching (concepts, aliases/policies, regex rules and
  embedding arrays), plus the result-relevant mapping and embedding-model
  configuration.
- Equivalent mapper configurations can share results; changing embedding policy
  or model configuration invalidates them. Unknown mapper/graph/model objects
  use strong-reference identity wrappers, so object-ID reuse cannot collide and
  references are released by LRU eviction or explicit cache clearing.
- The cache remains bounded and observable. Current production graph identity
  calculation was measured locally at about 4.0 ms per lookup for 136 concepts
  and 136 embedding vectors; the content check remains on the lookup path so a
  runtime graph mutation cannot silently reuse stale results.

Validation: 36 concept-mapper/cache tests passed; Ruff check/format and
`git diff --check` passed for the two directly changed files. The combined
repository suite after the SSE and concept-map repairs passed 548 tests with 14
skips and the existing optional-reranker warning; route validation remained
37/37 and 119/119 with Unexpected RAG 0.

## Final Review Closure

The utility duplication, public annotation, and current-document path-drift
items from the review are now closed. Historical reports retain their original
paths and commands with explicit stale-path mappings; current and future-facing
instructions use the post-M4 package owners.

### Utility cleanup progress

- R1 retrieval embedding timeout normalization now has one owner in
  `retrieval/timeouts.py`. Hybrid and vector/RAG retrieval callers import the
  same function; both former private copies were deleted. Parameterized tests
  preserve the existing missing, null/empty, zero/negative, valid and invalid
  configuration behavior.
- R3 short-memory `SUMMARY_MARKER` is now defined only by
  `shared/history.py`. Routing reads that owner dynamically, legacy persisted
  messages retain the same marker value, and no re-export alias remains.
- R4 model-call retries now have one typed owner in `runtime/retry.py` and one
  buffered execution loop in `runtime/model_runtime.py`. The `AgentService`
  chat model disables provider SDK retries (`max_retries=0`), while router,
  RAG, title and skill model factories retain their independent configured
  budgets. Streaming recovery consumes the same total attempt budget, occurs
  only before the first emitted token, and records 1-based retry trace events.
- R5 web-search result adaptation now has one typed owner in
  `research/models.py`. Progress events, fetch-candidate selection and the
  source index all consume `SearchResultView`; mapping/object field fallbacks
  for URL, title and publication date are no longer reimplemented in policy
  methods. The sync preparation path also reuses the same response-level
  adapters as streaming.
- R6 generic character-budget truncation now has one low-level owner in
  `shared/text.py`. Retrieval and web tools import it directly; their former
  private wrappers were deleted. Dynamic RAG markers and whitespace policy are
  parameters of the shared primitive, while metadata-preserving RAG block
  fitting, error redaction, conversation summarization and sandbox-output
  limits remain separate because their contracts differ.
- R8 teaching-skill learner ranking now has one domain owner in
  `teaching/learner_state.py`. Learning-path and personalized-explanation no
  longer sort the same snapshot independently. Recent concepts rank by last
  mention, mention count and stable concept ID; active weak spots rank by
  evidence confidence, last trigger and stable concept ID. Missing timestamps
  map to `0.0`. Memory aggregation and profile API presentation keep their
  separate ordering contracts.
- F11 was re-audited and is already covered by the earlier route-helper
  repair. In the pre-migration HEAD, `rag/route_handlers.py` and
  `rag/web_research.py` each contained equivalent `_route_result` and
  `_capture_retrieval` helpers. Both old files and all four local definitions
  are absent; current callers use `agent/route_executor.py`, while
  `agent/result_finalizer.py` remains the sole owner of retrieval fact merging.
  No additional helper or compatibility layer was added.

Validation: 40 focused retrieval tests and 43 short-memory/routing tests passed;
repository Ruff check/format passed for 227 files after R1/R3. R4 focused
validation passed 48 tests with 4 optional-dependency skips; Ruff check and
format passed for its seven directly affected files.

R5 focused validation passed 54 web policy/route/search/fetch tests; Ruff check
and format passed for the four directly affected files.

R6 focused validation passed 50 RAG/hybrid/web truncation tests with one
optional-dependency skip; Ruff check and format passed for its ten directly
affected files.

R8 focused validation passed 12 learner-state/learning-path/personalized-
explanation tests; Ruff check and format passed for the seven checked files.

F11 re-audit validation passed 81 route/finalizer/research/tool tests with one
optional-dependency skip; Ruff check and format passed for the ten checked
files. This audit required no code change.

Public annotation audit now covers the migrated agent/runtime/retrieval/
research/teaching surface. The API bridge service factories and stream entry,
agent service streams, hook results, retrieval streams, cache observers and
dynamic skill boundary have complete parameter/return annotations. Cache
observers use the public structural `shared.cache.CacheInfo` contract rather
than Python's private `functools._CacheInfo`; runtime values remain the original
`functools` cache-info objects.

Annotation-focused validation passed 27 API/routing/runtime/cache tests; Ruff
check and format passed for the twelve checked files. The scoped AST audit found
no remaining missing public parameter or return annotations in the migrated
packages; Protocol declarations and private helpers were intentionally excluded.

### Rollout-blocker re-audit

- History clearing now participates in the per-session operation lock, so it
  cannot delete a continuation target while its stream worker is replacing it.
  The worker also publishes an unpersisted terminal error if any final history
  mutation fails, guaranteeing that SSE replay terminates.
- Blank and whitespace-only streams were already recovered inside the selected
  handler boundary. The recovery path now also invokes the observation-only
  `after_stream_end` hook without replaying routing, tools, or finalization.
- Hybrid retrieval installs corpus generations atomically and takes an immutable
  reference snapshot under the corpus lock. Embedding and vector queries run
  after releasing that lock, so unrelated sessions are not serialized on the
  remote embedding call.
- One `ingest_chunks` operation now owns one knowledge-base revision window
  across all Chroma batches. Empty retrieval results are not cached, and cache
  identity includes embedding and reranker configuration.
- Web page fetch no longer catches arbitrary internal `TypeError` and retries
  through an unbudgeted legacy signature. Pending fetch futures are cancelled;
  already-running HTTP work remains bounded by the fetch request timeouts.
- Synchronous chat projection now handles non-mapping agent results without
  unguarded `.get()` calls.

Historical progress logs intentionally retain paths from their original stage;
current entrypoint documentation uses the migrated paths. The final repository
gate passed on 2026-09-08: 596 tests passed, 14 skipped, with one existing
optional-reranker warning; Ruff check passed and 233 files passed format check;
route tests passed 37/37; route harness passed 119/119 with Unexpected RAG 0;
the frontend production build passed with the existing Sass deprecation and
chunk-size warnings.
