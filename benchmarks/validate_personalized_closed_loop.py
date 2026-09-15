"""Validate the frozen personalized closed-loop dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from benchmarks.personalized_closed_loop_schema import dataset_json_schema, validate_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schema")
    validate = commands.add_parser("validate")
    validate.add_argument("dataset", type=Path)
    validate.add_argument("--catalog", type=Path, default=Path("data/knowledge_graph.json"))
    args = parser.parse_args(argv)
    if args.command == "schema":
        print(json.dumps(dataset_json_schema(), ensure_ascii=False, indent=2))
        return 0
    try:
        dataset = validate_dataset(args.dataset, catalog_path=args.catalog)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    print(f"VALID: {len(dataset.trajectories)} trajectories; frozen={dataset.generation.review_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
