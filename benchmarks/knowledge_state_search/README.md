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
  --batch-size 4 \
  --output var/artifacts/knowledge_state_search/relation_annotation_dev_smoke
```

Doubao and MiMo label all selected pairs independently. Every disagreement,
every context-uncertain row, and a deterministic stratified 20% sample of clean
agreements is written to a fresh blind priority-subagent packet. The priority
decision is terminal. The structural prompt derives five-way labels from
annotation-only atomic propositions and requires normalized verbatim excerpt
quotes for every non-`absent` proposition. Resulting labels are explicitly
model-only proxies.

The best repeated dev calibration is currently below the frozen release gates:
v3.2 reached `22/30` agreement with kappa `0.610`, then `21/30` with kappa
`0.563`; v3.3 remained `21/30`, kappa `0.564`; v3.4 synthetic boundary
examples remained `21/30`, kappa `0.570`. Prompt-only calibration is stopped,
and full annotation is not authorized.
