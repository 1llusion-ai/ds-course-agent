# Retrieval Chunk and Embedding Selection

Date: 2026-09-10. Status: experiment complete; production switch deferred.

This experiment uses the reviewed source and dual-agent panel described in
`retrieval_gold_schema_annotation_v1.md`. All Chroma indexes are isolated under
`var/chroma_candidates/chunk_eval_20260910/`; the active `var/chroma_db` was not
modified. Candidate selection uses only the 36-query dev split.

## 1. Structural Gate

The original long-paragraph splitter could cut inside `$$...$$`. Before indexing,
the splitter was corrected so a split target moves before or after the complete
display-math unit. The invariant is covered by an automated test.

| Candidate | Semantic chunks | Mean chars | Max chars | Atomic units intact | Mapping ambiguity |
| --- | ---: | ---: | ---: | ---: | ---: |
| `fine_700_140` | 313 | 588.6 | 1076 | 86/86 | 0 |
| `baseline_1300_300` | 234 | 742.9 | 1500 | 86/86 | 0 |
| `coarse_1800_360` | 230 | 750.8 | 1892 | 86/86 | 0 |

The baseline and coarse candidates are nearly identical because most reviewed
body pages contain fewer than 1300 characters and the current chunker does not
merge content across physical pages.

## 2. Dev Results

Values below are `(terra-a, terra-b)` on the quality-gate dev subset (`n=25`).
The panel pre-declared `CompleteEvidence@5` as the primary comparison depth.

| Chunk / embedding | Complete@3 | Complete@5 | Coverage@3 | Sufficient MRR |
| --- | --- | --- | --- | --- |
| baseline / Qwen native | (0.84, 0.84) | (0.96, 0.96) | (0.840, 0.862) | (0.567, 0.448) |
| coarse / Qwen native | (0.84, 0.84) | (0.96, 0.96) | (0.840, 0.862) | (0.567, 0.448) |
| fine / Qwen native | (0.84, 0.84) | **(1.00, 1.00)** | **(0.897, 0.888)** | (0.553, 0.440) |
| fine / Qwen 1024 | (0.76, 0.72) | (0.96, 0.96) | (0.871, 0.839) | (0.509, 0.417) |
| fine / BGE-M3 | (0.64, 0.60) | (0.84, 0.84) | (0.710, 0.708) | (0.443, 0.370) |

On the broader dev robustness group (`n=31`), fine/Qwen-native reaches
`CompleteEvidence@5 = (0.935, 1.000)`, versus `(0.903, 0.968)` for baseline and
coarse. Qwen-1024 loses ranking quality without reducing the number of indexed
documents. BGE-M3 is materially worse on both independent labels, so no BGE
chunk-interaction expansion is justified.

## 3. Frozen Selection

- Chunk configuration: `fine_700_140` (`chunk_size=700`, `overlap=140`, hard max 900;
  complete display math may exceed the ordinary hard max).
- Embedding: `Qwen/Qwen3-Embedding-8B`, provider-native 4096 dimensions.
- Vector distance: cosine.
- Primary retrieval depth: 5. Runtime context-budget behavior remains a separate
  acceptance check before production switching.
- Test rule: evaluate this configuration once; do not change parameters in
  response to the test result.

The selection accepts a small MRR regression in exchange for perfect dev
quality-gate completion at depth 5, higher evidence coverage at depth 3, and
better worst-side robustness completion. Index document count increases by 34%
over baseline, which is acceptable for a 313-document course corpus.

## 4. Frozen Dev Artifacts

- baseline/Qwen report SHA-256:
  `0581bb07fc39317d40e59c7e861d367e0e1108b1d7d3cd8fbf9cbe1bc549acde`
- coarse/Qwen report SHA-256:
  `c97856165bb0e6d8cf25cabf6d527de081f527dc581e0a74a35525cb3351a943`
- fine/Qwen-native report SHA-256:
  `4762e90181024660cc1d13b54b89a544b90f310abc16f9b53723bf951050d937`
- fine/Qwen-1024 report SHA-256:
  `2eebe97aefc61ed303a0d04e014a6cf8c52201a6804ecb989e9103d6964f3b4a`
- fine/BGE-M3 report SHA-256:
  `c0de7c2b3a2c23cce27c55657b224c3f50bc88e7e6be49549f74a6e3250ecf46`

These hashes bind the exact dev results used for selection. Runtime reports and
indexes remain under `var/`; they are not copied into the package or active KB.

## 5. Frozen Test Results

The frozen finalist was evaluated once on the 12-query test split. The
quality-gate subset contains 9 queries; the robustness group contains all 12.
Values remain `(terra-a, terra-b)`.

| Group | Complete@3 | Complete@5 | Complete@10 | Coverage@5 |
| --- | --- | --- | --- | --- |
| quality gate | (0.778, 0.778) | (0.778, 0.889) | (0.889, 1.000) | (0.919, 0.945) |
| robustness | (0.583, 0.583) | (0.583, 0.750) | (0.667, 0.833) | (0.753, 0.792) |

All test labels have complete evidence somewhere in the candidate corpus on
both annotation sides (`candidate_complete_rate = 1.0`). The remaining errors
are therefore ranking or semantic-retrieval misses, not evidence destroyed by
the fine chunking strategy.

At depth 5, incomplete evidence remains for feature-discovery stages
(`ret-0039`, both sides), KNN versus K-means (`ret-0041`, terra-a), PCA versus
LDA (`ret-0042`, both sides), DataFrame tabular evidence (`ret-0043`, terra-a),
and full-project stages (`ret-0048`, both sides). `ret-0042` becomes complete by
depth 10; the others expose broader ranking or query-understanding gaps.

Test report SHA-256:
`cb99fbb507c358d02b3db5258a9f6b4e3ec26f3c551fa7401e84ac2e0f86e44e`.

## 6. Exit Decision

`fine_700_140` with native 4096-dimensional Qwen embeddings is the best tested
configuration in this experiment. BGE-M3 and Qwen-1024 are not competitive,
and baseline/coarse do not justify further chunk-size expansion.

The finalist is not approved for a direct production switch. Its frozen test
result does not reproduce the perfect dev completion at depth 5, and changing
the retrieval depth or parameters now would tune on test. The active
`var/chroma_db` remains unchanged.

Further optimization requires a new unseen test family before another test
decision. The next experiment should hold fine/Qwen-native fixed and evaluate
retrieval strategy changes such as hybrid lexical-vector retrieval, explicit
query instructions, or reranking. Runtime context-budget behavior must also be
measured before any production migration.

The dev-only strategy sweep is recorded in
`docs/retrieval_strategy_selection_2026-09-10.md`. Raw vector retrieval remains
the best unconditional strategy; a conservative adaptive policy improves MRR
by routing only exact formula/enumeration lookups to BM25. Query instructions,
unweighted RRF, and BGE reranking all reduced the primary depth-5 completion
metric.
