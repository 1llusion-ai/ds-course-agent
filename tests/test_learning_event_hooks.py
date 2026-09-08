"""ClarificationDetectorHook and LearningEventHook tests."""

from types import SimpleNamespace

from ds_course_agent.agent.hooks import ClarificationDetectorHook, LearningEventHook
from ds_course_agent.teaching.knowledge_mapper import MatchedConcept
from ds_course_agent.teaching.learning_events import EventType, build_concept_mentioned_event


def test_clarification_detector_classifies_rules_and_distinction_concept():
    detector = ClarificationDetectorHook()
    matched = [
        MatchedConcept("overfit", "过拟合", "第6章", "exact", 0.95),
        MatchedConcept("generalization", "泛化", "第6章", "exact", 0.90),
    ]

    assert detector.is_clarification_request("我还是不懂过拟合，能举个例子吗？") is True
    assert detector.is_mastery_signal("明白了，我懂了") is True
    assert detector.infer_clarification_type("举个例子说明") == "example_request"
    assert detector.infer_clarification_type("过拟合和泛化有什么区别？我分不清") == "distinction_request"

    distinction = detector.build_distinction_learning_concept("过拟合和泛化有什么区别？", matched)
    assert distinction is not None
    assert distinction["concept_id"].startswith("distinction::")
    assert distinction["concept_name"] == "泛化 vs 过拟合"


def test_learning_event_hook_records_concept_and_clarification():
    detector = ClarificationDetectorHook()
    hook = LearningEventHook(detector)
    recorded = []
    matched = [MatchedConcept("svm", "支持向量机", "第6章", "exact", 0.95)]

    hook.record_learning_events(
        question="再解释一下 SVM，我还是不懂。",
        session_id="session-1",
        student_id="student-1",
        matched_concepts=matched,
        get_memory_core_fn=lambda: SimpleNamespace(load_events=lambda _student_id: []),
        record_event_fn=recorded.append,
        classify_question_type_fn=lambda _question: "概念理解",
    )

    assert [event.event_type for event in recorded] == [
        EventType.CONCEPT_MENTIONED,
        EventType.CLARIFICATION,
    ]
    assert recorded[0].payload["concept_id"] == "svm"
    assert recorded[1].payload["parent_event_id"] == recorded[0].event_id


def test_learning_event_hook_records_mastery_for_recent_contextual_concept():
    detector = ClarificationDetectorHook()
    hook = LearningEventHook(detector)
    concept_event = build_concept_mentioned_event(
        session_id="session-1",
        student_id="student-1",
        concept_id="decision_tree",
        concept_name="决策树",
        chapter="第6章",
        question_type="概念理解",
        matched_score=0.9,
        raw_question="什么是决策树？",
    )
    memory = SimpleNamespace(load_events=lambda _student_id: [concept_event])
    recorded = []

    hook.record_learning_events(
        question="懂了，谢谢",
        session_id="session-1",
        student_id="student-1",
        matched_concepts=[],
        get_memory_core_fn=lambda: memory,
        record_event_fn=recorded.append,
        classify_question_type_fn=lambda _question: "概念理解",
    )

    assert len(recorded) == 1
    assert recorded[0].event_type == EventType.MASTERY_SIGNAL
    assert recorded[0].payload["concept_id"] == "decision_tree"
    assert recorded[0].payload["source_event_id"] == concept_event.event_id


def test_learning_event_hook_on_session_end_aggregates_profile():
    calls = []
    memory = SimpleNamespace(aggregate_profile=lambda student_id: calls.append(student_id))

    LearningEventHook().on_session_end(
        "session-1",
        student_id="student-1",
        get_memory_core_fn=lambda: memory,
    )

    assert calls == ["student-1"]
