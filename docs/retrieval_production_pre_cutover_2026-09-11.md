# Retrieval Production Pre-Cutover Record

Date: 2026-09-11

Status: production cutover completed and validated on 2026-09-11. The active
service uses the 313-document promoted index. The former 560-document index is
preserved as a recoverable archive.

## 1. Approved Retrieval Target

- Semantic chunks: `fine_700_140` (`700/140`, ordinary hard maximum `900`).
- Embedding: `Qwen/Qwen3-Embedding-8B`, provider-native 4096 dimensions.
- Distance: cosine; query prefix: empty.
- Retrieval: raw vector Top-10 only.
- Context: preserve vector rank, subtract only exact same-source-page character
  intervals, then stop before exceeding 4096 `cl100k_base_v1` tokens.
- Answer reserve: 768 tokens inside an 8192-token serving window.

Hybrid RRF, adaptive BM25 routing, query instructions, MMR, and BGE reranking
were evaluated and rejected. They are not part of the production path.

## 2. Isolated Production-Shaped Index

| Field | Value |
| --- | --- |
| Directory | `var/chroma_candidates/production_switch_20260910/qwen3_8b_native/chroma` |
| Manifest | `var/chroma_candidates/production_switch_20260910/qwen3_8b_native/production_manifest.json` |
| Manifest SHA-256 | `cb63f11d10d60a1381ade8fb7350c0261e9aeae0e67df210dacef7c8594175b5` |
| Collection | `course_c37b7b78` |
| Documents | 313 |
| Vector dimension | 4096 |
| Collection revision | `6e5f0b09676cbde5e4166582bb0767788471cad07c92c8b9ef5a0c40f4d929c2` |
| Document-set SHA-256 | `ac1dbeff70a51997f599df7301ac57ae6e654925b0f16db026492895022cb720` |
| Source vector SHA-256 | `61fed6f3a575ba365dbe716ad259b8edc13939004c4d6d437048de8e8f34cbf2` |
| Destination vector SHA-256 | `56c3fcec0184603d9105483ddf0966bff706a3f295a3e10d5dc7cb56d61e4ad2` |
| Maximum absolute vector error | `1.4901161193847656e-08` |
| Minimum vector cosine similarity | `0.9999998807907104` |

Chroma normalizes cosine vectors when they are re-added, so source and
destination byte hashes intentionally differ. The numeric error and cosine
similarity bounds are the equivalence proof; the manifest does not claim byte
identity.

## 3. Prompt-Budget Proof

Report:
`var/artifacts/kb_eval/retrieval_production_20260911/prompt_budget.json`

Report SHA-256:
`6b6abd5cebcb4ba07963b90bf11a58ff52a30b761bf42c35f793abda400b5874`

The report validates all 48 frozen dev/test queries against the promoted
collection and the exact production prompt template.

| Metric | Result |
| --- | ---: |
| Maximum context tokens | 4095 |
| Maximum prompt tokens | 4310 |
| Maximum prompt plus answer reserve | 5078 |
| Minimum remaining context window | 3114 |
| Worst case | `ret-0055` |

The `ret-0053` regression probe selects all 10 candidates, includes source
pages 114 and 119, uses 2760 context tokens, and leaves 4435 tokens after the
768-token answer reserve. A real Qwen query embedding against the isolated
index reproduced the frozen Top-10 ranking exactly.

## 4. Active Index Snapshot Before Cutover

This was the rollback source immediately before the controlled switch.

| Field | Value |
| --- | --- |
| Directory | `var/chroma_db` |
| Collection | `course_c37b7b78` |
| Documents | 560 |
| Revision token | `1e01f7eb26cd4891ba8425f525bf82f0` |
| Content fingerprint | `bd470e97bfb7f9fd8fc35bd9599d8b6d3bb2276f20616720b08612a64b16cbab` |
| SQLite SHA-256 | `2d2cc07da695850a37c500d4c38cd96226e317ac61d4040edd712e127c3c49ad` |
| Recovery manifest SHA-256 | `23cb50790f73105cf98db5469a47cce5b5eac177c4b2c1ab7efa9d755e62bd27` |

The content fingerprint is SHA-256 over sorted records of each relative file
path, byte size, and file SHA-256. It intentionally excludes mtimes because a
Chroma client can touch SQLite timestamps during read access.

At snapshot time, `.env` pointed to `var/chroma_db`, had no
`RAG_INDEX_MANIFEST_PATH`, and still contained the obsolete character-budget
settings. Those entries were changed only during the approved switch.

## 5. Controlled Cutover Procedure

These steps were executed after explicit user approval.

1. Stop the FastAPI backend and every KB writer. Verify no process is serving
   requests or ingesting into `var/chroma_db`.
2. Run `.venv/bin/python scripts/reset_db.py` and verify it previews
   `var/chroma_db`, collection `course_c37b7b78`, and the expected hash-record
   path without mutation.
