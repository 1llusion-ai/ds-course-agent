"""ClarificationDetectorHook and LearningEventHook tests."""

from ds_course_agent.agent.hooks import ClarificationDetectorHook, LearningEventHook
from ds_course_agent.teaching.knowledge_mapper import MatchedConcept
from ds_course_agent.teaching.learning_event_repository import LearningEventRecord, SQLiteLearningEventRepository
from ds_course_agent.teaching.learning_events import EventType, build_concept_mentioned_event
from ds_course_agent.teaching.profile_snapshot_repository import SQLiteProfileSnapshotRepository


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


def test_learning_event_hook_records_concept_and_clarification(tmp_path):
    detector = ClarificationDetectorHook()
    hook = LearningEventHook(detector)
    event_repository = SQLiteLearningEventRepository(tmp_path / "app.db")
    recorded = []
    matched = [MatchedConcept("svm", "支持向量机", "第6章", "exact", 0.95)]

    recorded_count = hook.record_learning_events(
        question="再解释一下 SVM，我还是不懂。",
        session_id="session-1",
        student_id="student-1",
        matched_concepts=matched,
        event_repository=event_repository,
        record_event_fn=recorded.append,
        classify_question_type_fn=lambda _question: "概念理解",
    )

    assert [event.event_type for event in recorded] == [
        EventType.CONCEPT_MENTIONED,
        EventType.CLARIFICATION,
    ]
    assert recorded[0].payload["concept_id"] == "svm"
    assert recorded[1].payload["parent_event_id"] == recorded[0].event_id
    assert recorded_count == 2


def test_learning_event_hook_records_mastery_for_recent_contextual_concept(tmp_path):
    detector = ClarificationDetectorHook()
    hook = LearningEventHook(detector)
    event_repository = SQLiteLearningEventRepository(tmp_path / "app.db")
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
    event_repository.append(LearningEventRecord(concept_event, "turn-1"))
    recorded = []

    recorded_count = hook.record_learning_events(
        question="懂了，谢谢",
        session_id="session-1",
        student_id="student-1",
        matched_concepts=[],
        event_repository=event_repository,
        record_event_fn=recorded.append,
        classify_question_type_fn=lambda _question: "概念理解",
    )

    assert len(recorded) == 1
    assert recorded[0].event_type == EventType.MASTERY_SIGNAL
    assert recorded[0].payload["concept_id"] == "decision_tree"
    assert recorded[0].payload["source_event_id"] == concept_event.event_id
    assert recorded_count == 1


def test_learning_event_hook_on_session_end_projects_sqlite_profile(tmp_path):
    path = tmp_path / "app.db"
    event_repository = SQLiteLearningEventRepository(path)
    event = build_concept_mentioned_event(
        session_id="session-1",
        student_id="student-1",
        concept_id="pca",
        concept_name="主成分分析",
        chapter="第7章",
        question_type="概念理解",
        matched_score=0.9,
        raw_question="什么是 PCA？",
    )
    event_repository.append(LearningEventRecord(event, "turn-1"))
    profile_repository = SQLiteProfileSnapshotRepository(path)

    LearningEventHook().on_session_end(
        "session-1",
        student_id="student-1",
        profile_repository=profile_repository,
    )

    snapshot = profile_repository.get_latest("student-1")
    assert snapshot is not None
    assert set(snapshot.profile.recent_concepts) == {"pca"}
