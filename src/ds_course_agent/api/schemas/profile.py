from pydantic import BaseModel, Field
from typing import List, Optional, Dict


class ConceptFocus(BaseModel):
    concept_id: str
    display_name: str
    mention_count: int
    chapter: Optional[str] = None
    last_mentioned_at: Optional[str] = None
    last_question_type: Optional[str] = None


class WeakSpot(BaseModel):
    concept_id: str
    display_name: str
    confidence: float = Field(ge=0, le=1)
    evidence_count: int
    clarification_count: int = 0
    first_detected_at: Optional[str] = None
    last_triggered_at: Optional[str] = None
    resolved_at: Optional[str] = None
    resolution_note: Optional[str] = None


class LearningProgress(BaseModel):
    current_chapter: Optional[str] = None
    total_interactions: int
    concepts_explored: int


class ProfileStats(BaseModel):
    total_questions: int = 0
    total_concepts: int = 0
    pending_weak_spots: int = 0
    active_weak_spots: int = 0
    resolved_weak_spots: int = 0
    total_resolved_weak_spots: int = 0


class RelatedConcept(BaseModel):
    concept_id: str
    display_name: str


class ConceptDetail(BaseModel):
    concept_id: str
    display_name: str
    chapter: Optional[str] = None
    section: Optional[str] = None
    aliases: List[str]
    related_concepts: List[RelatedConcept]
    textbook_excerpt: Optional[str] = None
    sources: List[dict] = []


class ProfileSummary(BaseModel):
    student_id: str
    recent_concepts: List[ConceptFocus]
    pending_weak_spots: List[WeakSpot]
    weak_spots: List[WeakSpot]
    resolved_weak_spot_count: int = 0
    total_overcome_weak_spots: int = 0


class ProfileDetail(BaseModel):
    student_id: str
    recent_concepts: List[ConceptFocus]
    pending_weak_spots: List[WeakSpot]
    weak_spots: List[WeakSpot]
    resolved_weak_spots: List[WeakSpot]
    progress: LearningProgress
    chapter_stats: Dict[str, int]
    daily_activity: Dict[str, int]
    stats: ProfileStats
