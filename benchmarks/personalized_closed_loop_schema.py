"""Typed contracts and validation for personalized teaching closed-loop evaluations."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SchemaVersion = Literal["personalized-closed-loop/1.0"]
Category = Literal[
    "kc_routing",
    "profile_stratification",
    "history_utilization",
    "assessment_loop",
    "student_isolation",
    "lifecycle_idempotency",
]
StepType = Literal["open_session", "chat", "submit_assessment", "checkpoint", "retry_last_action"]
AssessmentOutcome = Literal["correct", "incorrect"]
HardGate = Literal["kc_correct", "profile_faithful", "student_isolation"]
CheckName = Literal[
    "sse_completed",
    "route_recorded",
    "kc_correct",
    "profile_updated",
    "profile_faithful",
    "interaction_persisted",
    "assessment_persisted",
    "assessment_kc_correct",
    "assessment_difficulty_matches",
    "answer_outcome_matches",
    "student_isolation",
    "idempotent_persistence",
    "cross_session_state",
    "controlled_degradation",
]


class EvalModel(BaseModel):
    """Reject undeclared fields and coercion at every dataset boundary."""

    model_config = ConfigDict(extra="forbid", strict=True)


class GenerationMetadata(EvalModel):
    model: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    prompt_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    review_status: Literal["frozen", "draft"]
    source: Literal["deterministic_local", "llm"] = "deterministic_local"


class Actor(EvalModel):
    actor_id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,63}$")]


class ExpectedChat(EvalModel):
    personalized_route: bool | None = None
    primary_kc_id: str | None = None
    allowed_kc_ids: list[str] = Field(default_factory=list)
    forbidden_student_facts: list[str] = Field(default_factory=list)
    expected_difficulty: Literal["basic", "intermediate", "advanced"] | None = None


class Step(EvalModel):
    type: StepType
    actor_id: str
    session_alias: str | None = None
    message: str | None = Field(default=None, min_length=1, max_length=2000)
    outcome: AssessmentOutcome | None = None
    expected: ExpectedChat | None = None
    checks: list[CheckName] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_shape(self) -> Step:
        if self.type in {"open_session", "chat", "submit_assessment", "checkpoint", "retry_last_action"}:
            if not self.actor_id or not self.actor_id.strip():
                raise ValueError("step actor_id is required")
        if (
            self.type in {"open_session", "chat", "submit_assessment", "checkpoint", "retry_last_action"}
            and not self.session_alias
        ):
            raise ValueError(f"{self.type} requires session_alias")
        if self.type == "chat" and not self.message:
            raise ValueError("chat requires message")
        if self.type == "submit_assessment" and self.outcome is None:
            raise ValueError("submit_assessment requires outcome")
        if self.type != "submit_assessment" and self.outcome is not None:
            raise ValueError("outcome is only valid for submit_assessment")
        if self.type == "checkpoint" and not self.checks:
            raise ValueError("checkpoint requires checks")
        if self.type != "chat" and self.expected is not None:
            raise ValueError("expected is only valid for chat")
        return self


class Trajectory(EvalModel):
    id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{2,99}$")]
    category: Category
    description: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    actors: list[Actor] = Field(min_length=1)
    steps: list[Step] = Field(min_length=2)
    hard_gates: list[HardGate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_trajectory(self) -> Trajectory:
        actor_ids = [actor.actor_id for actor in self.actors]
        if len(actor_ids) != len(set(actor_ids)):
            raise ValueError("actor IDs must be unique")
        session_aliases: set[str] = set()
        opened_sessions: set[tuple[str, str]] = set()
        has_assessment = False
        has_interleaving = False
        previous_actor: str | None = None
        for step in self.steps:
            if step.actor_id not in actor_ids:
                raise ValueError(f"unknown actor: {step.actor_id}")
            if step.session_alias:
                session_aliases.add(step.session_alias)
            if step.type == "open_session":
                opened_sessions.add((step.actor_id, step.session_alias or ""))
            elif step.type != "open_session" and (step.actor_id, step.session_alias or "") not in opened_sessions:
                raise ValueError(f"session used before open_session: {step.session_alias}")
            if step.type == "submit_assessment":
                has_assessment = True
            if previous_actor is not None and previous_actor != step.actor_id:
                has_interleaving = True
            previous_actor = step.actor_id
        if len(session_aliases) < 2:
            raise ValueError("each trajectory requires at least two session aliases")
        if self.category == "assessment_loop" and not has_assessment:
            raise ValueError("assessment_loop trajectory requires submit_assessment")
        if self.category == "student_isolation" and (len(actor_ids) < 2 or not has_interleaving):
            raise ValueError("student_isolation trajectory requires interleaved actors")
        return self


class Dataset(EvalModel):
    schema_version: SchemaVersion
    dataset_name: Literal["personalized_closed_loop_v1"]
    created_at: date
    generation: GenerationMetadata
    trajectories: list[Trajectory] = Field(min_length=24, max_length=24)

    @model_validator(mode="after")
    def validate_dataset(self) -> Dataset:
        ids = [item.id for item in self.trajectories]
        if len(ids) != len(set(ids)):
            raise ValueError("trajectory IDs must be unique")
        required = {
            "kc_routing": 4,
            "profile_stratification": 5,
            "history_utilization": 5,
            "assessment_loop": 4,
            "student_isolation": 4,
            "lifecycle_idempotency": 2,
        }
        counts = {category: sum(item.category == category for item in self.trajectories) for category in required}
        if counts != required:
            raise ValueError(f"coverage mismatch: {counts}")
        return self


def canonical_sha256(value: BaseModel | dict) -> str:
    """Hash compact, sorted UTF-8 JSON for provenance and prompt snapshots."""

    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def load_dataset(path: str | Path) -> Dataset:
    """Load and validate a frozen dataset."""

    return Dataset.model_validate_json(Path(path).read_bytes())


def current_course_kc_ids(catalog_path: str | Path = "data/knowledge_graph.json") -> set[str]:
    """Return canonical course KC IDs without importing runtime application code."""

    payload = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    return {str(item["canonical_id"]) for item in payload.get("concepts", []) if item.get("canonical_id")}


def validate_dataset(path: str | Path, *, catalog_path: str | Path = "data/knowledge_graph.json") -> Dataset:
    """Validate structure and ensure every declared KC exists in the course graph."""

    dataset = load_dataset(path)
    known = current_course_kc_ids(catalog_path)
    for trajectory in dataset.trajectories:
        for step in trajectory.steps:
            expected = step.expected
            if expected is None:
                continue
            declared = set(expected.allowed_kc_ids)
            if expected.primary_kc_id:
                declared.add(expected.primary_kc_id)
            unknown = declared - known
            if unknown:
                raise ValueError(f"{trajectory.id}: unknown KC IDs: {sorted(unknown)}")
    return dataset


def dataset_json_schema() -> dict:
    """Return JSON Schema 2020-12 for tooling and CI."""

    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **Dataset.model_json_schema()}


__all__ = [
    "Dataset",
    "Trajectory",
    "Step",
    "ExpectedChat",
    "GenerationMetadata",
    "canonical_sha256",
    "current_course_kc_ids",
    "dataset_json_schema",
    "load_dataset",
    "validate_dataset",
]
