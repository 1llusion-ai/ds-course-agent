"""Token-bounded retrieval context assembly with exact source provenance."""

from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import tiktoken
from langchain_core.documents import Document


class ContextProvenanceError(ValueError):
    """Raised when a retrieved document lacks trustworthy source provenance."""


class ContextBudgetError(ValueError):
    """Raised when retrieved context or a complete answer prompt exceeds its budget."""


class TokenCounter(Protocol):
    """Count model-input tokens under one named, stable policy."""

    policy_version: str

    def count(self, text: str) -> int:
        """Return the token count for one text value."""


@dataclass(frozen=True)
class TiktokenCounter:
    """Exact tiktoken counter backed by the repository runtime cache."""

    encoding: tiktoken.Encoding
    policy_version: str = "cl100k_base_v1"

    def count(self, text: str) -> int:
        """Count tokens without rejecting model-specific special-token strings."""
        return len(self.encoding.encode(str(text or ""), disallowed_special=()))


def load_token_counter(cache_dir: str | Path, encoding_name: str = "cl100k_base") -> TiktokenCounter:
    """Load the frozen production tokenizer policy from a local cache directory."""
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(Path(cache_dir).resolve()))
    return TiktokenCounter(tiktoken.get_encoding(encoding_name))


@dataclass(frozen=True, order=True)
class SourceInterval:
    """One half-open character interval on a frozen source page."""

    source_id: str
    source_page: int
    book_page: int
    char_start: int
    char_end: int

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ContextProvenanceError("source_id must be non-empty")
        if self.source_page <= 0 or self.book_page <= 0:
            raise ContextProvenanceError("source_page and book_page must be positive")
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise ContextProvenanceError("source character interval must be non-empty and half-open")

    @property
    def key(self) -> tuple[str, int]:
        """Return the page identity used for exact de-duplication."""
        return self.source_id, self.source_page


@dataclass(frozen=True)
class ChunkProvenance:
    """Validated source contract attached to one indexed document."""

    interval: SourceInterval
    content_sha256: str
    source_page_sha256: str
    source_page_text: str

    @classmethod
    def from_document(cls, document: Document) -> ChunkProvenance:
        """Validate and parse the scalar Chroma metadata for one document."""
        metadata = dict(getattr(document, "metadata", {}) or {})
        required = (
            "metadata_schema_version",
            "source_id",
            "source_page",
            "book_page",
            "source_char_start",
            "source_char_end",
            "content_sha256",
            "source_page_sha256",
            "source_page_text",
        )
        missing = [key for key in required if key not in metadata]
        if missing:
            raise ContextProvenanceError(
                "retrieved document is missing exact production provenance: " + ", ".join(missing)
            )
        if metadata["metadata_schema_version"] != "retrieval-provenance/1.0":
            raise ContextProvenanceError("retrieved document uses an unsupported provenance schema")

        interval = SourceInterval(
            source_id=_metadata_text(metadata, "source_id"),
            source_page=_metadata_int(metadata, "source_page"),
            book_page=_metadata_int(metadata, "book_page"),
            char_start=_metadata_int(metadata, "source_char_start"),
            char_end=_metadata_int(metadata, "source_char_end"),
        )
        content = str(getattr(document, "page_content", "") or "")
        content_sha256 = _metadata_digest(metadata, "content_sha256")
        if _sha256_text(content) != content_sha256:
            raise ContextProvenanceError("retrieved document content hash does not match metadata")

        source_page_text = _metadata_text(metadata, "source_page_text", strip=False)
        source_page_sha256 = _metadata_digest(metadata, "source_page_sha256")
        if _sha256_text(source_page_text) != source_page_sha256:
            raise ContextProvenanceError("source page text hash does not match metadata")
        if interval.char_end > len(source_page_text):
            raise ContextProvenanceError("source character interval exceeds the frozen source page")
        source_fragment = source_page_text[interval.char_start : interval.char_end]
        if _normalize_text(source_fragment) != _normalize_text(content):
            raise ContextProvenanceError("source character interval does not reproduce normalized document content")

        return cls(
            interval=interval,
            content_sha256=content_sha256,
            source_page_sha256=source_page_sha256,
            source_page_text=source_page_text,
        )


@dataclass(frozen=True)
class RankedContextCandidate:
    """One vector result in its immutable retrieval order."""

    document: Document
    retrieval_rank: int
    distance: float
    provenance: ChunkProvenance

    def __post_init__(self) -> None:
        if self.retrieval_rank <= 0:
            raise ValueError("retrieval_rank must be positive")
        if self.distance < 0:
            raise ValueError("distance must be non-negative")


