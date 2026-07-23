"""Tests for Phase B missing HTTP-access metadata rechecks."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.knowledge_state_search.phase_b_source_access_recheck import (
    load_verified_access_ids,
    write_access_recheck_artifacts,
)


class _Response:
    def __init__(self, status_code: int, url: str):
        self.status_code = status_code
        self.url = url
        self.headers = {"Content-Type": "text/html"}
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_access_recheck_writes_http_200_evidence_without_modifying_capture(
    tmp_path: Path,
):
    packet_path = tmp_path / "packet.jsonl"
    qa_report_path = tmp_path / "qa.json"
    output = tmp_path / "output"
    packet_path.write_text(
        json.dumps(
            {
                "source_id": "pb_t01_s01",
                "url": "https://source.example.test/page",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    qa_report_path.write_text(
        json.dumps(
            {
                "http_access_metadata_missing_source_ids": ["pb_t01_s01"],
            }
        ),
        encoding="utf-8",
    )
    response = _Response(200, "https://source.example.test/page")

    report = write_access_recheck_artifacts(
        packet_path=packet_path,
        qa_report_path=qa_report_path,
        output_directory=output,
        max_retries=1,
        request_get=lambda *args, **kwargs: response,
    )

    result_path = output / "http_access_recheck.jsonl"
    rows = [json.loads(line) for line in result_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert report["status"] == "pass"
    assert report["verified_http_200_count"] == 1
    assert report["historical_capture_metadata_modified"] is False
    assert rows[0]["verified_http_200"] is True
    assert response.closed is True
    assert load_verified_access_ids(
        result_path,
        expected_source_ids={"pb_t01_s01"},
    ) == {"pb_t01_s01"}
