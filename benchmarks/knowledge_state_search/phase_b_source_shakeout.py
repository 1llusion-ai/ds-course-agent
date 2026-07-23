"""Record and validate the Phase B dev source-discovery shakeout."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from benchmarks.knowledge_state_search.evidence import SnapshotSource

DEFAULT_OUTPUT = Path("var/artifacts/knowledge_state_search/phase_b_collection")
DEFAULT_CAPTURED_AT = "2026-07-22T19:35:00+08:00"
_PRIOR_SOURCE_FILES = (
    Path("benchmarks/data/knowledge_state_search_confirmatory_v3_pilot/sources.jsonl"),
    Path("benchmarks/data/knowledge_state_search_snapshot_v1/sources.jsonl"),
    Path("benchmarks/data/knowledge_state_search_snapshot_v2/sources.jsonl"),
)
_TRACKING_PARAMETERS = frozenset(
    {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "utm_campaign", "utm_medium", "utm_source"}
)


@dataclass(frozen=True)
class SourceCandidate:
    """One source candidate before full verbatim capture and annotation."""

    task_id: str
    source_id: str
    title: str
    url: str
    provider: str
    capture_locator: str
    discovery_query: str
    discovery_preview: str
    candidate_role: str
    candidate_targets: tuple[str, ...]

    def to_record(self) -> dict[str, object]:
        """Serialize the candidate without pretending the preview is evidence."""

        return {
            "task_id": self.task_id,
            "source_id": self.source_id,
            "title": self.title,
            "url": self.url,
            "provider": self.provider,
            "capture_locator": self.capture_locator,
            "discovery_query": self.discovery_query,
            "discovery_preview": self.discovery_preview,
            "preview_word_count": len(self.discovery_preview.split()),
            "candidate_role": self.candidate_role,
            "candidate_targets": list(self.candidate_targets),
            "capture_status": "metadata_only_needs_verbatim_capture",
            "usable_as_final_evidence": False,
        }


def build_dev_source_candidates() -> tuple[SourceCandidate, ...]:
    """Return the nine-source dev shakeout candidate set."""

    return (
        SourceCandidate(
            "pb_t01_cv_variance",
            "pb_t01_s01",
            "Cross-validation: evaluating estimator performance",
            "https://scikit-learn.org/stable/modules/cross_validation.html",
            "scikit-learn.org",
            "section 3.1, cross-validation",
            "k-fold cross-validation average fold scores stability",
            "In the basic approach, called k-fold CV, the training set is split into k smaller sets.",
            "support_candidate",
            ("pb_t01_c01", "pb_t01_c02", "pb_t01_c03", "pb_t01_c04"),
        ),
        SourceCandidate(
            "pb_t01_cv_variance",
            "pb_t01_s02",
            "Cross-validation and repeated data splitting",
            "https://arxiv.org/abs/2104.00673",
            "arxiv.org",
            "abstract",
            "each observation used for validation once k-fold",
            "Ideally, one would like to think that cross-validation estimates the prediction error for the model at hand.",
            "support_candidate",
            ("pb_t01_c01", "pb_t01_c02"),
        ),
        SourceCandidate(
            "pb_t01_cv_variance",
            "pb_t01_s03",
            "Pipeline",
            "https://scikit-learn.org/stable/modules/generated/sklearn.pipeline.Pipeline.html",
            "scikit-learn.org",
            "purpose of the pipeline",
            "cross-validation preprocessing fitted inside training folds",
            "The purpose of the pipeline is to assemble several steps that can be cross-validated together.",
            "support_candidate",
            ("pb_t01_c05",),
        ),
        SourceCandidate(
            "pb_t05_p_value_meaning",
            "pb_t05_s01",
            "ASA Statement on Statistical Significance and P-Values",
            "https://www.amstat.org/asa/files/pdfs/P-ValueStatement.pdf",
            "amstat.org",
            "statement definition and recommendations",
            "p-value is not probability null hypothesis true",
            "P-values do not measure the probability that the studied hypothesis is true.",
            "support_candidate",
            ("pb_t05_c01", "pb_t05_c02", "pb_t05_c03"),
        ),
        SourceCandidate(
            "pb_t05_p_value_meaning",
            "pb_t05_s02",
            "Critical values and p values",
            "https://www.itl.nist.gov/div898/handbook/prc/section1/prc131.htm",
            "itl.nist.gov",
            "section 7.1.3.1, p-value paragraphs",
            "NIST p-value test statistic null hypothesis significance level",
            "The p-value is the probability of the test statistic being at least as extreme as the one observed.",
            "partial_candidate",
            ("pb_t05_c01", "pb_t05_c03"),
        ),
        SourceCandidate(
            "pb_t05_p_value_meaning",
            "pb_t05_s03",
            "P-value",
            "https://en.wikipedia.org/wiki/P-value",
            "wikipedia.org",
            "definition section",
            "p-value definition probability observed or more extreme result",
            "A p-value does not measure the size of an effect or the importance of a result.",
            "topical_candidate",
            ("pb_t05_c01", "pb_t05_c02"),
        ),
        SourceCandidate(
            "pb_t09_skewed_summary",
            "pb_t09_s01",
            "2.3 Measures of the Location of the Data",
            "https://openstax.org/books/introductory-statistics-2e/pages/2-3-measures-of-the-location-of-the-data",
            "openstax.org",
            "quartiles and interquartile range",
            "median mean skewed distribution outliers",
            "The interquartile range is a number that indicates the spread of the middle half or the middle 50% of the data.",
            "support_candidate",
            ("pb_t09_c02", "pb_t09_c03", "pb_t09_c04", "pb_t09_c05"),
        ),
        SourceCandidate(
            "pb_t09_skewed_summary",
            "pb_t09_s02",
            "Box Plot",
            "https://www.itl.nist.gov/div898/software/dataplot/refman2/auxillar/iqrange.htm",
            "itl.nist.gov",
            "interquartile range definition",
            "interquartile range middle half of data box plot",
            "The interquartile range is less effected by extremes than the standard deviation.",
            "support_candidate",
            ("pb_t09_c04", "pb_t09_c05"),
        ),
        SourceCandidate(
            "pb_t09_skewed_summary",
            "pb_t09_s03",
            "Five Number Summary",
            "https://online.stat.psu.edu/stat200/lesson/2/2.2/2.2.10",
            "online.stat.psu.edu",
            "section 2.2.10",
            "mean median interquartile range skewed data",
            "The interquartile range is often preferred because it is resistant to outliers.",
            "partial_candidate",
            ("pb_t09_c02", "pb_t09_c04"),
        ),
    )


def write_dev_source_shakeout(
    output_directory: str | Path = DEFAULT_OUTPUT,
    *,
    captured_at: str = DEFAULT_CAPTURED_AT,
) -> dict[str, object]:
    """Write candidate metadata, deduplication results, and a status report."""

    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    candidates = build_dev_source_candidates()
    prior_urls = _load_prior_urls()
    normalized_urls = [normalize_url(candidate.url) for candidate in candidates]
    duplicate_current = sorted(url for url in set(normalized_urls) if normalized_urls.count(url) > 1)
    duplicate_prior = sorted(url for url in normalized_urls if url in prior_urls)
    records = [
        {
            **candidate.to_record(),
            "captured_at": captured_at,
            "preview_sha256": _sha256(candidate.discovery_preview),
        }
        for candidate in candidates
    ]
    _write_jsonl(root / "source_capture_log.jsonl", records)
    (root / "verbatim_capture_queue.json").write_text(
        json.dumps(
            {
                "status": "pending_human_verbatim_capture",
                "required_word_range": [40, 160],
                "candidates": build_verbatim_capture_queue(candidates),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "url_dedup_report.json").write_text(
        json.dumps(
            {
                "status": "pass" if not duplicate_current and not duplicate_prior else "fail",
                "candidate_count": len(candidates),
                "duplicate_within_shakeout": duplicate_current,
                "duplicate_with_prior_snapshots": duplicate_prior,
                "normalization": "lowercase host, strip fragment, remove tracking query parameters",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report = {
        "status": "source_discovery_only",
        "captured_at": captured_at,
        "tasks": ["pb_t01_cv_variance", "pb_t05_p_value_meaning", "pb_t09_skewed_summary"],
        "candidate_count": len(candidates),
        "preview_complete_count": sum(bool(candidate.discovery_preview) for candidate in candidates),
        "pending_verbatim_capture_count": len(candidates),
        "candidates_per_task": {
            task_id: sum(candidate.task_id == task_id for candidate in candidates)
            for task_id in (
                "pb_t01_cv_variance",
                "pb_t05_p_value_meaning",
                "pb_t09_skewed_summary",
            )
        },
        "verbatim_capture_complete": False,
        "annotation_started": False,
        "method_runs_authorized": False,
        "copyright_safe_preview_limit_words": 25,
        "next_action": "capture_short_natural_excerpts_from_the_pages_and_record_section_locators",
        "capture_queue": str(root / "verbatim_capture_queue.json"),
    }
    (root / "source_shakeout_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def build_verbatim_capture_queue(
    candidates: tuple[SourceCandidate, ...],
) -> list[dict[str, object]]:
    """Build explicit human-capture work items without treating previews as evidence."""

    return [
        {
            "task_id": candidate.task_id,
            "source_id": candidate.source_id,
            "title": candidate.title,
            "url": candidate.url,
            "provider": candidate.provider,
            "capture_locator": candidate.capture_locator,
            "candidate_targets": list(candidate.candidate_targets),
            "status": "pending",
            "required_actions": [
                "open_canonical_page",
                "copy_one_contiguous_verbatim_excerpt",
                "record_page_or_section_locator",
                "verify_excerpt_against_page",
                "compute_snapshot_source_sha256",
            ],
            "acceptance": {
                "word_count_min": 40,
                "word_count_max": 160,
                "must_be_natural_source_text": True,
                "must_not_include_query_or_annotation_metadata": True,
            },
        }
        for candidate in candidates
    ]


def validate_verbatim_source_record(payload: dict[str, object]) -> SnapshotSource:
    """Validate one future final source row and reject previews as evidence."""

    if "discovery_preview" in payload or "candidate_targets" in payload:
        raise ValueError("final source records cannot contain discovery metadata")
    text = payload.get("text")
    if not isinstance(text, str) or not (40 <= len(text.split()) <= 160):
        raise ValueError("final source excerpt must contain 40-160 whitespace-delimited words")
    return SnapshotSource.from_dict(payload)


def normalize_url(url: str) -> str:
    """Normalize a public URL for cross-dataset exact-URL deduplication."""

    parts = urlsplit(url.strip())
    query = [
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in _TRACKING_PARAMETERS
    ]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))


def build_parser() -> argparse.ArgumentParser:
    """Build the source-shakeout CLI."""

    parser = argparse.ArgumentParser(description="Write the Phase B dev source-discovery shakeout.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--captured-at", default=DEFAULT_CAPTURED_AT)
    return parser


def main() -> int:
    """Run the source-shakeout writer."""

    args = build_parser().parse_args()
    report = write_dev_source_shakeout(args.output, captured_at=args.captured_at)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _load_prior_urls() -> set[str]:
    """Load normalized URLs from prior benchmark source pools."""

    urls: set[str] = set()
    for path in _PRIOR_SOURCE_FILES:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                urls.add(normalize_url(str(json.loads(line)["url"])))
    return urls


def _sha256(value: str) -> str:
    """Return a stable digest for a preview field."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    """Write deterministic UTF-8 JSONL."""

    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
