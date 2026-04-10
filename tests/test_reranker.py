"""
重排序模块测试
"""
from unittest.mock import MagicMock, patch
from langchain_core.documents import Document

try:
    import pytest
except ModuleNotFoundError:
    pytest = None

from core.reranker import CrossEncoderReranker, get_reranker
from core.hybrid_retriever import HybridRetriever
import utils.config as config


class MockCrossEncoder:
    """Mock CrossEncoder for testing"""
    def __init__(self, *args, **kwargs):
        pass

    def predict(self, pairs, batch_size=8, show_progress_bar=False):
        # 简单的 mock 逻辑：如果文本包含 "best" 则分数高
        scores = []
        for query, text in pairs:
            if "best" in text:
                scores.append(0.9)
            elif "good" in text:
                scores.append(0.6)
            else:
                scores.append(0.1)
        return scores


def _mock_load_model(self):
    self._model = MockCrossEncoder()


def _mock_load_model_fail(self):
    self._model = None

def test_cross_encoder_rerank_changes_order():
    """测试重排序能改变文档顺序"""
    with patch.object(CrossEncoderReranker, "_load_model", _mock_load_model):
        reranker = CrossEncoderReranker(model_name="mock-model")

        docs = [
            Document(page_content="This is a normal doc"),
            Document(page_content="This is the best doc"),
            Document(page_content="This is a good doc"),
        ]

        result = reranker.rerank("query", docs)

        assert len(result) == 3
        # best 应该排到第一
        assert result[0][0].page_content == "This is the best doc"
        assert result[0][1] == 0.9
        # good 第二
        assert result[1][0].page_content == "This is a good doc"
        assert result[1][1] == 0.6


def test_cross_encoder_fail_open():
    """测试模型异常时 fail-open 返回原始顺序"""
    reranker = CrossEncoderReranker(model_name="mock-model")
    reranker._model = None  # 模拟加载失败

    docs = [
        Document(page_content="first"),
        Document(page_content="second"),
    ]

    result = reranker.rerank("query", docs)

    assert len(result) == 2
    assert result[0][0].page_content == "first"
    assert result[1][0].page_content == "second"
    assert result[0][1] == 0.0
    assert result[1][1] == 0.0


def test_get_reranker_respects_config():
    """测试 get_reranker 根据 ENABLE_RERANK 返回实例或 None"""
    original_enable = config.ENABLE_RERANK

    try:
        # 关闭时返回 None
        config.ENABLE_RERANK = False
        assert get_reranker() is None

        # 开启时返回实例（mock 掉模型加载）
        config.ENABLE_RERANK = True
        with patch.object(CrossEncoderReranker, "_load_model", _mock_load_model):
            r = get_reranker()
            assert isinstance(r, CrossEncoderReranker)
    finally:
        config.ENABLE_RERANK = original_enable


@patch("core.hybrid_retriever.chromadb.PersistentClient")
@patch("core.hybrid_retriever.OpenAIEmbeddings")
def test_hybrid_retriever_rerank_toggle(mock_embed, mock_client):
    """测试 HybridRetriever 在启用/禁用 rerank 时返回的文档数正确"""
    # mock chromadb get
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "documents": ["doc1 text", "doc2 text", "doc3 text"],
        "metadatas": [{"chunk_id": "c1"}, {"chunk_id": "c2"}, {"chunk_id": "c3"}]
    }
    mock_collection.query.return_value = {
        "documents": [["doc1 text", "doc2 text"]],
        "distances": [[0.1, 0.2]]
    }
    mock_client.return_value.get_collection.return_value = mock_collection

    # mock embed_query
    mock_embed_instance = MagicMock()
    mock_embed_instance.embed_query.return_value = [0.0] * 10
    mock_embed.return_value = mock_embed_instance

    # 关闭 rerank
    retriever_off = HybridRetriever(collection_name="test", k=2, use_rerank=False)
    docs_off = retriever_off.retrieve("test query")
    assert len(docs_off) == 2

    # 启用 rerank（mock CrossEncoder）
    with patch.object(CrossEncoderReranker, "_load_model", _mock_load_model):
        retriever_on = HybridRetriever(collection_name="test", k=2, use_rerank=True)
        docs_on = retriever_on.retrieve("test query")
        assert len(docs_on) == 2


@patch("core.hybrid_retriever.chromadb.PersistentClient")
@patch("core.hybrid_retriever.OpenAIEmbeddings")
def test_hybrid_retriever_disables_unavailable_rerank(mock_embed, mock_client):
    """当 reranker 模型不可用时，应显式回退为纯 hybrid。"""
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "documents": ["doc1 text", "doc2 text"],
        "metadatas": [{"chunk_id": "c1"}, {"chunk_id": "c2"}]
    }
    mock_collection.query.return_value = {
        "documents": [["doc1 text", "doc2 text"]],
        "distances": [[0.1, 0.2]]
    }
    mock_client.return_value.get_collection.return_value = mock_collection

    mock_embed_instance = MagicMock()
    mock_embed_instance.embed_query.return_value = [0.0] * 10
    mock_embed.return_value = mock_embed_instance

    with patch.object(CrossEncoderReranker, "_load_model", _mock_load_model_fail):
        retriever = HybridRetriever(collection_name="test", k=2, use_rerank=True)
        assert retriever.use_rerank is False
        assert retriever.reranker is None


if __name__ == "__main__":
    if pytest:
        pytest.main([__file__, "-v"])
    else:
        test_cross_encoder_rerank_changes_order()
        print("PASS: test_cross_engine_rerank_changes_order")
        test_cross_encoder_fail_open()
        print("PASS: test_cross_encoder_fail_open")
        test_get_reranker_respects_config()
        print("PASS: test_get_reranker_respects_config")
        test_hybrid_retriever_rerank_toggle()
        print("PASS: test_hybrid_retriever_rerank_toggle")
        print("All tests passed.")
