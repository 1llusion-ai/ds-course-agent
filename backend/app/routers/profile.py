import asyncio
import base64
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
import re

from fastapi.concurrency import run_in_threadpool
from fastapi import APIRouter, HTTPException
from pypdf import PdfReader

from app.schemas.profile import (
    ProfileSummary,
    ProfileDetail,
    ConceptFocus,
    WeakSpot,
    LearningProgress,
    ProfileStats,
    ConceptDetail,
    RelatedConcept,
)
from core.tools import build_sources_from_documents, get_rag_service
from kb_builder.toc_parser import get_toc_parser

router = APIRouter()
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"


def get_memory():
    from app.core_bridge import get_memory_core
    return get_memory_core()


def _isoformat(ts):
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _serialize_concept_focus(concept_id, focus):
    return ConceptFocus(
        concept_id=concept_id,
        display_name=focus.display_name,
        mention_count=focus.mention_count,
        chapter=focus.chapter,
        last_mentioned_at=_isoformat(focus.last_mentioned_at),
        last_question_type=focus.last_question_type,
    )


def _serialize_weak_spot(spot):
    return WeakSpot(
        concept_id=spot.concept_id,
        display_name=spot.display_name,
        confidence=spot.confidence,
        evidence_count=len(spot.signals),
        clarification_count=spot.clarification_count,
        first_detected_at=_isoformat(spot.first_detected_at),
        last_triggered_at=_isoformat(spot.last_triggered_at),
        resolved_at=_isoformat(spot.resolved_at),
        resolution_note=spot.resolution_note,
    )


def _sorted_recent_concepts(profile):
    return sorted(
        profile.recent_concepts.items(),
        key=lambda item: (
            item[1].last_mentioned_at or 0.0,
            item[1].mention_count,
        ),
        reverse=True,
    )


def _build_daily_activity(memory_core, student_id: str) -> dict[str, int]:
    events = memory_core.load_events(student_id)
    counts = Counter()

    for event in events:
        timestamp = getattr(event, "timestamp", None)
        if not timestamp:
            continue
        day = datetime.fromtimestamp(float(timestamp), tz=timezone.utc).strftime("%m-%d")
        counts[day] += 1

    recent_days = sorted(counts.items())[-7:]
    return {day: count for day, count in recent_days}


@lru_cache(maxsize=1)
def _get_concept_catalog():
    catalog_path = DATA_DIR / "knowledge_graph.json"
    with open(catalog_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return {
        item["canonical_id"]: item
        for item in data.get("concepts", [])
        if item.get("canonical_id")
    }


@lru_cache(maxsize=1)
def _get_cached_toc():
    return get_toc_parser()


@lru_cache(maxsize=16)
def _get_pdf_reader(chapter_no: str):
    pdf_path = DATA_DIR / f"数据科学导论(案例版)_{chapter_no}.pdf"
    if not pdf_path.exists():
        return None
    return PdfReader(str(pdf_path))


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "")


def _normalize_lookup_text(value: str | None) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", (value or "").lower())


