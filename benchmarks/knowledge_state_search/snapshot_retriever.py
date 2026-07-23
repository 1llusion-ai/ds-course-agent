"""Deterministic retrieval over the fixed evidence snapshot."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from benchmarks.knowledge_state_search.evidence import EvidenceSnapshot, SnapshotSource


@dataclass(frozen=True)
class SnapshotSearchHit:
    """One source returned by the fixed-snapshot retriever."""

    source_id: str
    title: str
    score: float


class SnapshotRetriever:
    """A deterministic lexical retriever with a shared source-quality prior."""

    def __init__(self, snapshot: EvidenceSnapshot) -> None:
        self._snapshot = snapshot

    def search(self, *, task_id: str, query: str, top_k: int = 5) -> tuple[SnapshotSearchHit, ...]:
        """Return deterministic source hits for one task and query."""

        if not query.strip():
            raise ValueError("snapshot query must be non-empty")
        if top_k < 1:
            raise ValueError("top_k must be positive")
        sources = [source for source in self._snapshot.sources if source.task_id == task_id]
        if not sources:
            raise ValueError(f"unknown task in snapshot: {task_id}")
        query_tokens = _tokens(query)
        ranked = []
        for source in sources:
            lexical_score = _score(query_tokens, source)
            if lexical_score <= 0:
                continue
            ranked.append(
                (
                    lexical_score + _source_quality_bonus(source),
                    source.source_id,
                    source,
                )
            )
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return tuple(
            SnapshotSearchHit(source_id=source.source_id, title=source.title, score=score)
            for score, _, source in ranked
        )[:top_k]


def _tokens(text: str) -> frozenset[str]:
    normalised = re.sub(r"\bk[\s-]?means\b", "kmeans", text.lower())
    raw_tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", normalised)
    return frozenset(_canonical_token(token) for token in raw_tokens)


_TOKEN_ALIASES = {
    "kmeans": "kmeans",
    "objective": "objective",
    "objectives": "objective",
    "inertia": "objective",
    "criterion": "objective",
    "sse": "objective",
    "initial": "initialization",
    "initialize": "initialization",
    "initialized": "initialization",
    "initialization": "initialization",
    "seed": "initialization",
    "seeds": "initialization",
    "iteration": "update",
    "iterations": "update",
    "iterative": "update",
    "iterate": "update",
    "alternating": "update",
    "alternation": "update",
    "update": "update",
    "updates": "update",
    "assignment": "assignment",
    "assignments": "assignment",
    "assign": "assignment",
    "center": "centroid",
    "centers": "centroid",
    "centroid": "centroid",
    "centroids": "centroid",
    "minimum": "minimum",
    "minima": "minimum",
    "minimization": "minimum",
    "minimize": "minimum",
    "optimum": "optimum",
    "optima": "optimum",
    "optimal": "optimum",
    "eigenvector": "eigenvector",
    "eigenvectors": "eigenvector",
    "component": "component",
    "components": "component",
    "variance": "variance",
    "variances": "variance",
    "correlation": "correlation",
    "correlations": "correlation",
}


def _canonical_token(token: str) -> str:
    """Map transparent spelling variants to a deterministic retrieval token."""

    return _TOKEN_ALIASES.get(token, token)


def _score(query_tokens: frozenset[str], source: SnapshotSource) -> float:
    if not query_tokens:
        return 0.0
    source_tokens = _tokens(f"{source.title} {source.text}")
    if not source_tokens:
        return 0.0
    return len(query_tokens & source_tokens) / len(query_tokens)


def _source_quality_bonus(source: SnapshotSource) -> float:
    """Prefer stable educational/official hosts without using claim labels."""

    hostname = (urlparse(source.url).hostname or "").lower()
    if hostname.endswith((".edu", ".ac.uk")):
        return 0.2
    if hostname in {"scikit-learn.org", "www.scikit-learn.org", "developers.google.com"}:
        return 0.1
    return 0.0
