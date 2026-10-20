"""
课程知识库存储测试
"""

from unittest.mock import MagicMock, patch

import pytest


class TestSanitizeCollectionName:
    """测试 collection 名称规范化"""

    def test_sanitize_chinese_name(self):
        """测试中文名称转换"""
        from ds_course_agent.kb.store import sanitize_collection_name

        result = sanitize_collection_name("数据科学导论")

        assert len(result) >= 3
        assert result[0].isalnum()
        assert result[-1].isalnum()
        assert all(c.isalnum() or c in "._-" for c in result)

    def test_sanitize_english_name(self):
        """测试英文名称"""
        from ds_course_agent.kb.store import sanitize_collection_name

        result = sanitize_collection_name("Data Science Introduction")

        assert "Data" in result or "data" in result.lower()
        assert result[0].isalnum()
        assert result[-1].isalnum()

    def test_sanitize_empty_name(self):
        """测试空名称"""
        from ds_course_agent.kb.store import sanitize_collection_name

        result = sanitize_collection_name("")

        assert result == "course_default"

    def test_sanitize_special_chars(self):
        """测试特殊字符"""
        from ds_course_agent.kb.store import sanitize_collection_name

        result = sanitize_collection_name("test@#$%name!")

        assert "@" not in result
        assert "#" not in result
        assert "$" not in result
        assert result[0].isalnum()
        assert result[-1].isalnum()

    def test_sanitize_long_name(self):
        """测试超长名称"""
        from ds_course_agent.kb.store import sanitize_collection_name

        long_name = "a" * 600
        result = sanitize_collection_name(long_name)

        assert len(result) <= 512
        assert result[-1].isalnum()

    def test_sanitize_short_name(self):
        """测试过短名称"""
        from ds_course_agent.kb.store import sanitize_collection_name

        result = sanitize_collection_name("ab")

        assert len(result) >= 3


class TestCourseKnowledgeBase:
    """测试课程知识库类"""

    def test_collection_name_logic(self):
        """测试 collection 名称逻辑"""
        from ds_course_agent.kb.store import sanitize_collection_name

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
        from ds_course_agent.kb.store import CourseKnowledgeBase

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
            collection_name="test_collection", embedding_function=mock_embedding, persist_directory="/tmp/test"
        )
        assert kb.hashes == {}

    def test_constructor_binds_explicit_candidate_collection_and_persist_directory(self, monkeypatch, tmp_path):
        from ds_course_agent.kb.store import CourseKnowledgeBase

        mock_chroma = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("langchain_chroma.Chroma", mock_chroma)
        monkeypatch.setattr("ds_course_agent.shared.embeddings.create_embedding_model", MagicMock())

        kb = CourseKnowledgeBase(
            "数字素养与技能导论",
            collection_name="candidate_digital_literacy",
            persist_directory=str(tmp_path / "candidate"),
            embedding_model="Qwen/Qwen3-Embedding-8B",
        )

        assert kb.collection_name == "candidate_digital_literacy"
        assert kb.persist_directory == str(tmp_path / "candidate")
        mock_chroma.assert_called_once()
        assert mock_chroma.call_args.kwargs["collection_name"] == "candidate_digital_literacy"
        assert mock_chroma.call_args.kwargs["persist_directory"] == str(tmp_path / "candidate")

    def test_constructor_passes_collection_distance_metadata(self, monkeypatch, tmp_path):
        from ds_course_agent.kb.store import CourseKnowledgeBase

        mock_chroma = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("langchain_chroma.Chroma", mock_chroma)
        monkeypatch.setattr("ds_course_agent.shared.embeddings.create_embedding_model", MagicMock())

        CourseKnowledgeBase(
            "数字素养与技能导论",
            collection_name="candidate_cosine",
            persist_directory=str(tmp_path / "candidate"),
            collection_metadata={"hnsw:space": "cosine"},
        )

        assert mock_chroma.call_args.kwargs["collection_metadata"] == {"hnsw:space": "cosine"}


class TestCollectionNaming:
    """测试 collection 命名规则"""

    def test_no_double_prefix(self):
        """测试避免双前缀"""
        from ds_course_agent.kb.store import sanitize_collection_name

        result = sanitize_collection_name("course_test")

        if result.startswith("course_"):
            assert not result.startswith("course_course_")


class TestIngestResult:
    """测试入库结果"""

    def test_ingest_result_dataclass(self):
        """测试入库结果数据类"""
        from ds_course_agent.kb.store import IngestResult

        result = IngestResult(
            source_file="test.pdf", total_chunks=10, success_count=8, skip_count=2, error_count=0, errors=[]
        )

        assert result.source_file == "test.pdf"
        assert result.total_chunks == 10
        assert result.success_count == 8


