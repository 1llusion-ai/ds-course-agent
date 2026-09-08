# Architecture Reorganization Plan

Status: src-layout and layered package migration implemented (2026-09-08); uncommitted.

## Layered migration

The approved target separates orchestration, model infrastructure, teaching,
retrieval, and web research. Borrow pi's dependency boundaries, not its generic
agent product surface. Preserve QueryPipeline, LearningEvent, Vue, and SSE.

| Stage | Scope | Status |
| --- | --- | --- |
| M1 | Move model runtime/stream/context into runtime; inject domain fallback; move shared trace; enforce dependency boundary | Complete, uncommitted |
| M2 | Extract route execution from AgentService without changing dispatch or lifecycle | Complete, uncommitted |
| M3 | Move teaching state, retrieval, and web research to their owning packages | Complete, uncommitted |
| M4 | Move agent orchestration/routing/hooks; remove the old rag package after all consumers migrate | Complete, uncommitted |

Each stage updates all consumers and tests together, removes replaced paths
without shims, and passes full pytest, Ruff, and the route harness. Do not create
empty future packages. Historical progress logs describe paths at that time.

```text
src/ds_course_agent/
  agent/       service, turn runner/events, routing, handlers, hooks, finalizer
  runtime/     model calls, stream decoding, context, messages, capability protocols
  teaching/    learner state/provider, learning events, profiles, graph, skills
  retrieval/   RAG service, hybrid retriever, reranker
  research/    web research pipeline, policy, fetch, models
  tools/       atomic tools, registry, execution sandbox
  api/         HTTP/SSE adapters and application services
  shared/      configuration, trace, generic messages/storage/model factories
  kb/          offline knowledge-base construction
```

> **Historical/stale path note.** The M2/M3 descriptions below retain paths
> used during those stages, including `rag/route_executor.py` and the earlier
> `src/ds_course_agent/rag/` destination. They are historical migration
> records, not current import instructions. The M4 owners are
> `agent/route_executor.py`, `agent/service.py`, `agent/routing/`,
> `agent/handlers.py`, `agent/events.py`, `agent/hooks/`, `teaching/`,
> `retrieval/`, `research/`, and `shared/` as shown in the current layout.

Runtime must not import domain packages, including tools. A typed tool resolver
and a fallback callable are injected by the composition root. Generic message
conversion lives in runtime; learner-context rendering remains in the domain.
Shared trace moves with M1 because runtime and shared context governance must
not import rag simply to emit telemetry.

M1 verification: 488 passed, 14 skipped, 1 existing optional-reranker warning;
route tests 36 passed; route harness 119/119, Unexpected RAG 0. Runtime boundary
tests cover import direction, fresh-process loading, removed paths, injected
fallback isolation, no retries after partial streams, and shared request trace.

M2 places dispatch, buffered execution/finalization, streaming exception handling,
and observation-only stream-end hooks in `rag/route_executor.py`. It follows the
existing module-function pattern of turn_runner; RouteAgent is the typed dependency
contract. AgentService no longer exposes the six former execution private methods.
The executor remains under rag until the M4 orchestration package move.
Verification: 496 passed, 14 skipped, 1 existing warning; route tests 36 passed;
route harness 119/119, Unexpected RAG 0. AgentService is now 549 lines.

M3 moves seven teaching modules (learner_state, profile_models, learning_events,
memory_core, knowledge_mapper, course_graph, skill_system), three retrieval modules
(service, hybrid_retriever, reranker), and four research modules (pipeline, policy,
fetch, models). Skill resources stay at teaching/skills and data/storage paths do
not change. The rag package initializer no longer re-exports Agent/tools/retrieval;
consumers import the owning modules directly. Research still consumes orchestration
contracts from rag until M4; M3 is not a claim of complete domain independence.
Verification: 501 passed, 14 skipped, 1 existing warning; route tests 36 passed;
route harness 119/119, Unexpected RAG 0. Five new tests cover independent imports,
absence of old module paths, and no domain-to-API imports.

M4 moves orchestration to `src/ds_course_agent/agent/`: service.py, routing/, hooks/, handlers.py,
events.py, turn_runner.py, route_executor.py, result_finalizer.py, message_context.py,
prompt.py, model_fallback.py, scope_guard.py, taxonomy.py. Code execution now lives
in tools/code_executor.py. The single existing handlers module stays a file rather
than gaining an unnecessary package layer. Old rag and top-level hooks packages
are removed; their local bytecode caches were archived outside the workspace.
All code imports and monkeypatch targets use the new paths. Package imports do
not eagerly initialize AgentService. Verification: 503 passed, 14 skipped,
1 existing warning; route tests 36 passed; harness 119/119, Unexpected RAG 0.

This completes the approved directory migration, not a rewrite of the execution
engine. Research still uses agent route/event contracts and the existing finalizer;
code tools still use routing text utilities. Further dependency inversion, if needed,
is a separate behavioral refactor, not hidden inside this package move.

## Final top-level layout

```text
src/ds_course_agent/      Python package using src-layout
web/                      Vue frontend application
tests/                    Unit and integration tests
scripts/                  Developer and maintenance scripts
benchmarks/                     Evaluation datasets, metrics, and runners
data/                     Tracked course metadata and sample data
var/                      Local runtime state; ignored except .gitkeep files
docs/                     Documentation and prompts
deploy/                   Docker/Compose deployment files
config/                   Dependency/config files used by deployment
```

## Current Python package layout

```text
src/ds_course_agent/
├── api/                  FastAPI app, routers, schemas, state
├── agent/                orchestration, service, routing, handlers, hooks
├── runtime/              model invocation, context, generic message conversion
├── retrieval/            RAG service, hybrid retrieval, reranking
├── research/             Web research pipeline, fetch, evidence policy
├── kb/                   parsing, cleaning, chunking, indexing helpers
├── teaching/             learner state, events, profiles, graph, skill registry
│   └── skills/           SKILL.md teaching strategies and executors
└── shared/               config, paths, logging, history, vector-store helpers
```

## Completed moves

- `rag/` and top-level `hooks/` removed by M1-M4; current owners are listed above.
- The entries below record the earlier src-layout migration, not current import paths.

- `backend/` removed; API moved to `src/ds_course_agent/api/`.
- `frontend/` removed; frontend moved to `web/`.
- `core/` removed; RAG/runtime code moved to `src/ds_course_agent/rag/`.
- `kb_builder/` removed; KB pipeline moved to `src/ds_course_agent/kb/`.
- `utils/` removed; shared utilities moved to `src/ds_course_agent/shared/`.
- `skills/` moved to `src/ds_course_agent/teaching/skills/`.
- API tests moved to `tests/integration/api/`.
- Compose/deployment files moved to `deploy/`.

## Runtime state policy

Use `var/` for local runtime state:

- `var/chat_history/`
- `var/chroma_db/`
- `var/logs/`
- `var/artifacts/`
- `var/cache/`

Legacy root-level runtime directories may exist locally from older runs, but new defaults point to `var/`.
