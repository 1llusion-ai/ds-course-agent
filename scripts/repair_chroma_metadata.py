#!/usr/bin/env python3
"""Repair Chroma metadata using the course TOC.

The existing collection stores parser/PDF page numbers in ``book_page`` for
some chunks.  The official TOC in ``data/目录.json`` uses textbook page numbers,
which are offset from parser pages.  This script rewrites chapter/section labels
and textbook page fields while preserving parser page fields as source_page*.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from scripts._path import PROJECT_ROOT, ensure_src_path

ensure_src_path()

from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import chromadb

import ds_course_agent.shared.config as config
from ds_course_agent.kb.toc_parser import SectionInfo, get_toc_parser


@dataclass(frozen=True)
class TocIndex:
    chapters: dict[str, SectionInfo]
    sections: dict[str, SectionInfo]
    all_sections: list[SectionInfo]
    first_textbook_page: int


def _build_toc_index() -> TocIndex:
    toc = get_toc_parser()
    chapters: dict[str, SectionInfo] = {}
    sections: dict[str, SectionInfo] = {}
    for section in getattr(toc, "all_sections", []):
        if section.number:
            sections[section.number] = section
        if section.level == 1 and section.number:
            chapters[section.number] = section
    all_sections = list(getattr(toc, "all_sections", []))
    first_textbook_page = min(
        (section.page for section in all_sections if getattr(section, "page", None)),
        default=1,
    )
    return TocIndex(
        chapters=chapters,
        sections=sections,
        all_sections=all_sections,
        first_textbook_page=first_textbook_page,
    )


def _parse_json_list(value: Any) -> list[int]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        raw = value
    elif isinstance(value, str):
        try:
            raw = json.loads(value)
        except json.JSONDecodeError:
            return []
    else:
        raw = [value]
    result = []
    for item in raw:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            pass
    return result


def _first_int(*values: Any) -> int | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _chapter_number_from_outline(metadata: dict[str, Any]) -> str:
    outline = str(metadata.get("subsection_no") or metadata.get("section_no") or "").strip()
    match = re.match(r"^(\d+)\.", outline)
    if not match:
        return ""
    return f"第{int(match.group(1))}章"


def _parent_number(number: str) -> str:
    parts = number.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else ""


def _chapter_by_number(index: TocIndex, number: str) -> SectionInfo | None:
    if number.startswith("第"):
        return index.chapters.get(number)
    match = re.match(r"^(\d+)\.", number)
    if not match:
        return None
    return index.chapters.get(f"第{int(match.group(1))}章")


def _best_section_by_number(
    index: TocIndex, metadata: dict[str, Any]
) -> tuple[SectionInfo | None, SectionInfo | None, SectionInfo | None]:
    subsection_no = str(metadata.get("subsection_no") or "").strip()
    section_no = str(metadata.get("section_no") or "").strip()

    subsection = index.sections.get(subsection_no) if subsection_no else None
    section = index.sections.get(section_no) if section_no else None
    if subsection and not section:
        section = index.sections.get(_parent_number(subsection.number))

    chapter = None
    for number in [
        subsection_no,
        section_no,
        _chapter_number_from_outline(metadata),
        str(metadata.get("chapter_no") or ""),
    ]:
        chapter = _chapter_by_number(index, number)
        if chapter:
            break
    return chapter, section, subsection


def _section_range_contains(section: SectionInfo | None, page: int | None) -> bool:
    if section is None or page is None:
        return False
    end_page = max(section.end_page or section.page, section.page)
    return section.page <= page <= end_page


def _parent_section(index: TocIndex, section: SectionInfo | None) -> SectionInfo | None:
    if section is None:
        return None
    return index.sections.get(_parent_number(section.number))


def _section_by_page(index: TocIndex, textbook_page: int | None) -> SectionInfo | None:
    if textbook_page is None:
        return None
    candidates = [section for section in index.all_sections if _section_range_contains(section, textbook_page)]
    if not candidates:
        return None
    return max(candidates, key=lambda section: section.level)


def _best_section_by_page(
    index: TocIndex, textbook_page: int | None
) -> tuple[SectionInfo | None, SectionInfo | None, SectionInfo | None]:
    best = _section_by_page(index, textbook_page)
    if best is None:
        return None, None, None
    chapter = _chapter_by_number(index, best.number) or (best if best.level == 1 else None)
    section = None
    subsection = None
    if best.level == 2:
        section = best
    elif best.level >= 3:
        subsection = best
        section = index.sections.get(_parent_number(best.number))
    return chapter, section, subsection


def _infer_source_pages(metadata: dict[str, Any]) -> tuple[int | None, int | None, list[int]]:
    source_pages = _parse_json_list(metadata.get("source_pages"))
    parser_page = _first_int(
        metadata.get("source_page_start"),
        metadata.get("source_page"),
        metadata.get("page_start"),
        metadata.get("page"),
        metadata.get("book_page_start"),
        metadata.get("book_page"),
    )
    parser_end = _first_int(
        metadata.get("source_page_end"),
        metadata.get("page_end"),
        metadata.get("book_page_end"),
        parser_page,
    )
    if not source_pages and parser_page is not None:
        source_pages = [parser_page]
    if source_pages:
        parser_page = source_pages[0]
        parser_end = source_pages[-1]
    return parser_page, parser_end, source_pages


def _infer_textbook_page(
    source_pages: list[int],
    parser_page: int | None,
    page_offset: int,
) -> tuple[int | None, int | None, list[int]]:
    textbook_pages = [page - page_offset for page in source_pages if page - page_offset > 0]
    if not textbook_pages and parser_page is not None and parser_page - page_offset > 0:
        textbook_pages = [parser_page - page_offset]
    start = textbook_pages[0] if textbook_pages else None
    end = textbook_pages[-1] if textbook_pages else start
    return start, end, textbook_pages


def _choose_sections(
    metadata: dict[str, Any],
    index: TocIndex,
    textbook_start: int | None,
) -> tuple[SectionInfo | None, SectionInfo | None, SectionInfo | None]:
    page_chapter, page_section, page_subsection = _best_section_by_page(index, textbook_start)
    number_chapter, number_section, number_subsection = _best_section_by_number(index, metadata)

    if page_chapter is None:
        return None, None, None

    # 页码范围是主信号；编号只允许在同一教材页范围内细化。
    chapter = page_chapter
    section = page_section
    subsection = page_subsection

    if number_section and _section_range_contains(number_section, textbook_start):
        section = number_section
        subsection = None
    if number_subsection and _section_range_contains(number_subsection, textbook_start):
        subsection = number_subsection
        section = _parent_section(index, number_subsection) or section

    return chapter, section, subsection


CHAPTER_KEYS = (
    "chapter_no",
    "chapter",
    "section_no",
    "section",
    "subsection_no",
    "subsection",
)
PAGE_KEYS = (
    "page",
    "page_start",
    "page_end",
    "book_page",
    "book_page_start",
    "book_page_end",
    "book_pages",
    "source_page",
    "source_page_start",
    "source_page_end",
    "source_pages",
)


def normalized_metadata(metadata: dict[str, Any], index: TocIndex, page_offset: int) -> dict[str, Any]:
    updated = dict(metadata)
    for key in (*CHAPTER_KEYS, *PAGE_KEYS):
        updated.pop(key, None)

    parser_start, parser_end, parser_pages = _infer_source_pages(metadata)
    textbook_start, textbook_end, textbook_pages = _infer_textbook_page(
        parser_pages,
        parser_start,
        page_offset,
    )
    chapter, section, subsection = _choose_sections(metadata, index, textbook_start)

    has_textbook_page = (
        textbook_start is not None and textbook_start >= index.first_textbook_page and chapter is not None
    )

    if chapter and has_textbook_page:
        updated["chapter_no"] = chapter.number
        updated["chapter"] = chapter.name
    if section and has_textbook_page:
        updated["section_no"] = section.number
        updated["section"] = section.name
    if subsection and has_textbook_page:
        updated["subsection_no"] = subsection.number
        updated["subsection"] = subsection.name

    # Preserve parser/PDF pages explicitly, and make book_page* mean textbook pages.
    if parser_start is not None:
        updated["source_page"] = parser_start
        updated["source_page_start"] = parser_start
    if parser_end is not None:
        updated["source_page_end"] = parser_end
    if parser_pages:
        updated["source_pages"] = json.dumps(parser_pages, ensure_ascii=False)

    if has_textbook_page and textbook_start is not None:
        updated["book_page"] = textbook_start
        updated["book_page_start"] = textbook_start
        updated["page"] = textbook_start
        updated["page_start"] = textbook_start
    if has_textbook_page and textbook_end is not None:
        updated["book_page_end"] = textbook_end
        updated["page_end"] = textbook_end
    if has_textbook_page and textbook_pages:
        updated["book_pages"] = json.dumps(textbook_pages, ensure_ascii=False)

    updated["metadata_repaired"] = True
    updated["metadata_repair_page_offset"] = page_offset
    return {k: v for k, v in updated.items() if v is not None and v != ""}


def repair_collection(
    collection_name: str, persist_dir: str, page_offset: int, dry_run: bool = False, batch_size: int = 200
) -> dict[str, int]:
    index = _build_toc_index()
    client = chromadb.PersistentClient(path=persist_dir)
    collection = client.get_collection(collection_name)
    total = collection.count()
    changed = 0
    all_ids = collection.get(limit=total).get("ids") or []

    for offset in range(0, len(all_ids), batch_size):
        batch_ids = all_ids[offset : offset + batch_size]
        batch = collection.get(
            ids=batch_ids,
            include=["documents", "embeddings", "metadatas"],
        )
        ids = batch.get("ids") or []
        documents = batch.get("documents") or []
        embeddings = batch.get("embeddings")
        metadatas = batch.get("metadatas") or []
        update_ids: list[str] = []
        update_docs: list[str] = []
        update_embeddings: list[list[float]] = []
        update_metas: list[dict[str, Any]] = []
        for idx, (item_id, metadata) in enumerate(zip(ids, metadatas)):
            metadata = dict(metadata or {})
            normalized = normalized_metadata(metadata, index, page_offset)
            if normalized != metadata:
                changed += 1
                update_ids.append(item_id)
                update_docs.append(documents[idx])
                if embeddings is not None:
                    update_embeddings.append(embeddings[idx])
                update_metas.append(normalized)
        if update_ids and not dry_run:
            # Chroma's update/upsert merge metadata and cannot delete stale keys.
            # Delete + add gives us an exact replacement of wrong page/chapter fields.
            collection.delete(ids=update_ids)
            add_kwargs: dict[str, Any] = {
                "ids": update_ids,
                "documents": update_docs,
                "metadatas": update_metas,
            }
            if embeddings is not None:
                add_kwargs["embeddings"] = update_embeddings
            collection.add(**add_kwargs)

    return {"total": total, "changed": changed, "dry_run": int(dry_run)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", default=config.collection_name)
    parser.add_argument("--persist-dir", default=config.CHROMA_PERSIST_DIR)
    parser.add_argument(
        "--page-offset",
        type=int,
        default=8,
        help="parser/PDF page - textbook page; full book parser page 9 is textbook page 1",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(repair_collection(args.collection, args.persist_dir, args.page_offset, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
