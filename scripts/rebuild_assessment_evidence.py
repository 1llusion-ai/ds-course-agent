"""Preview, delete, or rebuild one student's assessment teaching evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.assessment.repository import AssessmentRepository
from ds_course_agent.teaching.assessment_evidence import AssessmentEvidenceRecorder
from ds_course_agent.teaching.assessment_evidence_maintenance import AssessmentEvidenceMaintenance
from ds_course_agent.teaching.interaction_episode_repository import SQLiteInteractionEpisodeRepository
from ds_course_agent.teaching.learning_event_repository import SQLiteLearningEventRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--student-id", required=True)
    parser.add_argument("--assessment-id", required=True)
    parser.add_argument("--assessment-database", type=Path, default=Path(config.ASSESSMENT_DB_PATH))
    parser.add_argument("--database", type=Path, default=Path(config.APP_DB_PATH))
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--delete", action="store_true")
    action.add_argument("--rebuild", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Apply the selected mutation. Default is dry-run.")
    args = parser.parse_args()
    if args.apply and not (args.delete or args.rebuild):
        parser.error("--apply requires --delete or --rebuild")
    maintenance = AssessmentEvidenceMaintenance(args.database)
    before = maintenance.inspect(args.student_id, args.assessment_id)
    after = before
    if args.apply and (args.delete or args.rebuild):
        after = maintenance.delete(args.student_id, args.assessment_id)
        if args.rebuild:
            record = AssessmentRepository(args.assessment_database).get(args.assessment_id, args.student_id)
            if record is None:
                raise SystemExit("assessment not found for the requested student")
            AssessmentEvidenceRecorder(
                event_repository=SQLiteLearningEventRepository(args.database),
                episode_repository=SQLiteInteractionEpisodeRepository(args.database),
            )(record)
            after = maintenance.inspect(args.student_id, args.assessment_id)
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "action": "rebuild" if args.rebuild else "delete" if args.delete else "inspect",
                "student_id": args.student_id,
                "assessment_id": args.assessment_id,
                "before": before.__dict__,
                "after": after.__dict__,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
