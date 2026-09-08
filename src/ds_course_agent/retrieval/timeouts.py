"""Timeout policies shared by retrieval implementations."""

from __future__ import annotations

import ds_course_agent.shared.config as config

_DEFAULT_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS = 2.0


def retrieval_embedding_timeout_seconds() -> float:
    """Return the configured non-negative retrieval embedding timeout."""

    return max(
        0.0,
        float(
            getattr(
                config,
                "RAG_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS",
                _DEFAULT_RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS,
            )
            or 0.0
        ),
    )


__all__ = ["retrieval_embedding_timeout_seconds"]
