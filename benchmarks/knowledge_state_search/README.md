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
independent Doubao/MiMo relation packets with:

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

Doubao and MiMo label all selected pairs independently. Every disagreement,
every context-uncertain row, and a deterministic stratified 20% sample of clean
agreements is written to a fresh blind priority-subagent packet. The priority
decision is terminal, but the subagent returns atomic proposition checks rather
than choosing a relation directly. Deterministic code derives every five-way
relation from those checks and the same finalized source-level scope. All
non-`absent` checks require normalized verbatim excerpt quotes.

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

Run contract v2 is preregistered at exactly one target-source pair per request.
This changes only request isolation: reviewer models, prompt, response schema,
selection seed, fixed 30-pair universe, thresholds, and retry-drift rejection
remain unchanged. The single-pair contract removes co-batching as one possible
source of cross-item interference; it does not assume schema reliability is
fixed before the two v2 runs. The authorization gate also recomputes the
seed-selected pair universe and requires every consensus judgment to match its
reparsed raw response exactly. No parser repair or retry-until-pass path is
added.

The July 24, 2026 run-contract-v1 calibration is NO-GO. A diagnostic
run reached `24/30` agreement and kappa `0.718`, but the paired diagnostic
failed. The first frozen run then failed in Doubao `batch_002`: blind item
`d_0919` duplicated proposition `p2`, and routing-relevant judgments changed
across retries. That artifact used run contract v1. Post-failure audit repairs
and the preregistered single-pair isolation rule define run contract v2, under
which exactly two predetermined runs were attempted. Run 1 completed at
`24/30` agreement, kappa `0.716`, zero source-scope conflicts, and zero
semantic drift. Run 2 failed in MiMo `batch_004` for `m_0385`: the first
response used a non-verbatim `p2` quote, and the subsequent responses changed
routing-relevant judgments. This is a terminal v2 NO-GO. No replacement run,
authorization manifest, or full annotation was started.
