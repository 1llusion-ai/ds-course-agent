# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **先读 [`AGENTS.md`](AGENTS.md)（工程宪法，唯一事实源）。** 本文件只是它的补充与快捷命令索引，
> 不重复也不得与之冲突；冲突时以 AGENTS.md 为准。反屎山三铁律、统一风格、验证门槛、变更纪律都在那里。

## Project Overview

Data Science Course Agent — a course-focused RAG teaching assistant for "Introduction to Data Science". Built with FastAPI + Vue 3 + LangGraph + hybrid retrieval.

## Common Commands

```bash
cp .env.example .env
pip install -r config/api-requirements.txt
cd web && npm install

python main.py build data/
python main.py api --reload
cd web && npm run dev
bash scripts/wsl/start.sh   # 一键启动前后端 (WSL, 推荐)
bash scripts/wsl/stop.sh    # 停止前后端

python -m pytest -q
PYTHONPATH=src python -c "import ds_course_agent"
cd web && npm run build
docker compose -f deploy/compose.yaml config
```

## Architecture

```text
Vue 3 app (web/) → HTTP/SSE → FastAPI (src/ds_course_agent/api/) → ds_course_agent.agent.service
```

## Python Package Layout

- `src/ds_course_agent/api/` — FastAPI app, routers, schemas, API state.
- `src/ds_course_agent/agent/` — service, routing/QueryPipeline, turn events/runner, hooks, handlers, result finalizer.
- `src/ds_course_agent/runtime/` — model calls, context governance, message conversion, stream decoding.
- `src/ds_course_agent/retrieval/` — course RAG, hybrid retrieval and reranking.
- `src/ds_course_agent/research/` — web research pipeline and evidence policies.
- `src/ds_course_agent/tools/` — atomic tools, registry and execution sandbox.
- `src/ds_course_agent/kb/` — PDF/data parsing, cleaning, chunking, TOC parsing, vector-store write path.
- `src/ds_course_agent/teaching/` — learner state, learning events, profiles, graph and SKILL.md executors under skills/.
- `src/ds_course_agent/shared/` — config, repository paths, logging, chat history, vector-store helpers.

## Frontend

- `web/` — Vue 3 + Composition API + Element Plus + Pinia.
- API client layer lives under `web/src/api/`.

## Tests

- `tests/` contains unit and integration tests.
- API integration tests live under `tests/integration/api/`.

## Runtime State

Local runtime state should use `var/`:

- `var/chat_history/`
- `var/chroma_db/`
- `var/logs/`
- `var/artifacts/`
- `var/cache/`
