from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional, Dict


class ConceptFocus(BaseModel):
    concept_id: str
    display_name: str
    mention_count: int
    chapter: Optional[str] = None
    # 注意：profile_models 中已移除时间戳，如需时间信息需从事件记录计算
    # last_mentioned: datetime = None  # 暂不返回，避免语义不准确


class WeakSpot(BaseModel):
    concept_id: str
    display_name: str
    confidence: float = Field(ge=0, le=1)
    evidence_count: int


class LearningProgress(BaseModel):
    current_chapter: Optional[str] = None
    total_interactions: int
    concepts_explored: int
    # 注意：profile_models 中已移除时间戳，如需时间信息需从事件记录计算
    # last_study_date: Optional[datetime] = None  # 暂不返回，避免语义不准确


class ProfileSummary(BaseModel):
    student_id: str
    recent_concepts: List[ConceptFocus]
    weak_spots: List[WeakSpot]


class ProfileDetail(BaseModel):
    student_id: str
    recent_concepts: List[ConceptFocus]
    weak_spots: List[WeakSpot]
    progress: LearningProgress
    chapter_stats: Dict[str, int]
    daily_activity: Dict[str, int]
