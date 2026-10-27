"""Audit course knowledge components for offline assessment preparation.

The command is deliberately read-only with respect to assessment/runtime databases.
It writes a small JSON report under ``var/artifacts/assessment`` so the audit can be
reviewed and used as input to an offline bank build.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ds_course_agent.courses import CourseCatalog
from ds_course_agent.shared.paths import PROJECT_ROOT
from ds_course_agent.teaching.knowledge_map import NodeType, get_knowledge_map


def build_inventory(course_id: str) -> dict[str, Any]:
    catalog = CourseCatalog.from_directory(PROJECT_ROOT / "data/courses")
    course = catalog.require(course_id)
    knowledge_map = get_knowledge_map(course)
    nodes = [node for node in knowledge_map.nodes if node.node_type is NodeType.KC]
    entries = []
    for node in nodes:
        points = tuple(node.learning_points)
        components = tuple(node.assessment_components)
        # A point or explicit component gives the offline author a concrete
        # target. A bare summary is useful context but is not sufficient evidence.
        if components or points:
            status = "assessable"
        elif node.summary:
            status = "needs_evidence"
        else:
            status = "uncovered"
        entries.append(
            {
                "kc_id": node.canonical_id,
                "display_name": node.display_name,
                "chapter": node.chapter,
                "section": node.section,
                "status": status,
                "learning_point_count": len(points),
                "assessment_component_count": len(components),
            }
        )
    counts = {
        status: sum(item["status"] == status for item in entries)
        for status in ("assessable", "needs_evidence", "uncovered")
    }
    return {
        "schema_version": "assessment-coverage/1",
        "course_id": str(course.course_id),
        "course_revision": course.revision,
        "knowledge_graph_revision": knowledge_map.version,
        "kc_count": len(entries),
        "status_counts": counts,
        "knowledge_components": entries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-id", default="data-science-intro")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "var/artifacts/assessment/coverage.json")
    args = parser.parse_args(argv)
    report = build_inventory(args.course_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "course_id": report["course_id"],
                "kc_count": report["kc_count"],
                "status_counts": report["status_counts"],
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
