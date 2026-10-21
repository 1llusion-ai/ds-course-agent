"""Concept resolution and conservative evidence selection for question generation."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Protocol

from ds_course_agent.assessment.formulas import analyze_formula_quality
from ds_course_agent.assessment.models import (
    AssessmentEvidenceSpan,
    EvidenceCompleteness,
    EvidenceSource,
    FormulaQuality,
    GenerateQuestionsRequest,
    SourceInterval,
)
from ds_course_agent.courses import CourseCatalog
from ds_course_agent.shared.paths import PROJECT_ROOT
from ds_course_agent.teaching.knowledge_map import AssessmentComponent, get_knowledge_map


class InvalidAssessmentTarget(ValueError):
    """An explicit concept identity is unknown or conflicts with the topic."""


class EvidenceDocument(Protocol):
    """Read-only view of a retrieved document."""

    page_content: str
    metadata: Mapping[str, Any]


class EvidenceWindowReader(Protocol):
    """Read a bounded source-page window without changing retrieval ranking."""

    def read_evidence_window(self, document: EvidenceDocument) -> Sequence[EvidenceDocument]:
        """Return hash-validated source pages around one retrieved document."""


@dataclass
class EvidenceSelectionDiagnostics:
    """Counters explaining why retrieved documents did or did not become evidence."""

    retrieved_documents: int = 0
    contents_documents: int = 0
    invalid_provenance_documents: int = 0
    candidate_sentences: int = 0
    accepted_sentences: int = 0
    accepted_spans: int = 0
    required_sentences: int = 0
    question_count: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "retrieved_documents": self.retrieved_documents,
            "contents_documents": self.contents_documents,
            "invalid_provenance_documents": self.invalid_provenance_documents,
            "candidate_sentences": self.candidate_sentences,
            "accepted_sentences": self.accepted_sentences,
            "accepted_spans": self.accepted_spans,
            "required_sentences": self.required_sentences,
            "question_count": self.question_count,
        }


@dataclass(frozen=True)
class AssessmentTarget:
    """Canonical target and permitted lexical evidence anchors."""

    concept_id: str | None
    name: str
    aliases: tuple[str, ...]
    chapter: str = ""
    section: str = ""
    components: tuple[AssessmentComponent, ...] = ()

    @property
    def requirements(self) -> tuple[AssessmentComponent, ...]:
        """Every declared member must have factual support and batch coverage."""
        return self.components or (
            AssessmentComponent(component_id=self.concept_id or self.name, anchors=self.aliases or (self.name,)),
        )

    @property
    def query(self) -> str:
        """Expand with bounded aliases, never neighboring concepts."""
        normalized_name = _normalized(self.name)
        aliases = tuple(alias for alias in self.aliases if _normalized(alias) != normalized_name)
        return " ".join(
            dict.fromkeys(
                (self.name, *aliases[:3], *(anchor for member in self.components for anchor in member.anchors[:2]))
            )
        )


def _normalized(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def resolve_target(
    request: GenerateQuestionsRequest,
    *,
    course_id: str = "data-science-intro",
) -> AssessmentTarget:
    """Resolve identities through the teaching-owned validated course resources."""
    manifest = CourseCatalog.from_directory(PROJECT_ROOT / "data/courses").require(course_id)
    for concept in get_knowledge_map(manifest).nodes:
        if concept.canonical_id == request.target_kc_id:
            return AssessmentTarget(
                concept.canonical_id,
                concept.display_name,
                tuple(dict.fromkeys((concept.display_name, *concept.aliases))),
                concept.chapter,
                concept.section,
                concept.assessment_components,
            )
    raise InvalidAssessmentTarget("unknown course concept")


def _anchor_pattern(target: AssessmentTarget) -> re.Pattern[str]:
    patterns = []
    acronyms = re.findall(r"[A-Za-z]{3,}", target.name)
    for alias in (*target.aliases, *acronyms, *(anchor for member in target.components for anchor in member.anchors)):
        compact = _normalized(alias)
        if not compact:
            continue
        pattern = r"\s*".join(re.escape(char) for char in compact)
        if compact[0].isascii() and compact[0].isalnum():
            pattern = r"(?<![a-zA-Z0-9_])" + pattern
        if compact[-1].isascii() and compact[-1].isalnum():
            pattern += r"(?![a-zA-Z0-9_])"
        patterns.append(pattern)
    return re.compile("|".join(patterns), re.IGNORECASE)


def mentions_target(text: str, target: AssessmentTarget) -> bool:
    """Check an explicit lexical target anchor, not semantic correctness."""
    return bool(_anchor_pattern(target).search(text))


def _is_contents(text: str, metadata: Mapping[str, Any]) -> bool:
    if str(metadata.get("chunk_type", "")).lower() in {"toc", "table_of_contents", "contents"}:
        return True
    # OCR may flatten an entire contents page into one line without a type tag.
    entries = re.findall(r"\d+(?:\.\d+){1,3}\s+[^\n。！？]{1,50}?\s+\d{1,3}(?=\s|$)", text)
    return len(entries) >= 4 and len(re.findall(r"[。！？]", text)) < 3


def _source_metadata(metadata: Mapping[str, Any]) -> tuple[str | None, int | None]:
    source = next(
        (str(metadata[key]).strip()[:500] for key in ("source", "file_name", "filename") if metadata.get(key)), None
    )
    page = None
    for key in ("book_page", "book_page_start", "page", "page_start"):
        raw = metadata.get(key)
        if isinstance(raw, bool) or not re.fullmatch(r"\d+", str(raw)):
            continue
        if 1 <= int(raw) <= 100_000:
            page = int(raw)
            break
    return source or None, page


def _has_balanced_delimiters(text: str) -> bool:
    """Treat round-bracket widths alike only in the prose validation view."""
    pairs = {"(": ")", "[": "]", "{": "}", "【": "】", "《": "》"}
    closers = set(pairs.values())
    stack: list[str] = []
    for character in text.translate(str.maketrans("（）", "()")):
        if character in pairs:
            stack.append(pairs[character])
        elif character in closers:
            if not stack or stack.pop() != character:
                return False
    return not stack


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _SourcePage:
    text: str
    source_id: str
    page: int
    digest: str
    book_page: int | None
    offset: int


@dataclass(frozen=True)
class _DocumentWindow:
    text: str
    pages: tuple[_SourcePage, ...]
    starts_complete: bool
    ends_complete: bool

    def intervals(self, start: int, end: int) -> tuple[SourceInterval, ...]:
        return tuple(
            SourceInterval(
                source_id=page.source_id,
                source_page=page.page,
                start=max(start - page.offset, 0),
                end=min(end - page.offset, len(page.text)),
                page_sha256=page.digest,
            )
            for page in self.pages
            if start < page.offset + len(page.text) and end > page.offset
        )


def _assemble_document_span(
    document: EvidenceDocument,
    evidence_window_reader: EvidenceWindowReader | None,
) -> _DocumentWindow | None:
    """Validate every bounded window page before retaining exact original offsets."""
    metadata = document.metadata
    if metadata.get("metadata_schema_version") != "retrieval-provenance/1.0":
        if metadata.get("parser_source") == "marker_v2":
            return None
        return _DocumentWindow(document.page_content, (), True, True)
    if evidence_window_reader is None:
        return None
    try:
        page_text = str(metadata["source_page_text"])
        start, end = int(metadata["source_char_start"]), int(metadata["source_char_end"])
        source_id, center = str(metadata["source_id"]), int(metadata["source_page"])
        if not page_text or start < 0 or end <= start or end > len(page_text):
            return None
        if _sha256_text(page_text) != str(metadata["source_page_sha256"]):
            return None
        if _normalized(page_text[start:end]) != _normalized(document.page_content):
            if not metadata.get("selected_source_intervals"):
                return None
        pages = sorted(
            evidence_window_reader.read_evidence_window(document), key=lambda page: int(page.metadata["source_page"])
        )
        numbers = [int(page.metadata["source_page"]) for page in pages]
        if center not in numbers or len(pages) > 3 or any(abs(number - center) > 1 for number in numbers):
            return None
        if any(right != left + 1 for left, right in zip(numbers, numbers[1:], strict=False)):
            return None
        offset = 0
        original = []
        for page, number in zip(pages, numbers, strict=True):
            if page.metadata["source_id"] != source_id:
                return None
            digest = _sha256_text(page.page_content)
            expected = page.metadata.get("source_page_sha256")
            if digest != expected:
                return None
            original.append(
                _SourcePage(page.page_content, source_id, number, digest, _source_metadata(page.metadata)[1], offset)
            )
            offset += len(page.page_content)
        return _DocumentWindow("".join(page.text for page in original), tuple(original), False, False)
    except (KeyError, TypeError, ValueError):
        return None


def covered_components(text: str, target: AssessmentTarget) -> frozenset[str]:
    """Locate declared members without promoting their terms to identity aliases."""
    return frozenset(
        member.component_id
        for member in target.requirements
        if mentions_target(text, AssessmentTarget(None, member.anchors[0], member.anchors))
    )


def has_target_coverage(texts: Sequence[str], target: AssessmentTarget) -> bool:
    """Require every declared member in the actual assessed batch."""
    covered = set().union(*(covered_components(text, target) for text in texts))
    return covered >= {member.component_id for member in target.requirements}


def _formula_identity(formula: str) -> str:
    return formula.split("=", 1)[0] if "=" in formula else formula


def _remove_formula_conflicts(spans: list[AssessmentEvidenceSpan]) -> list[AssessmentEvidenceSpan]:
    formulas_by_identity: dict[str, set[str]] = {}
    for span in spans:
        for formula in span.formulas:
            formulas_by_identity.setdefault(_formula_identity(formula), set()).add(formula)
    conflicting = {identity for identity, formulas in formulas_by_identity.items() if len(formulas) > 1}
    if not conflicting:
        return spans
    return [span for span in spans if not any(_formula_identity(formula) in conflicting for formula in span.formulas)]


def select_evidence_spans(
    documents: Sequence[EvidenceDocument],
    target: AssessmentTarget,
    *,
    max_sources: int,
    max_chars: int,
    question_count: int,
    evidence_window_reader: EvidenceWindowReader | None = None,
    diagnostics: EvidenceSelectionDiagnostics | None = None,
) -> list[AssessmentEvidenceSpan]:
    """Select complete, non-conflicting target evidence spans."""
    pattern = _anchor_pattern(target)
    if diagnostics is not None:
        diagnostics.retrieved_documents = len(documents)
        diagnostics.question_count = question_count
        diagnostics.required_sentences = 0
    ranked = sorted(
        enumerate(documents),
        key=lambda pair: (
            not (target.section and target.section == pair[1].metadata.get("subsection_no")),
            not (
                target.chapter
                and target.chapter in (pair[1].metadata.get("chapter_no"), pair[1].metadata.get("chapter"))
            ),
            pair[0],
        ),
    )
    seen: list[str] = []
    spans: list[AssessmentEvidenceSpan] = []
    remaining = max_chars
    for _, document in ranked:
        if _is_contents(document.page_content, document.metadata):
            if diagnostics is not None:
                diagnostics.contents_documents += 1
            continue
        window = _assemble_document_span(document, evidence_window_reader)
        if window is None:
            if diagnostics is not None:
                diagnostics.invalid_provenance_documents += 1
            continue
        sentences = list(re.finditer(r"[^。！？!?；;\n]+[。！？!?；;]?", window.text))
        selected = []
        intervals = []
        previous_anchor_index = -10
        previous_sentence_end = 0
        for index, match in enumerate(sentences):
            raw = match.group()
            gap = window.text[previous_sentence_end : match.start()]
            previous_sentence_end = match.end()
            sentence = re.split(r"输出结果如下\s*[:：]", raw, maxsplit=1)[0].strip()
            if index == 0 and not window.starts_complete:
                continue
            if index == len(sentences) - 1 and not window.ends_complete:
                continue
            anchored = bool(pattern.search(sentence))
            # Only explicit anaphora/conditions extend an anchor, within two
            # sentences. Adjacency by itself never grants support.
            continuation = index - previous_anchor_index <= 2 and bool(
                re.match(r"(?:该|它|其|这|因此|其中|当|如果|通常|在实际)", sentence)
            )
            if re.search(r"(?:^|\s)\d+(?:\.\d+){1,3}\s", raw) or re.search(r"\n\s*\n", gap):
                previous_anchor_index = -10
                continuation = False
            if not (anchored or continuation):
                previous_anchor_index = -10
            if anchored and diagnostics is not None:
                diagnostics.candidate_sentences += 1
            normalized = _normalized(sentence)
            if not (anchored or continuation) or not sentence.endswith(tuple("。！？!?；;.")) or len(sentence) > 1200:
                continue
            if not _has_balanced_delimiters(sentence):
                continue
            formulas, quality = analyze_formula_quality(sentence)
            if quality is FormulaQuality.MALFORMED:
                continue
            duplicate = any(
                normalized in old
                or old in normalized
                or SequenceMatcher(None, normalized, old, autojunk=False).ratio() >= 0.88
                for old in seen
            )
            if duplicate and not formulas:
                continue
            cost = len(sentence) + bool(selected)
            if cost > remaining:
                continue
            if anchored:
                previous_anchor_index = index
            selected.append(sentence)
            first = match.start() + len(raw) - len(raw.lstrip())
            intervals.extend(window.intervals(first, first + len(sentence)))
            seen.append(normalized)
            remaining -= cost
            if diagnostics is not None:
                diagnostics.accepted_sentences += 1
        if not selected:
            continue
        selected_text = "\n".join(selected)
        formulas, quality = analyze_formula_quality(selected_text)
        if quality is FormulaQuality.MALFORMED:
            continue
        source, page = _source_metadata(document.metadata)
        spans.append(
            AssessmentEvidenceSpan(
                id=f"S{len(spans) + 1}",
                text=selected_text,
                source=source,
                page=(
                    next(
                        (original.book_page for original in window.pages if original.page == intervals[0].source_page),
                        None,
                    )
                    if intervals
                    else page
                ),
                completeness=EvidenceCompleteness.COMPLETE,
                formulas=formulas,
                formula_quality=quality,
                intervals=tuple(intervals),
                component_ids=tuple(sorted(covered_components(selected_text, target))),
            )
        )
        if len(spans) >= max_sources:
            break
    spans = _remove_formula_conflicts(spans)
    if diagnostics is not None:
        diagnostics.accepted_spans = len(spans)
    return spans if spans and has_target_coverage([span.text for span in spans], target) else []


def select_evidence(
    documents: Sequence[EvidenceDocument],
    target: AssessmentTarget,
    *,
    max_sources: int,
    max_chars: int,
    question_count: int,
    evidence_window_reader: EvidenceWindowReader | None = None,
    diagnostics: EvidenceSelectionDiagnostics | None = None,
) -> list[EvidenceSource]:
    """Return public sources derived only from complete typed spans."""
    spans = select_evidence_spans(
        documents,
        target,
        max_sources=max_sources,
        max_chars=max_chars,
        question_count=question_count,
        evidence_window_reader=evidence_window_reader,
        diagnostics=diagnostics,
    )
    return [
        EvidenceSource(
            id=span.id,
            text=span.text,
            source=span.source,
            page=span.page,
            intervals=span.intervals,
            component_ids=span.component_ids,
        )
        for span in spans
    ]
