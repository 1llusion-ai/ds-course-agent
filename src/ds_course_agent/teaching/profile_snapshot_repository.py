"""Relation-backed learner profile projections and event replay."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.shared.database import connect_sqlite
from ds_course_agent.teaching.database import migrate_learner_memory_database
from ds_course_agent.teaching.learning_event_repository import SQLiteLearningEventRepository
from ds_course_agent.teaching.memory_core import MemoryCore
from ds_course_agent.teaching.profile_models import ProfileWindowSnapshot, StudentProfile


@dataclass(frozen=True)
class ProfileSnapshot:
    student_id: str
    version: int
    computed_at: datetime
    source_event_cursor: str
    profile: StudentProfile


class SQLiteProfileSnapshotRepository:
    """Persist rebuildable profile snapshots sourced only from SQLite events."""

    def __init__(self, path: str | Path | None = None, *, profile_replayer: MemoryCore | None = None) -> None:
        self._path = Path(path or config.APP_DB_PATH)
        self._events = SQLiteLearningEventRepository(self._path)
        self._replayer = profile_replayer or MemoryCore.__new__(MemoryCore)

    def project(self, student_id: str, *, force: bool = False) -> ProfileSnapshot:
        self._validate_student_id(student_id)
        records = self._all_events(student_id)
        cursor = records[-1].event.event_id if records else ""
        latest = self.get_latest(student_id)
        if latest and not force and latest.source_event_cursor == cursor:
            return latest
        profile = self._replayer.replay_profile(student_id, (record.event for record in records))
        version = (latest.version + 1) if latest else 1
        snapshot = ProfileSnapshot(student_id, version, datetime.now(timezone.utc), cursor, profile)
        migrate_learner_memory_database(self._path)
        connection = connect_sqlite(self._path)
        try:
            connection.execute(
                "INSERT INTO learner_profile_snapshots "
                "(student_id, version, computed_at, source_event_cursor, payload_json) VALUES (?, ?, ?, ?, ?)",
                (
                    student_id,
                    version,
                    snapshot.computed_at.isoformat(),
                    cursor,
                    json.dumps(profile.to_dict(), ensure_ascii=False),
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return snapshot

    def get_latest(self, student_id: str) -> ProfileSnapshot | None:
        self._validate_student_id(student_id)
        migrate_learner_memory_database(self._path)
        connection = connect_sqlite(self._path)
        try:
            row = connection.execute(
                "SELECT * FROM learner_profile_snapshots WHERE student_id = ? ORDER BY version DESC LIMIT 1",
                (student_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return ProfileSnapshot(
            student_id=str(row["student_id"]),
            version=int(row["version"]),
            computed_at=datetime.fromisoformat(str(row["computed_at"])),
            source_event_cursor=str(row["source_event_cursor"]),
            profile=StudentProfile.from_dict(json.loads(row["payload_json"])),
        )

    def list_student_ids(self) -> tuple[str, ...]:
        """Return student identities represented by durable teaching facts."""

        migrate_learner_memory_database(self._path)
        connection = connect_sqlite(self._path)
        try:
            rows = connection.execute("SELECT DISTINCT student_id FROM learning_events ORDER BY student_id").fetchall()
        finally:
            connection.close()
        return tuple(str(row["student_id"]) for row in rows)

    def verify_replay(self, student_id: str) -> bool:
        """Confirm the latest persisted projection equals a fresh event replay."""

        snapshot = self.get_latest(student_id)
        if snapshot is None:
            return False
        records = self._all_events(student_id)
        replayed = self._replayer.replay_profile(student_id, (record.event for record in records))
        return (
            snapshot.source_event_cursor == (records[-1].event.event_id if records else "")
            and snapshot.profile.to_dict() == replayed.to_dict()
        )

    def _all_events(self, student_id: str):
        return self._events.list_all_for_student(student_id)

    @staticmethod
    def _validate_student_id(student_id: str) -> None:
        if not student_id or not student_id.strip():
            raise ValueError("student_id is required")


class SQLiteProfileReadService:
    """Compatibility-shaped profile reader backed by durable teaching facts."""

    def __init__(self, repository: SQLiteProfileSnapshotRepository | None = None) -> None:
        self._repository = repository or SQLiteProfileSnapshotRepository()

    def aggregate_profile(self, student_id: str) -> None:
        self._repository.project(student_id)

    def get_profile(self, student_id: str) -> StudentProfile:
        return self._repository.project(student_id).profile

    def get_profile_window(
        self,
        student_id: str,
        days: int,
        *,
        now: float | None = None,
        timezone_offset_minutes: int = 0,
    ) -> ProfileWindowSnapshot:
        if days < 1:
            raise ValueError("days must be positive")
        if not -840 <= timezone_offset_minutes <= 840:
            raise ValueError("timezone_offset_minutes must be between -840 and 840")
        records = self._repository._all_events(student_id)
        end = datetime.now(timezone.utc).timestamp() if now is None else float(now)
        local_timezone = timezone(-timedelta(minutes=timezone_offset_minutes))
        current_day = datetime.fromtimestamp(end, tz=local_timezone).date()
        first_day = current_day - timedelta(days=days - 1)
        start = datetime.combine(first_day, time.min, tzinfo=local_timezone).timestamp()
        events = [record.event for record in records if start <= record.event.timestamp <= end]
        profile = self._repository._replayer.replay_profile(student_id, events)
        counts = Counter(
            datetime.fromtimestamp(event.timestamp, tz=local_timezone).date().isoformat() for event in events
        )
        daily_activity = {
            (first_day + timedelta(days=index)).isoformat(): counts.get(
                (first_day + timedelta(days=index)).isoformat(), 0
            )
            for index in range(days)
        }
        return ProfileWindowSnapshot(
            profile=profile,
            daily_activity=daily_activity,
            start_timestamp=start,
            end_timestamp=end,
        )

    def resolve_active_weak_spot(self, student_id: str, concept_id: str):
        """Append a mastery fact and rebuild the SQLite profile projection."""

        from ds_course_agent.teaching.learning_event_repository import LearningEventRecord
        from ds_course_agent.teaching.learning_events import build_mastery_signal_event

        profile = self.get_profile(student_id)
        weak_spot = profile.get_weak_spot(concept_id)
        if weak_spot is None:
            raise KeyError(concept_id)
        source_event_id = next(
            (signal.get("event_id") for signal in reversed(weak_spot.signals) if signal.get("event_id")),
            f"manual_anchor::{concept_id}",
        )
        event = build_mastery_signal_event(
            session_id="profile_manual_action",
            student_id=student_id,
            concept_id=concept_id,
            source_event_id=source_event_id,
            signal_type="manual_resolve",
        )
        self._repository._events.append(LearningEventRecord(event, f"manual:{event.event_id}"))
        self._repository.project(student_id)
        resolved = self.get_profile(student_id).get_resolved_weak_spot(concept_id)
        if resolved is None:
            raise RuntimeError(f"Failed to resolve weak spot: {concept_id}")
        return resolved


__all__ = ["ProfileSnapshot", "SQLiteProfileReadService", "SQLiteProfileSnapshotRepository"]
