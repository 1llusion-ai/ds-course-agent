# Experiment Audit Report

**Date:** 2026-07-22
**Project:** `ds-course-agent`
**Scope:** Knowledge-State Search v3 Phase A pilot, repaired-contract confirmation,
target-contract ablation, M3R smoke, and the current Phase B design draft
**Auditor:** Independent read-only GPT-5.5 xhigh fallback reviewer
(`mcp__codex__codex` was unavailable; fallback reviewer used)

## Overall Verdict: WARN

## Integrity Status: warn

No evidence was found that model outputs were silently used as ground truth, and
no model-owned score normalization was found. The reviewer also identified one
overstated M3R tracker sentence; that entry has now been narrowed to “not
overall superior.”

The overall verdict remains `WARN` because the evidence itself is still a
three-task, single-curator, paraphrased-source Phase A pilot. The repaired code
is suitable for Phase B dataset construction, but current artifacts do not
support Phase B method claims or true closed-loop multi-hop.

## Remediation Status

- Failure-adjusted summaries: **PASS**
- M1N/M3R shared-plan cost allocation: **PASS**
- Planner/predictor/counterfactual telemetry: **PASS for future runs**
- Preregistered path/graph/partial/unassigned metrics: **PASS**
- Gold-ID and retrieval-label leakage regression tests: **PASS**
- Dead helper removal: **PASS** (`expected_single_gap_requirement` had no callers and was removed)
- Remaining code-level blocker for Phase B dataset construction: **none**

## Checks

### A. Ground-Truth Provenance: WARN

The v3 method matrix scores against frozen claims, edges, sources, and explicit
annotations rather than model-generated labels
(`benchmarks/knowledge_state_search/confirmatory_schema.py:366-384`,
`benchmarks/knowledge_state_search/confirmatory_evaluator_v3.py:29-34`,
`benchmarks/knowledge_state_search/confirmatory_matrix_v3.py:116-117`).
Fingerprint and exhaustive-annotation checks are implemented
(`benchmarks/knowledge_state_search/confirmatory_schema.py:488-497`,
`benchmarks/knowledge_state_search/confirmatory_validation.py:307-353`).

The limitation is provenance quality, not hidden model ground truth: the pilot
is explicitly single-curator and paraphrase-based
(`benchmarks/data/knowledge_state_search_confirmatory_v3_pilot/annotation_audit.json:2-8`,
`benchmarks/data/knowledge_state_search_confirmatory_v3_pilot/README.md:1-3`).
The v2 snapshot also contains benchmark-only synthetic controls
(`benchmarks/data/knowledge_state_search_snapshot_v2/manifest.json:13-15`).

### B. Score Normalization: PASS

No model-owned maximum, minimum, or prediction statistic is used as a metric
denominator. Claim, edge, path, and source metrics use fixed target/source
counts (`benchmarks/knowledge_state_search/confirmatory_evaluator_v3.py:55-76`,
`benchmarks/knowledge_state_search/confirmatory_evaluator_v3.py:95-151`,
`benchmarks/knowledge_state_search/confirmatory_evaluator_v3.py:182-221`).

The repaired v3 summary reports successful means, failed counts, success rate,
failure-adjusted metrics, raw source/call counts, and cost-adjusted coverage
without self-derived normalization
(`benchmarks/knowledge_state_search/confirmatory_matrix_support.py:250-355`).

### C. Result Existence and Consistency: WARN

The scoped artifacts exist and the principal reported values match the files.
The repaired 3-repeat artifact contains 72 cases and reports the documented M3
values (`var/artifacts/knowledge_state_search/confirmatory_v3_contract_repair_v2_combined_3repeat_analysis.json:3-9`,
`var/artifacts/knowledge_state_search/confirmatory_v3_contract_repair_v2_combined_3repeat_analysis.json:59-73`).

The historical method gate is a quality gate only
(`var/artifacts/knowledge_state_search/confirmatory_v3_contract_repair_v2_combined_3repeat_analysis.json:234-240`).
The historical artifact predates the repaired cost-adjusted fields, so it cannot
support a new cost-adjusted headline claim. The repaired matrix emits
failure-adjusted coverage and coverage per allocated logical model call for
future reruns.

