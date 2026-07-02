"""
学生画像模型。

画像分成三层：
1. 最近关注的知识点：按最近一次聊到的时间排序，同时保留累计提及次数。
2. 活跃薄弱点：当前仍需要巩固的概念。
3. 已克服薄弱点：历史上出现过、后来被确认理解的概念。
"""
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field, asdict


@dataclass
class ConceptFocus:
    """最近关注概念。"""

    concept_id: str
    display_name: str
    chapter: str
    mention_count: int = 0
    evidence: List[str] = field(default_factory=list)
    first_mentioned_at: Optional[float] = None
    last_mentioned_at: Optional[float] = None
    last_question_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WeakSpotCandidate:
    """薄弱点记录。活跃态和已克服态都复用这一结构。"""

    concept_id: str
    display_name: str
    parent_concept: Optional[str] = None
    signals: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    clarification_count: int = 0
    first_detected_at: Optional[float] = None
    last_triggered_at: Optional[float] = None
    resolved_at: Optional[float] = None
    resolution_note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProgressInfo:
    """学习进度信息。"""

    current_chapter: Optional[str] = None
    covered_chapters: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StudentProfile:
    """学生画像。"""

    student_id: str
    recent_concepts: Dict[str, ConceptFocus] = field(default_factory=dict)
    progress: ProgressInfo = field(default_factory=ProgressInfo)
    pending_weak_spots: List[WeakSpotCandidate] = field(default_factory=list)
    weak_spot_candidates: List[WeakSpotCandidate] = field(default_factory=list)
    resolved_weak_spots: List[WeakSpotCandidate] = field(default_factory=list)
    stats: Dict[str, Any] = field(
        default_factory=lambda: {
            "total_questions": 0,
            "total_concepts": 0,
            "pending_weak_spots": 0,
            "active_weak_spots": 0,
            "resolved_weak_spots": 0,
            "total_resolved_weak_spots": 0,
        }
    )

    def get_pending_weak_spot(self, concept_id: str) -> Optional[WeakSpotCandidate]:
        for spot in self.pending_weak_spots:
            if spot.concept_id == concept_id:
                return spot
        return None

    def get_weak_spot(self, concept_id: str) -> Optional[WeakSpotCandidate]:
        for spot in self.weak_spot_candidates:
            if spot.concept_id == concept_id:
                return spot
        return None

    def get_resolved_weak_spot(self, concept_id: str) -> Optional[WeakSpotCandidate]:
        for spot in self.resolved_weak_spots:
            if spot.concept_id == concept_id:
                return spot
        return None

    def get_concept_focus(self, concept_id: str) -> Optional[ConceptFocus]:
        return self.recent_concepts.get(concept_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "student_id": self.student_id,
            "recent_concepts": {
                concept_id: focus.to_dict()
                for concept_id, focus in self.recent_concepts.items()
            },
            "progress": self.progress.to_dict(),
            "pending_weak_spots": [spot.to_dict() for spot in self.pending_weak_spots],
            "weak_spot_candidates": [spot.to_dict() for spot in self.weak_spot_candidates],
            "resolved_weak_spots": [spot.to_dict() for spot in self.resolved_weak_spots],
            "stats": self.stats,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StudentProfile":
        profile = cls(student_id=data["student_id"])

        for cid, cdata in data.get("recent_concepts", {}).items():
            cdata_copy = cdata.copy()
            if "mention_count" in cdata_copy:
                cdata_copy["mention_count"] = int(cdata_copy["mention_count"])
            for field_name in ("first_mentioned_at", "last_mentioned_at"):
                if field_name in cdata_copy and cdata_copy[field_name] is not None:
                    cdata_copy[field_name] = float(cdata_copy[field_name])
            profile.recent_concepts[cid] = ConceptFocus(**cdata_copy)

        if "progress" in data:
            profile.progress = ProgressInfo(**data["progress"])

        for field_name, target in (
            ("pending_weak_spots", profile.pending_weak_spots),
            ("weak_spot_candidates", profile.weak_spot_candidates),
            ("resolved_weak_spots", profile.resolved_weak_spots),
        ):
            for raw in data.get(field_name, []):
                item = raw.copy()
                for numeric_key in (
                    "confidence",
                    "first_detected_at",
                    "last_triggered_at",
                    "resolved_at",
                ):
                    if item.get(numeric_key) is not None:
                        item[numeric_key] = float(item[numeric_key])
                if "clarification_count" in item:
                    item["clarification_count"] = int(item["clarification_count"])
                target.append(WeakSpotCandidate(**item))

        profile.stats = {**profile.stats, **data.get("stats", {})}
        return profile


def create_empty_profile(student_id: str) -> StudentProfile:
    return StudentProfile(student_id=student_id)
