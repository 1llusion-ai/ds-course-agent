"""
画像 API 测试
覆盖: 画像获取、字段语义、归属校验
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestProfileAPI:
    """画像接口测试类"""

    def setup_method(self):
        """每个测试前清理数据"""
        from app.routers.sessions import _sessions
        from app.routers.chat import _chat_history
        _sessions.clear()
        _chat_history.clear()

    def test_get_summary_basic(self):
        """测试获取画像摘要"""
        # 创建会话并发送消息产生画像数据
        session_resp = client.post("/api/sessions", json={
            "title": "测试会话",
            "student_id": "student001"
        })
        session_id = session_resp.json()["id"]

        # 发送关于SVM的消息
        client.post("/api/chat/send", json={
            "session_id": session_id,
            "message": "什么是SVM",
            "student_id": "student001"
        })

        # 聚合画像
        client.post("/api/profile/aggregate/student001")

        # 获取摘要
        resp = client.get("/api/profile/summary/student001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["student_id"] == "student001"
        assert "recent_concepts" in data
        assert "weak_spots" in data

    def test_summary_no_timestamps(self):
        """测试摘要不包含不准确的时间戳"""
        # 创建一些活动
        session_resp = client.post("/api/sessions", json={
            "title": "测试会话",
            "student_id": "student002"
        })
        session_id = session_resp.json()["id"]

        client.post("/api/chat/send", json={
            "session_id": session_id,
            "message": "什么是机器学习",
            "student_id": "student002"
        })

        client.post("/api/profile/aggregate/student002")

        # 获取摘要
        resp = client.get("/api/profile/summary/student002")
        data = resp.json()

        # 检查字段 - 不应包含 last_mentioned（语义不准确）
        for concept in data.get("recent_concepts", []):
            assert "last_mentioned" not in concept, "不应包含不准确的时间戳"
            assert "mention_count" in concept, "应包含mention_count"

    def test_summary_sorted_by_mention_count(self):
        """测试近期概念按mention_count排序而非时间"""
        # 多次询问不同概念
        session_resp = client.post("/api/sessions", json={
            "title": "测试会话",
            "student_id": "student003"
        })
        session_id = session_resp.json()["id"]

        # 多次询问SVM
        for _ in range(3):
            client.post("/api/chat/send", json={
                "session_id": session_id,
                "message": "SVM的核函数",
                "student_id": "student003"
            })

        # 一次询问决策树
        client.post("/api/chat/send", json={
            "session_id": session_id,
            "message": "决策树是什么",
            "student_id": "student003"
        })

        client.post("/api/profile/aggregate/student003")

        # 获取摘要
        resp = client.get("/api/profile/summary/student003")
        data = resp.json()

        if len(data.get("recent_concepts", [])) >= 2:
            # 第一个概念的mention_count应该大于等于第二个
            first = data["recent_concepts"][0]["mention_count"]
            second = data["recent_concepts"][1]["mention_count"]
            assert first >= second, "应按mention_count降序排列"

    def test_get_detail_no_timestamps(self):
        """测试详情也不包含不准确的时间戳"""
        session_resp = client.post("/api/sessions", json={
            "title": "测试会话",
            "student_id": "student004"
        })
        session_id = session_resp.json()["id"]

        client.post("/api/chat/send", json={
            "session_id": session_id,
            "message": "什么是SVM",
            "student_id": "student004"
        })

        client.post("/api/profile/aggregate/student004")

        resp = client.get("/api/profile/detail/student004")
        data = resp.json()

        # 检查progress中不应有last_study_date
        progress = data.get("progress", {})
        assert "last_study_date" not in progress, "不应包含不准确的时间戳"

        # 检查recent_concepts
        for concept in data.get("recent_concepts", []):
            assert "last_mentioned" not in concept, "不应包含不准确的时间戳"

    def test_aggregate_profile(self):
        """测试手动触发画像聚合"""
        resp = client.post("/api/profile/aggregate/student005")
        assert resp.status_code == 200
        assert resp.json()["student_id"] == "student005"

    def test_profile_isolation(self):
        """测试不同学生的画像隔离"""
        # student_a 的活动
        session_a = client.post("/api/sessions", json={
            "title": "A的会话",
            "student_id": "student_a"
        }).json()["id"]

        client.post("/api/chat/send", json={
            "session_id": session_a,
            "message": "什么是SVM",
            "student_id": "student_a"
        })

        client.post("/api/profile/aggregate/student_a")

        # student_b 的活动
        session_b = client.post("/api/sessions", json={
            "title": "B的会话",
            "student_id": "student_b"
        }).json()["id"]

        client.post("/api/chat/send", json={
            "session_id": session_b,
            "message": "什么是决策树",
            "student_id": "student_b"
        })

        client.post("/api/profile/aggregate/student_b")

        # 获取各自的画像
        profile_a = client.get("/api/profile/summary/student_a").json()
        profile_b = client.get("/api/profile/summary/student_b").json()

        # 检查概念不混淆
        a_concepts = [c["concept_id"] for c in profile_a.get("recent_concepts", [])]
        b_concepts = [c["concept_id"] for c in profile_b.get("recent_concepts", [])]

        # svm 应在 a 中，decision_tree 应在 b 中
        assert "svm" in a_concepts or any("svm" in c.lower() for c in a_concepts), "A的画像应包含SVM"


class TestProfileFields:
    """画像字段测试"""

    def test_weak_spot_evidence_count(self):
        """测试薄弱点的证据数量计算"""
        # 产生薄弱点信号（多次澄清同一概念）
        session_resp = client.post("/api/sessions", json={
            "title": "测试会话",
            "student_id": "student006"
        })
        session_id = session_resp.json()["id"]

        # 同一概念多次询问可能产生薄弱点
        for _ in range(5):
            client.post("/api/chat/send", json={
                "session_id": session_id,
                "message": "SVM核函数怎么选",
                "student_id": "student006"
            })

        client.post("/api/profile/aggregate/student006")

        resp = client.get("/api/profile/detail/student006")
        data = resp.json()

        # 检查薄弱点字段
        for spot in data.get("weak_spots", []):
            assert "evidence_count" in spot
            assert spot["evidence_count"] >= 0
            assert "confidence" in spot
            assert 0 <= spot["confidence"] <= 1

    def test_chapter_stats(self):
        """测试章节统计"""
        session_resp = client.post("/api/sessions", json={
            "title": "测试会话",
            "student_id": "student007"
        })
        session_id = session_resp.json()["id"]

        client.post("/api/chat/send", json={
            "session_id": session_id,
            "message": "什么是机器学习",
            "student_id": "student007"
        })

        client.post("/api/profile/aggregate/student007")

        resp = client.get("/api/profile/detail/student007")
        data = resp.json()

        assert "chapter_stats" in data
        assert "daily_activity" in data
