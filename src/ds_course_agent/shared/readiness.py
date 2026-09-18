"""Typed read-only readiness results shared by runtime owners and API edges."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReadinessCheck:
    """One named readiness check with a safe, user-facing detail string."""

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class ReadinessReport:
    """Aggregate readiness result before projecting it into HTTP JSON."""

    checks: tuple[ReadinessCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def as_dict(self) -> dict[str, object]:
        return {
            "status": "ok" if self.ok else "not_ready",
            "service": "rag-tutor-backend",
            "checks": {
                check.name: {"status": "ok" if check.ok else "error", "detail": check.detail} for check in self.checks
            },
        }


__all__ = ["ReadinessCheck", "ReadinessReport"]
