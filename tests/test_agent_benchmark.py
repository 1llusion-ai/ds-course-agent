from eval.agent_benchmark import (
    DEFAULT_BENCHMARK_PATH,
    AgentTask,
    build_benchmark_report,
    load_agent_tasks,
    score_agent_task,
)


class TestAgentBenchmarkDataset:
    def test_default_benchmark_has_expected_task_count(self):
        metadata, tasks = load_agent_tasks(DEFAULT_BENCHMARK_PATH)

        assert metadata["version"] == "v1.0"
        assert len(tasks) == 30

    def test_default_benchmark_has_expected_category_split(self):
        _, tasks = load_agent_tasks(DEFAULT_BENCHMARK_PATH)

        counts = {}
        for task in tasks:
            counts[task.category] = counts.get(task.category, 0) + 1

        assert counts == {
            "single_turn": 10,
            "multi_turn": 8,
            "personalized": 6,
            "edge": 6,
        }


class TestAgentBenchmarkScoring:
    def test_score_agent_task_success_when_required_dimensions_are_met(self):
        task = AgentTask(
            id="demo_success",
            category="multi_turn",
            description="demo",
            turns=["第一问", "第二问"],
            must_use_tool=True,
            must_use_context=True,
            must_personalize=True,
            must_fail_safe=True,
            required_keyword_groups=[["主成分分析"], ["协方差"]],
            context_keyword_groups=[["主成分分析"]],
            personalization_keyword_groups=[["第6章"]],
            safety_keyword_groups=[["可以先", "先"]],
        )

        turn_results = [
            {
                "user": "第一问",
                "assistant": "主成分分析是降维方法。",
                "used_retrieval": True,
                "sources": [{"reference": "《第7章 无监督学习算法》第123页"}],
            },
            {
                "user": "第二问",
                "assistant": "主成分分析通常先看协方差矩阵。结合你现在第6章的进度，可以先理解直觉再推公式。",
                "used_retrieval": False,
                "sources": [],
            },
        ]

        score = score_agent_task(task, turn_results)

        assert score["success"] is True
        assert score["dimension_scores"]["tool_call_correct"] is True
        assert score["dimension_scores"]["grounded_answer"] is True
        assert score["dimension_scores"]["context_utilization"] is True
        assert score["dimension_scores"]["personalization_hit"] is True
        assert score["dimension_scores"]["failure_safety"] is True

    def test_score_agent_task_fails_when_context_is_missing(self):
        task = AgentTask(
            id="demo_fail",
            category="multi_turn",
            description="demo",
            turns=["第一问", "第二问"],
            must_use_tool=True,
            must_use_context=True,
            required_keyword_groups=[["决策树"], ["过拟合"]],
            context_keyword_groups=[["决策树"]],
        )

        turn_results = [
            {
                "user": "第一问",
                "assistant": "决策树是一种分类方法。",
                "used_retrieval": True,
                "sources": [{"reference": "《第6章 监督学习常用算法》第120页"}],
            },
            {
                "user": "第二问",
                "assistant": "它容易过拟合，因为模型会变复杂。",
                "used_retrieval": False,
                "sources": [],
            },
        ]

        score = score_agent_task(task, turn_results)

        assert score["success"] is False
        assert score["dimension_scores"]["tool_call_correct"] is True
        assert score["dimension_scores"]["context_utilization"] is False


class TestAgentBenchmarkReport:
    def test_build_benchmark_report_aggregates_rates(self):
        metadata = {"version": "v1.0"}
        snapshot = {"model": {"chat_model": "demo"}}
        results = [
            {
                "task": {
                    "id": "t1",
                    "category": "single_turn",
                    "must_use_tool": True,
                    "must_use_context": False,
                    "must_personalize": False,
                    "must_fail_safe": False,
                },
                "score": {
                    "success": True,
                    "dimension_scores": {
                        "task_completion": True,
                        "tool_call_correct": True,
                        "grounded_answer": True,
                        "context_utilization": True,
                        "personalization_hit": True,
                        "failure_safety": True,
                    },
                },
            },
            {
                "task": {
                    "id": "t2",
                    "category": "edge",
                    "must_use_tool": False,
                    "must_use_context": False,
                    "must_personalize": False,
                    "must_fail_safe": True,
                },
                "score": {
                    "success": False,
                    "dimension_scores": {
                        "task_completion": False,
                        "tool_call_correct": False,
                        "grounded_answer": True,
                        "context_utilization": True,
                        "personalization_hit": True,
                        "failure_safety": False,
                    },
                },
            },
        ]

        report = build_benchmark_report(metadata, snapshot, results)

        assert report["summary"]["total_tasks"] == 2
        assert report["summary"]["passed_tasks"] == 1
        assert report["summary"]["agent_task_success_rate"] == 0.5
        assert report["summary"]["tool_call_success_rate"] == 0.5
        assert report["summary"]["grounded_answer_rate"] == 1.0
        assert report["summary"]["failure_safety_rate"] == 0.0
