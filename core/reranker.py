"""
重排序模块 - 基于 CrossEncoder 的精排层
接收粗排候选文档，计算 query-doc 相关性分数，返回重排后的结果
"""
import warnings
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from langchain_core.documents import Document

import utils.config as config


class BaseReranker(ABC):
    """重排序器抽象基类"""

    @abstractmethod
    def rerank(self, query: str, documents: List[Document]) -> List[Tuple[Document, float]]:
        """
        对候选文档进行重排序

        Args:
            query: 用户查询
            documents: 候选文档列表

        Returns:
            [(Document, score), ...] 按 score 降序排列
        """
        pass


class CrossEncoderReranker(BaseReranker):
    """基于 sentence_transformers CrossEncoder 的本地重排序器"""

    def __init__(self, model_name: str = None, device: str = None, batch_size: int = None):
        self.model_name = model_name or config.RERANK_MODEL
        self.device = device or config.RERANK_DEVICE
        self.batch_size = batch_size or config.RERANK_BATCH_SIZE
        self._model = None
        self._load_model()

    def _load_model(self):
        """延迟加载 CrossEncoder 模型"""
        try:
            from sentence_transformers import CrossEncoder
            # CrossEncoder 不接受 'auto' 作为 device，需要转换为 None 让库自动推断
            device = None if self.device == "auto" else self.device
            print(f"[Reranker] 加载模型: {self.model_name} (device={self.device})")
            self._model = CrossEncoder(self.model_name, device=device, max_length=512)
        except Exception as e:
            warnings.warn(f"[Reranker] 加载模型失败: {e}. 将自动禁用重排序功能。")
            self._model = None

    @property
    def is_available(self) -> bool:
        return self._model is not None

    def rerank(self, query: str, documents: List[Document]) -> List[Tuple[Document, float]]:
        if not documents:
            return []

        if self._model is None:
            # fail-open：模型未加载成功时，原顺序返回并给 0 分
            return [(doc, 0.0) for doc in documents]

        try:
            pairs = [(query, doc.page_content) for doc in documents]
            scores = self._model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)

            # 按分数降序排列
            scored = list(zip(documents, [float(s) for s in scores]))
            scored.sort(key=lambda x: x[1], reverse=True)
            return scored
        except Exception as e:
            warnings.warn(f"[Reranker] 重排序失败: {e}. 退回原始顺序。")
            return [(doc, 0.0) for doc in documents]


def get_reranker() -> Optional[BaseReranker]:
    """
    根据配置获取重排序器实例
    """
    if not config.ENABLE_RERANK:
        return None
    return CrossEncoderReranker()
