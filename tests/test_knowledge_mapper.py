"""
Knowledge Mapper 回归测试
用真实学生问题验证三层映射策略
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.knowledge_mapper import map_question_to_concepts


def test_questions():
    """
    真实学生问题测试集
    格式: (问题, 期望匹配的概念ID列表, 备注)
    """
    test_cases = [
        # === 精确匹配测试 ===
        ("什么是支持向量机？", ["svm"], "display_name 精确匹配"),
        ("SVM是什么？", ["svm"], "别名精确匹配"),
        ("核函数怎么选？", ["svm_kernel"], "核函数别名匹配"),
        ("kernel trick是什么？", ["svm_kernel"], "英文别名匹配"),

        # === 规则匹配测试 ===
        ("SVM的核函数怎么选择？", ["svm_kernel"], "正则规则: SVM.*核"),
        ("支持向量机里的核技巧怎么用？", ["svm_kernel"], "正则规则: 支持向量机.*核"),
        ("过拟合怎么处理？", ["overfitting"], "正则规则: 过拟合.*怎么"),
        ("模型泛化能力差怎么办？", ["overfitting"], "正则规则: 泛化.*差"),
        ("梯度下降的学习率怎么调？", ["gradient_descent"], "正则规则: 梯度下降.*怎么"),
        ("交叉验证怎么做？", ["cross_validation"], "正则规则: 交叉验证.*怎么"),
        ("决策树剪枝的方法？", ["decision_tree"], "正则规则: 决策树.*剪枝"),
        ("L1正则和L2正则的区别？", ["regularization"], "正则规则: L1正则|L2正则"),

        # === 语义/Embedding 兜底测试 ===
        ("SVM里的那个核是什么原理？", ["svm_kernel"], "需要embedding匹配到核函数"),
        ("怎么防止模型在训练集上记住数据？", ["overfitting"], "语义匹配到"),
        ("我想让模型在没见过数据上表现好", ["overfitting", "cross_validation"], "语义匹配泛化/验证概念"),

        # === 可能误判的边界测试 ===
        ("神经网络和SVM哪个好？", ["svm", "neural_network"], "多概念，SVM应被识别"),
        ("Python里怎么实现核函数？", ["svm_kernel"], "可能误判为代码实现而非概念"),
        ("什么是核技巧？kernel function的原理？", ["svm_kernel"], "中英混合，应识别"),
        ("数据清洗怎么做？", ["data_cleaning"], "基础概念，应精确匹配"),
        ("过拟合和欠拟合的区别？", ["overfitting"], "概念对比，应识别过拟合"),
    ]

    return test_cases


def run_regression_test():
    """运行回归测试"""
    test_cases = test_questions()

    print("=" * 80)
    print("Knowledge Mapper 回归测试")
    print("=" * 80)

    passed = 0
    failed = 0
    warnings = 0

    for question, expected_ids, note in test_cases:
        print(f"\n[测试] {question}")
        print(f"      备注: {note}")
        print(f"      期望: {expected_ids}")

        matches = map_question_to_concepts(question, top_k=3)
        actual_ids = [m.concept_id for m in matches]
        print(f"      实际: {actual_ids}")

        # 检查期望的概念是否在结果中
        missing = []
        for expected_id in expected_ids:
            if expected_id not in actual_ids:
                missing.append(expected_id)

        if not missing:
            print(f"      [OK] 通过")
            passed += 1
        else:
            print(f"      [FAIL] 失败 - 缺失: {missing}")
            failed += 1

        # 额外检查：显示匹配方法和分数
        for m in matches:
            marker = "[Y]" if m.concept_id in expected_ids else "[N]"
            print(f"         {marker} {m.concept_id}: {m.method} ({m.score})")

    print("\n" + "=" * 80)
    print(f"测试结果: 通过 {passed}/{len(test_cases)}, 失败 {failed}, 警告 {warnings}")
    print("=" * 80)

    return failed == 0


def test_edge_cases():
    """边界情况测试"""
    print("\n" + "=" * 80)
    print("边界情况测试")
    print("=" * 80)

    edge_cases = [
        ("", "空字符串"),
        ("12345", "无意义数字"),
        ("今天天气怎么样", "完全无关问题"),
        ("SVM SVM SVM 核函数 核函数", "重复关键词"),
        ("什么是什么是支持向量机机机？", "错别字/重复字"),
    ]

    for question, note in edge_cases:
        print(f"\n[边界] {note}: '{question}'")
        matches = map_question_to_concepts(question, top_k=3)
        if matches:
            print(f"      匹配到: {[(m.concept_id, m.method, m.score) for m in matches]}")
        else:
            print(f"      未匹配到任何概念（符合预期）")


if __name__ == "__main__":
    success = run_regression_test()
    test_edge_cases()

    sys.exit(0 if success else 1)
