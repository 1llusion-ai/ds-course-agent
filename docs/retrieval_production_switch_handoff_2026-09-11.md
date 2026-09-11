# Retrieval Production Switch Handoff

Date: 2026-09-11

Status: chunk, embedding, retrieval, and context experiments are complete.
Production code, `.env`, and active `var/chroma_db` are unchanged.

## 1. Objective For The Next Agent

Implement and validate the production migration to the selected retrieval
stack:

1. `fine_700_140` semantic chunks.
2. `Qwen/Qwen3-Embedding-8B`, provider-native 4096 dimensions, cosine distance.
3. Raw vector ranking with no query instruction, BM25 routing, RRF, or reranker.
4. Retrieve a Top-10 candidate pool.
5. Preserve vector rank while removing exact source-interval overlap.
6. Assemble retrieved context under a 4096-token budget, subject to full-prompt
   validation against the serving model.
7. Build and test everything against a new isolated production-shaped index.
8. Switch the active index only after explicit user approval and a verified
   rollback path.

This is an internal retrieval/module change. It is not a new tool or skill.

## 2. Required Reading

Read these before editing code:

- `AGENTS.md`
- `docs/architecture_reorg_plan.md`
- `docs/capability_model.md`
- `docs/nanobot_refactor_roadmap.md`
- `docs/phase1_backbone_contracts.md`
- `docs/kb_rebuild_evaluation_handoff_2026-09-10.md`
- `docs/retrieval_chunk_embedding_selection_2026-09-10.md`
- `docs/retrieval_strategy_selection_2026-09-10.md`
- `docs/retrieval_context_selection_2026-09-11.md`

Repository branch at handoff: `feat/retrieval-evidence-gold`.

The working tree is intentionally very dirty and contains the complete parsing,
gold-label, candidate-index, and evaluation work. Do not revert, reset, or
rewrite unrelated files. Do not assume untracked files are disposable.

## 3. Frozen Decisions

### Chunk And Embedding

- Candidate: `fine_700_140`
- `chunk_size=700`
- `chunk_overlap=140`
- ordinary hard maximum `900`; complete atomic formula units may exceed it
- 313 semantic chunks
- all 86 reviewed formula/table/code atomic units remain intact
- embedding model: `Qwen/Qwen3-Embedding-8B`
- native vector dimension: 4096
- distance: cosine

Qwen-1024 and BGE-M3 were worse. Do not reopen embedding selection on the
observed dev/test families.

### Retrieval

- Keep raw vector retrieval.
- Do not implement `adaptive_exact_lookup`.
- Do not implement BM25/vector RRF.
- Do not add Qwen query instructions.
- Do not enable `BAAI/bge-reranker-v2-m3`.
- Do not use MMR for context ordering.

The unseen strategy test showed no quality benefit from BM25 routing, RRF, or
BGE reranking. MMR later regressed `ret-0010` on dev.

### Context

- Candidate depth: Top-10.
- Preserve raw vector rank.
- De-duplicate only exact source-page character intervals already included.
- Never treat semantically similar text on different pages or intervals as a
  duplicate.
- Benchmark budgets: 2048 and 4096 tokens.
- Selected production target: 4096 retrieved-context tokens, conditional on
  measuring the complete production prompt.

At 2048 tokens, exact interval de-duplication improved test quality completion
from `(0.818, 0.818)` to `(0.909, 0.909)` with no regression. At 4096 tokens,
both independent annotations reached complete evidence on every quality-gate
dev and test query.

`ret-0053` is the key diagnostic. Its required source-page-119 evidence appears
at vector rank 7. It remains incomplete at 2048 tokens and becomes complete at
4096 tokens. Source de-duplication alone does not fix it.

## 4. Authoritative Artifacts

Use these exact artifacts:

- Selected chunk bundle:
  `var/chroma_candidates/chunk_eval_20260910/fine_700_140/chunks.json`
- Selected candidate index manifest:
  `var/chroma_candidates/chunk_eval_20260910/fine_700_140/indexes/qwen3_8b_native/index_manifest.json`
- Selected candidate Chroma directory:
  `var/chroma_candidates/chunk_eval_20260910/fine_700_140/indexes/qwen3_8b_native/chroma`
- Candidate collection:
  `retrieval_fine_700_140_qwen3_8b_native`
- Evidence panel v2:
  `benchmarks/data/retrieval_evidence_panel_v2.json`
  SHA-256 `8997d96f7a595fbfd058accb9355c2b1668299b05e9595432ac6ca423c6081b3`
- Context dev matrix:
  `benchmarks/data/retrieval_context_candidates_v1.json`
  SHA-256 `48fcd3a636923c56afafac1633204b3fd2f998366bf5e0e07b1162151ff6eb9c`
- Context finalist matrix:
  `benchmarks/data/retrieval_context_finalists_v1.json`
  SHA-256 `e175e065bf0c36ee08a033bdba080435cb7248466c1d9902ab4772df4b4a9f60`
