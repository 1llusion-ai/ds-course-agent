"""Generic SQLite connection and versioned migration infrastructure."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def connect_sqlite(path: str | Path) -> sqlite3.Connection:
    """Open a configured SQLite connection for application repositories."""

    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(resolved)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


@dataclass(frozen=True)
class Migration:
    """One immutable, ordered database schema migration."""

    version: int
    name: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        payload = "\n-- statement --\n".join(statement.strip() for statement in self.statements)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MigrationPlan:
    """Read-only description of applied and pending migrations."""

    applied_versions: tuple[int, ...]
    pending: tuple[Migration, ...]


class SQLiteMigrationRunner:
    """Apply immutable migrations to one SQLite database."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def plan(self, migrations: tuple[Migration, ...]) -> MigrationPlan:
        """Return pending migrations without creating or modifying the database."""

        ordered = self._validate_migrations(migrations)
        applied = self._load_applied()
        for migration in ordered:
            existing = applied.get(migration.version)
            if existing is None:
                continue
            name, checksum = existing
            if name != migration.name or checksum != migration.checksum:
                raise ValueError(f"applied migration {migration.version} no longer matches its definition")
        return MigrationPlan(
            applied_versions=tuple(sorted(applied)),
            pending=tuple(migration for migration in ordered if migration.version not in applied),
        )

    def apply(self, migrations: tuple[Migration, ...]) -> tuple[Migration, ...]:
        """Apply all pending migrations transactionally and return those applied."""

        plan = self.plan(migrations)
        if not plan.pending:
            return ()

        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = connect_sqlite(self.path)
        applied: list[Migration] = []
        try:
            self._ensure_migration_table(connection)
            for migration in plan.pending:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    for statement in migration.statements:
                        connection.execute(statement)
                    connection.execute(
                        """
                        INSERT INTO schema_migrations (version, name, checksum, applied_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            migration.version,
                            migration.name,
                            migration.checksum,
                            datetime.now(timezone.utc).isoformat(),
                        ),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                applied.append(migration)
        finally:
            connection.close()
        return tuple(applied)

    def _load_applied(self) -> dict[int, tuple[str, str]]:
        if not self.path.exists():
            return {}
        connection = connect_sqlite(self.path)
        try:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
            ).fetchone()
            if not exists:
                return {}
            rows = connection.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
            return {int(row["version"]): (str(row["name"]), str(row["checksum"])) for row in rows}
        finally:
            connection.close()

    @staticmethod
    def _ensure_migration_table(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.commit()

    @staticmethod
    def _validate_migrations(migrations: tuple[Migration, ...]) -> tuple[Migration, ...]:
        ordered = tuple(sorted(migrations, key=lambda item: item.version))
        versions = [migration.version for migration in ordered]
        if any(version <= 0 for version in versions):
            raise ValueError("migration versions must be positive integers")
        if len(versions) != len(set(versions)):
            raise ValueError("migration versions must be unique")
        if any(not migration.name.strip() for migration in ordered):
            raise ValueError("migration names must not be blank")
        if any(not migration.statements for migration in ordered):
            raise ValueError("migrations must contain at least one statement")
        return ordered


__all__ = ["Migration", "MigrationPlan", "SQLiteMigrationRunner", "connect_sqlite"]
