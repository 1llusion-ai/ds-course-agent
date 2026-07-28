"""Analysis contracts for the clean/noisy profile factorial."""

from __future__ import annotations

from statistics import mean
from typing import Any

CELLS = ("M1_CLEAN", "M1_NOISY", "M2_CLEAN", "M2_NOISY")


def _mean(values: list[float | int | None]) -> float | None:
    usable = [float(value) for value in values if value is not None]
    return mean(usable) if usable else None


def _cell_summary(results: list[dict[str, Any]], cell: str) -> dict[str, Any]:
    rows = [result for result in results if result["method"] == cell]
    successful = [result for result in rows if result["error"] is None]
    return {
        "cases": len(rows),
        "successful": len(successful),
        "learner_recall": _mean([result["metrics"]["learner_recall"] for result in successful]),
        "core_recall": _mean([result["metrics"]["core_recall"] for result in successful]),
        "strict_precision": _mean([result["metrics"]["strict_evidence_precision"] for result in successful]),
        "logical_model_calls": _mean([result["cost"]["logical_model_calls"] for result in rows]),
        "total_tokens": _mean([result["cost"]["total_tokens"] for result in successful]),
        "latency_seconds": _mean([result["cost"]["latency_seconds"] for result in successful]),
    }


def _paired_rows(
    results: list[dict[str, Any]],
    left: str,
    right: str,
) -> tuple[
    list[tuple[dict[str, Any], dict[str, Any]]],
    list[tuple[str, int]],
]:
    by_cell = {
        cell: {
            (result["task_id"], result["repeat"]): result
            for result in results
            if result["method"] == cell and result["error"] is None
        }
        for cell in (left, right)
    }
    keys = sorted(set(by_cell[left]).intersection(by_cell[right]))
    return [(by_cell[left][key], by_cell[right][key]) for key in keys], keys


def _paired_metric(
    results: list[dict[str, Any]],
    *,
    left: str,
    right: str,
    metric: str,
) -> dict[str, Any]:
    pairs, _keys = _paired_rows(results, left, right)
    deltas = [float(left_row["metrics"][metric]) - float(right_row["metrics"][metric]) for left_row, right_row in pairs]
    return {
        "paired_cases": len(deltas),
        "mean_delta": _mean(deltas),
        "left_better": sum(delta > 0 for delta in deltas),
        "tie": sum(delta == 0 for delta in deltas),
        "right_better": sum(delta < 0 for delta in deltas),
    }