class TestMetadataBuild:
    """测试入库 metadata 页码语义。"""

    def test_v2_metadata_uses_book_pages_for_public_page_fields(self):
        from ds_course_agent.kb.chunker import ChunkMetadataV2, ChunkV2
        from ds_course_agent.kb.store import CourseKnowledgeBase

        kb = CourseKnowledgeBase.__new__(CourseKnowledgeBase)
        kb.course_name = "数据科学导论"

        chunk = ChunkV2(
            content="2.2 数据科学",
            metadata=ChunkMetadataV2(
                source_file="book.pdf",
                parser_source="marker",
                source_pages=[28],
                book_pages=[20],
                chunk_type="semantic",
                chapter="数据科学基本知识",
                chapter_number="第2章",
                section="数据科学",
                section_number="2.2",
                subsection="数据科学的概念",
                subsection_number="2.2.1",
            ),
        )

        metadata = kb._build_metadata(chunk)

        assert metadata["page"] == 20
        assert metadata["book_page"] == 20
        assert metadata["source_page"] == 28
        assert metadata["source_pages"] == "[28]"
        assert metadata["book_pages"] == "[20]"
        assert metadata["chapter_no"] == "第2章"
        assert metadata["chapter"] == "数据科学基本知识"
        assert metadata["parser_source"] == "marker"

    def test_embedding_text_includes_heading_path_without_changing_evidence(self):
        from ds_course_agent.kb.chunker import ChunkMetadataV2, ChunkV2
        from ds_course_agent.kb.store import CourseKnowledgeBase

        kb = CourseKnowledgeBase.__new__(CourseKnowledgeBase)
        heading = "第1章 数字素养 > 1.1 数字时代 > 1.1.6 数字鸿沟"
        chunk = ChunkV2(
            content="数字鸿沟会造成数字技能和资源获取机会的差异。",
            metadata=ChunkMetadataV2(heading_path=heading),
        )

        embedding_text = kb._embedding_text(chunk)

        assert embedding_text.startswith(heading + "\n\n")
        assert embedding_text.endswith(chunk.content)
        assert embedding_text.count(chunk.content) == 1

    def test_embedding_text_does_not_duplicate_an_existing_heading(self):
        from ds_course_agent.kb.chunker import ChunkMetadataV2, ChunkV2
        from ds_course_agent.kb.store import CourseKnowledgeBase

        kb = CourseKnowledgeBase.__new__(CourseKnowledgeBase)
        heading = "第1章 数字素养 > 1.1 数字时代 > 1.1.6 数字鸿沟"
        content = f"{heading}\n\n正文"
        chunk = ChunkV2(content=content, metadata=ChunkMetadataV2(heading_path=heading))

        assert kb._embedding_text(chunk) == content

    def test_reference_embedding_text_has_document_type_label_only_in_vector_input(self):
        from ds_course_agent.kb.chunker import ChunkMetadataV2, ChunkV2
        from ds_course_agent.kb.store import CourseKnowledgeBase

        kb = CourseKnowledgeBase.__new__(CourseKnowledgeBase)
        kb.course_name = "数字素养与技能导论"
        content = "[1] 数字素养与技能研究报告。 https://example.test/source"
        chunk = ChunkV2(
            content=content,
            metadata=ChunkMetadataV2(
                chapter="参考文献",
                heading_path="参考文献",
                source_file="digital-literacy.pdf",
                chunk_type="semantic",
            ),
        )

        embedding_text = kb._embedding_text(chunk)
        metadata = kb._build_metadata(chunk)

        assert embedding_text.startswith("参考文献条目列表（来源索引）\n\n参考文献")
        assert embedding_text.count(content) == 1
        assert metadata["heading_path"] == "参考文献"
        assert content not in metadata["heading_path"]

    def test_non_reference_embedding_text_has_no_document_type_label(self):
        from ds_course_agent.kb.chunker import ChunkMetadataV2, ChunkV2
        from ds_course_agent.kb.store import CourseKnowledgeBase

        kb = CourseKnowledgeBase.__new__(CourseKnowledgeBase)
        chunk = ChunkV2(
            content="数字鸿沟会造成资源获取机会差异。",
            metadata=ChunkMetadataV2(
                chapter="数字素养",
                heading_path="第1章 数字素养 > 1.1 数字时代 > 1.1.6 数字鸿沟",
            ),
        )

        embedding_text = kb._embedding_text(chunk)

        assert "参考文献条目列表（来源索引）" not in embedding_text
        assert embedding_text.startswith("第1章 数字素养 > 1.1 数字时代 > 1.1.6 数字鸿沟")

    def test_v2_metadata_keeps_front_matter_without_book_page(self):
        from ds_course_agent.kb.chunker import ChunkMetadataV2, ChunkV2
        from ds_course_agent.kb.store import CourseKnowledgeBase

        kb = CourseKnowledgeBase.__new__(CourseKnowledgeBase)
        kb.course_name = "数据科学导论"

        chunk = ChunkV2(
            content="封面",
            metadata=ChunkMetadataV2(
                source_file="book.pdf",
                source_pages=[1],
                book_pages=[],
                chunk_type="semantic",
            ),
        )

        metadata = kb._build_metadata(chunk)

        assert metadata["source_page"] == 1
        assert metadata["source_pages"] == "[1]"
        assert "page" not in metadata
        assert "book_page" not in metadata
        assert "book_pages" not in metadata

    def test_v2_metadata_carries_candidate_provenance_context(self):
        from ds_course_agent.kb.chunker import ChunkMetadataV2, ChunkV2
        from ds_course_agent.kb.store import CourseKnowledgeBase

        kb = CourseKnowledgeBase.__new__(CourseKnowledgeBase)
        kb.course_name = "数字素养与技能导论"
        kb.metadata_context = {
            "course_id": "digital-literacy",
            "resource_version": "sha256-test",
            "source_sha256": "a" * 64,
            "collection_revision": "b" * 64,
        }

        chunk = ChunkV2(
            content="数字素养",
            metadata=ChunkMetadataV2(source_file="book.pdf", source_pages=[17], book_pages=[1]),
        )

        metadata = kb._build_metadata(chunk)

        assert metadata["course_id"] == "digital-literacy"
        assert metadata["resource_version"] == "sha256-test"
        assert metadata["source_sha256"] == "a" * 64
        assert metadata["collection_revision"] == "b" * 64


class TestKBStatus:
    """测试知识库状态"""

    def test_kb_status_dataclass(self):
        """测试状态数据类"""
        from ds_course_agent.kb.store import KBStatus

        status = KBStatus(
            collection_name="test_collection",
            course_name="测试课程",
            document_count=100,
            last_updated="2024-01-01",
            sources=["a.pdf", "b.pdf"],
        )

        assert status.collection_name == "test_collection"
        assert status.document_count == 100
