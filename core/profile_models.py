"""
学生画像模型（简化版）
移除了时间戳，只保留核心统计
"""
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field, asdict


@dataclass
class ConceptFocus:
    """最近关注概念"""
    concept_id: str
    display_name: str
    chapter: str
    mention_count: int = 0
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class WeakSpotCandidate:
    """薄弱点候选"""
    concept_id: str
    display_name: str
    parent_concept: Optional[str] = None
    signals: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ProgressInfo:
    """学习进度信息"""
    current_chapter: Optional[str] = None
    covered_chapters: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class StudentProfile:
    """学生画像（简化版）"""
    student_id: str

    # 最近关注概念: concept_id -> ConceptFocus
    recent_concepts: Dict[str, ConceptFocus] = field(default_factory=dict)

    # 学习进度
    progress: ProgressInfo = field(default_factory=ProgressInfo)

    # 薄弱点候选
    weak_spot_candidates: List[WeakSpotCandidate] = field(default_factory=list)

    # 统计
    stats: Dict[str, Any] = field(default_factory=lambda: {
        "total_questions": 0,
        "total_concepts": 0
    })

    def get_weak_spot(self, concept_id: str) -> Optional[WeakSpotCandidate]:
        """获取指定概念的薄弱点候选"""
        for spot in self.weak_spot_candidates:
            if spot.concept_id == concept_id:
                return spot
        return None

    def get_concept_focus(self, concept_id: str) -> Optional[ConceptFocus]:
        """获取指定概念的关注信息"""
        return self.recent_concepts.get(concept_id)

    def to_dict(self) -> Dict:
        """序列化为字典"""
        return {
            "student_id": self.student_id,
            "recent_concepts": {
                k: v.to_dict() for k, v in self.recent_concepts.items()
            },
            "progress": self.progress.to_dict(),
            "weak_spot_candidates": [s.to_dict() for s in self.weak_spot_candidates],
            "stats": self.stats
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "StudentProfile":
        """从字典反序列化"""
        profile = cls(student_id=data["student_id"])

        # 恢复 recent_concepts
        for cid, cdata in data.get("recent_concepts", {}).items():
            cdata_copy = cdata.copy()
            # 确保数值字段类型正确
            if "mention_count" in cdata_copy:
                cdata_copy["mention_count"] = int(cdata_copy["mention_count"])
            profile.recent_concepts[cid] = ConceptFocus(**cdata_copy)

        # 恢复 progress
        if "progress" in data:
            profile.progress = ProgressInfo(**data["progress"])

        # 恢复 weak_spot_candidates
        for s in data.get("weak_spot_candidates", []):
            s_copy = s.copy()
            if "confidence" in s_copy:
                s_copy["confidence"] = float(s_copy["confidence"])
            profile.weak_spot_candidates.append(WeakSpotCandidate(**s_copy))

        # 恢复 stats
        profile.stats = data.get("stats", profile.stats)

        return profile


def create_empty_profile(student_id: str) -> StudentProfile:
    """创建空画像"""
    return StudentProfile(student_id=student_id)
