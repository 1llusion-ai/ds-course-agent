"""Offline assessment-bank preparation skeleton.

Generation is opt-in. The default dry-run only reports requested work; writing a
reviewed bank requires ``--confirm-write`` and still relies on the formal service
and review certificates rather than constructing certificates in this script.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ds_course_agent.shared.paths import PROJECT_ROOT

try:
    from scripts.assessment_inventory import build_inventory
except ModuleNotFoundError:  # ``python scripts/assessment_bank.py`` from repo root
    from assessment_inventory import build_inventory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-id", default="data-science-intro")
    parser.add_argument("--kc-id")
    parser.add_argument("--count", type=int, default=2)
    parser.add_argument("--difficulty", choices=("basic", "intermediate", "advanced", "all"), default="all")
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "var/artifacts/assessment/bank-report.json",
        help="JSON report path.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Only inspect coverage; never call generation (default)."
    )
    parser.add_argument("--confirm-write", action="store_true", help="Explicitly permit formal bank persistence.")
    args = parser.parse_args(argv)
    if args.count < 1:
        parser.error("--count must be positive")
    report = build_inventory(args.course_id)
    candidates = [item for item in report["knowledge_components"] if item["status"] == "assessable"]
    if args.kc_id:
        candidates = [item for item in candidates if item["kc_id"] == args.kc_id]
    difficulties = (args.difficulty,) if args.difficulty != "all" else ("basic", "intermediate", "advanced")
    result = {
        "mode": "dry-run" if args.dry_run or not args.confirm_write else "write",
        "course_id": args.course_id,
        "count": args.count,
        "difficulties": difficulties,
        "kc_ids": [item["kc_id"] for item in candidates],
        "planned_batches": len(candidates) * len(difficulties),
        "generated_batches": 0,
        "failed_batches": [],
    }
    if not args.dry_run and args.confirm_write:
        # Keep the formal dependencies visible here; actual publication must be
        # performed by AssessmentService and accumulate(), after a full verified
        # GeneratedQuiz is returned. This skeleton intentionally does not invent
        # evidence or review certificates.
        from ds_course_agent.assessment.items import ReviewedItemRepository
        from ds_course_agent.assessment.models import Difficulty, GenerateQuestionsRequest
        from ds_course_agent.assessment.service import AssessmentService
        from ds_course_agent.shared.config import ASSESSMENT_DB_PATH
        from ds_course_agent.teaching.assessment_assignment import AssessmentAssignmentPlanner

        service = AssessmentService(course_id=args.course_id)
        repository = ReviewedItemRepository(ASSESSMENT_DB_PATH)
        planner = AssessmentAssignmentPlanner()
        generated = 0
        for item in candidates:
            for difficulty in difficulties:
                level = Difficulty(difficulty)
                request = GenerateQuestionsRequest(
                    target_kc_id=item["kc_id"],
                    count=args.count,
                    difficulty=level,
                    teaching_requirement=(
                        planner.complementary_requirement(item["kc_id"], level) if args.count == 2 else None
                    ),
                )
                try:
                    quiz = service.generate(request)
                    repository.accumulate(request, quiz)
                except Exception as exc:
                    result["failed_batches"].append(
                        {
                            "kc_id": item["kc_id"],
                            "difficulty": difficulty,
                            "failure_type": type(exc).__name__,
                            "failure_kind": getattr(getattr(exc, "failure_kind", None), "value", None),
                        }
                    )
                    continue
                generated += 1
        result["generated_batches"] = generated
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["report"] = str(args.report)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
