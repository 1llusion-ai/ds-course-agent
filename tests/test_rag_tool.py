"""
RAG Tool 单元测试
"""

import hashlib
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

import ds_course_agent.tools.course_rag as course_rag_module
from ds_course_agent.retrieval.term_resolution import (
    CourseTermIndex,
    CourseTermMatchKind,
    CourseTermResolution,
)
from ds_course_agent.shared.query_trace import begin_query_trace, end_query_trace
from ds_course_agent.tools.course_rag import (
    begin_retrieval_trace,
    clear_rag_answer_cache,
    course_rag_tool,
    end_retrieval_trace,
)
from ds_course_agent.tools.knowledge_base_status import check_knowledge_base_status
from ds_course_agent.tools.registry import get_rag_tools


@pytest.fixture(autouse=True)
def _clear_rag_answer_cache_between_tests():
    clear_rag_answer_cache()
    yield
    clear_rag_answer_cache()


class TestCourseRAGTool:
    """课程 RAG 工具测试"""

    def test_tool_has_correct_name(self):
        """测试工具名称正确"""
        assert course_rag_tool.name == "course_rag_tool"

    def test_tool_has_description(self):
        """测试工具有描述"""
        assert len(course_rag_tool.description) > 0
        assert "课程" in course_rag_tool.description or "数据科学" in course_rag_tool.description

    def test_get_rag_tools_returns_list(self):
        """测试获取工具列表"""
        tools = get_rag_tools()
        assert isinstance(tools, list)
        assert len(tools) >= 1
        assert course_rag_tool in tools

    @patch("ds_course_agent.tools.course_rag.get_rag_service")
    def test_tool_returns_error_message_on_exception(self, mock_get_service):
        """测试异常情况下返回错误消息"""
        mock_service = MagicMock()
        mock_service.retrieve.side_effect = Exception("测试异常")
        mock_get_service.return_value = mock_service

        result = course_rag_tool.invoke("测试问题")

        assert "错误" in result or "异常" in result or "error" in result.lower()

    @patch("ds_course_agent.tools.course_rag.get_rag_service")
    def test_tool_returns_no_results_message(self, mock_get_service):
        """测试无检索结果时返回提示消息"""
        mock_service = MagicMock()
        mock_result = MagicMock()
        mock_result.has_results = False
        mock_result.documents = []
        mock_result.retrieval_query = "测试问题"
        mock_result.term_resolution = None
        mock_service.retrieve.return_value = mock_result
        mock_get_service.return_value = mock_service

        result = course_rag_tool.invoke("测试问题")

        assert "未找到" in result or "无" in result or "建议" in result

    @patch("ds_course_agent.tools.course_rag.get_rag_service")
    def test_unknown_course_term_returns_no_sources_or_unrelated_answer(self, mock_get_service):
        mock_service = MagicMock()
        resolution = CourseTermResolution(
            requested_term="DMKI",
            resolved_term=None,
            resolved_query="DMKI是什么？",
            match_kind=CourseTermMatchKind.UNRESOLVED,
        )
        mock_service.retrieve.return_value = SimpleNamespace(
            has_results=False,
            documents=[],
            formatted_context="无相关资料",
            retrieval_query="DMKI是什么？",
            term_resolution=resolution,
        )
        mock_get_service.return_value = mock_service

        token = begin_retrieval_trace()
        try:
            result = course_rag_tool.invoke("DMKI是什么？")
        finally:
            trace = end_retrieval_trace(token)

        assert "没有找到与“DMKI”直接相关" in result
        assert "不会使用不相关的教材片段" in result
        assert trace.retrieval_attempted is True
        assert trace.used_retrieval is False
        assert trace.sources == []
        mock_service.answer_with_context.assert_not_called()

    @patch("ds_course_agent.tools.course_rag.get_rag_service")
    def test_corrected_course_term_is_disclosed_and_answered_with_resolved_query(self, mock_get_service):
        mock_service = MagicMock()
        resolution = CourseTermResolution(
            requested_term="DMKI",
            resolved_term="DIKW",
            resolved_query="DIKW是什么？",
            match_kind=CourseTermMatchKind.CORRECTED,
        )
        mock_service.retrieve.return_value = SimpleNamespace(
            has_results=True,
            documents=[Document(page_content="DIKW 表示数据到智慧", metadata={"book_page": 16})],
            formatted_context="DIKW 表示数据到智慧",
            retrieval_query="DIKW是什么？",
            term_resolution=resolution,
        )
        mock_service.answer_with_context.return_value = SimpleNamespace(answer="DIKW 是数据、信息、知识和智慧。")
        mock_get_service.return_value = mock_service

        result = course_rag_tool.invoke("DMKI是什么？")

        assert result.startswith("你输入的“DMKI”未在教材中出现，可能想问的是“DIKW”")
        assert result.endswith("DIKW 是数据、信息、知识和智慧。")
        mock_service.answer_with_context.assert_called_once_with("DIKW是什么？", "DIKW 表示数据到智慧")

    @patch("ds_course_agent.tools.course_rag.get_rag_service")
    def test_tool_tracks_retrieval_sources(self, mock_get_service):
        """测试检索轨迹会保留实际来源"""
        mock_service = MagicMock()
        mock_result = MagicMock()
        mock_result.has_results = True
        mock_result.formatted_context = "context"
        mock_result.retrieval_query = "PCA 的公式是什么？"
        mock_result.term_resolution = None

        doc = MagicMock()
        doc.metadata = {
            "source": "第7章_无监督学习算法.pdf",
            "chapter": "无监督学习算法",
            "chapter_no": "第7章",
            "book_page": 123,
        }
        mock_result.documents = [doc]
        mock_service.retrieve.return_value = mock_result

        mock_answer = MagicMock()
        mock_answer.answer = "PCA 是一种降维方法"
        mock_service.answer_with_context.return_value = mock_answer
        mock_get_service.return_value = mock_service

        token = begin_retrieval_trace()
        try:
            result = course_rag_tool.invoke("PCA 的公式是什么？")
        finally:
            trace = end_retrieval_trace(token)

        assert result == "PCA 是一种降维方法"
        assert trace.retrieval_attempted is True
        assert trace.used_retrieval is True
        assert trace.sources == [{"reference": "《第7章 无监督学习算法》第123页"}]

    def test_nested_retrieval_trace_isolated_and_merged_to_parent(self):
        from ds_course_agent.tools._shared import _track_retrieval

        parent_token = begin_retrieval_trace()
        try:
            _track_retrieval([{"reference": "父来源"}], attempted=True, used=True)
            child_token = begin_retrieval_trace()
            try:
                _track_retrieval([{"reference": "子来源"}], attempted=True, used=True)
            finally:
                child_trace = end_retrieval_trace(child_token)
        finally:
            parent_trace = end_retrieval_trace(parent_token)

        assert child_trace.sources == [{"reference": "子来源"}]
        assert parent_trace.sources == [{"reference": "父来源"}, {"reference": "子来源"}]
        assert parent_trace.used_retrieval is True

    @patch("ds_course_agent.tools.course_rag.get_rag_service")
    def test_tool_degrades_to_extractive_fallback_when_answer_llm_fails(self, mock_get_service):
        """检索成功但回答 LLM 失败时，应降级为教材片段而不是整轮报错。"""
        mock_service = MagicMock()
        mock_result = MagicMock()
        mock_result.has_results = True
        mock_result.formatted_context = "context"
        mock_result.retrieval_query = "PCA 的核心思想是什么？"
        mock_result.term_resolution = None
        mock_result.documents = [
            Document(
                page_content="PCA 通过投影到方差最大的方向来实现降维，同时尽量保留数据中的主要信息。",
                metadata={
                    "chapter": "无监督学习算法",
                    "chapter_no": "第7章",
                    "book_page": 140,
                },
            )
        ]
        mock_service.retrieve.return_value = mock_result
        mock_service.answer_with_context.side_effect = RuntimeError("llm unavailable")
        mock_get_service.return_value = mock_service

        token = begin_query_trace({"entrypoint": "unit_test"})
        result = course_rag_tool.invoke("PCA 的核心思想是什么？")
        trace = end_query_trace(token)

        assert "生成式回答服务暂时不可用" in result
        assert "PCA 通过投影" in result
        assert "《第7章 无监督学习算法》第140页" in result
        assert trace["status"] == "ok"
        assert any(
            event["stage"] == "tool.course_rag.answer_degraded"
            and event["status"] == "warning"
            and event["data"]["mode"] == "sync"
            for event in trace["events"]
        )

    def test_source_uses_outline_number_when_chapter_metadata_drifts(self):
        """metadata 章字段错位时，来源展示应按 section_no 纠偏。"""
        from ds_course_agent.tools.course_rag import build_sources_from_documents

        doc = MagicMock()
        doc.metadata = {
            "source": "数据科学导论.pdf",
            "chapter": "Python 语言快速入门",
            "chapter_no": "第3章",
            "section": "数据科学",
            "section_no": "2.2",
            "subsection": "数据科学的概念",
            "subsection_no": "2.2.1",
            "book_page": 20,
        }

        assert build_sources_from_documents([doc]) == [{"reference": "《第2章 数据科学基本知识》第20页"}]

    def test_source_uses_toc_title_when_chapter_number_matches(self):
        """章号已正确但章名陈旧时，来源展示仍应按目录标题纠偏。"""
        from ds_course_agent.tools.course_rag import build_sources_from_documents

        doc = MagicMock()
        doc.metadata = {
            "chapter": "Python 语言快速入门",
            "chapter_no": "第2章",
            "section_no": "2.2",
            "book_page": 20,
        }

        assert build_sources_from_documents([doc]) == [{"reference": "《第2章 数据科学基本知识》第20页"}]

    @patch("ds_course_agent.tools.course_rag.get_rag_service")
    def test_tool_tracks_empty_sources_when_no_results(self, mock_get_service):
        """测试无结果时仍会记录已尝试检索"""
        mock_service = MagicMock()
        mock_result = MagicMock()
        mock_result.has_results = False
        mock_result.documents = []
        mock_result.retrieval_query = "你好"
        mock_result.term_resolution = None
        mock_service.retrieve.return_value = mock_result
        mock_get_service.return_value = mock_service

        token = begin_retrieval_trace()
        try:
            course_rag_tool.invoke("你好")
        finally:
            trace = end_retrieval_trace(token)

        assert trace.retrieval_attempted is True
        assert trace.used_retrieval is False
        assert trace.sources == []

    @patch("ds_course_agent.tools.course_rag.get_rag_service")
    def test_tool_warns_on_large_course_rag_result_without_changing_return(self, mock_get_service, monkeypatch):
        """Large tool results are observed but not normalized/offloaded in v1."""
        import ds_course_agent.shared.context_governor as context_governor
        from ds_course_agent.shared.context_governor import ContextBudget

        monkeypatch.setattr(
            context_governor,
            "DEFAULT_CONTEXT_BUDGET",
            ContextBudget(large_message_tokens=2),
        )
        mock_service = MagicMock()
        mock_result = MagicMock()
        mock_result.has_results = True
        mock_result.formatted_context = "context"
        mock_result.documents = []
        mock_result.retrieval_query = "测试问题"
        mock_result.term_resolution = None
        mock_service.retrieve.return_value = mock_result

        large_answer = "教材回答" * 20
        mock_answer = MagicMock()
        mock_answer.answer = large_answer
        mock_service.answer_with_context.return_value = mock_answer
        mock_get_service.return_value = mock_service

        token = begin_query_trace({"entrypoint": "unit_test"})
        result = course_rag_tool.invoke("测试问题")
        trace = end_query_trace(token)

        assert result == large_answer
        assert any(
            event["stage"] == "context_governor.warning"
            and event["data"]["kind"] == "large_text_payload"
            and event["data"]["tool"] == "course_rag_tool"
            for event in trace["events"]
        )

    @patch("ds_course_agent.tools.course_rag.get_rag_service")
    def test_tool_answer_cache_hit_avoids_second_answer_llm_call(self, mock_get_service):
        """同一问题+同一检索上下文命中进程内缓存，第二次不再调回答 LLM。"""
        mock_service = MagicMock()
        mock_result = MagicMock()
        mock_result.has_results = True
        mock_result.formatted_context = "教材上下文：PCA 是降维算法"
        mock_result.retrieval_query = "PCA 有什么作用？"
        mock_result.term_resolution = None
        mock_result.documents = [
            Document(page_content="PCA 是降维算法", metadata={"chapter_no": "第7章", "book_page": 140})
        ]
        mock_service.retrieve.return_value = mock_result
        mock_service.answer_with_context.return_value = SimpleNamespace(answer="PCA 可以用于降维。")
        mock_get_service.return_value = mock_service

        token = begin_query_trace({"entrypoint": "unit_test"})
        first = course_rag_tool.invoke("PCA 有什么作用？")
        second = course_rag_tool.invoke(" PCA 有什么作用？ ")
        trace = end_query_trace(token)

        assert first == "PCA 可以用于降维。"
        assert second == first
        assert mock_service.answer_with_context.call_count == 1
        assert any(event["stage"] == "rag.answer.cache_store" for event in trace["events"])
        assert any(event["stage"] == "rag.answer.cache_hit" for event in trace["events"])
        assert any(
            event["stage"] == "tool.result"
            and event["status"] == "cache_hit"
            and event["data"].get("tool") == "course_rag_tool"
            for event in trace["events"]
        )

    @patch("ds_course_agent.tools.course_rag.get_rag_service")
    def test_tool_answer_cache_key_includes_retrieved_context(self, mock_get_service):
        """同一问题但检索上下文不同，不应复用旧答案。"""
        mock_service = MagicMock()
        result_a = MagicMock()
        result_a.has_results = True
        result_a.formatted_context = "上下文 A：PCA 用于降维"
        result_a.documents = [Document(page_content="A", metadata={"source": "a.pdf"})]
        result_a.retrieval_query = "PCA 有什么作用？"
        result_a.term_resolution = None
        result_b = MagicMock()
        result_b.has_results = True
        result_b.formatted_context = "上下文 B：PCA 用于可视化"
        result_b.documents = [Document(page_content="B", metadata={"source": "b.pdf"})]
        result_b.retrieval_query = "PCA 有什么作用？"
        result_b.term_resolution = None
        mock_service.retrieve.side_effect = [result_a, result_b]
        mock_service.answer_with_context.side_effect = [
            SimpleNamespace(answer="答案 A"),
            SimpleNamespace(answer="答案 B"),
        ]
        mock_get_service.return_value = mock_service

        token = begin_query_trace({"entrypoint": "unit_test"})
        first = course_rag_tool.invoke("PCA 有什么作用？")
        second = course_rag_tool.invoke("PCA 有什么作用？")
        trace = end_query_trace(token)

        assert first == "答案 A"
        assert second == "答案 B"
        assert mock_service.answer_with_context.call_count == 2
        assert sum(1 for event in trace["events"] if event["stage"] == "rag.answer.cache_miss") == 2

    @patch("ds_course_agent.tools.course_rag.get_rag_service")
    def test_tool_answer_timeout_degrades_to_extractive_fallback(self, mock_get_service, monkeypatch):
        """回答 LLM 超时后，应在超时保护窗口内降级为教材片段。"""
        monkeypatch.setattr(course_rag_module.config, "RAG_ANSWER_TIMEOUT_SECONDS", 0.001, raising=False)

        class SlowAnswerService:
            def retrieve(self, question):
                return SimpleNamespace(
                    has_results=True,
                    formatted_context="context",
                    retrieval_query=question,
                    term_resolution=None,
                    documents=[
                        Document(
                            page_content="PCA 通过投影到方差最大的方向来实现降维。",
                            metadata={"chapter": "无监督学习算法", "chapter_no": "第7章", "book_page": 140},
                        )
                    ],
                )

            def answer_with_context(self, question, context):
                time.sleep(0.05)
                return SimpleNamespace(answer="迟到的生成式答案")

        mock_get_service.return_value = SlowAnswerService()

        token = begin_query_trace({"entrypoint": "unit_test"})
        result = course_rag_tool.invoke("PCA 的核心思想是什么？")
        trace = end_query_trace(token)

        assert "生成式回答服务暂时不可用" in result
        assert "PCA 通过投影" in result
        assert "《第7章 无监督学习算法》第140页" in result
        assert any(
            event["stage"] == "rag.answer.timeout_degraded" and event["status"] == "warning"
            for event in trace["events"]
        )
        assert any(
            event["stage"] == "tool.course_rag.answer_degraded"
            and event["status"] == "warning"
            and event["data"]["error_type"] == "TimeoutError"
            for event in trace["events"]
        )


