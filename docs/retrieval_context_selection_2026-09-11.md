# Retrieval Context Selection

Date: 2026-09-11. Status: offline context policy selected; production unchanged.

This experiment evaluates what happens after raw-vector Top-10 retrieval. It
does not change the selected `fine_700_140` chunks, Qwen embedding index,
first-stage ranking, active `var/chroma_db`, or production configuration.

## 1. Frozen Contract

- Input ranking: the previously frozen raw-vector Top-10 reports.
- Tokenizer: `cl100k_base`, cached under `var/cache/tiktoken` after one-time
  initialization.
- Context budgets: `2048` and `4096` tokens, inherited from evidence panel v2.
- Overflow policy: include complete source spans in selection order and stop
  before the next block would exceed the budget.
- Header format: compact textbook-page header, included in token accounting.
- Evidence scoring: exact union of source-page character intervals against
  each agent's independent sufficient evidence sets.
- Source de-duplication: subtract only source intervals already included in the
  context. It does not use fuzzy text matching or discard semantically similar
  passages from different source regions.

The dev matrix froze five strategies before scoring: rank prefix, source
overlap de-duplication, and MMR plus source de-duplication with lambda values
`0.50`, `0.70`, and `0.85`. MMR uses the existing chunk embeddings and frozen
retrieval similarities; it makes no new embedding request.

## 2. Dev Selection

Values are `(terra-a, terra-b)` on the 25-query quality-gate group.

| Strategy | Complete@2048 | Coverage@2048 | Complete@4096 | Mean chunks@2048 | Removed source chars@2048 |
| --- | --- | --- | --- | ---: | ---: |
| rank prefix | (0.88, 0.84) | (0.907, 0.878) | (1.00, 1.00) | 2.72 | 0.0% |
| source overlap de-dup | **(0.92, 0.88)** | (0.920, 0.900) | **(1.00, 1.00)** | 2.84 | 2.53% |
| MMR 0.50 + de-dup | (0.56, 0.48) | (0.628, 0.623) | (0.76, 0.72) | 3.08 | 0.0% |
| MMR 0.70 + de-dup | (0.84, 0.80) | (0.897, 0.880) | (0.96, 0.96) | 3.12 | 1.59% |
| MMR 0.85 + de-dup | (0.92, 0.88) | **(0.950, 0.930)** | (1.00, 1.00) | 2.92 | 2.12% |

Source de-duplication recovers `ret-0001` at 2048 tokens with no quality-gate
regression. MMR `0.85` has a better aggregate coverage number, but it improves
`ret-0036` by moving other evidence while regressing `ret-0010`. Lower lambda
values cause broad regressions. Aggregate compensation is not sufficient to
accept a policy that removes required evidence from a previously complete
query, so MMR is rejected.

At 4096 tokens, rank prefix and source de-duplication both complete all 25
quality-gate dev queries for both annotations. De-duplication increases the
mean selected chunk count from `6.24` to `6.52` while removing `3.15%` of
selected source characters.

## 3. Test Diagnostic

The finalist matrix retained rank prefix, source overlap de-duplication, and
MMR `0.85`. Values are `(terra-a, terra-b)` on the 11-query test quality gate.

| Strategy | Complete@2048 | Coverage@2048 | Complete@4096 | Mean chunks@2048 | Removed source chars@2048 |
| --- | --- | --- | --- | ---: | ---: |
| rank prefix | (0.818, 0.818) | (0.944, 0.894) | (1.00, 1.00) | 3.73 | 0.0% |
| source overlap de-dup | **(0.909, 0.909)** | **(0.972, 0.961)** | **(1.00, 1.00)** | 4.00 | 2.95% |
| MMR 0.85 + de-dup | (0.909, 0.909) | (0.972, 0.961) | (1.00, 1.00) | 3.73 | 3.11% |

Source de-duplication recovers `ret-0052` at 2048 tokens with no test
regression. MMR adds no test evidence gain over source de-duplication and had a
dev regression, so it remains rejected.

The test should be treated as a held-out diagnostic rather than a fresh blind
test because the rank-7 gap for `ret-0053` was inspected before this context
experiment. No strategy or rule was added specifically for that query.

## 4. `ret-0053` Diagnosis

`ret-0053` requires evidence on source pages 114 and 119. The second region is
the raw-vector rank-7 chunk.

- At 2048 tokens, all finalist strategies stop after original retrieval rank 6
  and remain incomplete for both annotations.
- At 4096 tokens, rank prefix and source de-duplication include the full Top-10
  and complete both annotations.
- MMR `0.85` changes some early ordering but does not promote rank 7 into the
  2048-token context.

Therefore this query is fixed by candidate depth and context budget, not by
source overlap removal or semantic diversity reranking.

## 5. Decision

For the future production switch to the selected candidate knowledge base:

1. Keep raw-vector retrieval as the first-stage ranking.
2. Retrieve a Top-10 candidate pool for context assembly.
3. Preserve retrieval order; do not apply MMR, BGE reranking, RRF, or adaptive
   BM25 routing.
4. Remove only exact source-interval overlap while assembling context.
5. Use a 4096-token retrieved-context budget if the serving model's full prompt
   budget permits it.

The 4096-token recommendation is conditional on measuring the complete
production prompt, because the current service uses verbose metadata and a
character budget rather than the compact token-accounted format in this
benchmark. The production implementation should be made together with the
selected-index rebuild so that source interval metadata is guaranteed. The
active index and current service are intentionally unchanged by this task.

## 6. Artifacts

- Dev matrix:
  `benchmarks/data/retrieval_context_candidates_v1.json`
  (`48fcd3a636923c56afafac1633204b3fd2f998366bf5e0e07b1162151ff6eb9c`)
- Test finalist matrix:
  `benchmarks/data/retrieval_context_finalists_v1.json`
  (`e175e065bf0c36ee08a033bdba080435cb7248466c1d9902ab4772df4b4a9f60`)
- Dev report:
  `var/artifacts/kb_eval/retrieval_context_20260911/context_dev_v2.json`
  (`500ec50f6e2b47a81eab34162a5a677fbf45f2c2bd0e4dbd36d0f06901931c5a`)
- Test report:
  `var/artifacts/kb_eval/retrieval_context_20260911/context_test_v2_final.json`
  (`2fe70a3113e47955ffd0c9ec18d8b22b26e64f334e1fb2bcaeaa170419ec84e2`)

The evaluator and report schema are
`benchmarks/evaluate_retrieval_context.py` and
`benchmarks/retrieval_context_schema.py`.
