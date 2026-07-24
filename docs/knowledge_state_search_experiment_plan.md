# Knowledge-State Search Experiment Plan

**Date:** 2026-07-24
**Branch:** `feat/research-knowledge-state-search`
**Status:** Phase B relation calibration is structurally blocked; no full annotation or method claim is authorized.

## 2026-07-21 Status Amendment

The original C1 claim below is **not supported** by R025 or the v2
conflict-aware replay. M3 preserved some support and used fewer retrieval calls
in the latest run, but it did not show stable learner-evidence or precision
superiority over Raw Profile, and its conflict rate was not lower.

Therefore:

- B3 closed-loop remains blocked;
- no 3-repeat v2 matrix will be run;
- the current v2 snapshot is diagnostic, not a final confirmatory benchmark;
- the next active block is the v3 schema and 3-task discriminability pilot
  defined in `docs/knowledge_state_search_confirmatory_schema_v3.md`;
- SFT remains blocked.

## v3 Phase A amendment (2026-07-21)

The v3 Phase A pilot is now frozen and its deterministic Gold-vs-Core
discriminability gate passed under a fixed total source budget. This only
qualifies the three pilot tasks for a method smoke test; it is not evidence
that M1/M2/M3 outperform one another.

Pilot facts:

- 3 new tasks: prerequisite, misconception, and goal;
- 6 profiles, 18 claims, 9 required edges, 30 sources;
- 270 exhaustive claim/edge-source annotations;
- top-k `3`, total source budget `6`;
- learner node gain `3/3`, edge gain `2/3`, complete-path gain `2/3`;
- average learner recall delta `+1.000`, conflict delta `0.000`.

The source text is a curator-written paraphrase grounded in new natural-source
URLs, and annotation is single-curator. Therefore the pilot is diagnostic and
must not be presented as the final paper benchmark.

Next active block:

```text
M1N NullStructured
    → M1 Raw Profile + Core
    → M2 Predicted Gap + Core
    → M3 Counterfactual-Selective Gap + Core
```

All four variants must use the frozen v3 snapshot, the same source budget, and
the same target-attributed evaluator. Closed-loop multi-hop remains gated on
this matrix.

## v3 contract-ablation amendment (2026-07-22)

The first target-contract ablation smoke is complete. `M2U` and `M3U` relax
mandatory learner-target coverage while keeping the predictor, selective gate,
retriever, source budget, and English-query constraint unchanged.

The smoke is diagnostic only:

- `M2U` activated learner targets in `1/3` gap cases, versus `3/3` for `M2`;
- `M3U` activated learner targets in `1/3` gap cases, versus `2/3` for `M3`
  plus one planner schema failure;
- `M3U` gap learner recall was `0.333`, while successful `M3` cases reported
  `1.000`; the failed `M3` case must not be treated as successful evidence;
- the fresh `M3R` residual-planner smoke did not dominate `M3` on learner/path
  quality and remains diagnostic-only.

Artifact:

```text
var/artifacts/knowledge_state_search/confirmatory_v3_contract_ablation_smoke_1repeat.json
```

Interpretation: mandatory target coverage is currently justified as a structural
execution guardrail against obligation-to-query failure, not as an independent
algorithmic contribution. `M3R`, closed-loop search, and SFT remain blocked.

## Experiment-integrity amendment (2026-07-22)

An independent read-only experiment audit found no model-generated ground truth,
model-owned score normalization, v3 gold-claim prompt leakage, or annotation
label leakage in v3 lexical retrieval. The audit initially identified
failure-excluding summaries, shared-plan cost ambiguity, missing telemetry, and
missing preregistered method metrics. These code-level findings were repaired
and independently rechecked.

Current boundary:

```text
Phase B dataset construction: GO
Phase B method claims:         NO-GO
closed-loop multi-hop:         NO-GO
```

The next authorized block is data construction and annotation only. Phase B
methods must not run until selective-gate/neutralization ablations are complete,
the dataset is frozen and independently adjudicated, and all methods use the
repaired failure-adjusted metric and cost contract.

## Phase B exploratory model-proxy annotation amendment (2026-07-23)

The source gate is complete under the explicitly model-only
Doubao/MiMo-plus-priority-subagent protocol: 144/144 sources are accepted,
while `human_verified_count` remains zero.

