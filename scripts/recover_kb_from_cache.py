"""Rebuild into a separate directory from trusted local parse/clean caches only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    """Preview a verified cache rebuild; --ingest explicitly enables embedding calls."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-count", required=True, type=int)
    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "src"))
    import ds_course_agent.shared.config as config
    from ds_course_agent.kb.chunker import CourseChunkerV2
    from ds_course_agent.kb.store import CourseKnowledgeBase
    from scripts.build_kb import _compute_page_offset, _file_hash, _load_cache

    target = args.output.resolve()
    active = Path(config.CHROMA_PERSIST_DIR).resolve()
    runtime_root = (root / "var").resolve()
    if (
        not target.is_relative_to(runtime_root)
        or target == runtime_root
        or target.is_relative_to(active)
        or active.is_relative_to(target)
    ):
        parser.error("Recovery output must be a separate directory under var, not the active database")
    pdf = args.pdf.resolve()
    legacy_cache_base = root / "var" / "cache"
    legacy_cache_prefix = f"{pdf.stem}_{_file_hash(str(pdf))}_mp0"
    parse_path = legacy_cache_base / f"{legacy_cache_prefix}_parse.pkl"
    clean_path = legacy_cache_base / f"{legacy_cache_prefix}_clean.pkl"
    parsed, cleaned = _load_cache(parse_path), _load_cache(clean_path)
    if parsed is None or cleaned is None:
        parser.error("Trusted parse/clean caches are required; refusing automatic PDF parsing")
    chunks = CourseChunkerV2().chunk_document(
        [(page.page_num, page.cleaned_text) for page in cleaned.pages],
        parsed.file_name,
        parser_source=parsed.parser_mode,
        page_offset=_compute_page_offset(str(pdf)),
    )
    semantic = [chunk for chunk in chunks.chunks if chunk.metadata.chunk_type == "semantic"]
    if len(semantic) != args.expected_count:
        parser.error(f"Expected {args.expected_count} semantic chunks, got {len(semantic)}")
    plan = {
        "schema": "kb-recovery-v1",
        "source": str(pdf),
        "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "parse_cache": str(parse_path),
        "clean_cache": str(clean_path),
        "pages": parsed.total_pages,
        "semantic_chunks": len(semantic),
        "total_chunks": chunks.total_chunks,
        "page_offset": _compute_page_offset(str(pdf)),
        "collection": config.collection_name,
        "output": str(target),
        "embedding_model": config.MODEL_EMBEDDING,
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
    if not args.ingest:
        return 0
    report_path = target / "recovery.json"
    if target.exists():
        if not args.resume or not report_path.is_file() or json.loads(report_path.read_text())["plan"] != plan:
            parser.error("Existing output is not a matching explicitly resumed recovery")
    else:
        target.mkdir(parents=True, exist_ok=False)
    report_path.write_text(
        json.dumps({"plan": plan, "status": "building"}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Only this process is redirected; .env and the running backend stay unchanged.
    config.CHROMA_PERSIST_DIR = str(target)
    config.persist_directory = str(target)
    os.environ["CHROMA_PERSIST_DIR"] = str(target)
    kb = CourseKnowledgeBase()
    result = kb.ingest_chunking_result(chunks, source_file=parsed.file_name)
    status = kb.get_status()
    valid = result.error_count == 0 and status.document_count == args.expected_count
    report = {
        "plan": plan,
        "status": "verified_count" if valid else "incomplete",
        "ingest": asdict(result),
        "kb": asdict(status),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
