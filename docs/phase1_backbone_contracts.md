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
- Every API turn carries an explicit `CourseContext` into `QueryPipeline` and
  `RouteState`. Chat requests that omit `course_id` retain the
  `data-science-intro` scope. A `(course_id, session_id)` has exactly one student
  owner; the same session ID may be used in different courses, while histories,
  operation locks, title tasks, stream replay and cancellation remain isolated.
  Unready courses may be listed and own empty sessions, but cannot start or
  continue chat generation.

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
- Routing course identity comes from the selected catalogue manifest, carried
  as an immutable typed `QueryContext.course_resources: ResolvedCourse` preparation fact matching
  `course_context.course_id`. The scope guard, semantic classification prompt
  and out-of-course response share its display name and teaching-built coverage. Resolution failure is retained for the whole turn rather than reparsed. Research scope checks and teaching-skill prompts consume the same explicit value. Only an omitted course
  selects the default manifest; an unknown or unavailable identity stays
  neutral. Shared semantic routers receive the name explicitly per call and
  never store request-scoped course identity.

## Contract 5: One Turn Entry

- Public sync and streaming chat methods both consume
  `agent.turn_runner.iter_turn_events()`.
- Turn persistence, route execution, fallback and terminal result construction
  have one owner each. API code only adapts HTTP/SSE and session use cases.
- A retry or degraded response must resume inside the selected execution
  boundary; it must not restart the complete route or repeat lifecycle hooks.
- Successful learning turns may schedule session practice after persisting the
  answer and before the terminal event. This hook is shared by sync and stream,
  uses explicit student/session identity, and never waits for question generation.
  Failed/degraded turns do not schedule new practice. Preparation failures cannot
  turn an already delivered teaching answer into a failed turn.
- Ordinary grounded concept answers load the learner snapshot through their
  declared enrichment plan. Practice guidance is passed to answer generation
  explicitly; it must not be appended to the retrieval query or bound as a tool.

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

## Course coverage and student actions

- `courses/` owns `ResolvedCourse` and `CourseScopeTerm` data contracts only;
  `teaching/course_scope.py` builds coverage through `get_knowledge_map` and the
  mapper's public alias-policy vocabulary. No other course graph is consulted
  when the selected resources are absent. Contextual aliases alone grant no scope.
- `agent/scope_guard.py` owns scope and safety decisions. Academic integrity and
  privacy rules precede course coverage; market quote/investment-service requests
  cannot become learning requests solely by mentioning a course topic. Legal
  analysis and risk education remain allowed. `taxonomy` does not reapply a
  second subject blacklist after the scope guard.
- `scope_terms` is a typed manifest array of textbook topics with `term`,
  `section`, `book_page`, `source_page`. It fills coverage gaps where a topic is
  mentioned inside textbook prose but has no graph KC/TOC title. It never creates
  concept identity, learner events, or synonyms. Missing declarations add no scope.
- Shared prompts render `{{course_name}}`/`{{course_description}}`; only the
  selected manifest's `prompt_path` contributes subject-specific instructions.
- Knowledge-map actions use the loaded graph's course name and node chapter/
  section, carry its captured `course_id` into chat, and reject late graph loads
  or a question tied to another selected course. Profile actions use the same
  course query binding. Chat creation and SSE preserve the captured course ID.
