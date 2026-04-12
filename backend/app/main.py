"""Compatibility FastAPI entrypoint for legacy imports and tooling."""

from apps.api.app.main import app


__all__ = ["app"]