- Final context dev report:
  `var/artifacts/kb_eval/retrieval_context_20260911/context_dev_v2.json`
  SHA-256 `500ec50f6e2b47a81eab34162a5a677fbf45f2c2bd0e4dbd36d0f06901931c5a`
- Final context test report:
  `var/artifacts/kb_eval/retrieval_context_20260911/context_test_v2_final.json`
  SHA-256 `2fe70a3113e47955ffd0c9ec18d8b22b26e64f334e1fb2bcaeaa170419ec84e2`

Do not use these two early reports; they were generated before the final context
report schema cleanup:

- `var/artifacts/kb_eval/retrieval_context_20260911/context_dev.json`
- `var/artifacts/kb_eval/retrieval_context_20260911/context_test_v2.json`

## 5. Critical Metadata Hazard

The benchmark and production code currently use similar names for different
concepts:

- `CandidateChunk.source_start/source_end` are exact Unicode code-point offsets
  within one frozen source page.
- Local variables named `source_start/source_end` in
  `src/ds_course_agent/kb/store.py` are page numbers used to populate
  `source_page_start/source_page_end`.

Current `ChunkMetadataV2` and normal production ingestion do not carry exact
page-local character intervals. Do not confuse page ranges with text offsets.
Doing so would silently delete unrelated content.

Introduce an explicit production provenance contract, preferably with
unambiguous names such as:

- `source_id`
- `source_page`
- `book_page`
- `source_char_start`
- `source_char_end`
- `content_sha256`

Use a typed dataclass/model at the module boundary and project it to Chroma's
scalar metadata dictionary only at ingestion. Do not use metadata dictionary
keys as hidden control signals.

The production context assembler must fail clearly when the selected production
index lacks this provenance. Do not add a fuzzy-text or page-only compatibility
fallback.

## 6. Recommended Index Migration

Do not run the existing rebuild scripts blindly:

- `scripts/rebuild_kb_full.py` is chapter-PDF oriented and defaults to
  `1300/300`.
- `scripts/build_kb.py` currently invokes chunker defaults rather than the
  frozen `700/140/900` configuration.
- `src/ds_course_agent/shared/config/schema.py` still defaults to the BGE
  embedding model.

The safest migration is to promote the exact tested candidate without
re-chunking or re-embedding:

1. Read and hash-validate the selected candidate bundle and index manifest.
2. Read IDs, documents, embeddings, and metadata from the tested candidate
   collection.
3. Create a fresh directory under `var/chroma_candidates/`, never directly in
   `var/chroma_db`.
4. Create a production-shaped collection using the exact tested IDs,
   documents, and embeddings.
5. Enrich metadata from the candidate bundle with the production fields needed
   by citations, cache revision, and exact source-interval assembly.
6. Emit a typed promotion manifest containing source hashes, source collection,
   destination collection, document count, vector dimension, model identity,
   metadata schema version, code revision, and build time.
7. Verify all 313 IDs, document hashes, vectors/dimensions, and provenance
   intervals before considering a switch.

This approach avoids provider drift and guarantees that production uses the
same chunks and vectors that won the evaluation. Do not copy or mutate the
candidate Chroma directory in place.

The selected candidate collection already contains basic `source_id`, page,
character-offset, chapter, and section metadata, but it is not a complete
production metadata contract. Audit and enrich it in the isolated destination.

## 7. Recommended Context Module

Create a normal retrieval module, for example
`src/ds_course_agent/retrieval/context_assembler.py`. Keep it independent from
agent orchestration and tools.

Suggested typed contracts:

- `SourceInterval`
- `RankedContextCandidate`
- `ContextAssemblyConfig`
- `SelectedContextFragment`
- `AssembledContext`

Required behavior:

1. Consume documents in vector rank order.
2. Validate source ID, page, and exact character interval.
3. Subtract the union of already selected intervals on the same source page.
4. Preserve all remaining disjoint fragments in original source order.
5. Include compact citation/page headers in token accounting.
6. Stop before adding a block that would exceed the budget.
7. Return the formatted context, selected documents/fragments, token usage,
   duplicate characters removed, and overflow diagnostics through typed fields.

The deterministic interval subtraction and evaluator reference implementation
is in `benchmarks/evaluate_retrieval_context.py`. Reuse the algorithmic contract,
but do not make production import from `benchmarks/`.

Do not add MMR, similarity-based duplicate detection, fuzzy string deletion, or
query-specific exceptions.

## 8. RAG Service Integration

Current production behavior is in
`src/ds_course_agent/retrieval/service.py`:

- default `SIMILARITY_TOP_K=3`
- query asks Chroma for `max(k * 3, 10)` and returns only `k`
- `_format_documents()` uses a 4500-character total budget
- each document has a 1500-character cap
- once one document is fitted or dropped, lower-ranked documents are ignored

Replace the old character-only assembly path rather than leaving parallel old
and new implementations. Update all callers and tests in the same change; do
not leave an indefinite compatibility shim.

Integration requirements:

- Default candidate depth becomes 10.
- Context is assembled once through the new typed module.
- `RetrievalResult.documents` and displayed sources must correspond to evidence
  actually included in the assembled context, not every discarded candidate.
