import tempfile

from fastapi.testclient import TestClient

from apps.api.app.main import app
from core.events import build_clarification_event, build_concept_mentioned_event
from core.memory_core import MemoryCore
from core.profile_models import ConceptFocus, StudentProfile, WeakSpotCandidate

client = TestClient(app)


class TestProfileAPI:
    def setup_method(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.memory = MemoryCore(base_dir=self.temp_dir.name)

        from apps.api.app.routers import profile as profile_router

        self._old_get_memory = profile_router.get_memory
        profile_router.get_memory = lambda: self.memory

    def teardown_method(self):
        from apps.api.app.routers import profile as profile_router

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

        resp = client.get("/api/profile/summary/student001")
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
        profile = StudentProfile(student_id="student002")
        profile.recent_concepts["decision_tree"] = ConceptFocus(
            concept_id="decision_tree",
            display_name="决策树",
            chapter="第6章",
            mention_count=5,
            last_mentioned_at=100.0,
            last_question_type="概念理解",
        )
        profile.recent_concepts["pca"] = ConceptFocus(
            concept_id="pca",
            display_name="主成分分析",
            chapter="第7章",
            mention_count=2,
            last_mentioned_at=300.0,
            last_question_type="数学推导",
        )
        self.memory.save_profile(profile)

        resp = client.get("/api/profile/detail/student002")
        assert resp.status_code == 200
        data = resp.json()

        assert data["recent_concepts"][0]["concept_id"] == "pca"
        assert data["recent_concepts"][1]["concept_id"] == "decision_tree"
        assert "stats" in data
        assert "resolved_weak_spots" in data

    def test_get_detail_includes_active_and_resolved_weak_spots(self):
        profile = StudentProfile(student_id="student003")
        profile.weak_spot_candidates.append(
            WeakSpotCandidate(
                concept_id="cross_validation",
                display_name="交叉验证",
                confidence=0.75,
                clarification_count=2,
                first_detected_at=20.0,
                last_triggered_at=50.0,
                signals=[{"type": "CLARIFICATION"}, {"type": "CLARIFICATION"}],
            )
        )
        profile.pending_weak_spots.append(
            WeakSpotCandidate(
                concept_id="distinction::demo",
                display_name="过拟合 vs 泛化",
                confidence=0.42,
                clarification_count=1,
                first_detected_at=15.0,
                last_triggered_at=40.0,
                signals=[{"type": "CLARIFICATION"}],
            )
        )
        profile.resolved_weak_spots.append(
            WeakSpotCandidate(
                concept_id="gradient_descent",
                display_name="梯度下降",
                confidence=0.68,
                clarification_count=2,
                first_detected_at=10.0,
                last_triggered_at=30.0,
                resolved_at=60.0,
                resolution_note="explicit_understanding",
                signals=[{"type": "CLARIFICATION"}, {"type": "MASTERY"}],
            )
        )
        profile.stats.update(
            {
                "total_questions": 8,
                "total_concepts": 3,
                "pending_weak_spots": 1,
                "active_weak_spots": 1,
                "resolved_weak_spots": 1,
                "total_resolved_weak_spots": 1,
            }
        )
        self.memory.save_profile(profile)

        resp = client.get("/api/profile/detail/student003")
        assert resp.status_code == 200
        data = resp.json()

        assert data["pending_weak_spots"][0]["concept_id"] == "distinction::demo"
        assert data["weak_spots"][0]["concept_id"] == "cross_validation"
        assert data["resolved_weak_spots"][0]["concept_id"] == "gradient_descent"
        assert data["resolved_weak_spots"][0]["resolved_at"] is not None
        assert data["stats"]["total_resolved_weak_spots"] == 1
        assert data["stats"]["pending_weak_spots"] == 1

    def test_get_concept_detail_returns_catalog_and_excerpt(self):
        from apps.api.app.routers import profile as profile_router

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
        from apps.api.app.routers import profile as profile_router
        from core.agent import AgentService

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
        concept_event.timestamp = 100.0
        self.memory.record_event(concept_event)

        clarification_one = build_clarification_event(
            session_id="sess_profile",
            student_id="student004",
            concept_id="cross_validation",
            parent_event_id=concept_event.event_id,
            clarification_type="simplify_request",
        )
        clarification_one.timestamp = 120.0
        self.memory.record_event(clarification_one)

        clarification_two = build_clarification_event(
            session_id="sess_profile",
            student_id="student004",
            concept_id="cross_validation",
            parent_event_id=concept_event.event_id,
            clarification_type="example_request",
        )
        clarification_two.timestamp = 150.0
        self.memory.record_event(clarification_two)

        self.memory.aggregate_profile("student004")

        resp = client.post("/api/profile/weak-spots/student004/cross_validation/resolve")
        assert resp.status_code == 200
        data = resp.json()

        assert "已移出" in data["message"]
        assert data["resolved_weak_spot"]["concept_id"] == "cross_validation"
        assert data["resolved_weak_spot"]["resolution_note"] == "manual_resolve"

        detail_resp = client.get("/api/profile/detail/student004")
        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()
        assert detail_data["weak_spots"] == []
        assert detail_data["resolved_weak_spots"][0]["concept_id"] == "cross_validation"
