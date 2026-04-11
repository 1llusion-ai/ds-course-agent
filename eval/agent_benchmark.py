"""
Agent benchmark runner.

This module evaluates end-to-end agent behavior on a fixed task set that
covers retrieval, multi-turn context, personalization, and safety handling.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tempfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import utils.config as config
from backend.app import core_bridge
import core.agent as agent_module
import core.memory_core as memory_core_module
from core.profile_models import ConceptFocus, ProgressInfo, StudentProfile, WeakSpotCandidate


DEFAULT_BENCHMARK_PATH = Path(__file__).parent / "data" / "agent_tasks_v1.json"
DEFAULT_REPORT_PATH = Path(__file__).parent / "reports" / "agent_benchmark_report.json"
PROMPT_PATH = Path(__file__).parent.parent / "docs" / "prompts" / "system_prompt.txt"
KNOWLEDGE_GRAPH_PATH = Path(__file__).parent.parent / "data" / "knowledge_graph.json"


def safe_print(text: str) -> None:
    """Print text without crashing on Windows encoding issues."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding))


def _sha256_of_file(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalize_keyword_groups(items: Optional[list[Any]]) -> list[list[str]]:
    groups: list[list[str]] = []
    for item in items or []:
        if isinstance(item, str):
            groups.append([item])
        elif isinstance(item, list):
            group = [str(value) for value in item if str(value).strip()]
            if group:
                groups.append(group)
    return groups


def _contains_keyword(text: str, keyword: str) -> bool:
    return keyword.lower() in text.lower()


def _match_keyword_groups(text: str, groups: list[list[str]]) -> tuple[bool, list[dict[str, Any]]]:
    details: list[dict[str, Any]] = []

    for group in groups:
        matched = next((keyword for keyword in group if _contains_keyword(text, keyword)), None)
        details.append({"group": group, "matched": matched})

    return all(item["matched"] for item in details), details


def _find_forbidden_keywords(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if _contains_keyword(text, keyword)]


@dataclass
class AgentTask:
    id: str
    category: str
    description: str
    turns: list[str]
    must_use_tool: Optional[bool] = None
    must_use_context: bool = False
    must_personalize: bool = False
    must_fail_safe: bool = False
    required_keyword_groups: list[list[str]] = field(default_factory=list)
    context_keyword_groups: list[list[str]] = field(default_factory=list)
    personalization_keyword_groups: list[list[str]] = field(default_factory=list)
    safety_keyword_groups: list[list[str]] = field(default_factory=list)
    forbidden_keywords: list[str] = field(default_factory=list)
    seed_profile: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentTask":
        return cls(
            id=data["id"],
            category=data["category"],
            description=data.get("description", ""),
            turns=list(data.get("turns", [])),
            must_use_tool=data.get("must_use_tool"),
            must_use_context=bool(data.get("must_use_context", False)),
            must_personalize=bool(data.get("must_personalize", False)),
            must_fail_safe=bool(data.get("must_fail_safe", False)),
            required_keyword_groups=_normalize_keyword_groups(data.get("required_keyword_groups")),
            context_keyword_groups=_normalize_keyword_groups(data.get("context_keyword_groups")),
            personalization_keyword_groups=_normalize_keyword_groups(data.get("personalization_keyword_groups")),
            safety_keyword_groups=_normalize_keyword_groups(data.get("safety_keyword_groups")),
            forbidden_keywords=list(data.get("forbidden_keywords", [])),
            seed_profile=dict(data.get("seed_profile", {})),
            notes=data.get("notes", ""),
        )


def load_agent_tasks(path: Path | str = DEFAULT_BENCHMARK_PATH) -> tuple[dict[str, Any], list[AgentTask]]:
    benchmark_path = Path(path)
    payload = json.loads(benchmark_path.read_text(encoding="utf-8"))
    tasks = [AgentTask.from_dict(item) for item in payload.get("tasks", [])]
    metadata = {key: value for key, value in payload.items() if key != "tasks"}
    return metadata, tasks


def collect_benchmark_snapshot(benchmark_path: Path | str) -> dict[str, Any]:
    benchmark_path = Path(benchmark_path)

    knowledge_graph_version = None
    if KNOWLEDGE_GRAPH_PATH.exists():
        knowledge_graph_version = json.loads(KNOWLEDGE_GRAPH_PATH.read_text(encoding="utf-8")).get("version")

    return {
        "generated_at": datetime.now().isoformat(),
        "model": {
            "use_remote_llm": config.USE_REMOTE_LLM,
            "chat_model": config.MODEL_CHAT,
            "chat_base_url": config.BASE_URL_CHAT,
            "remote_model_name": config.REMOTE_MODEL_NAME,
        },
        "prompt": {
            "path": str(PROMPT_PATH),
            "sha256": _sha256_of_file(PROMPT_PATH),
        },
        "retrieval": {
            "collection_name": config.collection_name,
            "similarity_top_k": config.similarity_top_k,
            "enable_rerank": config.enable_rerank,
            "rerank_top_k": config.rerank_top_k,
            "chunk_size": config.chunk_size,
            "chunk_overlap": config.chunk_overlap,
            "persist_directory": config.persist_directory,
        },
        "knowledge_base": {
            "course_name": config.COURSE_NAME,
            "knowledge_graph_version": knowledge_graph_version,
            "knowledge_graph_sha256": _sha256_of_file(KNOWLEDGE_GRAPH_PATH),
            "chroma_persist_dir": config.CHROMA_PERSIST_DIR,
        },
        "benchmark": {
            "path": str(benchmark_path),
            "sha256": _sha256_of_file(benchmark_path),
        },
    }


def _build_seed_profile(student_id: str, seed: dict[str, Any]) -> StudentProfile:
    profile = StudentProfile(student_id=student_id)

    progress = seed.get("progress", {})
    if progress:
        profile.progress = ProgressInfo(
            current_chapter=progress.get("current_chapter"),
            covered_chapters=list(progress.get("covered_chapters", [])),
        )

    for item in seed.get("recent_concepts", []):
        concept_id = item["concept_id"]
        profile.recent_concepts[concept_id] = ConceptFocus(
            concept_id=concept_id,
            display_name=item.get("display_name", concept_id),
            chapter=item.get("chapter", ""),
            mention_count=int(item.get("mention_count", 1)),
            evidence=list(item.get("evidence", [])),
        )

    for item in seed.get("weak_spots", []):
        profile.weak_spot_candidates.append(
            WeakSpotCandidate(
                concept_id=item["concept_id"],
                display_name=item.get("display_name", item["concept_id"]),
                parent_concept=item.get("parent_concept"),
                signals=list(item.get("signals", [])),
                confidence=float(item.get("confidence", 0.7)),
            )
        )

    stats = seed.get("stats", {})
    if stats:
        profile.stats.update(stats)

    return profile


@contextmanager
def isolated_benchmark_environment():
    """Run benchmark in a temporary history/profile sandbox."""
    old_storage_path = config.storage_path
    old_chat_history_dir = config.CHAT_HISTORY_DIR
    old_memory_core = memory_core_module._memory_core
    old_agent_service = agent_module._agent_service
    old_bridge_agent_service = core_bridge._agent_service
    old_bridge_memory_core = core_bridge._memory_core

    with tempfile.TemporaryDirectory(prefix="agent_benchmark_") as temp_dir:
        config.storage_path = temp_dir
        config.CHAT_HISTORY_DIR = temp_dir
        memory_core_module._memory_core = memory_core_module.MemoryCore(base_dir=temp_dir)
        agent_module._agent_service = None
        core_bridge._agent_service = None
        core_bridge._memory_core = memory_core_module._memory_core

        try:
            yield Path(temp_dir)
        finally:
            core_bridge._memory_core = old_bridge_memory_core
            core_bridge._agent_service = old_bridge_agent_service
            agent_module._agent_service = old_agent_service
            memory_core_module._memory_core = old_memory_core
            config.storage_path = old_storage_path
            config.CHAT_HISTORY_DIR = old_chat_history_dir


def score_agent_task(task: AgentTask, turn_results: list[dict[str, Any]]) -> dict[str, Any]:
    final_turn = turn_results[-1] if turn_results else {
        "assistant": "",
        "used_retrieval": False,
        "sources": [],
    }
    final_response = final_turn.get("assistant", "")
    retrieval_used_any_turn = any(item.get("used_retrieval") for item in turn_results)
    sources_present = any(item.get("sources") for item in turn_results)

    required_passed, required_details = _match_keyword_groups(final_response, task.required_keyword_groups)
    context_passed, context_details = _match_keyword_groups(final_response, task.context_keyword_groups)
    personalization_passed, personalization_details = _match_keyword_groups(
        final_response,
        task.personalization_keyword_groups,
    )
    safety_passed, safety_details = _match_keyword_groups(final_response, task.safety_keyword_groups)
    forbidden_hits = _find_forbidden_keywords(final_response, task.forbidden_keywords)

    task_completion = required_passed and not forbidden_hits

    if task.must_use_tool is True:
        tool_call_correct = retrieval_used_any_turn
    elif task.must_use_tool is False:
        tool_call_correct = not retrieval_used_any_turn
    else:
        tool_call_correct = True

    grounded_answer = True
    if task.must_use_tool:
        grounded_answer = retrieval_used_any_turn and sources_present and not forbidden_hits

    context_utilization = True if not task.must_use_context else context_passed and not forbidden_hits
    personalization_hit = True if not task.must_personalize else personalization_passed and not forbidden_hits
    failure_safety = True if not task.must_fail_safe else safety_passed and not forbidden_hits

    required_dimensions = ["task_completion"]
    if task.must_use_tool is not None:
        required_dimensions.append("tool_call_correct")
    if task.must_use_tool:
        required_dimensions.append("grounded_answer")
    if task.must_use_context:
        required_dimensions.append("context_utilization")
    if task.must_personalize:
        required_dimensions.append("personalization_hit")
    if task.must_fail_safe:
        required_dimensions.append("failure_safety")

    dimension_values = {
        "task_completion": task_completion,
        "tool_call_correct": tool_call_correct,
        "grounded_answer": grounded_answer,
        "context_utilization": context_utilization,
        "personalization_hit": personalization_hit,
        "failure_safety": failure_safety,
    }

    success = all(dimension_values[name] for name in required_dimensions)

    return {
        "success": success,
        "required_dimensions": required_dimensions,
        "dimension_scores": dimension_values,
        "details": {
            "required_keyword_groups": required_details,
            "context_keyword_groups": context_details,
            "personalization_keyword_groups": personalization_details,
            "safety_keyword_groups": safety_details,
            "forbidden_hits": forbidden_hits,
            "retrieval_used_any_turn": retrieval_used_any_turn,
            "sources_present": sources_present,
        },
    }


def run_agent_benchmark(
    benchmark_path: Path | str = DEFAULT_BENCHMARK_PATH,
    output_path: Path | str = DEFAULT_REPORT_PATH,
    limit: Optional[int] = None,
    task_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    metadata, tasks = load_agent_tasks(benchmark_path)

    if task_ids:
        selected = set(task_ids)
        tasks = [task for task in tasks if task.id in selected]

    if limit is not None:
        tasks = tasks[:limit]

    snapshot = collect_benchmark_snapshot(benchmark_path)
    results: list[dict[str, Any]] = []

    safe_print(f"Running agent benchmark: {len(tasks)} tasks")
    safe_print("=" * 60)

    with isolated_benchmark_environment():
        for index, task in enumerate(tasks, 1):
            student_id = f"benchmark_student_{task.id}"
            session_id = f"benchmark_session_{task.id}"

            if task.seed_profile:
                profile = _build_seed_profile(student_id, task.seed_profile)
                memory_core_module.get_memory_core().save_profile(profile)

            turn_results: list[dict[str, Any]] = []

            for turn in task.turns:
                response = core_bridge.chat_with_history(
                    message=turn,
                    session_id=session_id,
                    student_id=student_id,
                )
                turn_results.append(
                    {
                        "user": turn,
                        "assistant": response.get("content", ""),
                        "used_retrieval": bool(response.get("used_retrieval")),
                        "sources": response.get("sources") or [],
                    }
                )

            score = score_agent_task(task, turn_results)
            result = {
                "task": asdict(task),
                "turns": turn_results,
                "score": score,
            }
            results.append(result)

            status = "PASS" if score["success"] else "FAIL"
            safe_print(f"[{index}/{len(tasks)}] {task.id} {status} | {task.description}")

    report = build_benchmark_report(metadata, snapshot, results)

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    safe_print("=" * 60)
    safe_print(f"Agent task success rate: {report['summary']['agent_task_success_rate']:.1%}")
    safe_print(f"Tool call success rate: {report['summary']['tool_call_success_rate']:.1%}")
    safe_print(f"Grounded answer rate: {report['summary']['grounded_answer_rate']:.1%}")
    safe_print(f"Personalization hit rate: {report['summary']['personalization_hit_rate']:.1%}")
    safe_print(f"Saved report to: {output_file}")

    return report


def build_benchmark_report(
    metadata: dict[str, Any],
    snapshot: dict[str, Any],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    total_tasks = len(results)
    success_count = sum(1 for item in results if item["score"]["success"])

    applicable_tool = [item for item in results if item["task"]["must_use_tool"] is not None]
    applicable_grounded = [item for item in results if item["task"]["must_use_tool"] is True]
    applicable_context = [item for item in results if item["task"]["must_use_context"]]
    applicable_personalization = [item for item in results if item["task"]["must_personalize"]]
    applicable_safety = [item for item in results if item["task"]["must_fail_safe"]]

    def _rate(items: list[dict[str, Any]], key: str) -> float:
        if not items:
            return 0.0
        passed = sum(1 for item in items if item["score"]["dimension_scores"][key])
        return passed / len(items)

    by_category: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[result["task"]["category"]].append(result)

    for category, items in grouped.items():
        by_category[category] = {
            "total": len(items),
            "passed": sum(1 for item in items if item["score"]["success"]),
            "success_rate": _rate(items, "task_completion") if not items else sum(
                1 for item in items if item["score"]["success"]
            ) / len(items),
        }

    return {
        "metadata": metadata,
        "snapshot": snapshot,
        "summary": {
            "total_tasks": total_tasks,
            "passed_tasks": success_count,
            "agent_task_success_rate": success_count / total_tasks if total_tasks else 0.0,
            "tool_call_success_rate": _rate(applicable_tool, "tool_call_correct"),
            "grounded_answer_rate": _rate(applicable_grounded, "grounded_answer"),
            "context_utilization_rate": _rate(applicable_context, "context_utilization"),
            "personalization_hit_rate": _rate(applicable_personalization, "personalization_hit"),
            "failure_safety_rate": _rate(applicable_safety, "failure_safety"),
            "category_counts": dict(Counter(item["task"]["category"] for item in results)),
        },
        "by_category": by_category,
        "results": results,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the agent task benchmark")
    parser.add_argument(
        "--benchmark",
        default=str(DEFAULT_BENCHMARK_PATH),
        help="Path to the benchmark JSON file",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_REPORT_PATH),
        help="Where to save the JSON report",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only run the first N tasks",
    )
    parser.add_argument(
        "--task-id",
        action="append",
        default=None,
        help="Run only specific task ids. Can be provided multiple times.",
    )
    return parser


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    args = build_arg_parser().parse_args()
    run_agent_benchmark(
        benchmark_path=args.benchmark,
        output_path=args.output,
        limit=args.limit,
        task_ids=args.task_id,
    )
