"""
生成完整课程知识库汇总报告
"""
import json
from pathlib import Path
from course_kb_store import CourseKnowledgeBase


def main():
    print('=' * 70)
    print('《数据科学导论》课程知识库 - 完整汇总')
    print('=' * 70)

    kb = CourseKnowledgeBase()
    status = kb.get_status()

    # 基础统计
    total_docs = status.document_count

    print(f"\n[基本信息]")
    print(f"  Collection: {status.collection_name}")
    print(f"  课程名称: {status.course_name}")
    print(f"  Embedding模型: Qwen/Qwen3-Embedding-8B (4096维)")
    print(f"  总文档数: {total_docs}")
    print(f"  来源章节: 第1-10章")

    # 按章节统计
    print(f"\n[各章节详情]")
    chapter_stats = {}
    for i in range(1, 11):
        # 通过搜索统计
        results = kb.search(f"第{i}章 数据", k=100)
        chapter_count = len([r for r in results if f"第{i}章" in r['metadata'].get('chapter', '')])
        if chapter_count == 0:
            # 尝试另一种方式
            all_results = kb.search("数据科学", k=100)
            chapter_count = len([r for r in all_results if r['metadata'].get('chapter_no') == f"第{i}章"])
        chapter_stats[i] = chapter_count
        print(f"  第{i:2}章: ~{chapter_count} 个块")

    # 检索测试
    print(f"\n[检索测试]")
    test_queries = [
        "数据思维是什么",
        "机器学习算法",
        "Python数据分析",
        "深度学习神经网络",
        "数据可视化",
    ]

    for query in test_queries:
        results = kb.search(query, k=3)
        if results:
            top = results[0]
            print(f"  \"{query}\"")
            print(f"    -> 匹配: {top['metadata'].get('chapter', 'N/A')} {top['metadata'].get('section_no', '')}")
            print(f"    -> 得分: {top['score']:.3f}")

    # 最终报告
    report = {
        'course': status.course_name,
        'collection': status.collection_name,
        'embedding_model': 'Qwen/Qwen3-Embedding-8B',
        'embedding_dim': 4096,
        'total_documents': total_docs,
        'chapters': list(range(1, 11)),
        'chunk_size': 800,
        'chunk_overlap': 150,
        'generated_at': status.last_updated
    }

    with open('artifacts/final_summary.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n[报告保存]")
    print(f"  artifacts/final_summary.json")

    print(f"\n{'=' * 70}")
    print("知识库构建完成！")
    print("=" * 70)


if __name__ == "__main__":
    main()