@dataclass(frozen=True)
class ContextAssemblyConfig:
    """Frozen production context-selection policy."""

    token_budget: int = 4096
    candidate_depth: int = 10
    tokenizer_policy: str = "cl100k_base_v1"
    deduplication_mode: str = "exact_source_interval_v1"
    overflow_policy: str = "stop_v1"
    header_policy: str = "compact_page_v1"

    def __post_init__(self) -> None:
        if self.token_budget <= 0 or self.candidate_depth <= 0:
            raise ValueError("context token budget and candidate depth must be positive")
        if self.deduplication_mode != "exact_source_interval_v1":
            raise ValueError("unsupported retrieval context de-duplication mode")
        if self.overflow_policy != "stop_v1":
            raise ValueError("unsupported retrieval context overflow policy")
        if self.header_policy != "compact_page_v1":
            raise ValueError("unsupported retrieval context header policy")


@dataclass(frozen=True)
class SelectedContextFragment:
    """One disjoint source fragment included in the model context."""

    retrieval_rank: int
    interval: SourceInterval
    text: str


@dataclass(frozen=True)
class SelectedContextDocument:
    """One retrieved document represented by its included source fragments."""

    retrieval_rank: int
    distance: float
    document: Document
    fragments: tuple[SelectedContextFragment, ...]
    context_tokens: int


@dataclass(frozen=True)
class AssembledContext:
    """Typed output of exact, token-bounded context assembly."""

    formatted_context: str
    selected: tuple[SelectedContextDocument, ...]
    token_budget: int
    used_tokens: int
    duplicate_characters_removed: int
    skipped_fully_covered_count: int
    stopped_on_overflow: bool
    overflow_retrieval_rank: int | None
    policy_version: str

    @property
    def documents(self) -> list[Document]:
        """Return clones containing only evidence actually sent to the answer model."""
        return [_clone_document(item.document) for item in self.selected]


