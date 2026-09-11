# Knowledge Base Rebuild and Retrieval Evaluation Handoff

Date: 2026-09-10

## 1. Decision Summary

The PDF parsing and formula-repair work has produced a reviewed source baseline.
The next step is **not** to overwrite or rebuild the production knowledge base
immediately.

The correct order is:

1. Freeze and verify the reviewed parse/clean baseline.
2. Build a retrieval gold dataset whose labels do not depend on chunk IDs.
3. Generate several candidate chunk configurations from the same clean baseline.
4. Build a separate ChromaDB index for each candidate under `var/`.
5. Evaluate retrieval quality, context quality, and index cost on the same dataset.
6. Select and freeze the winning chunk strategy.
7. Rebuild and switch the production knowledge base only after the strategy wins.
8. Refresh RAG/Agent evaluation after retrieval behavior is stable.

In short: **gold evidence first, candidate chunks second, production rebuild last**.
Otherwise the project would select chunks using labels generated from those same
chunks, which creates circular evaluation.

## 2. Completed PDF Baseline

Source PDF:

`data/数据科学导论（案例版）洪文兴-0823.pdf`

The reviewed result has the following verified properties:

| Item | Result |
| --- | ---: |
| Physical PDF pages | 248 |
| Non-empty parsed pages | 236 |
| Original Marker equation blocks | 87 |
| OCR formulas accepted after visual review | 62 |
| Formulas manually corrected against the PDF | 24 |
| Decorative equation block removed | 1 |
| Final LaTeX display-equation blocks | 86 |
| Missing, rejected, or unreviewed formulas | 0 |
| Replacement/private-use/duplicate candidate characters | 0 |
| Display-math delimiters | 172, balanced |
| Actual prose letter-spacing candidates | 0 |

Formula replacement is review-gated. The merge process checks SHA-256 hashes for
the PDF, baseline parse cache, and OCR result. Syntactically valid LaTeX is not
accepted without an explicit review decision because OCR can produce valid but
mathematically incorrect formulas.

The remaining 14 spaced alphanumeric sequences are not identified prose noise:

- 9 are inline mathematical notation embedded in text.
- 5 are legitimate table values or column labels.
- LaTeX blocks are excluded from prose spacing-noise detection.

This means the source is clean enough to enter chunking experiments. It does not
mean that every mathematical expression has publication-grade two-dimensional
typesetting. The stored representation is retrieval-oriented LaTeX/text.

## 3. Frozen Artifacts

Reviewed parse cache:

`var/cache/数据科学导论（案例版）洪文兴-0823_1f733c2af93a74f1_mp0_marker_parse_blocks-v2_equation-reviewed-v1.pkl`

Reviewed clean cache:

`var/cache/数据科学导论（案例版）洪文兴-0823_1f733c2af93a74f1_mp0_marker_clean_blocks-v2_equation-reviewed-v1.pkl`

Current preview chunk cache:

`var/cache/数据科学导论（案例版）洪文兴-0823_1f733c2af93a74f1_mp0_marker_chunks_blocks-v2_equation-reviewed-v1.pkl`

Quality and review reports:

- `var/artifacts/marker_equation_reviewed_report_20260910.json`
- `var/artifacts/marker_parser_quality_comparison_20260910.json`
- `var/artifacts/marker_equation_reviewed_chunk_report_20260910.json`
- `var/artifacts/equation_review_20260910/equation_review.json`
- `var/artifacts/equation_review_20260910/review_manifest.json`
- `var/artifacts/equation_review_20260910/sheet-*.png`

These files are runtime/review artifacts under `var/`; they are not a substitute
for a reproducible build manifest. Before running candidate experiments, record
the source PDF hash, cache hash, code revision, parser mode, cleaner version, and
candidate chunk parameters in each experiment report.

No active ChromaDB ingestion was performed during the latest parsing and formula
review. The active `var/chroma_db` must remain unchanged during chunk selection.

## 4. Page Number Semantics

The full-book PDF uses two page systems:

- `source_page`: one-based physical page number in the 248-page PDF.
- `book_page`: printed textbook page number used for user-facing citations.
- Mapping: `book_page = source_page - 8`.

The physical-page sequence was checked as unique and continuous from 1 through
248. The preview semantic chunks span `source_page` 10-248 and `book_page` 2-240.
Front matter and non-body/decorative content must not become normal retrievable
semantic evidence.

Candidate chunking must preserve at least:

- source PDF identity;
- `source_page_start` and `source_page_end`;
- `book_page_start` and `book_page_end`;
- chapter, section, and subsection where available;
- chunk type;
- parser/cleaner/chunker version or configuration fingerprint.

Page mapping should be covered by an automated invariant before production
ingestion: each chunk's book-page range must equal its source-page range minus 8,
and ranges must remain within the verified PDF bounds.

## 5. Why 233, 560, and 566 Are Not Comparable Yet

The current `CourseChunkerV2` preview produced:

| Chunk type | Count |
| --- | ---: |
| Total | 245 |
| Semantic | 233 |
| Structural | 1 |
| Shadow | 11 |
| Empty | 0 |