class TestCheckKnowledgeBaseStatus:
    """知识库状态检查工具测试"""

    @patch("ds_course_agent.tools.knowledge_base_status.get_rag_service")
    def test_status_tool_returns_success(self, mock_get_service):
        """测试状态检查返回成功"""
        mock_service = MagicMock()
        mock_result = MagicMock()
        mock_result.has_results = True
        mock_service.retrieve.return_value = mock_result
        mock_get_service.return_value = mock_service

        result = check_knowledge_base_status.invoke({})

        assert "正常" in result or "✅" in result

    @patch("ds_course_agent.tools.knowledge_base_status.get_rag_service")
    def test_status_tool_returns_error_on_exception(self, mock_get_service):
        """测试状态检查异常时返回错误"""
        mock_get_service.side_effect = Exception("连接失败")

        result = check_knowledge_base_status.invoke({})

        assert "异常" in result or "❌" in result or "错误" in result


class TestRAGPayloadWarnings:
    def test_retrieve_warns_on_large_formatted_context_without_changing_result(self, monkeypatch):
        import ds_course_agent.retrieval.service as rag_service_module
        import ds_course_agent.shared.context_governor as context_governor
        from ds_course_agent.retrieval.service import RAGService
        from ds_course_agent.shared.context_governor import ContextBudget

        monkeypatch.setattr(
            context_governor,
            "DEFAULT_CONTEXT_BUDGET",
            ContextBudget(large_message_tokens=2),
        )

        service = RAGService.__new__(RAGService)
        text = "教材片段" * 20
        digest = hashlib.sha256(text.encode()).hexdigest()
        service.embedding = object()
        service._token_counter = SimpleNamespace(policy_version="cl100k_base_v1", count=len)
        service.vector_store_service = MagicMock()
        service.course_term_index = CourseTermIndex([])
        service.vector_store_service.query.return_value = {
            "ids": [["chunk-1"]],
            "documents": [[text]],
            "metadatas": [
                [
                    {
                        "metadata_schema_version": "retrieval-provenance/1.0",
                        "source": "test.pdf",
                        "source_id": "test",
                        "source_page": 9,
                        "book_page": 1,
                        "source_char_start": 0,
                        "source_char_end": len(text),
                        "content_sha256": digest,
                        "source_page_sha256": digest,
                        "source_page_text": text,
                    }
                ]
            ],
            "distances": [[0.1]],
        }
        monkeypatch.setattr(rag_service_module, "embed_query_cached", lambda *args, **kwargs: [1.0])
        monkeypatch.setattr(rag_service_module.config, "RAG_CONTEXT_MAX_TOKENS", 10_000, raising=False)

        token = begin_query_trace({"entrypoint": "unit_test"})
        result = service.retrieve("测试问题", top_k=1)
        trace = end_query_trace(token)

        assert result.has_results is True
        assert "教材片段" in result.formatted_context
        assert any(
            event["stage"] == "context_governor.warning"
            and event["data"]["kind"] == "large_text_payload"
            and event["data"]["payload_type"] == "rag_context"
            for event in trace["events"]
        )


class TestToolIntegration:
    """工具集成测试（需要真实环境）"""

    @pytest.mark.skip(reason="需要真实环境运行")
    def test_tool_can_be_invoked(self):
        """测试工具可以被调用"""
        result = course_rag_tool.invoke("什么是数据科学？")
        assert isinstance(result, str)
        assert len(result) > 0
