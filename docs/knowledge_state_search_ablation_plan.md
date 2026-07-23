# Knowledge-State Search Ablation Plan

**Date:** 2026-07-22
**Scope:** v3 Knowledge-State Search Phase A diagnostics before choosing any
Phase B method candidate.
**Status:** Planning document only. Do not treat any Phase A number as a Phase B
method claim.

## 1. Current evidence boundary

The repaired v3 Phase A pilot has useful diagnostic signal, but it is not a
paper-grade benchmark:

- dataset: 3 tasks, 6 profiles, 18 claims, 9 required edges, 30 sources;
- annotations: single curator;
- source text: curator paraphrases grounded in URLs, not frozen verbatim web
  excerpts;
- audit status: code-level blockers are repaired, but overall integrity remains
  `WARN` because the evidence is still a small Phase A pilot.

The repaired 3-repeat Phase A confirmation reported a positive M3-vs-M1 pilot
signal under the strict target/query contract: core `+0.067`, gap learner
`+0.889`, strict precision `+0.110`, path `+0.389`, conflict `-0.031`, with
about `+1.444` extra logical model calls. That result is enough to motivate
ablations, not enough to select a final method for Phase B claims.

The independent audit requires two missing isolations before choosing a Phase B
candidate:

1. whether the counterfactual selective gate contributes beyond predicted
   obligations (`M3` vs `M2`), and
2. whether paired no-gap neutralization is necessary, rather than a cheaper
   local/empty neutralization.

## 2. Decision target

This plan chooses the smallest method worthy of Phase B confirmation. The
candidate can be:

- `M2-AllPred-Strict` if predicted learner obligations work but the selective
  gate is not independently useful;
- `M3-PairedCF-Strict` only if the selective gate beats `M2` and paired
  neutralization beats the local/empty alternative;
- no Phase B method candidate if neither `M2` nor `M3` remains non-inferior to
  `M1-RawProfile` under the repaired failure-adjusted metric/cost contract.

Closed-loop multi-hop, SFT, live-web evaluation, and residual planners remain
blocked until this decision is made and Phase B data is frozen.

## 3. Shared controls for every ablation

All ablations must share these controls unless the variant definition explicitly
changes one field.

| Control | Required setting |
|---|---|
| Dataset | Frozen v3 Phase A pilot for diagnostics; frozen Phase B only after construction/adjudication. |
| Retrieval | `V3LexicalRetriever`, generic lexical overlap only; no annotation/provider relation labels. |
| Source budget | `top_k=3`, `max_queries=3`, total selected source budget `6`. |
| Model | Same endpoint/model as the repaired run, temperature `0.0`, same timeout/retry policy. |
| Query language | English `SEARCH`/`REFINE` queries. |
| Target contract | Enforced for candidate methods: every visible learner requirement must be targeted by a `SEARCH`/`REFINE` action, and the query must overlap its English `search_terms`. |
| Evaluation | Same target-attributed v3 evaluator; evaluator never sees method name or gold learner IDs in planner prompts. |
| Cost | Report planner, predictor, counterfactual, retrieval calls, allocated logical model calls, tokens when available, latency, and coverage per allocated logical call. |
| Failures | Keep failed cases in the artifact; report successful means and failure-adjusted means. |
| Pairing | Primary comparisons are paired by `(task_id, profile_id, repeat)`, with separate all-profile and gap-profile summaries. |
| Caching | Reuse the same original predictor output for all variants of a case. Do not duplicate predictor calls across `M2`, `M3-PairedCF`, and neutralization variants. |
| Run discipline | Interleave variants within each task/profile/repeat block to reduce endpoint drift; do not run one method in a large block before the others. |

## 4. Exact variants

### 4.1 Must-run Phase A diagnostic variants

| Name | Planner input | Counterfactual neutralization | Target contract | Purpose |
|---|---|---|---|---|
| `M1N-SharedCore` | Core requirements only through structured planner interface; one shared task plan allocated across profiles. | None | Core-only. | Controls for structured prompt format and shared-plan accounting. |
| `M1-RawProfile` | Core requirements plus raw student profile prompt. | None | Core-only. | Strong baseline; candidate methods must beat or match this. |
| `M2-AllPred-Strict` | Core + all predictor obligations. | None | Enforced. | Tests whether typed predicted obligations are sufficient without the selective gate. |
| `M3-PairedCF-Strict` | Core + obligations that disappear under the task's frozen no-gap profile. | Current paired no-gap profile for the same task; `neutral_learning_goal` equals the paired no-gap learning goal. | Enforced. | Tests the full proposed selective gate. |
| `M3-LocalCF-Strict` | Core + obligations that disappear under local trigger neutralization. | Same original profile with only the claimed trigger neutralized: weak concept removed and marked mastered; misconception removed; learning goal set to `""`. | Enforced. | Tests whether paired no-gap neutralization is better than the cheaper local/empty alternative. |

