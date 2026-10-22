"""Validate cognitive-task fixtures, or explicitly calibrate the real blind critic.

Offline: PYTHONPATH=src .venv/bin/python benchmarks/assessment_task_harness.py
Live: add --provider --confirm [--course digital-literacy] [--limit 2].
Only live runs write reports. These fixtures calibrate cognitive classification,
not textbook grounding, generation success, or learner mastery.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ds_course_agent.assessment.models import CognitiveOperation, Difficulty, GeneratedQuestion  # noqa: E402

DATASET_PATH = Path(__file__).parent / "data/assessment_cognitive_tasks.json"
REPORT_DIRECTORY = PROJECT_ROOT / "var/artifacts/assessment-robustness-20261022"
COURSE_TARGETS = {"digital-literacy": "dl_5_2_1_1", "data-science-intro": "pca"}


class CognitiveCase(BaseModel):
    """Fixed annotation kept separate from the candidate sent to the reviewer."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1)
    course_id: Literal["digital-literacy", "data-science-intro"]
    target_kc_id: str = Field(min_length=1)
    case_kind: Literal["positive", "long_context_recall"]
    expected_operation: CognitiveOperation
    misleading_operations: tuple[CognitiveOperation, ...]
    annotation_rationale: str = Field(min_length=20)
    question: GeneratedQuestion

    @model_validator(mode="after")
    def validate_annotation(self) -> CognitiveCase:
        if self.target_kc_id != COURSE_TARGETS[self.course_id]:
            raise ValueError("case target must belong to its declared course fixture")
        if self.question.difficulty is not Difficulty.BASIC:
            raise ValueError("all fixtures use the same schema-only difficulty, independent of the gold label")
        if self.question.source_ids != ["fixture-not-textbook-evidence"]:
            raise ValueError("synthetic fixture sources must not masquerade as verified textbook evidence")
        if self.case_kind == "long_context_recall":
            if self.expected_operation is not CognitiveOperation.RECALL or len(self.question.stem) < 100:
                raise ValueError("long-context negatives must be annotated recall with at least 100 stem characters")
            if not self.misleading_operations or CognitiveOperation.RECALL in self.misleading_operations:
                raise ValueError(
                    "long-context negatives must identify the higher operations they could be mistaken for"
                )
        elif self.misleading_operations:
            raise ValueError("positive fixtures must not declare misleading operations")
        return self