def subtract_interval(interval: tuple[int, int], covered: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """Subtract merged half-open intervals while preserving source order."""
    start, end = interval
    if start < 0 or end <= start:
        raise ValueError("source interval end must exceed start")
    remaining: list[tuple[int, int]] = []
    cursor = start
    for covered_start, covered_end in _merge_intervals(covered):
        if covered_end <= cursor:
            continue
        if covered_start >= end:
            break
        if covered_start > cursor:
            remaining.append((cursor, min(covered_start, end)))
        cursor = max(cursor, covered_end)
        if cursor >= end:
            break
    if cursor < end:
        remaining.append((cursor, end))
    return remaining


def assemble_context(
    candidates: Sequence[RankedContextCandidate],
    *,
    config: ContextAssemblyConfig,
    token_counter: TokenCounter,
) -> AssembledContext:
    """Assemble ranked candidates without reordering or fuzzy de-duplication."""
    ordered = list(candidates[: config.candidate_depth])
    ranks = [candidate.retrieval_rank for candidate in ordered]
    if ranks != sorted(ranks) or len(ranks) != len(set(ranks)):
        raise ValueError("ranked context candidates must retain unique ascending vector ranks")
    if token_counter.policy_version != config.tokenizer_policy:
        raise ValueError("token counter policy does not match context assembly configuration")

    covered: defaultdict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
    blocks: list[str] = []
    selected: list[SelectedContextDocument] = []
    used_tokens = 0
    duplicate_characters_removed = 0
    skipped_fully_covered = 0
    stopped_on_overflow = False
    overflow_rank: int | None = None

    for candidate in ordered:
        source = candidate.provenance.interval
        remaining = subtract_interval(
            (source.char_start, source.char_end),
            covered[source.key],
        )
        removed = (source.char_end - source.char_start) - sum(end - start for start, end in remaining)
        if not remaining:
            duplicate_characters_removed += removed
            skipped_fully_covered += 1
            continue

        fragments = tuple(
            SelectedContextFragment(
                retrieval_rank=candidate.retrieval_rank,
                interval=SourceInterval(
                    source_id=source.source_id,
                    source_page=source.source_page,
                    book_page=source.book_page,
                    char_start=start,
                    char_end=end,
                ),
                text=candidate.provenance.source_page_text[start:end].strip(),
            )
            for start, end in remaining
            if candidate.provenance.source_page_text[start:end].strip()
        )
        if not fragments:
            duplicate_characters_removed += removed
            skipped_fully_covered += 1
            continue

        block = _format_block(len(selected) + 1, fragments)
        candidate_context = "".join([*blocks, block])
        candidate_tokens = token_counter.count(candidate_context)
        if candidate_tokens > config.token_budget:
            stopped_on_overflow = True
            overflow_rank = candidate.retrieval_rank
            break

        duplicate_characters_removed += removed
        selected_content = "\n[...]\n".join(fragment.text for fragment in fragments)
        selected_metadata = dict(candidate.document.metadata)
        selected_metadata["retrieval_rank"] = candidate.retrieval_rank
        selected_metadata["selected_source_intervals"] = ";".join(
            f"{fragment.interval.char_start}:{fragment.interval.char_end}" for fragment in fragments
        )
        selected.append(
            SelectedContextDocument(
                retrieval_rank=candidate.retrieval_rank,
                distance=candidate.distance,
                document=Document(page_content=selected_content, metadata=selected_metadata),
                fragments=fragments,
                context_tokens=candidate_tokens - used_tokens,
            )
        )
        blocks.append(block)
        used_tokens = candidate_tokens
        covered[source.key] = _merge_intervals([*covered[source.key], *remaining])

    return AssembledContext(
        formatted_context="".join(blocks).rstrip(),
        selected=tuple(selected),
        token_budget=config.token_budget,
        used_tokens=used_tokens,
        duplicate_characters_removed=duplicate_characters_removed,
        skipped_fully_covered_count=skipped_fully_covered,
        stopped_on_overflow=stopped_on_overflow,
        overflow_retrieval_rank=overflow_rank,
        policy_version="|".join(
            (
                config.tokenizer_policy,
                config.deduplication_mode,
                config.overflow_policy,
                config.header_policy,
            )
        ),
    )


def clone_assembled_context(context: AssembledContext) -> AssembledContext:
    """Clone mutable LangChain documents held by an assembled result."""
    return AssembledContext(
        formatted_context=context.formatted_context,
        selected=tuple(
            SelectedContextDocument(
                retrieval_rank=item.retrieval_rank,
                distance=item.distance,
                document=_clone_document(item.document),
                fragments=item.fragments,
                context_tokens=item.context_tokens,
            )
            for item in context.selected
        ),
        token_budget=context.token_budget,
        used_tokens=context.used_tokens,
        duplicate_characters_removed=context.duplicate_characters_removed,
        skipped_fully_covered_count=context.skipped_fully_covered_count,
        stopped_on_overflow=context.stopped_on_overflow,
        overflow_retrieval_rank=context.overflow_retrieval_rank,
        policy_version=context.policy_version,
    )


def _format_block(selection_rank: int, fragments: Sequence[SelectedContextFragment]) -> str:
    page = fragments[0].interval.book_page
    content = "\n[...]\n".join(fragment.text for fragment in fragments)
    return f"[片段 {selection_rank} | 教材第{page}页]\n{content}\n\n"


def _merge_intervals(intervals: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if end <= start:
            raise ValueError("covered source interval must be non-empty")
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def _metadata_text(metadata: dict[str, Any], key: str, *, strip: bool = True) -> str:
    value = metadata.get(key)
    if not isinstance(value, str):
        raise ContextProvenanceError(f"{key} must be a string")
    normalized = value.strip() if strip else value
    if not normalized:
        raise ContextProvenanceError(f"{key} must be non-empty")
    return normalized


def _metadata_int(metadata: dict[str, Any], key: str) -> int:
    value = metadata.get(key)
    if isinstance(value, bool):
        raise ContextProvenanceError(f"{key} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ContextProvenanceError(f"{key} must be an integer") from exc


def _metadata_digest(metadata: dict[str, Any], key: str) -> str:
    value = _metadata_text(metadata, key).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ContextProvenanceError(f"{key} must be a SHA-256 digest")
    return value


def _normalize_text(text: str) -> str:
    return "".join(str(text or "").split())


def _sha256_text(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _clone_document(document: Document) -> Document:
    return Document(
        page_content=str(getattr(document, "page_content", "") or ""),
        metadata=dict(getattr(document, "metadata", {}) or {}),
    )


__all__ = [
    "AssembledContext",
    "ChunkProvenance",
    "ContextAssemblyConfig",
    "ContextBudgetError",
    "ContextProvenanceError",
    "RankedContextCandidate",
    "SelectedContextDocument",
    "SelectedContextFragment",
    "SourceInterval",
    "TiktokenCounter",
    "TokenCounter",
    "assemble_context",
    "clone_assembled_context",
    "load_token_counter",
    "subtract_interval",
]
