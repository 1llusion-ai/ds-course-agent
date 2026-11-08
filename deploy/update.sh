#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$PROJECT_ROOT/deploy"
DEPLOY_ENV_FILE="${DEPLOY_ENV_FILE:-$PROJECT_ROOT/.env}"
STATE_DIR="$PROJECT_ROOT/var/deployment"
STATE_ENV_FILE="$STATE_DIR/.env"
RUNTIME_OVERLAY="$STATE_DIR/compose.runtime.json"
LOCK_FILE="${DEPLOY_LOCK_FILE:-/tmp/ds-course-agent-deploy.lock}"
WAIT_TIMEOUT_SECONDS="${DEPLOY_WAIT_TIMEOUT_SECONDS:-180}"
BACKEND_URL="${DEPLOY_BACKEND_URL:-http://127.0.0.1:8000/readyz}"
BACKEND_LIVENESS_URL="${DEPLOY_BACKEND_LIVENESS_URL:-http://127.0.0.1:8000/health}"
FRONTEND_URL="${DEPLOY_FRONTEND_URL:-http://127.0.0.1:8080/}"
BUILD_BUILDER="${DEPLOY_BUILDER:-memlimited}"

switched=0
rollback_available=0
selected_tag=""
revision=""
rollback_tag=""

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

git_safe() {
  git -c "safe.directory=$PROJECT_ROOT" -C "$PROJECT_ROOT" "$@"
}

read_selected_tag() {
  local line count=0
  [[ -f "$STATE_ENV_FILE" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" == DEPLOY_IMAGE_TAG=* ]]; then
      selected_tag="${line#DEPLOY_IMAGE_TAG=}"
      count=$((count + 1))
    fi
  done < "$STATE_ENV_FILE"
  ((count <= 1)) || die "duplicate DEPLOY_IMAGE_TAG in $STATE_ENV_FILE"
  if ((count == 1)); then
    [[ "$selected_tag" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}$ ]] || die "invalid saved deployment image tag"
  fi
}

compose() {
  local args=(--project-name ds-course-agent --project-directory "$COMPOSE_DIR" --env-file "$DEPLOY_ENV_FILE")
  [[ ! -f "$STATE_ENV_FILE" ]] || args+=(--env-file "$STATE_ENV_FILE")
  args+=(-f "$COMPOSE_DIR/compose.yaml")
  [[ ! -f "$RUNTIME_OVERLAY" ]] || args+=(-f "$RUNTIME_OVERLAY")
  DEPLOY_IMAGE_TAG="$selected_tag" DEPLOY_GIT_REVISION="$revision" docker compose "${args[@]}" "$@"
}

save_selected_tag() {
  local temporary line
  mkdir -p "$STATE_DIR" || return 1
  temporary="$(umask 077; mktemp "$STATE_DIR/.env.XXXXXX")" || return 1
  # Preserve unrelated deployment variables without evaluating them as shell code.
  if [[ -f "$STATE_ENV_FILE" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      if [[ "$line" != DEPLOY_IMAGE_TAG=* ]]; then
        printf '%s\n' "$line" >> "$temporary" || { rm -f "$temporary"; return 1; }
      fi
    done < "$STATE_ENV_FILE"
  fi
  printf 'DEPLOY_IMAGE_TAG=%s\n' "$selected_tag" >> "$temporary" || { rm -f "$temporary"; return 1; }
  mv -f "$temporary" "$STATE_ENV_FILE" || { rm -f "$temporary"; return 1; }
}

wait_for_url() {
  local name="$1" url="$2"
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

snapshot_running_images() {
  local backend_id frontend_id names
  names="$(docker container ls -a --format '{{.Names}}')"
  if [[ $'\n'"$names"$'\n' != *$'\n'rag-backend$'\n'* && $'\n'"$names"$'\n' != *$'\n'rag-frontend$'\n'* ]]; then
    log "no existing application containers; automatic rollback unavailable for first deployment"
    return 0
  fi
  [[ $'\n'"$names"$'\n' == *$'\n'rag-backend$'\n'* && $'\n'"$names"$'\n' == *$'\n'rag-frontend$'\n'* ]] || die "both application containers are required for an image rollback snapshot"
  backend_id="$(docker container inspect --format '{{.Image}}' rag-backend)"
  frontend_id="$(docker container inspect --format '{{.Image}}' rag-frontend)"
  [[ "$backend_id" =~ ^sha256:[a-f0-9]{64}$ && "$frontend_id" =~ ^sha256:[a-f0-9]{64}$ ]] || die "cannot capture both current container image IDs"
  # Derive a stable recovery tag from the actual container images, never from latest.
  rollback_tag="rollback-${backend_id:7:24}-${frontend_id:7:24}"
  docker image tag "$backend_id" "ds-course-agent-backend:$rollback_tag"
  docker image tag "$frontend_id" "ds-course-agent-frontend:$rollback_tag"
  rollback_available=1
  log "saved current container images under $rollback_tag"
}

validate_selected_images() {
  local images
  compose config --quiet
  images="$(compose config --images)"
  [[ $'\n'"$images"$'\n' == *$'\n'"ds-course-agent-backend:$selected_tag"$'\n'* ]] || die "runtime overlay must not override the backend release image"
  [[ $'\n'"$images"$'\n' == *$'\n'"ds-course-agent-frontend:$selected_tag"$'\n'* ]] || die "runtime overlay must not override the frontend release image"
}

build_image() {
  local service="$1" image="ds-course-agent-$1:$selected_tag" image_revision
  if docker image inspect "$image" >/dev/null 2>&1; then
    log "reusing immutable image $image"
  else
    log "building $image while current containers remain online"
    COMPOSE_DOCKER_CLI_BUILD=1 DOCKER_BUILDKIT=1 compose build --builder "$BUILD_BUILDER" "$service"
  fi
  image_revision="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")"
  [[ "$image_revision" == "$revision" ]] || die "image $image has an unexpected OCI revision; refusing to overwrite it"
}

rollback() {
  if ((rollback_available == 0)); then
    log "automatic rollback unavailable; deployment state was not advanced"
    return 1
  fi
  log "restoring the previous container images; databases and runtime resources are unchanged"
  selected_tag="$rollback_tag"
  compose up -d --no-build --force-recreate --remove-orphans backend frontend || return 1
  wait_for_url "rollback backend" "$BACKEND_LIVENESS_URL" || return 1
  wait_for_url "rollback frontend" "$FRONTEND_URL" || return 1
  save_selected_tag || return 1
  switched=0
  log "rollback completed and selected recovery images were saved"
}

on_error() {
  local exit_code=$?
  trap - ERR
  if ((switched == 1)); then
    if ! rollback; then
      log "ERROR: automatic recovery did not complete; inspect current containers before retrying"
    fi
  fi
  compose ps || true
  compose logs --tail=100 backend frontend || true
  exit "$exit_code"
}

case "${1:-}" in
  "") apply=0 ;;
  --apply) apply=1 ;;
  --help|-h)
    printf 'Usage: %s [--apply]\nDefault: preview only. --apply fetches/fast-forwards main, builds immutable images and deploys.\n' "$0"
    exit 0 ;;
  *) die "unknown argument: $1; use --help" ;;
