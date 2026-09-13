import tempfile
from datetime import datetime, timedelta, timezone

from ds_course_agent.teaching.learning_events import (
    build_clarification_event,
    build_concept_mentioned_event,
    build_mastery_signal_event,
)
from ds_course_agent.teaching.memory_core import MemoryCore


def test_profile_window_rebuilds_all_profile_signals_from_in_range_events():
    with tempfile.TemporaryDirectory() as temp_dir:
        memory = MemoryCore(base_dir=temp_dir)
        now = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)

        old_event = build_concept_mentioned_event(
            session_id="sess_window",
            student_id="student_window",
            concept_id="old_concept",
            concept_name="历史概念",
            chapter="第1章",
            question_type="概念理解",
            matched_score=0.9,
            raw_question="历史概念是什么？",
        )
        old_event.timestamp = (now - timedelta(days=7)).timestamp()

        recent_event = build_concept_mentioned_event(
            session_id="sess_window",
            student_id="student_window",
            concept_id="recent_concept",
            concept_name="近期概念",
            chapter="第6章",
            question_type="概念理解",
            matched_score=0.9,
            raw_question="近期概念是什么？",
        )
        recent_event.timestamp = (now - timedelta(days=6)).timestamp()
        clarification = build_clarification_event(
            session_id="sess_window",
            student_id="student_window",
            concept_id="recent_concept",
            parent_event_id=recent_event.event_id,
            clarification_type="simplify_request",
        )
        clarification.timestamp = now.timestamp()

        memory.record_events((old_event, recent_event, clarification))
        memory.aggregate_profile("student_window")
        snapshot = memory.get_profile_window("student_window", 7, now=now.timestamp())

        assert set(snapshot.profile.recent_concepts) == {"recent_concept"}
        assert snapshot.profile.progress.covered_chapters == ["第6章"]
        assert [spot.concept_id for spot in snapshot.profile.pending_weak_spots] == ["recent_concept"]
        assert snapshot.profile.stats["total_questions"] == 2
        assert list(snapshot.daily_activity) == [
            "2026-09-07",
            "2026-09-08",
            "2026-09-09",
            "2026-09-10",
            "2026-09-11",
            "2026-09-12",
            "2026-09-13",
        ]
        assert snapshot.daily_activity["2026-09-07"] == 1
        assert snapshot.daily_activity["2026-09-13"] == 1
        assert set(memory.get_profile("student_window").recent_concepts) == {"old_concept", "recent_concept"}


def test_profile_window_uses_the_requested_local_day_boundary():
    with tempfile.TemporaryDirectory() as temp_dir:
        memory = MemoryCore(base_dir=temp_dir)
        now = datetime(2026, 9, 12, 16, 30, tzinfo=timezone.utc)
        event = build_concept_mentioned_event(
            session_id="sess_timezone",
            student_id="student_timezone",
            concept_id="local_day",
            concept_name="本地日期",
            chapter="第1章",
            question_type="概念理解",
            matched_score=0.9,
            raw_question="本地日期是什么？",
        )
        event.timestamp = now.timestamp()
        memory.record_event(event)

        snapshot = memory.get_profile_window(
            "student_timezone",
            7,
            now=now.timestamp(),
            timezone_offset_minutes=-480,
        )

        assert list(snapshot.daily_activity)[-1] == "2026-09-13"
        assert snapshot.daily_activity["2026-09-13"] == 1


def test_recent_concepts_keep_last_mentioned_timestamp():
    with tempfile.TemporaryDirectory() as temp_dir:
        memory = MemoryCore(base_dir=temp_dir)

        first = build_concept_mentioned_event(
            session_id="sess_1",
            student_id="student_a",
            concept_id="svm",
            concept_name="支持向量机",
            chapter="第6章",
            question_type="概念理解",
            matched_score=0.92,
            raw_question="什么是 SVM？",
        )
        first.timestamp = 100.0

        second = build_concept_mentioned_event(
            session_id="sess_1",
            student_id="student_a",
            concept_id="svm",
            concept_name="支持向量机",
            chapter="第6章",
            question_type="概念理解",
            matched_score=0.90,
            raw_question="再讲一下 SVM。",
        )
        second.timestamp = 200.0

        memory.record_event(first)
        memory.record_event(second)
        memory.aggregate_profile("student_a")

        profile = memory.get_profile("student_a")
        svm_focus = profile.get_concept_focus("svm")

        assert svm_focus is not None
        assert svm_focus.mention_count == 2
        assert svm_focus.last_mentioned_at == 200.0


