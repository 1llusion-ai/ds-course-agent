#!/usr/bin/env python3
"""Backward-compatible wrapper for the repository CLI."""

from scripts._path import ensure_src_path

ensure_src_path()

from scripts.cli import main


if __name__ == "__main__":
    main()
