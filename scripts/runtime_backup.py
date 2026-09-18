"""Create, verify, restore, and retain non-destructive runtime backups.

The default snapshot covers the persisted student state and external-research
artifacts that are not cheaply reproducible.  Backup archives contain a
manifest with SHA-256 hashes and never include credentials from ``.env``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP_DIR = Path("var/backups")
DEFAULT_RELATIVE_PATHS = (
    Path("var/app.db"),
    Path("var/auth.db"),
    Path("var/assessment.db"),
    Path("var/chat_history"),
    Path("var/artifacts/tool_results"),
)
ARCHIVE_GLOB = "backup-*.tar.gz"
MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA = "runtime-backup-v1"


class BackupError(RuntimeError):
    """Raised when a backup operation would be unsafe or cannot be verified."""


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    kind: str
    size: int
    sha256: str


def _resolve_root(root: Path) -> Path:
    return root.expanduser().resolve()


def _resolve_relative(root: Path, relative_path: Path) -> Path:
    if relative_path.is_absolute():
        raise BackupError(f"Backup paths must be relative: {relative_path}")
    unresolved = root / relative_path
    if unresolved.is_symlink():
        raise BackupError(f"Refusing to archive symlink: {unresolved}")
    candidate = unresolved.resolve()
    if not candidate.is_relative_to(root) or candidate == root:
        raise BackupError(f"Path escapes backup root: {relative_path}")
    return candidate


def _relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_label(label: str | None) -> str:
    value = "".join(character if character.isalnum() or character in "-_" else "-" for character in label or "")
    return value.strip("-")[:48]


def _copy_sqlite_database(source: Path, destination: Path) -> None:
    """Take a consistent SQLite snapshot without copying a live WAL file."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()


def _copy_source(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise BackupError(f"Refusing to archive symlink: {source}")
    if source.is_file():
        if source.suffix == ".db":
            _copy_sqlite_database(source, destination)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        return
    if source.is_dir():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, symlinks=False)
        return
    raise BackupError(f"Unsupported runtime path: {source}")


def _manifest_entries(payload_root: Path) -> list[ManifestEntry]:
    entries: list[ManifestEntry] = []
    for path in sorted(payload_root.rglob("*")):
        if path.is_symlink():
            raise BackupError(f"Archive staging contains symlink: {path}")
        relative = _relative_path(path, payload_root)
        if path.is_dir():
            entries.append(ManifestEntry(relative, "directory", 0, ""))
        elif path.is_file():
            entries.append(ManifestEntry(relative, "file", path.stat().st_size, _hash_file(path)))
        else:
            raise BackupError(f"Unsupported staged path: {path}")
    return entries


def _validate_source_paths(root: Path, relative_paths: tuple[Path, ...]) -> None:
    resolved = [_resolve_relative(root, path) for path in relative_paths]
    for index, current in enumerate(resolved):
        for other in resolved[index + 1 :]:
            if current == other or current.is_relative_to(other) or other.is_relative_to(current):
                raise BackupError(f"Overlapping backup paths are not allowed: {current} and {other}")


def _tar_filter(member: tarfile.TarInfo) -> tarfile.TarInfo:
    member.uid = 0
    member.gid = 0
    member.uname = ""
    member.gname = ""
    return member


