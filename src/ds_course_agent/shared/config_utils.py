"""Small typed-config readers used outside ``shared.config``.

The project exports Pydantic-backed constants from ``ds_course_agent.shared
.config``.  Tests and admin hooks also monkeypatch those module attributes
directly, so these helpers use one consistent lookup order and clamp behavior
without requiring every caller to duplicate ``getattr``/``try`` blocks.
"""

from __future__ import annotations

from typing import Any

import ds_course_agent.shared.config as config

_MISSING = object()


def config_value(name: str, default: Any = _MISSING) -> Any:
    """Read a setting from the public config module or schema default."""

    if hasattr(config, name):
        return getattr(config, name)

    settings = getattr(config, "settings", None)
    if settings is not None and hasattr(settings, name):
        return getattr(settings, name)

    try:
        from ds_course_agent.shared.config.schema import Settings

        field = Settings.model_fields.get(name)
        if field is not None:
            return field.default
    except Exception:
        pass

    if default is not _MISSING:
        return default
    raise AttributeError(name)


def config_bool(name: str, default: bool = False) -> bool:
    """Read a bool setting with common string coercions."""

    value = config_value(name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def config_int(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """Read an int setting and apply optional clamps."""

    try:
        value = int(config_value(name, default))
    except (TypeError, ValueError):
        value = int(default)
    if minimum is not None:
        value = max(value, int(minimum))
    if maximum is not None:
        value = min(value, int(maximum))
    return value


def config_float(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    """Read a float setting and apply optional clamps."""

    try:
        value = float(config_value(name, default))
    except (TypeError, ValueError):
        value = float(default)
    if minimum is not None:
        value = max(value, float(minimum))
    if maximum is not None:
        value = min(value, float(maximum))
    return value


def config_str(name: str, default: str = "") -> str:
    """Read a string setting and normalize ``None`` to ``default``."""

    value = config_value(name, default)
    if value is None:
        return str(default)
    return str(value)


__all__ = [
    "config_bool",
    "config_float",
    "config_int",
    "config_str",
    "config_value",
]
