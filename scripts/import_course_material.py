#!/usr/bin/env python3
"""Create or run a controlled course material import.

Creating a job only records a queued resource version.  ``--run`` explicitly
executes the local offline pipeline and writes candidate artifacts under
``var/``; it never publishes a student-facing course index.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts._path import ensure_src_path  # noqa: E402

ensure_src_path()

from ds_course_agent.kb.ingestion import CourseMaterialImporter  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-id", required=True, help="course resource ID")
    parser.add_argument("--source", required=True, help="PDF under var/course_sources")
    parser.add_argument("--run", action="store_true", help="run the offline stages after creating the job")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    importer = CourseMaterialImporter()
    job = importer.create_job(args.course_id, args.source)
    if args.run:
        job = importer.run(job.job_id)
    print(json.dumps(job.to_dict(), ensure_ascii=False, indent=2))
    return 0 if job.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
