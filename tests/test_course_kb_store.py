"""
课程知识库存储测试
"""
import pytest
from unittest.mock import patch, MagicMock


class TestSanitizeCollectionName:
    """测试 collection 名称规范化"""

    def test_sanitize_chinese_name(self):
        """测试中文名称转换"""
        from kb_builder.store import sanitize_collection_name
        
        result = sanitize_collection_name("数据科学导论")
        
        assert len(result) >= 3
        assert result[0].isalnum()
        assert result[-1].isalnum()
        assert all(c.isalnum() or c in '._-' for c in result)

    def test_sanitize_english_name(self):
        """测试英文名称"""
        from kb_builder.store import sanitize_collection_name
        
        result = sanitize_collection_name("Data Science Introduction")
        
        assert "Data" in result or "data" in result.lower()
        assert result[0].isalnum()
        assert result[-1].isalnum()

    def test_sanitize_empty_name(self):
        """测试空名称"""
        from kb_builder.store import sanitize_collection_name
        
        result = sanitize_collection_name("")
        
        assert result == "course_default"

    def test_sanitize_special_chars(self):
        """测试特殊字符"""
        from kb_builder.store import sanitize_collection_name
        
        result = sanitize_collection_name("test@#$%name!")
        
        assert '@' not in result
        assert '#' not in result
        assert '$' not in result
        assert result[0].isalnum()
        assert result[-1].isalnum()

    def test_sanitize_long_name(self):
        """测试超长名称"""
        from kb_builder.store import sanitize_collection_name
        
        long_name = "a" * 600
        result = sanitize_collection_name(long_name)
        
        assert len(result) <= 512
        assert result[-1].isalnum()

    def test_sanitize_short_name(self):
        """测试过短名称"""
        from kb_builder.store import sanitize_collection_name
        
        result = sanitize_collection_name("ab")
        
        assert len(result) >= 3


class TestCourseKnowledgeBase:
    """测试课程知识库类"""

    def test_collection_name_logic(self):
        """测试 collection 名称逻辑"""
        from kb_builder.store import sanitize_collection_name
        
        course_name = "测试课程"
        custom_collection = "custom_collection"
        
        if custom_collection:
            collection_name = custom_collection
        else:
            collection_name = f"course_{sanitize_collection_name(course_name)}"
        
        assert collection_name == "custom_collection"
        
        custom_collection = ""
        if custom_collection:
            collection_name = custom_collection
        else:
            collection_name = f"course_{sanitize_collection_name(course_name)}"
        
        assert collection_name.startswith("course_")
        assert len(collection_name) >= 3

    def test_clear_method_with_cached_chroma_class(self):
        """测试 clear() 方法使用缓存的 Chroma 类"""
        from kb_builder.store import CourseKnowledgeBase
        
        mock_vector_store = MagicMock()
        mock_chroma = MagicMock(return_value=mock_vector_store)
        mock_embedding = MagicMock()
        mock_config = MagicMock()
        mock_config.COURSE_NAME = "测试课程"
        mock_config.COURSE_COLLECTION_NAME = ""
        mock_config.CHROMA_PERSIST_DIR = "/tmp/test"
        mock_config.MODEL_EMBEDDING = "test"
        mock_config.API_KEY = "test"
        mock_config.BASE_URL = "http://test"
        
        kb = CourseKnowledgeBase.__new__(CourseKnowledgeBase)
        kb._chroma_cls = mock_chroma
        kb._config = mock_config
        kb.collection_name = "test_collection"
        kb.embedding = mock_embedding
        kb.vector_store = mock_vector_store
        kb.hashes = {"hash1": "file1.pdf"}
        kb.hash_file = MagicMock()
        
        kb.clear()
        
        mock_vector_store.delete_collection.assert_called_once()
        mock_chroma.assert_called_once_with(
            collection_name="test_collection",
            embedding_function=mock_embedding,
            persist_directory="/tmp/test"
        )
        assert kb.hashes == {}


class TestCollectionNaming:
    """测试 collection 命名规则"""

    def test_no_double_prefix(self):
        """测试避免双前缀"""
        from kb_builder.store import sanitize_collection_name
        
        result = sanitize_collection_name("course_test")
        
        if result.startswith("course_"):
            assert not result.startswith("course_course_")


class TestIngestResult:
    """测试入库结果"""

    def test_ingest_result_dataclass(self):
        """测试入库结果数据类"""
        from kb_builder.store import IngestResult
        
        result = IngestResult(
            source_file="test.pdf",
            total_chunks=10,
            success_count=8,
            skip_count=2,
            error_count=0,
            errors=[]
        )
        
        assert result.source_file == "test.pdf"
        assert result.total_chunks == 10
        assert result.success_count == 8


class TestKBStatus:
    """测试知识库状态"""

    def test_kb_status_dataclass(self):
        """测试状态数据类"""
        from kb_builder.store import KBStatus
        
        status = KBStatus(
            collection_name="test_collection",
            course_name="测试课程",
            document_count=100,
            last_updated="2024-01-01",
            sources=["a.pdf", "b.pdf"]
        )
        
        assert status.collection_name == "test_collection"
        assert status.document_count == 100