The original human A/B packet draft was superseded before labels were
collected. The active exploratory protocol is:

- fixed seed `20260723`;
- 1,440 canonical claim/edge-source pairs;
- 1,440 independently ordered blind rows for Doubao;
- 1,440 independently ordered blind rows for Gemini;
- all disagreements and any context-uncertain rows go to the priority Codex
  subagent;
- a deterministic stratified 20% of clean agreements also goes to the priority
  subagent;
- the priority decision is terminal and lower-priority labels are hidden from
  that reviewer;
- public packet fields are allowlisted and exclude canonical IDs, profile
  state, collection roles, discovery metadata, oracle queries, prior model
  reviews, and gold relations;
- checksummed data-lead-only maps recover canonical IDs after annotation.

These outputs are model-only proxy labels, not human annotations or final gold
truth. Calibration evidence currently is:

```text
v1 cross-task agreement:     4 / 12; kappa 0.127
v2 cross-task agreement:     5 / 12; kappa 0.152
v3.2 dev run 1:             22 / 30; kappa 0.610
v3.2 dev run 2:             21 / 30; kappa 0.563
v3.2 repeatability:          Doubao 0.933; MiMo 0.733
v3.3 dev + quote anchors:    21 / 30; kappa 0.564
v3.4 + synthetic examples:   21 / 30; kappa 0.570
full proxy labels:           0 / 1,440
dataset frozen:              false
Phase B methods authorized:  false
```

The structural rubric uses 72 annotation-only claim specifications, 174 atomic
propositions, deterministic relation mapping, retry-drift rejection, and
normalized verbatim evidence quotes. It is not authorized for the full run:
no repeated dev smoke meets agreement `>=0.80`, kappa `>=0.65`, and per-model
relation repeatability `>=0.90`. A final synthetic-boundary-example prompt did
not improve the result, so prompt-only iteration is stopped. Closed-loop
multi-hop remains blocked.

## Fixed-source-scope relation amendment (2026-07-24)

The source-level decomposition is now structurally integrated into pair-level
relation annotation:

- Doubao and Gemini output only ordered atomic proposition checks,
  `needs_context`, and notes; they no longer output `task_scope` or a five-way
  relation;
- both reviewers' five-way relations are derived with the same finalized
  144-source scope artifact;
- the source-scope terminal report binds the consensus, priority manifest/map,
  priority results, final labels, and unresolved queue by SHA-256;
- any `out_of_scope` source with non-`absent` target evidence enters repair
  instead of silently becoming `supported` or `partial`;
- the priority subagent also returns atomic proposition checks, and its final
  relation is derived with the same fixed scope;
- a full 1,440-pair run now fails closed unless a machine-generated
  authorization manifest proves that two frozen 30-pair dev runs both meet the
  existing `0.80/0.65/0.90` gates with zero scope conflicts and zero retry
  semantic drift.

A pre-authorization diagnostic completed at `24/30` agreement with kappa
`0.718` and zero cross-stage scope conflicts. Its paired repeat did not
complete. The first final-contract frozen attempt on July 24, 2026 also failed:
Doubao duplicated proposition `p2` for blind item `d_0919` in `batch_002`, and
routing-relevant judgments changed across all retries. Because the frozen
protocol requires two completed fresh runs, no replacement attempt was started
and no authorization manifest was created. That failure used run contract v1.
Post-failure audit repairs and a preregistered request-isolation change define
the current contract v2: exactly one target-source pair per request. The
reviewer models, prompt, response schema, fixed 30-pair universe, selection
seed, thresholds, and semantic-drift rejection are unchanged. This removes
co-batching as one possible source of cross-item interference but does not
presume the reliability issue is solved. The v2 gate now recomputes the
seed-selected pair universe and binds every consensus summary to the reparsed
raw model judgment before calculating metrics. No parser repair or
retry-until-pass path was added.

The two predetermined v2 runs were then executed. Run 1 completed with
`24/30` agreement, kappa `0.716`, zero source-scope conflicts, and zero
semantic drift. Run 2 failed before completion in MiMo `batch_004` for blind
item `m_0385`: the first response supplied a non-verbatim `p2` evidence quote,
then the retries changed routing-relevant proposition judgments. The machine
authorization builder rejected the incomplete pair of runs and no manifest was
written. This is a terminal v2 NO-GO; no replacement run or full annotation is
permitted under this contract.

