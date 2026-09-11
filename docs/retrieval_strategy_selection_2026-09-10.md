# Retrieval Strategy Selection

Date: 2026-09-10. Status: unseen validation complete; raw vector retained for production.

This experiment keeps the previously selected `fine_700_140` chunks,
`Qwen/Qwen3-Embedding-8B` native 4096-dimensional index, cosine distance, and
dual-agent evidence panel fixed. It first compares query formatting, BM25
reciprocal rank fusion, and BGE reranking on the 36-query dev split. The
original test split was not used to tune these strategies. After the adaptive
candidate was frozen, a new 12-query dual-agent test split replaced the already
observed test families and was used once for unseen validation.

All reports are stored under
`var/artifacts/kb_eval/retrieval_strategy_20260910/`. The active
`var/chroma_db` and production configuration were not modified.

## 1. Frozen Matrix

- Query forms: raw query, generic retrieval instruction, and a Chinese
  course-specific instruction.
- First-stage retrieval: vector-only or BM25 plus vector with unweighted RRF
  (`rank_constant=60`).
- Candidate depth: 20. Evidence is reported at the panel's fixed depths
  `1/3/5/10`.
- Reranker: `BAAI/bge-reranker-v2-m3`, applied to the first-stage top 20 and
  returning top 10.
- Strategy matrix SHA-256:
  `c37a680b36502b12da4228a6884a138224c3aa0eb7a153b0b8a36f2f8d3d068f`.

## 2. Dev Results

Values are `(terra-a, terra-b)`. `Complete@5` on the quality-gate group
(`n=25`) remains the primary metric; robustness uses `n=31`.

| Strategy | Quality Complete@3 | Quality Complete@5 | Coverage@3 | Sufficient MRR | Robust Complete@5 |
| --- | --- | --- | --- | --- | --- |
| vector / raw | (0.84, 0.84) | **(1.00, 1.00)** | (0.897, 0.888) | (0.553, 0.440) | **(0.935, 1.000)** |
| vector / generic instruction | (0.84, 0.84) | (0.96, 0.96) | (0.894, 0.913) | (0.558, 0.437) | (0.903, 0.968) |
| vector / course instruction | (0.84, 0.84) | (0.92, 0.92) | (0.894, 0.913) | (0.576, 0.452) | (0.871, 0.935) |
| hybrid RRF / raw | **(0.88, 0.88)** | (0.96, 0.96) | (0.910, 0.910) | (0.547, 0.387) | (0.903, 0.935) |
| hybrid RRF / generic instruction | (0.84, 0.80) | (0.96, 0.96) | **(0.923, 0.914)** | (0.583, 0.423) | (0.903, 0.903) |
| hybrid RRF / course instruction | (0.84, 0.84) | (0.92, 0.92) | **(0.923, 0.920)** | (0.590, 0.430) | (0.871, 0.871) |
| vector / raw / BGE rerank | (0.72, 0.72) | (0.88, 0.88) | (0.831, 0.841) | (0.566, 0.457) | (0.839, 0.806) |
| hybrid RRF / raw / BGE rerank | (0.72, 0.72) | (0.88, 0.88) | (0.831, 0.841) | (0.564, 0.457) | (0.839, 0.806) |
| BM25 / raw | (0.64, 0.60) | (0.92, 0.88) | (0.710, 0.699) | (0.517, 0.357) | (0.871, 0.806) |
| adaptive lexical v1 | (0.84, 0.80) | (1.00, 0.96) | (0.910, 0.896) | (0.603, 0.470) | (0.935, 0.935) |
| **adaptive exact lookup** | **(0.84, 0.84)** | **(1.00, 1.00)** | **(0.910, 0.902)** | **(0.603, 0.470)** | **(0.935, 1.000)** |

BGE reranking added approximately `0.56-0.59 s` per query for the rerank call
alone. Both first-stage candidate pools converged to almost the same reranked
top 10 and the same completion rates.

## 3. Interpretation

Raw vector retrieval is the best unconditional strategy. The later adaptive
extension also preserves complete evidence for both independent labels on every
quality-gate dev query at depth 5 while improving early-rank coverage and MRR.

Query instructions move some directly relevant passages upward, but they also
change the neighborhood enough to remove required companion evidence from
multi-region questions. The generic instruction loses `ret-0014` at depth 5;
the course instruction also loses `ret-0002`.

Unweighted RRF improves quality-gate `Complete@3` from `(0.84, 0.84)` to
`(0.88, 0.88)`, but BM25 candidates displace necessary vector results for
`ret-0010` and one annotation side of `ret-0018`. This is not an acceptable
trade for lower `Complete@5` and robustness.

BGE reranking is the strongest regression. It loses depth-5 completion on
`ret-0010`, `ret-0016`, `ret-0032`, and one annotation side of `ret-0018` and
`ret-0033`. The cross-encoder appears to reward individually relevant passages
while under-preserving the collection of passages required for multi-evidence
answers.

The first adaptive rule was too broad: routing explicit Pandas/scikit-learn API
procedures to BM25 reduced one annotation side at depth 5. The final
`exact_lookup` policy removes API procedures and sends only formula/calculation
queries and precise Latin/digit enumeration lookups to BM25. On this dev split,
8 of 36 queries use BM25 and 28 use vectors. This structurally avoids remote
query embedding for 22% of queries while retaining the raw-vector completion
rates.

