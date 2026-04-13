# Data Science Course Agent

A course-focused RAG teaching assistant for **Introduction to Data Science**, built with `FastAPI + Vue 3 + LangGraph + Hybrid Retrieval`.

It supports grounded textbook Q&A, streaming chat, personalized learning memory, student profile views, course schedule tools, and evaluation workflows for both retrieval and agent behavior.

## Highlights

- Grounded answers with textbook citations
- Hybrid retrieval with BM25 + vector search + RRF fusion
- Multi-turn chat with session persistence
- SSE streaming responses
- Student memory for recent concepts, weak spots, and resolved weak spots
- Personalized explanation scaffolds
- Agent and retrieval benchmark runners

## Repository Status

This repository has been reorganized toward a more standard open-source layout while keeping the system runnable during migration.

- Active backend entrypoint: `apps/api/app/main.py`
- Legacy backend path kept as compatibility shim: `backend/app`
- Frontend runtime still lives in `frontend/`
- Shared package boundaries are being introduced under `packages/`

In other words: the project now has a cleaner backbone, but it is still in an incremental migration rather than a one-shot rewrite.

## Architecture

```text
frontend/                Vue 3 application
apps/api/app/            Active FastAPI app
backend/app/             Compatibility shims for legacy imports
core/                    Current runtime domain logic
packages/rag_core/       Package-facing wrappers for core capabilities
packages/kb_pipeline/    Package-facing wrappers for KB build pipeline
packages/shared/         Shared config/history/vector-store wrappers
eval/                    Retrieval and agent evaluation code + datasets
scripts/                 CLI and local run helpers
data/                    Small tracked metadata and local course assets
docs/                    Architecture and prompt docs
tests/                   Core/unit-style tests
backend/tests/           API integration tests
```

Runtime request flow:

1. `frontend/` sends HTTP/SSE requests to the FastAPI app.
2. `apps/api/app/routers/` handles chat, sessions, and profile APIs.
3. `apps/api/app/core_bridge.py` bridges the API layer to the current `core/` agent and memory logic.
4. `core/` uses retrieval, tools, and learning memory to answer or stream results.

## Capability Model

This repo intentionally uses a mixed capability architecture:

- `tools` for deterministic queries or external/data-backed access
- a small number of `skills` for user-facing teaching strategies
- normal modules/services for internal ranking, mapping, and memory logic

Current examples:

- tools: textbook retrieval, KB status check, course schedule query
- skills: `learning-path`, `personalized-explanation`
- internal modules: weak-spot detection, concept mapping, route ranking

The detailed boundary document is in `docs/capability_model.md`.

## Quick Start

### 1. Prerequisites

- Python 3.10+
- Node.js 18+
- A configured embedding endpoint
- A configured chat model endpoint or local model

### 2. Configure environment

```bash
cp .env.example .env
```

Fill in the required keys in `.env`.

### 3. Install dependencies

Backend:

```bash
pip install -r backend/requirements.txt
```

Frontend:

```bash
cd frontend
npm install
```

### 4. Build the knowledge base

Put course files under `data/` and run:

```bash
python main.py build data/
```

### 5. Start the backend

```bash
python main.py api --reload
```

Or directly:

```bash
python scripts/run_api.py --reload
```

### 6. Start the frontend

```bash
cd frontend
npm run dev
```

### 7. Health check

```bash
curl http://127.0.0.1:8083/health
```

## Common Commands

```bash
python main.py help
python main.py build data/
python main.py api --reload
python -m pytest -q
python -m eval.agent_benchmark --output eval/reports/agent_benchmark_report.json
```

## Development Notes

### Backend

- Active ASGI app: `apps.api.app.main:app`
- Compatibility app import: `backend.app.main:app`
- API routes:
  - `apps/api/app/routers/chat.py`
  - `apps/api/app/routers/sessions.py`
  - `apps/api/app/routers/profile.py`

### Frontend

- Current runtime app lives in `frontend/`
- `apps/web/` is currently a boundary marker for the long-term target layout

### Testing

The repository now runs tests with workspace-local temporary directories instead of relying on OS temp directories. This avoids Windows permission issues in restricted environments.

Main suites:

- `tests/`
- `backend/tests/`

## Data and Git Hygiene

These are intentionally ignored and should usually stay out of GitHub:

- `.env`
- `chat_history/`
- `chroma_db/`
- `frontend/node_modules/`
- `frontend/dist/`
- `artifacts/`
- generated benchmark reports in `eval/reports/`
- raw course PDFs and other large copyrighted assets in `data/`

Tracked course metadata that is useful for reproducibility can stay in Git, for example:

- `data/course_schedule.json`
- `data/knowledge_graph.json`
- `data/目录.json`
- benchmark datasets under `eval/data/`

## Evaluation

This repository includes two evaluation layers:

- Retrieval evaluation under `eval/`
- Agent task evaluation under `eval/agent_benchmark.py`

Current tracked snapshots in this repository:

### Retrieval benchmark

Dataset:

- 50 reviewed retrieval queries
- Top-5 evaluation
- active dataset: `eval/data/retrieval_qa_pairs_chunk1300.json`
- review overlay: `eval/data/retrieval_qa_reviews.json`

Latest tracked report: `eval/reports/retrieval_benchmark_report_2026-04-13.json`

| Method | Recall@5 | Precision@5 | MRR | NDCG@5 | Hit@5 |
|--------|----------|-------------|-----|--------|-------|
| Vector | 0.5600 | 0.2640 | 0.6433 | 0.5220 | 0.82 |
| Hybrid | 0.6667 | 0.3240 | 0.6740 | 0.6166 | 0.84 |
| Hybrid + Rerank | 0.6733 | 0.3320 | 0.6873 | 0.6173 | 0.88 |

### Agent benchmark

Dataset:

- 30 end-to-end agent tasks
- covers retrieval, multi-turn context, personalization, and safety handling
- active dataset: `eval/data/agent_tasks_v1.json`

Latest tracked report: `eval/reports/agent_benchmark_report_2026-04-13.json`

| Metric | Value |
|--------|-------|
| Agent task success rate | 0.9333 |
| Tool call success rate | 0.9667 |
| Grounded answer rate | 0.9583 |
| Context utilization rate | 0.8750 |
| Personalization hit rate | 1.0000 |
| Failure safety rate | 1.0000 |

If you are quoting metrics externally, make sure to distinguish:

- `Hit@5` belongs to the retrieval benchmark
- `Agent task success rate` belongs to the end-to-end agent benchmark
- they are not interchangeable

## Migration Notes

The repo has already completed:

- standardized Python project metadata via `pyproject.toml`
- standardized backend app entrypoint under `apps/api`
- repository CLI under `scripts/cli.py`
- compatibility shims for legacy backend imports
- improved `.gitignore` and artifact boundaries

Still intentionally incremental:

- frontend has not yet been physically moved into `apps/web`
- core runtime logic still primarily lives in `core/`
- package wrappers in `packages/` are present, but not every runtime import has been physically migrated yet

## License

MIT
