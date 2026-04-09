"""
半自动检索评测样本生成器
基于 knowledge_graph.json 和 ChromaDB 内容自动标注 ground-truth chunk_id
"""
import json
import sys
from pathlib import Path
import chromadb
from typing import List, Dict
from dataclasses import dataclass, asdict

sys.path.insert(0, str(Path(__file__).parent.parent))

import utils.config as config


@dataclass
class RetrievalQAPair:
    id: str
    query: str
    category: str  # semantic | term | code_abbr
    ground_truth_ids: List[str]
    concept_id: str
    concept_name: str
    annotation_rule: str


CATEGORY_MAPPING = {
    "semantic": [
        "data_science_definition", "\ufeffdata_thinking", "overfitting", "data_visualization",
        "supervised_learning", "unsupervised_learning", "data_insight", "digital_economy",
        "ensemble_learning", "classification_problem", "clustering", "dimensionality_reduction",
        "natural_language_processing", "deep_learning_tasks", "eda", "text_mining",
        "cross_validation", "regularization", "model_evaluation", "neural_network"
    ],
    "term": [
        "dikw_pyramid", "technology_hype_cycle", "big_data_4v", "digitization",
        "data_fusion", "feature_discovery", "intelligent_manufacturing", "technology_forecasting",
        "data_businessization", "data_collection", "data_cleaning", "missing_values",
        "groupby_aggregation", "data_merge", "descriptive_statistics", "hypothesis_testing",
        "probability", "kaggle", "feature_engineering", "competition_workflow"
    ],
    "code_abbr": [
        "python_language", "pandas", "dataframe", "series", "loc_iloc",
        "svm", "pca", "knn", "lstm", "scikit_learn"
    ]
}


def load_knowledge_graph(path: str = "data/knowledge_graph.json") -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_client():
    return chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)


def find_relevant_chunks(query_keywords: List[str], top_k: int = 3) -> List[str]:
    """
    基于关键词在 ChromaDB 中查找相关 semantic chunks。
    策略：获取 collection 中所有文档，过滤包含关键词的 semantic chunks。
    """
    client = get_client()
    collection = client.get_collection(config.collection_name)
    # 为避免加载全部文档导致内存问题，先用向量检索召回候选池
    from langchain_openai import OpenAIEmbeddings
    embedding = OpenAIEmbeddings(
        model=config.MODEL_EMBEDDING,
        api_key=config.API_KEY,
        base_url=config.BASE_URL,
        tiktoken_enabled=False,
        check_embedding_ctx_length=False,
    )
    query_text = " ".join(query_keywords)
    q_emb = embedding.embed_query(query_text)
    results = collection.query(
        query_embeddings=[q_emb],
        n_results=30,
        include=["documents", "metadatas"]
    )

    matched = []
    fallback = []
    if results["documents"] and results["documents"][0]:
        for doc_text, meta in zip(results["documents"][0], results["metadatas"][0]):
            if meta.get("chunk_type") != "semantic":
                continue
            chunk_id = meta.get("chunk_id")
            if not chunk_id:
                continue
            fallback.append((chunk_id, len(doc_text)))
            text_lower = doc_text.lower()
            # 至少命中一个关键词（不区分大小写）
            if any(kw.lower() in text_lower for kw in query_keywords):
                matched.append((chunk_id, len(doc_text)))

    # 如果关键词未命中，回退到向量检索的 top_k semantic chunks
    source = matched if matched else fallback

    # 去重并按文档长度降序（通常长文档包含更完整解释）
    seen = set()
    unique = []
    for cid, length in sorted(source, key=lambda x: x[1], reverse=True):
        if cid not in seen:
            seen.add(cid)
            unique.append(cid)

    return unique[:top_k]


def generate_qa_pairs() -> List[RetrievalQAPair]:
    kg = load_knowledge_graph()
    concepts = {c["canonical_id"]: c for c in kg["concepts"]}
    pairs = []
    idx = 1
    for category, concept_ids in CATEGORY_MAPPING.items():
        for cid in concept_ids:
            concept = concepts.get(cid)
            if not concept:
                continue
            aliases = concept["aliases"]
            display = concept["display_name"]
            # 选择最合适的 query：优先用中文别名，再用英文
            query_candidates = [a for a in aliases if any("\u4e00" <= ch <= "\u9fff" for ch in a)]
            if not query_candidates:
                query_candidates = aliases
            query = query_candidates[0]

            #  ground truth 标注
            keywords = [display] + aliases[:2]
            gt_ids = find_relevant_chunks(keywords, top_k=3)

            pairs.append(RetrievalQAPair(
                id=f"{idx:03d}",
                query=query,
                category=category,
                ground_truth_ids=gt_ids,
                concept_id=cid,
                concept_name=display,
                annotation_rule=f"keywords_in_content: {keywords}"
            ))
            idx += 1
    return pairs


def save_json(pairs: List[RetrievalQAPair], path: str = "eval/data/retrieval_qa_pairs.json"):
    data = [asdict(p) for p in pairs]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"qa_pairs": data}, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(pairs)} QA pairs to {path}")


if __name__ == "__main__":
    pairs = generate_qa_pairs()
    save_json(pairs)