def _decode_distinction_payload(concept_id: str) -> dict | None:
    if not concept_id.startswith("distinction::"):
        return None

    token = concept_id.split("::", 1)[1]
    token += "=" * (-len(token) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8"))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    return payload


def _find_catalog_concept_by_label(label: str, catalog: dict[str, dict]) -> dict | None:
    target = _normalize_lookup_text(label)
    if not target:
        return None

    for concept in catalog.values():
        if _normalize_lookup_text(concept.get("display_name")) == target:
            return concept
        aliases = concept.get("aliases", [])
        if any(_normalize_lookup_text(alias) == target for alias in aliases):
            return concept
    return None


def _build_distinction_summary(labels: list[str], related_names: list[str], chapter: str | None) -> str:
    label_text = " 和 ".join(labels[:2]) if labels else "这两个概念"
    related_text = "、".join(related_names[:4]) if related_names else "相关概念"
    chapter_text = chapter or "当前课程内容"
    return (
        f"{label_text} 是一个辨析型知识点，表示你最近在重点区分它们之间的边界和适用场景。"
        f" 这类问题通常出现在 {chapter_text} 的相近概念对比里。"
        f" 你可以先抓定义差异，再看典型例子和常见混淆点。相关概念包括：{related_text}。"
    )


def _find_toc_section(concept: dict):
    toc = _get_cached_toc()
    chapter_no = concept.get("chapter")
    section_no = concept.get("section")
    display_name = _normalize_text(concept.get("display_name"))

    chapter_info = next((item for item in toc.sections if item.number == chapter_no), None)
    if chapter_info is None:
        return None, None

    section_candidates = [
        section
        for section in toc.all_sections
        if chapter_info.page <= section.page <= chapter_info.end_page
    ]

    if section_no:
        matched = next((item for item in section_candidates if item.number == section_no), None)
        if matched:
            return chapter_info, matched

    for item in section_candidates:
        title = _normalize_text(item.title)
        name = _normalize_text(item.name)
        if display_name and (display_name in title or display_name == name):
            return chapter_info, item

    return chapter_info, chapter_info


def _clean_pdf_excerpt(raw_text: str, concept: dict, section_info) -> str | None:
    if not raw_text:
        return None

    text = raw_text.replace("\x00", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None

    anchors = []
    if section_info and section_info.number and concept.get("display_name"):
        anchors.append(f"{section_info.number} {concept['display_name']}")
    if concept.get("display_name"):
        anchors.append(concept["display_name"])

    for anchor in anchors:
        index = text.find(anchor)
        if index != -1:
            text = text[index:]
            break

    return text[:360]


def _extract_textbook_excerpt_from_pdf(concept: dict) -> tuple[str | None, list[dict]]:
    chapter_info, section_info = _find_toc_section(concept)
    if chapter_info is None:
        return None, []

    reader = _get_pdf_reader(chapter_info.number)
    if reader is None:
        return None, []

    page = section_info.page if section_info else chapter_info.page
    relative_index = max(0, page - chapter_info.page)
    if relative_index >= len(reader.pages):
        return None, []

    collected = []
    for page_index in range(relative_index, min(relative_index + 2, len(reader.pages))):
        page_text = reader.pages[page_index].extract_text() or ""
        if page_text:
            collected.append(page_text)

    excerpt = _clean_pdf_excerpt(" ".join(collected), concept, section_info)
    chapter_name = chapter_info.name or concept.get("chapter") or "课程内容"
    reference = f"《{chapter_info.number} {chapter_name}》第{page}页"
    return excerpt, [{"reference": reference}]


def _build_concept_summary(concept: dict, related_concepts: list[RelatedConcept]) -> str:
    chapter = concept.get("chapter") or "课程知识图谱"
    section = concept.get("section")
    aliases = concept.get("aliases", [])
    alias_text = "、".join(aliases[:3]) if aliases else "暂无别名"
    related_text = "、".join(item.display_name for item in related_concepts[:4]) if related_concepts else "暂无关联知识点"
    section_text = f"{chapter} {section}" if section else chapter
    return (
        f"{concept['display_name']} 位于 {section_text}。"
        f" 常见检索词包括：{alias_text}。"
        f" 相关知识点有：{related_text}。"
    )


def _retrieve_textbook_excerpt_with_rag(concept: dict) -> tuple[str | None, list[dict]]:
    query = f"{concept['display_name']} 是什么"
    result = get_rag_service().retrieve(query, top_k=2)
    sources = build_sources_from_documents(result.documents)
    if not result.documents:
        return None, sources

    excerpt = re.sub(r"\s+", " ", result.documents[0].page_content).strip()
    return excerpt[:320], sources


def _retrieve_distinction_excerpt_with_rag(labels: list[str]) -> tuple[str | None, list[dict]]:
    if len(labels) < 2:
        return None, []

    query = f"{labels[0]} 和 {labels[1]} 的区别"
    result = get_rag_service().retrieve(query, top_k=2)
    sources = build_sources_from_documents(result.documents)
    if not result.documents:
        return None, sources

    excerpt = re.sub(r"\s+", " ", result.documents[0].page_content).strip()
    return excerpt[:320], sources


@router.get("/summary/{student_id}", response_model=ProfileSummary)
async def get_profile_summary(student_id: str):
    memory_core = get_memory()
    memory_core.aggregate_profile(student_id)
    profile = memory_core.get_profile(student_id)

    recent_concepts = [
        _serialize_concept_focus(concept_id, focus)
        for concept_id, focus in _sorted_recent_concepts(profile)[:5]
    ]
    pending_weak_spots = [_serialize_weak_spot(spot) for spot in profile.pending_weak_spots]
    weak_spots = [_serialize_weak_spot(spot) for spot in profile.weak_spot_candidates]

    return ProfileSummary(
        student_id=student_id,
        recent_concepts=recent_concepts,
        pending_weak_spots=pending_weak_spots,
        weak_spots=weak_spots,
        resolved_weak_spot_count=len(profile.resolved_weak_spots),
        total_overcome_weak_spots=profile.stats.get("total_resolved_weak_spots", len(profile.resolved_weak_spots)),
    )


@router.get("/detail/{student_id}", response_model=ProfileDetail)
async def get_profile_detail(student_id: str):
    memory_core = get_memory()
    memory_core.aggregate_profile(student_id)
    profile = memory_core.get_profile(student_id)

    chapter_counts = {}
    for _, focus in profile.recent_concepts.items():
        chapter = focus.chapter or "未分类"
        chapter_counts[chapter] = chapter_counts.get(chapter, 0) + focus.mention_count

    recent_concepts = [
        _serialize_concept_focus(concept_id, focus)
        for concept_id, focus in _sorted_recent_concepts(profile)
    ]
    pending_weak_spots = [_serialize_weak_spot(spot) for spot in profile.pending_weak_spots]
    weak_spots = [_serialize_weak_spot(spot) for spot in profile.weak_spot_candidates]
    resolved_weak_spots = [_serialize_weak_spot(spot) for spot in profile.resolved_weak_spots]

    return ProfileDetail(
        student_id=student_id,
        recent_concepts=recent_concepts,
        pending_weak_spots=pending_weak_spots,
        weak_spots=weak_spots,
        resolved_weak_spots=resolved_weak_spots,
        progress=LearningProgress(
            current_chapter=profile.progress.current_chapter,
            total_interactions=sum(focus.mention_count for focus in profile.recent_concepts.values()),
            concepts_explored=len(profile.recent_concepts),
        ),
        chapter_stats=chapter_counts,
        daily_activity=_build_daily_activity(memory_core, student_id),
        stats=ProfileStats(**profile.stats),
    )


@router.post("/weak-spots/{student_id}/{concept_id}/resolve")
async def resolve_weak_spot(student_id: str, concept_id: str):
    memory_core = get_memory()

    try:
        resolved_spot = memory_core.resolve_active_weak_spot(student_id, concept_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Weak spot not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail="Failed to resolve weak spot") from exc

    return {
        "message": "活跃薄弱点已移出，并记录到已克服历史",
        "resolved_weak_spot": _serialize_weak_spot(resolved_spot),
    }


@router.get("/concepts/{concept_id}", response_model=ConceptDetail)
async def get_concept_detail(concept_id: str):
    catalog = _get_concept_catalog()
    concept = catalog.get(concept_id)
    if concept_id.startswith("distinction::"):
        payload = _decode_distinction_payload(concept_id)
        if not payload:
            raise HTTPException(status_code=404, detail="Concept not found")

        labels = payload.get("labels", [])
        chapter = payload.get("chapter")
        related_ids = payload.get("related_ids", [])

        related_concepts = []
        for related_id in related_ids:
            related = catalog.get(related_id)
            if related:
                related_concepts.append(
                    RelatedConcept(
                        concept_id=related_id,
                        display_name=related.get("display_name", related_id),
                    )
                )

        if not related_concepts:
            for label in labels:
                related = _find_catalog_concept_by_label(label, catalog)
                if related:
                    related_concepts.append(
                        RelatedConcept(
                            concept_id=related["canonical_id"],
                            display_name=related.get("display_name", related["canonical_id"]),
                        )
                    )

        textbook_excerpt = _build_distinction_summary(
            labels,
            [item.display_name for item in related_concepts],
            chapter,
        )
        sources = []
        try:
            rag_excerpt, rag_sources = await asyncio.wait_for(
                run_in_threadpool(_retrieve_distinction_excerpt_with_rag, labels),
                timeout=1.8,
            )
            if rag_excerpt:
                textbook_excerpt = rag_excerpt
            if rag_sources:
                sources = rag_sources
        except Exception:
            pass

        return ConceptDetail(
            concept_id=concept_id,
            display_name=" vs ".join(labels) if labels else "概念辨析",
            chapter=chapter,
            section=None,
            aliases=labels,
            related_concepts=related_concepts,
            textbook_excerpt=textbook_excerpt,
            sources=sources,
        )

    if not concept:
        raise HTTPException(status_code=404, detail="Concept not found")

    related_concepts = []
    for related_id in concept.get("related_concepts", []):
        related = catalog.get(related_id)
        related_concepts.append(
            RelatedConcept(
                concept_id=related_id,
                display_name=(related or {}).get("display_name", related_id),
            )
        )

    textbook_excerpt = None
    sources = []

    try:
        textbook_excerpt, sources = await run_in_threadpool(
            _extract_textbook_excerpt_from_pdf,
            concept,
        )
    except Exception:
        textbook_excerpt, sources = None, []

    if not textbook_excerpt:
        try:
            textbook_excerpt, rag_sources = await asyncio.wait_for(
                run_in_threadpool(_retrieve_textbook_excerpt_with_rag, concept),
                timeout=2.5,
            )
            if rag_sources:
                sources = rag_sources
        except Exception:
            textbook_excerpt = None

    if not textbook_excerpt:
        textbook_excerpt = _build_concept_summary(concept, related_concepts)

    return ConceptDetail(
        concept_id=concept["canonical_id"],
        display_name=concept["display_name"],
        chapter=concept.get("chapter"),
        section=concept.get("section"),
        aliases=concept.get("aliases", []),
        related_concepts=related_concepts,
        textbook_excerpt=textbook_excerpt,
        sources=sources,
    )


@router.post("/aggregate/{student_id}")
async def aggregate_profile(student_id: str):
    memory_core = get_memory()
    memory_core.aggregate_profile(student_id)
    return {"message": "画像已更新", "student_id": student_id}
