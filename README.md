# Data Science Course Agent

A course-focused RAG teaching assistant for **Introduction to Data Science**, built with `FastAPI + Vue 3 + LangGraph + Hybrid Retrieval`.

It supports grounded textbook Q&A, streaming chat, personalized learning memory, student profile views, course schedule tools, and evaluation workflows for both retrieval and agent behavior.

## Repository Layout

```text
src/ds_course_agent/      Python package: API, RAG, KB pipeline, memory, teaching skills, shared utilities
web/                      Vue 3 frontend application
tests/                    Unit and integration tests
scripts/                  Developer and maintenance CLIs
benchmarks/                     Evaluation datasets, metrics, and benchmark runners
data/                     Small tracked course metadata and sample data
var/                      Local runtime state (gitignored except .gitkeep files)
docs/                     Architecture notes and prompts
deploy/                   Docker/Compose deployment files
config/                   Dependency/config files used by deployment
```

Python code uses the standard `src` layout:

```text
src/ds_course_agent/
├── api/                  FastAPI app, routers, schemas, API state
├── rag/                  Agent, RAG, retrieval, tools, query pipeline, memory models
├── kb/                   Parsing, cleaning, chunking, indexing pipeline
├── teaching/skills/      SKILL.md teaching strategies and executors
└── shared/               Config, paths, logging, history, vector-store helpers
```

## Runtime Request Flow

1. `web/` sends HTTP/SSE requests to the FastAPI app.
2. `src/ds_course_agent/api/routers/` handles chat, sessions, and profile APIs.
3. `src/ds_course_agent/api/core_bridge.py` bridges the API layer to `ds_course_agent.rag`.
4. `src/ds_course_agent/rag/` uses retrieval, tools, and learning memory to answer or stream results.

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

Backend/API:

```bash
pip install -r config/api-requirements.txt
```

Frontend:

```bash
cd web
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
cd web
npm run dev
```

### 7. Health check

```bash
curl http://127.0.0.1:8083/health
```

## Common Commands

The repository uses Python `src` layout. `pytest`, `main.py`, `scripts/*`, and Docker are configured for it. For ad-hoc one-liners, use `PYTHONPATH=src`.

```bash
python main.py help
python main.py build data/
python main.py api --reload
python -m pytest -q
PYTHONPATH=src python -c "import ds_course_agent"
python -m benchmarks.agent_benchmark --output var/artifacts/benchmarks/agent_benchmark_report.json
cd web && npm run build
docker compose -f deploy/compose.yaml config
```

## Development Notes

### Backend/API

- Active ASGI app: `ds_course_agent.api.main:app`
- API routes:
  - `src/ds_course_agent/api/routers/chat.py`
  - `src/ds_course_agent/api/routers/sessions.py`
  - `src/ds_course_agent/api/routers/profile.py`

### Frontend

- Runtime app lives in `web/`
- Build with `cd web && npm run build`

### Testing

Main suites:

- `tests/`
- API integration tests live under `tests/integration/api/`

## Data and Git Hygiene

These are intentionally ignored and should usually stay out of GitHub:

- `.env`
- `var/chat_history/`
- `var/chroma_db/`
- `var/logs/`
- `var/artifacts/`
- `var/cache/`
- `web/node_modules/`
- `web/dist/`
- generated benchmark reports in `var/artifacts/benchmarks/`
- raw course PDFs and other large copyrighted assets in `data/`

Tracked course metadata that is useful for reproducibility can stay in Git, for example:

- `data/course_schedule.json`
- `data/knowledge_graph.json`
- benchmark datasets under `benchmarks/data/`

## Deployment

Compose configuration lives in `deploy/compose.yaml`:

```bash
docker compose -f deploy/compose.yaml config
docker compose -f deploy/compose.yaml up --build
```

The second command requires a running Docker daemon.

## License

MIT