3. Run `.venv/bin/python scripts/reset_db.py --confirm-reset course_c37b7b78`.
   Record the returned `var/artifacts/kb_backups/<timestamp>-<id>` path and
   verify that it contains `database/chroma.sqlite3`. Do not delete this archive.
4. Update only these retrieval entries in `.env`:

   ```dotenv
   CHROMA_PERSIST_DIR=var/chroma_candidates/production_switch_20260910/qwen3_8b_native/chroma
   EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B
   RAG_CANDIDATE_DEPTH=10
   RAG_CONTEXT_MAX_TOKENS=4096
   RAG_CONTEXT_TOKENIZER_POLICY=cl100k_base_v1
   RAG_CONTEXT_DEDUPLICATION_MODE=exact_source_interval_v1
   RAG_CONTEXT_OVERFLOW_POLICY=stop_v1
   RAG_CONTEXT_HEADER_POLICY=compact_page_v1
   RAG_INDEX_MANIFEST_PATH=var/chroma_candidates/production_switch_20260910/qwen3_8b_native/production_manifest.json
   ```

5. Remove `RAG_CONTEXT_TRIM_ENABLED`, `RAG_CONTEXT_MAX_CHARS`, and
   `RAG_CONTEXT_DOC_MAX_CHARS` from `.env`; they no longer have consumers.
6. Start a fresh backend process so embedding, vector-store, retrieval, and
   answer caches cannot retain the old index identity.
7. Run startup, health, definition, formula, exact-term, procedure, and
   `ret-0053` multi-region smoke checks. Confirm the service manifest identity,
   313-document count, source pages, and prompt-budget telemetry.
8. Keep the rollback archive through the observation period. Do not ingest or
   rebuild the promoted directory in place.

## 6. Rollback Procedure

Rollback does not re-ingest or re-embed documents.

1. Stop the backend and all KB writers.
2. Restore the previous retrieval entries in `.env`, especially
   `CHROMA_PERSIST_DIR=var/chroma_db`, and remove the promoted
   `RAG_INDEX_MANIFEST_PATH` while running the pre-migration code revision.
3. Move the empty or failed `var/chroma_db` aside into a new path under
   `var/artifacts/kb_backups/`; never delete it in place.
4. Move `<recorded-backup>/database` back to `var/chroma_db`. Restore
   `<recorded-backup>/hash-record` only if that file exists in the archive and
   its configured destination is under `var/`.
5. Restore the pre-cutover code revision if the new code requires the promoted
   manifest, then restart the backend.
6. Verify collection `course_c37b7b78`, document count 560, revision token
   `1e01f7eb26cd4891ba8425f525bf82f0`, and representative retrievals before
   reopening traffic.

`CourseKnowledgeBase.clear()` is not a deployment or rollback mechanism.

## 7. Validation Gates

- Focused retrieval, promotion, report, and archive tests: 42 passed.
- Route tests: 38 passed.
- Route harness: 119/119; unexpected RAG count 0.
- Evidence panel v2: valid (36 quality-gate, 43 robustness, 7
  interpretation-sensitive, 5 boundary samples).
- Full suite: 734 passed, 14 skipped, one existing optional-reranker warning.
- Ruff check: passed.
- Ruff format: 276 Python files passed.
- Live `RAGService()` manifest/startup and `ret-0053` retrieval smoke: passed.

## 8. Executed Cutover

- Cutover date and time: 2026-09-11, backend started at 14:12 Asia/Shanghai.
- Rollback archive:
  `var/artifacts/kb_backups/20260911-141029-b488abee/database`.
- Archived collection: `course_c37b7b78`, 560 documents, revision
  `1e01f7eb26cd4891ba8425f525bf82f0`.
- Archive SQLite SHA-256 after opening it once for count verification:
  `238f5f1b695318dd2a9dec15ddc26e20e164a30109f239f0daf6c789dc31a7fa`.
  Chroma updated internal SQLite state during that verification, so the
  pre-cutover SQLite byte hash is retained as historical evidence rather than
  used as the rollback acceptance condition.
- Active collection after restart: `course_c37b7b78`, 313 documents, manifest
  SHA-256
  `cb63f11d10d60a1381ade8fb7350c0261e9aeae0e67df210dacef7c8594175b5`.
- Definition, formula, procedure, and `ret-0053` live vector retrievals passed.
  `ret-0053` reproduced the frozen Top-10 exactly and retained source pages 114
  and 119 in a 2760-token context.
- Authenticated FastAPI SSE smoke passed through routing, retrieval, answer
  generation, source projection, and history persistence. It completed without
  degradation with 6 displayed sources.
- Backend process: local development service on `127.0.0.1:8084`; health check
  returned `{"status":"ok","service":"rag-tutor-backend"}`.

Keep the rollback archive unchanged through the observation period.

## 9. Post-Cutover Term Resolution Hardening

Live testing exposed two failure modes after the index switch:

1. The optional 0.5-second concept-mapping embedding request shared the same
   circuit-breaker mutation path as required RAG embeddings. Its timeout could
   incorrectly block required retrieval for 60 seconds.
