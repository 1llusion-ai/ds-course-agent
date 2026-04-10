"""Rebuild the chapter-based course knowledge base with explicit chunk params."""

from __future__ import annotations

import argparse
import hashlib
import pickle
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from kb_builder.cleaner import clean_document
from kb_builder.chunker import CourseChunkerV2
from kb_builder.parser import parse_pdf_file
from kb_builder.store import CourseKnowledgeBase
from kb_builder.toc_parser import get_toc_parser


def _file_hash(pdf_path: str) -> str:
    """Match the cache key strategy used by scripts/build_kb.py."""
    stat = Path(pdf_path).stat()
    key = f"{Path(pdf_path).resolve()}|{stat.st_mtime}|{stat.st_size}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _cache_path(pdf_path: str, stage: str, max_pages: int = 0) -> Path:
    base = Path("data/cache")
    name = f"{Path(pdf_path).stem}_{_file_hash(pdf_path)}_mp{max_pages}_{stage}.pkl"
    return base / name


def _load_cache(cache_path: Path):
    if not cache_path.exists():
        return None
    try:
        with cache_path.open("rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _save_cache(cache_path: Path, obj):
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("wb") as f:
        pickle.dump(obj, f)


def check_current_kb():
    """Print current KB status and return the active collection + count."""
    print("=" * 60)
    print("Step 1: Check current KB")
    print("=" * 60)

    import chromadb
    import utils.config as config

    client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
    collections = client.list_collections()
    print(f"\nExisting collections ({len(collections)}):")
    for collection_info in collections:
        coll = client.get_collection(collection_info.name)
        print(f"  - {collection_info.name}: {coll.count()} docs")

    if not collections:
        print("  (none)")
        return None, 0

    collection = client.get_collection(config.COLLECTION_NAME)
    count = collection.count()
    if count == 0:
        print("\nCurrent KB is empty")
        return collection, 0

    results = collection.get(include=["metadatas"], limit=1000)
    chapter_counts = defaultdict(int)
    sources = set()
    for metadata in results["metadatas"]:
        if not metadata:
            continue
        chapter = metadata.get("chapter_no", metadata.get("chapter", "Unknown"))
        chapter_counts[chapter] += 1
        sources.add(metadata.get("source", "unknown"))

    print(f"\nCurrent docs: {count}")
    print(f"Source files: {len(sources)}")
    print("Chapter distribution:")
    for chapter in sorted(chapter_counts.keys()):
        print(f"  {chapter}: {chapter_counts[chapter]}")

    return collection, count


def get_pdf_files():
    """Return chapter PDFs plus appendix in a deterministic order."""
    data_dir = Path("data")
    pdf_files = []
    for chapter_num in range(1, 11):
        pdf_path = data_dir / f"数据科学导论(案例版)_第{chapter_num}章.pdf"
        if pdf_path.exists():
            pdf_files.append((chapter_num, str(pdf_path)))

    appendix_path = data_dir / "数据科学导论(案例版)_附录.pdf"
    if appendix_path.exists():
        pdf_files.append(("appendix", str(appendix_path)))

    return pdf_files


def resolve_source_section(toc, chapter_key):
    """Map a source PDF to its TOC section to recover absolute book pages."""
    if chapter_key == "appendix":
        for section in toc.sections:
            if "附录" in section.title or "附录" in section.name:
                return section
        return None

    target_number = f"第{chapter_key}章"
    for section in toc.sections:
        if section.number == target_number:
            return section
    return None


def check_chunk_quality(chunk_result):
    """Simple chunk quality checks used during rebuild."""
    issues = []

    empty_chunks = [c for c in chunk_result.chunks if not c.content or not c.content.strip()]
    if empty_chunks:
        issues.append(f"empty_chunks={len(empty_chunks)}")

    short_chunks = [c for c in chunk_result.chunks if len(c.content) < 100]
    if short_chunks:
        issues.append(f"short_chunks={len(short_chunks)}")

    no_chapter = [c for c in chunk_result.chunks if not c.metadata.chapter]
    if no_chapter:
        issues.append(f"missing_chapter={len(no_chapter)}")

    cut_paragraphs = 0
    for chunk in chunk_result.chunks:
        content = chunk.content.strip()
        if content and content[-1] not in "。！？?!\n":
            lines = content.split("\n")
            if lines and len(lines[-1]) < 50:
                cut_paragraphs += 1
    if cut_paragraphs:
        issues.append(f"maybe_cut_paragraphs={cut_paragraphs}")

    semantic_chunks = [c for c in chunk_result.chunks if c.metadata.chunk_type == "semantic"]
    struct_chunks = [c for c in chunk_result.chunks if c.metadata.chunk_type == "struct"]
    shadow_chunks = [c for c in chunk_result.chunks if c.metadata.chunk_type == "shadow"]

    return {
        "total": chunk_result.total_chunks,
        "semantic": len(semantic_chunks),
        "struct": len(struct_chunks),
        "shadow": len(shadow_chunks),
        "avg_size": (
            sum(len(chunk.content) for chunk in chunk_result.chunks) / len(chunk_result.chunks)
            if chunk_result.chunks
            else 0
        ),
        "issues": issues,
    }


def process_source(
    chapter_key,
    pdf_path,
    toc,
    chunk_size: int = 1300,
    chunk_overlap: int = 300,
    max_chunk_size: int | None = None,
    use_cache: bool = True,
):
    """Parse, clean, chunk one source PDF."""
    parse_cache = _cache_path(pdf_path, "parse", max_pages=0)
    clean_cache = _cache_path(pdf_path, "clean", max_pages=0)

    parse_result = _load_cache(parse_cache) if use_cache else None
    if parse_result is not None:
        print(f"\n  Parse PDF... [cache] {parse_cache.name}")
    else:
        print("\n  Parse PDF...")
        parse_result = parse_pdf_file(pdf_path)
        if use_cache:
            _save_cache(parse_cache, parse_result)
            print(f"    saved parse cache: {parse_cache.name}")
    print(f"    total_pages={parse_result.total_pages}, marker_pages={parse_result.marker_pages}")

    cleaned = _load_cache(clean_cache) if use_cache else None
    if cleaned is not None:
        print(f"  Clean text... [cache] {clean_cache.name}")
    else:
        print("  Clean text...")
        pages = [(page.page_num, page.text) for page in parse_result.pages if page.text]
        cleaned = clean_document(pages, parse_result.file_name)
        if use_cache:
            _save_cache(clean_cache, cleaned)
            print(f"    saved clean cache: {clean_cache.name}")
    print(f"    cleaned_pages={len(cleaned.pages)}")

    source_section = resolve_source_section(toc, chapter_key)
    page_offset = source_section.page - 1 if source_section else 0
    print(f"  page_offset={page_offset}")

    chunk_pages = [(page.page_num, page.cleaned_text) for page in cleaned.pages]
    chunker = CourseChunkerV2()
    chunk_result = chunker.chunk_document(
        chunk_pages,
        parse_result.file_name,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        page_offset=page_offset,
        max_chunk_size=max_chunk_size,
    )

    quality = check_chunk_quality(chunk_result)
    print(
        "  Chunk stats:"
        f" total={quality['total']}, semantic={quality['semantic']},"
        f" struct={quality['struct']}, shadow={quality['shadow']},"
        f" avg_size={quality['avg_size']:.0f}"
    )
    if quality["issues"]:
        for issue in quality["issues"]:
            print(f"    [!] {issue}")
    else:
        print("    [OK] no obvious chunk issues")

    return chunk_result, parse_result.file_name


def verify_page_mapping():
    """Print start pages from the TOC and return them for display."""
    print("\n" + "=" * 60)
    print("Step 3: Verify page mapping")
    print("=" * 60)

    toc = get_toc_parser()
    chapter_pages = {}
    for section in toc.sections:
        if section.number.startswith("第") and "章" in section.number:
            try:
                chapter_num = int(section.number.replace("第", "").replace("章", ""))
                chapter_pages[chapter_num] = section.page
            except ValueError:
                pass
        elif "附录" in section.title or "附录" in section.name:
            chapter_pages["appendix"] = section.page

    print("\nTOC start pages:")
    for chapter_key, page in sorted(chapter_pages.items(), key=lambda item: (isinstance(item[0], str), item[0])):
        if chapter_key == "appendix":
            print(f"  appendix: page {page}")
        else:
            print(f"  chapter {chapter_key}: page {page}")

    return chapter_pages


def parse_args():
    parser = argparse.ArgumentParser(description="Rebuild the chapter-based knowledge base")
    parser.add_argument("--chunk-size", type=int, default=1300, help="Target semantic chunk size")
    parser.add_argument("--chunk-overlap", type=int, default=300, help="Overlap between chunks")
    parser.add_argument(
        "--max-chunk-size",
        type=int,
        default=None,
        help="Hard upper bound; defaults to chunk_size + 200",
    )
    parser.add_argument("--no-cache", action="store_true", help="Ignore parse/clean caches under data/cache")
    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 60)
    print("Knowledge base rebuild")
    print("=" * 60)

    _, current_count = check_current_kb()

    print("\n" + "=" * 60)
    print("Step 2: Check source PDFs")
    print("=" * 60)

    pdf_files = get_pdf_files()
    print(f"\nFound {len(pdf_files)} source PDFs:")
    for chapter_key, path in pdf_files:
        label = "appendix" if chapter_key == "appendix" else f"chapter {chapter_key}"
        size_mb = Path(path).stat().st_size / 1024 / 1024
        print(f"  {label}: {Path(path).name} ({size_mb:.1f} MB)")

    chapter_pages = verify_page_mapping()

    print("\n" + "=" * 60)
    print("Step 4: Prepare rebuild")
    print("=" * 60)
    if current_count > 0:
        print(f"\n[!] current KB docs: {current_count}")
        print("    rebuild will clear the active collection first")

    print("\nSources to ingest:")
    for chapter_key, path in pdf_files:
        label = "appendix" if chapter_key == "appendix" else f"chapter {chapter_key}"
        print(f"  {label}: start_page={chapter_pages.get(chapter_key, 'Unknown')} file={Path(path).name}")

    effective_max = args.max_chunk_size or (args.chunk_size + 200)
    print(f"use_cache: {not args.no_cache}")
    print(
        f"\nchunk params: chunk_size={args.chunk_size}, "
        f"chunk_overlap={args.chunk_overlap}, max_chunk_size={effective_max}"
    )

    print("\n" + "=" * 60)
    print("Step 5: Rebuild")
    print("=" * 60)

    kb = CourseKnowledgeBase()
    print("\nClear active collection...")
    kb.clear()
    print("  [OK] cleared")

    toc = get_toc_parser()
    total_stats = {
        "sources": 0,
        "chunks": 0,
        "errors": [],
    }

    for chapter_key, pdf_path in pdf_files:
        label = "appendix" if chapter_key == "appendix" else f"chapter {chapter_key}"
        print(f"\n{'=' * 60}")
        print(f"Process {label}: {Path(pdf_path).name}")
        print("=" * 60)

        try:
            chunk_result, source_file = process_source(
                chapter_key,
                pdf_path,
                toc,
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
                max_chunk_size=args.max_chunk_size,
                use_cache=not args.no_cache,
            )
            print("\n  Ingest...")
            ingest_result = kb.ingest_chunking_result(chunk_result, source_file=source_file)
            print(
                f"    success={ingest_result.success_count}, "
                f"skip={ingest_result.skip_count}, error={ingest_result.error_count}"
            )

            total_stats["sources"] += 1
            total_stats["chunks"] += ingest_result.success_count
            if ingest_result.errors:
                total_stats["errors"].extend(ingest_result.errors[:3])
        except Exception as exc:
            print(f"\n  [FAIL] {exc}")
            import traceback

            traceback.print_exc()

    print("\n" + "=" * 60)
    print("Step 6: Final verification")
    print("=" * 60)

    status = kb.get_status()
    print("\nKB status:")
    print(f"  collection={status.collection_name}")
    print(f"  course={status.course_name}")
    print(f"  document_count={status.document_count}")
    print(f"  source_files={len(status.sources)}")

    print("\nRun stats:")
    print(f"  ingested_sources={total_stats['sources']}/{len(pdf_files)}")
    print(f"  ingested_chunks={total_stats['chunks']}")
    if total_stats["errors"]:
        print("  errors:")
        for error in total_stats["errors"]:
            print(f"    - {error}")

    print("\n" + "=" * 60)
    print("Rebuild complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
