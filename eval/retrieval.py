"""
检索效果评估脚本
对比纯向量检索 vs BM25混合检索的召回准确率

评估指标:
1. Recall@K: Top-K结果中相关文档的比例
2. MRR (Mean Reciprocal Rank): 第一个相关文档排名的倒数均值
3. 精确匹配率: 是否命中预期章节
"""
import json
import time
from typing import List, Dict, Tuple
from dataclasses import dataclass

from core.rag import RAGService
from core.hybrid_retriever import HybridRetriever


@dataclass
class TestCase:
    """测试用例"""
    query: str
    expected_chapters: List[str]  # 预期应该检索到的章节
    description: str


# 定义测试用例
def get_test_cases() -> List[TestCase]:
    """获取测试用例集"""
    return [
        TestCase(
            query="什么是过拟合",
            expected_chapters=["监督学习常用算法"],
            description="核心概念查询"
        ),
        TestCase(
            query="LASSO回归",
            expected_chapters=["监督学习常用算法"],
            description="算法名称查询"
        ),
        TestCase(
            query="决策树算法",
            expected_chapters=["监督学习常用算法"],
            description="分类算法查询"
        ),
        TestCase(
            query="k均值聚类",
            expected_chapters=["无监督学习算法"],
            description="聚类算法查询"
        ),
        TestCase(
            query="卷积神经网络 CNN",
            expected_chapters=["深度学习"],
            description="深度学习查询"
        ),
        TestCase(
            query="第6章 监督学习",
            expected_chapters=["监督学习常用算法"],
            description="章节号查询"
        ),
        TestCase(
            query="主成分分析 PCA",
            expected_chapters=["无监督学习算法"],
            description="降维算法查询"
        ),
        TestCase(
            query="随机森林",
            expected_chapters=["监督学习常用算法"],
            description="集成学习查询"
        ),
        TestCase(
            query="数据可视化",
            expected_chapters=["数据可视化"],
            description="可视化查询"
        ),
        TestCase(
            query="Python pandas",
            expected_chapters=["数据分析"],
            description="工具库查询"
        ),
    ]


def evaluate_retrieval(
    test_cases: List[TestCase],
    use_hybrid: bool = False,
    top_k: int = 5
) -> Dict:
    """
    评估检索效果

    Args:
        test_cases: 测试用例列表
        use_hybrid: 是否使用混合检索
        top_k: 返回结果数量

    Returns:
        评估结果字典
    """
    print(f"\n{'='*60}")
    print(f"评估 {'BM25混合检索' if use_hybrid else '纯向量检索'} (Top-{top_k})")
    print('='*60)

    # 初始化检索服务
    service = RAGService(use_hybrid=use_hybrid)

    results = {
        'method': 'hybrid' if use_hybrid else 'vector',
        'top_k': top_k,
        'test_cases': [],
        'summary': {}
    }

    total_recall = 0
    total_mrr = 0
    total_match = 0

    for tc in test_cases:
        print(f"\n查询: {tc.query}")
        print(f"  预期章节: {tc.expected_chapters}")

        start_time = time.time()
        retrieval_result = service.retrieve(tc.query, top_k=top_k)
        elapsed = time.time() - start_time

        retrieved_chapters = [
            doc.metadata.get('chapter', 'Unknown')
            for doc in retrieval_result.documents
        ]
        print(f"  检索章节: {retrieved_chapters}")
        print(f"  耗时: {elapsed:.3f}s")

        # 计算指标
        # 1. Recall@K: 检索到的相关文档数 / 预期相关文档数
        # 简化处理：只要有一个预期章节在结果中就算命中
        hit = any(
            any(exp in ret for ret in retrieved_chapters)
            for exp in tc.expected_chapters
        )
        recall = 1.0 if hit else 0.0

        # 2. MRR: 第一个相关文档的排名倒数
        mrr = 0.0
        for i, chapter in enumerate(retrieved_chapters, 1):
            if any(exp in chapter for exp in tc.expected_chapters):
                mrr = 1.0 / i
                break

        # 3. 精确匹配: Top-1是否是预期章节
        top1_match = any(
            exp in retrieved_chapters[0]
            for exp in tc.expected_chapters
        ) if retrieved_chapters else False

        print(f"  Recall@{top_k}: {recall:.2f}, MRR: {mrr:.4f}, Top-1匹配: {top1_match}")

        total_recall += recall
        total_mrr += mrr
        total_match += 1 if top1_match else 0

        results['test_cases'].append({
            'query': tc.query,
            'expected': tc.expected_chapters,
            'retrieved': retrieved_chapters,
            'recall': recall,
            'mrr': mrr,
            'top1_match': top1_match,
            'time': elapsed
        })

    # 计算平均值
    n = len(test_cases)
    results['summary'] = {
        'avg_recall': total_recall / n,
        'avg_mrr': total_mrr / n,
        'top1_accuracy': total_match / n,
        'total_queries': n
    }

    print(f"\n{'='*60}")
    print("汇总结果:")
    print(f"  平均 Recall@{top_k}: {results['summary']['avg_recall']:.4f}")
    print(f"  平均 MRR: {results['summary']['avg_mrr']:.4f}")
    print(f"  Top-1 精确匹配率: {results['summary']['top1_accuracy']:.4f}")
    print('='*60)

    return results


def compare_methods(top_k: int = 5):
    """对比两种检索方法"""
    test_cases = get_test_cases()

    print("\n" + "="*60)
    print("检索效果对比评估")
    print("="*60)
    print(f"测试用例数: {len(test_cases)}")

    # 纯向量检索
    vector_results = evaluate_retrieval(test_cases, use_hybrid=False, top_k=top_k)

    # BM25混合检索
    hybrid_results = evaluate_retrieval(test_cases, use_hybrid=True, top_k=top_k)

    # 对比结果
    print("\n" + "="*60)
    print("方法对比")
    print("="*60)

    print(f"\n指标                纯向量检索    BM25混合检索    提升")
    print("-"*60)

    metrics = [
        ('平均 Recall@{}'.format(top_k), 'avg_recall'),
        ('平均 MRR', 'avg_mrr'),
        ('Top-1 精确匹配率', 'top1_accuracy'),
    ]

    for name, key in metrics:
        v_val = vector_results['summary'][key]
        h_val = hybrid_results['summary'][key]
        improvement = ((h_val - v_val) / v_val * 100) if v_val > 0 else 0
        print(f"{name:<20} {v_val:.4f}        {h_val:.4f}         {improvement:+.1f}%")

    # 保存详细结果
    output = {
        'vector': vector_results,
        'hybrid': hybrid_results,
        'comparison': {
            'recall_improvement': hybrid_results['summary']['avg_recall'] - vector_results['summary']['avg_recall'],
            'mrr_improvement': hybrid_results['summary']['avg_mrr'] - vector_results['summary']['avg_mrr'],
            'top1_improvement': hybrid_results['summary']['top1_accuracy'] - vector_results['summary']['top1_accuracy'],
        }
    }

    with open('retrieval_eval_results.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n详细结果已保存到: retrieval_eval_results.json")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='检索效果评估')
    parser.add_argument('--top-k', type=int, default=5, help='Top-K结果数量')
    parser.add_argument('--method', choices=['vector', 'hybrid', 'both'], default='both',
                        help='评估方法: vector=纯向量, hybrid=混合, both=两者对比')

    args = parser.parse_args()

    test_cases = get_test_cases()

    if args.method == 'both':
        compare_methods(top_k=args.top_k)
    else:
        use_hybrid = (args.method == 'hybrid')
        evaluate_retrieval(test_cases, use_hybrid=use_hybrid, top_k=args.top_k)
