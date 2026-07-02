# Architecture Reorganization Plan

Status: implemented.

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

## Final Python package layout

```text
src/ds_course_agent/
├── api/                  FastAPI app, routers, schemas, state
├── rag/                  agent, retrieval, tools, query pipeline, memory models
├── kb/                   parsing, cleaning, chunking, indexing helpers
├── teaching/skills/      SKILL.md teaching strategies and executors
└── shared/               config, paths, logging, history, vector-store helpers
```

## Completed moves

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
