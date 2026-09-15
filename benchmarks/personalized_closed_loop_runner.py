"""Run frozen personalized closed-loop trajectories through the FastAPI boundary."""

from __future__ import annotations

import argparse
import inspect
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmarks.personalized_closed_loop_judge import PersonalizedClosedLoopJudge
from benchmarks.personalized_closed_loop_schema import Dataset, Trajectory, validate_dataset
from benchmarks.personalized_closed_loop_scoring import score_trajectory, summarize_scores


def _patch_httpx_compat() -> None:
    """Support the repository's Starlette TestClient with httpx 0.28+."""

    import httpx

    if "app" in inspect.signature(httpx.Client.__init__).parameters:
        return
    original_init = httpx.Client.__init__
    if getattr(original_init, "_personalized_eval_app_kwarg_patch", False):
        return

    def patched_init(self, *args: Any, **kwargs: Any):
        kwargs.pop("app", None)
        return original_init(self, *args, **kwargs)

    patched_init._personalized_eval_app_kwarg_patch = True
    httpx.Client.__init__ = patched_init


def _parse_sse(response_text: str) -> list[dict[str, Any]]:
    events = []
    for line in response_text.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            value = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _configure_runtime(root: Path) -> None:
    """Point all mutable runtime stores at one trajectory directory."""

    import ds_course_agent.shared.config as config

    paths = {
        "APP_DB_PATH": root / "app.db",
        "AUTH_DB_PATH": root / "auth.db",
        "ASSESSMENT_DB_PATH": root / "assessment.db",
        "CHAT_HISTORY_DIR": root / "chat_history",
        "TOOL_RESULT_ARTIFACT_DIR": root / "artifacts",
    }
    for name, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        setattr(config, name, str(path))
    os.environ.update({name: str(path) for name, path in paths.items()})


def _reset_process_singletons_for_runtime() -> None:
    """Drop path-bound process singletons after switching to a trajectory sandbox."""

    from ds_course_agent.agent import learning_loop
    from ds_course_agent.agent import service as agent_service
    from ds_course_agent.api import core_bridge
    from ds_course_agent.assessment import application as assessment_application
    from ds_course_agent.assessment import service as assessment_service

    # The runner waits for each preparation before advancing a trajectory, so
    # dropping the old coordinator is sufficient and avoids blocking on a
    # provider call that belongs to a previous sandbox.
    learning_loop._loop = None
    core_bridge._agent_service = None
    agent_service._agent_service = None
    assessment_application._application_service = None
    assessment_service._assessment_service = None


def _new_clients(trajectory: Trajectory, client_factory: Any) -> dict[str, Any]:
    from ds_course_agent.api.auth import models
    from ds_course_agent.api.auth.service import hash_password

    clients: dict[str, Any] = {}
    for actor in trajectory.actors:
        client = client_factory()
        username = f"eval_{actor.actor_id}_{uuid.uuid4().hex[:8]}"
        models.create_or_update_user(
            username=username,
            password_hash=hash_password("eval-only-password"),
            student_id=actor.actor_id,
            display_name=actor.actor_id,
        )
        response = client.post("/api/auth/login", json={"username": username, "password": "eval-only-password"})
        response.raise_for_status()
        clients[actor.actor_id] = client
    return clients