## 4. Dev Freeze Decision

Freeze `adaptive_exact_lookup` for unseen validation on the isolated
fine/Qwen-native candidate:

- Formula/calculation and precise enumeration lookups: BM25-only.
- All other queries: raw vector retrieval.
- No query instruction, RRF, or BGE reranking.

This was a validation candidate, not a production switch.

This closes strategy selection on the current dev set. Further tuning here is
not justified: both raw vector and the selected adaptive policy already have
perfect quality-gate completion at depth 5, and repeated variants would
increasingly overfit 25 queries. The next step is a new unseen dual-agent panel
focused on comparison questions, tables, process stages, and multi-region
answers. `adaptive_exact_lookup` is frozen before that panel is evaluated.

## 5. Unseen Validation

Panel v2 keeps the original 36 dev queries and replaces the observed test
families with `ret-0049` through `ret-0060`. Two independent `terra/max`
annotations mark all 12 new queries answerable. Eleven meet the evidence-span
agreement threshold; `ret-0050` remains interpretation-sensitive rather than
being merged into a looser label.

Values are `(terra-a, terra-b)` on the new test split.

| Strategy | Quality Complete@1 | Quality Complete@3 | Quality Complete@5 | Quality MRR | Robust Complete@5 |
| --- | --- | --- | --- | --- | --- |
| **vector / raw** | **(0.545, 0.545)** | (0.909, 0.909) | (0.909, 0.909) | **(0.591, 0.621)** | (0.917, 0.917) |
| adaptive exact lookup | (0.455, 0.455) | (0.909, 0.909) | (0.909, 0.909) | (0.530, 0.561) | (0.917, 0.917) |

Both strategies miss the same multi-region visualization query `ret-0053` at
depth 5. Its evidence on source pages 114 and 119 is completed only when the
page-119 chunk appears at rank 7, so this is a depth/multi-evidence issue rather
than a lexical-routing failure.

The adaptive policy routes three exact-looking queries to BM25. It preserves
depth-3 and depth-5 completion but degrades `ret-0060`: raw vector retrieval
ranks the complete page-235 evidence first, while BM25 ranks related page-234
and page-238 material ahead of it and completes the answer at rank 3. The other
two BM25-routed queries do not improve completion over raw vectors.

The adaptive run embeds 9 instead of 12 queries, a structural 25% reduction.
The observed batch embedding times (`1.47 s` versus `6.89 s`) are provider-run
measurements, not a controlled latency benchmark, so only the reduced embedding
count is used in the decision. Local BM25 and Chroma lookup times are both on
the order of milliseconds for this small corpus.

**Production decision:** retain raw vector retrieval with the selected
`fine_700_140` / Qwen-native index. Do not implement `adaptive_exact_lookup`,
unweighted RRF, or BGE reranking in production. BM25 remains a valid future
option for explicit identifiers or latency-sensitive fallback, but this unseen
panel provides no quality gain that justifies routing normal student queries
away from vectors. Any new lexical rule must be developed on new dev families,
not tuned against this now-observed test split.

The active `var/chroma_db` and production configuration remain unchanged.

## 6. Frozen Reports

- vector/raw:
  `ab779de767b9cd98303f5a3022e8b128d67f7cb36ebe7f0f6ac77a317fdac60a`
- vector/generic instruction:
  `46d5810fdb30b47f4f8a564dbe3fad7a46d77a5159de6126d718605d126540eb`
- vector/course instruction:
  `0a072875b867393b41f45a2c10668b04dfc2bf8045b56870bb9d2082154ef50e`
- hybrid RRF/raw:
  `37ab47adadbfe65698898ee46eddb47086a0cfd2a2d3b12d50d8e46011285c1f`
- hybrid RRF/generic instruction:
  `c99d061d4dc48b85f93f7fc86eecdd9859fa3553ec17fab76be5bfa5550010b7`
- hybrid RRF/course instruction:
  `291fa42bc0cfd99c5dc86b19c09020038c94de9122018d9f4bf8b305f8f0b068`
- vector/raw/BGE rerank:
  `d6f52699980e0d64bc46e2d26ab6c66cdcd0ecf8d8df7361e277d9f7e4d4fede`
- hybrid RRF/raw/BGE rerank:
  `0827f5e1c081a9a1cd266902cebee871d8c71b0eb9d31f937d5e16a165346d49`.
- BM25/raw:
  `70c7480357c9e55f41c5b4bb960672e754e89dd84bbc07b801f48cfb0021a488`
- adaptive lexical v1:
  `e2bcd849dd510848fbb6727af9f7f35b051409cb8c520f0cd8f86fbe63b287a0`
- adaptive exact lookup:
  `3dc4d2141088a4c442ea19535e9029be1f3834058e00a3a82d1e6d6a7c33a98f`.
- unseen panel v2:
  `8997d96f7a595fbfd058accb9355c2b1668299b05e9595432ac6ca423c6081b3`
- vector/raw unseen test:
  `7e9cb20103f0efde63143269f9d8f882fc5da9863ddbcaf1a1fe3f32e7097240`
- adaptive exact lookup unseen test:
  `b73942e41fd84d9a009065d0b02510492f409ca477f92a174f94b3e83523755a`.
