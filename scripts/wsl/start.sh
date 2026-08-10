#!/usr/bin/env bash
# One-command WSL dev launcher: backend (FastAPI) + frontend (Vite).
#
# Encapsulates this repo's WSL environment quirks so startup is one command:
#   - sources nvm so a Node.js runtime lands on PATH (non-interactive shells
#     have none by default); the version is pinned in web/.nvmrc
#   - launches both services with setsid so they survive after the calling
#     shell exits (wsl.exe otherwise reaps background children)
#   - stops any previous instance first (idempotent), then health-checks both
#
# Overrides (env vars): RAG_API_PORT=8084  RAG_WEB_PORT=5185
#                       RAG_API_RELOAD=1   RAG_OPEN_BROWSER=0
#
# cwd-independent: it locates the repo via this script's own path.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

BACKEND_PORT="${RAG_API_PORT:-8084}"
FRONTEND_PORT="${RAG_WEB_PORT:-5185}"
API_RELOAD="${RAG_API_RELOAD:-1}"
OPEN_BROWSER="${RAG_OPEN_BROWSER:-0}"
PYTHON_BIN="$ROOT/.venv/bin/python"
BACKEND_LOG="$ROOT/var/logs/api.log"
FRONTEND_LOG="$ROOT/var/logs/vite.log"

cd "$ROOT"
mkdir -p var/logs

# --- Node runtime (nvm) ------------------------------------------------
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
if [[ -s "$NVM_DIR/nvm.sh" ]]; then
    # shellcheck source=/dev/null
    source "$NVM_DIR/nvm.sh"
    if [[ -f web/.nvmrc ]]; then
        (cd web && nvm use >/dev/null)
    else
        nvm use default >/dev/null 2>&1 || true
    fi
fi
if ! command -v node >/dev/null 2>&1; then
    echo "ERROR: Node.js not found. Install via nvm (see web/.nvmrc) and retry." >&2
    exit 1
fi
echo "node $(node --version) at $(command -v node)"

# --- restart cleanly ---------------------------------------------------
bash "$SCRIPT_DIR/stop.sh" >/dev/null 2>&1 || true
sleep 1

# --- backend -----------------------------------------------------------
echo "Starting backend on port $BACKEND_PORT ..."
RELOAD_ARGS=()
if [[ "$API_RELOAD" == "1" ]]; then
    RELOAD_ARGS=(--reload)
fi
setsid -f "$PYTHON_BIN" main.py api --host 127.0.0.1 --port "$BACKEND_PORT" "${RELOAD_ARGS[@]}" \
    > "$BACKEND_LOG" 2>&1 < /dev/null

# --- frontend ----------------------------------------------------------
echo "Starting frontend on port $FRONTEND_PORT ..."
(
    cd web
    setsid -f npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" \
        > "$FRONTEND_LOG" 2>&1 < /dev/null
)

# --- health checks -----------------------------------------------------
wait_for() {
    local url="$1" name="$2" tries=0
    until curl -sf -m 2 -o /dev/null "$url"; do
        tries=$((tries + 1))
        if [[ $tries -ge 30 ]]; then
            echo "FAIL: $name did not come up at $url within 30s." >&2
            echo "      tail $BACKEND_LOG / $FRONTEND_LOG for clues." >&2
            return 1
        fi
        sleep 1
    done
    echo "OK:   $name is up ($url)"
}

wait_for "http://127.0.0.1:$BACKEND_PORT/api/health" "backend"
wait_for "http://127.0.0.1:$FRONTEND_PORT/" "frontend"

echo
echo "Backend:  http://localhost:$BACKEND_PORT   (log: $BACKEND_LOG)"
echo "Frontend: http://localhost:$FRONTEND_PORT  (log: $FRONTEND_LOG)"
echo "Stop:     bash scripts/wsl/stop.sh"

if [[ "$OPEN_BROWSER" == "1" ]]; then
    explorer.exe "http://localhost:$FRONTEND_PORT/" >/dev/null 2>&1 || true
fi
