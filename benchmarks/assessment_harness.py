"""Replay frozen evidence or explicitly run the same five live generation requests."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace

from ds_course_agent.assessment.evidence import resolve_target, select_evidence
from ds_course_agent.assessment.generator import AssessmentGenerationError
from ds_course_agent.assessment.models import GenerateQuestionsRequest
from ds_course_agent.assessment.service import AssessmentService, NoAssessmentEvidence
from ds_course_agent.shared.paths import PROJECT_ROOT


class _FrozenEvidenceWindowReader:
    """Replay a complete three-page window for one frozen production document."""

    def read_evidence_window(self, document):
        metadata = document.metadata
        source_id = metadata["source_id"]
        source_page = metadata["source_page"]
        return (
            SimpleNamespace(
                page_content="上一页背景结束。\n",
                metadata={"source_id": source_id, "source_page": source_page - 1},
            ),
            SimpleNamespace(
                page_content=document.page_content,
                metadata={"source_id": source_id, "source_page": source_page},
            ),
            SimpleNamespace(
                page_content="\n下一页背景结束。",
                metadata={"source_id": source_id, "source_page": source_page + 1},
            ),
        )


def _frozen_documents(case: dict) -> list[SimpleNamespace]:
    """Project frozen retrieval captures into the current provenance contract."""

    documents = []
    for index, raw in enumerate(case["documents"]):
        text = raw["text"].rstrip()
        if text and text[-1] not in "。！？!?；;.":
            text += "。"
        metadata = dict(raw["metadata"])
        source_page = int(metadata.get("source_page") or metadata.get("page") or index + 1)
        metadata.update(
            metadata_schema_version="retrieval-provenance/1.0",
            source_id=f"assessment-harness:{case['concept_id']}:{index}",
            source_page=source_page,
            source_char_start=0,
            source_char_end=len(text),
            source_page_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            source_page_text=text,
        )
        documents.append(SimpleNamespace(page_content=text, metadata=metadata))
    return documents


def main() -> None:
    """Default to offline regression, with paid generation requiring --live."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--concept-id", help="Investigate one fixed case without resampling concepts")
    parser.add_argument(
        "--output", type=Path, default=PROJECT_ROOT / "var/artifacts/assessment/evidence_regression_report.json"
    )
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    fixture = json.loads(
        (PROJECT_ROOT / "benchmarks/data/assessment_evidence_regression.json").read_text(encoding="utf-8")
    )
    cases = [c for c in fixture["cases"] if args.concept_id in (None, c["concept_id"])]
    if not cases:
        parser.error("concept-id must name one of the five frozen cases")
    rows = []
    service = AssessmentService() if args.live else None
    started = time.perf_counter()
    for case in cases:
        request = GenerateQuestionsRequest(target_kc_id=case["concept_id"], count=2)
        row = {"concept_id": case["concept_id"], "topic": case["topic"]}
        batch_started = time.perf_counter()
        if service is not None:
            try:
                row["quiz"] = service.generate(request).model_dump(mode="json")
                row["status"] = "generated"
            except NoAssessmentEvidence:
                row["status"] = "insufficient_evidence"
            except AssessmentGenerationError as exc:
                row.update(status="error", error_type=type(exc).__name__, reason=str(exc))
            except Exception as exc:
                row.update(status="error", error_type=type(exc).__name__)
        else:
            documents = _frozen_documents(case)
            sources = select_evidence(
                documents,
                resolve_target(request),
                max_sources=3,
                max_chars=6000,
                question_count=2,
                evidence_window_reader=_FrozenEvidenceWindowReader(),
            )
            text = "\n".join(s.text for s in sources)
            row.update(
                status="passed"
                if bool(sources) == case["expect_sufficient"] and all(t not in text for t in case["excluded_text"])
                else "failed",
                sources=[s.model_dump(mode="json") for s in sources],
            )
        row["seconds"] = round(time.perf_counter() - batch_started, 3)
        rows.append(row)
        print(
            json.dumps({k: v for k, v in row.items() if k not in {"sources", "quiz"}}, ensure_ascii=False), flush=True
        )
    report = {
        "mode": "live" if args.live else "frozen_evidence",
        "seed": fixture["seed"],
        "total_seconds": round(time.perf_counter() - started, 3),
        "cases": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if any(r["status"] in {"failed", "error"} for r in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
