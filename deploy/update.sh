#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$PROJECT_ROOT/deploy"
LOCK_FILE="${DEPLOY_LOCK_FILE:-/tmp/ds-course-agent-deploy.lock}"
WAIT_TIMEOUT_SECONDS="${DEPLOY_WAIT_TIMEOUT_SECONDS:-180}"
BACKEND_URL="${DEPLOY_BACKEND_URL:-http://127.0.0.1:8000/health}"
FRONTEND_URL="${DEPLOY_FRONTEND_URL:-http://127.0.0.1/}"
BACKEND_IMAGE="ds-course-agent-backend:latest"
FRONTEND_IMAGE="ds-course-agent-frontend:latest"
BACKEND_ROLLBACK_IMAGE="ds-course-agent-backend:rollback"
FRONTEND_ROLLBACK_IMAGE="ds-course-agent-frontend:rollback"

switched=0
rollback_available=0

log() {
    printf '[deploy] %s\n' "$*"
}

die() {
    log "ERROR: $*"
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

wait_for_url() {
    local name="$1"
    local url="$2"
    local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))

    until curl --fail --silent --show-error --max-time 5 "$url" >/dev/null; do
        if ((SECONDS >= deadline)); then
            log "$name did not become healthy within ${WAIT_TIMEOUT_SECONDS}s"
            return 1
        fi
        log "waiting for $name: $url"
        sleep 2
    done
    log "$name is healthy"
}

tag_rollback_images() {
    local tagged=0

    if docker image inspect "$BACKEND_IMAGE" >/dev/null 2>&1; then
        docker image tag "$BACKEND_IMAGE" "$BACKEND_ROLLBACK_IMAGE"
        tagged=$((tagged + 1))
    fi
    if docker image inspect "$FRONTEND_IMAGE" >/dev/null 2>&1; then
        docker image tag "$FRONTEND_IMAGE" "$FRONTEND_ROLLBACK_IMAGE"
        tagged=$((tagged + 1))
    fi

    if ((tagged == 2)); then
        rollback_available=1
        log "saved current backend/frontend images as rollback targets"
    else
        log "rollback images are incomplete; this appears to be a first deployment"
    fi
}

rollback() {
    if ((rollback_available == 0)); then
        log "automatic rollback unavailable"
        return 1
    fi

    log "deployment failed after container switch; restoring previous images"
    docker image tag "$BACKEND_ROLLBACK_IMAGE" "$BACKEND_IMAGE"
    docker image tag "$FRONTEND_ROLLBACK_IMAGE" "$FRONTEND_IMAGE"
    (
        cd "$COMPOSE_DIR"
        docker compose up -d --no-build --force-recreate --remove-orphans
    )
    wait_for_url "rollback backend" "$BACKEND_URL"
    wait_for_url "rollback frontend" "$FRONTEND_URL"
    log "rollback completed"
}

on_error() {
    local exit_code=$?
    trap - ERR

    if ((switched == 1)); then
        rollback || true
    fi

    (
        cd "$COMPOSE_DIR"
        docker compose ps || true
        docker compose logs --tail=100 backend frontend || true
    )
    exit "$exit_code"
}

trap on_error ERR

require_command curl
require_command docker
require_command flock
require_command git

git_safe() {
    git -c "safe.directory=$PROJECT_ROOT" "$@"
}

exec 9>"$LOCK_FILE"
flock -n 9 || die "another deployment is already running"

cd "$PROJECT_ROOT"

current_branch="$(git_safe branch --show-current)"
[[ "$current_branch" == "main" ]] || die "deployment must run from main, current branch: $current_branch"
[[ -z "$(git_safe status --porcelain --untracked-files=no)" ]] || die "tracked working tree changes detected"

log "fetching origin/main"
git_safe fetch origin main
git_safe merge --ff-only origin/main

cd "$COMPOSE_DIR"
docker compose config --quiet

tag_rollback_images

log "building images while current containers remain online"
docker compose build

log "switching to the newly built images"
switched=1
docker compose up -d --no-build --remove-orphans

wait_for_url "backend" "$BACKEND_URL"
wait_for_url "frontend" "$FRONTEND_URL"
switched=0

docker compose ps
log "deployment completed successfully at commit $(git_safe -C "$PROJECT_ROOT" rev-parse --short HEAD)"