`M3-LocalCF-Strict` is the only required neutralization challenger. Do not run
both a local-trigger and a fully blank-profile challenger unless this single
comparison is ambiguous.

### 4.2 Already-smoked target-contract diagnostics

| Name | Difference from strict counterpart | Purpose | Required action |
|---|---|---|---|
| `M2U-AllPred-Unconstrained` | Same as `M2`, but `enforce_target_contract=False`. | Checks whether learner obligations are actually executed as queries. | Do not expand beyond a 1-repeat diagnostic unless the old smoke lacks repaired failure/cost fields needed for interpretation. |
| `M3U-PairedCF-Unconstrained` | Same as `M3-PairedCF`, but `enforce_target_contract=False`. | Checks whether target coverage is a guardrail against obligation-to-query failure. | Same as above. |

The target contract is a shared execution guardrail, not an independent
algorithmic claim. The existing smoke already showed lower learner-target
activation when the contract was relaxed; the minimum next work is selective
and neutralization isolation.

### 4.3 Conditional only

| Name | Run only if | Purpose |
|---|---|---|
| `M3-CountMatchedDrop-Strict` | `M3-PairedCF` removes at least 10% of predicted obligations or at least 25% of cases have more than one predicted obligation. | Tests whether any count-matched pruning would help, rather than the counterfactual criterion. |
| `M4-GoldGap` | A new dataset split is being qualified, not for method selection on the existing pilot. | Dataset discriminability upper bound. |
| `M5-WrongGap` | Phase B dataset needs a negative-control sanity check. | Confirms that arbitrary learner gaps do not look good. |

## 5. Metrics

### 5.1 Gate-only diagnostics

These are computed before planner evidence metrics and are the cheapest way to
know whether `M3` has an independent mechanism.

| Metric | Definition | Why it matters |
|---|---|---|
| `predicted_obligation_count` | Number of obligations emitted by the original predictor. | Separates predictor sparsity from planner failure. |
| `selected_obligation_count` | Number kept by the selective gate. | Shows whether the gate actually changes `M2`. |
| `drop_rate` | `(predicted - selected) / predicted`, on cases with predictions. | If near zero, `M3` is not meaningfully different from `M2`. |
| `gold_aligned_selected_recall` | Fraction of active learner claims matched by kept obligations. | Detects false drops of needed learner evidence. |
| `selected_obligation_precision` | Fraction of kept obligations aligned with active learner claims/triggers. | Detects false keeps. |
| `no_gap_selected_fpr` | No-gap cases with any kept learner obligation. | Must stay zero or near zero. |
| `paired_vs_local_selection_disagreement` | Cases where paired and local neutralization keep different obligation sets. | If zero, paired neutralization has no demonstrated value. |
| `counterfactual_failure_rate` | Failed counterfactual predictor calls divided by attempted calls. | Any repeated failure makes `M3` operationally fragile. |

Gold alignment in Phase A may use the frozen canonical learner claims and
profile triggers, but this is still diagnostic because Phase A annotations are
single-curator.

### 5.2 End-to-end evidence metrics

Report all metrics as paired deltas and as method summaries. The headline
summary must use failure-adjusted means.

Primary metrics:

- `ConflictAwareCoreRecall` / `core_recall`;
- gap-profile `ConflictAwareLearnerRecall` / `learner_recall`;
- `StrictTargetPrecision` and `GradedTargetPrecision`;
- `FullEdgeRecall`;
- `CompletePathRecall@2` and `CompletePathRecall@3`;
- `GraphCompletionRate`;
- `ClaimConflictRate`.

Safety/cost metrics:

- `PartialOnlyClaimRate`;
- `ContradictionRate` / contradiction-source rate;
- `DistractorRate`;
- `UnassignedSourceRate`;
- learner target activation rate;
- learner-support source acquisition rate;
- search calls and selected-source count;
- allocated logical model calls;
- tokens and latency when the endpoint reports them;
- coverage per allocated logical model call.

## 6. Run order

### Step A0 — Artifact hygiene

1. Confirm dataset fingerprints and schema validation pass.
2. Confirm the runner emits failure-adjusted metrics, cost-adjusted coverage,
   tokens/latency when available, and failed-case records.
3. Do not modify annotations after any method trace is inspected.

Stop if any of these fail.

### Step A1 — Gate-only diagnostic pass

Run original predictor and both counterfactual neutralizers for every
`task/profile/repeat` in the Phase A pilot, using 3 repeats. Cache all outputs.
No planner calls are needed for this step.

Stop early if:

