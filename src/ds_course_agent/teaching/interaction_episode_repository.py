"""Student-scoped persistence for interaction episode projections."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import ds_course_agent.shared.config as config
from ds_course_agent.shared.database import connect_sqlite
from ds_course_agent.teaching.database import migrate_learner_memory_database
from ds_course_agent.teaching.personalization import EpisodeOutcome, InteractionEpisode


class SQLiteInteractionEpisodeRepository:
    """Persist rebuildable episode projections and their typed relationships."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path or config.APP_DB_PATH)

    def save(self, episode: InteractionEpisode) -> bool:
        """Create or update one episode and its links atomically.

        Returns ``False`` when the exact projection is already present.
        """

        self._validate_episode(episode)
        migrate_learner_memory_database(self._path)
        connection = connect_sqlite(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM interaction_episodes WHERE id = ? AND student_id = ?",
                (episode.episode_id, episode.student_id),
            ).fetchone()
            values = self._episode_values(episode)
            changed = existing is None or tuple(existing) != values
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO interaction_episodes (
                        id, student_id, session_id, turn_id, learner_question,
                        observed_signals_json, inferred_difficulties_json,
                        teaching_approach_json, outcome, related_episode_id,
                        created_at, updated_at, extractor_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            elif changed:
                connection.execute(
                    """
                    UPDATE interaction_episodes SET
                        session_id = ?, turn_id = ?, learner_question = ?,
                        observed_signals_json = ?, inferred_difficulties_json = ?,
                        teaching_approach_json = ?, outcome = ?,
                        related_episode_id = ?, created_at = ?, updated_at = ?,
                        extractor_version = ?
                    WHERE id = ? AND student_id = ?
                    """,
                    (*values[2:], episode.episode_id, episode.student_id),
                )
            self._replace_concepts(connection, episode)
            self._replace_evidence(connection, episode)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return changed

    def list_for_student(
        self,
        student_id: str,
        *,
        concept_ids: Sequence[str] = (),
        outcomes: Sequence[EpisodeOutcome] = (),
        limit: int = 6,
    ) -> tuple[InteractionEpisode, ...]:
        """Return newest episodes belonging only to ``student_id``."""

        self._validate_student_id(student_id)
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        migrate_learner_memory_database(self._path)
        clauses = ["e.student_id = ?"]
        params: list[object] = [student_id]
        if outcomes:
            placeholders = ", ".join("?" for _ in outcomes)
            clauses.append(f"e.outcome IN ({placeholders})")
            params.extend(outcome.value for outcome in outcomes)
        if concept_ids:
            placeholders = ", ".join("?" for _ in concept_ids)
            clauses.append(
                "EXISTS (SELECT 1 FROM interaction_episode_concepts c "
                "WHERE c.episode_id = e.id AND c.student_id = e.student_id "
                f"AND c.concept_id IN ({placeholders}))"
            )
            params.extend(concept_ids)
        params.append(limit)
        query = (
            "SELECT e.* FROM interaction_episodes e WHERE "
            + " AND ".join(clauses)
            + " ORDER BY e.updated_at DESC, e.id DESC LIMIT ?"
        )
        connection = connect_sqlite(self._path)
        try:
            rows = connection.execute(query, params).fetchall()
            episodes = [self._episode_from_row(row) for row in rows]
            episodes = [self._with_links(connection, episode) for episode in episodes]
        finally:
            connection.close()
        return tuple(episodes)

    def get_for_turn(self, student_id: str, session_id: str, turn_id: str) -> InteractionEpisode | None:
        """Return the projection for one student-scoped completed turn."""
        self._validate_student_id(student_id)
        if not session_id.strip() or not turn_id.strip():
            raise ValueError("session_id and turn_id are required")
        migrate_learner_memory_database(self._path)
        connection = connect_sqlite(self._path)
        try:
            row = connection.execute(
                "SELECT * FROM interaction_episodes WHERE student_id = ? AND session_id = ? AND turn_id = ?",
                (student_id, session_id, turn_id),
            ).fetchone()
            if row is None:
                return None
            return self._with_links(connection, self._episode_from_row(row))
        finally:
            connection.close()

    @staticmethod
    def _replace_concepts(connection: sqlite3.Connection, episode: InteractionEpisode) -> None:
        connection.execute(
            "DELETE FROM interaction_episode_concepts WHERE episode_id = ? AND student_id = ?",
            (episode.episode_id, episode.student_id),
        )
        connection.executemany(
            """
            INSERT INTO interaction_episode_concepts (episode_id, student_id, concept_id)
            VALUES (?, ?, ?)
            """,
            ((episode.episode_id, episode.student_id, concept_id) for concept_id in dict.fromkeys(episode.concept_ids)),
        )

    @staticmethod
    def _replace_evidence(connection: sqlite3.Connection, episode: InteractionEpisode) -> None:
        connection.execute(
            "DELETE FROM interaction_episode_evidence WHERE episode_id = ? AND student_id = ?",
            (episode.episode_id, episode.student_id),
        )
        connection.executemany(
            """
            INSERT INTO interaction_episode_evidence (episode_id, learning_event_id, student_id)
            VALUES (?, ?, ?)
            """,
            (
                (episode.episode_id, event_id, episode.student_id)
                for event_id in dict.fromkeys(episode.evidence_event_ids)
            ),
        )

    @classmethod
    def _with_links(cls, connection: sqlite3.Connection, episode: InteractionEpisode) -> InteractionEpisode:
        concepts = connection.execute(
            """
            SELECT concept_id FROM interaction_episode_concepts
            WHERE episode_id = ? AND student_id = ? ORDER BY concept_id
            """,
            (episode.episode_id, episode.student_id),
        ).fetchall()
        evidence = connection.execute(
            """
            SELECT learning_event_id FROM interaction_episode_evidence
            WHERE episode_id = ? AND student_id = ? ORDER BY learning_event_id
            """,
            (episode.episode_id, episode.student_id),
        ).fetchall()
        return replace(
            episode,
            concept_ids=tuple(row["concept_id"] for row in concepts),
            evidence_event_ids=tuple(row["learning_event_id"] for row in evidence),
        )

    @staticmethod
    def _episode_values(episode: InteractionEpisode) -> tuple[object, ...]:
        return (
            episode.episode_id,
            episode.student_id,
            episode.session_id,
            episode.turn_id,
            episode.learner_question,
            json.dumps(episode.observed_signals, ensure_ascii=False),
            json.dumps(episode.inferred_difficulties, ensure_ascii=False),
            json.dumps(episode.teaching_approach, ensure_ascii=False),
            episode.outcome.value,
            episode.related_episode_id,
            episode.created_at.isoformat(),
            episode.updated_at.isoformat(),
            episode.extractor_version,
        )

    @staticmethod
    def _episode_from_row(row: sqlite3.Row) -> InteractionEpisode:
        return InteractionEpisode(
            episode_id=str(row["id"]),
            student_id=str(row["student_id"]),
            session_id=str(row["session_id"]),
            turn_id=str(row["turn_id"]),
            concept_ids=(),
            learner_question=str(row["learner_question"]),
            observed_signals=tuple(json.loads(row["observed_signals_json"])),
            inferred_difficulties=tuple(json.loads(row["inferred_difficulties_json"])),
            teaching_approach=tuple(json.loads(row["teaching_approach_json"])),
            outcome=EpisodeOutcome(str(row["outcome"])),
            related_episode_id=row["related_episode_id"],
            evidence_event_ids=(),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            extractor_version=str(row["extractor_version"]),
        )

    @staticmethod
    def _validate_episode(episode: InteractionEpisode) -> None:
        SQLiteInteractionEpisodeRepository._validate_student_id(episode.student_id)
        for value, name in (
            (episode.episode_id, "episode_id"),
            (episode.session_id, "session_id"),
            (episode.turn_id, "turn_id"),
            (episode.learner_question, "learner_question"),
            (episode.extractor_version, "extractor_version"),
        ):
            if not value.strip():
                raise ValueError(f"{name} is required")
        if not isinstance(episode.outcome, EpisodeOutcome):
            raise ValueError("outcome must be an EpisodeOutcome")

    @staticmethod
    def _validate_student_id(student_id: str) -> None:
        if not student_id or not student_id.strip():
            raise ValueError("student_id is required")


__all__ = ["SQLiteInteractionEpisodeRepository"]
