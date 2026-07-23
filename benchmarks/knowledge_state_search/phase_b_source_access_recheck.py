"""Recheck HTTP accessibility for Phase B captures missing status sidecars."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from benchmarks.knowledge_state_search.model_retry import (
    is_retryable_status,
    retry_delay,
)
from benchmarks.knowledge_state_search.phase_b_model_verification_contract import (
    required_string,
)
from benchmarks.knowledge_state_search.phase_b_model_verification_inputs import (
    DEFAULT_PACKET_PATH,
    DEFAULT_QA_REPORT_PATH,
)

DEFAULT_OUTPUT_DIRECTORY = Path("var/artifacts/knowledge_state_search/phase_b_source_access_recheck")
RequestGet = Callable[..., requests.Response]


def write_access_recheck_artifacts(
    *,
    packet_path: Path = DEFAULT_PACKET_PATH,
    qa_report_path: Path = DEFAULT_QA_REPORT_PATH,
    output_directory: Path = DEFAULT_OUTPUT_DIRECTORY,
    timeout: float = 45.0,
    max_retries: int = 2,
    request_get: RequestGet = requests.get,
) -> dict[str, object]:
    """Recheck only source IDs explicitly lacking historical HTTP metadata."""

    packet_rows = _read_jsonl(packet_path)
    packet_by_id = _unique_rows(packet_rows)
    qa_report = json.loads(qa_report_path.read_text(encoding="utf-8"))
    missing_ids = tuple(
        sorted(str(source_id) for source_id in qa_report.get("http_access_metadata_missing_source_ids", []))
    )
    unknown_ids = sorted(set(missing_ids) - set(packet_by_id))
    if unknown_ids:
        raise ValueError(f"HTTP metadata gaps contain unknown source IDs: {unknown_ids}")

    rows = [
        _recheck_source(
            packet_by_id[source_id],
            timeout=timeout,
            max_retries=max_retries,
            request_get=request_get,
        )
        for source_id in missing_ids
    ]
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / "http_access_recheck.jsonl"
    _write_jsonl(output_path, rows)
    verified_count = sum(row["verified_http_200"] is True for row in rows)
    report = {
        "status": "pass" if verified_count == len(rows) else "complete_with_failures",
        "checked_count": len(rows),
        "verified_http_200_count": verified_count,
        "failed_count": len(rows) - verified_count,
        "source_ids": list(missing_ids),
        "output_path": str(output_path),
        "historical_capture_metadata_modified": False,
        "annotation_started": False,
        "method_runs_authorized": False,
    }
    (output_directory / "http_access_recheck_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def load_verified_access_ids(
    path: Path,
    *,
    expected_source_ids: set[str],
) -> set[str]:
    """Load unique successful HTTP rechecks without accepting unknown IDs."""

    rows = _read_jsonl(path)
    verified: set[str] = set()
    seen: set[str] = set()
    for row in rows:
        source_id = required_string(row, "source_id")
        if source_id in seen:
            raise ValueError(f"duplicate HTTP access recheck source_id: {source_id}")
        if source_id not in expected_source_ids:
            raise ValueError(f"unknown HTTP access recheck source_id: {source_id}")
        seen.add(source_id)
        if row.get("verified_http_200") is True:
            if row.get("status_code") != 200:
                raise ValueError(f"successful HTTP recheck lacks status 200: {source_id}")
            verified.add(source_id)
    return verified


def build_parser() -> argparse.ArgumentParser:
    """Build the missing-access recheck CLI."""

    parser = argparse.ArgumentParser(description="Recheck Phase B sources missing historical HTTP-200 metadata.")
    parser.add_argument("--packet", type=Path, default=DEFAULT_PACKET_PATH)
    parser.add_argument("--qa-report", type=Path, default=DEFAULT_QA_REPORT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--max-retries", type=int, default=2)
    return parser


def main() -> int:
    """Run access rechecks and print the machine-readable report."""

    args = build_parser().parse_args()
    report = write_access_recheck_artifacts(
        packet_path=args.packet,
        qa_report_path=args.qa_report,
        output_directory=args.output,
        timeout=args.timeout,
        max_retries=args.max_retries,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _recheck_source(
    packet: dict[str, Any],
    *,
    timeout: float,
    max_retries: int,
    request_get: RequestGet,
) -> dict[str, object]:
    source_id = required_string(packet, "source_id")
    url = required_string(packet, "url")
    attempts: list[dict[str, object]] = []
    final_status: int | None = None
    effective_url = ""
    content_type = ""
    final_error = ""
    for attempt in range(1, max_retries + 1):
        checked_at = datetime.now(timezone.utc).isoformat()
        try:
            response = request_get(
                url,
                headers={"User-Agent": ("Mozilla/5.0 (compatible; ds-course-agent-phase-b-source-verifier/1.0)")},
                allow_redirects=True,
                stream=True,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            final_error = f"{type(exc).__name__}: {exc}"
            attempts.append(
                {
                    "attempt": attempt,
                    "checked_at": checked_at,
                    "error": final_error,
                }
            )
            if attempt < max_retries:
                time.sleep(retry_delay(status_code=None, retry_after=None, attempt=attempt))
            continue
        try:
            final_status = response.status_code
            effective_url = str(response.url)
            content_type = response.headers.get("Content-Type", "")
            attempts.append(
                {
                    "attempt": attempt,
                    "checked_at": checked_at,
                    "status_code": final_status,
                    "effective_url": effective_url,
                    "content_type": content_type,
                }
            )
            if final_status == 200:
                break
            final_error = f"HTTP {final_status}"
            if attempt < max_retries and is_retryable_status(final_status):
                time.sleep(
                    retry_delay(
                        status_code=final_status,
                        retry_after=response.headers.get("Retry-After"),
                        attempt=attempt,
                    )
                )
                continue
            break
        finally:
            response.close()
    return {
        "source_id": source_id,
        "url": url,
        "status_code": final_status,
        "effective_url": effective_url,
        "content_type": content_type,
        "verified_http_200": final_status == 200,
        "error": final_error if final_status != 200 else "",
        "attempts": attempts,
    }


def _unique_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        source_id = required_string(row, "source_id")
        if source_id in result:
            raise ValueError(f"duplicate verification packet source_id: {source_id}")
        result[source_id] = row
    return result


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
