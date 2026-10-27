"""Offline assessment coverage and bank command contracts."""

from __future__ import annotations

import json

from scripts.assessment_bank import main as bank_main
from scripts.assessment_inventory import build_inventory


def test_data_science_inventory_classifies_every_knowledge_point() -> None:
    report = build_inventory("data-science-intro")

    assert report["kc_count"] == 129
    assert sum(report["status_counts"].values()) == report["kc_count"]
    assert report["status_counts"] == {"assessable": 22, "needs_evidence": 2, "uncovered": 105}


def test_bank_defaults_to_a_read_only_three_level_dry_run(capsys) -> None:
    assert bank_main(["--course-id", "data-science-intro", "--dry-run", "--count", "2"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry-run"
    assert output["planned_batches"] == 22 * 3
    assert output["difficulties"] == ["basic", "intermediate", "advanced"]
