"""Build the expanded v2 confirmatory task and evidence snapshot artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from benchmarks.knowledge_state_search.models import SearchTask

DEFAULT_TASKS = Path("benchmarks/data/knowledge_state_search_probe_v1.json")
DEFAULT_SNAPSHOT = Path("benchmarks/data/knowledge_state_search_snapshot_v1")
DEFAULT_OUTPUT_TASKS = Path("benchmarks/data/knowledge_state_search_probe_v2.json")
DEFAULT_OUTPUT_SNAPSHOT = Path("benchmarks/data/knowledge_state_search_snapshot_v2")


def build_confirmatory_tasks(payload: dict[str, Any]) -> dict[str, Any]:
    """Expand v1 tasks with controlled no-gap, single-gap, and multi-gap profiles."""

    tasks = [SearchTask.from_dict(item) for item in payload["tasks"]]
    expanded = []
    for task in tasks:
        requirements = task.evidence_requirements
        prerequisite = next((item for item in requirements if item.kind == "prerequisite"), None)
        misconception = next((item for item in requirements if item.kind == "misconception"), None)
        goal = next((item for item in requirements if item.kind == "goal"), None)
        mastered = tuple(
            dict.fromkeys(
                (
                    *task.target_concepts,
                    *(item.concept for item in requirements if item.kind == "prerequisite"),
                )
            )
        )
        profiles: list[dict[str, Any]] = [
            _profile(
                f"{task.task_id}_nogap",
                level="intermediate",
                mastered=mastered,
                learning_goal="理解算法原理",
            )
        ]
        if prerequisite is not None:
            profiles.append(
                _profile(
                    f"{task.task_id}_prereq_gap",
                    level="intermediate",
                    mastered=tuple(item for item in mastered if item != prerequisite.concept),
                    weak=(prerequisite.concept,),
                    learning_goal="理解算法原理",
                )
            )
        if misconception is not None:
            profiles.append(
                _profile(
                    f"{task.task_id}_misconception_gap",
                    level="intermediate",
                    mastered=mastered,
                    misconceptions=(misconception.concept,),
                    learning_goal="纠正错误理解",
                )
            )
        if goal is not None:
            profiles.append(
                _profile(
                    f"{task.task_id}_goal_gap",
                    level="intermediate",
                    mastered=mastered,
                    learning_goal=_goal_for_requirement(goal.concept),
                )
            )
        if prerequisite is not None and goal is not None:
            profiles.append(
                _profile(
                    f"{task.task_id}_multi_gap",
                    level="intermediate",
                    mastered=tuple(item for item in mastered if item != prerequisite.concept),
                    weak=(prerequisite.concept,),
                    learning_goal=_goal_for_requirement(goal.concept),
                )
            )
        elif prerequisite is not None and misconception is not None:
            profiles.append(
                _profile(
                    f"{task.task_id}_multi_gap",
                    level="intermediate",
                    mastered=tuple(item for item in mastered if item != prerequisite.concept),
                    weak=(prerequisite.concept,),
                    misconceptions=(misconception.concept,),
                    learning_goal="纠正错误理解",
                )
            )
        expanded.append(
            {
                "task_id": task.task_id,
                "question": task.question,
                "target_concepts": list(task.target_concepts),
                "evidence_requirements": [item.to_dict() for item in requirements],
                "profiles": profiles,
            }
        )
    return {
        "schema_version": 2,
        "experiment": "knowledge_state_search_confirmatory_v2",
        "description": (
            "Expanded paired profiles for confirmatory testing of learner-conditioned "
            "evidence acquisition. v2 adds controlled gap types and multi-gap cases."
        ),
        "tasks": expanded,
    }


def build_confirmatory_snapshot(
    source_directory: Path,
    output_directory: Path,
) -> None:
    """Copy the audited v1 snapshot and add explicit distractor/contradiction controls."""

    if output_directory.exists():
        shutil.rmtree(output_directory)
    output_directory.mkdir(parents=True)
    source_lines = [
        line for line in (source_directory / "sources.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    annotation_lines = [
        line
        for line in (source_directory / "annotations.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    source_payloads = [json.loads(line) for line in source_lines]
    annotation_payloads = [json.loads(line) for line in annotation_lines]
    for source, source_annotations in _controlled_sources():
        source_payloads.append(source)
        annotation_payloads.extend(source_annotations)
    source_payloads.sort(key=lambda item: item["source_id"])
    annotation_payloads.sort(key=lambda item: (item["task_id"], item["requirement_id"], item["source_id"]))
    task_ids = sorted({item["task_id"] for item in source_payloads})
    manifest = {
        "snapshot_id": "knowledge-state-search-v2",
        "schema_version": 1,
        "captured_at": "2026-07-21T00:00:00+00:00",
        "task_ids": task_ids,
        "source_count": len(source_payloads),
        "annotation_count": len(annotation_payloads),
        "capture_method": "v1 audited snapshot plus explicit benchmark controls",
        "annotation_protocol": (
            "v1 labels retained; v2 distractor and contradiction controls are "
            "explicitly marked as benchmark-only annotations."
        ),
        "provenance_note": (
            "Queries and planner metadata are not stored in source records. "
            "Sources with provider benchmark_*_control are not web evidence."
        ),
    }
    (output_directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_directory / "sources.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in source_payloads) + "\n",
        encoding="utf-8",
    )
    (output_directory / "annotations.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in annotation_payloads) + "\n",
        encoding="utf-8",
    )
    (output_directory / "README.md").write_text(
        """# Knowledge-State Search Snapshot v2

