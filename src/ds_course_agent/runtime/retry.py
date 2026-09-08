"""Structured retry policy for model-runtime call boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RetryAction(str, Enum):
    """Action selected after a model attempt is classified."""

    RETRY = "retry"
    RETURN = "return"


@dataclass(frozen=True)
class RetryPolicy:
    """Bound model attempts and provide deterministic exponential backoff."""

    max_retries: int
    initial_delay_seconds: float = 1.0
    backoff_factor: float = 2.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_retries", max(0, int(self.max_retries)))
        if self.initial_delay_seconds <= 0:
            raise ValueError("initial_delay_seconds must be positive")
        if self.backoff_factor < 1:
            raise ValueError("backoff_factor must be at least 1")

    @property
    def max_attempts(self) -> int:
        """Return the initial attempt plus the configured retries."""

        return self.max_retries + 1

    def attempts(self, *, start_attempt: int = 0) -> range:
        """Return the bounded attempt indexes still available for a call."""

        return range(max(0, int(start_attempt)), self.max_attempts)

    def should_retry(self, attempt: int) -> bool:
        """Return whether another attempt is within this policy's budget."""

        return int(attempt) < self.max_retries

    def delay_seconds(self, attempt: int) -> float:
        """Return the deterministic delay before retrying after ``attempt``."""

        return self.initial_delay_seconds * self.backoff_factor ** max(0, int(attempt))


@dataclass(frozen=True)
class RetryResolution:
    """Typed result of classifying one failed model attempt."""

    action: RetryAction
    response: str = ""


__all__ = ["RetryAction", "RetryPolicy", "RetryResolution"]
