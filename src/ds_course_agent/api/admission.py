"""One process-wide admission owner for HTTP chat work, including detached streams."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from fastapi import HTTPException

import ds_course_agent.shared.config as config


@dataclass
class ChatLease:
    """Reserve capacity until the actual worker ends, independently of its HTTP client."""

    owner: ChatAdmission
    student_id: str
    _released: bool = field(default=False, init=False)

    def release(self) -> None:
        """Return capacity once, including exception and disconnect paths."""

        self.owner.release(self)


class ChatAdmission:
    """Bound running and waiting chat requests globally and per authenticated student."""

    def __init__(self) -> None:
        self._students: dict[str, int] = {}
        self._active = 0
        self._lock = threading.Lock()

    def acquire(self, student_id: str) -> ChatLease:
        """Reject overload before response headers or new history are written."""

        with self._lock:
            if self._active >= config.API_CHAT_MAX_CONCURRENT or (
                self._students.get(student_id, 0) >= config.API_CHAT_MAX_PER_STUDENT
            ):
                raise HTTPException(
                    status_code=429, detail="当前生成任务较多，请稍后重试", headers={"Retry-After": "5"}
                )
            self._active += 1
            self._students[student_id] = self._students.get(student_id, 0) + 1
            return ChatLease(self, student_id)

    def release(self, lease: ChatLease) -> None:
        """Release the lease under the same lock used by admission."""

        with self._lock:
            if lease._released:
                return
            lease._released = True
            self._active -= 1
            remaining = self._students[lease.student_id] - 1
            if remaining:
                self._students[lease.student_id] = remaining
            else:
                del self._students[lease.student_id]


chat_admission = ChatAdmission()
