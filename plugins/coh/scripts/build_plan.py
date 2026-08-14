#!/usr/bin/env python3
"""Validate canonical CoH BuildPlan v1 context without repository writes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))

from coh_hook_common import (  # noqa: E402
    COMMIT,
    DIGEST,
    IDENTIFIER,
    MODEL_RELATIVE_PATH,
    PROOF_LAYERS,
    ContractError,
    _exact_keys,
    git_head,
    load_json_object,
    repository_id,
)


BUILD_PLAN_VERSION = 1
MAX_PLAN_BYTES = 64 * 1024
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_OBSERVED_INPUTS = 4096
MAX_OPERATIONS = 64
TASK_ID_ENVIRONMENT = "CODEX_THREAD_ID"
PERMISSIONS = {"file", "executable"}
ROLES = {"authority", "guide", "sensor"}
MODES = {"adopt", "create"}


class BuildPlanError(ValueError):
    """One bounded Build Plan failure code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(payload: object) -> bytes:
    try:
        return (
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BuildPlanError("PLAN_INVALID") from exc


def semantic_sha256(payload: dict[str, Any]) -> str:
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BuildPlanError("PLAN_MODEL_INVALID") from exc
    return _sha256(encoded)


def _relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 240:
        raise BuildPlanError("PLAN_INVALID")
    if "\\" in value or any(ord(character) < 32 for character in value):
        raise BuildPlanError("PLAN_INVALID")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or not pure.parts
        or pure.parts[0] == ".git"
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise BuildPlanError("PLAN_INVALID")
    return pure.as_posix()


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise BuildPlanError("PLAN_INVALID")
    return value


def _digest(value: Any) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise BuildPlanError("PLAN_INVALID")
    return value


def _validate_plan(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        _exact_keys(
            payload,
            {
                "plan_version",
                "task_id_sha256",
                "repository_id",
                "base_head_sha",
                "observed_inputs",
                "model",
                "operations",
                "proof_boundaries",
            },
            set(),
            "BUILD_PLAN_FIELDS",
        )
    except ContractError as exc:
        raise BuildPlanError("PLAN_INVALID") from exc
    if type(payload["plan_version"]) is not int or payload["plan_version"] != BUILD_PLAN_VERSION:
        raise BuildPlanError("PLAN_VERSION_UNSUPPORTED")
    _digest(payload["task_id_sha256"])
    _digest(payload["repository_id"])
    if not isinstance(payload["base_head_sha"], str) or not COMMIT.fullmatch(payload["base_head_sha"]):
        raise BuildPlanError("PLAN_INVALID")

    observed = payload["observed_inputs"]
    if not isinstance(observed, list) or not 1 <= len(observed) <= MAX_OBSERVED_INPUTS:
        raise BuildPlanError("PLAN_INVALID")
    observed_paths: set[str] = set()
    for item in observed:
        if not isinstance(item, dict):
            raise BuildPlanError("PLAN_INVALID")
        state = item.get("state")
        required = {"path", "state", "sha256"} if state == "PRESENT" else {"path", "state"}
        if set(item) != required or state not in {"PRESENT", "ABSENT"}:
            raise BuildPlanError("PLAN_INVALID")
        path = _relative_path(item["path"])
        if path in observed_paths:
            raise BuildPlanError("PLAN_INVALID")
        observed_paths.add(path)
        if state == "PRESENT":
            _digest(item["sha256"])

    model = payload["model"]
    if not isinstance(model, dict):
        raise BuildPlanError("PLAN_INVALID")
    try:
        _exact_keys(
            model,
            {"source", "raw_sha256", "semantic_sha256"},
            set(),
            "BUILD_PLAN_MODEL_FIELDS",
        )
    except ContractError as exc:
        raise BuildPlanError("PLAN_INVALID") from exc
    _relative_path(model["source"])
    _digest(model["raw_sha256"])
    _digest(model["semantic_sha256"])

    operations = payload["operations"]
    if not isinstance(operations, list) or len(operations) > MAX_OPERATIONS:
        raise BuildPlanError("PLAN_INVALID")
    operation_ids: set[str] = set()
    operation_paths: set[str] = set()
    for operation in operations:
        if not isinstance(operation, dict):
            raise BuildPlanError("PLAN_INVALID")
        mode = operation.get("mode")
        if mode == "adopt":
            required = {"id", "role", "mode", "path", "expected_sha256"}
        elif mode == "create":
            required = {
                "id",
                "role",
                "mode",
                "path",
                "source",
                "expected_sha256",
                "permissions",
            }
        else:
            raise BuildPlanError("PLAN_INVALID")
        if set(operation) != required:
            raise BuildPlanError("PLAN_INVALID")
        operation_id = _identifier(operation["id"])
        path = _relative_path(operation["path"])
        if operation_id in operation_ids or path in operation_paths:
            raise BuildPlanError("PLAN_INVALID")
        operation_ids.add(operation_id)
        operation_paths.add(path)
        if operation["role"] not in ROLES or mode not in MODES:
            raise BuildPlanError("PLAN_INVALID")
        _digest(operation["expected_sha256"])
        if mode == "create":
            _relative_path(operation["source"])
            if operation["permissions"] not in PERMISSIONS:
                raise BuildPlanError("PLAN_INVALID")

    boundaries = payload["proof_boundaries"]
    if (
        not isinstance(boundaries, list)
        or not 1 <= len(boundaries) <= len(PROOF_LAYERS)
        or len(set(boundaries)) != len(boundaries)
        or any(item not in PROOF_LAYERS for item in boundaries)
    ):
        raise BuildPlanError("PLAN_INVALID")
    return payload


def load_build_plan(path: Path) -> tuple[dict[str, Any], str]:
    if path.is_symlink():
        raise BuildPlanError("PLAN_INVALID")
    try:
        payload, _ = load_json_object(path, MAX_PLAN_BYTES)
        raw = path.read_bytes()
    except (ContractError, OSError) as exc:
        raise BuildPlanError("PLAN_INVALID") from exc
    payload = _validate_plan(payload)
    canonical = canonical_json(payload)
    if raw != canonical:
        raise BuildPlanError("PLAN_NOT_CANONICAL")
    return payload, _sha256(canonical)


def current_task_id_sha256() -> str:
    task_id = os.environ.get(TASK_ID_ENVIRONMENT)
    if not isinstance(task_id, str) or not task_id or len(task_id) > 1024:
        raise BuildPlanError("TASK_ID_UNAVAILABLE")
    return _sha256(task_id.encode("utf-8"))


def context_for_repository(root: Path) -> dict[str, str]:
    try:
        root = root.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BuildPlanError("REPOSITORY_UNAVAILABLE") from exc
    if not root.is_dir():
        raise BuildPlanError("REPOSITORY_UNAVAILABLE")
    head = git_head(root)
    if head is None:
        raise BuildPlanError("HEAD_UNAVAILABLE")
    return {
        "task_id_sha256": current_task_id_sha256(),
        "repository_id": repository_id(root),
        "base_head_sha": head,
    }


def _live_input(root: Path, relative: str) -> dict[str, str]:
    current = root
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        current = current / part
        if not os.path.lexists(current):
            return {"path": relative, "state": "ABSENT"}
        if current.is_symlink():
            raise BuildPlanError("PLAN_INPUT_CHANGED")
        if index < len(parts) - 1 and not current.is_dir():
            raise BuildPlanError("PLAN_INPUT_CHANGED")
    try:
        metadata = current.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_INPUT_BYTES:
            raise BuildPlanError("PLAN_INPUT_CHANGED")
        data = current.read_bytes()
    except OSError as exc:
        raise BuildPlanError("PLAN_INPUT_CHANGED") from exc
    if len(data) > MAX_INPUT_BYTES:
        raise BuildPlanError("PLAN_INPUT_CHANGED")
    return {"path": relative, "state": "PRESENT", "sha256": _sha256(data)}


def verify_plan_context(
    root: Path,
    plan: dict[str, Any],
    model_payload: dict[str, Any],
) -> None:
    context = context_for_repository(root)
    if plan["task_id_sha256"] != context["task_id_sha256"]:
        raise BuildPlanError("PLAN_TASK_MISMATCH")
    if plan["repository_id"] != context["repository_id"]:
        raise BuildPlanError("PLAN_REPOSITORY_MISMATCH")
    if plan["base_head_sha"] != context["base_head_sha"]:
        raise BuildPlanError("PLAN_HEAD_STALE")

    authority_paths = {
        item.get("ref", {}).get("path")
        for item in model_payload.get("authorities", [])
        if isinstance(item, dict) and isinstance(item.get("ref"), dict)
    }
    if any(not isinstance(path, str) for path in authority_paths):
        raise BuildPlanError("PLAN_INPUT_CLOSURE")
    expected_paths = {
        MODEL_RELATIVE_PATH,
        *(_relative_path(path) for path in authority_paths),
        *(_relative_path(item["path"]) for item in plan["operations"]),
    }
    observed_by_path = {item["path"]: item for item in plan["observed_inputs"]}
    if set(observed_by_path) != expected_paths:
        raise BuildPlanError("PLAN_INPUT_CLOSURE")
    for path in sorted(expected_paths):
        if observed_by_path[path] != _live_input(root, path):
            raise BuildPlanError("PLAN_INPUT_CHANGED")


def _inspect(root: Path, plan_path: Path) -> dict[str, Any]:
    plan, plan_sha256 = load_build_plan(plan_path)
    plan_directory = plan_path.resolve(strict=True).parent
    source = (plan_directory / plan["model"]["source"]).resolve(strict=True)
    try:
        source.relative_to(plan_directory)
        model_payload, raw_sha256 = load_json_object(source, MAX_PLAN_BYTES)
    except (ValueError, OSError, ContractError) as exc:
        raise BuildPlanError("PLAN_MODEL_INVALID") from exc
    if raw_sha256 != plan["model"]["raw_sha256"]:
        raise BuildPlanError("PLAN_MODEL_CHANGED")
    if semantic_sha256(model_payload) != plan["model"]["semantic_sha256"]:
        raise BuildPlanError("PLAN_MODEL_CHANGED")
    for operation in plan["operations"]:
        if operation["mode"] != "create":
            continue
        candidate = plan_directory / operation["source"]
        if candidate.is_symlink():
            raise BuildPlanError("PLAN_SOURCE_CHANGED")
        try:
            source = candidate.resolve(strict=True)
            source.relative_to(plan_directory)
            if not source.is_file() or source.stat().st_size > MAX_INPUT_BYTES:
                raise BuildPlanError("PLAN_SOURCE_CHANGED")
            data = source.read_bytes()
        except (OSError, ValueError) as exc:
            raise BuildPlanError("PLAN_SOURCE_CHANGED") from exc
        if len(data) > MAX_INPUT_BYTES or _sha256(data) != operation["expected_sha256"]:
            raise BuildPlanError("PLAN_SOURCE_CHANGED")
    verify_plan_context(root, plan, model_payload)
    return {"plan_version": BUILD_PLAN_VERSION, "plan_sha256": plan_sha256, **context_for_repository(root)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    context = subparsers.add_parser("context")
    context.add_argument("--repository", type=Path, required=True)
    context.add_argument("--json", action="store_true")
    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--repository", type=Path, required=True)
    inspect.add_argument("--plan", type=Path, required=True)
    inspect.add_argument("--accepted-plan-sha256", required=True)
    inspect.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "context":
            result = context_for_repository(args.repository)
        else:
            result = _inspect(args.repository, args.plan)
            if args.accepted_plan_sha256 != result["plan_sha256"]:
                raise BuildPlanError("PLAN_ACCEPTANCE_MISMATCH")
        output = {"ok": True, **result}
    except BuildPlanError as exc:
        output = {"ok": False, "code": exc.code}
    if getattr(args, "json", False):
        print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    elif output["ok"]:
        print("PASS: canonical Build Plan context is current")
    else:
        print(f"FAIL: {output['code']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
