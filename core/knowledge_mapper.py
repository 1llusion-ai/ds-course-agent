"""
知识点映射模块
将自然语言问题映射到标准知识点（canonical_id）
采用三层匹配策略：精确匹配 -> 规则匹配 -> Embedding兜底
"""
import json
import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class MatchedConcept:
    """匹配结果"""
    concept_id: str
    display_name: str
    chapter: str
    method: str  # exact_alias / regex_rule / embedding
    score: float


class KnowledgeGraph:
    """知识图谱加载与查询"""

    def __init__(self, graph_path: Optional[str] = None):
        if graph_path is None:
            graph_path = Path(__file__).parent.parent / "data" / "knowledge_graph.json"

        with open(graph_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.concepts: Dict[str, Dict] = {}
        self.alias_to_concept: Dict[str, str] = {}  # alias -> canonical_id
        self.embeddings: Dict[str, np.ndarray] = {}  # canonical_id -> embedding vector

        for concept in data["concepts"]:
            cid = concept["canonical_id"]
            self.concepts[cid] = concept

            # 构建别名映射
            for alias in concept["aliases"]:
                normalized_alias = self._normalize_text(alias)
                self.alias_to_concept[normalized_alias] = cid

        # 预编译正则规则（在精确匹配之后应用）
        self.regex_rules = self._build_regex_rules()

        # 预计算 embedding（如果可用）
        self._precompute_embeddings()

    def _normalize_text(self, text: str) -> str:
        """文本归一化：去标点、小写、统一空格"""
        text = re.sub(r'[^\w\s]', '', text.lower())
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _build_regex_rules(self) -> List[Tuple[re.Pattern, str]]:
        """
        构建正则规则
        """
        rules = []

        # SVM 相关
        rules.append((re.compile(r'svm.*核|支持向量机.*核|svm.*kernel', re.I), "svm_kernel"))
        rules.append((re.compile(r'核函数.*svm|核技巧.*svm', re.I), "svm_kernel"))

        # 过拟合相关
        rules.append((re.compile(r'过拟合.*怎么|overfitting.*|泛化.*差', re.I), "overfitting"))

        # 交叉验证相关
        rules.append((re.compile(r'交叉验证.*怎么|k折|k-fold.*怎么', re.I), "cross_validation"))

        # 梯度下降相关
        rules.append((re.compile(r'梯度下降.*怎么|学习率.*怎么|sgd.*怎么', re.I), "gradient_descent"))

        # 决策树相关
        rules.append((re.compile(r'决策树.*剪枝|信息熵.*怎么|信息增益.*', re.I), "decision_tree"))

        # 正则化相关
        rules.append((re.compile(r'正则化.*怎么|l1正则|l2正则|岭回归.*lasso', re.I), "regularization"))

        return rules

    def _precompute_embeddings(self):
        """预计算知识图谱中所有概念的 embedding"""
        try:
            # 尝试使用本地 embedding 模型
            from utils.config import MODEL_EMBEDDING, API_KEY, BASE_URL
            from langchain_openai import OpenAIEmbeddings

            embedding_model = OpenAIEmbeddings(
                model=MODEL_EMBEDDING,
                api_key=API_KEY,
                base_url=BASE_URL,
                tiktoken_enabled=False,
                check_embedding_ctx_length=False,
            )

            # 为每个概念的 display_name + aliases 生成 embedding
            for cid, concept in self.concepts.items():
                # 组合文本：display_name + 主要别名
                text = concept["display_name"] + " " + " ".join(concept["aliases"][:3])
                try:
                    embedding = embedding_model.embed_query(text)
                    self.embeddings[cid] = np.array(embedding)
                except Exception as e:
                    print(f"[KnowledgeGraph] Embedding failed for {cid}: {e}")

            print(f"[KnowledgeGraph] Precomputed {len(self.embeddings)} embeddings")

        except Exception as e:
            print(f"[KnowledgeGraph] Embedding model not available: {e}")

    def get_concept(self, concept_id: str) -> Optional[Dict]:
        """获取概念详情"""
        return self.concepts.get(concept_id)

    def get_embedding(self, concept_id: str) -> Optional[np.ndarray]:
        """获取概念预计算embedding"""
        return self.embeddings.get(concept_id)


class KnowledgeMapper:
    """知识点映射器"""

    def __init__(self, graph: Optional[KnowledgeGraph] = None):
        self.graph = graph or KnowledgeGraph()
        self._embedding_model = None

    def _get_embedding_model(self):
        """延迟加载 embedding 模型"""
        if self._embedding_model is None:
            from utils.config import MODEL_EMBEDDING, API_KEY, BASE_URL
            from langchain_openai import OpenAIEmbeddings

            self._embedding_model = OpenAIEmbeddings(
                model=MODEL_EMBEDDING,
                api_key=API_KEY,
                base_url=BASE_URL,
                tiktoken_enabled=False,
                check_embedding_ctx_length=False,
            )
        return self._embedding_model

    def _embed_text(self, text: str) -> np.ndarray:
        """获取文本 embedding"""
        model = self._get_embedding_model()
        embedding = model.embed_query(text)
        return np.array(embedding)

    def _cosine_similarity(self, v1: np.ndarray, v2: np.ndarray) -> float:
        """计算余弦相似度"""
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(v1, v2) / (norm1 * norm2))

    def map_question(self, question: str, top_k: int = 3,
                     embedding_threshold: float = 0.82) -> List[MatchedConcept]:
        """
        三层匹配策略：
        1. 别名精确匹配（含归一化）
        2. 正则规则匹配
        3. Embedding语义匹配（兜底）

        Args:
            question: 用户问题
            top_k: 返回最大匹配数
            embedding_threshold: embedding匹配阈值

        Returns:
            MatchedConcept列表，按score降序
        """
        matches = []
        matched_ids = set()

        # ===== Layer 1: 别名精确匹配 =====
        normalized = self.graph._normalize_text(question)

        # 直接匹配
        if normalized in self.graph.alias_to_concept:
            cid = self.graph.alias_to_concept[normalized]
            concept = self.graph.get_concept(cid)
            matches.append(MatchedConcept(
                concept_id=cid,
                display_name=concept["display_name"],
                chapter=concept["chapter"],
                method="exact_alias",
                score=1.0
            ))
            matched_ids.add(cid)

        # 子串匹配（用于长问题中提取概念）
        for alias, cid in self.graph.alias_to_concept.items():
            if cid in matched_ids:
                continue
            if alias in normalized or normalized in alias:
                concept = self.graph.get_concept(cid)
                # 子串匹配 score 根据长度比例计算
                score = min(len(alias), len(normalized)) / max(len(alias), len(normalized))
                if score >= 0.5:  # 子串匹配阈值（>=0.5 捕获"核函数"->"核函数怎么选"）
                    matches.append(MatchedConcept(
                        concept_id=cid,
                        display_name=concept["display_name"],
                        chapter=concept["chapter"],
                        method="exact_alias",
                        score=round(score, 2)
                    ))
                    matched_ids.add(cid)

        # ===== Layer 2: 正则规则匹配 =====
        for pattern, cid in self.graph.regex_rules:
            if cid in matched_ids:
                continue
            if pattern.search(question):
                concept = self.graph.get_concept(cid)
                matches.append(MatchedConcept(
                    concept_id=cid,
                    display_name=concept["display_name"],
                    chapter=concept["chapter"],
                    method="regex_rule",
                    score=0.95
                ))
                matched_ids.add(cid)

        # ===== Layer 3: Embedding语义匹配（兜底）=====
        # 只有当精确匹配不足 top_k 时才使用
        if len(matches) < top_k and self.graph.embeddings:
            try:
                query_vec = self._embed_text(question)

                embedding_matches = []
                for cid, concept_vec in self.graph.embeddings.items():
                    if cid in matched_ids:
                        continue
                    sim = self._cosine_similarity(query_vec, concept_vec)
                    if sim > embedding_threshold:
                        concept = self.graph.get_concept(cid)
                        embedding_matches.append(MatchedConcept(
                            concept_id=cid,
                            display_name=concept["display_name"],
                            chapter=concept["chapter"],
                            method="embedding",
                            score=round(sim, 3)
                        ))

                # 按相似度排序，补充到 matches
                embedding_matches.sort(key=lambda x: x.score, reverse=True)
                matches.extend(embedding_matches[:top_k - len(matches)])

            except Exception as e:
                print(f"[KnowledgeMapper] Embedding match failed: {e}")

        # 最终排序，取 top_k
        matches.sort(key=lambda x: x.score, reverse=True)
        return matches[:top_k]

    def get_related_concepts(self, concept_id: str) -> List[str]:
        """获取相关概念列表"""
        concept = self.graph.get_concept(concept_id)
        if concept:
            return concept.get("related_concepts", [])
        return []


# 全局单例
_knowledge_mapper: Optional[KnowledgeMapper] = None


def get_knowledge_mapper() -> KnowledgeMapper:
    """获取知识点映射器单例"""
    global _knowledge_mapper
    if _knowledge_mapper is None:
        _knowledge_mapper = KnowledgeMapper()
    return _knowledge_mapper


def map_question_to_concepts(question: str, top_k: int = 3) -> List[MatchedConcept]:
    """
    便捷函数：将问题映射到知识点

    Returns:
        MatchedConcept列表，按匹配分数降序
    """
    mapper = get_knowledge_mapper()
    return mapper.map_question(question, top_k)


if __name__ == "__main__":
    # 测试
    mapper = get_knowledge_mapper()

    test_questions = [
        "什么是支持向量机？",
        "SVM的核函数怎么选？",
        "核技巧是什么？",
        "kernel trick的原理",
        "过拟合怎么处理？",
        "梯度下降的学习率怎么调？"
    ]

    for q in test_questions:
        print(f"\n问题: {q}")
        matches = mapper.map_question(q)
        for m in matches:
            print(f"  -> {m.display_name} ({m.concept_id}) | {m.method} | score={m.score}")
