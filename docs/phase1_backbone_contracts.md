# Phase 1 Backbone Contracts

Status: authoritative repository contract, restored on 2026-09-08.

This document defines the backbone constraints referenced by `AGENTS.md`. It is
kept in the repository so every contributor and automation agent reads the same
version. Package ownership and migration status remain authoritative in
`docs/architecture_reorg_plan.md`.

## Contract 1: Typed Turn State

- `QueryContext` owns normalized input and preparation facts.
- `RouteDecision` owns the selected family, intent, execution mode, retrieval
  policy, executor and allowed tools.
- `RouteState` owns the stable state passed into route execution.
- Cross-stage control facts use dataclasses, enums, protocols or explicit
  fields. A generic `metadata` mapping may carry diagnostics only; it must not
  steer routing, tool access, retries, fallback or persistence.

## Contract 2: Explicit Control Signals

- Control flow is represented by typed fields and finite events, not magic
  strings hidden in dictionaries.
- `RouteExecutionResult` is the terminal route result contract. It carries
  content, route identity, sources, retrieval attempt/use and degraded state.
  `retrieval_attempted` means a retrieval operation ran; `used_retrieval`
  means usable evidence actually entered the answer.
- Turn lifecycle changes travel through the finite event types in
  `agent/events.py`. API payload dictionaries are boundary projections, not the
  domain control protocol.

## Contract 3: Structural Tool Gating

- A tool-capable route receives an explicit non-empty allowlist from its
  `RouteDecision`.
- Direct-model, deterministic, static, teaching-skill, sandbox and web-pipeline
  modes do not inherit the generic tool registry.
- Tool denial is enforced by construction and registry selection. Prompts must
  not be used as the security or capability boundary.

## Contract 4: Routing Is Data

- `QueryPipeline` is the only query preparation and route-selection entry.
- Deterministic routing policy is an ordered rule table with explicit priority,
  predicates and decision builders.
- Enrichment is declared by `EnrichmentPlan` and evaluated only when required.
- Semantic routing is the explicit fallback after deterministic rules, not an
  extra branch hidden in callers.

## Contract 5: One Turn Entry

- Public sync and streaming chat methods both consume
  `agent.turn_runner.iter_turn_events()`.
- Turn persistence, route execution, fallback and terminal result construction
  have one owner each. API code only adapts HTTP/SSE and session use cases.
- A retry or degraded response must resume inside the selected execution
  boundary; it must not restart the complete route or repeat lifecycle hooks.

## Required Invariants (T1-T7)

- **T1 — Single preparation:** every normal turn obtains its `RouteState` from
  exactly one `QueryPipeline.prepare()` call.
- **T2 — Typed control:** routing and execution control signals are explicit
  typed fields and never read from diagnostic metadata.
- **T3 — Tool isolation:** `TOOL_AGENT` requires a non-empty allowlist; other
  execution modes cannot bind generic-agent tools.
- **T4 — Data-driven routing:** deterministic rules are priority ordered and
  semantic fallback remains outside that rule table as the final fallback.
- **T5 — Shared lifecycle:** sync and streaming public methods use the same turn
  event producer and do not maintain duplicate orchestration paths.
- **T6 — Result preservation:** sources, retrieval state and degraded state from
  the selected handler survive finalization and the terminal turn event.
- **T7 — Runtime boundary:** `runtime/` imports only generic model protocols and
  `shared/`; all domain fallback and tool resolution are injected explicitly.

Any change to these contracts must update the relevant invariant tests in the
same task. Compatibility shims are not an acceptable substitute for migrating
all callers.