- `M3-PairedCF` selection equals `M2` on more than 95% of predicted cases; or
- no-gap selected-obligation FPR is nonzero in more than one no-gap case; or
- any neutralization strategy repeatedly drops a gold-aligned prerequisite,
  misconception, or goal obligation.

If stopped here, select `M2-AllPred-Strict` as the only possible Phase B method
candidate, subject to the `M2` vs `M1` gate below. Do not spend Phase A budget on
`M3` planner runs that cannot demonstrate a selective mechanism.

### Step A2 — End-to-end strict ablation packet

Run `M1N-SharedCore`, `M1-RawProfile`, `M2-AllPred-Strict`,
`M3-PairedCF-Strict`, and `M3-LocalCF-Strict` for 3 repeats on the Phase A
pilot, reusing the cached predictor/counterfactual outputs from A1.

Compute paired deltas:

1. `M2-AllPred-Strict - M1-RawProfile`;
2. `M3-PairedCF-Strict - M2-AllPred-Strict`;
3. `M3-PairedCF-Strict - M3-LocalCF-Strict`;
4. `M3-PairedCF-Strict - M1-RawProfile`.

### Step A3 — Target-contract check only if needed

If the available target-contract smoke cannot be interpreted under the repaired
cost/failure schema, run exactly one fresh repeat of:

- `M2-AllPred-Strict`;
- `M2U-AllPred-Unconstrained`;
- `M3-PairedCF-Strict`;
- `M3U-PairedCF-Unconstrained`.

Do not expand `M2U/M3U` to 3 repeats unless the strict candidate passes all
other gates but target activation remains the only unresolved reviewer question.

### Step A4 — Candidate decision

Apply the stop/go gates in Section 8. Record the selected candidate and the
failed alternatives before constructing or running Phase B methods.

## 7. Cost budget

The Phase A diagnostic budget is bounded by logical model calls, not wall-clock
or GPU time. No GPU is required.

For 3 tasks × 2 profiles × 3 repeats = 18 cases:

| Component | Calls |
|---|---:|
| Shared original predictor outputs | `18` |
| `M1N-SharedCore` planner, shared across profiles | `9` |
| `M1-RawProfile` planner | `18` |
| `M2-AllPred-Strict` planner | `18` |
| `M3-PairedCF-Strict` planner | `18` |
| `M3-LocalCF-Strict` planner | `18` |
| Paired counterfactual predictions | at most `36` because predictor outputs at most 2 obligations per case |
| Local/empty counterfactual predictions | at most `36` |
| **Hard ceiling for A1+A2** | **`171` logical calls** |

Typical cost should be lower because no-gap profiles should emit no obligations
and single-gap profiles usually emit one obligation. If the optional A3
1-repeat target-contract check is needed, add at most `48` logical calls. The
absolute Phase A ceiling is therefore `219` logical calls.

Stop the ablation packet if either ceiling would be exceeded or if endpoint
failures make success rate fall below `95%`; do not silently exclude failures.

## 8. Stop/go gates

### 8.1 `M2` may be a Phase B candidate only if it beats raw profile

On Phase A diagnostics, `M2-AllPred-Strict` must satisfy all of:

- all-profile core recall delta vs `M1` >= `-0.05`;
- gap-profile learner recall delta vs `M1` >= `0.25`;
- strict precision delta vs `M1` >= `0.05`;
- claim conflict delta vs `M1` <= `+0.02`;
- complete path recall delta vs `M1` >= `0.00`;
- no-gap selected-obligation FPR equals `0`;
- coverage per allocated logical model call is not worse than `M1` by more than
  `5%`, or the planned Phase B claim must explicitly be quality-at-higher-cost
  rather than cost-adjusted superiority.

If this gate fails, there is no Phase B method candidate. Continue only with
Phase B dataset construction, not method claims.

### 8.2 Selective gate is justified only if `M3-PairedCF` beats `M2`

`M3-PairedCF-Strict` may replace `M2` as the Phase B candidate only if it
satisfies all of:

- selection differs from `M2` on at least one meaningful gap case, otherwise no
  selective mechanism was exercised;
- gap-profile learner recall delta vs `M2` >= `0.00`;
- all-profile core recall delta vs `M2` >= `-0.05`;
- strict precision delta vs `M2` >= `0.03`;
- claim conflict delta vs `M2` <= `+0.02`;
- complete path recall delta vs `M2` >= `0.00`;
- selected-obligation precision is higher than all-predicted precision, or
  false-positive selected obligations are lower;
- coverage per allocated logical call is not worse than `M2` by more than `5%`.

If this gate fails, choose `M2-AllPred-Strict` if Section 8.1 passed. Do not
claim a counterfactual selective-gate contribution.

### 8.3 Paired neutralization is justified only if it beats local/empty neutralization

`M3-PairedCF-Strict` may be selected over `M3-LocalCF-Strict` only if it
satisfies all of:

