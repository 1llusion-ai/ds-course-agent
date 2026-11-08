import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_api_image_includes_shared_and_catalog_course_prompts() -> None:
    dockerfile = (PROJECT_ROOT / "deploy" / "api.Dockerfile").read_text(encoding="utf-8")
    prompt_directory = Path("docs/prompts")

    assert "COPY docs/prompts/ ./docs/prompts/" in dockerfile.splitlines()
    assert (PROJECT_ROOT / prompt_directory / "base_system_prompt.txt").is_file()
    for manifest_path in (PROJECT_ROOT / "data" / "courses").glob("*.json"):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if prompt_path := manifest.get("prompt_path"):
            resource = Path(prompt_path)
            assert resource.is_relative_to(prompt_directory), manifest_path
            assert (PROJECT_ROOT / resource).is_file(), manifest_path


def test_update_script_uses_root_env_file_for_compose_interpolation() -> None:
    script = (PROJECT_ROOT / "deploy" / "update.sh").read_text(encoding="utf-8")

    assert 'DEPLOY_ENV_FILE="${DEPLOY_ENV_FILE:-$PROJECT_ROOT/.env}"' in script
    assert '--env-file "$DEPLOY_ENV_FILE"' in script
    assert '--env-file "$STATE_ENV_FILE"' in script
    assert 'docker compose "${args[@]}" "$@"' in script
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


def test_frontend_port_is_private_for_host_tls_proxy() -> None:
    compose = (PROJECT_ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")

    assert '"127.0.0.1:8080:80"' in compose
    assert '\n      - "80:80"' not in compose


def test_deployment_frontend_probe_matches_compose_listener() -> None:
    script = (PROJECT_ROOT / "deploy" / "update.sh").read_text(encoding="utf-8")

    assert 'FRONTEND_URL="${DEPLOY_FRONTEND_URL:-http://127.0.0.1:8080/}"' in script


def test_release_images_use_selected_tag_and_oci_revision() -> None:
    compose = (PROJECT_ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    assert "ds-course-agent-backend:${DEPLOY_IMAGE_TAG:-latest}" in compose
    assert "ds-course-agent-frontend:${DEPLOY_IMAGE_TAG:-latest}" in compose
    assert compose.count("GIT_REVISION: ${DEPLOY_GIT_REVISION:-unknown}") == 2
    for relative in ("deploy/api.Dockerfile", "web/Dockerfile"):
        dockerfile = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert "ARG GIT_REVISION=unknown" in dockerfile
        assert "LABEL org.opencontainers.image.revision=$GIT_REVISION" in dockerfile
