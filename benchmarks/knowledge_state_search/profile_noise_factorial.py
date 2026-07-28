"""Test whether predicted-gap planning filters irrelevant learner-profile noise."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from benchmarks.knowledge_state_search.confirmatory_evaluator_v3 import (
    build_annotation_map,
)
from benchmarks.knowledge_state_search.confirmatory_matrix_support import (
    adapt_profile,
    adapt_task,
    failed_case,
    requirement_from_claim,
)
from benchmarks.knowledge_state_search.confirmatory_matrix_v3 import (
    _run_planner_case,
)
from benchmarks.knowledge_state_search.confirmatory_oracle_v3 import (
    V3LexicalRetriever,
)
from benchmarks.knowledge_state_search.confirmatory_schema import (
    ConfirmatorySchema,
    EvidenceRelation,
    TargetType,
)
from benchmarks.knowledge_state_search.models import EvidenceGap, StudentProfile
from benchmarks.knowledge_state_search.predicted_gap import (
    predict_obligations,
    predicted_gap,
)
from benchmarks.knowledge_state_search.profile_noise_analysis import (
    summarize_profile_noise_results,
)

DEFAULT_DATASET = Path("var/artifacts/knowledge_state_search/phase_b_coverage_repair_v1/repair_v2/dataset")
DEFAULT_OUTPUT = Path(
    "var/artifacts/knowledge_state_search/model_only_scaled_12task_v1/profile_noise_factorial_r3.json"
)
DEFAULT_BASE_URL = "http://model.mify.ai.srv/v1"
DEFAULT_MODEL = "xiaomi/mimo-v2.5-pro"
DEFAULT_TASK_IDS = (
    "pb_t02_logistic_log_odds",
    "pb_t04_confounding_correlation",
    "pb_t05_p_value_meaning",
    "pb_t07_outlier_removal",
    "pb_t08_label_encoding_order",
)
CELLS = ("M1_CLEAN", "M1_NOISY", "M2_CLEAN", "M2_NOISY")


class ProfileCondition(str, Enum):
    """Profile treatment used by the representation factorial."""

    CLEAN = "clean"
    NOISY = "noisy"


@dataclass(frozen=True)
class ProfileNoiseSpec:
    """Task-independent learner-profile facts that are irrelevant to the task."""

    mastered_concepts: tuple[str, ...]
    weak_concepts: tuple[str, ...]
    misconceptions: tuple[str, ...]
    learning_goal: str

    def to_dict(self) -> dict[str, object]:
        """Return the preregistered noise payload."""

        return {
            "mastered_concepts": list(self.mastered_concepts),
            "weak_concepts": list(self.weak_concepts),
            "misconceptions": list(self.misconceptions),
            "learning_goal": self.learning_goal,
        }


DEFAULT_NOISE_SPEC = ProfileNoiseSpec(
    mastered_concepts=("主成分分析", "支持向量机"),
    weak_concepts=("K-means 初始化稳定性",),
    misconceptions=("增加聚类簇数一定会提高模型质量",),
    learning_goal="比较降维与聚类方法的使用场景",
)


def _deduplicate(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def profile_for_condition(
    profile: StudentProfile,
    *,
    condition: ProfileCondition,
    noise_spec: ProfileNoiseSpec = DEFAULT_NOISE_SPEC,
    preserve_learning_goal: bool = False,
) -> StudentProfile:
    """Build a clean clone or add fixed task-independent distractor facts."""

    suffix = condition.value
    if condition is ProfileCondition.CLEAN:
        return StudentProfile(
            student_id=f"{profile.student_id}__{suffix}",
            level=profile.level,
            mastered_concepts=profile.mastered_concepts,
            weak_concepts=profile.weak_concepts,
            misconceptions=profile.misconceptions,
            learning_goal=profile.learning_goal,
        )
    return StudentProfile(
        student_id=f"{profile.student_id}__{suffix}",
        level=profile.level,
        mastered_concepts=_deduplicate((*profile.mastered_concepts, *noise_spec.mastered_concepts)),
        weak_concepts=_deduplicate((*profile.weak_concepts, *noise_spec.weak_concepts)),
        misconceptions=_deduplicate((*profile.misconceptions, *noise_spec.misconceptions)),
        learning_goal=profile.learning_goal if preserve_learning_goal else noise_spec.learning_goal,
    )


def _supported_learner_sources(
    schema: ConfirmatorySchema,
    *,
    task_id: str,
    claim_id: str,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            annotation.source_id
            for annotation in schema.annotations_for_task(task_id)
            if annotation.target_type is TargetType.CLAIM
            and annotation.target_id == claim_id
            and annotation.relation is EvidenceRelation.SUPPORTED
        )
    )


def validate_factorial_tasks(
    schema: ConfirmatorySchema,
    task_ids: tuple[str, ...],
) -> None:
    """Require one active learner profile and available support per task."""

    known = {task.task_id for task in schema.tasks}
    unknown = set(task_ids) - known
    if unknown:
        raise ValueError(f"unknown factorial task IDs: {sorted(unknown)}")
    for task_id in task_ids:
        active_profiles = [
            profile for profile in schema.profiles_for_task(task_id) if schema.active_learner_claims(profile)
        ]
        if len(active_profiles) != 1:
            raise ValueError(f"factorial task must have exactly one active profile: {task_id}")
        learner_claims = schema.active_learner_claims(active_profiles[0])
        if len(learner_claims) != 1:
            raise ValueError(f"factorial task must activate exactly one learner claim: {task_id}")
        if not _supported_learner_sources(
            schema,
            task_id=task_id,
            claim_id=learner_claims[0].claim_id,
        ):
            raise ValueError(f"factorial task lacks supported learner evidence: {task_id}")


def _failed_prediction_case(
    *,
    cell: str,
    task_id: str,
    base_profile_id: str,
    profile: StudentProfile,
    condition: ProfileCondition,
    repeat: int,
    prediction: dict[str, Any],
    true_trigger: dict[str, str],
    noise_spec: ProfileNoiseSpec,
) -> dict[str, Any]:
    result = failed_case(
        method=cell,
        task_id=task_id,
        profile_id=profile.student_id,
        repeat=repeat,
        error=f"predictor_failed: {prediction['error']}",
        prediction=prediction,
    )
    result.update(
        {
            "base_profile_id": base_profile_id,
            "profile_condition": condition.value,
            "profile_payload": profile.to_dict(),
            "true_trigger": true_trigger,
            "noise_spec": noise_spec.to_dict(),
        }
    )
    return result


def run_profile_noise_factorial(
    *,
    api_key: str,
    base_url: str,
    model: str,
    schema: ConfirmatorySchema,
    task_ids: tuple[str, ...] = DEFAULT_TASK_IDS,
    noise_spec: ProfileNoiseSpec = DEFAULT_NOISE_SPEC,
    repeats: int = 3,
    top_k: int = 4,
    max_queries: int = 3,
    source_budget: int = 6,
    timeout: float = 180.0,
    max_retries: int = 2,
) -> dict[str, Any]:
    """Run clean/noisy M1 versus free-executor M2 over supported learner tasks."""

    if repeats < 1 or top_k < 1 or max_queries < 1 or source_budget < 1:
        raise ValueError("repeats, top_k, max_queries, and source_budget must be positive")
    schema.validate()
    validate_factorial_tasks(schema, task_ids)
    task_map = {task.task_id: task for task in schema.tasks}
    retriever = V3LexicalRetriever(schema)
    annotations = build_annotation_map(schema)
    results: list[dict[str, Any]] = []
    executed_model_calls = 0
    for repeat in range(1, repeats + 1):
        for task_id in task_ids:
            task = task_map[task_id]
            claims = schema.claims_for_task(task_id)
            core_claims = tuple(claim for claim in claims if claim.hard)
            active_profile = next(
                profile for profile in schema.profiles_for_task(task_id) if schema.active_learner_claims(profile)
            )
            no_gap_profile = next(
                profile for profile in schema.profiles_for_task(task_id) if not schema.active_learner_claims(profile)
            )
            learner_claim = schema.active_learner_claims(active_profile)[0]
            if learner_claim.profile_condition is None:
                raise ValueError(f"active learner claim lacks a profile condition: {learner_claim.claim_id}")
            true_trigger = {
                "field": learner_claim.profile_condition.field.value,
                "value": learner_claim.profile_condition.value,
            }
            adapter_task = adapt_task(
                task_id,
                task.question,
                task.target_concepts,
                claims,
            )
            core_gap = EvidenceGap(core_requirements=tuple(requirement_from_claim(claim) for claim in core_claims))
            evaluation_claim_ids = tuple(claim.claim_id for claim in (*core_claims, learner_claim))
            base_profile = adapt_profile(active_profile)
            for condition in ProfileCondition:
                profile = profile_for_condition(
                    base_profile,
                    condition=condition,
                    noise_spec=noise_spec,
                    preserve_learning_goal=(true_trigger["field"] == "learning_goal"),
                )
                common_extra = {
                    "base_profile_id": active_profile.profile_id,
                    "profile_condition": condition.value,
                    "profile_payload": profile.to_dict(),
                    "true_trigger": true_trigger,
                    "noise_spec": noise_spec.to_dict(),
                    "supported_learner_source_ids": list(
                        _supported_learner_sources(
                            schema,
                            task_id=task_id,
                            claim_id=learner_claim.claim_id,
                        )
                    ),
                }
                executed_model_calls += 1
                results.append(
                    _run_planner_case(
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        method=f"M1_{condition.value.upper()}",
                        task=adapter_task,
                        profile=profile,
                        visible_gap=core_gap,
                        evaluation_claim_ids=evaluation_claim_ids,
                        schema=schema,
                        task_id=task_id,
                        retriever=retriever,
                        annotations=annotations,
                        repeat=repeat,
                        top_k=top_k,
                        max_queries=max_queries,
                        source_budget=source_budget,
                        timeout=timeout,
                        max_retries=max_retries,
                        variant="profile_prompt",
                        extra=common_extra,
                    )
                )
                executed_model_calls += 1
                prediction = predict_obligations(
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    task=adapter_task,
                    profile=profile,
                    timeout=timeout,
                    max_retries=max_retries,
                    neutral_learning_goal=no_gap_profile.learning_goal,
                )
                cell = f"M2_{condition.value.upper()}"
                if prediction["error"] is not None or not prediction["prediction"]:
                    results.append(
                        _failed_prediction_case(
                            cell=cell,
                            task_id=task_id,
                            base_profile_id=active_profile.profile_id,
                            profile=profile,
                            condition=condition,
                            repeat=repeat,
                            prediction=prediction,
                            true_trigger=true_trigger,
                            noise_spec=noise_spec,
                        )
                    )
                    continue
                visible_gap = predicted_gap(
                    adapter_task,
                    prediction["prediction"],
                )
                executed_model_calls += 1
                results.append(
                    _run_planner_case(
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        method=cell,
                        task=adapter_task,
                        profile=profile,
                        visible_gap=visible_gap,
                        evaluation_claim_ids=evaluation_claim_ids,
                        schema=schema,
                        task_id=task_id,
                        retriever=retriever,
                        annotations=annotations,
                        repeat=repeat,
                        top_k=top_k,
                        max_queries=max_queries,
                        source_budget=source_budget,
                        timeout=timeout,
                        max_retries=max_retries,
                        variant="gap_planner",
                        predictor_calls=1,
                        enforce_target_contract=False,
                        extra={
                            **common_extra,
                            "prediction": prediction,
                        },
                    )
                )
    summary = summarize_profile_noise_results(results)
    return {
        "schema_version": 1,
        "experiment": "knowledge_state_search_profile_noise_factorial",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_id": schema.manifest.benchmark_id,
        "executed_model_calls": executed_model_calls,
        "config": {
            "cells": list(CELLS),
            "task_ids": list(task_ids),
            "repeats": repeats,
            "top_k": top_k,
            "max_queries": max_queries,
            "source_budget": source_budget,
            "m2_executor": "free",
            "noise_spec": noise_spec.to_dict(),
            "model": model,
            "base_url": base_url.rstrip("/"),
            "status": "post_hoc_operational_mechanism_test",
        },
        "summary": summary,
        "results": results,
    }


def _load_env() -> None:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


def build_parser() -> argparse.ArgumentParser:
    """Build the profile-noise factorial CLI."""

    parser = argparse.ArgumentParser(description="Run clean/noisy raw-profile versus predicted-gap planning.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--task-id", action="append")
    parser.add_argument("--api-key-env", default="PROFILE_EVAL_API_KEY")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PROFILE_EVAL_BASE_URL") or os.environ.get("MIFY_BASE_URL") or DEFAULT_BASE_URL,
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("PROFILE_EVAL_MODEL") or os.environ.get("MIFY_MODEL") or DEFAULT_MODEL,
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--max-queries", type=int, default=3)
    parser.add_argument("--source-budget", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-retries", type=int, default=2)
    return parser


def main() -> int:
    """Run and persist the profile-noise factorial."""

    _load_env()
    args = build_parser().parse_args()
    api_key = os.environ.get(args.api_key_env) or os.environ.get("MIFY_API_KEY") or os.environ.get("JUDGE_API_KEY")
    if not api_key:
        print("API key not found.", file=sys.stderr)
        return 2
    schema = ConfirmatorySchema.load(args.dataset)
    task_ids = tuple(args.task_id or DEFAULT_TASK_IDS)
    report = run_profile_noise_factorial(
        api_key=api_key,
        base_url=args.base_url,
        model=args.model,
        schema=schema,
        task_ids=task_ids,
        repeats=args.repeats,
        top_k=args.top_k,
        max_queries=args.max_queries,
        source_budget=args.source_budget,
        timeout=args.timeout,
        max_retries=args.max_retries,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Saved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