def _interaction(results: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    cells = {
        cell: {
            (result["task_id"], result["repeat"]): result
            for result in results
            if result["method"] == cell and result["error"] is None
        }
        for cell in CELLS
    }
    keys = sorted(set.intersection(*(set(rows) for rows in cells.values())))
    effects = []
    by_case = []
    for key in keys:
        clean_delta = float(cells["M2_CLEAN"][key]["metrics"][metric]) - float(
            cells["M1_CLEAN"][key]["metrics"][metric]
        )
        noisy_delta = float(cells["M2_NOISY"][key]["metrics"][metric]) - float(
            cells["M1_NOISY"][key]["metrics"][metric]
        )
        effect = noisy_delta - clean_delta
        effects.append(effect)
        by_case.append(
            {
                "task_id": key[0],
                "repeat": key[1],
                "clean_m2_minus_m1": clean_delta,
                "noisy_m2_minus_m1": noisy_delta,
                "interaction": effect,
            }
        )
    return {
        "paired_cases": len(effects),
        "mean_interaction": _mean(effects),
        "positive": sum(effect > 0 for effect in effects),
        "zero": sum(effect == 0 for effect in effects),
        "negative": sum(effect < 0 for effect in effects),
        "by_case": by_case,
    }


def _prediction_diagnostics(
    results: list[dict[str, Any]],
    cell: str,
) -> dict[str, Any]:
    rows = [
        result
        for result in results
        if result["method"] == cell and result["error"] is None and result.get("prediction")
    ]
    true_retained = 0
    noise_selected = 0
    obligation_counts = []
    for result in rows:
        obligations = (result["prediction"].get("prediction") or {}).get("obligations") or []
        triggers = [
            {
                "field": str((item.get("trigger") or {}).get("field", "")),
                "value": str((item.get("trigger") or {}).get("value", "")),
            }
            for item in obligations
            if isinstance(item, dict)
        ]
        obligation_counts.append(len(obligations))
        if result["true_trigger"] in triggers:
            true_retained += 1
        noise = result["noise_spec"]
        noise_values = {
            *(str(value) for value in noise["weak_concepts"]),
            *(str(value) for value in noise["misconceptions"]),
            str(noise["learning_goal"]),
        }
        if any(trigger["value"] in noise_values for trigger in triggers):
            noise_selected += 1
    return {
        "cases": len(rows),
        "true_trigger_retention_rate": (true_retained / len(rows) if rows else None),
        "noise_trigger_selection_rate": (noise_selected / len(rows) if rows else None),
        "mean_obligation_count": _mean(obligation_counts),
    }


def summarize_profile_noise_results(
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate cells and compute the preregistered noise interaction."""

    cells = {cell: _cell_summary(results, cell) for cell in CELLS}
    learner_interaction = _interaction(results, "learner_recall")
    noisy_m2_vs_m1 = _paired_metric(
        results,
        left="M2_NOISY",
        right="M1_NOISY",
        metric="learner_recall",
    )
    noisy_core = _paired_metric(
        results,
        left="M2_NOISY",
        right="M1_NOISY",
        metric="core_recall",
    )
    task_wins: dict[str, list[float]] = {}
    for item in learner_interaction["by_case"]:
        task_wins.setdefault(item["task_id"], []).append(item["noisy_m2_minus_m1"])
    positive_noisy_tasks = sum(mean(deltas) > 0 for deltas in task_wins.values())
    passed = (
        learner_interaction["mean_interaction"] is not None
        and learner_interaction["mean_interaction"] >= 0.10
        and noisy_m2_vs_m1["mean_delta"] is not None
        and noisy_m2_vs_m1["mean_delta"] > 0
        and positive_noisy_tasks >= 2
        and noisy_core["mean_delta"] is not None
        and noisy_core["mean_delta"] >= -0.05
    )
    return {
        "cells": cells,
        "paired": {
            "M1_noise_effect": {
                metric: _paired_metric(
                    results,
                    left="M1_NOISY",
                    right="M1_CLEAN",
                    metric=metric,
                )
                for metric in (
                    "learner_recall",
                    "core_recall",
                    "strict_evidence_precision",
                )
            },
            "M2_noise_effect": {
                metric: _paired_metric(
                    results,
                    left="M2_NOISY",
                    right="M2_CLEAN",
                    metric=metric,
                )
                for metric in (
                    "learner_recall",
                    "core_recall",
                    "strict_evidence_precision",
                )
            },
            "M2_vs_M1_clean": {
                metric: _paired_metric(
                    results,
                    left="M2_CLEAN",
                    right="M1_CLEAN",
                    metric=metric,
                )
                for metric in (
                    "learner_recall",
                    "core_recall",
                    "strict_evidence_precision",
                )
            },
            "M2_vs_M1_noisy": {
                metric: _paired_metric(
                    results,
                    left="M2_NOISY",
                    right="M1_NOISY",
                    metric=metric,
                )
                for metric in (
                    "learner_recall",
                    "core_recall",
                    "strict_evidence_precision",
                )
            },
        },
        "learner_interaction": learner_interaction,
        "prediction_diagnostics": {
            "clean": _prediction_diagnostics(results, "M2_CLEAN"),
            "noisy": _prediction_diagnostics(results, "M2_NOISY"),
        },
        "decision_gate": {
            "interaction_at_least_0_10": (
                learner_interaction["mean_interaction"] is not None and learner_interaction["mean_interaction"] >= 0.10
            ),
            "noisy_m2_above_m1": (noisy_m2_vs_m1["mean_delta"] is not None and noisy_m2_vs_m1["mean_delta"] > 0),
            "at_least_two_positive_tasks": positive_noisy_tasks >= 2,
            "noisy_core_noninferior_0_05": (noisy_core["mean_delta"] is not None and noisy_core["mean_delta"] >= -0.05),
            "positive_noisy_tasks": positive_noisy_tasks,
            "passed": passed,
        },
    }
