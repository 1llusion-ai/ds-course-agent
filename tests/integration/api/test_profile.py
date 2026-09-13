import tempfile
import time

from fastapi.testclient import TestClient

from ds_course_agent.api.main import app
from ds_course_agent.teaching.learning_events import (
    build_clarification_event,
    build_concept_mentioned_event,
    build_mastery_signal_event,
)
from ds_course_agent.teaching.memory_core import MemoryCore
from ds_course_agent.teaching.profile_models import ConceptFocus, StudentProfile, WeakSpotCandidate

client = TestClient(app)


class TestProfileAPI:
    def setup_method(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.memory = MemoryCore(base_dir=self.temp_dir.name)

        from ds_course_agent.api.routers import profile as profile_router

        self._old_get_memory = profile_router.get_memory
        profile_router.get_memory = lambda: self.memory

    def teardown_method(self):
        from ds_course_agent.api.routers import profile as profile_router

        profile_router.get_memory = self._old_get_memory
        self.temp_dir.cleanup()

    def test_get_summary_exposes_recent_concepts_and_resolved_count(self):
        profile = StudentProfile(student_id="student001")
        profile.recent_concepts["svm"] = ConceptFocus(
            concept_id="svm",
            display_name="支持向量机",
            chapter="第6章",
            mention_count=3,
            last_mentioned_at=200.0,
            last_question_type="概念理解",
        )
        profile.weak_spot_candidates.append(
            WeakSpotCandidate(
                concept_id="svm_kernel",
                display_name="核函数",
                confidence=0.82,
                clarification_count=3,
                first_detected_at=100.0,
                last_triggered_at=180.0,
                signals=[{"type": "CLARIFICATION"}],
            )
        )
        profile.pending_weak_spots.append(
            WeakSpotCandidate(
                concept_id="svm_margin",
                display_name="间隔最大化",
                confidence=0.48,
                clarification_count=1,
                first_detected_at=90.0,
                last_triggered_at=95.0,
                signals=[{"type": "CLARIFICATION"}],
            )
        )
        profile.resolved_weak_spots.append(
            WeakSpotCandidate(
                concept_id="overfitting",
                display_name="过拟合",
                confidence=0.7,
                clarification_count=2,
                first_detected_at=50.0,
                last_triggered_at=120.0,
                resolved_at=160.0,
                signals=[{"type": "CLARIFICATION"}, {"type": "CLARIFICATION"}],
            )
        )
        profile.stats["total_resolved_weak_spots"] = 1
        self.memory.save_profile(profile)

        resp = client.get("/api/profile/summary", headers={"x-test-student-id": "student001"})
        assert resp.status_code == 200
        data = resp.json()

        assert data["student_id"] == "student001"
        assert data["resolved_weak_spot_count"] == 1
        assert data["recent_concepts"][0]["concept_id"] == "svm"
        assert data["pending_weak_spots"][0]["concept_id"] == "svm_margin"
        assert data["recent_concepts"][0]["last_mentioned_at"] is not None
        assert data["weak_spots"][0]["concept_id"] == "svm_kernel"
        assert data["weak_spots"][0]["clarification_count"] == 3

    def test_get_detail_sorts_recent_concepts_by_last_mentioned_at(self):
        now = time.time()
        decision_tree = build_concept_mentioned_event(
            session_id="sess_detail",
            student_id="student002",
            concept_id="decision_tree",
            concept_name="决策树",
            chapter="第6章",
            question_type="概念理解",
            matched_score=0.9,
            raw_question="决策树是什么？",
        )
        decision_tree.timestamp = now - 7200
        pca = build_concept_mentioned_event(
            session_id="sess_detail",
            student_id="student002",
            concept_id="pca",
            concept_name="主成分分析",
            chapter="第7章",
            question_type="数学推导",
            matched_score=0.9,
            raw_question="PCA 怎么推导？",
        )
        pca.timestamp = now - 3600
        old_concept = build_concept_mentioned_event(
            session_id="sess_detail",
            student_id="student002",
            concept_id="linear_regression",
            concept_name="线性回归",
            chapter="第3章",
            question_type="概念理解",
            matched_score=0.9,
            raw_question="线性回归是什么？",
        )
        old_concept.timestamp = now - 10 * 86400
        self.memory.record_events((decision_tree, pca, old_concept))

        resp = client.get("/api/profile/detail", headers={"x-test-student-id": "student002"})
        assert resp.status_code == 200
        data = resp.json()

        assert data["recent_concepts"][0]["concept_id"] == "pca"
        assert data["recent_concepts"][1]["concept_id"] == "decision_tree"
        assert {item["concept_id"] for item in data["recent_concepts"]} == {"pca", "decision_tree"}
        assert data["chapter_stats"] == {"第6章": 1, "第7章": 1}
        assert "stats" in data
        assert "resolved_weak_spots" in data

        month_resp = client.get("/api/profile/detail?days=30", headers={"x-test-student-id": "student002"})
        assert month_resp.status_code == 200
        assert {item["concept_id"] for item in month_resp.json()["recent_concepts"]} == {
            "pca",
            "decision_tree",
            "linear_regression",
        }

    def test_get_detail_includes_active_and_resolved_weak_spots(self):
        now = time.time()
        events = []
        for index, (concept_id, display_name, chapter, clarification_count) in enumerate(
            (
                ("cross_validation", "交叉验证", "第6章", 2),
                ("distinction::demo", "过拟合 vs 泛化", "第8章", 1),
                ("gradient_descent", "梯度下降", "第5章", 2),
            )
        ):
            concept = build_concept_mentioned_event(
                session_id="sess_weak_spots",
                student_id="student003",
                concept_id=concept_id,
                concept_name=display_name,
                chapter=chapter,
                question_type="概念理解",
                matched_score=0.9,
                raw_question=f"{display_name}是什么？",
            )
            concept.timestamp = now - 600 + index * 100
            events.append(concept)
            for clarification_index in range(clarification_count):
                clarification = build_clarification_event(
                    session_id="sess_weak_spots",
                    student_id="student003",
                    concept_id=concept_id,
                    parent_event_id=concept.event_id,
                    clarification_type="simplify_request",
                )
                clarification.timestamp = concept.timestamp + clarification_index + 1
                events.append(clarification)
            if concept_id == "gradient_descent":
                mastery = build_mastery_signal_event(
                    session_id="sess_weak_spots",
                    student_id="student003",
                    concept_id=concept_id,
                    source_event_id=concept.event_id,
                    signal_type="explicit_understanding",
                )
                mastery.timestamp = concept.timestamp + 10
                events.append(mastery)
        self.memory.record_events(tuple(events))

        resp = client.get("/api/profile/detail", headers={"x-test-student-id": "student003"})
        assert resp.status_code == 200
        data = resp.json()

        assert data["pending_weak_spots"][0]["concept_id"] == "distinction::demo"
        assert data["weak_spots"][0]["concept_id"] == "cross_validation"
        assert data["resolved_weak_spots"][0]["concept_id"] == "gradient_descent"
        assert data["resolved_weak_spots"][0]["resolved_at"] is not None
        assert data["stats"]["total_resolved_weak_spots"] == 1
        assert data["stats"]["pending_weak_spots"] == 1

    def test_get_concept_detail_returns_catalog_and_excerpt(self):
        from ds_course_agent.api.routers import profile as profile_router

        fake_catalog = {
            "svm": {
                "canonical_id": "svm",
                "display_name": "支持向量机",
                "chapter": "第6章",
                "section": "6.2",
                "aliases": ["支持向量机", "SVM"],
                "related_concepts": ["svm_kernel"],
            },
            "svm_kernel": {
                "canonical_id": "svm_kernel",
                "display_name": "核函数",
                "chapter": "第6章",
                "section": "6.2",
                "aliases": ["核函数"],
                "related_concepts": [],
            },
        }

        old_catalog = profile_router._get_concept_catalog
        old_pdf_extractor = profile_router._extract_textbook_excerpt_from_pdf
        old_rag_extractor = profile_router._retrieve_textbook_excerpt_with_rag
        profile_router._get_concept_catalog = lambda: fake_catalog
        profile_router._extract_textbook_excerpt_from_pdf = lambda concept: (
            "支持向量机是一种用于分类与回归的监督学习方法。",
            [{"reference": "《第6章 监督学习常用算法》第123页"}],
        )
        profile_router._retrieve_textbook_excerpt_with_rag = lambda concept: (None, [])
        try:
            resp = client.get("/api/profile/concepts/svm")
        finally:
            profile_router._get_concept_catalog = old_catalog
            profile_router._extract_textbook_excerpt_from_pdf = old_pdf_extractor
            profile_router._retrieve_textbook_excerpt_with_rag = old_rag_extractor

        assert resp.status_code == 200
        data = resp.json()
        assert data["concept_id"] == "svm"
        assert data["aliases"] == ["支持向量机", "SVM"]
        assert data["related_concepts"][0]["concept_id"] == "svm_kernel"
        assert "支持向量机" in data["textbook_excerpt"]

    def test_get_concept_detail_supports_distinction_concept(self):
        from ds_course_agent.agent.service import AgentService
        from ds_course_agent.api.routers import profile as profile_router

        service = AgentService.__new__(AgentService)
        distinction = service._build_distinction_learning_concept(
            "我感觉我老是搞不懂过拟合和泛化到底有什么差别",
            [],
        )

        old_rag_extractor = profile_router._retrieve_distinction_excerpt_with_rag
        profile_router._retrieve_distinction_excerpt_with_rag = lambda labels: (None, [])
        try:
            resp = client.get(f"/api/profile/concepts/{distinction['concept_id']}")
        finally:
            profile_router._retrieve_distinction_excerpt_with_rag = old_rag_extractor

        assert resp.status_code == 200
        data = resp.json()
        assert data["display_name"] == "泛化 vs 过拟合"
        assert data["aliases"] == ["泛化", "过拟合"]
        assert "辨析型知识点" in data["textbook_excerpt"]

    def test_resolve_weak_spot_moves_active_item_to_resolved_history(self):
        now = time.time()
        concept_event = build_concept_mentioned_event(
            session_id="sess_profile",
            student_id="student004",
            concept_id="cross_validation",
            concept_name="交叉验证",
            chapter="第6章",
            question_type="概念理解",
            matched_score=0.92,
            raw_question="交叉验证是什么？",
        )
        concept_event.timestamp = now - 120
        self.memory.record_event(concept_event)

        clarification_one = build_clarification_event(
            session_id="sess_profile",
            student_id="student004",
            concept_id="cross_validation",
            parent_event_id=concept_event.event_id,
            clarification_type="simplify_request",
        )
        clarification_one.timestamp = now - 90
        self.memory.record_event(clarification_one)

        clarification_two = build_clarification_event(
            session_id="sess_profile",
            student_id="student004",
            concept_id="cross_validation",
            parent_event_id=concept_event.event_id,
            clarification_type="example_request",
        )
        clarification_two.timestamp = now - 60
        self.memory.record_event(clarification_two)

        self.memory.aggregate_profile("student004")

        resp = client.post(
            "/api/profile/weak-spots/cross_validation/resolve", headers={"x-test-student-id": "student004"}
        )
        assert resp.status_code == 200
        data = resp.json()

        assert "已移出" in data["message"]
        assert data["resolved_weak_spot"]["concept_id"] == "cross_validation"
        assert data["resolved_weak_spot"]["resolution_note"] == "manual_resolve"

        detail_resp = client.get("/api/profile/detail", headers={"x-test-student-id": "student004"})
        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()
        assert detail_data["weak_spots"] == []
        assert detail_data["resolved_weak_spots"][0]["concept_id"] == "cross_validation"
