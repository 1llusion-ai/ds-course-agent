from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_update_script_uses_root_env_file_for_compose_interpolation() -> None:
    script = (PROJECT_ROOT / "deploy" / "update.sh").read_text(encoding="utf-8")

    assert 'DEPLOY_ENV_FILE="${DEPLOY_ENV_FILE:-$PROJECT_ROOT/.env}"' in script
    assert 'docker compose --env-file "$DEPLOY_ENV_FILE" "$@"' in script
    assert '[[ -f "$DEPLOY_ENV_FILE" ]]' in script
    assert script.count("docker compose") == 1


def test_container_healthcheck_remains_rollback_compatible() -> None:
    compose = (PROJECT_ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "deploy" / "update.sh").read_text(encoding="utf-8")

    assert "http://127.0.0.1:8000/health" in compose
    assert "http://127.0.0.1:8000/readyz" not in compose
    assert 'BACKEND_URL="${DEPLOY_BACKEND_URL:-http://127.0.0.1:8000/readyz}"' in script
    assert 'BACKEND_LIVENESS_URL="${DEPLOY_BACKEND_LIVENESS_URL:-http://127.0.0.1:8000/health}"' in script
    assert 'wait_for_url "rollback backend" "$BACKEND_LIVENESS_URL"' in script


def test_backend_port_is_not_published_publicly() -> None:
    compose = (PROJECT_ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")

    assert '"127.0.0.1:8000:8000"' in compose
    assert '\n      - "8000:8000"' not in compose