def _counts(
    client: Any,
    sessions: dict[str, str],
    *,
    app_db: Path | None = None,
    assessment_db: Path | None = None,
    student_id: str | None = None,
) -> dict[str, int]:
    messages = 0
    for session_id in sessions.values():
        response = client.get(f"/api/chat/history/{session_id}")
        if response.status_code == 200:
            messages += int(response.json().get("total", 0))
    preparations = client.get("/api/assessments/preparations")
    assessment_count = len(preparations.json()) if preparations.status_code == 200 else 0
    counts = {"messages": messages, "preparations": assessment_count}
    if app_db is not None and app_db.exists() and student_id:
        with sqlite3.connect(app_db) as connection:
            counts["learning_events"] = (
                connection.execute(
                    "SELECT COUNT(*) FROM learning_events WHERE student_id = ?", (student_id,)
                ).fetchone()[0]
                if _table_exists(connection, "learning_events")
                else 0
            )
            counts["episodes"] = (
                connection.execute(
                    "SELECT COUNT(*) FROM interaction_episodes WHERE student_id = ?", (student_id,)
                ).fetchone()[0]
                if _table_exists(connection, "interaction_episodes")
                else 0
            )
            counts["profiles"] = (
                connection.execute(
                    "SELECT COUNT(*) FROM learner_profile_snapshots WHERE student_id = ?", (student_id,)
                ).fetchone()[0]
                if _table_exists(connection, "learner_profile_snapshots")
                else 0
            )
    if assessment_db is not None and assessment_db.exists() and student_id:
        with sqlite3.connect(assessment_db) as connection:
            counts["assessments"] = (
                connection.execute("SELECT COUNT(*) FROM assessments WHERE student_id = ?", (student_id,)).fetchone()[0]
                if _table_exists(connection, "assessments")
                else 0
            )
    return counts


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
        is not None
    )


def _learning_facts(app_db: Path, student_id: str) -> tuple[list[str], int]:
    if not app_db.exists():
        return [], 0
    with sqlite3.connect(app_db) as connection:
        if not _table_exists(connection, "learning_events"):
            return [], 0
        rows = connection.execute(
            "SELECT concept_id FROM learning_events WHERE student_id = ? AND concept_id IS NOT NULL ORDER BY observed_at, id",
            (student_id,),
        ).fetchall()
        sessions = connection.execute(
            "SELECT COUNT(DISTINCT session_id) FROM learning_events WHERE student_id = ?", (student_id,)
        ).fetchone()[0]
    return list(dict.fromkeys(str(row[0]) for row in rows)), int(sessions)


def _assessment_answer_keys(assessment_db: Path, assessment_id: str) -> dict[str, str]:
    with sqlite3.connect(assessment_db) as connection:
        rows = connection.execute(
            "SELECT id, correct_option_id FROM assessment_questions WHERE assessment_id = ? ORDER BY position",
            (assessment_id,),
        ).fetchall()
    return {str(question_id): str(correct_id) for question_id, correct_id in rows}


def _student_isolation_facts(
    app_db: Path,
    assessment_db: Path,
    actor_ids: set[str],
) -> tuple[bool, str]:
    """Check that persisted student-scoped rows stay within this trajectory's actors."""

    violations: list[str] = []
    for database_path in (app_db, assessment_db):
        if not database_path.exists():
            continue
        with sqlite3.connect(database_path) as connection:
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            for (table_name,) in tables:
                columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")}
                if "student_id" not in columns:
                    continue
                rows = connection.execute(f"SELECT DISTINCT student_id FROM {table_name}").fetchall()
                unexpected = {str(row[0]) for row in rows if row[0] is not None} - actor_ids
                if unexpected:
                    violations.append(f"{database_path.name}:{table_name}:{sorted(unexpected)}")

            if _table_exists(connection, "sessions") and _table_exists(connection, "messages"):
                rows = connection.execute(
                    """
                    SELECT m.session_id, m.student_id, s.student_id
                    FROM messages AS m
                    LEFT JOIN sessions AS s ON s.id = m.session_id
                    WHERE s.student_id IS NULL OR s.student_id <> m.student_id
                    """
                ).fetchall()
                violations.extend(
                    f"{database_path.name}:message_session:{session_id}:{message_student}:{session_student}"
                    for session_id, message_student, session_student in rows
                )
    if violations:
        return False, "; ".join(violations)
    return True, f"all student-scoped rows belong to {sorted(actor_ids)!r}"


def _wait_preparation(client: Any, *, timeout: float = 180.0) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get("/api/assessments/preparations")
        if response.status_code == 200:
            jobs = response.json()
            ready = next((job for job in jobs if job.get("status") == "ready" and job.get("assessment_id")), None)
            if ready:
                return ready
            if jobs and all(job.get("status") == "failed" for job in jobs):
                return None
        time.sleep(0.1)
    return None


