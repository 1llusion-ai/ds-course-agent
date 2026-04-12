#!/usr/bin/env python3
"""Repository-level CLI entrypoint."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def build_kb(args: list[str]) -> None:
    from scripts.build_kb import main as build_main

    sys.argv = ["build_kb", *args]
    build_main()


def run_eval() -> None:
    from eval.retrieval import compare_methods

    compare_methods(top_k=5)


def run_tests() -> None:
    subprocess.run(
        [sys.executable, "-m", "pytest", "-v"],
        cwd=PROJECT_ROOT,
        check=True,
    )


def run_api(args: list[str]) -> None:
    from scripts.run_api import main as run_api_main

    run_api_main(args)


def print_help() -> None:
    print(
        """
Data Science Course Agent CLI

Usage:
    python -m scripts.cli <command> [args]
    python main.py <command> [args]

Commands:
    build [path]    Build the course knowledge base (default: data/)
    eval            Run retrieval evaluation
    test            Run backend and core tests
    api             Start the FastAPI backend
    help            Show this help message
"""
    )


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print_help()
        return

    command, *rest = args
    command = command.lower()

    if command == "build":
        build_kb(rest or ["data/"])
        return
    if command == "eval":
        run_eval()
        return
    if command == "test":
        run_tests()
        return
    if command == "api":
        run_api(rest)
        return
    if command in {"help", "-h", "--help"}:
        print_help()
        return

    print(f"Unknown command: {command}")
    print_help()
    raise SystemExit(1)


if __name__ == "__main__":
    main()
