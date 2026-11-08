"""Execute the deployment shell against isolated Git/Docker/HTTP command doubles."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OLD_REVISION = "a" * 40
NEW_REVISION = "b" * 40
BACKEND_ID = "sha256:" + "1" * 64
FRONTEND_ID = "sha256:" + "2" * 64
ROLLBACK_TAG = "rollback-" + "1" * 24 + "-" + "2" * 24

COMMAND_STUB = r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

command = Path(sys.argv[0]).name
args = sys.argv[1:]
state_path = Path(os.environ["STUB_STATE"])
state = json.loads(state_path.read_text())
scenario = os.environ.get("STUB_SCENARIO", "success")
tag = os.environ.get("DEPLOY_IMAGE_TAG", "")
revision = os.environ.get("DEPLOY_GIT_REVISION", "")
with Path(os.environ["STUB_LOG"]).open("a") as log:
    log.write(json.dumps({"command": command, "args": args, "tag": tag, "revision": revision}) + "\n")

def save():
    state_path.write_text(json.dumps(state))

def stop(code=0):
    sys.exit(code)

if command == "git":
    while args and args[0] in {"-c", "-C"}:
        args = args[2:]
    if args[:2] == ["rev-parse", "HEAD"]:
        print("b" * 40 if state.get("merged") else "a" * 40)
    elif args[:2] == ["branch", "--show-current"]:
        print("main")
    elif args[0] in {"status", "ls-files"}:
        pass
    elif args == ["fetch", "origin", "main"]:
        pass
    elif args == ["merge", "--ff-only", "origin/main"]:
        state["merged"] = True
        save()
    else:
        stop(90)
    stop()

if command == "docker":
    if args[:2] == ["container", "ls"]:
        if scenario == "daemon_failed":
            stop(1)
        print("\n".join(state["containers"]))
        stop()
    if args[:2] == ["container", "inspect"]:
        image_id = state["containers"].get(args[-1])
        if not image_id:
            stop(1)
        print(image_id)
        stop()
    if args[:2] == ["image", "inspect"]:
        image = state["images"].get(args[-1])
        if not image:
            stop(1)
        print(image["revision"] if "--format" in args else "[]")
        stop()
    if args[:2] == ["image", "tag"]:
        source, target = args[-2:]
        image = next((v for v in state["images"].values() if v["id"] == source), None)
        if image is None:
            stop(91)
        state["images"][target] = image
        save()
        stop()
    if args[0] == "compose":
        action = next((value for value in args if value in {"config", "build", "up", "ps", "logs"}), None)
        if action == "config":
            if "--images" in args:
                print("ds-course-agent-backend:" + ("wrong" if scenario == "image_overlay" else tag))
                print("ds-course-agent-frontend:" + tag)
            stop()
        if action == "build":
            service = args[-1]
            if scenario == "build_failed" and service == "frontend":
                stop(1)
            state["images"]["ds-course-agent-" + service + ":" + tag] = {
                "id": "sha256:" + ("3" if service == "backend" else "4") * 64,
                "revision": revision,
            }
            save()
            stop()
        if action == "up":
            state["active_tag"] = tag
            for service in ("backend", "frontend"):
                state["containers"]["rag-" + service] = state["images"]["ds-course-agent-" + service + ":" + tag]["id"]
            save()
            if scenario == "switch_failed" and tag == "b" * 40:
                stop(1)
            stop()
        if action in {"ps", "logs"}:
            stop()
    stop(92)

if command == "curl":
    if scenario in {"unhealthy", "rollback_failed"}:
        if state.get("active_tag") == "b" * 40 or scenario == "rollback_failed":
            stop(22)
    stop()

if command == "sleep":
    stop()
stop(93)
"""


