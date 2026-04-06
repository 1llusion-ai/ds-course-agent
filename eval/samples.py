"""
评测样本模块
《数据科学导论》课程问答评测样本
"""
from dataclasses import dataclass
from typing import Optional
import json


@dataclass
class EvalSample:
    """评测样本"""
    id: str
    question: str
    category: str
    expected_keywords: list[str]
    expected_source: Optional[str] = None
    difficulty: str = "medium"


EVAL_SAMPLES: list[EvalSample] = [
    EvalSample(
        id="001",
        question="什么是数据科学？请简要介绍其定义和核心内容。",
        category="概念答疑",
        expected_keywords=["数据科学", "跨学科", "统计学", "计算机", "分析"],
        difficulty="easy"
    ),
    EvalSample(
        id="002",
        question="数据科学的主要应用领域有哪些？",
        category="概念答疑",
        expected_keywords=["应用", "商业", "医疗", "金融", "推荐"],
        difficulty="easy"
    ),
    EvalSample(
        id="003",
        question="数据挖掘的定义是什么？它包含哪些主要任务？",
        category="概念答疑",
        expected_keywords=["数据挖掘", "模式", "发现", "知识", "分类", "聚类"],
        difficulty="easy"
    ),
    EvalSample(
        id="004",
        question="机器学习和数据科学有什么关系？",
        category="概念答疑",
        expected_keywords=["机器学习", "数据科学", "算法", "模型", "预测"],
        difficulty="medium"
    ),
    EvalSample(
        id="005",
        question="什么是大数据的4V特征？请分别解释。",
        category="概念答疑",
        expected_keywords=["Volume", "Velocity", "Variety", "Value", "大量", "高速", "多样", "价值"],
        difficulty="medium"
    ),
    EvalSample(
        id="006",
        question="数据清洗的目的是什么？常见的数据质量问题有哪些？",
        category="概念答疑",
        expected_keywords=["数据清洗", "质量", "缺失", "异常", "重复", "一致性"],
        difficulty="easy"
    ),
    EvalSample(
        id="007",
        question="什么是数据可视化？它有什么作用？",
        category="概念答疑",
        expected_keywords=["可视化", "图表", "展示", "直观", "洞察"],
        difficulty="easy"
    ),
    EvalSample(
        id="008",
        question="解释什么是回归分析？它适用于什么场景？",
        category="概念答疑",
        expected_keywords=["回归", "预测", "连续", "变量", "关系"],
        difficulty="medium"
    ),
    EvalSample(
        id="009",
        question="分类和聚类有什么区别？",
        category="概念答疑",
        expected_keywords=["分类", "聚类", "监督", "无监督", "标签"],
        difficulty="medium"
    ),
    EvalSample(
        id="010",
        question="什么是特征工程？为什么它很重要？",
        category="概念答疑",
        expected_keywords=["特征", "工程", "提取", "选择", "转换", "模型"],
        difficulty="medium"
    ),
    EvalSample(
        id="011",
        question="数据科学项目的一般流程是什么？",
        category="学习方法",
        expected_keywords=["流程", "收集", "清洗", "分析", "建模", "部署"],
        difficulty="medium"
    ),
    EvalSample(
        id="012",
        question="如何学习数据科学？有什么建议？",
        category="学习方法",
        expected_keywords=["学习", "编程", "统计", "实践", "项目", "Python"],
        difficulty="easy"
    ),
    EvalSample(
        id="013",
        question="数据科学家需要掌握哪些技能？",
        category="学习方法",
        expected_keywords=["技能", "编程", "统计", "机器学习", "沟通", "Python"],
        difficulty="easy"
    ),
    EvalSample(
        id="014",
        question="推荐一些数据科学的学习资源？",
        category="学习方法",
        expected_keywords=["资源", "课程", "书籍", "网站", "实践"],
        difficulty="easy"
    ),
    EvalSample(
        id="015",
        question="Python在数据科学中有什么优势？",
        category="概念答疑",
        expected_keywords=["Python", "库", "易学", "社区", "Pandas", "NumPy"],
        difficulty="easy"
    ),
    EvalSample(
        id="016",
        question="什么是监督学习？举例说明。",
        category="概念答疑",
        expected_keywords=["监督学习", "标签", "训练", "分类", "回归"],
        difficulty="easy"
    ),
    EvalSample(
        id="017",
        question="什么是无监督学习？它有哪些应用？",
        category="概念答疑",
        expected_keywords=["无监督", "聚类", "降维", "标签", "发现"],
        difficulty="easy"
    ),
    EvalSample(
        id="018",
        question="什么是过拟合？如何防止过拟合？",
        category="概念答疑",
        expected_keywords=["过拟合", "泛化", "训练", "正则化", "交叉验证"],
        difficulty="medium"
    ),
    EvalSample(
        id="019",
        question="什么是交叉验证？为什么需要交叉验证？",
        category="概念答疑",
        expected_keywords=["交叉验证", "验证", "模型", "评估", "K折"],
        difficulty="medium"
    ),
    EvalSample(
        id="020",
        question="数据预处理包括哪些步骤？",
        category="概念答疑",
        expected_keywords=["预处理", "清洗", "转换", "标准化", "归一化", "编码"],
        difficulty="easy"
    ),
    EvalSample(
        id="021",
        question="什么是特征选择？有哪些方法？",
        category="概念答疑",
        expected_keywords=["特征选择", "相关性", "重要性", "降维", "过滤", "包装"],
        difficulty="medium"
    ),
    EvalSample(
        id="022",
        question="解释什么是决策树？它如何工作？",
        category="概念答疑",
        expected_keywords=["决策树", "节点", "分支", "分类", "规则", "分裂"],
        difficulty="easy"
    ),
    EvalSample(
        id="023",
        question="什么是随机森林？它有什么优点？",
        category="概念答疑",
        expected_keywords=["随机森林", "集成", "决策树", "投票", "准确"],
        difficulty="medium"
    ),
    EvalSample(
        id="024",
        question="神经网络的基本原理是什么？",
        category="概念答疑",
        expected_keywords=["神经网络", "神经元", "权重", "激活", "层", "反向传播"],
        difficulty="medium"
    ),
    EvalSample(
        id="025",
        question="什么是深度学习？它与传统机器学习有什么区别？",
        category="概念答疑",
        expected_keywords=["深度学习", "神经网络", "多层", "特征", "自动"],
        difficulty="easy"
    ),
    EvalSample(
        id="026",
        question="数据科学中常用的Python库有哪些？",
        category="学习方法",
        expected_keywords=["NumPy", "Pandas", "Matplotlib", "Scikit-learn", "TensorFlow"],
        difficulty="easy"
    ),
    EvalSample(
        id="027",
        question="如何评估分类模型的性能？",
        category="概念答疑",
        expected_keywords=["准确率", "精确率", "召回率", "F1", "混淆矩阵", "ROC"],
        difficulty="medium"
    ),
    EvalSample(
        id="028",
        question="什么是降维？有哪些常用的降维方法？",
        category="概念答疑",
        expected_keywords=["降维", "PCA", "特征", "维度", "压缩", "可视化"],
        difficulty="medium"
    ),
    EvalSample(
        id="029",
        question="数据伦理在数据科学中为什么重要？",
        category="概念答疑",
        expected_keywords=["伦理", "隐私", "偏见", "公平", "责任"],
        difficulty="medium"
    ),
    EvalSample(
        id="030",
        question="什么是自然语言处理？它在数据科学中的应用？",
        category="概念答疑",
        expected_keywords=["自然语言处理", "NLP", "文本", "情感", "分类", "生成"],
        difficulty="medium"
    ),
]


def get_eval_samples() -> list[EvalSample]:
    """获取所有评测样本"""
    return EVAL_SAMPLES


def get_samples_by_category(category: str) -> list[EvalSample]:
    """按类别获取评测样本"""
    return [s for s in EVAL_SAMPLES if s.category == category]


def export_samples_to_json(filepath: str):
    """导出样本到JSON文件"""
    data = [
        {
            "id": s.id,
            "question": s.question,
            "category": s.category,
            "expected_keywords": s.expected_keywords,
            "expected_source": s.expected_source,
            "difficulty": s.difficulty,
        }
        for s in EVAL_SAMPLES
    ]
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    print(f"共有 {len(EVAL_SAMPLES)} 条评测样本")
    
    categories = set(s.category for s in EVAL_SAMPLES)
    for cat in categories:
        count = len(get_samples_by_category(cat))
        print(f"  - {cat}: {count} 条")