- lower or equal false-drop rate for gold-aligned learner obligations;
- lower or equal no-gap selected-obligation FPR;
- gap-profile learner recall delta vs local >= `0.00`;
- strict precision delta vs local >= `0.00`;
- complete path recall delta vs local >= `0.00`;
- conflict delta vs local <= `+0.02`;
- counterfactual failure rate no higher than local.

If paired and local neutralization are indistinguishable, do not claim paired
neutralization as a contribution. Prefer the simpler method only if it also
passes the `M2` and `M1` gates; otherwise fall back to `M2`.

### 8.4 Target contract remains a guardrail

Keep the mandatory target/query contract in any Phase B candidate if relaxing it
causes either:

- learner target activation to drop below strict variants; or
- gap learner recall/path recall to drop; or
- planner schema failures to become hidden successes.

Even if the strict contract is kept, present it as an execution contract, not as
an algorithmic contribution.

## 9. Failure interpretation

| Observation | Interpretation | Decision |
|---|---|---|
| `M3-PairedCF` and `M2` keep the same obligations. | The selective gate was not exercised; any evidence delta is planner sampling or ID-prefix noise. | Do not select or claim `M3`; evaluate `M2` only. |
| `M3-PairedCF` improves learner recall but loses core/path or precision. | Learner query may be displacing core evidence. | Do not enter closed loop; choose `M2` or no candidate. |
| `M3-PairedCF` improves quality but cost-adjusted coverage worsens. | Counterfactual calls buy quality at too much cost. | Candidate only if Phase B claim is explicitly quality-at-higher-cost; otherwise choose `M2`. |
| `M3-LocalCF` matches `M3-PairedCF`. | Paired no-gap neutralization is not an independent component. | Do not claim paired neutralization; prefer simpler variant or `M2`. |
| `M3-LocalCF` beats paired. | The paired no-gap profile may be over-constraining or mismatched. | Do not use paired neutralization in Phase B. |
| Relaxed target variants match strict variants. | Mandatory target coverage may be unnecessary for the chosen dataset. | Keep only if needed for schema safety; do not claim it improves evidence. |
| Relaxed target variants fail to activate learner targets. | Target contract prevents obligation-to-query failure. | Keep strict target contract as a guardrail. |
| No-gap FPR is nonzero repeatedly. | Predictor/gate over-personalizes generic profiles. | Block candidate; fix predictor contract before Phase B methods. |
| Schema or API failures exceed 5%. | Operational result is unstable. | Rerun only after fixing reliability; do not exclude failures. |

## 10. Phase B use of this plan

Phase A ablations are diagnostic only. They may select a Phase B candidate, but
they do not support Phase B claims.

Before any Phase B method run:

1. construct 12 new tasks with natural verbatim source excerpts;
2. freeze task/source/claim/edge/annotation files and fingerprints;
3. complete dual human review or dual judge plus adjudication;
4. pass the Gold Gap vs Core-only dataset discriminability gate;
5. preregister the selected method, baselines, metrics, and stop/go gates;
6. run all methods under the repaired failure-adjusted metric and cost contract.

Minimum Phase B method matrix:

- If Phase A selects `M2`: run `M1N`, `M1`, `M2`, and `M4` dataset upper bound;
- if Phase A selects `M3-PairedCF`: run `M1N`, `M1`, `M2`, `M3-PairedCF`,
  `M3-LocalCF`, and `M4` dataset upper bound;
- include `M5-WrongGap` only as a dataset sanity check, not as a headline
  method baseline.

A Phase B method claim is allowed only if the selected candidate passes the
same non-inferiority, precision, conflict, path, and cost gates on the frozen
12-task adjudicated set. Closed-loop multi-hop remains blocked until then.

## 11. Ablations to skip

Skip these until the above gates pass:

- `M3R` / core-anchored residual planner: the fresh smoke did not dominate `M3`
  on learner/path/strict precision, so it is not a Phase B candidate now;
- observation-conditioned closed loop and fixed-depth multi-hop comparisons;
- SFT, RL, bandits, cross-encoder reranking, larger-model sweeps, or prompt-only
  patch variants;
- top-k/source-budget hyperparameter sweeps before choosing the method;
- live web experiments for method claims;
- v1/v2 synthetic or mixed-proxy datasets for headline evidence;
- broad profile-field ablations already superseded by typed obligations;
- multiple neutralization challengers unless `M3-LocalCF` is ambiguous;
- count-matched random/drop controls unless the selective gate actually drops a
  meaningful number of obligations.

The goal is not to maximize experiment count. The goal is to answer the two
reviewer questions that currently block method selection: whether selective
gating adds value beyond predicted obligations, and whether paired no-gap
neutralization is necessary.