def create_backup(
    root: Path,
    destination: Path,
    *,
    relative_paths: tuple[Path, ...] = DEFAULT_RELATIVE_PATHS,
    label: str | None = None,
    strict: bool = False,
) -> tuple[Path, dict[str, object]]:
    """Snapshot selected runtime state into a compressed, hashed archive."""

    root = _resolve_root(root)
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    _validate_source_paths(root, relative_paths)
    for relative_path in relative_paths:
        source = _resolve_relative(root, relative_path)
        if source.exists() and (destination == source or destination.is_relative_to(source)):
            raise BackupError(f"Backup destination overlaps source: {destination}")

    timestamp = datetime.now(timezone.utc)
    label_suffix = f"-{_safe_label(label)}" if _safe_label(label) else ""
    archive = destination / f"backup-{timestamp:%Y%m%dT%H%M%SZ}{label_suffix}-{uuid4().hex[:8]}.tar.gz"
    missing_sources: list[str] = []

    with tempfile.TemporaryDirectory(prefix=".runtime-backup-", dir=destination.parent) as temporary:
        stage_root = Path(temporary)
        payload_root = stage_root / "payload"
        payload_root.mkdir(parents=True, exist_ok=True)
        for relative_path in relative_paths:
            source = _resolve_relative(root, relative_path)
            if not source.exists():
                missing_sources.append(relative_path.as_posix())
                continue
            _copy_source(source, payload_root / relative_path)

        if strict and missing_sources:
            raise BackupError(f"Required runtime paths are missing: {', '.join(missing_sources)}")

        entries = _manifest_entries(payload_root) if payload_root.exists() else []
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "created_at": timestamp.isoformat(),
            "source_paths": [path.as_posix() for path in relative_paths],
            "missing_sources": missing_sources,
            "entries": [asdict(entry) for entry in entries],
        }
        (stage_root / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        with tarfile.open(archive, "w:gz") as handle:
            handle.add(stage_root / MANIFEST_NAME, arcname=MANIFEST_NAME, recursive=False, filter=_tar_filter)
            if payload_root.exists():
                handle.add(payload_root, arcname="payload", recursive=True, filter=_tar_filter)

    return archive, manifest


def _safe_members(handle: tarfile.TarFile, destination: Path) -> list[tarfile.TarInfo]:
    destination = destination.resolve()
    members = handle.getmembers()
    seen_names: set[str] = set()
    for member in members:
        if member.name in seen_names:
            raise BackupError(f"Duplicate archive member: {member.name}")
        seen_names.add(member.name)
        member_path = Path(member.name)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise BackupError(f"Unsafe archive member: {member.name}")
        if member.name != MANIFEST_NAME and member.name != "payload" and not member.name.startswith("payload/"):
            raise BackupError(f"Unexpected archive member: {member.name}")
        if member.issym() or member.islnk():
            raise BackupError(f"Archive links are not allowed: {member.name}")
        resolved = (destination / member_path).resolve()
        if not resolved.is_relative_to(destination):
            raise BackupError(f"Archive member escapes restore target: {member.name}")
    return members


def _extract_archive(archive: Path, destination: Path) -> dict[str, object]:
    if not archive.is_file():
        raise BackupError(f"Backup archive does not exist: {archive}")
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as handle:
        members = _safe_members(handle, destination)
        if MANIFEST_NAME not in {member.name for member in members}:
            raise BackupError("Backup archive has no manifest.json")
        handle.extractall(destination, members=members)
    manifest_path = destination / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError("Backup manifest is unreadable") from exc
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise BackupError(f"Unsupported backup manifest schema: {manifest.get('schema')!r}")
    return manifest


def _verify_extracted(manifest: dict[str, object], extracted_root: Path) -> dict[str, object]:
    payload_root = extracted_root / "payload"
    raw_entries = manifest.get("entries", [])
    if not isinstance(raw_entries, list):
        raise BackupError("Backup manifest entries must be a list")
    try:
        expected_entries = [ManifestEntry(**entry) for entry in raw_entries]
    except (TypeError, ValueError) as exc:
        raise BackupError("Backup manifest entries are malformed") from exc
    actual_entries = {entry.path: entry for entry in _manifest_entries(payload_root)} if payload_root.exists() else {}
    expected_paths = {entry.path for entry in expected_entries}
    if actual_entries.keys() != expected_paths:
        missing = sorted(expected_paths - actual_entries.keys())
        unexpected = sorted(actual_entries.keys() - expected_paths)
        raise BackupError(f"Backup file inventory mismatch: missing={missing}, unexpected={unexpected}")

    for expected in expected_entries:
        actual = actual_entries[expected.path]
        if actual.kind != expected.kind or actual.size != expected.size or actual.sha256 != expected.sha256:
            raise BackupError(f"Backup hash mismatch: {expected.path}")

    return {
        "schema": manifest["schema"],
        "created_at": manifest["created_at"],
        "verified_entries": len(expected_entries),
        "missing_sources": list(manifest.get("missing_sources", [])),
    }


def verify_backup(archive: Path) -> dict[str, object]:
    """Extract into a temporary directory and verify every manifest entry."""

    archive = archive.expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix=".runtime-backup-verify-") as temporary:
        extracted = Path(temporary)
        manifest = _extract_archive(archive, extracted)
        result = _verify_extracted(manifest, extracted)
    return {"archive": str(archive), "verified": True, **result}