def test_weak_spot_moves_from_active_to_resolved_after_mastery_signal():
    with tempfile.TemporaryDirectory() as temp_dir:
        memory = MemoryCore(base_dir=temp_dir)

        concept_event = build_concept_mentioned_event(
            session_id="sess_2",
            student_id="student_b",
            concept_id="gradient_descent",
            concept_name="梯度下降",
            chapter="第5章",
            question_type="概念理解",
            matched_score=0.95,
            raw_question="什么是梯度下降？",
        )
        concept_event.timestamp = 100.0
        memory.record_event(concept_event)

        clarification_one = build_clarification_event(
            session_id="sess_2",
            student_id="student_b",
            concept_id="gradient_descent",
            parent_event_id=concept_event.event_id,
            clarification_type="simplify_request",
        )
        clarification_one.timestamp = 120.0
        memory.record_event(clarification_one)

        clarification_two = build_clarification_event(
            session_id="sess_2",
            student_id="student_b",
            concept_id="gradient_descent",
            parent_event_id=concept_event.event_id,
            clarification_type="example_request",
        )
        clarification_two.timestamp = 140.0
        memory.record_event(clarification_two)

        memory.aggregate_profile("student_b")
        profile = memory.get_profile("student_b")
        assert len(profile.weak_spot_candidates) == 1
        assert profile.weak_spot_candidates[0].concept_id == "gradient_descent"

        mastery_event = build_mastery_signal_event(
            session_id="sess_2",
            student_id="student_b",
            concept_id="gradient_descent",
            source_event_id=concept_event.event_id,
            signal_type="explicit_understanding",
        )
        mastery_event.timestamp = 180.0
        memory.record_event(mastery_event)

        memory.aggregate_profile("student_b")
        profile = memory.get_profile("student_b")

        assert not profile.weak_spot_candidates
        assert len(profile.resolved_weak_spots) == 1
        assert profile.resolved_weak_spots[0].concept_id == "gradient_descent"
        assert profile.resolved_weak_spots[0].resolved_at == 180.0


def test_single_clarification_stays_in_pending_weak_spots():
    with tempfile.TemporaryDirectory() as temp_dir:
        memory = MemoryCore(base_dir=temp_dir)

        concept_event = build_concept_mentioned_event(
            session_id="sess_3",
            student_id="student_c",
            concept_id="overfitting",
            concept_name="过拟合",
            chapter="第8章",
            question_type="概念对比",
            matched_score=0.91,
            raw_question="过拟合和泛化有什么区别？",
        )
        concept_event.timestamp = 100.0
        memory.record_event(concept_event)

        clarification = build_clarification_event(
            session_id="sess_3",
            student_id="student_c",
            concept_id="overfitting",
            parent_event_id=concept_event.event_id,
            clarification_type="distinction_request",
        )
        clarification.timestamp = 120.0
        memory.record_event(clarification)

        memory.aggregate_profile("student_c")
        profile = memory.get_profile("student_c")

        assert len(profile.pending_weak_spots) == 1
        assert profile.pending_weak_spots[0].concept_id == "overfitting"
        assert profile.pending_weak_spots[0].clarification_count == 1
        assert not profile.weak_spot_candidates


def test_manual_resolve_active_weak_spot_moves_it_to_resolved_history():
    with tempfile.TemporaryDirectory() as temp_dir:
        memory = MemoryCore(base_dir=temp_dir)

        concept_event = build_concept_mentioned_event(
            session_id="sess_4",
            student_id="student_d",
            concept_id="cross_validation",
            concept_name="交叉验证",
            chapter="第6章",
            question_type="概念理解",
            matched_score=0.93,
            raw_question="交叉验证是什么？",
        )
        concept_event.timestamp = 100.0
        memory.record_event(concept_event)

        clarification_one = build_clarification_event(
            session_id="sess_4",
            student_id="student_d",
            concept_id="cross_validation",
            parent_event_id=concept_event.event_id,
            clarification_type="simplify_request",
        )
        clarification_one.timestamp = 120.0
        memory.record_event(clarification_one)

        clarification_two = build_clarification_event(
            session_id="sess_4",
            student_id="student_d",
            concept_id="cross_validation",
            parent_event_id=concept_event.event_id,
            clarification_type="example_request",
        )
        clarification_two.timestamp = 150.0
        memory.record_event(clarification_two)

        memory.aggregate_profile("student_d")
        profile = memory.get_profile("student_d")
        assert len(profile.weak_spot_candidates) == 1

        resolved_spot = memory.resolve_active_weak_spot("student_d", "cross_validation")
        profile = memory.get_profile("student_d")

        assert resolved_spot.concept_id == "cross_validation"
        assert resolved_spot.resolution_note == "manual_resolve"
        assert not profile.weak_spot_candidates
        assert len(profile.resolved_weak_spots) == 1
        assert profile.resolved_weak_spots[0].concept_id == "cross_validation"
