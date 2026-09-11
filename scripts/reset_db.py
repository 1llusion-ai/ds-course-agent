"""Preview a knowledge-base reset; explicitly confirmed resets archive data."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def archive_database(directory: Path, md5_path: Path, runtime_root: Path) -> Path:
    """Move validated runtime data to a recoverable archive, never recursively delete it."""

    root = runtime_root.resolve()
    directory, md5_path = directory.resolve(), md5_path.resolve()
    archive_root = root / "artifacts" / "kb_backups"
    if not directory.is_relative_to(root) or directory == root:
        raise ValueError(f"Refusing a reset outside a dedicated runtime path: {directory}")
    if archive_root.is_relative_to(directory) or directory.is_relative_to(archive_root):
        raise ValueError(f"Reset target overlaps backup storage: {directory}")
    if not directory.is_dir():
        raise ValueError(f"Knowledge-base directory does not exist: {directory}")
    if md5_path.exists():
        if not md5_path.is_relative_to(root) or md5_path == root:
            raise ValueError(f"Refusing a reset outside a dedicated runtime path: {md5_path}")
        if archive_root.is_relative_to(md5_path) or md5_path.is_relative_to(archive_root):
            raise ValueError(f"Reset target overlaps backup storage: {md5_path}")
        if not md5_path.is_file():
            raise ValueError(f"Hash-record target is not a file: {md5_path}")
    archive = archive_root / f"{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"
    archive.mkdir(parents=True, exist_ok=False)
    shutil.move(str(directory), str(archive / "database"))
    if md5_path.exists():
        shutil.move(str(md5_path), str(archive / "hash-record"))
    directory.mkdir(parents=True, exist_ok=False)
    return archive


def main(argv: list[str] | None = None) -> int:
    """Require an explicit collection-name confirmation before archiving a database."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-reset", metavar="COLLECTION", help="Confirm the exact configured collection name")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    import ds_course_agent.shared.config as config

    directory, md5_path = Path(config.persist_directory), Path(config.md5_path)
    print(f"Database: {directory.resolve()}\nHash record: {md5_path.resolve()}\nCollection: {config.collection_name}")
    if args.confirm_reset is None:
        print("Preview only. Stop the backend before a reset; confirmation archives the whole database directory.")
        return 0
    if args.confirm_reset != config.collection_name:
        parser.error("Confirmation does not match the configured collection")
    archive = archive_database(directory, md5_path, root / "var")
    print(f"Database archived, recoverable at: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
