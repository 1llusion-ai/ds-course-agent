"""
学生画像模型
定义带元数据（evidence、confidence、last_updated）的学生画像结构
"""
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class ConceptFocus:
    """最近关注概念"""
    concept_id: str
    display_name: str
    chapter: str
    mention_count: int
    first_seen: int  # unix timestamp
    last_seen: int
    evidence: List[str] = field(default_factory=list)  # event_id 列表
    confidence: float = 1.0  # mention_count 是硬事实，confidence=1

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ChapterProgress:
    """章节进度"""
    chapter: str
    first_seen: int
    last_seen: int
    question_count: int
    evidence: List[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class WeakSpotCandidate:
    """薄弱点候选"""
    concept_id: str
    display_name: str
    parent_concept: Optional[str]  # 如：核函数属于SVM
    signals: List[Dict[str, Any]] = field(default_factory=list)
    # signals 示例：
    # [{"type": "CLARIFICATION", "count": 2, "evidence": ["ev_043", "ev_046"]},
    #  {"type": "CROSS_SESSION_REPEAT", "count": 2, "evidence": ["ev_030", "ev_041"]}]
    confidence: float = 0.0
    first_flagged: int = 0
    last_updated: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class PreferenceCandidate:
    """偏好候选（低置信度，需要更多数据验证）"""
    preference_type: str  # 如：code_example_preferred
    signals: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    status: str = "insufficient_data"  # insufficient_data / confirmed / rejected

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ProgressInfo:
    """学习进度信息"""
    current_chapter: Optional[str] = None
    current_chapter_evidence: List[str] = field(default_factory=list)
    current_chapter_confidence: float = 0.0
    covered_chapters: List[str] = field(default_factory=list)
    chapter_switch_history: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class StudentProfile:
    """
    学生画像
    每个字段都包含 evidence、confidence、last_updated 元数据
    """
    student_id: str
    created_at: int = field(default_factory=lambda: int(datetime.now().timestamp()))
    last_updated: int = field(default_factory=lambda: int(datetime.now().timestamp()))
    last_aggregate_time: int = 0  # 上次聚合时间

    # ========== 硬信息：最近关注 ==========
    # concept_id -> ConceptFocus
    recent_concepts: Dict[str, ConceptFocus] = field(default_factory=dict)

    # ========== 硬信息：学习进度 ==========
    progress: ProgressInfo = field(default_factory=ProgressInfo)

    # ========== 硬信息：薄弱点候选 ==========
    weak_spot_candidates: List[WeakSpotCandidate] = field(default_factory=list)

    # ========== 偏好候选（低优先级）==========
    preference_candidates: List[PreferenceCandidate] = field(default_factory=list)

    # ========== 增量统计支持 ==========
    # 日计数器：day_timestamp -> {concept_id: count}
    daily_mention_counter: Dict[int, Dict[str, int]] = field(default_factory=dict)

    # ========== 元信息 ==========
    stats: Dict[str, Any] = field(default_factory=lambda: {
        "total_sessions": 0,
        "total_questions": 0,
        "total_events": 0,
        "first_session": None,
        "last_session": None
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

    def update_timestamp(self):
        """更新最后修改时间"""
        self.last_updated = int(datetime.now().timestamp())

    def to_dict(self) -> Dict:
        """序列化为字典"""
        return {
            "student_id": self.student_id,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "last_aggregate_time": self.last_aggregate_time,
            "recent_concepts": {
                k: v.to_dict() for k, v in self.recent_concepts.items()
            },
            "progress": self.progress.to_dict(),
            "weak_spot_candidates": [s.to_dict() for s in self.weak_spot_candidates],
            "preference_candidates": [p.to_dict() for p in self.preference_candidates],
            "daily_mention_counter": self.daily_mention_counter,
            "stats": self.stats
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "StudentProfile":
        """从字典反序列化"""
        profile = cls(student_id=data["student_id"])
        profile.created_at = data.get("created_at", profile.created_at)
        profile.last_updated = data.get("last_updated", profile.last_updated)
        profile.last_aggregate_time = data.get("last_aggregate_time", 0)

        # 恢复 recent_concepts（确保数值类型正确）
        for cid, cdata in data.get("recent_concepts", {}).items():
            cdata_copy = cdata.copy()
            # 确保数值字段类型正确
            if "mention_count" in cdata_copy:
                cdata_copy["mention_count"] = int(cdata_copy["mention_count"])
            if "first_seen" in cdata_copy:
                cdata_copy["first_seen"] = int(cdata_copy["first_seen"])
            if "last_seen" in cdata_copy:
                cdata_copy["last_seen"] = int(cdata_copy["last_seen"])
            if "confidence" in cdata_copy:
                cdata_copy["confidence"] = float(cdata_copy["confidence"])
            profile.recent_concepts[cid] = ConceptFocus(**cdata_copy)

        # 恢复 progress
        if "progress" in data:
            profile.progress = ProgressInfo(**data["progress"])

        # 恢复 weak_spot_candidates（确保数值类型正确）
        for s in data.get("weak_spot_candidates", []):
            # 确保 confidence 是浮点数
            s_copy = s.copy()
            if "confidence" in s_copy:
                s_copy["confidence"] = float(s_copy["confidence"])
            if "first_flagged" in s_copy:
                s_copy["first_flagged"] = int(s_copy["first_flagged"])
            if "last_updated" in s_copy:
                s_copy["last_updated"] = int(s_copy["last_updated"])
            profile.weak_spot_candidates.append(WeakSpotCandidate(**s_copy))

        # 恢复 preference_candidates
        profile.preference_candidates = [
            PreferenceCandidate(**p) for p in data.get("preference_candidates", [])
        ]

        # 恢复日计数器
        profile.daily_mention_counter = data.get("daily_mention_counter", {})

        # 恢复 stats
        profile.stats = data.get("stats", profile.stats)

        return profile


def create_empty_profile(student_id: str) -> StudentProfile:
    """创建空画像"""
    return StudentProfile(student_id=student_id)
