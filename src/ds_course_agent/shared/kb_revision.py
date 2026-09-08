"""Cross-process revision tokens for knowledge-base mutations and readers."""

from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import ds_course_agent.shared.config as config


def _path(collection: str, directory: str | None = None) -> Path:
    key = hashlib.sha256(collection.encode()).hexdigest()
    return Path(directory or config.CHROMA_PERSIST_DIR) / f"revision-{key}"


def read_kb_revision(collection: str, directory: str | None = None) -> str:
    """Read a collection's committed revision, including pre-versioned stores."""

    try:
        return _path(collection, directory).read_text(encoding="ascii")
    except FileNotFoundError:
        return "legacy"


def _publish(collection: str, directory: str | None) -> None:
    target = _path(collection, directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".revision-")
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(uuid.uuid4().hex)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def knowledge_base_write(collection: str, directory: str | None = None) -> Iterator[None]:
    """Invalidate before and after a write, including partially failed writes.

    Reads during a rebuild may see an intermediate corpus; their revision cannot
    be reused after the writer completes. This is invalidation, not a transaction.
    """

    _publish(collection, directory)
    try:
        yield
    finally:
        _publish(collection, directory)
