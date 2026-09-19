"""Process-local request quota for authenticated business API routes."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from math import ceil

from fastapi import Depends, HTTPException, status

import ds_course_agent.shared.config as config

from .auth.deps import get_current_student_id


@dataclass(frozen=True, slots=True)
class ApiRequestQuotaDecision:
    """Result of reserving one authenticated API request."""

    allowed: bool
    retry_after_seconds: int = 0


class ApiRequestQuota:
    """Bound one student's authenticated API requests in a sliding window."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._student_events: dict[str, deque[float]] = {}

    @staticmethod
    def _trim(events: deque[float], cutoff: float) -> None:
        while events and events[0] <= cutoff:
            events.popleft()

    @staticmethod
    def _retry_after(events: deque[float], now: float, window_seconds: int) -> int:
        if not events:
            return 1
        return max(1, int(ceil(events[0] + window_seconds - now)))

    def try_acquire(
        self,
        *,
        student_id: str,
        limit: int,
        window_seconds: int,
    ) -> ApiRequestQuotaDecision:
        """Reserve one request when the configured student limit allows it."""

        if limit <= 0:
            return ApiRequestQuotaDecision(True)

        normalized_student_id = str(student_id or "").strip()
        if not normalized_student_id:
            return ApiRequestQuotaDecision(False, retry_after_seconds=max(1, int(window_seconds)))

        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            for key, events in list(self._student_events.items()):
                self._trim(events, cutoff)
                if not events:
                    del self._student_events[key]

            events = self._student_events.setdefault(normalized_student_id, deque())
            if len(events) >= limit:
                return ApiRequestQuotaDecision(
                    False,
                    retry_after_seconds=self._retry_after(events, now, window_seconds),
                )

            events.append(now)
            return ApiRequestQuotaDecision(True)


_api_request_quota = ApiRequestQuota()


def enforce_api_request_quota(student_id: str = Depends(get_current_student_id)) -> str:
    """Authenticate and reserve one request for a business API route."""

    decision = _api_request_quota.try_acquire(
        student_id=student_id,
        limit=int(getattr(config, "API_PER_STUDENT_REQUESTS_PER_WINDOW", 0) or 0),
        window_seconds=max(1, int(getattr(config, "API_REQUEST_QUOTA_WINDOW_SECONDS", 3600) or 3600)),
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后重试。",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )
    return student_id


__all__ = ["ApiRequestQuota", "ApiRequestQuotaDecision", "enforce_api_request_quota"]