def run_trajectory(trajectory: Trajectory, *, output_root: Path, client_factory: Any | None = None) -> dict[str, Any]:
    """Execute one trajectory and return a serializable trace."""

    root = output_root / trajectory.id
    root.mkdir(parents=True, exist_ok=True)
    trace: dict[str, Any] = {
        "trajectory_id": trajectory.id,
        "steps": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _configure_runtime(root)
        _reset_process_singletons_for_runtime()
        _patch_httpx_compat()
        from fastapi.testclient import TestClient

        from ds_course_agent.api.main import app

        clients = _new_clients(trajectory, client_factory or (lambda: TestClient(app)))
        sessions: dict[tuple[str, str], str] = {}
        last_action: tuple[str, str, dict[str, Any]] | None = None
        app_db = root / "app.db"
        assessment_db = root / "assessment.db"
        for step in trajectory.steps:
            client = clients[step.actor_id]
            key = (step.actor_id, step.session_alias or "")
            observed: dict[str, Any] = {}
            if step.type == "open_session":
                response = client.post("/api/sessions", json={"title": trajectory.id})
                if response.status_code != 200:
                    raise RuntimeError(f"open_session HTTP {response.status_code}")
                sessions[key] = response.json()["id"]
                observed["session_id"] = sessions[key]
            elif step.type == "chat":
                session_id = sessions[key]
                before_facts, before_sessions = _learning_facts(app_db, step.actor_id)
                response = client.post(
                    "/api/chat/send/stream",
                    json={"session_id": session_id, "message": step.message},
                )
                events = _parse_sse(response.text)
                final = next((event for event in reversed(events) if event.get("type") == "final"), {})
                observed.update(final)
                observed["terminal_type"] = final.get("type")
                observed["personalized_route"] = bool(final.get("personalized_route", False))
                observed["primary_kc_id"] = final.get("primary_kc_id")
                observed["matched_kc_ids"] = final.get("matched_kc_ids", [])
                observed["intent"] = final.get("intent")
                after_facts, after_sessions = _learning_facts(app_db, step.actor_id)
                observed["matched_kc_ids"] = after_facts
                observed["primary_kc_id"] = after_facts[0] if after_facts else None
                observed["personalized_route"] = bool(before_facts or before_sessions)
                observed["profile_updated"] = after_sessions > 0
                last_action = ("chat", session_id, {"message": step.message})
            elif step.type == "submit_assessment":
                job = _wait_preparation(client)
                if not job:
                    raise RuntimeError("assessment preparation did not become ready")
                assessment_id = job["assessment_id"]
                opened = client.post(f"/api/assessments/{assessment_id}/open")
                assessment = opened.json()
                questions = assessment.get("questions") or []
                if not questions:
                    raise RuntimeError("assessment contains no questions")
                keys = _assessment_answer_keys(assessment_db, assessment_id)
                answers = []
                for question in questions:
                    correct = keys[question["id"]]
                    selected = (
                        correct
                        if step.outcome == "correct"
                        else next(option["id"] for option in question["options"] if option["id"] != correct)
                    )
                    answers.append(
                        {"question_id": question["id"], "selected_option_id": selected, "response_time_ms": 1}
                    )
                result = client.post(f"/api/assessments/{assessment_id}/submit", json={"answers": answers})
                if result.status_code != 200:
                    raise RuntimeError(f"assessment submit HTTP {result.status_code}")
                values = result.json().get("questions", [])
                observed["outcome"] = "correct" if all(item.get("is_correct") for item in values) else "incorrect"
                observed["assessment_id"] = assessment_id
                last_action = ("assessment", assessment_id, {"answers": answers})
            elif step.type == "checkpoint":
                counts = _counts(
                    client,
                    {alias: value for (actor, alias), value in sessions.items() if actor == step.actor_id},
                    app_db=app_db,
                    assessment_db=assessment_db,
                    student_id=step.actor_id,
                )
                derived = {
                    "profile_updated": counts.get("profiles", 0) > 0,
                    "interaction_persisted": counts.get("episodes", 0) > 0,
                    "assessment_persisted": counts.get("assessments", 0) > 0,
                    "cross_session_state": counts.get("learning_events", 0) > 0,
                    "sse_completed": any(item.get("terminal_type") == "final" for item in trace["steps"]),
                    "idempotent_persistence": False,
                }
                if trace["steps"] and isinstance(trace["steps"][-1], dict):
                    retry = trace["steps"][-1]
                    if "before_counts" in retry and "after_counts" in retry:
                        derived["idempotent_persistence"] = retry["before_counts"] == retry["after_counts"]
                if "student_isolation" in step.checks:
                    isolated, evidence = _student_isolation_facts(
                        app_db, assessment_db, {actor.actor_id for actor in trajectory.actors}
                    )
                    derived["student_isolation"] = isolated
                    observed["student_isolation_evidence"] = evidence
                observed.update({name: bool(derived.get(name, False)) for name in step.checks})
                observed["counts"] = _counts(
                    client,
                    {alias: value for (actor, alias), value in sessions.items() if actor == step.actor_id},
                    app_db=app_db,
                    assessment_db=assessment_db,
                    student_id=step.actor_id,
                )
            elif step.type == "retry_last_action":
                before = _counts(
                    client,
                    {alias: value for (actor, alias), value in sessions.items() if actor == step.actor_id},
                    app_db=app_db,
                    assessment_db=assessment_db,
                    student_id=step.actor_id,
                )
                if last_action and last_action[0] == "chat":
                    response = client.post(
                        "/api/chat/send/stream", json={"session_id": last_action[1], **last_action[2]}
                    )
                    if response.status_code not in {200, 409}:
                        raise RuntimeError(f"retry chat HTTP {response.status_code}")
                elif last_action and last_action[0] == "assessment":
                    response = client.post(
                        f"/api/assessments/{last_action[1]}/submit",
                        json={"answers": last_action[2]["answers"]},
                    )
                    if response.status_code not in {200, 409}:
                        raise RuntimeError(f"retry assessment HTTP {response.status_code}")
                after = _counts(
                    client,
                    {alias: value for (actor, alias), value in sessions.items() if actor == step.actor_id},
                    app_db=app_db,
                    assessment_db=assessment_db,
                    student_id=step.actor_id,
                )
                observed.update(before_counts=before, after_counts=after)
            trace["steps"].append(observed)
        trace["finished_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        trace["infrastructure_error"] = f"{type(exc).__name__}: {exc}"
    return trace


def run_dataset(dataset: Dataset, *, output: Path, judge: PersonalizedClosedLoopJudge | None = None) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    traces = []
    scores = []
    judges = []
    for trajectory in dataset.trajectories:
        trace = run_trajectory(trajectory, output_root=output / "runtime")
        with (output / "trajectory_results.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(trace, ensure_ascii=False) + "\n")
        traces.append(trace)
        score = score_trajectory(trajectory, trace)
        scores.append(score)
        if judge is not None:
            judges.append(
                {
                    "trajectory_id": trajectory.id,
                    **judge.judge({"trajectory": trajectory.model_dump(mode="json"), "trace": trace, "score": score}),
                }
            )
    summary = summarize_scores(dataset, scores)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "judge_results.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in judges), encoding="utf-8"
    )
    (output / "human_review_queue.jsonl").write_text(
        "".join(
            json.dumps(item, ensure_ascii=False) + "\n"
            for item in judges
            if item.get("needs_human_review") or not item.get("kc_correct", {}).get("passed", False)
        ),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("benchmarks/data/personalized_closed_loop_v1.json"))
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--trajectory-id", action="append")
    parser.add_argument("--category", action="append")
    parser.add_argument("--skip-judge", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    dataset = validate_dataset(args.dataset)
    selected = [
        item
        for item in dataset.trajectories
        if (not args.trajectory_id or item.id in args.trajectory_id)
        and (not args.category or item.category in args.category)
    ]
    if not selected:
        raise SystemExit("No trajectories match the requested filters")
    dataset = dataset.model_copy(update={"trajectories": selected})
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or Path("var/artifacts/personalized_closed_loop_eval") / run_id
    judge = (
        None if args.skip_judge or not args.judge_model else PersonalizedClosedLoopJudge(model_name=args.judge_model)
    )
    summary = run_dataset(dataset, output=output, judge=judge)
    (output / "manifest.json").write_text(
        json.dumps({"dataset": str(args.dataset), "run_id": run_id, "judge_model": args.judge_model}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
