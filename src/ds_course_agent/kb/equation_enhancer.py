"""Merge selectively OCRed Marker equations into an existing parse result."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from ds_course_agent.kb.parser import PageResult, ParsedBlock, PDFParseResult


@dataclass(frozen=True)
class EquationEnhancementResult:
    """Result and review counts for an equation-only OCR merge."""

    parse_result: PDFParseResult
    source_equations: int
    ocr_equations: int
    structurally_valid_ocr_equations: int
    replaced_equations: int
    approved_ocr_replacements: int
    manual_replacements: int
    removed_equations: int
    unreviewed_equations: int
    missing_equations: int
    rejected_equations: int


@dataclass(frozen=True)
class EquationReview:
    """Explicit human decisions for OCR equation candidates."""

    approved_ocr_block_ids: frozenset[str]
    text_overrides: Mapping[str, str]
    removed_block_ids: frozenset[str]


@dataclass
class _MergeCounts:
    approved_ocr_replacements: int = 0
    manual_replacements: int = 0
    removed_equations: int = 0
    unreviewed_equations: int = 0
    missing_equations: int = 0
    rejected_equations: int = 0


def _has_balanced_braces(value: str) -> bool:
    depth = 0
    for index, character in enumerate(value):
        escaped = index > 0 and value[index - 1] == "\\"
        if escaped:
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _is_valid_display_math(value: str) -> bool:
    stripped = value.strip()
    if "\ufffd" in stripped or stripped.count("$$") != 2:
        return False
    if not stripped.startswith("$$") or not stripped.endswith("$$"):
        return False
    body = stripped[2:-2].strip()
    if not body or "$" in body:
        return False
    return _has_balanced_braces(body)


def _replace_page_equations(
    page: PageResult,
    ocr_blocks: dict[str, ParsedBlock],
    review: EquationReview,
) -> tuple[PageResult, _MergeCounts]:
    blocks: list[ParsedBlock] = []
    counts = _MergeCounts()

    for block in page.blocks:
        if block.block_type != "Equation":
            blocks.append(block)
            continue

        block_id = block.block_id
        if block_id in review.removed_block_ids:
            counts.removed_equations += 1
            continue

        override = review.text_overrides.get(block_id)
        if override is not None:
            counts.manual_replacements += 1
            blocks.append(replace(block, text=override.strip()))
            continue

        if block_id not in review.approved_ocr_block_ids:
            counts.unreviewed_equations += 1
            blocks.append(block)
            continue

        candidate = ocr_blocks.get(block_id)
        if candidate is None:
            counts.missing_equations += 1
            blocks.append(block)
        elif not _is_valid_display_math(candidate.text):
            counts.rejected_equations += 1
            blocks.append(block)
        else:
            counts.approved_ocr_replacements += 1
            blocks.append(replace(block, text=candidate.text.strip()))

    text = "\n".join(block.text for block in blocks)
    return replace(page, text=text, char_count=len(text), blocks=blocks), counts


def _validate_review(review: EquationReview, source_block_ids: set[str]) -> None:
    approved = set(review.approved_ocr_block_ids)
    overridden = set(review.text_overrides)
    removed = set(review.removed_block_ids)
    overlap = (approved & overridden) | (approved & removed) | (overridden & removed)
    if overlap:
        raise ValueError(f"Equation review actions overlap for block IDs: {sorted(overlap)}")

    unknown = (approved | overridden | removed) - source_block_ids
    if unknown:
        raise ValueError(f"Equation review contains unknown block IDs: {sorted(unknown)}")

    invalid_overrides = [
        block_id for block_id, text in review.text_overrides.items() if not _is_valid_display_math(text)
    ]
    if invalid_overrides:
        raise ValueError(f"Equation review contains invalid display-math overrides: {sorted(invalid_overrides)}")


def merge_marker_equation_ocr(
    baseline: PDFParseResult,
    ocr_result: PDFParseResult,
    review: EquationReview,
) -> EquationEnhancementResult:
    """Apply reviewed exact-ID OCR candidates and manual formula corrections."""
    ocr_blocks = {
        block.block_id: block
        for page in ocr_result.pages
        for block in page.blocks
        if block.block_type == "Equation" and block.block_id
    }
    source_block_ids = {
        block.block_id
        for page in baseline.pages
        for block in page.blocks
        if block.block_type == "Equation" and block.block_id
    }
    source_equations = sum(block.block_type == "Equation" for page in baseline.pages for block in page.blocks)
    _validate_review(review, source_block_ids)

    totals = _MergeCounts()
    pages: list[PageResult] = []

    for page in baseline.pages:
        updated_page, counts = _replace_page_equations(page, ocr_blocks, review)
        pages.append(updated_page)
        totals.approved_ocr_replacements += counts.approved_ocr_replacements
        totals.manual_replacements += counts.manual_replacements
        totals.removed_equations += counts.removed_equations
        totals.unreviewed_equations += counts.unreviewed_equations
        totals.missing_equations += counts.missing_equations
        totals.rejected_equations += counts.rejected_equations

    full_text = "\n\n".join(f"[第 {page.page_num} 页]\n{page.text}" for page in pages if page.text)
    parse_result = replace(baseline, pages=pages, full_text=full_text)
    return EquationEnhancementResult(
        parse_result=parse_result,
        source_equations=source_equations,
        ocr_equations=len(ocr_blocks),
        structurally_valid_ocr_equations=sum(_is_valid_display_math(block.text) for block in ocr_blocks.values()),
        replaced_equations=totals.approved_ocr_replacements + totals.manual_replacements,
        approved_ocr_replacements=totals.approved_ocr_replacements,
        manual_replacements=totals.manual_replacements,
        removed_equations=totals.removed_equations,
        unreviewed_equations=totals.unreviewed_equations,
        missing_equations=totals.missing_equations,
        rejected_equations=totals.rejected_equations,
    )
