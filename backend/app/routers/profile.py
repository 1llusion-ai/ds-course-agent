from fastapi import APIRouter, HTTPException
from datetime import datetime

from app.schemas.profile import (
    ProfileSummary, ProfileDetail,
    ConceptFocus, WeakSpot, LearningProgress
)

router = APIRouter()


def get_memory():
    from app.core_bridge import get_memory_core
    return get_memory_core()


@router.get("/summary/{student_id}", response_model=ProfileSummary)
async def get_profile_summary(student_id: str):
    """获取画像摘要（用于聊天页）"""
    memory_core = get_memory()

    # 触发聚合
    memory_core.aggregate_profile(student_id)
    profile = memory_core.get_profile(student_id)

    # 转换近期概念
    recent_concepts = [
        ConceptFocus(
            concept_id=cid,
            display_name=cf.display_name,
            mention_count=cf.mention_count,
            chapter=cf.chapter,
            last_mentioned=datetime.now()
        )
        for cid, cf in list(profile.recent_concepts.items())[:5]
    ]

    # 转换薄弱点
    weak_spots = [
        WeakSpot(
            concept_id=ws.concept_id,
            display_name=ws.display_name,
            confidence=ws.confidence,
            evidence_count=len(ws.evidence)
        )
        for ws in profile.weak_spot_candidates
        if ws.confidence > 0.5
    ]

    return ProfileSummary(
        student_id=student_id,
        recent_concepts=recent_concepts,
        weak_spots=weak_spots
    )


@router.get("/detail/{student_id}", response_model=ProfileDetail)
async def get_profile_detail(student_id: str):
    """获取完整画像详情"""
    memory_core = get_memory()
    memory_core.aggregate_profile(student_id)
    profile = memory_core.get_profile(student_id)

    # 构建章节统计
    chapter_counts = {}
    for cf in profile.recent_concepts.values():
        ch = cf.chapter or "未分类"
        chapter_counts[ch] = chapter_counts.get(ch, 0) + cf.mention_count

    recent_concepts = [
        ConceptFocus(
            concept_id=cid,
            display_name=cf.display_name,
            mention_count=cf.mention_count,
            chapter=cf.chapter,
            last_mentioned=datetime.now()
        )
        for cid, cf in profile.recent_concepts.items()
    ]

    weak_spots = [
        WeakSpot(
            concept_id=ws.concept_id,
            display_name=ws.display_name,
            confidence=ws.confidence,
            evidence_count=len(ws.evidence)
        )
        for ws in profile.weak_spot_candidates
    ]

    return ProfileDetail(
        student_id=student_id,
        recent_concepts=recent_concepts,
        weak_spots=weak_spots,
        progress=LearningProgress(
            current_chapter=profile.progress.current_chapter,
            total_interactions=sum(cf.mention_count for cf in profile.recent_concepts.values()),
            concepts_explored=len(profile.recent_concepts),
            last_study_date=datetime.now()
        ),
        chapter_stats=chapter_counts,
        daily_activity={}
    )


@router.post("/aggregate/{student_id}")
async def aggregate_profile(student_id: str):
    """手动触发画像聚合"""
    memory_core = get_memory()
    memory_core.aggregate_profile(student_id)
    return {"message": "画像已更新", "student_id": student_id}
