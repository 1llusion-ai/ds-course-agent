"""Content-free request and stage logging for assessment failures."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from time import perf_counter
from uuid import uuid4

logger = logging.getLogger(__name__)


class AssessmentStage(str, Enum):
    """Finite assessment stages used only for diagnostics."""

    REQUEST = "request"
    TARGET = "target"
    RETRIEVAL = "retrieval"
    EVIDENCE = "evidence"
    GENERATION = "generation"
    VERIFICATION = "verification"
    CRITIQUE = "critique"


@dataclass(frozen=True)
class AssessmentTrace:
    """Correlate stages without logging prompts, credentials, or exception text."""

    request_id: str

    @contextmanager
    def stage(self, stage: AssessmentStage, *, round_index: int = 0, count: int = 0) -> Iterator[None]:
        """Record timing and exception class chains, never exception messages."""
        started = perf_counter()
        status = "ok"
        error_types: list[str] = []
        try:
            yield
        except Exception as exc:
            status = "error"
            current: BaseException | None = exc
            seen: set[int] = set()
            while current is not None and id(current) not in seen:
                seen.add(id(current))
                error_types.append(type(current).__name__)
                current = current.__cause__ or current.__context__
            raise
        finally:
            logger.info(
                "assessment request_id=%s stage=%s round=%s count=%s status=%s duration_ms=%s error_types=%s",
                self.request_id,
                stage.value,
                round_index,
                count,
                status,
                round((perf_counter() - started) * 1000),
                ",".join(error_types) or "none",
            )


def new_assessment_trace() -> AssessmentTrace:
    """Allocate a request correlation ID for a single service invocation."""
    return AssessmentTrace(uuid4().hex)