The historical 560/566 figures came from different source caches and chunking
conditions, including chapter-based source files in an earlier rebuild. A chunk
count is a capacity/cost observation, not a retrieval-quality score.

Therefore:

- 233 is not automatically too coarse.
- 560 or 566 is not automatically more accurate.
- Matching an old count is not an acceptance criterion.
- A candidate wins only if it retrieves complete, relevant evidence with less
  fragmentation and acceptable redundancy/cost.

The preview chunk cache is useful as one baseline candidate, but it is not the
selected production strategy.

## 6. Gold Retrieval Dataset

The existing datasets under `benchmarks/data/retrieval_qa_pairs*.json` primarily
label `ground_truth_ids`, `acceptable_ids`, and per-chunk relevance. Those IDs are
tied to an old index. They become stale whenever source files, cleaning, or chunk
boundaries change.

Create a new reviewed dataset, for example:

`benchmarks/data/retrieval_evidence_gold_v1.json`

Its authoritative labels should describe evidence in the textbook rather than a
specific chunking output. Recommended sample fields:

```json
{
  "id": "ret-001",
  "query": "为什么训练误差很低仍可能泛化不好？",
  "question_type": "explanation",
  "difficulty": "medium",
  "concepts": ["过拟合", "泛化"],
  "gold_evidence": [
    {
      "source_page_start": 169,
      "source_page_end": 170,
      "book_page_start": 161,
      "book_page_end": 162,
      "chapter": "第8章",
      "section": "...",
      "evidence_text": "经人工核对的最小充分证据原文",
      "relevance": 3
    }
  ],
  "acceptable_evidence_regions": [],
  "review_status": "double_checked",
  "review_notes": ""
}
```

Exact page values in the example are illustrative and must be replaced by manual
annotation against the reviewed PDF/cache.

Dataset requirements:

- Include definition, mechanism/explanation, comparison, procedure, code/API,
  table interpretation, formula interpretation, and cross-section questions.
- Include natural student wording, aliases, abbreviations, and underspecified
  queries, not only textbook headings.
- Mark the smallest sufficient evidence span and any genuinely acceptable
  alternative evidence regions.
- Use graded relevance where a primary explanation and a brief mention are both
  relevant but not equally useful.
- Separate single-region questions from multi-region questions.
- Keep development and held-out test splits fixed before tuning chunk parameters.
- Require manual review; automatic generation may propose questions but may not
  assign final evidence labels by retrieving from a candidate index.

For a first useful iteration, prioritize coverage and annotation quality over a
large sample count. A small manually audited set is more valuable than many
self-labeled queries that encode the current retriever's mistakes.

## 7. Mapping Gold Evidence to Candidate Chunks

For each candidate chunking output, derive candidate-specific relevance labels by
intersecting chunk provenance with the stable gold evidence spans. Do not write
those derived chunk IDs back into the authoritative gold dataset.

The mapping stage should emit a separate artifact such as:

`var/artifacts/kb_eval/<run_id>/<candidate>/derived_relevance.json`

A chunk can receive graded relevance based on:

- whether it covers the gold evidence region;
- how much of the required evidence it covers;
- whether it includes the complete formula/table/code block needed by the query;
- how much unrelated context it adds;
- whether several chunks are jointly required because a boundary split the
  evidence.

Text-span matching should use normalized text plus page/section provenance, with
manual review for ambiguous mappings. Page overlap alone is too coarse.

## 8. Candidate Chunk Experiments

All candidates must use the same reviewed parse/clean baseline. Change only
declared chunk dimensions in a controlled experiment.

Candidate dimensions worth evaluating:

- target chunk size and hard maximum size;
- overlap size or overlap policy;
- paragraph/heading-aware boundary behavior;
- preservation of formulas, code blocks, and tables as atomic units;
- whether short section fragments merge with adjacent explanatory text;
- whether shadow/parent context participates in retrieval or only context
  expansion;
- metadata included in BM25/vector text;
- retrieval-time parent/neighbor expansion.

The current default `CourseChunkerV2` configuration (`chunk_size=1300`,
`chunk_overlap=300`) should be retained as a baseline. Add only a small number of
meaningfully different candidates. A useful initial matrix is:

| Candidate | Purpose |
| --- | --- |
| `baseline_1300_300` | Current reviewed preview baseline |
| `finer_structure_aware` | Test whether smaller evidence units improve rank and reduce irrelevant context |
| `coarser_structure_aware` | Test whether larger units reduce boundary fragmentation for explanations/formulas |

Do not optimize by testing many near-identical sizes against the held-out test
set. Tune on the development split, then evaluate the frozen finalists once on
the test split.

## 9. Candidate Index Isolation

Each candidate must use a separate persistent directory and collection. Example:

```text
var/chroma_candidates/<run_id>/baseline_1300_300/
var/chroma_candidates/<run_id>/finer_structure_aware/
var/chroma_candidates/<run_id>/coarser_structure_aware/
```

Each directory needs a manifest containing:

