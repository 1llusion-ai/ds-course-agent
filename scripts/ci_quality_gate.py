#!/usr/bin/env python3
"""Run the local quality gate for route/sandbox/refactor invariants.

The gate intentionally avoids network-only checks. Docker integration tests are
optional and run only with ``--include-docker``; they still skip when Docker or
the sandbox image is unavailable.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROUTE_REPORT = PROJECT_ROOT / "var" / "artifacts" / "benchmarks" / "ci_route_harness_report.json"


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    print("$ " + " ".join(command), flush=True)
    return subprocess.run(command, cwd=PROJECT_ROOT, check=check)


def run_gate(*, include_docker: bool = False, skip_full: bool = False) -> int:
    py = sys.executable
    targeted_tests = [
        "tests/test_code_review_skill.py",
        "tests/test_code_executor.py",
        "tests/test_config_settings.py",
        "tests/test_context_governor.py",
        "tests/test_tool_registry.py",
        "tests/test_tool_result_store.py",
        "tests/test_query_pipeline.py",
        "tests/test_route_harness.py",
    ]

    _run([py, "-m", "pytest", "-q", *targeted_tests])
    _run([py, "benchmarks/route_harness.py", "--output", str(DEFAULT_ROUTE_REPORT)])

    report = json.loads(DEFAULT_ROUTE_REPORT.read_text(encoding="utf-8"))
    summary = report.get("summary", {})
    failed = int(summary.get("failed_cases", 0) or 0)
    unexpected_rag = int(summary.get("unexpected_rag_count", 0) or 0)
    if failed or unexpected_rag:
        print(
            f"Route harness gate failed: failed_cases={failed}, unexpected_rag_count={unexpected_rag}",
            file=sys.stderr,
        )
        return 1

    if include_docker:
        _run([py, "-m", "pytest", "-q", "-m", "docker", "tests/integration/test_python_sandbox_docker.py"])

    if not skip_full:
        _run([py, "-m", "pytest", "-q"])

    print("CI quality gate passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run route/sandbox/refactor quality gate checks.")
    parser.add_argument("--include-docker", action="store_true", help="also run optional real Docker sandbox tests")
    parser.add_argument("--skip-full", action="store_true", help="skip full pytest suite after targeted checks")
    args = parser.parse_args()
    return run_gate(include_docker=args.include_docker, skip_full=args.skip_full)


if __name__ == "__main__":
    raise SystemExit(main())
