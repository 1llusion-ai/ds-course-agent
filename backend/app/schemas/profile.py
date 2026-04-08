from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional, Dict


class ConceptFocus(BaseModel):
    concept_id: str
    display_name: str
    mention_count: int
    chapter: Optional[str] = None
    last_mentioned: datetime


class WeakSpot(BaseModel):
    concept_id: str
    display_name: str
    confidence: float = Field(ge=0, le=1)
    evidence_count: int


class LearningProgress(BaseModel):
    current_chapter: Optional[str] = None
    total_interactions: int
    concepts_explored: int
    last_study_date: Optional[datetime] = None


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