- source PDF and SHA-256;
- reviewed parse/clean cache paths and hashes;
- Git commit or working-tree identifier;
- chunk parameters and chunk-type counts;
- embedding model and settings;
- collection name;
- build time, success/skip/error counts;
- evaluation dataset version and split;
- evaluation report paths.

**Do not clear, overwrite, migrate, or point experiments at `var/chroma_db`.**
Candidate build commands must require an explicit output under `var/` and reject
the configured active database path, following the safeguards documented in
`docs/kb_incident_2026-09-08.md`.

## 10. Retrieval Evaluation

Evaluate the chunk strategy and retrieval strategy separately where possible.
First hold the retriever constant to compare chunk candidates. Then, on the
selected or finalist chunk strategies, compare vector, BM25/vector fusion, and
reranking options.

Core retrieval metrics:

- `Hit@k`: whether at least one sufficient evidence chunk is retrieved.
- `Recall@k`: coverage of all required evidence regions, especially for
  multi-evidence questions.
- `MRR`: rank of the first sufficient result.
- `nDCG@k`: ranked quality when relevance is graded.
- Evidence coverage: proportion of the gold span contained in retrieved context.
- Complete-evidence rate: proportion of queries whose retrieved set contains all
  evidence needed to answer correctly.

Chunk/context diagnostics:

- Boundary fragmentation: number or rate of gold spans split across chunks.
- Context redundancy: repeated/overlapping characters or tokens in top-k context.
- Irrelevant-context ratio: retrieved context outside accepted evidence regions.
- Atomic-block integrity: formulas, tables, and code blocks split incorrectly.
- Context size: characters/tokens passed downstream per query.
- Empty, very short, oversized, or metadata-incomplete chunk counts.

Operational metrics are secondary but still useful:

- index document count and disk size;
- embedding/build time and failures;
- retrieval latency distribution measured over repeated local runs;
- reranker availability/fallback rate.

Do not report a single end-to-end latency number as a property of chunking. Agent
latency also includes model provider time, tool execution, retries, streaming, and
network conditions. If latency is later placed on the resume, document the test
environment, sample size, warm-up, concurrency, start/end boundary, and p50/p95.

## 11. Selection Rule

Choose the simplest candidate that satisfies quality gates rather than the one
with the largest chunk count or a marginal win on one aggregate metric.

Recommended decision order:

1. Reject candidates with page/provenance errors, empty chunks, broken atomic
   blocks, or build failures.
2. Reject candidates with unacceptable complete-evidence or Recall@k results.
3. Compare MRR/nDCG, fragmentation, irrelevant context, and redundancy among the
   remaining candidates.
4. Check per-category regressions; aggregate averages must not hide failures on
   formula, table, code, or multi-section questions.
5. Use index size and latency as tie-breakers after evidence quality is adequate.

The selected parameters, dataset version, and report must be frozen in a tracked
decision record. Avoid selecting from an undocumented interactive run.

## 12. Production Rebuild Exit Criteria

Production KB rebuild may begin only when all of the following are true:

- The reviewed parse and clean artifacts are hash-pinned.
- Page-mapping invariants pass for every candidate chunk.
- The gold dataset has completed manual review and a frozen test split.
- All finalist indexes were built outside `var/chroma_db` from the same baseline.
- Candidate-specific chunk relevance was derived from evidence labels, not copied
  from the old chunk-ID dataset.
- The winner meets the agreed retrieval and context-quality gates with no critical
  category regression.
- The winning chunk configuration and embedding/retrieval settings are recorded.
- A reversible production switch and rollback path are prepared.

After those criteria pass:

1. Build the winning index in a new staging directory under `var/`.
2. Verify collection count, metadata, page mapping, retrieval probes, and the full
   retrieval benchmark against the staging index.
3. Stop services that hold the active ChromaDB.
4. Archive the current production index; do not delete it.
5. Switch the verified staging index into the configured production path.
6. Restart services and run KB status, retrieval smoke tests, and API/Agent checks.
7. Keep the rollback index until the new build has passed an observation period.

## 13. Follow-up Evaluation Order

Once retrieval is stable, update evaluation in this order:

1. Retrieval evidence dataset and chunk selection.
2. Retrieval strategy comparison: vector, hybrid, fusion parameters, reranker.
3. Grounded RAG answer evaluation: correctness, citation support, completeness,
   unsupported-claim rate, and citation/page accuracy.
4. Agent route/tool-contract evaluation using the stabilized RAG behavior.
5. Learner-profile and personalization evaluation after the learner-memory
   algorithm has stabilized.

This keeps learner-profile work out of the current critical path while still
refreshing the stale retrieval and Agent/RAG evaluations at the correct time.

## 14. Immediate Next Deliverables

The next implementation task should produce these artifacts without touching the
active knowledge base:

1. A versioned, chunk-independent retrieval gold schema and validator.
2. An initial manually reviewed development/test dataset.
3. A candidate chunk export format with complete page/section provenance.
4. An isolated candidate-index builder with active-path rejection.
5. An evaluator that derives chunk relevance from evidence spans and reports both
   ranking metrics and chunk/context diagnostics.
6. A candidate comparison report that records the final selection decision.

Only item 6 should authorize a production rebuild.
