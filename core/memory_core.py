"""
Memory Core 核心模块。

职责：
1. 事件记录（追加写入）
2. 画像读取（从磁盘加载）
3. 聚合更新（按事件重建画像）
"""
import json
from typing import List, Dict, Optional
from pathlib import Path
from collections import Counter, defaultdict

from core.events import BaseEvent, EventType, build_mastery_signal_event
from core.profile_models import StudentProfile, ConceptFocus, WeakSpotCandidate


class MemoryCore:
    def __init__(self, base_dir: Optional[str] = None):
        if base_dir is None:
            base_dir = Path(__file__).parent.parent / "chat_history"

        self.base_dir = Path(base_dir)
        self.events_dir = self.base_dir / "learning_events"
        self.profiles_dir = self.base_dir / "profiles"
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self._profile_cache: Dict[str, StudentProfile] = {}

    # ========== 事件记录 ==========

    def record_event(self, event: BaseEvent) -> None:
        student_id = event.student_id
        file_path = self.events_dir / f"{student_id}_events.jsonl"

        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

        if student_id in self._profile_cache:
            self._profile_cache[student_id].stats["total_questions"] += 1

    def load_events(
        self,
        student_id: str,
        event_types: Optional[List[EventType]] = None,
    ) -> List[BaseEvent]:
        events: List[BaseEvent] = []
        file_path = self.events_dir / f"{student_id}_events.jsonl"

        if not file_path.exists():
            return events

        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    event = BaseEvent.from_dict(data)
                    if event_types and event.event_type not in event_types:
                        continue
                    events.append(event)
                except Exception as e:
                    print(f"[MemoryCore] Failed to parse event: {e}")

        return events

    # ========== 画像读取 ==========

    def get_profile(self, student_id: str) -> StudentProfile:
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
        profile_path = self.profiles_dir / f"{profile.student_id}.json"
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2)

        self._profile_cache[profile.student_id] = profile

    # ========== 聚合 ==========

    def aggregate_profile(self, student_id: str) -> None:
        profile = self.get_profile(student_id)
        events = self.load_events(student_id)

        if not events:
            return

        seen_event_ids = set()
        unique_events: List[BaseEvent] = []
        for event in events:
            if event.event_id in seen_event_ids:
                continue
            seen_event_ids.add(event.event_id)
            unique_events.append(event)

        unique_events.sort(key=self._event_timestamp)

        profile.recent_concepts = {}
        profile.progress.current_chapter = None
        profile.progress.covered_chapters = []
        profile.pending_weak_spots = []
        profile.weak_spot_candidates = []
        profile.resolved_weak_spots = []

        self._update_recent_concepts(profile, unique_events)
        self._update_progress(profile, unique_events)
        self._detect_weak_spots(profile, unique_events)

        profile.stats["total_questions"] = len(unique_events)
        profile.stats["total_concepts"] = len(profile.recent_concepts)
        profile.stats["pending_weak_spots"] = len(profile.pending_weak_spots)
        profile.stats["active_weak_spots"] = len(profile.weak_spot_candidates)
        profile.stats["resolved_weak_spots"] = len(profile.resolved_weak_spots)
        profile.stats["total_resolved_weak_spots"] = len(profile.resolved_weak_spots)

        self.save_profile(profile)

    # ========== 聚合规则 ==========

    def _event_timestamp(self, event: BaseEvent) -> float:
        try:
            return float(getattr(event, "timestamp", 0.0) or 0.0)
        except Exception:
            return 0.0

    def _update_recent_concepts(self, profile: StudentProfile, events: List[BaseEvent]) -> None:
        for event in events:
            if event.event_type != EventType.CONCEPT_MENTIONED:
                continue

            payload = getattr(event, "payload", {}) or {}
            concept_id = payload.get("concept_id")
            if not concept_id or concept_id == "general_question":
                continue

            concept_name = payload.get("concept_name") or concept_id
            chapter = payload.get("chapter") or ""
            question_type = payload.get("question_type")
            ts = self._event_timestamp(event)

            if concept_id not in profile.recent_concepts:
                profile.recent_concepts[concept_id] = ConceptFocus(
                    concept_id=concept_id,
                    display_name=concept_name,
                    chapter=chapter,
                    mention_count=1,
                    evidence=[event.event_id],
                    first_mentioned_at=ts,
                    last_mentioned_at=ts,
                    last_question_type=question_type,
                )
                continue

            focus = profile.recent_concepts[concept_id]
            focus.mention_count += 1
            if event.event_id not in focus.evidence:
                focus.evidence.append(event.event_id)
            if ts and (focus.last_mentioned_at is None or ts >= focus.last_mentioned_at):
                focus.last_mentioned_at = ts
                if question_type:
                    focus.last_question_type = question_type
            if focus.first_mentioned_at is None or (ts and ts < focus.first_mentioned_at):
                focus.first_mentioned_at = ts

    def _update_progress(self, profile: StudentProfile, events: List[BaseEvent]) -> None:
        chapter_counts = Counter()

        for event in events:
            if event.event_type != EventType.CONCEPT_MENTIONED:
                continue
            chapter = (getattr(event, "payload", {}) or {}).get("chapter")
            if chapter:
                chapter_counts[chapter] += 1

        if not chapter_counts:
            return

        top_chapter, count = chapter_counts.most_common(1)[0]
        if count >= 2:
            profile.progress.current_chapter = top_chapter

        profile.progress.covered_chapters = list(chapter_counts.keys())

    def _compute_weak_spot_confidence(self, clarification_count: int) -> float:
        return min(0.55 + 0.12 * max(clarification_count - 2, 0), 0.95)

    def _build_weak_spot(
        self,
        profile: StudentProfile,
        concept_id: str,
        clarification_count: int,
        signals: List[Dict],
        first_detected_at: Optional[float],
        last_triggered_at: Optional[float],
        resolved_at: Optional[float] = None,
        resolution_note: Optional[str] = None,
    ) -> WeakSpotCandidate:
        concept = profile.recent_concepts.get(concept_id)
        display_name = concept.display_name if concept else concept_id
        parent = concept_id.rsplit("_", 1)[0] if "_" in concept_id else None

        return WeakSpotCandidate(
            concept_id=concept_id,
            display_name=display_name,
            parent_concept=parent,
            signals=signals,
            confidence=self._compute_weak_spot_confidence(clarification_count),
            clarification_count=clarification_count,
            first_detected_at=first_detected_at,
            last_triggered_at=last_triggered_at,
            resolved_at=resolved_at,
            resolution_note=resolution_note,
        )

    def _detect_weak_spots(self, profile: StudentProfile, events: List[BaseEvent]) -> None:
        grouped_events: Dict[str, List[BaseEvent]] = defaultdict(list)

        for event in events:
            payload = getattr(event, "payload", {}) or {}
            concept_id = payload.get("concept_id")
            if not concept_id or concept_id == "general_question":
                continue
            grouped_events[concept_id].append(event)

        pending_spots: List[WeakSpotCandidate] = []
        active_spots: List[WeakSpotCandidate] = []
        resolved_spots: List[WeakSpotCandidate] = []

        for concept_id, concept_events in grouped_events.items():
            concept_events.sort(key=self._event_timestamp)
            cycle: Optional[Dict] = None

            for event in concept_events:
                timestamp = self._event_timestamp(event)
                payload = getattr(event, "payload", {}) or {}

                if event.event_type == EventType.CLARIFICATION:
                    if cycle is None:
                        cycle = {
                            "clarification_count": 0,
                            "first_detected_at": timestamp,
                            "last_triggered_at": timestamp,
                            "signals": [],
                        }

                    cycle["clarification_count"] += 1
                    cycle["last_triggered_at"] = timestamp
                    cycle["signals"].append(
                        {
                            "type": "CLARIFICATION",
                            "event_id": event.event_id,
                            "clarification_type": payload.get("clarification_type"),
                            "timestamp": timestamp,
                        }
                    )
                    continue

                if event.event_type == EventType.MASTERY_SIGNAL:
                    if cycle and cycle["clarification_count"] >= 2:
                        resolved_spots.append(
                            self._build_weak_spot(
                                profile,
                                concept_id=concept_id,
                                clarification_count=cycle["clarification_count"],
                                signals=cycle["signals"],
                                first_detected_at=cycle["first_detected_at"],
                                last_triggered_at=cycle["last_triggered_at"],
                                resolved_at=timestamp,
                                resolution_note=payload.get("signal_type"),
                            )
                        )
                    cycle = None

            if cycle:
                target = (
                    active_spots
                    if cycle["clarification_count"] >= 2
                    else pending_spots
                )
                target.append(
                    self._build_weak_spot(
                        profile,
                        concept_id=concept_id,
                        clarification_count=cycle["clarification_count"],
                        signals=cycle["signals"],
                        first_detected_at=cycle["first_detected_at"],
                        last_triggered_at=cycle["last_triggered_at"],
                    )
                )

        pending_spots.sort(key=lambda item: (item.last_triggered_at or 0.0, item.confidence), reverse=True)
        active_spots.sort(key=lambda item: (item.last_triggered_at or 0.0, item.confidence), reverse=True)
        resolved_spots.sort(key=lambda item: (item.resolved_at or 0.0, item.last_triggered_at or 0.0), reverse=True)
        profile.pending_weak_spots = pending_spots
        profile.weak_spot_candidates = active_spots
        profile.resolved_weak_spots = resolved_spots

    # ========== 辅助接口 ==========

    def get_evidence_chain(self, student_id: str, concept_id: str) -> List[Dict]:
        events = self.load_events(student_id)
        evidence = []

        for event in events:
            payload = getattr(event, "payload", {}) or {}
            if payload.get("concept_id") != concept_id:
                continue
            event_type = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
            evidence.append(
                {
                    "event_id": event.event_id,
                    "type": event_type,
                    "session_id": event.session_id,
                    "timestamp": self._event_timestamp(event),
                }
            )

        return evidence

    def get_memory_stats(self, student_id: str) -> Dict:
        profile = self.get_profile(student_id)
        events = self.load_events(student_id)
        return {
            "student_id": student_id,
            "total_events": len(events),
            "total_concepts": len(profile.recent_concepts),
            "weak_spots": len(profile.weak_spot_candidates),
            "resolved_weak_spots": len(profile.resolved_weak_spots),
            "current_chapter": profile.progress.current_chapter,
        }

    def resolve_active_weak_spot(
        self,
        student_id: str,
        concept_id: str,
        session_id: str = "profile_manual_action",
        signal_type: str = "manual_resolve",
    ) -> WeakSpotCandidate:
        self.aggregate_profile(student_id)
        profile = self.get_profile(student_id)
        weak_spot = profile.get_weak_spot(concept_id)

        if weak_spot is None:
            raise KeyError(concept_id)

        source_event_id = next(
            (
                signal.get("event_id")
                for signal in reversed(weak_spot.signals)
                if signal.get("event_id")
            ),
            f"manual_anchor::{concept_id}",
        )

        mastery_event = build_mastery_signal_event(
            session_id=session_id,
            student_id=student_id,
            concept_id=concept_id,
            source_event_id=source_event_id,
            signal_type=signal_type,
        )
        self.record_event(mastery_event)
        self.aggregate_profile(student_id)

        updated_profile = self.get_profile(student_id)
        resolved_spot = updated_profile.get_resolved_weak_spot(concept_id)
        if resolved_spot is None:
            raise RuntimeError(f"Failed to resolve weak spot: {concept_id}")

        return resolved_spot


_memory_core: Optional[MemoryCore] = None


def get_memory_core() -> MemoryCore:
    global _memory_core
    if _memory_core is None:
        _memory_core = MemoryCore()
    return _memory_core


def record_event(event: BaseEvent) -> None:
    get_memory_core().record_event(event)


def get_profile(student_id: str) -> StudentProfile:
    return get_memory_core().get_profile(student_id)


def aggregate_profile(student_id: str) -> None:
    get_memory_core().aggregate_profile(student_id)