### D. Dead Code and Missing Outputs: PASS

The unused `controlled_profiles.expected_single_gap_requirement` helper was
removed after confirming there were no callers. The repaired method matrix emits
partial-only claim rate, CompletePathRecall@2/@3, graph completion,
unassigned-source rate, token usage when reported by the endpoint, latency, and
cost-adjusted coverage.

### E. Scope Assessment: WARN

The actual Phase A scope is three tasks, six profiles, 18 claims, nine edges,
30 sources, and 270 annotations
(`benchmarks/data/knowledge_state_search_confirmatory_v3_pilot/manifest.json:12-18`).
The split contains only the three pilot tasks
(`benchmarks/data/knowledge_state_search_confirmatory_v3_pilot/splits.json:2-8`).
The project documentation mostly qualifies this correctly and explicitly says
the pilot does not establish general M1/M2/M3 superiority
(`docs/knowledge_state_search_experiment_plan.md:25-28`).

The current Phase B artifact is design-only: 12 tasks, 24 profiles, 72 claims,
48 edges, zero sources, and zero annotations
(`benchmarks/data/knowledge_state_search_confirmatory_v3_phase_b_design/design_manifest.json:2-14`).
The freeze check correctly remains blocked because the final schema manifest is
not present
(`var/artifacts/knowledge_state_search/phase_b_freeze_report.json:5-8`).

### F. Evaluation Type: WARN

| Evaluation | Classification |
|---|---|
| v3 oracle gate | `real_gt` diagnostic upper bound |
| v3 method matrix and repair | `real_gt` scoring on frozen pilot annotations |
| v3 residual replay | `real_gt` deterministic replay, no new model calls |
| v1/v2 controls | mixed `real_gt` and `synthetic_proxy` |
| prompt/term-match probes | `self_supervised_proxy` |
| predictor-only diagnostics | `synthetic_proxy` / controlled-profile evaluation |

The classification is acceptable as long as proxy controls and the Phase A pilot
are not presented as final benchmark evidence.

## Leakage and Cost Findings

- No v3 evidence of gold learner claim IDs entering planner prompts:
  `benchmarks/knowledge_state_search/confirmatory_matrix_support.py:65-91`.
- v3 retrieval ranks by source text/title overlap, not annotation relation:
  `benchmarks/knowledge_state_search/confirmatory_oracle_v3.py:44-64`.
- The v1/v2 source-quality prior is not relation-label leakage, but provider
  quality may correlate with annotation relation
  (`benchmarks/knowledge_state_search/snapshot_retriever.py:21-23`,
  `benchmarks/knowledge_state_search/snapshot_retriever.py:124-132`).
- M1N and M3R now carry an explicit fractional shared-plan allocation in
  per-case logical cost.
- Failed attempts now remain visible through failed counts, success rate, and
  failure-adjusted metrics.
- Telemetry aggregation includes planner, predictor, counterfactual, and shared
  planner requests without truncating fractional shared-token allocations.

## Claim Impact

### Supported with pilot qualifiers

- The typed v3 schema, fingerprinting, and exhaustive annotation contract run.
- The Phase A oracle gate distinguishes Core-only from Gold Gap on the pilot.
- Repaired M3 has positive pilot deltas versus M1 under the mandatory target
  and query-term contract.

### Needs qualification

- Any statement of stable evidence-quality gain must mention the three-task,
  single-curator, paraphrased-source pilot and increased model-call cost.
- Mandatory target coverage is supported as an execution guardrail, not as a
  standalone algorithmic contribution.

### Unsupported

- Final-paper superiority over Raw Profile.
- Phase B confirmatory method claims.
- Closed-loop multi-hop, learning gain, BKT, SFT, or transfer claims.
- M3R as a better headline method.

## Remaining Actions Before Phase B Method Claims or Closed-Loop

