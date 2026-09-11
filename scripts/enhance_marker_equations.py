"""Enhance Marker equation blocks without modifying the active knowledge base."""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from scripts._path import ensure_src_path

ensure_src_path()

from ds_course_agent.kb.equation_enhancer import EquationReview, merge_marker_equation_ocr
from ds_course_agent.kb.parser import PDFParseResult, _build_result, _extract_pages_from_json
from ds_course_agent.kb.parser_quality import measure_parser_quality


def _load_parse_cache(path: Path) -> PDFParseResult:
    with path.open("rb") as file:
        result = pickle.load(file)
    if not isinstance(result, PDFParseResult):
        raise TypeError(f"Unsupported parse cache object: {type(result).__name__}")
    return result


def _load_ocr_json(path: Path) -> PDFParseResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    pages = _extract_pages_from_json(data, parser="marker-equation-ocr")
    return _build_result(path.name, pages, "marker-equation-ocr")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_review(path: Path, pdf: Path, baseline_cache: Path, ocr_json: Path) -> EquationReview:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "marker-equation-review-v1":
        raise ValueError("Unsupported equation review schema")

    expected_hashes = {
        "pdf_sha256": _sha256(pdf),
        "baseline_cache_sha256": _sha256(baseline_cache),
        "ocr_json_sha256": _sha256(ocr_json),
    }
    mismatches = [key for key, expected in expected_hashes.items() if data.get(key) != expected]
    if mismatches:
        raise ValueError(f"Equation review source hash mismatch: {', '.join(mismatches)}")

    return EquationReview(
        approved_ocr_block_ids=frozenset(data.get("approved_ocr_block_ids") or []),
        text_overrides=data.get("text_overrides") or {},
        removed_block_ids=frozenset(data.get("removed_block_ids") or []),
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("baseline_cache", type=Path)
    parser.add_argument("--ocr-json", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--output-cache", type=Path)
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("var/artifacts/marker_equation_enhancement_report.json"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run equation-only OCR merge and save a separate parse cache."""
    args = _parse_args(argv)
    if not args.pdf.is_file():
        raise SystemExit(f"PDF not found: {args.pdf}")
    if not args.baseline_cache.is_file():
        raise SystemExit(f"Baseline cache not found: {args.baseline_cache}")
    if not args.ocr_json.is_file():
        raise SystemExit(f"OCR JSON not found: {args.ocr_json}")
    if not args.review.is_file():
        raise SystemExit(f"Review manifest not found: {args.review}")

    output_cache = args.output_cache or args.baseline_cache.with_name(f"{args.baseline_cache.stem}_equation-ocr.pkl")
    if output_cache.exists():
        raise SystemExit(f"Output cache already exists: {output_cache}")

    baseline = _load_parse_cache(args.baseline_cache)
    ocr_result = _load_ocr_json(args.ocr_json)
    review = _load_review(args.review, args.pdf, args.baseline_cache, args.ocr_json)
    enhancement = merge_marker_equation_ocr(baseline, ocr_result, review)
    if enhancement.replaced_equations == 0:
        raise SystemExit("Equation OCR produced no valid exact-ID replacements")
    if enhancement.unreviewed_equations or enhancement.missing_equations or enhancement.rejected_equations:
        raise SystemExit(
            "Equation review is incomplete or invalid: "
            f"unreviewed={enhancement.unreviewed_equations}, "
            f"missing={enhancement.missing_equations}, rejected={enhancement.rejected_equations}"
        )

    output_cache.parent.mkdir(parents=True, exist_ok=True)
    with output_cache.open("wb") as file:
        pickle.dump(enhancement.parse_result, file)

    payload = {
        "schema": "marker-equation-enhancement-v1",
        "generated_at": datetime.now().isoformat(),
        "pdf": str(args.pdf.resolve()),
        "baseline_cache": str(args.baseline_cache.resolve()),
        "ocr_json": str(args.ocr_json.resolve()),
        "review": str(args.review.resolve()),
        "output_cache": str(output_cache.resolve()),
        "enhancement": {key: value for key, value in asdict(enhancement).items() if key != "parse_result"},
        "quality": measure_parser_quality(enhancement.parse_result).to_dict(),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
