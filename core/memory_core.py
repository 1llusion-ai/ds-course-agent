"""
Memory Core 核心模块（简化版）
移除了时间戳和滑动窗口，只保留核心统计
"""
import json
import os
from typing import List, Dict, Optional
from pathlib import Path
from collections import Counter

from core.events import (
    BaseEvent, EventType, ConceptMentionedEvent, ClarificationEvent,
    build_concept_mentioned_event, build_clarification_event
)
from core.profile_models import (
    StudentProfile, ConceptFocus, WeakSpotCandidate, ProgressInfo
)


class MemoryCore:
    """
    记忆核心（简化版）

    职责：
    1. 事件记录（追加写入）
    2. 画像读取（从磁盘加载）
    3. 聚合更新（增量统计）
    """

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir is None:
            base_dir = Path(__file__).parent.parent / "chat_history"

        self.base_dir = Path(base_dir)
        self.events_dir = self.base_dir / "learning_events"
        self.profiles_dir = self.base_dir / "profiles"

        # 创建目录
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

        # 缓存
        self._profile_cache: Dict[str, StudentProfile] = {}

    # ========== 事件记录接口 ==========

    def record_event(self, event: BaseEvent) -> None:
        """
        记录学习事件
        事件是不可变的，追加写入 JSONL 文件
        """
        student_id = event.student_id
        file_path = self.events_dir / f"{student_id}_events.jsonl"

        # 追加写入
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

        # 更新缓存中的 stats
        if student_id in self._profile_cache:
            self._profile_cache[student_id].stats["total_questions"] += 1

    def load_events(self, student_id: str,
                    event_types: Optional[List[EventType]] = None) -> List[BaseEvent]:
        """
        加载学生事件

        Args:
            student_id: 学生ID
            event_types: 只加载指定类型的事件

        Returns:
            事件列表
        """
        events = []
        file_path = self.events_dir / f"{student_id}_events.jsonl"

        if not file_path.exists():
            return events

        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    event = BaseEvent.from_dict(data)

                    # 类型过滤
                    if event_types and event.event_type not in event_types:
                        continue

                    events.append(event)
                except Exception as e:
                    print(f"[MemoryCore] Failed to parse event: {e}")

        return events

    # ========== 画像读取接口 ==========

    def get_profile(self, student_id: str) -> StudentProfile:
        """
        获取学生画像（带缓存）
        如果画像不存在，创建空画像
        """
        if student_id in self._profile_cache:
            return self._profile_cache[student_id]

        profile_path = self.profiles_dir / f"{student_id}.json"

        if profile_path.exists():
            with open(profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            profile = StudentProfile.from_dict(data)
        else:
            profile = StudentProfile(student_id=student_id)

        self._profile_cache[student_id] = profile
        return profile

    def save_profile(self, profile: StudentProfile) -> None:
        """保存画像到磁盘"""
        profile_path = self.profiles_dir / f"{profile.student_id}.json"

        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2)

        # 更新缓存
        self._profile_cache[profile.student_id] = profile

    # ========== 聚合接口 ==========

    def aggregate_profile(self, student_id: str) -> None:
        """
        聚合事件生成/更新画像
        重新计算所有统计（从0开始）
        """
        profile = self.get_profile(student_id)

        # 加载所有事件
        events = self.load_events(student_id)

        if not events:
            return

        # 去重：同一事件ID只处理一次
        seen_event_ids = set()
        unique_events = []
        for e in events:
            if e.event_id not in seen_event_ids:
                seen_event_ids.add(e.event_id)
                unique_events.append(e)

        # 重置计数（重新计算）- 同时清除缓存中的旧数据
        profile.recent_concepts = {}
        profile.progress.covered_chapters = []

        # 更新 mention_count
        self._update_mention_count(profile, unique_events)

        # 更新学习进度
        self._update_progress(profile, unique_events)

        # 检测薄弱点
        self._detect_weak_spots(profile, unique_events)

        # 更新统计
        profile.stats["total_questions"] = len(events)
        profile.stats["total_concepts"] = len(profile.recent_concepts)

        # 保存
        self.save_profile(profile)

    # ========== 聚合规则实现 ==========

    def _update_mention_count(self, profile: StudentProfile,
                              events: List[BaseEvent]) -> None:
        """
        更新 mention_count
        累计统计，不清除过期数据
        """
        for event in events:
            if event.event_type != EventType.CONCEPT_MENTIONED:
                continue

            cid = event.payload.get("concept_id")
            if not cid:
                continue

            # 更新 recent_concepts
            if cid not in profile.recent_concepts:
                concept_name = event.payload.get("concept_name", cid)
                chapter = event.payload.get("chapter", "")
                profile.recent_concepts[cid] = ConceptFocus(
                    concept_id=cid,
                    display_name=concept_name,
                    chapter=chapter,
                    mention_count=1,
                    evidence=[event.event_id]
                )
            else:
                cf = profile.recent_concepts[cid]
                cf.mention_count += 1
                # evidence 去重追加
                if event.event_id not in cf.evidence:
                    cf.evidence.append(event.event_id)

    def _update_progress(self, profile: StudentProfile,
                         events: List[BaseEvent]) -> None:
        """
        更新学习进度
        只统计 CONCEPT_MENTIONED / CLARIFICATION
        """
        chapter_counts = Counter()

        for event in events:
            chapter = event.payload.get("chapter")
            if chapter:
                chapter_counts[chapter] += 1

        if not chapter_counts:
            return

        # 取提问最多的章节作为当前章节
        top_chapter, count = chapter_counts.most_common(1)[0]
        min_evidence = 2  # 最少2次提问才算

        if count >= min_evidence:
            profile.progress.current_chapter = top_chapter

            # 更新 covered_chapters（累积）
            for ch in chapter_counts.keys():
                if ch not in profile.progress.covered_chapters:
                    profile.progress.covered_chapters.append(ch)

    def _detect_weak_spots(self, profile: StudentProfile,
                           events: List[BaseEvent]) -> None:
        """
        检测薄弱点
        基于澄清信号（同一概念多次追问）
        """
        # 按 concept_id 分组统计
        concept_clarifications: Dict[str, int] = {}

        for event in events:
            if event.event_type == EventType.CLARIFICATION:
                cid = event.payload.get("concept_id")
                if cid:
                    concept_clarifications[cid] = concept_clarifications.get(cid, 0) + 1

        for cid, clarification_count in concept_clarifications.items():
            if clarification_count < 2:
                continue

            # 计算置信度
            confidence = min(0.5 + 0.2 * (clarification_count - 2), 0.9)

            # 更新或创建薄弱点候选
            existing = profile.get_weak_spot(cid)
            if existing:
                existing.confidence = max(existing.confidence, confidence)
            else:
                concept = profile.recent_concepts.get(cid)
                display_name = concept.display_name if concept else cid
                parent = None
                if "_" in cid:
                    parent = cid.rsplit("_", 1)[0]

                profile.weak_spot_candidates.append(WeakSpotCandidate(
                    concept_id=cid,
                    display_name=display_name,
                    parent_concept=parent,
                    signals=[{"type": "CLARIFICATION", "count": clarification_count}],
                    confidence=confidence
                ))

    # ========== 辅助接口 ==========

    def get_evidence_chain(self, student_id: str, concept_id: str) -> List[Dict]:
        """
        获取某个概念的所有证据
        """
        events = self.load_events(student_id)
        evidence = []

        for event in events:
            if event.payload.get("concept_id") == concept_id:
                evidence.append({
                    "event_id": event.event_id,
                    "type": event.event_type.value,
                    "session_id": event.session_id
                })

        return evidence

    def get_memory_stats(self, student_id: str) -> Dict:
        """获取记忆系统统计"""
        profile = self.get_profile(student_id)
        events = self.load_events(student_id)

        return {
            "student_id": student_id,
            "total_events": len(events),
            "total_concepts": len(profile.recent_concepts),
            "weak_spots": len(profile.weak_spot_candidates),
            "current_chapter": profile.progress.current_chapter
        }


# 全局单例
_memory_core: Optional[MemoryCore] = None


def get_memory_core() -> MemoryCore:
    """获取 MemoryCore 单例"""
    global _memory_core
    if _memory_core is None:
        _memory_core = MemoryCore()
    return _memory_core


def record_event(event: BaseEvent) -> None:
    """记录事件"""
    get_memory_core().record_event(event)


def get_profile(student_id: str) -> StudentProfile:
    """获取画像"""
    return get_memory_core().get_profile(student_id)


def aggregate_profile(student_id: str) -> None:
    """聚合画像"""
    get_memory_core().aggregate_profile(student_id)
