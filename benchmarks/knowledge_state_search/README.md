# Knowledge-State Search Probe

This directory contains the first falsifiable experiment for the
knowledge-state-conditioned evidence search idea. It does not change the
default course-agent route and does not execute web search yet.

## Variants

- `generic`: one shared search trajectory, with no student state.
- `profile_at_answer`: the same shared trajectory, representing profile use
  only in the final answer stage.
- `profile_prompt`: raw student profile is exposed to the search planner.
- `gap_planner`: the deterministic planner exposes core evidence obligations
  and profile-conditioned learner obligations.

The `generic` trajectory is called once per task and cloned across profiles.
This is important: otherwise model sampling noise can look like
profile-conditioned behavior.

## Run

Use an OpenAI-compatible endpoint without putting the key in source files:

```bash
PROFILE_EVAL_API_KEY=... \
PYTHONPATH=src:. \
python -m benchmarks.knowledge_state_search.prompt_probe \
  --concurrency 2 \
  --output var/artifacts/knowledge_state_search/probe_v1.json
```

Analyze the artifact:

```bash
PYTHONPATH=src:. \
python -m benchmarks.knowledge_state_search.analyze_probe \
  var/artifacts/knowledge_state_search/probe_v1.json \
  --output var/artifacts/knowledge_state_search/probe_v1_summary.json
```

The current probe only tests whether planning actions change in a
profile-specific and obligation-aligned way. A second-stage experiment should
execute the generated queries through the existing web search/fetch tools and
measure actual evidence support, citation precision, and search cost.

## Phase B model-proxy relation annotation

After the model-only source-verification gate passes, generate the unlabeled
independent Doubao/Gemini relation packets with:

```bash
PYTHONPATH=src:. \
python -m benchmarks.knowledge_state_search.phase_b_annotation_packets
```

The runtime artifact is written under
`var/artifacts/knowledge_state_search/phase_b_model_annotation_packets/`. The command
creates checksummed public packets and separate data-lead-only canonical ID
maps. It does not create annotation labels, freeze the dataset, or authorize
Phase B method runs.

Run the current 30-pair dev-only structural calibration:

```bash
PYTHONPATH=src:. \
python -m benchmarks.knowledge_state_search.phase_b_relation_annotation \
  --task-split phase_b_dev \
  --limit-pairs 30 \
  --batch-size 1 \
  --output var/artifacts/knowledge_state_search/relation_annotation_dev_smoke
```

Doubao and Gemini label all selected pairs independently. Every disagreement,
every context-uncertain row, and a deterministic stratified 20% sample of clean
agreements is written to a fresh blind priority-subagent packet. The priority
decision is terminal, but the subagent returns atomic proposition checks rather
than choosing a relation directly. Deterministic code derives every five-way
relation from those checks and the same finalized source-level scope. All
non-`absent` checks require contiguous sentence IDs; deterministic code
reconstructs the exact verbatim excerpt span.

The runner writes `relation_run_contract.json`, which binds the complete
request/schema/configuration and source-scope provenance. A 1,440-pair run
fails closed unless two frozen 30-pair dev runs first produce:

```text
var/artifacts/knowledge_state_search/
└── phase_b_relation_calibration_authorization.json
```

The release gates remain agreement `>=0.80`, kappa `>=0.65`, and per-model
derived-relation repeatability `>=0.90`, with zero source-scope conflicts and
zero retry semantic drift.

Historical run contracts v1 and v2 are terminal NO-GO evidence. Under v2,
run 1 completed at `24/30` agreement and kappa `0.716`, but run 2 failed in
MiMo `batch_004` after a non-verbatim quote and routing-relevant retry drift.
No replacement v2 run or full annotation was started.

Run contract v3 is a new preregistered reviewer/schema contract, not a v2
replacement run. It freezes:

- Doubao Seed 2.1 Pro with thinking disabled;
- `vertex_ai/gemini-3.5-flash` with `reasoning_effort=minimal`;
- one pair per request, temperature `0`, max tokens `2048`, timeout `180s`,
  and at most three same-request attempts with semantic-drift rejection;
- deterministic sentence segmentation and sentence-ID evidence;
- a unique request nonce that the schema must echo exactly;
- exact raw-response body hashes, request fingerprints, timestamps, and
  optional provider response IDs;
- exactly two predetermined 30-pair dev runs, with no replacement run;
- unchanged `0.80/0.65/0.90` release thresholds and zero conflict/drift gates.

A non-gating, zero-retry 5-item × 2-run Gemini diagnostic passed 10/10 schema,
nonce, and sentence-ID validations, with proposition-status and derived-relation
repeatability both `1.0`. Gemini does not provide a response ID through the
current gateway, so v3 freshness is established by unique nonce echo,
request fingerprint, exact response-body SHA-256, and timezone-aware request
timestamps rather than by inventing a provider ID.

The two predetermined v3 calibration runs subsequently passed:

```text
run 1: agreement 0.800; kappa 0.696; conflicts 0; drift 0
run 2: agreement 0.867; kappa 0.798; conflicts 0; drift 0
repeatability: Doubao 0.967; Gemini 0.933
```

The machine authorization manifest was created, and the 1,440-pair full
Doubao/Gemini annotation started on July 24, 2026. Dataset freeze and Phase B
method runs remain blocked until all lower-model judgments and terminal
priority-subagent actions are finalized with zero unresolved repair rows.
