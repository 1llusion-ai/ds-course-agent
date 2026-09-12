"""Audit the active course corpus without modifying it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts._path import ensure_src_path

ensure_src_path()

import chromadb

import ds_course_agent.shared.config as config
from ds_course_agent.kb.corpus_audit import CorpusAuditRecord, audit_corpus_records
from ds_course_agent.retrieval.index_manifest import PromotedIndexManifest


def parse_args() -> argparse.Namespace:
    """Parse bounded read-only audit options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=_PROJECT_ROOT / "var/artifacts/assessment/corpus_audit_20260911.json",
    )
    return parser.parse_args()


def main() -> None:
    """Read the active collection and write a deterministic audit artifact."""
    args = parse_args()
    client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
    manifest_path = Path(config.RAG_INDEX_MANIFEST_PATH)
    manifest = PromotedIndexManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    try:
        collection = client.get_collection(config.collection_name)
        payload = collection.get(include=["documents", "metadatas"])
        records = [
            CorpusAuditRecord(text=text or "", metadata=metadata or {})
            for text, metadata in zip(payload.get("documents") or [], payload.get("metadatas") or [], strict=True)
        ]
        report = audit_corpus_records(
            records,
            expected_document_count=manifest.document_count,
            expected_collection_revision=manifest.collection_revision,
        )
    finally:
        client.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": report.passed,
                "total_records": report.total_records,
                "semantic_records": report.semantic_records,
                "issue_count": len(report.issues),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    if not report.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
