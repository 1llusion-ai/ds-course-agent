import tempfile

from core.events import (
    build_clarification_event,
    build_concept_mentioned_event,
    build_mastery_signal_event,
)
from core.memory_core import MemoryCore


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
