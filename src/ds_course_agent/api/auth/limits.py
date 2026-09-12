"""Bound login attempts before expensive password verification in one API process."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class LoginLimit:
    """Sliding-window limits shared by account and trusted peer identities."""

    window_seconds: int
    per_account: int
    per_ip: int


class LoginRateLimiter:
    """Atomically admit both identities, with bounded memory and no background task."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, max_keys: int = 4096) -> None:
        self._clock = clock
        self._max_keys = max_keys
        self._attempts: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def retry_after(self, username: str, peer: str, limit: LoginLimit) -> int:
        """Reserve an attempt, or return the seconds until it can be retried."""

        now = self._clock()
        cutoff = now - limit.window_seconds
        keys = (("account", username), ("peer", peer))
        with self._lock:
            for key, attempts in list(self._attempts.items()):
                while attempts and attempts[0] <= cutoff:
                    attempts.popleft()
                if not attempts:
                    del self._attempts[key]
            waits = [
                self._attempts[key][0] + limit.window_seconds - now
                for key, maximum in zip(keys, (limit.per_account, limit.per_ip), strict=True)
                if len(self._attempts.get(key, ())) >= maximum
            ]
            if waits:
                return max(1, math.ceil(max(waits)))
            if len(self._attempts) + sum(key not in self._attempts for key in keys) > self._max_keys:
                # Do not evict live identities: that would let rotating names bypass limits.
                return max(1, math.ceil(min(values[0] for values in self._attempts.values()) - cutoff))
            for key in keys:
                self._attempts.setdefault(key, deque()).append(now)
            return 0

    def clear(self) -> None:
        """Reset counters for isolated tests and a fresh application lifecycle."""

        with self._lock:
            self._attempts.clear()


login_rate_limiter = LoginRateLimiter()
