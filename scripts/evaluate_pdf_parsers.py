"""Compare PDF parser outputs without modifying the active knowledge base."""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from scripts._path import ensure_src_path

ensure_src_path()

from ds_course_agent.kb.chunker import CourseChunkerV2
from ds_course_agent.kb.cleaner import clean_document
from ds_course_agent.kb.parser import PageResult, ParserMode, PDFParseResult, parse_pdf_file
from ds_course_agent.kb.parser_quality import measure_parser_quality
from ds_course_agent.kb.toc_parser import get_toc_parser

SUPPORTED_MODES: tuple[ParserMode, ...] = ("pypdf-plain", "pypdf-layout", "marker", "datalab")


def _load_parse_cache(path: Path) -> PDFParseResult:
    with path.open("rb") as file:
        result = pickle.load(file)
    if not isinstance(result, PDFParseResult):
        raise TypeError(f"Unsupported parse cache object: {type(result).__name__}")
    return result


def _expected_titles() -> list[str]:
    return [section.name for section in get_toc_parser().all_sections if section.name]


def _evaluate_result(
    result: PDFParseResult,
    source: Path,
    titles: list[str],
    page_offset: int,
) -> dict[str, object]:
    raw_metrics = measure_parser_quality(result, titles)
    cleaned = clean_document(
        [(page.page_num, page.text) for page in result.pages if page.text],
        result.file_name,
    )
    cleaned_pages = [
        PageResult(
            page_num=page.page_num,
            text=page.cleaned_text,
            parser=f"{result.parser_mode}-cleaned",
            char_count=len(page.cleaned_text),
            original_char_count=len(page.original_text),
        )
        for page in cleaned.pages
    ]
    cleaned_result = PDFParseResult(
        file_name=result.file_name,
        total_pages=result.total_pages,
        pages=cleaned_pages,
        success_rate=result.success_rate,
        full_text=cleaned.full_text,
        parser_mode=f"{result.parser_mode}-cleaned",
    )
    cleaned_metrics = measure_parser_quality(cleaned_result, titles)

    chunk_result = CourseChunkerV2().chunk_document(
        [(page.page_num, page.cleaned_text) for page in cleaned.pages],
        result.file_name,
        parser_source=result.parser_mode,
        page_offset=page_offset,
        max_chunk_size=1500,
    )
    semantic_chunks = [chunk for chunk in chunk_result.chunks if chunk.metadata.chunk_type == "semantic"]

    return {
        "source": str(source),
        "raw": raw_metrics.to_dict(),
        "cleaned": {
            **cleaned_metrics.to_dict(),
            "chars_removed": cleaned.total_chars_removed,
        },
        "chunking": {
            "total_chunks": chunk_result.total_chunks,
            "semantic_chunks": chunk_result.semantic_chunks,
            "struct_chunks": chunk_result.struct_chunks,
            "shadow_chunks": chunk_result.shadow_chunks,
            "average_chunk_chars": chunk_result.avg_chunk_size,
            "max_semantic_chunk_chars": max((len(chunk.content) for chunk in semantic_chunks), default=0),
            "semantic_chunks_over_1500": sum(len(chunk.content) > 1500 for chunk in semantic_chunks),
        },
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument(
        "--mode",
        action="append",
        choices=SUPPORTED_MODES,
        dest="modes",
        help="Parser mode to evaluate; repeat to compare multiple modes",
    )
    parser.add_argument("--baseline-cache", type=Path, help="Existing PDFParseResult pickle to include")
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--page-offset", type=int, default=-8, help="Textbook page = PDF page + offset")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("var/artifacts/pdf_parser_quality.json"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run parser comparisons and write a JSON report under var/artifacts."""
    args = _parse_args(argv)
    if not args.pdf.is_file():
        raise SystemExit(f"PDF not found: {args.pdf}")

    titles = _expected_titles()
    reports: list[dict[str, object]] = []
    if args.baseline_cache:
        baseline = _load_parse_cache(args.baseline_cache)
        reports.append(_evaluate_result(baseline, args.baseline_cache, titles, args.page_offset))

    for mode in args.modes or ["pypdf-layout"]:
        result = parse_pdf_file(
            str(args.pdf),
            max_pages=args.max_pages,
            save_trace=False,
            parser_mode=mode,
        )
        reports.append(_evaluate_result(result, args.pdf, titles, args.page_offset))

    payload = {
        "schema": "pdf-parser-quality-v1",
        "generated_at": datetime.now().isoformat(),
        "pdf": str(args.pdf.resolve()),
        "results": reports,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