@pytest.fixture
def deployment(tmp_path: Path):
    root = tmp_path / "project"
    (root / "deploy").mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "deploy" / "update.sh", root / "deploy" / "update.sh")
    shutil.copy2(PROJECT_ROOT / "deploy" / "compose.yaml", root / "deploy" / "compose.yaml")
    (root / ".env").write_text("AUTH_SECRET_KEY=fixture-only\n", encoding="utf-8")
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    for name in ("git", "docker", "curl", "sleep"):
        executable = bin_path / name
        executable.write_text(COMMAND_STUB, encoding="utf-8")
        executable.chmod(0o755)
    state = {
        "containers": {"rag-backend": BACKEND_ID, "rag-frontend": FRONTEND_ID},
        "images": {
            "ds-course-agent-backend:live-release": {"id": BACKEND_ID, "revision": OLD_REVISION},
            "ds-course-agent-frontend:live-release": {"id": FRONTEND_ID, "revision": OLD_REVISION},
            # latest deliberately points elsewhere: using it would restore the wrong code.
            "ds-course-agent-backend:latest": {"id": "sha256:" + "5" * 64, "revision": "wrong"},
            "ds-course-agent-frontend:latest": {"id": "sha256:" + "6" * 64, "revision": "wrong"},
        },
        "active_tag": "live-release",
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    log_path = tmp_path / "commands.jsonl"
    env = {
        **os.environ,
        "PATH": f"{bin_path}:{os.environ['PATH']}",
        "STUB_STATE": str(state_path),
        "STUB_LOG": str(log_path),
        "DEPLOY_LOCK_FILE": str(tmp_path / "deployment.lock"),
        "DEPLOY_WAIT_TIMEOUT_SECONDS": "0",
        "DEPLOY_ENV_FILE": str(root / ".env"),
    }
    for key in ("DEPLOY_BACKEND_URL", "DEPLOY_BACKEND_LIVENESS_URL", "DEPLOY_FRONTEND_URL", "DEPLOY_IMAGE_TAG"):
        env.pop(key, None)
    return root, state_path, log_path, env


def execute(deployment, *args: str, scenario: str = "success"):
    root, _, log_path, env = deployment
    result = subprocess.run(
        ["bash", str(root / "deploy" / "update.sh"), *args],
        env={**env, "STUB_SCENARIO": scenario},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    events = [json.loads(line) for line in log_path.read_text().splitlines()] if log_path.exists() else []
    return result, events


def add_runtime_state(root: Path) -> tuple[Path, bytes]:
    directory = root / "var" / "deployment"
    directory.mkdir(parents=True)
    (directory / ".env").write_text("# deployment selection\nDEPLOY_IMAGE_TAG=live-release\nOTHER_SETTING=preserved\n")
    overlay = directory / "compose.runtime.json"
    content = b'{"services":{"backend":{"volumes":["/frozen-courses:/app/data:ro"]}}}\n'
    overlay.write_bytes(content)
    return overlay, content


def test_preview_does_not_fetch_build_lock_or_create_deployment_state(deployment):
    root, state_path, _, env = deployment
    before = state_path.read_bytes()
    result, events = execute(deployment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PREVIEW ONLY" in result.stdout
    assert [event["command"] for event in events] == ["git"]
    assert events[0]["args"][-2:] == ["rev-parse", "HEAD"]
    assert not (root / "var").exists()
    assert not Path(env["DEPLOY_LOCK_FILE"]).exists()
    assert state_path.read_bytes() == before


def test_success_preserves_overlay_and_persists_full_revision_atomically(deployment):
    root, _, _, _ = deployment
    overlay, content = add_runtime_state(root)
    result, events = execute(deployment, "--apply")
    assert result.returncode == 0, result.stdout + result.stderr
    saved = root / "var" / "deployment" / ".env"
    assert saved.read_text() == f"# deployment selection\nOTHER_SETTING=preserved\nDEPLOY_IMAGE_TAG={NEW_REVISION}\n"
    assert saved.stat().st_mode & 0o777 == 0o600
    assert not list(saved.parent.glob(".env.*"))
    assert overlay.read_bytes() == content
    compose_calls = [event for event in events if event["command"] == "docker" and event["args"][0] == "compose"]
    for event in compose_calls:
        assert str(overlay) in event["args"]
        assert str(saved) in event["args"]
        assert event["tag"] == NEW_REVISION
        assert event["revision"] == NEW_REVISION
    assert [event["args"][-1] for event in compose_calls if "build" in event["args"]] == ["backend", "frontend"]
    assert [event["args"][-3:] for event in events if event["command"] == "git" and "merge" in event["args"]] == [
        ["merge", "--ff-only", "origin/main"]
    ]
    tagged = [
        event["args"][-2] for event in events if event["command"] == "docker" and event["args"][:2] == ["image", "tag"]
    ]
    assert tagged == [BACKEND_ID, FRONTEND_ID]


@pytest.mark.parametrize("scenario", ["unhealthy", "switch_failed"])
def test_failure_restores_actual_container_images_and_persists_recovery_tag(deployment, scenario):
    root, state_path, _, _ = deployment
    overlay, content = add_runtime_state(root)
    result, events = execute(deployment, "--apply", scenario=scenario)
    assert result.returncode != 0
    assert "rollback completed" in result.stdout
    state = json.loads(state_path.read_text())
    assert state["containers"] == {"rag-backend": BACKEND_ID, "rag-frontend": FRONTEND_ID}
    assert state["active_tag"] == ROLLBACK_TAG
    assert f"DEPLOY_IMAGE_TAG={ROLLBACK_TAG}\n" in (root / "var" / "deployment" / ".env").read_text()
    assert overlay.read_bytes() == content
    calls = [event for event in events if event["command"] == "docker" and "up" in event["args"]]
    assert [event["tag"] for event in calls] == [NEW_REVISION, ROLLBACK_TAG]
    assert all(str(overlay) in event["args"] for event in calls)
    urls = [event["args"][-1] for event in events if event["command"] == "curl"]
    assert "http://127.0.0.1:8000/health" in urls
    assert "http://127.0.0.1:8080/" in urls


def test_build_failure_leaves_running_containers_and_saved_selection_unchanged(deployment):
    root, state_path, _, _ = deployment
    add_runtime_state(root)
    saved = root / "var" / "deployment" / ".env"
    before = saved.read_bytes()
    result, events = execute(deployment, "--apply", scenario="build_failed")
    assert result.returncode != 0
    assert saved.read_bytes() == before
    assert json.loads(state_path.read_text())["active_tag"] == "live-release"
    assert not any(event["command"] == "docker" and "up" in event["args"] for event in events)


def test_first_deployment_can_run_without_resource_overlay(deployment):
    root, state_path, _, _ = deployment
    state = json.loads(state_path.read_text())
    state["containers"] = {}
    state_path.write_text(json.dumps(state))
    result, events = execute(deployment, "--apply")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / "var" / "deployment" / ".env").read_text() == f"DEPLOY_IMAGE_TAG={NEW_REVISION}\n"
    assert not (root / "var" / "deployment" / "compose.runtime.json").exists()
    assert not any(event["command"] == "docker" and event["args"][:2] == ["image", "tag"] for event in events)


def test_failed_first_deployment_does_not_save_unhealthy_tag(deployment):
    root, state_path, _, _ = deployment
    state = json.loads(state_path.read_text())
    state["containers"] = {}
    state_path.write_text(json.dumps(state))
    result, _ = execute(deployment, "--apply", scenario="unhealthy")
    assert result.returncode != 0
    assert "automatic rollback unavailable" in result.stdout
    assert not (root / "var" / "deployment" / ".env").exists()


def test_failed_recovery_does_not_persist_a_successful_selection(deployment):
    root, _, _, _ = deployment
    add_runtime_state(root)
    saved = root / "var" / "deployment" / ".env"
    before = saved.read_bytes()
    result, _ = execute(deployment, "--apply", scenario="rollback_failed")
    assert result.returncode != 0
    assert "automatic recovery did not complete" in result.stdout
    assert saved.read_bytes() == before


@pytest.mark.parametrize("matching_revision", [True, False])
def test_existing_full_sha_images_are_never_overwritten(deployment, matching_revision):
    root, state_path, _, _ = deployment
    state = json.loads(state_path.read_text())
    for service, digit in (("backend", "3"), ("frontend", "4")):
        state["images"][f"ds-course-agent-{service}:{NEW_REVISION}"] = {
            "id": "sha256:" + digit * 64,
            "revision": NEW_REVISION if matching_revision else "wrong",
        }
    state_path.write_text(json.dumps(state))
    result, events = execute(deployment, "--apply")
    assert (result.returncode == 0) is matching_revision, result.stdout + result.stderr
    assert not any(event["command"] == "docker" and "build" in event["args"] for event in events)
    if not matching_revision:
        assert "unexpected OCI revision" in result.stdout
        assert not (root / "var" / "deployment" / ".env").exists()


@pytest.mark.parametrize("scenario", ["image_overlay", "daemon_failed"])
def test_invalid_image_overlay_or_unreadable_daemon_never_switches_containers(deployment, scenario):
    root, _, _, _ = deployment
    add_runtime_state(root)
    result, events = execute(deployment, "--apply", scenario=scenario)
    assert result.returncode != 0
    assert not any(event["command"] == "docker" and "up" in event["args"] for event in events)


def test_concurrent_apply_cannot_fetch_or_switch_while_lock_is_held(deployment):
    _, _, _, env = deployment
    with Path(env["DEPLOY_LOCK_FILE"]).open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, events = execute(deployment, "--apply")
    assert result.returncode != 0
    assert "another deployment is already running" in result.stdout
    assert not any(event["command"] == "docker" for event in events)
    assert not any(event["command"] == "git" and "fetch" in event["args"] for event in events)
