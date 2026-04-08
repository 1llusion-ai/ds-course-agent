"""运行完整评测"""
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from eval.metrics.retrieval import RetrievalMetrics, calculate_recall_at_k, calculate_precision_at_k, calculate_mrr, calculate_ndcg_at_k
from eval.metrics.answer import evaluate_answer
from core.rag import RAGService


class BenchmarkRunner:
    def __init__(self):
        self.rag_service = RAGService()
        self.results = []

    def load_qa_pairs(self, path: str = "eval/data/qa_pairs.json"):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("qa_pairs", [])

    def evaluate_single(self, qa_pair: dict) -> dict:
        question = qa_pair["question"]
        print(f"\n评测: {question[:40]}...")

        # 检索
        retrieved_docs = self.rag_service.retrieve(question, top_k=3)

        # 生成回答
        answer = self.rag_service.answer_with_context(question, retrieved_docs)

        # 评估检索
        ground_truth = qa_pair.get("ground_truth", {})
        retrieved_ids = [d.metadata.get("id", str(i)) for i, d in enumerate(retrieved_docs)]

        # 评估回答
        answer_metrics = evaluate_answer(
            question=question,
            answer=answer,
            expected_keywords=qa_pair.get("expected_keywords", [])
        )

        result = {
            "id": qa_pair["id"],
            "question": question,
            "answer": answer[:200] + "..." if len(answer) > 200 else answer,
            "answer_quality": {
                "relevance": answer_metrics.relevance_score,
                "completeness": answer_metrics.completeness_score,
                "correctness": answer_metrics.correctness_score,
                "has_source": answer_metrics.has_source,
                "keyword_coverage": answer_metrics.keyword_coverage,
                "avg_score": answer_metrics.avg_score
            }
        }

        print(f"  回答平均分: {answer_metrics.avg_score:.2%}")
        return result

    def run(self, output_path: str = None):
        qa_pairs = self.load_qa_pairs()
        print(f"开始评测，共 {len(qa_pairs)} 条问答对...")
        print("=" * 60)

        for qa in qa_pairs:
            try:
                result = self.evaluate_single(qa)
                self.results.append(result)
            except Exception as e:
                print(f"  失败: {e}")
                self.results.append({"id": qa["id"], "error": str(e)})

        report = self.generate_report()

        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print(f"\n报告已保存: {output_path}")

        return report

    def generate_report(self) -> dict:
        valid = [r for r in self.results if "error" not in r]

        avg_answer = {
            "relevance": sum(r["answer_quality"]["relevance"] for r in valid) / len(valid),
            "completeness": sum(r["answer_quality"]["completeness"] for r in valid) / len(valid),
            "correctness": sum(r["answer_quality"]["correctness"] for r in valid) / len(valid),
            "has_source_rate": sum(r["answer_quality"]["has_source"] for r in valid) / len(valid),
            "keyword_coverage": sum(r["answer_quality"]["keyword_coverage"] for r in valid) / len(valid),
            "avg_score": sum(r["answer_quality"]["avg_score"] for r in valid) / len(valid)
        }

        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": len(self.results),
                "successful": len(valid),
                "failed": len(self.results) - len(valid)
            },
            "answer_metrics": avg_answer,
            "overall_score": avg_answer["avg_score"],
            "results": self.results
        }

        print("\n" + "=" * 60)
        print("评测报告")
        print("=" * 60)
        print(f"总样本数: {report['summary']['total']}")
        print(f"成功: {report['summary']['successful']} | 失败: {report['summary']['failed']}")
        print("\n【回答质量】")
        print(f"  相关性:      {avg_answer['relevance']:.2%}")
        print(f"  完整性:      {avg_answer['completeness']:.2%}")
        print(f"  正确性:      {avg_answer['correctness']:.2%}")
        print(f"  来源引用率:  {avg_answer['has_source_rate']:.2%}")
        print(f"  关键词覆盖:  {avg_answer['keyword_coverage']:.2%}")
        print(f"\n【总体评分】{report['overall_score']:.2%}")

        return report


if __name__ == "__main__":
    runner = BenchmarkRunner()
    runner.run("eval/reports/benchmark_report.json")