Current boundary:

```text
full dual-model judgments:   0 / 2,880
full proxy relation labels:  0 / 1,440
full-run authorization:      absent
dataset frozen:              false
Phase B methods authorized:  false
```

This is a structural NO-GO, not a threshold failure to tune around. Any future
change to batching or reviewer design must be preregistered as a new calibration
version. Closed-loop multi-hop remains blocked.

## Doubao/Gemini sentence-ID preregistration (2026-07-24)

The v2 result above remains terminal. A new run contract v3 replaces MiMo in
the current relation-label gate with `vertex_ai/gemini-3.5-flash` and replaces
model-copied quotes with deterministic sentence-ID evidence. This is a new
reviewer/schema contract, not a replacement v2 run.

Frozen v3 settings:

```text
annotator A:              volcengine_maas/doubao-seed-2-1-pro-260628
annotator A thinking:     disabled
annotator B:              vertex_ai/gemini-3.5-flash
annotator B thinking:     reasoning_effort=minimal
pair batch size:          1
temperature:              0
max tokens:               2048
timeout:                  180 seconds
same-request attempts:    3 maximum, reject semantic drift
calibration runs:         exactly 2 predetermined runs
```

Each response must echo a unique request nonce. For every non-`absent`
proposition, the model returns a contiguous span of sentence IDs; code
reconstructs the exact source substring and rejects unknown, duplicate, or
noncontiguous IDs. Raw evidence binds the request nonce, full request
fingerprint, exact response-body SHA-256, timezone-aware request timestamps,
response model, and optional provider response ID. The current gateway returns
an empty provider ID for Gemini, so no synthetic provider ID is created.

A diagnostic-only, zero-retry 5-item × 2-run check completed 10/10 valid
requests. Proposition-status repeatability and derived-relation repeatability
were both `1.0`. Gemini reported a mean of `848` reasoning tokens per request
under the minimum supported setting; therefore v3 keeps the 2,048-token cap
and records reasoning-token usage separately.

The release gates were unchanged: each run had to reach agreement `>=0.80` and
kappa `>=0.65`; each model must reach repeatability `>=0.90`; scope conflicts
and semantic drift must both be zero. Failed or pending batch artifacts cannot
be resumed or overwritten. No replacement v3 calibration is permitted.

Both predetermined v3 runs passed:

```text
run 1 agreement / kappa:     0.800 / 0.696
run 2 agreement / kappa:     0.867 / 0.798
Doubao repeatability:        0.967
Gemini repeatability:        0.933
source-scope conflicts:      0 in both runs
semantic drift errors:       0 in both runs
v3 calibration runs:         2 / 2 complete
full-run authorization:      accepted
full dual-model annotation:  started 2026-07-24
full proxy relation labels:  0 / 1,440
dataset frozen:              false
Phase B methods authorized:  false
closed-loop multi-hop:       blocked
```

The full run started automatically only after the machine authorization was
created. Its lower-model judgments, terminal priority actions, and final proxy
labels are still pending; therefore no dataset-freeze or method claim is
authorized yet.

### Priority-subagent invalidation of v3 authorization

The owner-authorized priority subagent independently recomputed both v3 runs
and confirmed their nominal metrics, but rejected the authorization mechanism.
The validator hashed `response_body_hex` while parsing an independently stored
sidecar `content` field, and the authorization builder did not enforce the
exact preregistered run1/run2 directories. A tampered-copy test changed the
sidecar judgment and local timestamps while retaining the response-body hash;
the v3 validator still accepted it.

The in-progress full run was stopped at 163 successful Doubao batches and 94
successful Gemini batches, with one interrupted pending artifact per model.
No consensus, priority packet, or final relation label was produced. The
canonical v3 authorization was invalidated and removed from its active path.
All v3 results are diagnostic-only.

Run contract v4 repairs the authorization boundary before any new model call:

- all response content/model/ID/usage fields are decoded from the exact hashed
  response body;
- provider `created` is checked against the local request window;
- the attempt envelope is hashed;
- a tracked preregistration file and its SHA-256 bind exact run1/run2, exact
  full output, and the sole authorization path;
