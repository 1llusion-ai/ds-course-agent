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

## Phase B blind annotation packets

After the model-only source-verification gate passes, generate the unlabeled
independent A/B relation packets with:

```bash
PYTHONPATH=src:. \
python -m benchmarks.knowledge_state_search.phase_b_annotation_packets
```

The runtime artifact is written under
`var/artifacts/knowledge_state_search/phase_b_annotation_packets/`. The command
creates checksummed public packets and separate data-lead-only canonical ID
maps. It does not create annotation labels, freeze the dataset, or authorize
Phase B method runs.