- Keep raw vector ranking and the existing similarity threshold semantics.
- Update the retrieval cache key to include candidate depth, token budget,
  tokenizer/policy version, de-duplication mode, collection revision, and
  embedding identity.
- Clear or naturally invalidate old in-process cache entries after the policy
  changes.
- Keep retrieval/context telemetry, but rename character-only fields where the
  semantics become token based.

Do not move this logic into `agent/service.py`, prompts, or the course RAG tool.

## 9. Configuration Migration

Production query embeddings must exactly match the selected index:

- `EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B`
- native 4096-dimensional responses
- same provider/base URL behavior used by the candidate build
- no query prefix/instruction

The current schema default is `BAAI/bge-large-zh-v1.5`; serving the Qwen index
with that query model is invalid even if Chroma accepts the request shape.

Replace the character budget configuration with an explicit token contract if
the implementation fully migrates to token accounting. Do not retain unused
`RAG_CONTEXT_MAX_CHARS` or `RAG_CONTEXT_DOC_MAX_CHARS` settings after all callers
have migrated.

Before fixing 4096 as the production value, measure the complete prompt:

- system instructions
- selected retrieved context including headers
- relevant chat history
- current user message
- reserved answer tokens (`RAG_ANSWER_MAX_TOKENS=768` currently)

The runtime context window currently defaults to 8192 tokens. The benchmark
uses `cl100k_base`; the serving model is Qwen, so record which tokenizer or
conservative counting policy production uses and add boundary tests. The
`cl100k_base` cache currently lives under `var/cache/tiktoken`.

## 10. Tests To Add

At minimum, add invariants for:

- complete, partial, nested, and middle-overlap interval subtraction
- no de-duplication across different pages or sources
- disjoint remainder fragments preserve source order
- missing/invalid exact provenance fails clearly
- rank order remains unchanged
- context never exceeds the configured token budget
- headers are included in token accounting
- a fully covered chunk is skipped and later candidates are still considered
- overflow stops lower-ranked candidates under the frozen policy
- selected source documents match the assembled context
- retrieval cache key changes with policy/token/index/model changes
- production-shaped promoted index has 313 documents and 4096-dimensional
  vectors
- every promoted document ID/content hash matches the frozen candidate bundle
- source/book page mapping remains `book_page = source_page - 8`
- exact source intervals reproduce normalized chunk content

Add an end-to-end regression for `ret-0053`: the rank-7 source-page-119 chunk
must enter a 4096-token Top-10 context and both page-114/page-119 evidence
regions must remain present.

## 11. Validation Commands

Run focused retrieval tests while implementing, then the repository gates:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_rag_context_trim.py tests/test_hybrid_retriever.py -q
PYTHONPATH=src .venv/bin/python -m pytest tests/test_query_pipeline.py tests/test_route_harness.py -q
PYTHONPATH=src .venv/bin/python benchmarks/route_harness.py
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests scripts benchmarks
.venv/bin/ruff format --check src tests scripts benchmarks
PYTHONPATH=src .venv/bin/python -m benchmarks.validate_retrieval_gold validate-panel benchmarks/data/retrieval_evidence_panel_v2.json --root .
git diff --check
```

The current verified baseline before production changes is:

- `695 passed, 14 skipped, 1 existing optional-reranker warning`
- Ruff check passed
- Ruff format check passed for 268 files
- Panel v2 valid: 36 quality, 43 robustness, 7 interpretation-sensitive,
  5 boundary

After building the production-shaped isolated index, rerun the raw-vector and
context evaluations against it or prove byte/vector/metadata equivalence to the
frozen candidate before switching.

## 12. Cutover And Rollback

Do not mutate or clear `var/chroma_db` during implementation and testing.

Before cutover:

1. Stop or quiesce writers through the repository's KB write coordination.
2. Archive the active directory and record its collection, revision, count,
   hashes, and configuration.
3. Verify the new isolated index with production code and representative live
   retrievals.
4. Obtain explicit user approval for the active path/configuration switch.
5. Switch atomically where possible; do not rebuild in place.
6. Restart the service so embedding, vector-store, and retrieval caches use the
   new model/index identity.
7. Run smoke queries covering definitions, formulas, exact terms, procedures,
   and `ret-0053`-style multi-region evidence.

Rollback must restore the archived path/configuration without re-ingestion.
Do not treat `CourseKnowledgeBase.clear()` as a deployment mechanism.

## 13. Definition Of Done

The next task is complete only when:

- production code uses the exact selected chunks and Qwen-native vectors
- the active query embedding model matches the index
- Top-10 raw vector candidates feed one typed context assembler
- exact source overlap is removed without rank changes or fuzzy rules
- the complete prompt is proven to fit with the selected token budget
- sources shown to users match the context actually sent to the answer model
- cache identity includes the new retrieval/context policy
- focused, full, Ruff, panel, and route-harness validations pass
- isolated and active index manifests plus rollback instructions are recorded
- the active switch was explicitly approved

Until those conditions are met, keep `var/chroma_db`, `.env`, and production
defaults unchanged.
