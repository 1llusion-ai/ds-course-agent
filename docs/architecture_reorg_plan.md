# RAG System Architecture Reorg Plan

## Why Reorganize

The repository already has useful core capabilities, but the current layout mixes:

- product code and one-off scripts
- runtime state and source code
- backend API code and domain logic
- benchmark artifacts and benchmark code
- local developer files and repository files

That makes the project feel less like a reusable open-source repository and more like an active workspace snapshot.

## Target Shape

This structure is closer to what high-star GitHub projects in the RAG / AI app space usually adopt:

```text
RAG_System/
├── apps/
│   ├── api/                     # FastAPI app only
│   │   ├── app/
│   │   │   ├── api/             # routers
│   │   │   ├── schemas/
│   │   │   ├── services/        # thin service adapters
│   │   │   ├── state/
│   │   │   └── main.py
│   │   └── tests/
│   └── web/                     # Vue app only
│       ├── src/
│       │   ├── api/
│       │   ├── components/
│       │   ├── stores/
│       │   ├── views/
│       │   └── router/
│       └── package.json
├── packages/
│   ├── rag_core/                # retrieval / rerank / tool orchestration
│   │   ├── agent.py
│   │   ├── retrieval/
│   │   ├── tools/
│   │   └── memory/
│   ├── kb_pipeline/             # parsing / cleaning / chunking / indexing
│   └── shared/                  # shared config, models, helpers
├── eval/
│   ├── benchmarks/
│   ├── datasets/
│   ├── metrics/
│   ├── runners/
│   └── reports/                 # gitignored
├── scripts/                     # CLI wrappers only
├── docs/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── data/
│   ├── fixtures/                # small public sample data only
│   └── manifests/
├── .env.example
├── README.md
└── pyproject.toml
```

## Mapping From Current Repo

Recommended mapping from the current directories:

- `backend/app` -> `apps/api/app`
- `backend/tests` -> `apps/api/tests`
- `frontend` -> `apps/web`
- `core` -> `packages/rag_core`
- `kb_builder` -> `packages/kb_pipeline`
- `utils/config.py`, `utils/history.py`, `utils/vector_store.py` -> `packages/shared` and `packages/rag_core`
- `skills/personalized_explanation.py` -> `packages/rag_core/skills`
- `eval/*` -> keep under `eval`, but split code from generated reports

## Recommended Python Package Boundaries

Split by responsibility, not by “whatever file existed first”.

### `apps/api`

Only HTTP-facing code:

- request / response schemas
- routers
- app bootstrap
- minimal dependency injection

The API layer should not hold business logic.

### `packages/rag_core`

Core product behavior:

- agent orchestration
- retrieval pipeline
- reranker
- tool definitions
- learning memory / profile aggregation
- knowledge mapper

### `packages/kb_pipeline`

Offline content processing:

- PDF parsing
- cleaning
- chunking
- TOC parsing
- vector store write path

### `packages/shared`

Shared primitives only:

- config loading
- common path helpers
- small reusable types

Avoid putting domain logic here.

## Recommended Test Layout

Current tests are split between `tests/` and `backend/tests/`, which is workable but uneven.

Better long-term layout:

```text
tests/
├── unit/
│   ├── rag_core/
│   ├── kb_pipeline/
│   └── shared/
├── integration/
│   ├── api/
│   ├── chat/
│   └── memory/
└── e2e/
    ├── benchmark/
    └── frontend/
```

Short-term migration rule:

- keep `backend/tests` for API integration tests
- move pure logic tests from `tests/` into `tests/unit/`
- move benchmark runner validation into `tests/integration/benchmark/`

## What Should Not Go To GitHub

These should stay local or be generated in CI:

- `.env`
- `chat_history/`
- `chroma_db/`
- `utils/chroma_db/`
- `frontend/node_modules/`
- `frontend/dist/`
- `eval/reports/*.json`
- `eval/reports/*.log`
- `eval/reports/*.pid`
- `tmp_mapper_debug.json`
- raw course PDFs in `data/` if they are copyrighted or too large
- local agent metadata like `.claude/` and `CLAUDE.md`

## Files That Look Like Old Or Workspace-Only Artifacts

These are the clearest cleanup candidates.

### Safe to remove now

- `tmp_mapper_debug.json`
  - tracked debug output, not referenced by runtime code
- `eval/reports/agent_benchmark_report_2026-04-11.json`
  - generated output
- `eval/reports/agent_benchmark_report_2026-04-11_v2.json`
  - generated output
- `eval/reports/agent_benchmark_targeted_2026-04-11.json`
  - generated output
- `eval/reports/agent_benchmark_targeted_2026-04-11_v2.json`
  - generated output
- `eval/reports/agent_benchmark_targeted_2026-04-11_v3.json`
  - generated output
- `eval/reports/agent_benchmark_run_2026-04-11.pid`
  - runtime artifact

### Likely removable, but confirm intent first

- `PROJECT_STRUCTURE.md`
  - appears to be an older manually maintained structure snapshot
- `frontend/test-api.html`
  - likely manual debugging page, not part of the app
- `start_backend.py`
  - Windows-local launcher with hard-coded absolute paths
- `start_all.bat`
  - local convenience launcher, good for personal use, weak for open-source default
- `stop_all.bat`
  - local convenience script, same reason

### Keep, but relocate or rename

- root `main.py`
  - still referenced by the README as a CLI entrypoint
  - better future home: `scripts/cli.py` or `python -m rag_system`

## Concrete Migration Plan

### Phase 1: Repository hygiene

- fix `.gitignore`
- stop tracking runtime outputs and benchmark reports
- remove obvious temp files
- add one authoritative architecture document

### Phase 2: Package boundaries

- create `apps/api`, `apps/web`, `packages/rag_core`, `packages/kb_pipeline`, `packages/shared`
- move code without changing behavior
- add import shims only if needed for a short transition

### Phase 3: Entrypoints

- replace root `main.py` with a clean CLI
- replace hard-coded Windows launchers with:
  - `Makefile` or `justfile`
  - optional `scripts/dev.ps1`
  - optional `scripts/dev.sh`

### Phase 4: CI / OSS readiness

- add `pyproject.toml`
- add lint / format / test commands
- add GitHub Actions for backend tests and frontend build
- keep benchmark reports as CI artifacts, not committed files

## What I Would Do Next

If we continue from here, the best practical order is:

1. remove tracked generated files
2. move startup scripts into `scripts/`
3. move `core`, `kb_builder`, and `utils` into clearer package boundaries
4. update README commands after the move

