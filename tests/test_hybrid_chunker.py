"""
分块器测试
"""
import pytest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from course_chunker import (
    HybridChunker, ChunkType, generate_chunk_id, 
    chunk_document, filter_empty_chunks
)
from document_tree import build_document_tree, NodeType


class TestChunkID:
    """分块ID测试"""
    
    def test_chunk_id_uniqueness(self):
        """分块ID应该唯一"""
        id1 = generate_chunk_id("测试内容1", "test.pdf", "struct", 0)
        id2 = generate_chunk_id("测试内容2", "test.pdf", "struct", 1)
        
        assert id1 != id2
    
    def test_chunk_id_format(self):
        """分块ID格式测试"""
        chunk_id = generate_chunk_id("测试内容", "test.pdf", "semantic", 0)
        
        assert "semantic" in chunk_id
        assert "_" in chunk_id


class TestHybridChunker:
    """混合分块器测试"""
    
    def test_chunker_initialization(self):
        """分块器初始化测试"""
        chunker = HybridChunker()
        
        assert chunker.struct_max_size == 800
        assert chunker.semantic_size == 600
        assert chunker.shadow_size == 500
    
    def test_custom_chunk_sizes(self):
        """自定义分块大小测试"""
        chunker = HybridChunker(
            struct_max_size=500,
            semantic_size=400,
            semantic_overlap=50,
            shadow_size=300,
            shadow_overlap=30
        )
        
        assert chunker.struct_max_size == 500
        assert chunker.semantic_size == 400
        assert chunker.semantic_overlap == 50
        assert chunker.shadow_size == 300
        assert chunker.shadow_overlap == 30


class TestDocumentTree:
    """文档树测试"""
    
    def test_build_simple_tree(self):
        """构建简单文档树"""
        text = """
## 第1章 数据思维

数据科学是一门跨学科的领域。

## 1.1 什么是数据科学

数据科学是从数据中提取知识的过程。
"""
        
        tree = build_document_tree(text)
        
        assert tree.total_nodes > 0
        assert len(tree.chapters) > 0
    
    def test_chapter_extraction(self):
        """章节提取测试"""
        text = """
## 第1章 数据思维

## 第2章 数据预处理

## 第3章 数据可视化
"""
        
        tree = build_document_tree(text)
        
        assert len(tree.chapters) >= 3
    
    def test_section_extraction(self):
        """小节提取测试"""
        text = """
## 第1章 数据思维

## 1.1 什么是数据科学

## 1.2 数据科学的应用

## 第2章 数据预处理

## 2.1 数据清洗
"""
        
        tree = build_document_tree(text)
        
        assert len(tree.sections) >= 3


class TestChunkTypes:
    """分块类型测试"""
    
    def test_struct_chunk(self):
        """结构分块测试"""
        text = """
## 第1章 数据思维

数据科学是一门跨学科的领域。

## 1.1 什么是数据科学

数据科学是从数据中提取知识的过程。
"""
        
        result = chunk_document([(1, text)], "test.pdf")
        
        struct_chunks = [c for c in result.chunks if c.metadata.chunk_type == "struct"]
        
        assert len(struct_chunks) > 0, "应有结构分块"
    
    def test_shadow_chunk(self):
        """影子分块测试"""
        text = "这是测试内容。" * 100
        
        result = chunk_document([(1, text)], "test.pdf")
        
        shadow_chunks = [c for c in result.chunks if c.metadata.chunk_type == "shadow"]
        
        assert len(shadow_chunks) > 0, "应有影子分块"


class TestEmptyChunkFilter:
    """空块过滤测试"""
    
    def test_filter_empty(self):
        """过滤空块测试"""
        from course_chunker import TextChunk, ChunkMetadata
        
        chunks = [
            TextChunk(content="有效内容", metadata=ChunkMetadata(
                chunk_id="1", course="测试", source="test.pdf", chunk_type="struct",
                char_count=10, position=0
            )),
            TextChunk(content="", metadata=ChunkMetadata(
                chunk_id="2", course="测试", source="test.pdf", chunk_type="struct",
                char_count=0, position=1
            )),
            TextChunk(content="   ", metadata=ChunkMetadata(
                chunk_id="3", course="测试", source="test.pdf", chunk_type="struct",
                char_count=0, position=2
            )),
        ]
        
        filtered = filter_empty_chunks(chunks)
        
        assert len(filtered) == 1


class TestChunkMetadata:
    """分块元数据测试"""
    
    def test_metadata_fields(self):
        """元数据字段测试"""
        from course_chunker import TextChunk, ChunkMetadata
        
        chunk = TextChunk(
            content="测试内容",
            metadata=ChunkMetadata(
                chunk_id="test_001",
                course="数据科学导论",
                source="test.pdf",
                chunk_type="struct",
                heading_path="第1章 > 1.1 什么是数据科学",
                chapter="第1章 数据思维",
                chapter_no=1,
                section="1.1 什么是数据科学",
                section_no="1.1",
                page_start=1,
                page_end=2,
                source_pages=[1, 2],
                parser_source="marker",
                char_count=100,
                position=0
            )
        )
        
        assert chunk.metadata.chunk_type == "struct"
        assert chunk.metadata.heading_path == "第1章 > 1.1 什么是数据科学"
        assert chunk.metadata.chapter_no == 1
        assert chunk.metadata.section_no == "1.1"
        assert chunk.metadata.parser_source == "marker"
        assert 1 in chunk.metadata.source_pages


class TestParserSource:
    """解析器来源测试"""
    
    def test_parser_source_is_marker(self):
        """解析器来源必须是 marker"""
        from course_chunker import TextChunk, ChunkMetadata
        
        chunk = TextChunk(
            content="测试内容",
            metadata=ChunkMetadata(
                chunk_id="test_001",
                course="数据科学导论",
                source="test.pdf",
                chunk_type="struct",
                parser_source="marker",
                char_count=100,
                position=0
            )
        )
        
        assert chunk.metadata.parser_source == "marker"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
