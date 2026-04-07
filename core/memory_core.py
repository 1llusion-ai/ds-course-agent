"""
Memory Core 核心模块
负责学生画像读取、学习事件记录、掌握度更新与持久化
支持增量统计和滑动时间窗计算
"""
import json
import os
from typing import List, Dict, Optional, Callable
from datetime import datetime
from pathlib import Path
from collections import Counter

from core.events import (
    BaseEvent, EventType, ConceptMentionedEvent, ClarificationEvent,
    is_learning_related_event, build_concept_mentioned_event, build_clarification_event
)
from core.profile_models import (
    StudentProfile, ConceptFocus, WeakSpotCandidate, ProgressInfo
)


class MemoryCore:
    """
    记忆核心

    职责：
    1. 事件记录（追加写入，不可变）
    2. 画像读取（从磁盘加载）
    3. 批量聚合（从事件计算画像字段，支持增量）
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
        事件是不可变的，追加写入按月分片的 JSONL 文件
        """
        student_id = event.student_id
        month_key = datetime.fromtimestamp(event.timestamp).strftime("%Y_%m")
        file_path = self.events_dir / f"{student_id}_{month_key}.jsonl"

        # 追加写入
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

        # 更新缓存中的 stats
        if student_id in self._profile_cache:
            self._profile_cache[student_id].stats["total_events"] += 1

    def load_events(self, student_id: str, since: int = 0,
                    event_types: Optional[List[EventType]] = None) -> List[BaseEvent]:
        """
        加载学生事件

        Args:
            student_id: 学生ID
            since: 时间戳，只加载此之后的事件
            event_types: 只加载指定类型的事件

        Returns:
            事件列表
        """
        events = []

        # 查找所有该学生的事件文件
        for file_path in self.events_dir.glob(f"{student_id}_*.jsonl"):
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        event = BaseEvent.from_dict(data)

                        # 时间过滤
                        if event.timestamp < since:
                            continue

                        # 类型过滤
                        if event_types and event.event_type not in event_types:
                            continue

                        events.append(event)
                    except Exception as e:
                        print(f"[MemoryCore] Failed to parse event: {e}")

        # 按时间排序
        events.sort(key=lambda e: e.timestamp)
        return events

    def load_all_events(self, student_id: str, days: int = 90) -> List[BaseEvent]:
        """
        加载最近 N 天的所有事件（用于全量重算）
        """
        since = int(datetime.now().timestamp()) - days * 86400
        return self.load_events(student_id, since=since)

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

    # ========== 批量聚合接口 ==========

    def aggregate_profile(self, student_id: str, full_recalc: bool = False) -> None:
        """
        聚合事件生成/更新画像

        Args:
            student_id: 学生ID
            full_recalc: 是否全量重算（默认增量更新）
        """
        profile = self.get_profile(student_id)

        if full_recalc:
            # 全量：重置画像，加载90天所有事件
            profile = StudentProfile(student_id=student_id)
            events = self.load_all_events(student_id, days=90)
            new_events = events
        else:
            # 增量：只加载上次聚合之后的新事件
            new_events = self.load_events(student_id, since=profile.last_aggregate_time)
            events = None  # 增量模式不需要全量事件

        if not new_events:
            print(f"[MemoryCore] No new events for {student_id}, skip aggregation")
            return

        # 去重：同一事件ID只处理一次
        seen_event_ids = set()
        unique_new_events = []
        for e in new_events:
            if e.event_id not in seen_event_ids:
                seen_event_ids.add(e.event_id)
                unique_new_events.append(e)

        if len(unique_new_events) < len(new_events):
            print(f"[MemoryCore] Deduplicated {len(new_events) - len(unique_new_events)} duplicate events")
            new_events = unique_new_events

        # ===== 增量统计：mention_count =====
        # 注意：new_events 已经去重
        self._update_mention_count_incremental(profile, new_events)

        # ===== 时间窗统计：current_chapter =====
        # 需要加载最近14天全量
        recent_14d = self.load_events(
            student_id,
            since=int(datetime.now().timestamp()) - 14 * 86400,
            event_types=[EventType.CONCEPT_MENTIONED, EventType.CLARIFICATION, EventType.FOLLOW_UP]
        )
        self._update_progress(profile, recent_14d)

        # ===== 增量检测：weak_spots =====
        self._detect_weak_spots_incremental(profile, new_events)

        # ===== 更新统计 =====
        profile.stats["total_events"] = self._count_total_events(student_id)
        profile.last_aggregate_time = int(datetime.now().timestamp())
        profile.update_timestamp()

        # 保存
        self.save_profile(profile)
        print(f"[MemoryCore] Aggregated profile for {student_id}: "
              f"{len(new_events)} new events, "
              f"{len(profile.weak_spot_candidates)} weak spots, "
              f"current chapter: {profile.progress.current_chapter}")

    # ========== 聚合规则实现（可解释、可验证） ==========

    def _update_mention_count_incremental(self, profile: StudentProfile,
                                          new_events: List[BaseEvent]) -> None:
        """
        增量更新 mention_count
        维护日计数器，支持滑动窗口（30天）
        注意：new_events 应该已由调用者去重
        """
        window_days = 30
        today = int(datetime.now().timestamp()) // 86400

        # 处理新事件
        for event in new_events:
            if event.event_type != EventType.CONCEPT_MENTIONED:
                continue

            cid = event.payload.get("concept_id")
            if not cid:
                continue

            # 更新日计数器
            event_day = event.timestamp // 86400
            if event_day not in profile.daily_mention_counter:
                profile.daily_mention_counter[event_day] = {}

            if cid not in profile.daily_mention_counter[event_day]:
                profile.daily_mention_counter[event_day][cid] = 0
            profile.daily_mention_counter[event_day][cid] += 1

            # 更新 recent_concepts
            if cid not in profile.recent_concepts:
                concept_name = event.payload.get("concept_name", cid)
                chapter = event.payload.get("chapter", "")
                profile.recent_concepts[cid] = ConceptFocus(
                    concept_id=cid,
                    display_name=concept_name,
                    chapter=chapter,
                    mention_count=0,
                    first_seen=event.timestamp,
                    last_seen=event.timestamp,
                    evidence=[event.event_id],
                    confidence=1.0
                )
            else:
                cf = profile.recent_concepts[cid]
                cf.mention_count += 1
                cf.last_seen = event.timestamp
                # evidence 去重追加
                if event.event_id not in cf.evidence:
                    cf.evidence.append(event.event_id)

        # 清理过期日计数器（滑动窗口）
        cutoff_day = today - window_days
        for day in list(profile.daily_mention_counter.keys()):
            if day < cutoff_day:
                del profile.daily_mention_counter[day]

        # 重新计算当前窗口内的 mention_count
        for cid in profile.recent_concepts:
            total = sum(
                day_counts.get(cid, 0)
                for day_counts in profile.daily_mention_counter.values()
            )
            profile.recent_concepts[cid].mention_count = total

    def _update_progress(self, profile: StudentProfile,
                         learning_events: List[BaseEvent]) -> None:
        """
        更新学习进度
        只统计 CONCEPT_MENTIONED / CLARIFICATION / FOLLOW_UP
        """
        chapter_counts = Counter()

        for event in learning_events:
            chapter = event.payload.get("chapter")
            if chapter:
                chapter_counts[chapter] += 1

        if not chapter_counts:
            return

        # 取提问最多的章节作为当前章节
        top_chapter, count = chapter_counts.most_common(1)[0]
        min_evidence = 3

        if count >= min_evidence:
            old_chapter = profile.progress.current_chapter
            if old_chapter != top_chapter:
                # 章节切换，记录历史
                profile.progress.chapter_switch_history.append({
                    "from": old_chapter,
                    "to": top_chapter,
                    "timestamp": int(datetime.now().timestamp()),
                    "reason": f"最近14天内{top_chapter}提问数({count})超过阈值"
                })

            profile.progress.current_chapter = top_chapter
            profile.progress.current_chapter_confidence = min(count / 10, 1.0)  # 10次达到满置信度
            profile.progress.current_chapter_evidence = [
                e.event_id for e in learning_events
                if e.payload.get("chapter") == top_chapter
            ][:10]  # 只保留前10个证据

            # 更新 covered_chapters（累积）
            for ch in chapter_counts.keys():
                if ch not in profile.progress.covered_chapters:
                    profile.progress.covered_chapters.append(ch)

    def _detect_weak_spots_incremental(self, profile: StudentProfile,
                                       new_events: List[BaseEvent]) -> None:
        """
        增量检测薄弱点
        基于信号的置信度综合
        """
        # 按 concept_id 分组事件
        concept_events: Dict[str, List[BaseEvent]] = {}
        for event in new_events:
            if event.event_type == EventType.CONCEPT_MENTIONED:
                cid = event.payload.get("concept_id")
                if cid:
                    concept_events.setdefault(cid, []).append(event)
            elif event.event_type == EventType.CLARIFICATION:
                cid = event.payload.get("concept_id")
                if cid:
                    concept_events.setdefault(cid, []).append(event)

        for cid, events in concept_events.items():
            # 检查信号
            signals = []

            # 信号A：澄清行为（24小时内多次提及同一概念）
            clarification_events = [e for e in events if e.event_type == EventType.CLARIFICATION]
            if len(clarification_events) >= 2:
                signals.append({
                    "type": "CLARIFICATION",
                    "count": len(clarification_events),
                    "evidence": [e.event_id for e in clarification_events]
                })

            # 信号B：跨会话重复（需要加载历史判断）
            # 这里简化处理：如果该 concept 在 profile 中已存在且 mention_count > 1
            if cid in profile.recent_concepts:
                rc = profile.recent_concepts[cid]
                if rc.mention_count >= 2:
                    # 检查时间跨度
                    time_span = rc.last_seen - rc.first_seen
                    if time_span > 7 * 86400:  # 跨度超过7天
                        signals.append({
                            "type": "CROSS_SESSION_REPEAT",
                            "count": rc.mention_count,
                            "evidence": rc.evidence[-5:]  # 最近5个证据
                        })

            if not signals:
                continue

            # 计算置信度
            confidence = 0.0
            for sig in signals:
                if sig["type"] == "CLARIFICATION":
                    confidence += 0.6 + 0.1 * (sig["count"] - 2)
                elif sig["type"] == "CROSS_SESSION_REPEAT":
                    confidence += 0.5 + 0.15 * (sig["count"] - 2)

            confidence = min(confidence, 0.95)

            # 更新或创建薄弱点候选
            existing = profile.get_weak_spot(cid)
            if existing:
                # 指数移动平均更新置信度
                alpha = 0.3
                existing.confidence = (1 - alpha) * existing.confidence + alpha * confidence
                existing.signals.extend(signals)
                existing.last_updated = int(datetime.now().timestamp())
            else:
                concept = profile.recent_concepts.get(cid)
                display_name = concept.display_name if concept else cid
                parent = None
                # 尝试提取父概念（如 svm_kernel 的父概念是 svm）
                if "_" in cid:
                    parent = cid.rsplit("_", 1)[0]

                profile.weak_spot_candidates.append(WeakSpotCandidate(
                    concept_id=cid,
                    display_name=display_name,
                    parent_concept=parent,
                    signals=signals,
                    confidence=confidence,
                    first_flagged=int(datetime.now().timestamp()),
                    last_updated=int(datetime.now().timestamp())
                ))

    def _count_total_events(self, student_id: str) -> int:
        """统计学生总事件数"""
        count = 0
        for file_path in self.events_dir.glob(f"{student_id}_*.jsonl"):
            with open(file_path, "r", encoding="utf-8") as f:
                count += sum(1 for _ in f)
        return count

    # ========== 辅助接口 ==========

    def get_evidence_chain(self, student_id: str, concept_id: str) -> List[Dict]:
        """
        获取某个概念的所有证据（用于 Skill 解释为什么学生薄弱）
        """
        events = self.load_events(student_id)
        evidence = []

        for event in events:
            if event.payload.get("concept_id") == concept_id:
                evidence.append({
                    "event_id": event.event_id,
                    "timestamp": event.timestamp,
                    "type": event.event_type.value,
                    "session_id": event.session_id
                })

        return evidence

    def get_memory_stats(self, student_id: str) -> Dict:
        """获取记忆系统统计"""
        profile = self.get_profile(student_id)
        events = self.load_events(student_id)
        learning_events = [e for e in events if is_learning_related_event(e)]

        return {
            "student_id": student_id,
            "total_events": len(events),
            "learning_related_events": len(learning_events),
            "total_concepts": len(profile.recent_concepts),
            "weak_spots": len(profile.weak_spot_candidates),
            "current_chapter": profile.progress.current_chapter,
            "last_aggregate": profile.last_aggregate_time,
            "profile_age_days": (datetime.now().timestamp() - profile.created_at) // 86400
        }


# 全局单例
_memory_core: Optional[MemoryCore] = None


def get_memory_core() -> MemoryCore:
    """获取 MemoryCore 单例"""
    global _memory_core
    if _memory_core is None:
        _memory_core = MemoryCore()
    return _memory_core


# 便捷函数
def record_event(event: BaseEvent) -> None:
    """记录事件"""
    get_memory_core().record_event(event)


def get_profile(student_id: str) -> StudentProfile:
    """获取画像"""
    return get_memory_core().get_profile(student_id)


def aggregate_profile(student_id: str, full_recalc: bool = False) -> None:
    """聚合画像"""
    get_memory_core().aggregate_profile(student_id, full_recalc)
