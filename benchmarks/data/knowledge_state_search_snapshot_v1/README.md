# Knowledge-State Search Evidence Snapshot v1

This is a fixed local evidence snapshot for the B1 offline evaluation.

## Provenance

- Captured: `2026-07-21T05:07:38.479342+00:00` UTC
- Capture path: project `web_search` + `web_fetch`
- Tasks: four existing data-science multi-hop questions
- Sources: 16 curated excerpts/snippets
- Annotations: 30 conservative claim/source labels

`sources.jsonl` intentionally contains only source metadata and curated page
excerpts. It does not contain planner queries, action purposes,
`target_requirements`, or method names. `annotations.jsonl` is an explicit
claim/source evaluation layer; unannotated pairs are treated as `missing`.

This snapshot is an initial B1 fixture, not a final benchmark. The main
limitation is that annotations are single-pass manual conservative labels and
should receive a second independent review before paper claims are made.
