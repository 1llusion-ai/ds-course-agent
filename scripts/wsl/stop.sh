#!/usr/bin/env bash
# Stop the WSL dev services started by scripts/wsl/start.sh (idempotent).
#
# The [x] character-class patterns are deliberate: `pkill -f` matches its own
# command line, so `[m]ain` never matches the literal "main" in this script's
# process args the way a plain `main` pattern would.

set -uo pipefail

# Backend: uvicorn launched via "python main.py api ..."
pkill -f "[m]ain.py api" 2>/dev/null || true
# Frontend: the vite dev-server node process (npm wrapper exits with it)
pkill -f "[n]ode.*node_modules/.bin/vite" 2>/dev/null || true
# esbuild service child spawned by vite (belt and braces)
pkill -f "[e]sbuild --service" 2>/dev/null || true

echo "Stopped backend (port ${RAG_API_PORT:-8084}) and frontend (port ${RAG_WEB_PORT:-5185})."
