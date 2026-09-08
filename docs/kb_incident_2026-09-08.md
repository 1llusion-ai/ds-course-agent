# Knowledge Base Deletion and Recovery

## Evidence

All times below are Asia/Shanghai on 2026-09-08.

- 13:36:30: backend log records loading 560 course documents into BM25.
- 13:38:30: a Claude Code review subagent ran an importlib import check including
  `scripts.reset_db`. Its tool-call log is in session
  `032d8afd-f0ff-4a9a-98d1-2b9c63b30427`, subagent `agent-af22dfa92d1071344`, line 87.
- 13:38:32: the tool result explicitly contains `知识库已清空` followed by
  `OK scripts.reset_db` (line 88). The database directory's birth time matches.
- The old reset script ran shutil.rmtree(config.persist_directory) at module
  scope, removed the hash record, and recreated an empty directory on import.
- A replacement empty SQLite database was created at 13:38:58. Subsequent backend
  restarts lost the old in-memory corpus and reported the missing collection.

This was an actual destructive side effect during review, not a WSL path mismatch.
Passing isolated unit tests and a health endpoint did not verify real KB contents.

## Prevention

`scripts/reset_db.py` is now import-safe and defaults to preview. Mutation requires
`--confirm-reset` with the configured collection name. Confirmed resets archive
the database and hash record under var/artifacts/kb_backups instead of deleting
them. Paths outside the dedicated runtime tree, its root, and backup-overlapping
paths are rejected. The backend must be stopped before invoking a reset.

Six regression tests cover import safety, preview, invalid confirmation, archive
preservation, and broad/overlapping path rejection. Deletion/move traps are installed
before importing the script so the regression test itself cannot erase a live KB.
Reviewers must statically inspect scripts before imports; import is executable code.

## Recovery

Original database copies and open deleted database descriptors were not found.
The textbook PDF and matching parse/clean caches survived:

- PDF SHA256: `816dd50235ebeafe13cdc7cd6db53baea52ab4ef295c6f17fed23f856180eb11`.
- 248 parsed pages; 246 cleaned pages; default chunking with book-page offset -8.
- 572 total chunks: 560 semantic chunks ingested, 12 structural/shadow chunks filtered.
- Embedding model: `Qwen/Qwen3-Embedding-8B`; collection: `course_c37b7b78`.
- New build: 560 successes, 0 skips, 0 errors.

`scripts/recover_kb_from_cache.py` defaults to preview, requires matching trusted
local caches and an expected semantic count, and refuses the active database path.
`--ingest` enables network embedding. Resume requires a matching recovery manifest.
It does not reparse PDFs, clear collections, or precompute unrelated graph embeddings.

The new database was built under `var/chroma_db_recovered_20260908` and tested with
three real embedding queries (logistic regression, PCA, overfitting/underfitting).
All returned three textbook sources with valid book-page metadata.

After user-approved backend shutdown, the empty original was moved to
`var/artifacts/kb-empty-original-20260908`, and the recovered database was moved to
`var/chroma_db`. The backend was restarted at port 8084. No database directory was
deleted during recovery and .env was not changed.

Recovery manifest: `var/chroma_db/recovery.json` (its plan records the original
staging path). Build log: `var/logs/kb_recovery_20260908.log`.
This reconstructs the corpus from surviving caches; it is not a byte-identical
restore of the deleted vectors or any prior metadata repairs.

## Verification

- Full tests: 523 passed, 14 skipped, 1 existing optional-reranker warning.
- Ruff check/format: pass.
- Route tests: 36 passed; route harness: 119/119, Unexpected RAG 0.
- Real restored collection: 560 documents; three retrieval probes passed.
- Backend health: OK after switching to the restored database.
- Real course_rag_tool answer for logistic-regression classification: completed
  in 19,849 ms, trace status OK, three textbook references, no missing collection.
