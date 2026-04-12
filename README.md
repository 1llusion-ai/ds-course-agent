# Data Science Course Agent

A course-focused RAG teaching assistant for an introductory data science class.
The project combines `FastAPI + Vue 3 + LangGraph + Hybrid RAG` to support:

- course Q&A grounded in textbook content
- personalized explanations and learning-memory features
- student profile snapshots for recent topics and weak spots
- course schedule lookup
- retrieval and agent benchmark workflows

## Project Status

This repository is being reorganized incrementally toward a cleaner open-source structure.

- `apps/api/app` is now the primary FastAPI implementation entrypoint.
- `backend/app` is kept as a compatibility shim so existing imports and tests still work.
- `frontend/` is still the active Vue application.
- `packages/` provides compatibility facades for the future package-oriented layout.

The goal is to improve structure without breaking the running system in one large refactor.

## Repository Layout

```text
apps/                Application layer boundaries
apps/api/app/        Active FastAPI implementation
apps/web/            Future home of the web app
backend/             Compatibility layer, tests, requirements, Docker assets
frontend/            Active Vue 3 + Vite frontend
core/                Agent / RAG / retrieval / memory implementation
skills/              Higher-level skills such as personalized explanation
kb_builder/          Parsing, cleaning, chunking, and indexing pipeline
utils/               Shared runtime utilities and storage helpers
packages/            Compatibility package facades for future migration
scripts/             CLI and developer entrypoints
eval/                Evaluation code, datasets, and gitignored reports
docs/                Architecture notes and migration plans
tests/               Core logic tests
backend/tests/       API integration tests
data/                Structured course data and local content manifests
pyproject.toml       Project metadata and pytest configuration
```

Architecture plan:

- [docs/architecture_reorg_plan.md](docs/architecture_reorg_plan.md)

## Features

- Agent-based course Q&A with tool use and multi-turn context handling
- Hybrid retrieval with `BM25 + vector retrieval + RRF`
- Learning profile aggregation for recent concepts, active weak spots, and resolved weak spots
- Personalized explanations driven by concept and student context
- Course schedule tools for next class and weekly schedule queries
- Benchmark support for retrieval quality and end-to-end agent tasks

## Quick Start

### 1. Prepare the Environment

Recommended:

- Python 3.10+
- Node.js 18+
- an available embedding API
- a local Ollama model or another compatible chat model endpoint

Copy the environment template:

```bash
cp .env.example .env
```

Example settings:

```env
EMBEDDING_API_KEY=your_api_key_here
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B

CHAT_MODEL=qwen3:8b
CHAT_BASE_URL=http://localhost:11434

CHROMA_PERSIST_DIR=chroma_db
CHAT_HISTORY_DIR=chat_history
CHUNK_SIZE=1300
CHUNK_OVERLAP=300
```

### 2. Install Dependencies

Backend:

```bash
python -m pip install -r backend/requirements.txt
```

Frontend:

```bash
cd frontend
npm install
```

### 3. Build the Knowledge Base

Place source materials in `data/` and run:

```bash
python main.py build data/
```

or:

```bash
python -m scripts.cli build data/
```

### 4. Run the Backend

Recommended entrypoint:

```bash
python -m scripts.cli api --reload
```

or:

```bash
python scripts/run_api.py --reload
```

Direct uvicorn entrypoint:

```bash
python -m uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8083 --reload
```

Health check:

```bash
curl http://127.0.0.1:8083/health
```

### 5. Run the Frontend

```bash
cd frontend
npm run dev
```

Production build:

```bash
npm run build
```

### 6. Windows One-Click Development

```bat
start_all.bat
```

Stop services:

```bat
stop_all.bat
```

## CLI

Unified CLI entrypoints:

```bash
python main.py help
python -m scripts.cli help
```

Available commands:

- `build [path]` builds the knowledge base
- `eval` runs retrieval evaluation
- `test` runs the repository test suite
- `api` starts the FastAPI backend

## Evaluation

Run retrieval evaluation:

```bash
python eval/retrieval_benchmark.py --top-k 5
```

Run the agent benchmark:

```bash
python -m eval.agent_benchmark --output eval/reports/agent_benchmark_report.json
```

Notes:

- `eval/reports/` is intentionally gitignored
- keep benchmark outputs locally or store them as CI artifacts

## What Should Not Be Committed

The repository is configured to keep the following local:

- `.env`
- `chat_history/`
- `chroma_db/`
- `frontend/node_modules/`
- `frontend/dist/`
- `eval/reports/*.json`
- `eval/reports/*.log`
- `eval/reports/*.pid`
- temporary debug files and local scratch outputs
- raw course PDFs or other large / restricted source assets

Structured JSON manifests in `data/` can be committed when they are safe to share.
Raw textbooks and other large local assets are intentionally ignored.

## Testing

Run the full test suite:

```bash
python -m pytest -q
```

## Current Reorganization Milestones

Completed so far:

- cleaned `.gitignore` and stopped tracking generated benchmark artifacts
- centralized CLI and startup scripts under `scripts/`
- introduced `packages/` compatibility facades
- introduced `apps/` application boundaries
- moved the active FastAPI implementation to `apps/api/app`
- kept `backend/app` as a compatibility layer for imports and tests
- added repository-level metadata and formatting defaults

Still planned:

- move the active Vue app from `frontend/` into `apps/web`
- progressively move `core/` into `packages/rag_core`
- progressively move `kb_builder/` into `packages/kb_pipeline`
- progressively move `utils/` into `packages/shared`

## License

MIT
