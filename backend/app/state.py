"""Compatibility wrapper for migrated backend state."""

from apps.api.app.state import (
    DEFAULT_SESSION_TITLE,
    STATE_FILE,
    _chat_history,
    _deleted_session_ids,
    _load,
    _save,
    _sessions,
    purge_session,
)


__all__ = [
    "DEFAULT_SESSION_TITLE",
    "STATE_FILE",
    "_chat_history",
    "_deleted_session_ids",
    "_load",
    "_save",
    "_sessions",
    "purge_session",
]
