"""Read-only checks for settings that are unsafe to leave implicit in production."""

from __future__ import annotations

from urllib.parse import urlsplit

from ds_course_agent.shared.config.schema import Settings
from ds_course_agent.shared.readiness import ReadinessCheck

_WEAK_SECRET_VALUES = {"", "change-me", "changeme", "secret", "test-secret", "your-secret-key"}


def _cors_origins(value: str) -> tuple[str, ...]:
    return tuple(origin.strip() for origin in str(value or "").split(",") if origin.strip())


def check_production_settings(settings: Settings) -> tuple[ReadinessCheck, ...]:
    """Validate production-only settings without making network or model calls."""

    if settings.APP_ENV != "production":
        return (
            ReadinessCheck(
                "production_settings",
                True,
                f"APP_ENV={settings.APP_ENV}; production-only checks are disabled",
            ),
        )

    checks: list[ReadinessCheck] = []
    secret = str(settings.AUTH_SECRET_KEY or "").strip()
    secret_ok = len(secret) >= 32 and secret.lower() not in _WEAK_SECRET_VALUES
    checks.append(
        ReadinessCheck(
            "auth_secret_key",
            secret_ok,
            "configured" if secret_ok else "AUTH_SECRET_KEY must be at least 32 characters and non-default",
        )
    )

    origins = _cors_origins(settings.CORS_ALLOW_ORIGINS)
    origin_errors: list[str] = []
    for origin in origins:
        parsed = urlsplit(origin)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
            origin_errors.append(origin)
    origins_ok = bool(origins) and not origin_errors and "*" not in origins
    checks.append(
        ReadinessCheck(
            "cors_origins",
            origins_ok,
            "configured HTTPS origins"
            if origins_ok
            else "production CORS must contain one or more HTTPS origins without wildcard/path entries",
        )
    )
    checks.append(
        ReadinessCheck(
            "secure_cookie",
            bool(settings.AUTH_COOKIE_SECURE),
            "enabled" if settings.AUTH_COOKIE_SECURE else "AUTH_COOKIE_SECURE must be true in production",
        )
    )
    return tuple(checks)


__all__ = ["check_production_settings"]