def restore_backup(archive: Path, target: Path) -> dict[str, object]:
    """Verify an archive, then restore its payload below a new target directory."""

    archive = archive.expanduser().resolve()
    target = target.expanduser().resolve()
    if target.exists():
        raise BackupError(f"Restore target must not already exist: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".runtime-backup-restore-", dir=target.parent) as temporary:
        extracted = Path(temporary)
        manifest = _extract_archive(archive, extracted)
        verification = _verify_extracted(manifest, extracted)
        payload_root = extracted / "payload"
        if not payload_root.exists():
            raise BackupError("Backup contains no payload")
        shutil.move(str(payload_root), str(target))

    return {"archive": str(archive), "target": str(target), "restored": True, **verification}


def _backup_archives(destination: Path) -> list[Path]:
    return sorted(
        (path for path in destination.glob(ARCHIVE_GLOB) if path.is_file()), key=lambda path: path.stat().st_mtime
    )


def retention_candidates(destination: Path, *, keep_days: int, now: datetime | None = None) -> list[Path]:
    """Return old archives, preserving the newest archive even when it is old."""

    if keep_days < 1:
        raise BackupError("keep_days must be at least 1")
    archives = _backup_archives(destination.expanduser().resolve())
    if len(archives) <= 1:
        return []
    now = now or datetime.now(timezone.utc)
    cutoff = now.timestamp() - timedelta(days=keep_days).total_seconds()
    newest = archives[-1]
    return [archive for archive in archives[:-1] if archive.stat().st_mtime < cutoff and archive != newest]


def prune_backups(destination: Path, *, keep_days: int, confirmation: str) -> list[Path]:
    if confirmation != "DELETE":
        raise BackupError("Pruning requires --confirm-prune DELETE")
    candidates = retention_candidates(destination, keep_days=keep_days)
    for archive in candidates:
        archive.unlink()
    return candidates


def _path_from_root(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT, help="Project/runtime root")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup", help="Create a runtime archive")
    backup_parser.add_argument("--destination", type=Path, default=DEFAULT_BACKUP_DIR)
    backup_parser.add_argument("--label", default=None)
    backup_parser.add_argument("--strict", action="store_true", help="Fail when any default source is missing")

    verify_parser = subparsers.add_parser("verify", help="Verify archive hashes without changing runtime state")
    verify_parser.add_argument("archive", type=Path)

    restore_parser = subparsers.add_parser("restore", help="Restore into a new, empty target root")
    restore_parser.add_argument("archive", type=Path)
    restore_parser.add_argument("--target", required=True, type=Path)

    retention_parser = subparsers.add_parser("retention", help="Preview or explicitly prune old archives")
    retention_parser.add_argument("--destination", type=Path, default=DEFAULT_BACKUP_DIR)
    retention_parser.add_argument("--keep-days", type=int, default=30)
    retention_parser.add_argument("--prune", action="store_true")
    retention_parser.add_argument("--confirm-prune", default=None)

    args = parser.parse_args(argv)
    root = _resolve_root(args.root)
    try:
        if args.command == "backup":
            archive, manifest = create_backup(
                root,
                _path_from_root(root, str(args.destination)),
                label=args.label,
                strict=args.strict,
            )
            print(json.dumps({"archive": str(archive), "manifest": manifest}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "verify":
            print(json.dumps(verify_backup(_path_from_root(root, str(args.archive))), ensure_ascii=False, indent=2))
            return 0
        if args.command == "restore":
            print(
                json.dumps(
                    restore_backup(_path_from_root(root, str(args.archive)), args.target),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        destination = _path_from_root(root, str(args.destination))
        if args.prune:
            removed = prune_backups(destination, keep_days=args.keep_days, confirmation=args.confirm_prune)
            print(json.dumps({"pruned": [str(path) for path in removed]}, ensure_ascii=False, indent=2))
        else:
            candidates = retention_candidates(destination, keep_days=args.keep_days)
            print(
                json.dumps(
                    {"dry_run": True, "candidates": [str(path) for path in candidates]}, ensure_ascii=False, indent=2
                )
            )
        return 0
    except (BackupError, OSError, sqlite3.Error) as exc:
        print(f"runtime backup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