esac
(($# <= 1)) || die "unexpected additional arguments"

require_command git
read_selected_tag
revision="$(git_safe rev-parse HEAD)"
log "repository: $PROJECT_ROOT; local revision: $revision"
log "saved image tag: ${selected_tag:-not set}; deployment state: $STATE_ENV_FILE"
if [[ -f "$RUNTIME_OVERLAY" ]]; then
  log "preserving runtime resources from $RUNTIME_OVERLAY"
else
  log "no runtime resource overlay; using base Compose configuration"
fi
if ((apply == 0)); then
  log "PREVIEW ONLY: --apply will lock, fetch/fast-forward origin/main, build both images tagged with the full Git SHA, switch, check health, and atomically save the selected tag"
  exit 0
fi

require_command curl
require_command docker
require_command flock
[[ -f "$DEPLOY_ENV_FILE" ]] || die "deployment env file not found: $DEPLOY_ENV_FILE"
[[ "$WAIT_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || die "invalid health-check timeout"
exec 9>"$LOCK_FILE"
flock -n 9 || die "another deployment is already running"

[[ "$(git_safe branch --show-current)" == "main" ]] || die "deployment must run from main"
[[ -z "$(git_safe status --porcelain --untracked-files=no)" ]] || die "tracked working tree changes detected"
[[ -z "$(git_safe ls-files --others --exclude-standard src scripts data docs/prompts config web deploy)" ]] || die "untracked files in deployment inputs detected"

trap on_error ERR
log "fetching origin/main"
git_safe fetch origin main
git_safe merge --ff-only origin/main
revision="$(git_safe rev-parse HEAD)"
[[ "$revision" =~ ^[a-f0-9]{40}$ ]] || die "expected a full Git SHA"
selected_tag="$revision"
validate_selected_images
snapshot_running_images
build_image backend
build_image frontend

log "switching to release $selected_tag"
switched=1
compose up -d --no-build --force-recreate --remove-orphans backend frontend
wait_for_url "backend" "$BACKEND_URL"
wait_for_url "frontend" "$FRONTEND_URL"
save_selected_tag
switched=0
compose ps || true
log "deployment completed successfully at commit $revision"
