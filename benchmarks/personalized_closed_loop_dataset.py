"""Build the deterministic v1 personalized closed-loop fixture."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from benchmarks.personalized_closed_loop_schema import (
    Actor,
    Dataset,
    ExpectedChat,
    GenerationMetadata,
    Step,
    Trajectory,
    canonical_sha256,
)

KC = ("pca", "svm", "linear_regression", "decision_tree", "cross_validation")
KC_LABELS = {
    "pca": "主成分分析",
    "svm": "支持向量机",
    "linear_regression": "线性回归",
    "decision_tree": "决策树",
    "cross_validation": "交叉验证",
}


def _chat(actor: str, session: str, kc: str, text: str, *, personalized: bool | None = None) -> Step:
    return Step(
        type="chat",
        actor_id=actor,
        session_alias=session,
        message=text,
        expected=ExpectedChat(
            personalized_route=personalized,
            primary_kc_id=kc,
            allowed_kc_ids=[kc],
        ),
    )


def _trajectory(index: int, category: str, kc: str, *, actor_count: int = 1, assessment: bool = False) -> Trajectory:
    label = KC_LABELS[kc]
    actors = [Actor(actor_id=f"student_{letter}") for letter in "ab"[:actor_count]]
    first = actors[0].actor_id
    second = actors[-1].actor_id
    steps = [
        Step(type="open_session", actor_id=first, session_alias="first"),
        _chat(first, "first", kc, f"请解释 {label} 的核心概念。", personalized=False),
        Step(type="open_session", actor_id=first, session_alias="second"),
        _chat(first, "second", kc, f"我还不太理解{label}，请结合上次内容再解释一次。", personalized=True),
    ]
    if actor_count == 2:
        steps = [
            Step(type="open_session", actor_id=first, session_alias="first"),
            Step(type="open_session", actor_id=second, session_alias="first"),
            _chat(first, "first", kc, f"我在{label}上的主要问题是什么？", personalized=False),
            _chat(second, "first", kc, f"请解释{label}，但不要使用其他学生的历史。", personalized=False),
            Step(type="open_session", actor_id=first, session_alias="second"),
            _chat(first, "second", kc, f"基于我的历史继续讲解{label}。", personalized=True),
        ]
    if assessment:
        steps.extend(
            [
                _chat(
                    first,
                    "second",
                    kc,
                    f"帮我出一道测验题，主题是{label}。",
                    personalized=True,
                ),
                Step(type="submit_assessment", actor_id=first, session_alias="second", outcome="incorrect"),
                Step(
                    type="checkpoint",
                    actor_id=first,
                    session_alias="second",
                    checks=["assessment_persisted", "profile_updated"],
                ),
            ]
        )
    else:
        steps.append(
            Step(
                type="checkpoint",
                actor_id=first,
                session_alias="second",
                checks=["profile_updated", "interaction_persisted", "cross_session_state"],
            )
        )
    if category == "lifecycle_idempotency":
        steps.append(Step(type="retry_last_action", actor_id=first, session_alias="second"))
        steps.append(Step(type="checkpoint", actor_id=first, session_alias="second", checks=["idempotent_persistence"]))
    return Trajectory(
        id=f"{category}_{index:03d}",
        category=category,
        description=f"Deterministic closed-loop case for {kc}.",
        actors=actors,
        steps=steps,
        hard_gates=["kc_correct", "profile_faithful"] + (["student_isolation"] if actor_count == 2 else []),
    )


def build_dataset() -> Dataset:
    """Return the frozen 24-case coverage matrix."""

    specs = [
        ("kc_routing", 4, 1, False),
        ("profile_stratification", 5, 1, False),
        ("history_utilization", 5, 1, False),
        ("assessment_loop", 4, 1, True),
        ("student_isolation", 4, 2, False),
        ("lifecycle_idempotency", 2, 1, True),
    ]
    trajectories: list[Trajectory] = []
    offset = 0
    for category, count, actors, assessment in specs:
        for index in range(1, count + 1):
            trajectories.append(
                _trajectory(index, category, KC[offset % len(KC)], actor_count=actors, assessment=assessment)
            )
            offset += 1
    prompt_digest = canonical_sha256({"generator": "deterministic-local-v1", "coverage": [item[0] for item in specs]})
    return Dataset(
        schema_version="personalized-closed-loop/1.0",
        dataset_name="personalized_closed_loop_v1",
        created_at=date(2026, 9, 13),
        generation=GenerationMetadata(
            model="deterministic-local-v1",
            prompt_sha256=prompt_digest,
            review_status="frozen",
            source="deterministic_local",
        ),
        trajectories=trajectories,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/data/personalized_closed_loop_v1.json"))
    args = parser.parse_args()
    dataset = build_dataset()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(dataset.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.output}: {len(dataset.trajectories)} trajectories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
