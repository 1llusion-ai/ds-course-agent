"""Configuration loading helpers."""

from __future__ import annotations

from functools import lru_cache

from dotenv import load_dotenv

from ds_course_agent.shared.config.schema import Settings
from ds_course_agent.shared.paths import PROJECT_ROOT


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    """Load and validate settings once for the current process."""

    # Preserve the old side effect that made .env values visible to code paths
    # that still read os.environ directly (for example Datalab parser helpers).
    load_dotenv(PROJECT_ROOT / ".env")
    return Settings()


def reload_settings() -> Settings:
    """Clear the settings cache and load a fresh settings object."""

    load_settings.cache_clear()
    return load_settings()


__all__ = ["load_settings", "reload_settings"]
