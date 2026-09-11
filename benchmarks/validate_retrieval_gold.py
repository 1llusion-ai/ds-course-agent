"""Read-only CLI for retrieval gold validation and generated JSON schemas."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from benchmarks.retrieval_gold_schema import dataset_json_schema
from benchmarks.retrieval_gold_validation import validate_annotation_batch, validate_dataset
from benchmarks.retrieval_panel_schema import panel_json_schema
from benchmarks.retrieval_panel_validation import validate_panel_manifest


def main(argv: list[str] | None = None) -> int:
    """Print a schema or validation result; never write datasets or source files."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schema", help="Print JSON Schema 2020-12 to stdout")
    commands.add_parser("panel-schema", help="Print panel JSON Schema 2020-12 to stdout")
    validate = commands.add_parser("validate", help="Check labels, pinned files, and dual-agent review")
    validate.add_argument("dataset", type=Path)
    validate.add_argument("--root", type=Path, required=True, help="Explicit root for all artifact paths")
    validate.add_argument("--draft", action="store_true", help="Allow unfinished review; never certify a release")
    annotation = commands.add_parser("validate-annotation", help="Check one independent agent annotation batch")
    annotation.add_argument("annotation", type=Path)
    annotation.add_argument("--queries", type=Path, required=True)
    annotation.add_argument("--source-manifest", type=Path, required=True)
    annotation.add_argument("--root", type=Path, required=True)
    panel = commands.add_parser("validate-panel", help="Check the dual-agent candidate-selection panel")
    panel.add_argument("panel", type=Path)
    panel.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "schema":
        print(json.dumps(dataset_json_schema(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "panel-schema":
        print(json.dumps(panel_json_schema(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "validate-annotation":
        try:
            batch = validate_annotation_batch(
                args.annotation,
                queries_path=args.queries,
                source_manifest_path=args.source_manifest,
                root=args.root,
            )
        except (ValueError, OSError) as exc:
            print(f"INVALID: {exc}", file=sys.stderr)
            return 1
        print(f"VALID AGENT ANNOTATION: {batch.annotator_id}; {len(batch.samples)} samples")
        return 0
    if args.command == "validate-panel":
        try:
            validated_panel = validate_panel_manifest(args.panel, root=args.root)
        except (ValueError, OSError) as exc:
            print(f"INVALID PANEL: {exc}", file=sys.stderr)
            return 1
        groups = validated_panel.groups
        print(
            "VALID RETRIEVAL PANEL: "
            f"{len(groups.quality_gate)} quality-gate, "
            f"{len(groups.robustness)} robustness, "
            f"{len(groups.interpretation_sensitive)} interpretation-sensitive, "
            f"{len(groups.boundary)} boundary samples"
        )
        return 0
    try:
        dataset = validate_dataset(args.dataset, root=args.root, release=not args.draft)
    except (ValueError, OSError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    mode = "DRAFT ONLY" if args.draft else "RELEASE STRUCTURE AND AUDIT"
    print(f"VALID ({mode}): {len(dataset.samples)} samples; annotation semantics are not independently certified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