1. Freeze Phase B with 12 tasks, natural verbatim source excerpts, and
   independent adjudication before method runs.
2. Complete selective-gate and neutralization ablations before choosing the
   Phase B method candidate.
3. Rerun methods under the repaired metric/cost contract; historical artifacts
   cannot retroactively supply tokens, latency, or failure-adjusted fields.
4. Keep R044's corrected wording and do not promote M3R to a headline method.

## Go / No-Go

- **GO:** Phase B dataset construction and additional diagnostic ablations.
- **NO-GO:** Phase B method claims and true observation-conditioned
  multi-hop experiments until the actions above are addressed.

## Post-audit construction progress (2026-07-23; not a new independent audit)

Since the read-only audit above, source construction and the source gate have
completed with 144/144 model-only verifications. The human A/B packet draft was
superseded before labels were collected. The active exploratory protocol uses
independent Doubao/MiMo labels plus terminal priority-subagent review of all
disagreements and a deterministic 20% agreement sample.

Calibration did not stop at the first 12-pair smoke. v1 produced `4/12`
agreement with Cohen's kappa `0.127`, and v2 produced `5/12`, kappa `0.152`.
A dev-only structural track then introduced 72 annotation-only claim
specifications, 174 atomic propositions, deterministic five-way mapping,
same-request semantic-drift rejection, and normalized verbatim evidence
quotes. Repeated v3.2 30-pair runs produced `22/30`, kappa `0.610`, then
`21/30`, kappa `0.563`; Doubao relation repeatability was `0.933`, but MiMo
was `0.733`. v3.3 quote containment passed but remained `21/30`, kappa
`0.564`. A final v3.4 prompt with six synthetic non-benchmark boundary examples
also remained `21/30`, kappa `0.570`. Prompt-only calibration is stopped.
These diagnostics remain model-only and do not authorize the full run.

This progress does not change the audit verdict or method boundary:

```text
full dual-model judgments:   0 / 2,880
full proxy relation labels:  0 / 1,440
dataset frozen:              false
Phase B methods authorized:  false
```

The next integrity-relevant checkpoint is a passing repeated dev calibration:
agreement at least `0.80`, kappa at least `0.65`, and per-model relation
repeatability at least `0.90`.
Even after full completion, these labels must be described as model-only proxy
annotations unless a separate external validation stage is completed.

## Fixed-scope authorization progress (2026-07-24; not a new independent audit)

The pair-level contract now consumes the terminal 144-source scope artifact
instead of asking each pair reviewer to rejudge scope. Doubao, MiMo, and the
terminal priority subagent return atomic proposition checks; deterministic code
derives the relation using the same fixed scope. The implementation also adds:

- complete source-scope provenance hashes;
- target-to-task consistency checks;
- repair routing for non-`absent` evidence under fixed `out_of_scope`;
- complete request fingerprints including endpoint and request payload;
- a machine-generated calibration authorization manifest;
- a fail-closed full runner that cannot start all 1,440 pairs without that
  manifest.

A pre-gate diagnostic produced `24/30` derived-relation agreement, kappa
`0.718`, and zero scope conflicts. Its repeat did not complete. The first
final-contract frozen run on July 24, 2026 also failed before completion:
Doubao `batch_002` duplicated proposition `p2` for `d_0919`, and
routing-relevant judgments changed across all retries. The failure artifact
was retained. A replacement run was not launched, because retrying until two
runs pass would undermine the preregistered two-run gate. The failed artifact
used run contract v1; post-failure audit repairs bumped the current contract to
v2, and no v2 model calibration exists.

The integrity boundary therefore remains:

```text
calibration authorization:   absent
full dual-model judgments:   0 / 2,880
full proxy relation labels:  0 / 1,440
dataset frozen:              false
Phase B methods authorized:  false
```

This is a structural NO-GO. The existing thresholds were not lowered, and no
full relation annotation or method run was started. Engineering validation is
643 passed, 14 skipped, with one pre-existing offline-reranker warning; full
ruff, format, diff, and JSON checks pass.
