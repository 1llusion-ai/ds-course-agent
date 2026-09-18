from fastapi.testclient import TestClient

from ds_course_agent.api.main import app
from ds_course_agent.shared.config.production import check_production_settings
from ds_course_agent.shared.config.schema import Settings
from ds_course_agent.shared.readiness import ReadinessCheck, ReadinessReport


def test_development_settings_keep_production_checks_explicitly_disabled() -> None:
    checks = check_production_settings(Settings(APP_ENV="development"))

    assert checks == (
        ReadinessCheck("production_settings", True, "APP_ENV=development; production-only checks are disabled"),
    )


def test_production_settings_require_strong_secret_https_origins_and_secure_cookie() -> None:
    failed = check_production_settings(
        Settings(
            APP_ENV="production",
            AUTH_SECRET_KEY="short",
            CORS_ALLOW_ORIGINS="http://localhost,https://course.example.edu/path",
            AUTH_COOKIE_SECURE=False,
        )
    )

    assert [check.name for check in failed] == ["auth_secret_key", "cors_origins", "secure_cookie"]
    assert not any(check.ok for check in failed)

    passed = check_production_settings(
        Settings(
            APP_ENV="production",
            AUTH_SECRET_KEY="a" * 64,
            CORS_ALLOW_ORIGINS="https://course.example.edu",
            AUTH_COOKIE_SECURE=True,
        )
    )
    assert all(check.ok for check in passed)


def test_python_and_web_readiness_fail_closed_on_enabled_configuration(monkeypatch) -> None:
    from ds_course_agent.tools import code_executor, web_search

    monkeypatch.setattr(
        code_executor,
        "_python_exec_setting",
        lambda name: {
            "PYTHON_EXEC_ENABLED": True,
            "PYTHON_EXEC_BACKEND": "local",
            "PYTHON_EXEC_ALLOW_HOST_FALLBACK": False,
            "PYTHON_EXEC_DOCKER_IMAGE": "python:3.11-slim",
        }[name],
    )
    assert not code_executor.check_python_execution_readiness().ok

    monkeypatch.setattr(web_search.config, "WEB_SEARCH_ENABLED", True, raising=False)
    monkeypatch.setattr(web_search.config, "WEB_SEARCH_PROVIDER", "tavily", raising=False)
    monkeypatch.setattr(web_search.config, "WEB_SEARCH_API_KEY", "", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("WEB_SEARCH_API_KEY", raising=False)
    assert not web_search.check_web_search_readiness().ok


def test_python_readiness_fails_when_docker_daemon_is_unavailable(monkeypatch) -> None:
    from ds_course_agent.tools import code_executor

    monkeypatch.setattr(
        code_executor,
        "_python_exec_setting",
        lambda name: {
            "PYTHON_EXEC_ENABLED": True,
            "PYTHON_EXEC_BACKEND": "docker",
            "PYTHON_EXEC_ALLOW_HOST_FALLBACK": False,
            "PYTHON_EXEC_DOCKER_IMAGE": "python:3.11-slim",
            "PYTHON_EXEC_DOCKER_AVAILABILITY_TTL_SECONDS": 5.0,
        }[name],
    )
    monkeypatch.setattr(code_executor._DockerPythonExecutor, "is_available", lambda self: False)

    check = code_executor.check_python_execution_readiness()

    assert not check.ok
    assert check.detail == "Docker daemon is unavailable"


def test_health_is_liveness_only_while_readyz_reports_readiness(monkeypatch) -> None:
    import ds_course_agent.api.main as main

    monkeypatch.setattr(
        main,
        "build_readiness_report",
        lambda: ReadinessReport((ReadinessCheck("retrieval_index", False, "missing"),)),
    )

    with TestClient(app) as client:
        health = client.get("/health")
        ready = client.get("/readyz")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert ready.status_code == 503
    assert ready.json()["status"] == "not_ready"
    assert ready.json()["checks"]["retrieval_index"]["status"] == "error"
