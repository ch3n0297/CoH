from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPOSITORY_ROOT / "plugins" / "coh"
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "ready-repository"
ROUTER = PLUGIN_ROOT / "hooks" / "user_prompt_router.py"
COLLECTOR = PLUGIN_ROOT / "hooks" / "stop_receipt_collector.py"
MODEL_VALIDATOR = PLUGIN_ROOT / "scripts" / "validate_harness_model.py"

sys.dont_write_bytecode = True
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def initialize_git(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.email", "coh-fixture@example.invalid")
    git(root, "config", "user.name", "CoH Fixture")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "fixture")


def copy_fixture(
    destination: Path,
    *,
    include_model: bool = True,
    include_guide: bool = True,
) -> Path:
    shutil.copytree(FIXTURE_ROOT, destination)
    if not include_model:
        (destination / ".coh" / "model.json").unlink()
    if not include_guide:
        (destination / "docs" / "AUTH_GUIDE.md").unlink()
    (destination / "scripts" / "validate.sh").chmod(0o755)
    initialize_git(destination)
    return destination.resolve()


def repository_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.parts
    }


def run_hook(
    script: Path,
    event: dict[str, object],
    data_root: Path,
) -> dict[str, object]:
    env = os.environ.copy()
    for key in ("PLUGIN_ROOT", "PLUGIN_DATA", "CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA"):
        env.pop(key, None)
    env["PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    env["PLUGIN_DATA"] = str(data_root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0 or completed.stderr:
        raise AssertionError(
            f"hook failed rc={completed.returncode}: {completed.stderr}"
        )
    return json.loads(completed.stdout)


def additional_context(output: dict[str, object]) -> str:
    hook_output = output.get("hookSpecificOutput")
    if not isinstance(hook_output, dict):
        return ""
    value = hook_output.get("additionalContext")
    return value if isinstance(value, str) else ""


def context_payload(output: dict[str, object]) -> dict[str, object]:
    context = additional_context(output)
    lines = context.splitlines()
    if len(lines) < 2:
        raise AssertionError(f"missing CoH context payload: {context}")
    return json.loads(lines[1])
