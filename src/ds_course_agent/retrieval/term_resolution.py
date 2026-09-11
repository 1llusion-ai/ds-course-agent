"""Conservative course-term lookup and typo resolution for short queries."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum

from langchain_core.documents import Document

from ds_course_agent.shared.term_queries import parse_short_term_query

_CORPUS_ACRONYM = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{2,7})(?![A-Za-z0-9])")
COURSE_TERM_POLICY_VERSION = "bounded_course_term_v3"


class CourseTermMatchKind(str, Enum):
    """How a term-like course query was resolved."""

    EXACT = "exact"
    CORRECTED = "corrected"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class CourseTermResolution:
    """Typed result for one term-like query."""

    requested_term: str
    resolved_term: str | None
    resolved_query: str
    match_kind: CourseTermMatchKind
    policy_version: str = COURSE_TERM_POLICY_VERSION

    @property
    def corrected(self) -> bool:
        """Return whether the query was corrected to a different course term."""

        return self.match_kind is CourseTermMatchKind.CORRECTED


@dataclass(frozen=True)
class CourseTermLookup:
    """A term resolution plus direct-evidence documents from the course index."""

    resolution: CourseTermResolution
    documents: tuple[Document, ...]


class CourseTermIndex:
    """Resolve single short terms against exact text in the promoted index."""

    def __init__(self, documents: list[Document]) -> None:
        self._documents = tuple(_clone_document(document) for document in documents)
        self._term_documents = self._index_corpus_terms(self._documents)

    @classmethod
    def from_collection_payload(cls, payload: dict) -> CourseTermIndex:
        """Build a term index from a Chroma ``get`` response."""

        ids = list(payload.get("ids") or [])
        texts = list(payload.get("documents") or [])
        metadatas = list(payload.get("metadatas") or [])
        if not (len(ids) == len(texts) == len(metadatas)):
            raise ValueError("Chroma returned inconsistent term-index columns")
        documents = []
        for chunk_id, text, metadata in zip(ids, texts, metadatas, strict=True):
            document_metadata = dict(metadata or {})
            document_metadata.setdefault("chunk_id", str(chunk_id))
            documents.append(Document(page_content=str(text or ""), metadata=document_metadata))
        return cls(documents)

    def lookup(self, question: str) -> CourseTermLookup | None:
        """Resolve one explicit short-term query, or return ``None`` when inapplicable."""

        parsed = parse_short_term_query(question)
        if parsed is None:
            return None
        requested_term = parsed.term
        normalized = requested_term.upper()
        exact_documents = self._documents_containing(normalized)
        if exact_documents:
            return CourseTermLookup(
                resolution=CourseTermResolution(
                    requested_term=requested_term,
                    resolved_term=normalized,
                    resolved_query=str(question),
                    match_kind=CourseTermMatchKind.EXACT,
                ),
                documents=exact_documents,
            )

        corrected = self._nearest_course_term(requested_term) if parsed.is_uppercase_identifier else None
        if corrected is None:
            return CourseTermLookup(
                resolution=CourseTermResolution(
                    requested_term=requested_term,
                    resolved_term=None,
                    resolved_query=str(question),
                    match_kind=CourseTermMatchKind.UNRESOLVED,
                ),
                documents=(),
            )

        resolved_query = parsed.replace(question, corrected)
        return CourseTermLookup(
            resolution=CourseTermResolution(
                requested_term=requested_term,
                resolved_term=corrected,
                resolved_query=resolved_query,
                match_kind=CourseTermMatchKind.CORRECTED,
            ),
            documents=self._documents_containing(corrected),
        )

    @staticmethod
    def _index_corpus_terms(documents: tuple[Document, ...]) -> dict[str, tuple[int, ...]]:
        occurrences: dict[str, set[int]] = defaultdict(set)
        counts: Counter[str] = Counter()
        for index, document in enumerate(documents):
            source_text = _document_search_text(document)
            for match in _CORPUS_ACRONYM.finditer(source_text):
                term = match.group(1)
                counts[term] += 1
                occurrences[term].add(index)
        return {term: tuple(sorted(indexes)) for term, indexes in occurrences.items() if counts[term] >= 2}

    def _documents_containing(self, term: str) -> tuple[Document, ...]:
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.IGNORECASE)
        matches = [
            _clone_document(document) for document in self._documents if pattern.search(_document_search_text(document))
        ]
        matches.sort(key=_document_sort_key)
        return tuple(matches)

    def _nearest_course_term(self, requested_term: str) -> str | None:
        normalized = requested_term.upper()
        candidates = [term for term in self._term_documents if len(term) == len(normalized)]
        if not candidates:
            return None
        ranked = sorted((_levenshtein_distance(normalized, term), term) for term in candidates)
        best_distance, best_term = ranked[0]
        maximum_distance = 1 if len(normalized) <= 3 else 2
        if best_distance > maximum_distance:
            return None
        if len(ranked) > 1 and ranked[1][0] <= best_distance:
            return None
        return best_term


def _document_search_text(document: Document) -> str:
    return str(getattr(document, "page_content", "") or "")


def _document_sort_key(document: Document) -> tuple[int, int, str]:
    metadata = dict(getattr(document, "metadata", {}) or {})
    return (
        int(metadata.get("book_page") or metadata.get("book_page_start") or 0),
        int(metadata.get("source_char_start") or 0),
        str(metadata.get("chunk_id") or ""),
    )


def _levenshtein_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _clone_document(document: Document) -> Document:
    return Document(
        page_content=str(getattr(document, "page_content", "") or ""),
        metadata=dict(getattr(document, "metadata", {}) or {}),
    )


__all__ = [
    "COURSE_TERM_POLICY_VERSION",
    "CourseTermIndex",
    "CourseTermLookup",
    "CourseTermMatchKind",
    "CourseTermResolution",
]