This is an expanded confirmatory snapshot derived from the audited v1
development snapshot. It adds off-contract distractors and explicit
`benchmark_*_control` passages so the evaluator can test partial,
unannotated, and contradicted evidence without pretending that synthetic
negative controls are real web pages.

Planner queries, target labels, and method names are not stored in source
records. The snapshot is for benchmark evaluation only.
""",
        encoding="utf-8",
    )


def _profile(
    student_id: str,
    *,
    level: str,
    mastered: tuple[str, ...],
    weak: tuple[str, ...] = (),
    misconceptions: tuple[str, ...] = (),
    learning_goal: str,
) -> dict[str, Any]:
    return {
        "student_id": student_id,
        "level": level,
        "mastered_concepts": list(mastered),
        "weak_concepts": list(weak),
        "misconceptions": list(misconceptions),
        "learning_goal": learning_goal,
    }


def _goal_for_requirement(concept: str) -> str:
    if concept == "formalism":
        return "理解公式和推导"
    return "比较方法和应用"


def _controlled_sources() -> tuple[tuple[dict[str, Any], list[dict[str, str]]], ...]:
    """Return benchmark-only distractor and contradiction passages."""

    controls = (
        (
            "kmeans_support_example",
            "kmeans_initialization",
            "Benchmark support control: a toy initialization example",
            "benchmark://knowledge-state-search-v2/kmeans/toy-example",
            "On a small toy dataset, two different initial centroid choices can "
            "lead the alternating assignment and update procedure to different "
            "clusterings, making the effect of initialization intuitive.",
            (
                {
                    "task_id": "kmeans_initialization",
                    "requirement_id": "goal_intuition",
                    "status": "supported",
                },
            ),
        ),
        (
            "kmeans_distractor_choose_k",
            "kmeans_initialization",
            "Choosing the number of clusters with silhouette analysis",
            "benchmark://knowledge-state-search-v2/kmeans/choose-k",
            "The silhouette coefficient can help compare candidate values of k. "
            "This passage concerns model selection for the number of clusters, "
            "not the optimization path induced by initial centroids.",
            (),
        ),
        (
            "kmeans_contradiction_global_optimum",
            "kmeans_initialization",
            "Benchmark negative control: K-means always finds the global optimum",
            "benchmark://knowledge-state-search-v2/kmeans/false-global-optimum",
            "K-means always reaches the global optimum, regardless of the initial "
            "centers, because every update removes all dependence on initialization.",
            (
                {
                    "task_id": "kmeans_initialization",
                    "requirement_id": "core_local_minimum",
                    "status": "contradicted",
                },
                {
                    "task_id": "kmeans_initialization",
                    "requirement_id": "misconception_global_optimum",
                    "status": "contradicted",
                },
            ),
        ),
        (
            "overfit_distractor_scaling",
            "overfitting_generalization",
            "Feature scaling and numerical optimization",
            "benchmark://knowledge-state-search-v2/overfit/scaling",
            "Feature scaling can affect numerical optimization and the relative "
            "magnitude of input variables. This passage does not establish the "
            "relationship between training accuracy and generalization.",
            (),
        ),
        (
            "overfit_contradiction_train_accuracy",
            "overfitting_generalization",
            "Benchmark negative control: training accuracy proves generalization",
            "benchmark://knowledge-state-search-v2/overfit/false-generalization",
            "A high training accuracy always proves that a model generalizes well "
            "to unseen data; a separate test set is unnecessary.",
            (
                {
                    "task_id": "overfitting_generalization",
                    "requirement_id": "core_fit_generalization",
                    "status": "contradicted",
                },
                {
                    "task_id": "overfitting_generalization",
                    "requirement_id": "misconception_train_accuracy",
                    "status": "contradicted",
                },
            ),
        ),
        (
            "pca_support_eigenvector",
            "pca_covariance",
            "Benchmark support control: covariance eigenvectors",
            "benchmark://knowledge-state-search-v2/pca/eigenvector",
            "For centered data, eigenvectors of the covariance matrix define the "
            "principal directions, while the corresponding eigenvalues quantify "
            "the variance along those directions.",
            (
                {
                    "task_id": "pca_covariance",
                    "requirement_id": "prereq_eigenvector",
                    "status": "supported",
                },
            ),
        ),
        (
            "pca_distractor_whitening",
            "pca_covariance",
            "PCA whitening and scale normalization",
            "benchmark://knowledge-state-search-v2/pca/whitening",
            "Whitening rescales projected components to unit variance. This "
            "passage concerns post-decomposition scaling rather than why the "
            "covariance matrix determines principal directions.",
            (),
        ),
        (
            "pca_contradiction_random_axes",
            "pca_covariance",
            "Benchmark negative control: PCA chooses random axes",
            "benchmark://knowledge-state-search-v2/pca/false-random-axes",
            "PCA chooses random orthogonal axes and does not use covariance or "
            "variance; the selected directions are unrelated to the data.",
            (
                {
                    "task_id": "pca_covariance",
                    "requirement_id": "core_variance_direction",
                    "status": "contradicted",
                },
                {
                    "task_id": "pca_covariance",
                    "requirement_id": "core_covariance_role",
                    "status": "contradicted",
                },
            ),
        ),
        (
            "svm_support_compare_kernels",
            "svm_kernel",
            "Benchmark support control: comparing linear and RBF kernels",
            "benchmark://knowledge-state-search-v2/svm/compare-kernels",
            "A linear kernel is a useful choice when the classes are approximately "
            "linearly separable in the original features, whereas an RBF kernel "
            "can model nonlinear boundaries through similarities in feature space.",
            (
                {
                    "task_id": "svm_kernel",
                    "requirement_id": "goal_compare",
                    "status": "supported",
                },
            ),
        ),
        (
            "svm_distractor_probability",
            "svm_kernel",
            "Probability estimates for support vector classifiers",
            "benchmark://knowledge-state-search-v2/svm/probability",
            "Probability calibration can be added to a classifier and may require "
            "cross-validation. This passage does not explain the feature-space "
            "effect of a kernel.",
            (),
        ),
        (
            "svm_contradiction_explicit_mapping",
            "svm_kernel",
            "Benchmark negative control: the kernel trick explicitly maps all data",
            "benchmark://knowledge-state-search-v2/svm/false-explicit-map",
            "The kernel trick requires explicitly constructing every high-dimensional "
            "feature vector before computing similarities.",
            (
                {
                    "task_id": "svm_kernel",
                    "requirement_id": "core_kernel_trick",
                    "status": "contradicted",
                },
            ),
        ),
    )
    result = []
    for source_id, task_id, title, url, text, source_annotations in controls:
        payload = {
            "source_id": source_id,
            "task_id": task_id,
            "title": title,
            "url": url,
            "provider": (
                "benchmark_negative_control"
                if "contradiction" in source_id
                else "benchmark_support_control"
                if "support" in source_id
                else "benchmark_distractor"
            ),
            "captured_at": "2026-07-21T00:00:00+00:00",
            "text": text,
        }
        payload["sha256"] = _source_checksum(payload)
        result.append(
            (
                payload,
                [
                    {
                        **item,
                        "source_id": source_id,
                    }
                    for item in source_annotations
                ],
            )
        )
    return tuple(result)


def _source_checksum(payload: dict[str, str]) -> str:
    raw = "\n".join(
        payload[field] for field in ("source_id", "task_id", "title", "url", "provider", "captured_at", "text")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    """Build the v2 dataset generation CLI."""

    parser = argparse.ArgumentParser(description="Build knowledge-state search confirmatory v2 artifacts.")
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS))
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    parser.add_argument("--output-tasks", default=str(DEFAULT_OUTPUT_TASKS))
    parser.add_argument("--output-snapshot", default=str(DEFAULT_OUTPUT_SNAPSHOT))
    return parser


def main() -> int:
    """Build and validate the v2 task and snapshot files."""

    args = build_parser().parse_args()
    task_path = Path(args.tasks)
    payload = json.loads(task_path.read_text(encoding="utf-8"))
    result = build_confirmatory_tasks(payload)
    output_tasks = Path(args.output_tasks)
    output_tasks.parent.mkdir(parents=True, exist_ok=True)
    output_tasks.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    build_confirmatory_snapshot(Path(args.snapshot), Path(args.output_snapshot))
    print(f"Wrote {output_tasks}")
    print(f"Wrote {args.output_snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
