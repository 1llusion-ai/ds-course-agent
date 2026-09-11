"""PDF 解析结果的确定性质量指标。"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from ds_course_agent.kb.parser import PDFParseResult

_SPACED_ALPHANUMERIC_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z0-9][ \t]+){2,}[A-Za-z0-9](?![A-Za-z0-9])")
_PROSE_LETTER_SPACING_PATTERN = re.compile(r"(?<![A-Za-z])(?:[A-Za-z][ \t]+){3,}[A-Za-z](?![A-Za-z])")
_MATH_DELIMITED_PATTERN = re.compile(r"\$\$.*?\$\$|(?<!\$)\$(?!\$).*?(?<!\$)\$(?!\$)", re.DOTALL)
_VISUAL_DESCRIPTION_PATTERNS = (
    re.compile(r"\bLogo of\b", re.IGNORECASE),
    re.compile(r"\bDecorative arrow(?: graphic)?\b", re.IGNORECASE),
    re.compile(r"\b(?:Screenshot|Illustration|Photo|Image) of\b", re.IGNORECASE),
    re.compile(r"\bQR code linking to\b", re.IGNORECASE),
    re.compile(r"\bFigure \d+(?:[-.]\d+)*:\s", re.IGNORECASE),
    re.compile(r"\bThe (?:diagram|figure|image|screenshot) (?:shows|illustrates|depicts|features)\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class ParserQualityMetrics:
    """用于比较解析器输出的无模型质量指标。"""

    parser_mode: str
    total_pages: int
    nonempty_pages: int
    page_coverage: float
    text_chars: int
    duplicate_candidate_chars: int
    duplicate_candidate_ratio: float
    private_use_chars: int
    replacement_chars: int
    spaced_alphanumeric_sequences: int
    text_spaced_alphanumeric_sequences: int
    equation_spaced_alphanumeric_sequences: int
    table_spaced_alphanumeric_sequences: int
    prose_letter_spacing_candidates: int
    visual_description_candidates: int
    expected_titles: int
    matched_titles: int
    title_recall: float

    def to_dict(self) -> dict[str, int | float | str]:
        """转换为可序列化字典。"""
        return asdict(self)


def _normalize_for_comparison(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _duplicate_candidate_chars(text: str, min_segment_chars: int = 60) -> int:
    """统计重复行及被更长行包含的文本，作为解析重复的启发式信号。"""
    segments = {
        normalized
        for line in text.splitlines()
        if len(normalized := _normalize_for_comparison(line)) >= min_segment_chars
    }
    accepted: list[str] = []
    duplicate_chars = 0
    for segment in sorted(segments, key=len, reverse=True):
        if any(segment in longer for longer in accepted):
            duplicate_chars += len(segment)
        else:
            accepted.append(segment)

    normalized_lines = Counter(
        normalized
        for line in text.splitlines()
        if len(normalized := _normalize_for_comparison(line)) >= min_segment_chars
    )
    duplicate_chars += sum((count - 1) * len(segment) for segment, count in normalized_lines.items() if count > 1)
    return duplicate_chars


def _is_private_use(character: str) -> bool:
    codepoint = ord(character)
    return 0xE000 <= codepoint <= 0xF8FF or 0xF0000 <= codepoint <= 0xFFFFD or 0x100000 <= codepoint <= 0x10FFFD


def _spaced_sequence_counts(parse_result: PDFParseResult) -> tuple[int, int, int, int]:
    """区分正文、公式和表格中的空格分隔字母数字序列。"""
    text_count = 0
    equation_count = 0
    table_count = 0
    prose_letter_spacing_count = 0

    for page in parse_result.pages:
        segments = ((block.block_type, block.text) for block in page.blocks) if page.blocks else (("Text", page.text),)
        for block_type, text in segments:
            plain_text = _MATH_DELIMITED_PATTERN.sub("", text)
            count = len(_SPACED_ALPHANUMERIC_PATTERN.findall(plain_text))
            if block_type == "Equation":
                equation_count += count
            elif block_type == "Table":
                table_count += count
            else:
                text_count += count
                prose_letter_spacing_count += len(_PROSE_LETTER_SPACING_PATTERN.findall(plain_text))

    return text_count, equation_count, table_count, prose_letter_spacing_count


def measure_parser_quality(
    parse_result: PDFParseResult,
    expected_titles: Iterable[str] = (),
) -> ParserQualityMetrics:
    """计算页覆盖、重复文本、异常字形、线性化序列和标题召回。"""
    nonempty_pages = sum(bool(page.text.strip()) for page in parse_result.pages)
    text_chars = sum(len(page.text) for page in parse_result.pages)
    duplicate_chars = sum(_duplicate_candidate_chars(page.text) for page in parse_result.pages)
    full_text_normalized = _normalize_for_comparison(parse_result.full_text)

    normalized_titles = {normalized for title in expected_titles if (normalized := _normalize_for_comparison(title))}
    matched_titles = sum(title in full_text_normalized for title in normalized_titles)
    text_spaced, equation_spaced, table_spaced, prose_letter_spacing = _spaced_sequence_counts(parse_result)

    return ParserQualityMetrics(
        parser_mode=parse_result.parser_mode,
        total_pages=parse_result.total_pages,
        nonempty_pages=nonempty_pages,
        page_coverage=nonempty_pages / parse_result.total_pages if parse_result.total_pages else 0.0,
        text_chars=text_chars,
        duplicate_candidate_chars=duplicate_chars,
        duplicate_candidate_ratio=duplicate_chars / text_chars if text_chars else 0.0,
        private_use_chars=sum(_is_private_use(character) for page in parse_result.pages for character in page.text),
        replacement_chars=sum(page.text.count("\ufffd") for page in parse_result.pages),
        spaced_alphanumeric_sequences=text_spaced + equation_spaced + table_spaced,
        text_spaced_alphanumeric_sequences=text_spaced,
        equation_spaced_alphanumeric_sequences=equation_spaced,
        table_spaced_alphanumeric_sequences=table_spaced,
        prose_letter_spacing_candidates=prose_letter_spacing,
        visual_description_candidates=sum(
            len(pattern.findall(page.text)) for page in parse_result.pages for pattern in _VISUAL_DESCRIPTION_PATTERNS
        ),
        expected_titles=len(normalized_titles),
        matched_titles=matched_titles,
        title_recall=matched_titles / len(normalized_titles) if normalized_titles else 0.0,
    )
