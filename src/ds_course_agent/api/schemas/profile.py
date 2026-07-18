from pydantic import BaseModel, Field


class ConceptFocus(BaseModel):
    concept_id: str
    display_name: str
    mention_count: int
    chapter: str | None = None
    last_mentioned_at: str | None = None
    last_question_type: str | None = None


class WeakSpot(BaseModel):
    concept_id: str
    display_name: str
    confidence: float = Field(ge=0, le=1)
    evidence_count: int
    clarification_count: int = 0
    first_detected_at: str | None = None
    last_triggered_at: str | None = None
    resolved_at: str | None = None
    resolution_note: str | None = None


class LearningProgress(BaseModel):
    current_chapter: str | None = None
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
    chapter: str | None = None
    section: str | None = None
    aliases: list[str]
    related_concepts: list[RelatedConcept]
    textbook_excerpt: str | None = None
    sources: list[dict] = []


class ProfileSummary(BaseModel):
    student_id: str
    recent_concepts: list[ConceptFocus]
    pending_weak_spots: list[WeakSpot]
    weak_spots: list[WeakSpot]
    resolved_weak_spot_count: int = 0
    total_overcome_weak_spots: int = 0


class ProfileDetail(BaseModel):
    student_id: str
    recent_concepts: list[ConceptFocus]
    pending_weak_spots: list[WeakSpot]
    weak_spots: list[WeakSpot]
    resolved_weak_spots: list[WeakSpot]
    progress: LearningProgress
    chapter_stats: dict[str, int]
    daily_activity: dict[str, int]
    stats: ProfileStats
