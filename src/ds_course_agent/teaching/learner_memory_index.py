"""Optional, rebuildable Chroma index for learner interaction episodes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ds_course_agent.teaching.interaction_episode_repository import SQLiteInteractionEpisodeRepository

LEARNER_MEMORY_COLLECTION = "learner_memory_chunks"


@dataclass(frozen=True)
class IndexConsistencyReport:
    expected_count: int
    indexed_count: int
    missing_ids: tuple[str, ...]
    orphan_ids: tuple[str, ...]
    cross_student_ids: tuple[str, ...]

    @property
    def consistent(self) -> bool:
        return not self.missing_ids and not self.orphan_ids and not self.cross_student_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_count": self.expected_count,
            "indexed_count": self.indexed_count,
            "missing_ids": list(self.missing_ids),
            "orphan_ids": list(self.orphan_ids),
            "cross_student_ids": list(self.cross_student_ids),
            "consistent": self.consistent,
        }


def episode_document(episode) -> tuple[str, str, dict[str, Any]]:
    text = (
        f"学习问题: {episode.learner_question}\n"
        f"知识点: {', '.join(episode.concept_ids)}\n"
        f"观察信号: {', '.join(episode.observed_signals) or '无'}\n"
        f"推断困难: {', '.join(episode.inferred_difficulties) or '无'}\n"
        f"教学方式: {', '.join(episode.teaching_approach) or '无'}\n"
        f"结果: {episode.outcome.value}"
    )
    metadata = {
        "student_id": episode.student_id,
        "episode_id": episode.episode_id,
        "concept_ids": ",".join(episode.concept_ids),
        "created_at": episode.created_at.isoformat(),
        "updated_at": episode.updated_at.isoformat(),
    }
    return episode.episode_id, text, metadata


class LearnerMemoryIndex:
    """Manage a separate Chroma collection without making it a fact source."""

    def __init__(self, persist_directory: str | Path, embedding: Any, collection_name: str = LEARNER_MEMORY_COLLECTION):
        import chromadb

        self.client = chromadb.PersistentClient(path=str(persist_directory))
        self.collection = self.client.get_or_create_collection(collection_name)
        self.embedding = embedding

    def check(
        self, repository: SQLiteInteractionEpisodeRepository, student_id: str | None = None
    ) -> IndexConsistencyReport:
        expected = self._episodes(repository, student_id)
        indexed = self.collection.get(include=["metadatas"])
        metadatas = indexed.get("metadatas") or []
        expected_by_id = {item.episode_id: item.student_id for item in expected}
        indexed_by_id = {str(item.get("episode_id")): str(item.get("student_id")) for item in metadatas if item}
        indexed_student_ids = set(indexed_by_id.values())
        missing = tuple(sorted(set(expected_by_id) - set(indexed_by_id)))
        orphan = tuple(
            sorted(
                episode_id
                for episode_id, indexed_student in indexed_by_id.items()
                if indexed_student == student_id and episode_id not in expected_by_id
            )
        )
        cross = tuple(
            sorted(
                episode_id
                for episode_id, indexed_student in indexed_by_id.items()
                if indexed_student != student_id
                or (episode_id in expected_by_id and indexed_student != expected_by_id[episode_id])
            )
        )
        del indexed_student_ids
        indexed_count = sum(indexed_student == student_id for indexed_student in indexed_by_id.values())
        return IndexConsistencyReport(len(expected), indexed_count, missing, orphan, cross)

    def rebuild(self, repository: SQLiteInteractionEpisodeRepository, student_id: str | None = None) -> int:
        episodes = self._episodes(repository, student_id)
        existing = self.collection.get(include=["metadatas"])
        existing_ids = [
            item_id
            for item_id, metadata in zip(existing.get("ids") or (), existing.get("metadatas") or (), strict=True)
            if metadata and metadata.get("student_id") == student_id
        ]
        if existing_ids:
            self.collection.delete(ids=existing_ids)
        if not episodes:
            return 0
        ids, documents, metadatas = zip(*(episode_document(item) for item in episodes), strict=True)
        embeddings = self.embedding.embed_documents(list(documents))
        self.collection.add(ids=list(ids), documents=list(documents), metadatas=list(metadatas), embeddings=embeddings)
        return len(episodes)

    @staticmethod
    def _episodes(repository, student_id):
        if student_id is not None:
            return repository.list_for_student(student_id, limit=100)
        raise ValueError("student_id is required for learner-memory index operations")


__all__ = ["IndexConsistencyReport", "LEARNER_MEMORY_COLLECTION", "LearnerMemoryIndex", "episode_document"]
