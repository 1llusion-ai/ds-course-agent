"""Concept resolution and conservative evidence selection for question generation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Protocol

from ds_course_agent.assessment.formulas import analyze_formula_quality
from ds_course_agent.assessment.models import (
    AssessmentEvidenceSpan,
    EvidenceCompleteness,
    EvidenceSource,
    FormulaQuality,
    GenerateQuestionsRequest,
)
from ds_course_agent.shared.paths import PROJECT_ROOT


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


@dataclass(frozen=True)
class AssessmentTarget:
    """Canonical target and permitted lexical evidence anchors."""

    concept_id: str | None
    name: str
    aliases: tuple[str, ...]
    chapter: str = ""
    section: str = ""

    @property
    def query(self) -> str:
        """Expand with bounded aliases, never neighboring concepts."""
        normalized_name = _normalized(self.name)
        aliases = tuple(alias for alias in self.aliases if _normalized(alias) != normalized_name)
        return " ".join((self.name, *aliases[:3]))


def _normalized(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def resolve_target(request: GenerateQuestionsRequest, catalog_path: Path | None = None) -> AssessmentTarget:
    """Resolve exact catalog identities without model calls or fuzzy guessing."""
    path = catalog_path or PROJECT_ROOT / "data" / "knowledge_graph.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    for concept in catalog["concepts"]:
        if concept["canonical_id"] != request.target_kc_id:
            continue
        aliases = tuple(dict.fromkeys([concept["display_name"], *concept.get("aliases", [])]))
        return AssessmentTarget(
            concept["canonical_id"],
            concept["display_name"],
            aliases,
            concept.get("chapter", ""),
            concept.get("section", ""),
        )
    raise InvalidAssessmentTarget("unknown course concept")


def _anchor_pattern(target: AssessmentTarget) -> re.Pattern[str]:
    patterns = []
    acronyms = re.findall(r"[A-Za-z]{3,}", target.name)
    for alias in (*target.aliases, *acronyms):
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
    pairs = {"(": ")", "[": "]", "{": "}", "（": "）", "【": "】", "《": "》"}
    closers = set(pairs.values())
    stack: list[str] = []
    for character in text:
        if character in pairs:
            stack.append(pairs[character])
        elif character in closers:
            if not stack or stack.pop() != character:
                return False
    return not stack


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _assemble_document_span(
    document: EvidenceDocument,
    evidence_window_reader: EvidenceWindowReader | None,
) -> tuple[str, EvidenceCompleteness, bool, bool] | None:
    """Recover complete-page text from the production provenance contract."""
    metadata = document.metadata
    if metadata.get("metadata_schema_version") != "retrieval-provenance/1.0":
        if metadata.get("parser_source") == "marker_v2":
            return None
        return document.page_content, EvidenceCompleteness.COMPLETE, True, True

    if evidence_window_reader is None:
        return None

    required = (
        "source_id",
        "source_page",
        "source_char_start",
        "source_char_end",
        "source_page_sha256",
        "source_page_text",
    )
    if any(key not in metadata for key in required):
        return None
    try:
        page_text = str(metadata["source_page_text"])
        start = int(metadata["source_char_start"])
        end = int(metadata["source_char_end"])
    except (TypeError, ValueError):
        return None
    if not page_text or start < 0 or end <= start or end > len(page_text):
        return None
    if _sha256_text(page_text) != str(metadata["source_page_sha256"]):
        return None
    if _normalized(page_text[start:end]) != _normalized(document.page_content):
        selected_intervals = str(metadata.get("selected_source_intervals", ""))
        if not selected_intervals:
            return None
    pages = tuple(evidence_window_reader.read_evidence_window(document))
    if not pages:
        return None
    try:
        source_id = str(metadata["source_id"])
        source_page = int(metadata["source_page"])
        ordered = sorted(pages, key=lambda page: int(page.metadata["source_page"]))
    except (KeyError, TypeError, ValueError):
        return None
    if any(page.metadata.get("source_id") != source_id for page in ordered):
        return None
    page_numbers = [int(page.metadata["source_page"]) for page in ordered]
    if source_page not in page_numbers or any(
        right != left + 1 for left, right in zip(page_numbers, page_numbers[1:], strict=False)
    ):
        return None
    # The target page is normally internal to this three-page window. Dropping
    # only the outer sentences preserves cross-page continuations without
    # publishing an unbounded edge fragment.
    return "".join(page.page_content for page in ordered), EvidenceCompleteness.COMPLETE, False, False


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
) -> list[AssessmentEvidenceSpan]:
    """Select complete, non-conflicting target evidence spans."""
    pattern = _anchor_pattern(target)
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
            continue
        assembled = _assemble_document_span(document, evidence_window_reader)
        if assembled is None:
            continue
        text, completeness, starts_complete, ends_complete = assembled
        selected = []
        text = re.sub(r"(?=\d+(?:\.\d+){2,3}\s*[\u4e00-\u9fff])", "\n", text)
        sentences = re.split(r"(?<=[。！？!?；;])\s*|\n+", text)
        for sentence_index, sentence in enumerate(sentences):
            sentence = re.split(r"输出结果如下\s*[:：]", sentence, maxsplit=1)[0].strip()
            if sentence_index == 0 and not starts_complete:
                continue
            if sentence_index == len(sentences) - 1 and not ends_complete:
                continue
            has_terminal = bool(sentence) and sentence[-1] in "。！？!?；;."
            if not has_terminal and not (sentence_index == len(sentences) - 1 and ends_complete):
                continue
            normalized = _normalized(sentence)
            if len(normalized) < 24 or len(sentence) > 1200 or not pattern.search(sentence):
                continue
            if not _has_balanced_delimiters(sentence):
                continue
            sentence_formulas, sentence_formula_quality = analyze_formula_quality(sentence)
            if sentence_formula_quality is FormulaQuality.MALFORMED:
                continue
            is_duplicate = any(
                normalized in old
                or old in normalized
                or SequenceMatcher(None, normalized, old, autojunk=False).ratio() >= 0.88
                for old in seen
            )
            if is_duplicate and not sentence_formulas:
                continue
            cost = len(sentence) + bool(selected)
            if cost > remaining:
                continue
            selected.append(sentence)
            seen.append(normalized)
            remaining -= cost
        if not selected:
            continue
        selected_text = "\n".join(selected)
        formulas, formula_quality = analyze_formula_quality(selected_text)
        if formula_quality is FormulaQuality.MALFORMED:
            continue
        source, page = _source_metadata(document.metadata)
        spans.append(
            AssessmentEvidenceSpan(
                id=f"S{len(spans) + 1}",
                text=selected_text,
                source=source,
                page=page,
                completeness=completeness,
                formulas=formulas,
                formula_quality=formula_quality,
            )
        )
        if len(spans) >= max_sources:
            break
    spans = _remove_formula_conflicts(spans)
    return spans if spans and len(seen) >= question_count else []


def select_evidence(
    documents: Sequence[EvidenceDocument],
    target: AssessmentTarget,
    *,
    max_sources: int,
    max_chars: int,
    question_count: int,
    evidence_window_reader: EvidenceWindowReader | None = None,
) -> list[EvidenceSource]:
    """Return public sources derived only from complete typed spans."""
    spans = select_evidence_spans(
        documents,
        target,
        max_sources=max_sources,
        max_chars=max_chars,
        question_count=question_count,
        evidence_window_reader=evidence_window_reader,
    )
    return [EvidenceSource(id=span.id, text=span.text, source=span.source, page=span.page) for span in spans]