class CognitiveDataset(BaseModel):
    """Reviewable fixed labels, including coverage requirements for both courses."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["assessment-cognitive-tasks/1"]
    annotation_method: str = Field(min_length=1)
    review_status: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    cases: tuple[CognitiveCase, ...] = Field(min_length=10)

    @model_validator(mode="after")
    def validate_coverage(self) -> CognitiveDataset:
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("case IDs must be unique")
        for course in COURSE_TARGETS:
            cases = [case for case in self.cases if case.course_id == course]
            positives = {case.expected_operation for case in cases if case.case_kind == "positive"}
            if positives != set(CognitiveOperation):
                raise ValueError("each course must contain positive examples of all four operations")
            if not any(case.case_kind == "long_context_recall" for case in cases):
                raise ValueError("each course must contain a long-context recall negative")
        return self


def _positive_limit(value: str) -> int:
    limit = int(value)
    if limit < 1:
        raise argparse.ArgumentTypeError("limit must be at least 1")
    return limit


def _statistics(rows: list[dict]) -> dict:
    """Keep failed calls out of accuracy denominators and expose their count."""
    per_class = {}
    confusion = {
        operation.value: dict.fromkeys((item.value for item in CognitiveOperation), 0)
        for operation in CognitiveOperation
    }
    for operation in CognitiveOperation:
        selected = [row for row in rows if row["expected_operation"] == operation.value]
        valid = [row for row in selected if row["observed_operation"] is not None]
        correct = sum(row["matched"] for row in valid)
        per_class[operation.value] = {
            "attempted": len(selected),
            "observed": len(valid),
            "failed": len(selected) - len(valid),
            "correct": correct,
            "accuracy_on_observed": correct / len(valid) if valid else None,
        }
        for row in valid:
            confusion[operation.value][row["observed_operation"]] += 1
    valid = [row for row in rows if row["observed_operation"] is not None]
    correct = sum(row["matched"] for row in valid)
    return {
        "attempted": len(rows),
        "observed": len(valid),
        "provider_failures": len(rows) - len(valid),
        "provider_failure_rate": (len(rows) - len(valid)) / len(rows) if rows else None,
        "accuracy_on_observed": correct / len(valid) if valid else None,
        "correct_per_attempt": correct / len(rows) if rows else None,
        "per_class": per_class,
        "confusion_expected_to_observed": confusion,
    }


def run_provider(cases: tuple[CognitiveCase, ...], dataset_digest: str, review_status: str) -> int:
    """Call the configured real critic only after the CLI's double opt-in."""
    from ds_course_agent.assessment.critic import AssessmentQualityCritic
    from ds_course_agent.assessment.evidence import resolve_target
    from ds_course_agent.assessment.feedback import AssessmentFailureKind
    from ds_course_agent.assessment.models import GenerateQuestionsRequest
    from ds_course_agent.assessment.task_context import AssessmentTaskContext
    from ds_course_agent.assessment.versioning import assessment_resource_revision

    # Resolve all targets before paying for any call. Never retrieve student data.
    contexts = {}
    revisions = {}
    for case in cases:
        if case.course_id not in contexts:
            request = GenerateQuestionsRequest(target_kc_id=case.target_kc_id, count=1, difficulty=Difficulty.BASIC)
            contexts[case.course_id] = AssessmentTaskContext(request, resolve_target(request, course_id=case.course_id))
            revisions[case.course_id] = assessment_resource_revision(case.course_id).model_dump(mode="json")
    started_at = datetime.now(timezone.utc).isoformat()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    REPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIRECTORY / f"critic-calibration-{run_id}.json"
    rows = []
    report = {
        "mode": "real_provider",
        "started_at": started_at,
        "dataset_sha256": dataset_digest,
        "annotation_review_status": review_status,
        "scope": "cognitive classification only; not a generation or textbook evidence acceptance test",
        "failure_rate_definition": "all attempted critic calls without a valid verdict, including setup/schema failures",
        "resource_revisions": revisions,
        "completed": False,
        "cases": rows,
    }

    def save_report() -> None:
        report["summary"] = _statistics(rows)
        report["by_course"] = {
            course: _statistics([row for row in rows if row["course_id"] == course]) for course in contexts
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Do not serialize provider exceptions, raw responses, prompts or credentials.
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    critic = AssessmentQualityCritic()
    save_report()
    try:
        for case in cases:
            row = {
                "id": case.id,
                "course_id": case.course_id,
                "case_kind": case.case_kind,
                "expected_operation": case.expected_operation.value,
                "observed_operation": None,
                "matched": False,
                "status": "provider_failure",
            }
            started = time.perf_counter()
            try:
                # Gold labels, annotation rationale and learner data never enter
                # the call. Required question schema fields are stripped by the
                # real critic's answer/difficulty-blind prompt projection.
                (verdict,) = critic.critique_batch(contexts[case.course_id], [case.question])
                row.update(
                    observed_operation=verdict.cognitive_operation.value,
                    matched=verdict.cognitive_operation == case.expected_operation,
                    status="observed",
                )
            except Exception as exc:
                kind = getattr(exc, "failure_kind", AssessmentFailureKind.UNKNOWN)
                row["failure_kind"] = kind.value if isinstance(kind, AssessmentFailureKind) else "unknown"
            row["seconds"] = round(time.perf_counter() - started, 3)
            rows.append(row)
            save_report()
            print(json.dumps(row, ensure_ascii=False), flush=True)
        report["completed"] = True
        save_report()
    finally:
        logging.disable(previous_logging)
    print(json.dumps({"summary": report["summary"], "report": str(report_path)}, ensure_ascii=False, indent=2))
    return int(any(not row["matched"] for row in rows))


def main() -> int:
    """Validate all fixtures before selection; default mode never creates a model."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", action="store_true", help="Use the configured real AssessmentQualityCritic")
    parser.add_argument(
        "--confirm", action="store_true", help="Explicitly confirm real provider calls and possible cost"
    )
    parser.add_argument("--course", choices=tuple(COURSE_TARGETS))
    parser.add_argument("--limit", type=_positive_limit)
    args = parser.parse_args()
    if args.provider != args.confirm:
        parser.error("real provider calls require --provider and --confirm together")
    try:
        raw = DATASET_PATH.read_bytes()
        dataset = CognitiveDataset.model_validate_json(raw)
    except (OSError, ValidationError) as exc:
        parser.error(f"fixture validation failed: {exc}")
    cases = tuple(case for case in dataset.cases if args.course in (None, case.course_id))
    if args.limit is not None:
        cases = cases[: args.limit]
    if not args.provider:
        print(
            json.dumps(
                {
                    "mode": "static_validation",
                    "status": "passed",
                    "dataset": str(DATASET_PATH),
                    "validated_cases": len(dataset.cases),
                    "selected_cases": len(cases),
                    "by_course": dict(Counter(case.course_id for case in cases)),
                    "expected_operations": dict(Counter(case.expected_operation.value for case in cases)),
                    "long_context_recall_cases": sum(case.case_kind == "long_context_recall" for case in cases),
                    "review_status": dataset.review_status,
                    "provider_calls": 0,
                    "accuracy": None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    return run_provider(cases, hashlib.sha256(raw).hexdigest(), dataset.review_status)


if __name__ == "__main__":
    raise SystemExit(main())