- replacement runs and authorization overwrite are rejected;
- new fail-closed tests cover body/content detachment, timestamp tampering,
  replacement directories, and overwrite attempts.

Current boundary:

```text
v4 calibration runs complete: 0 / 2
canonical authorization:     absent
v4 full annotation:          not started
full proxy relation labels:  0 / 1,440
dataset frozen:              false
Phase B methods authorized:  false
closed-loop multi-hop:       blocked
```

## Claim Map

| Claim | Why it matters | Minimum convincing evidence | Blocks |
|---|---|---|---|
| C1. Counterfactual-selective learner obligations improve learner-claim evidence precision over Raw Profile + Core without losing hard-core support. | This is the smallest algorithmic response to the current over-prediction and fair-baseline result. | Fixed snapshot, claim-level ledger, 4 tasks, 3 repeats, no new hard-core miss, positive paired learner-precision delta on at least 3/4 single-gap tasks. | B0, B1, B2 |
| C2. Observation-conditioned replanning improves coverage-cost trade-off over fixed-depth search. | This tests whether the project is genuinely multi-hop/closed-loop rather than only a structured prompt. | Only run if C1 passes; same obligations, retriever and budget; no support loss and fewer redundant calls. | B3 |

### Anti-claims

- The current pilot does **not** support superiority over Raw Profile.
- The project does **not** currently claim learning gain, transfer improvement,
  BKT quality, topology benefit, RL/bandit benefit, or SFT benefit.
- A term match is not treated as claim support.

## Paper Storyline

### Main paper must prove

1. A learner-state trigger can selectively add learner-specific evidence
   obligations without weakening the shared core contract.
2. The resulting evidence acquisition is more precise than raw profile prompting
   under a fixed evidence snapshot and fixed search budget.

### Appendix / failure analysis

- Trigger-neutralization examples.
- Swapped/wrong-gap negative controls.
- Query redundancy and no-gap unnecessary-search cases.
- Off-contract evidence labels: helpful novel, irrelevant, or distracting.

### Intentionally cut

- BKT and time-series learner modeling.
- TDA/topological gap detection.
- Serendipity optimization.
- RL, contextual bandits, cross-encoder reranking, and SFT.
- Human learning-gain studies.
- Large external datasets and benchmark release.
- Claim dependency DAG edge metrics.

## Experiment Blocks

### B0 — Contract and Metric Sanity

- **Claim tested:** The evaluator measures source-backed claims rather than query
  or label leakage.
- **Dataset:** Existing
  `benchmarks/data/knowledge_state_search_probe_v1.json`.
- **Compared systems:** None; evaluator invariants only.
- **Required checks:**
  - query/header/purpose text is never evidence;
  - `target_requirements` labels are not evidence;
  - empty learner gaps are `N/A`, not success;
  - every source has a stable `source_id`;
  - every ledger entry has `claim_id`, `source_id`, and support status;
  - no evaluator sees the method name.
- **Priority:** MUST-RUN.

### B1 — Fixed Evidence Snapshot Construction

- **Claim tested:** A deterministic local corpus can support claim-level
  comparisons across methods.
- **Dataset:** Four existing tasks:
  `kmeans_initialization`, `overfitting_generalization`,
  `pca_covariance`, `svm_kernel`.
- **Snapshot contents:**
  - 12–20 passages per task;
  - at least one support passage per core claim;
  - support passages for prerequisite, misconception, and goal claims;
  - partial-support, contradiction, and distractor passages;
  - source title, excerpt, URL/provider, capture date, checksum.
- **Compared systems:** Snapshot backend only.
- **Priority:** MUST-RUN.

### B2 — Fair Selective-Obligation Evaluation

- **Claim tested:** Counterfactual-selective obligations improve evidence quality
  over Raw Profile while preserving core support.
- **Profiles:**
  - one no-gap profile per task;
  - one single-gap profile per task;
  - across four single-gap cases: two prerequisite, one misconception, one goal.
- **Methods:**
  - M0: Core-only Generic;
  - M1: Raw Profile + Core;
  - M2: Predicted Gap + Core;
  - M3: Counterfactual-Selective Gap + Core;
  - M4: Gold Gap + Core oracle;
  - M5: Swapped/Wrong Gap + Core negative control.