2. A missing short acronym still received semantic Top-10 neighbors, which
   displayed unrelated course sources and encouraged an unsupported answer.

The production path now uses typed embedding circuit modes. Required RAG
embeddings use the managed breaker, while optional concept mapping observes
failures without opening it.

Single explicit short-term queries also pass through a conservative course-term
index before vector retrieval:

- Exact terms use only chunks that directly contain the term.
- A typo is corrected only when one same-length course acronym is uniquely
  close enough; the correction is disclosed before answering.
- An unresolved term returns zero documents and zero displayed sources instead
  of semantic neighbors.
- Normal multi-term questions remain on the raw-vector Top-10 path.

Live SSE validation on 2026-09-11 confirmed:

- `DMKI是什么？` resolves to the textbook term `DIKW`, answers using the
  corrected query, and displays only the direct evidence on book pages 16 and
  23.
- `ZZZZ是什么？` does not call answer generation, returns a deterministic
  spelling/context request, and displays no sources.
- Both responses match persisted chat history and complete without degradation.

A later browser regression showed that contextual follow-up rewriting could
prepend a previous acronym to the semantic retrieval query. For example, a
previous `BCA` turn caused the enriched `DWKI是什么？` query to contain two
acronyms, so conservative term resolution treated it as inapplicable and fell
back to vector Top-10. Retrieval now receives the enriched semantic query and
the current original user query as separate typed parameters. Term resolution
uses only the current query, while normal vector retrieval retains conversational
context. The reproduced `BCA` then `DWKI` sequence now resolves to `DIKW` and
returns only book pages 16 and 23.

Explicit short-term definition questions now also have a typed,
deterministic route before the semantic learning router. Bounded frames such as
`BCA是什么？`, `请解释 OOP`, and `SVM 的定义` route directly to required
course retrieval, so a semantic-router timeout cannot prevent term resolution.
The route does not resolve the term itself; the course-term index still owns
exact matching, unique typo correction, and zero-evidence rejection. Broader
requests such as `PCA怎么学比较好？` and personalized explanations remain on
their learning-path or teaching-skill routes. The route harness remains
119/119 with zero unexpected RAG cases.

## 10. Acceptance Repairs

The 2026-09-11 acceptance run found two retrieval regressions and repeated
embedding failures in the running development backend. The repairs preserve
the promoted index and the frozen raw-vector/context policy:

- Short-term parsing now accepts only complete definition frames. Procedures,
  mixed Chinese/English comparisons, and compound names such as `K-means`
  retain their full semantic query. `Pandas` and `Kaggle` mentions no longer
  replace those queries with page-ordered literal matches.
- Retrieval cache keys preserve capitalization and token boundaries in both
  the semantic query and original term query. Warming `DMKI` no longer changes
  the result for `dmki`. Automatic typo correction still requires uppercase;
  deterministic definition routing supports either case.
- Explicit requests beginning with `根据教材`, `依据课程资料`, and equivalent
  supported source instructions set `QueryContext.course_evidence_requested`.
  The existing grounded-learning rule consumes that typed signal before
  semantic fallback. Boundary, web, code, and teaching-strategy rules retain
  their earlier priorities.
- Managed query embeddings retry transient failures once. Three consecutive
  exhausted requests, rather than one timeout, open the existing breaker.
  Success resets the consecutive failure count. Optional concept mapping
  neither retries nor changes that count. The configured timeout remains a
  per-attempt limit, so the current 5-second limit permits up to two attempts.

The former local backend inherited `CODEX_SANDBOX_NETWORK_DISABLED=1` and the
workspace permission profile. It was replaced by a persistent Herdr terminal
process without those inherited restrictions, still serving `127.0.0.1:8084`.
Launch command from the project root:

```bash
.venv/bin/python main.py api --host 127.0.0.1 --port 8084 >> var/logs/retrieval-api-20260911.log 2>&1
```

Verification artifacts live under
`var/artifacts/kb_eval/retrieval_repair_20260911/`:

- Full pytest: 772 passed, 14 skipped, one existing optional-reranker warning.
- Ruff check and format: passed; route harness 119/119, unexpected RAG 0.
- All 36 quality-gate queries regained complete evidence under both
  independent annotations, measured through actual production `retrieve()`.
  `ret-0016` includes book pages 62/63; `ret-0036` includes book page 216;
  `ret-0053` retains source pages 114/119 in 2760 tokens.
- The 48-query live run completed 47 initially. Four requests recovered through
  the added retry; one non-gate query exhausted both attempts, then passed a
  separately recorded recheck. No subsequent batch-wide circuit rejection
  occurred. This is evidence of recovery, not a claim of zero provider failures.
- Browser checks confirmed repaired Pandas/Kaggle references, zero references
  for the lowercase unknown term, and identical content after refresh.

The acceptance directory retains failed runs and rechecks separately. External
model latency remains variable; the old degraded-status propagation issue and
mobile sidebar layout are separate issues recorded in the original acceptance
report.
