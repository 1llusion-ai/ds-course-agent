#!/usr/bin/env python3
"""Build offline embedding cache for knowledge mapper concepts."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.knowledge_mapper import precompute_knowledge_graph_embeddings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Precompute and persist knowledge mapper concept embeddings."
    )
    parser.add_argument(
        "--graph",
        default="data/knowledge_graph.json",
        help="Path to knowledge graph json.",
    )
    parser.add_argument(
        "--output",
        default="data/knowledge_graph_embeddings.json",
        help="Path to embedding cache output json.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force rebuild even if in-memory embeddings already exist.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    graph_path = Path(args.graph)
    if not graph_path.is_absolute():
        graph_path = PROJECT_ROOT / graph_path

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    if not graph_path.exists():
        print(f"[ERROR] knowledge graph not found: {graph_path}")
        return 1

    os.environ["KNOWLEDGE_MAPPER_EMBEDDING_CACHE"] = str(output_path)
    count = precompute_knowledge_graph_embeddings(
        graph_path=str(graph_path),
        embedding_cache_path=str(output_path),
        force=args.force,
    )
    print(f"[OK] cached {count} concept embeddings -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