- **Runs:** 3 repeats per task/profile/method.
- **Primary metrics:**
  - `HardCoreSupportRecall@3`;
  - `LearnerSupportRecall@3` on non-empty gaps.
- **Secondary metrics:**
  - claim-source evidence precision;
  - flat obligation precision/recall/F1;
  - coverage-cost AUC at 1/2/3 retrievals;
  - no-gap unnecessary learner-search rate;
  - contradicted-claim rate;
  - duplicate-query rate;
  - schema validity, calls, tokens, and latency.
- **Pass gate for M3 vs M1:**
  - no new hard-core miss;
  - learner recall non-inferior on at least 3/4 single-gap tasks;
  - positive paired learner-precision delta;
  - no-gap search rate no higher than M1;
  - M3 beats M5 on at least 3/4 single-gap tasks.
- **Failure interpretation:** If M3 fails, do not add a larger model or another
  component. The claim that structured obligations improve search is not yet
  supported.
- **Priority:** MUST-RUN.

### B3 — Minimal Observation-Conditioned Closed Loop

- **Claim tested:** Replanning after each observation improves coverage-cost
  trade-off rather than merely producing a longer plan.
- **Prerequisite:** B2 must pass.
- **Compared systems:**
  - fixed-depth open-loop with the same obligation/query generator;
  - one-action-per-hop closed-loop with a flat claim ledger.
- **Constraints:**
  - maximum 3 hops;
  - `SEARCH` and `FETCH(source_id)` are separate;
  - one planner action per hop;
  - ledger update is mandatory after every observation;
  - `FINISH` is invalid when a hard claim is unsupported.
- **Metrics:**
  - final core and learner support recall;
  - coverage-cost AUC;
  - premature-stop rate;
  - redundant-call rate;
  - planner-call overhead.
- **Priority:** GATED MUST-RUN.

### B4 — Qualitative Failure Analysis

- **Claim tested:** Not a headline claim; diagnoses where personalization helps
  or harms.
- **Labels:** helpful novel evidence, irrelevant evidence,
  distracting/contradictory evidence.
- **Priority:** NICE-TO-HAVE.

## Run Order and Milestones

| Milestone | Goal | Runs | Decision gate | Cost | Risk |
|---|---|---:|---|---|---|
| M0 | Contract/evaluator sanity | deterministic tests | all invariants pass | low | leakage |
| M1 | Build frozen snapshot | 4 task snapshots | every requirement has a source candidate | low–medium | weak/ambiguous passages |
| M2 | Fair open-loop comparison | 4 × 2 profiles × 6 methods × 3 repeats | M3 passes against M1 | medium | small task count |
| M3 | Closed-loop comparison | only after M2 | no support loss and better cost curve | medium | planner overhead |
| M4 | Failure analysis | selected traces | interpret errors only | low | subjective labels |

## Compute and Data Budget

- No GPU is required for B0–B4.
- Use the existing model endpoint only for planner/predictor calls.
- Use a fixed local snapshot for formal comparisons; live web is smoke-test only.
- Do not create new learner logs, large corpora, or human participants in this
  phase.
- Track model calls, token estimates, retrieval calls, and latency per case.

## Risks and Mitigations

- **Small sample scope:** report task-level paired deltas, not broad significance
  claims.
- **Explicit gap leakage:** include misconception and goal cases, plus
  Swapped/Wrong Gap.
- **Evaluator bias:** hide method names and query text from support judging.
- **Term-match inflation:** use support statuses and source excerpts.
- **Over-prediction:** require trigger neutralization and abstention.
- **Closed-loop confounding:** keep the same predictor, retriever, and budget.

## Final Checklist

- [ ] Core contract is identical for all methods.
- [ ] Raw Profile + Core is included as the strongest fair baseline.
- [ ] Gold Gap is labeled as an oracle upper bound.
- [ ] Swapped/Wrong Gap is included as a negative control.
- [ ] Claim-level support is separate from query-term matching.
- [ ] No-gap learner search is measured explicitly.
- [ ] Closed-loop is gated on B2.
- [ ] No unsupported learning-gain or generalization claim is made.
