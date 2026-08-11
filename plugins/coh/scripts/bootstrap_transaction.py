#!/usr/bin/env python3
"""Create-only, recoverable coordinator for publishing one Harness Model last."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))

from harness_model import MAX_MODEL_BYTES, validate_model
from coh_hook_common import (
    DIGEST,
    IDENTIFIER,
    MODEL_RELATIVE_PATH,
    PROOF_LAYERS,
    REGISTRY_RELATIVE_PATH,
    ContractError,
    _exact_keys,
    load_json_object,
)

PLAN_SCHEMA_VERSION = 1
JOURNAL_SCHEMA_VERSION = 1
MAX_PLAN_BYTES = 64 * 1024
MAX_JOURNAL_BYTES = 256 * 1024
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_TOTAL_STAGED_BYTES = 16 * 1024 * 1024
MAX_VERIFICATION_BYTES = 64 * 1024
MAX_ARTIFACTS = 64

HARNESS_DIRECTORY = ".coh"
BOOTSTRAP_DIRECTORY = ".bootstrap"
ACTIVE_FILE = "active"
TRANSACTION_ID = re.compile(r"^[0-9a-f]{32}$")
TOMBSTONE = re.compile(r"^\.tombstone-[0-9a-f]{32}-[0-9a-f]{16}$")
BLOCKER_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

ARTIFACT_ROLES = {"authority", "guide", "sensor"}
ARTIFACT_MODES = {"adopt", "create"}
PERMISSIONS = {"file": 0o644, "executable": 0o755}
JOURNAL_STATES = {
    "PREPARED",
    "APPLYING",
    "ARTIFACTS_READY",
    "LEGACY_RETIRING",
    "LEGACY_RETIRED",
    "MODEL_PUBLISHING",
    "MODEL_PUBLISHED",
    "RECOVERY_REQUIRED",
}
ARTIFACT_STATES = {"PENDING", "ADOPTED", "CREATED", "UNCHANGED"}
UNAVAILABLE_REASONS = {
    "ENVIRONMENT_UNAVAILABLE",
    "EXTERNAL_SIDE_EFFECT_NOT_AUTHORIZED",
    "CREDENTIAL_UNAVAILABLE",
}


class BootstrapError(ValueError):
    """One bounded coordinator failure code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(payload: object) -> bytes:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BootstrapError("INPUT_INVALID") from exc


def _semantic_sha256(payload: dict[str, Any]) -> str:
    return _sha256(_canonical_json(payload))


def _relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 240:
        raise BootstrapError("INPUT_INVALID")
    if "\\" in value or any(ord(character) < 32 for character in value):
        raise BootstrapError("INPUT_INVALID")
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise BootstrapError("INPUT_INVALID")
    return pure.as_posix()


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise BootstrapError("INPUT_INVALID")
    return value


def _digest(value: Any) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise BootstrapError("INPUT_INVALID")
    return value


def _root(value: str | Path) -> Path:
    try:
        resolved = Path(value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BootstrapError("INPUT_INVALID") from exc
    if not resolved.is_dir():
        raise BootstrapError("INPUT_INVALID")
    return resolved


def _contained_path(
    base: Path,
    relative: str,
    *,
    must_exist: bool,
    must_be_file: bool,
) -> Path:
    pure = PurePosixPath(relative)
    current = base
    for index, part in enumerate(pure.parts):
        current = current / part
        is_leaf = index == len(pure.parts) - 1
        if os.path.lexists(current):
            if current.is_symlink():
                raise BootstrapError("INPUT_INVALID")
            if not is_leaf and not current.is_dir():
                raise BootstrapError("INPUT_INVALID")
        elif not is_leaf or must_exist:
            raise BootstrapError("INPUT_INVALID")
    try:
        resolved_parent = current.parent.resolve(strict=True)
        resolved_parent.relative_to(base)
    except (OSError, RuntimeError, ValueError) as exc:
        raise BootstrapError("INPUT_INVALID") from exc
    if must_exist and not current.exists():
        raise BootstrapError("INPUT_INVALID")
    if must_be_file and not current.is_file():
        raise BootstrapError("INPUT_INVALID")
    return current


def _source_path(plan_directory: Path, value: Any) -> tuple[str, Path]:
    relative = _relative_path(value)
    return relative, _contained_path(
        plan_directory,
        relative,
        must_exist=True,
        must_be_file=True,
    )


def _artifact_target(root: Path, value: Any, *, must_exist: bool) -> tuple[str, Path]:
    relative = _relative_path(value)
    if relative == HARNESS_DIRECTORY or relative.startswith(HARNESS_DIRECTORY + "/"):
        raise BootstrapError("INPUT_INVALID")
    return relative, _contained_path(
        root,
        relative,
        must_exist=must_exist,
        must_be_file=must_exist,
    )


def _read_bounded(path: Path, maximum: int) -> bytes:
    try:
        if path.is_symlink() or not path.is_file():
            raise BootstrapError("INPUT_INVALID")
        if path.stat().st_size > maximum:
            raise BootstrapError("INPUT_INVALID")
        data = path.read_bytes()
    except OSError as exc:
        raise BootstrapError("IO_FAILURE") from exc
    if len(data) > maximum:
        raise BootstrapError("INPUT_INVALID")
    return data


def _mode(path: Path) -> int:
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise BootstrapError("IO_FAILURE") from exc


def _file_state(path: Path) -> tuple[bool, str | None, int | None]:
    if not os.path.lexists(path):
        return False, None, None
    if path.is_symlink() or not path.is_file():
        raise BootstrapError("PRECONDITION_CHANGED")
    data = _read_bounded(path, MAX_ARTIFACT_BYTES)
    return True, _sha256(data), _mode(path)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _directory_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _open_repo_parent(root: Path, relative: str) -> tuple[int, str]:
    """Open a repository-relative parent without following path symlinks."""

    pure = PurePosixPath(_relative_path(relative))
    descriptor: int | None = None
    try:
        descriptor = os.open(root, _directory_flags())
        for part in pure.parts[:-1]:
            next_descriptor = os.open(
                part,
                _directory_flags(),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
    except OSError as exc:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise BootstrapError("IO_FAILURE") from exc
    return descriptor, pure.parts[-1]


def _write_new(path: Path, data: bytes, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, mode)
        _fsync_directory(path.parent)
    except FileExistsError:
        raise
    except OSError as exc:
        try:
            path.unlink()
        except OSError:
            pass
        raise BootstrapError("IO_FAILURE") from exc


def _publish_no_clobber(
    root: Path,
    relative: str,
    data: bytes,
    mode: int,
) -> None:
    """Publish one complete file through a no-follow repository dirfd."""

    parent_descriptor, leaf = _open_repo_parent(root, relative)
    temporary = f".{leaf}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(temporary, flags, 0o600, dir_fd=parent_descriptor)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
        os.link(
            temporary,
            leaf,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        os.fsync(parent_descriptor)
    except FileExistsError:
        raise
    except OSError as exc:
        raise BootstrapError("IO_FAILURE") from exc
    finally:
        try:
            os.unlink(temporary, dir_fd=parent_descriptor)
        except FileNotFoundError:
            pass
        except OSError:
            pass
        os.close(parent_descriptor)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        raise BootstrapError("IO_FAILURE") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _atomic_json_at(
    directory_descriptor: int,
    leaf: str,
    payload: dict[str, Any],
) -> None:
    data = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    temporary = f".{leaf}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(temporary, flags, 0o600, dir_fd=directory_descriptor)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fchmod(handle.fileno(), 0o600)
            os.fsync(handle.fileno())
        os.replace(
            temporary,
            leaf,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        os.fsync(directory_descriptor)
    except OSError as exc:
        raise BootstrapError("IO_FAILURE") from exc
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_descriptor)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _inspect_harness(root: Path) -> tuple[Path, bool]:
    path = root / HARNESS_DIRECTORY
    if not os.path.lexists(path):
        return path, False
    if path.is_symlink() or not path.is_dir():
        raise BootstrapError("INPUT_INVALID")
    try:
        if path.resolve(strict=True) != path:
            raise BootstrapError("INPUT_INVALID")
    except (OSError, RuntimeError) as exc:
        raise BootstrapError("INPUT_INVALID") from exc
    return path, True


def _bootstrap_directory(root: Path, *, create: bool) -> tuple[Path, bool]:
    harness, harness_exists = _inspect_harness(root)
    created_harness = False
    if not harness_exists:
        if not create:
            return harness / BOOTSTRAP_DIRECTORY, False
        try:
            harness.mkdir(mode=0o755)
            _fsync_directory(root)
            created_harness = True
        except FileExistsError:
            _, harness_exists = _inspect_harness(root)
            if not harness_exists:
                raise BootstrapError("IO_FAILURE")
        except OSError as exc:
            raise BootstrapError("IO_FAILURE") from exc
    bootstrap = harness / BOOTSTRAP_DIRECTORY
    if os.path.lexists(bootstrap):
        if bootstrap.is_symlink() or not bootstrap.is_dir():
            raise BootstrapError("INPUT_INVALID")
    elif create:
        try:
            bootstrap.mkdir(mode=0o700)
            _fsync_directory(harness)
        except OSError as exc:
            raise BootstrapError("IO_FAILURE") from exc
    return bootstrap, created_harness


def _active_transactions(root: Path) -> list[str]:
    bootstrap, _ = _bootstrap_directory(root, create=False)
    if not bootstrap.is_dir():
        return []
    transaction_ids: list[str] = []
    active_id: str | None = None
    try:
        entries = list(bootstrap.iterdir())
    except OSError as exc:
        raise BootstrapError("IO_FAILURE") from exc
    for entry in entries:
        if TOMBSTONE.fullmatch(entry.name):
            continue
        if entry.name == ACTIVE_FILE:
            if entry.is_symlink() or not entry.is_file():
                raise BootstrapError("RECOVERY_REQUIRED")
            try:
                candidate = _read_bounded(entry, 128).decode("ascii").strip()
            except (BootstrapError, UnicodeDecodeError) as exc:
                raise BootstrapError("RECOVERY_REQUIRED") from exc
            if not TRANSACTION_ID.fullmatch(candidate):
                raise BootstrapError("RECOVERY_REQUIRED")
            active_id = candidate
            continue
        if entry.is_symlink() or not entry.is_dir() or not TRANSACTION_ID.fullmatch(entry.name):
            raise BootstrapError("RECOVERY_REQUIRED")
        transaction_ids.append(entry.name)
    transaction_ids.sort()
    if active_id is not None:
        if transaction_ids != [active_id]:
            raise BootstrapError("RECOVERY_REQUIRED")
        return [active_id]
    if len(transaction_ids) > 1:
        raise BootstrapError("RECOVERY_REQUIRED")
    return transaction_ids


def _transaction_directory(root: Path, transaction_id: str) -> Path:
    if not TRANSACTION_ID.fullmatch(transaction_id):
        raise BootstrapError("INPUT_INVALID")
    active = _active_transactions(root)
    if active != [transaction_id]:
        raise BootstrapError("TRANSACTION_NOT_FOUND")
    bootstrap, _ = _bootstrap_directory(root, create=False)
    path = bootstrap / transaction_id
    if not path.is_dir() or path.is_symlink():
        raise BootstrapError("TRANSACTION_NOT_FOUND")
    return path


def _journal_path(transaction: Path) -> Path:
    return transaction / "journal.json"


def _model_stage(transaction: Path) -> Path:
    return transaction / "staged" / "model.json"


def _artifact_stage(transaction: Path, artifact_id: str) -> Path:
    return transaction / "staged" / "artifacts" / artifact_id


def _legacy_backup(transaction: Path) -> Path:
    return transaction / "backup" / "routes.json"


def _validate_journal(payload: dict[str, Any], transaction_id: str) -> dict[str, Any]:
    try:
        _exact_keys(
            payload,
            {
                "schema_version",
                "transaction_id",
                "state",
                "plan_sha256",
                "created_harness_directory",
                "model",
                "artifacts",
                "legacy_routes",
                "verification",
                "failure",
            },
            set(),
            "JOURNAL_FIELDS",
        )
    except ContractError as exc:
        raise BootstrapError("RECOVERY_REQUIRED") from exc
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != JOURNAL_SCHEMA_VERSION
        or payload["transaction_id"] != transaction_id
        or not isinstance(payload["state"], str)
        or payload["state"] not in JOURNAL_STATES
        or not isinstance(payload["created_harness_directory"], bool)
        or not DIGEST.fullmatch(str(payload["plan_sha256"]))
    ):
        raise BootstrapError("RECOVERY_REQUIRED")
    model = payload["model"]
    if not isinstance(model, dict) or set(model) != {
        "raw_sha256",
        "semantic_sha256",
        "state",
    }:
        raise BootstrapError("RECOVERY_REQUIRED")
    if (
        not DIGEST.fullmatch(str(model["raw_sha256"]))
        or not DIGEST.fullmatch(str(model["semantic_sha256"]))
        or not isinstance(model["state"], str)
        or model["state"] not in {"STAGED", "PUBLISHED"}
    ):
        raise BootstrapError("RECOVERY_REQUIRED")
    artifacts = payload["artifacts"]
    if not isinstance(artifacts, list) or len(artifacts) > MAX_ARTIFACTS:
        raise BootstrapError("RECOVERY_REQUIRED")
    seen: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != {
            "id",
            "role",
            "mode",
            "path",
            "expected_sha256",
            "permissions",
            "base",
            "state",
        }:
            raise BootstrapError("RECOVERY_REQUIRED")
        artifact_id = item["id"]
        if (
            not isinstance(artifact_id, str)
            or not IDENTIFIER.fullmatch(artifact_id)
            or artifact_id in seen
            or not isinstance(item["role"], str)
            or item["role"] not in ARTIFACT_ROLES
            or not isinstance(item["mode"], str)
            or item["mode"] not in ARTIFACT_MODES
            or not isinstance(item["state"], str)
            or item["state"] not in ARTIFACT_STATES
            or not DIGEST.fullmatch(str(item["expected_sha256"]))
        ):
            raise BootstrapError("RECOVERY_REQUIRED")
        seen.add(artifact_id)
        _relative_path(item["path"])
        base = item["base"]
        if not isinstance(base, dict) or set(base) != {"exists", "sha256", "mode"}:
            raise BootstrapError("RECOVERY_REQUIRED")
        if not isinstance(base["exists"], bool):
            raise BootstrapError("RECOVERY_REQUIRED")
        if base["sha256"] is not None and not DIGEST.fullmatch(str(base["sha256"])):
            raise BootstrapError("RECOVERY_REQUIRED")
        if base["mode"] is not None and type(base["mode"]) is not int:
            raise BootstrapError("RECOVERY_REQUIRED")
        if item["mode"] == "adopt" and item["permissions"] is not None:
            raise BootstrapError("RECOVERY_REQUIRED")
        if item["mode"] == "create":
            if (
                not isinstance(item["permissions"], str)
                or item["permissions"] not in PERMISSIONS
            ):
                raise BootstrapError("RECOVERY_REQUIRED")
    legacy = payload["legacy_routes"]
    if legacy is not None:
        if not isinstance(legacy, dict) or set(legacy) != {
            "expected_sha256",
            "mode",
            "state",
        }:
            raise BootstrapError("RECOVERY_REQUIRED")
        if (
            not DIGEST.fullmatch(str(legacy["expected_sha256"]))
            or type(legacy["mode"]) is not int
            or not isinstance(legacy["state"], str)
            or legacy["state"] not in {"PRESENT", "RETIRED"}
        ):
            raise BootstrapError("RECOVERY_REQUIRED")
    verification = payload["verification"]
    if verification is not None:
        if not isinstance(verification, dict) or set(verification) != {
            "status",
            "sha256",
            "attempt_count",
            "trusted_receipt",
        }:
            raise BootstrapError("RECOVERY_REQUIRED")
        if (
            not isinstance(verification["status"], str)
            or verification["status"] not in {"NOT_PROVIDED", "BOOTSTRAP_OBSERVATION"}
            or type(verification["attempt_count"]) is not int
            or not 0 <= verification["attempt_count"] <= 64
            or verification["trusted_receipt"] is not False
            or (
                verification["sha256"] is not None
                and not DIGEST.fullmatch(str(verification["sha256"]))
            )
        ):
            raise BootstrapError("RECOVERY_REQUIRED")
    failure = payload["failure"]
    if failure is not None:
        if not isinstance(failure, dict) or set(failure) != {"code", "operation_id"}:
            raise BootstrapError("RECOVERY_REQUIRED")
        if (
            not isinstance(failure["code"], str)
            or not BLOCKER_CODE.fullmatch(failure["code"])
            or not isinstance(failure["operation_id"], str)
            or failure["operation_id"] not in {"apply", "publish", "recover"}
        ):
            raise BootstrapError("RECOVERY_REQUIRED")
    return payload


def _load_journal(root: Path, transaction_id: str) -> tuple[Path, dict[str, Any]]:
    transaction = _transaction_directory(root, transaction_id)
    path = _journal_path(transaction)
    if path.is_symlink():
        raise BootstrapError("RECOVERY_REQUIRED")
    try:
        payload, _ = load_json_object(path, MAX_JOURNAL_BYTES)
    except ContractError as exc:
        raise BootstrapError("RECOVERY_REQUIRED") from exc
    return transaction, _validate_journal(payload, transaction_id)


def _write_journal(transaction: Path, journal: dict[str, Any]) -> None:
    _atomic_json(_journal_path(transaction), journal)


def _failure(
    root: Path,
    transaction: Path,
    journal: dict[str, Any],
    code: str,
    operation_id: str,
) -> None:
    journal["state"] = "RECOVERY_REQUIRED"
    journal["failure"] = {"code": code, "operation_id": operation_id}
    if not TRANSACTION_ID.fullmatch(transaction.name):
        raise BootstrapError("IO_FAILURE")
    relative = (
        f"{HARNESS_DIRECTORY}/{BOOTSTRAP_DIRECTORY}/"
        f"{transaction.name}/journal.json"
    )
    directory_descriptor, leaf = _open_repo_parent(root, relative)
    try:
        _atomic_json_at(directory_descriptor, leaf, journal)
    finally:
        os.close(directory_descriptor)


def _safe_cleanup_transaction(
    root: Path,
    transaction: Path,
    created_harness: bool,
    *,
    canonical_legacy_must_be_absent: bool = False,
) -> None:
    bootstrap = transaction.parent
    harness = bootstrap.parent
    tombstone = bootstrap / (
        f".tombstone-{transaction.name}-{secrets.token_hex(8)}"
    )
    try:
        if canonical_legacy_must_be_absent and os.path.lexists(
            root / REGISTRY_RELATIVE_PATH
        ):
            raise BootstrapError("PRECONDITION_CHANGED")
        if transaction.is_symlink() or transaction.parent.name != BOOTSTRAP_DIRECTORY:
            raise BootstrapError("IO_FAILURE")
        active = bootstrap / ACTIVE_FILE
        active_exists = os.path.lexists(active)
        if active_exists:
            if active.is_symlink() or not active.is_file():
                raise BootstrapError("IO_FAILURE")
            active_id = _read_bounded(active, 128).decode("ascii").strip()
            if active_id != transaction.name:
                raise BootstrapError("IO_FAILURE")

        bootstrap_descriptor = os.open(bootstrap, _directory_flags())
        try:
            if active_exists:
                try:
                    os.unlink(ACTIVE_FILE, dir_fd=bootstrap_descriptor)
                except FileNotFoundError:
                    pass
                os.fsync(bootstrap_descriptor)
            os.rename(
                transaction.name,
                tombstone.name,
                src_dir_fd=bootstrap_descriptor,
                dst_dir_fd=bootstrap_descriptor,
            )
            os.fsync(bootstrap_descriptor)
        finally:
            os.close(bootstrap_descriptor)

        # Once renamed and deactivated, partial deletion leaves only an
        # ignorable tombstone and cannot block a later transaction.
        shutil.rmtree(tombstone)
        _fsync_directory(bootstrap)
        if not any(bootstrap.iterdir()):
            bootstrap.rmdir()
            _fsync_directory(harness)
        if created_harness and harness.is_dir() and not any(harness.iterdir()):
            harness.rmdir()
            _fsync_directory(root)
    except BootstrapError:
        raise
    except OSError as exc:
        raise BootstrapError("IO_FAILURE") from exc


def _load_plan(root: Path, plan_value: str | Path) -> dict[str, Any]:
    plan_candidate = Path(plan_value).expanduser()
    if plan_candidate.is_symlink():
        raise BootstrapError("INPUT_INVALID")
    try:
        plan_path = plan_candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BootstrapError("INPUT_INVALID") from exc
    if not plan_path.is_file():
        raise BootstrapError("INPUT_INVALID")
    try:
        raw_plan, plan_sha256 = load_json_object(plan_path, MAX_PLAN_BYTES)
    except ContractError as exc:
        raise BootstrapError("INPUT_INVALID") from exc
    try:
        _exact_keys(
            raw_plan,
            {"schema_version", "model_source", "artifacts"},
            {"legacy_routes"},
            "PLAN_FIELDS",
        )
    except ContractError as exc:
        raise BootstrapError("INPUT_INVALID") from exc
    if type(raw_plan["schema_version"]) is not int or raw_plan["schema_version"] != 1:
        raise BootstrapError("INPUT_INVALID")
    artifacts_raw = raw_plan["artifacts"]
    if not isinstance(artifacts_raw, list) or len(artifacts_raw) > MAX_ARTIFACTS:
        raise BootstrapError("INPUT_INVALID")

    plan_directory = plan_path.parent.resolve(strict=True)
    _, model_source = _source_path(plan_directory, raw_plan["model_source"])
    try:
        model_payload, model_raw_sha256 = load_json_object(model_source, MAX_MODEL_BYTES)
    except ContractError as exc:
        raise BootstrapError("INPUT_INVALID") from exc
    model_bytes = _read_bounded(model_source, MAX_MODEL_BYTES)
    if _sha256(model_bytes) != model_raw_sha256:
        raise BootstrapError("PRECONDITION_CHANGED")

    artifacts: list[dict[str, Any]] = []
    ids: set[str] = set()
    paths: set[str] = set()
    total_staged = len(model_bytes)
    for raw in artifacts_raw:
        if not isinstance(raw, dict):
            raise BootstrapError("INPUT_INVALID")
        mode = raw.get("mode")
        if mode == "adopt":
            required = {"id", "role", "mode", "path", "expected_sha256"}
        elif mode == "create":
            required = {"id", "role", "mode", "path", "source", "permissions"}
        else:
            raise BootstrapError("INPUT_INVALID")
        if set(raw) != required:
            raise BootstrapError("INPUT_INVALID")
        artifact_id = _identifier(raw["id"])
        role = raw["role"]
        if (
            not isinstance(role, str)
            or role not in ARTIFACT_ROLES
            or artifact_id in ids
        ):
            raise BootstrapError("INPUT_INVALID")
        ids.add(artifact_id)
        relative, target = _artifact_target(root, raw["path"], must_exist=mode == "adopt")
        if relative in paths:
            raise BootstrapError("INPUT_INVALID")
        paths.add(relative)

        if mode == "adopt":
            expected = _digest(raw["expected_sha256"])
            exists, current_digest, current_mode = _file_state(target)
            if not exists or current_digest != expected:
                raise BootstrapError("PRECONDITION_CHANGED")
            artifacts.append(
                {
                    "id": artifact_id,
                    "role": role,
                    "mode": mode,
                    "path": relative,
                    "expected_sha256": expected,
                    "permissions": None,
                    "base": {
                        "exists": True,
                        "sha256": current_digest,
                        "mode": current_mode,
                    },
                    "state": "PENDING",
                    "bytes": None,
                }
            )
            continue

        permissions = raw["permissions"]
        if not isinstance(permissions, str) or permissions not in PERMISSIONS:
            raise BootstrapError("INPUT_INVALID")
        _, source = _source_path(plan_directory, raw["source"])
        source_bytes = _read_bounded(source, MAX_ARTIFACT_BYTES)
        source_digest = _sha256(source_bytes)
        total_staged += len(source_bytes)
        if total_staged > MAX_TOTAL_STAGED_BYTES:
            raise BootstrapError("INPUT_INVALID")
        exists, current_digest, current_mode = _file_state(target)
        if exists and (
            current_digest != source_digest or current_mode != PERMISSIONS[permissions]
        ):
            raise BootstrapError("PRECONDITION_CHANGED")
        artifacts.append(
            {
                "id": artifact_id,
                "role": role,
                "mode": mode,
                "path": relative,
                "expected_sha256": source_digest,
                "permissions": permissions,
                "base": {
                    "exists": exists,
                    "sha256": current_digest,
                    "mode": current_mode,
                },
                "state": "PENDING",
                "bytes": source_bytes,
            }
        )

    legacy_record: dict[str, Any] | None = None
    legacy_path = root / REGISTRY_RELATIVE_PATH
    if "legacy_routes" in raw_plan:
        legacy = raw_plan["legacy_routes"]
        if not isinstance(legacy, dict) or set(legacy) != {"path", "expected_sha256"}:
            raise BootstrapError("INPUT_INVALID")
        if _relative_path(legacy["path"]) != REGISTRY_RELATIVE_PATH:
            raise BootstrapError("INPUT_INVALID")
        expected = _digest(legacy["expected_sha256"])
        _contained_path(root, REGISTRY_RELATIVE_PATH, must_exist=True, must_be_file=True)
        data = _read_bounded(legacy_path, MAX_PLAN_BYTES)
        if _sha256(data) != expected:
            raise BootstrapError("PRECONDITION_CHANGED")
        legacy_record = {
            "expected_sha256": expected,
            "mode": _mode(legacy_path),
            "state": "PRESENT",
        }
    elif os.path.lexists(legacy_path):
        raise BootstrapError("INPUT_INVALID")

    return {
        "plan_sha256": plan_sha256,
        "model_payload": model_payload,
        "model_bytes": model_bytes,
        "model_raw_sha256": model_raw_sha256,
        "model_semantic_sha256": _semantic_sha256(model_payload),
        "artifacts": artifacts,
        "legacy_routes": legacy_record,
    }


def _model_target(root: Path) -> Path:
    harness, exists = _inspect_harness(root)
    target = root / MODEL_RELATIVE_PATH
    if exists and os.path.lexists(target) and (target.is_symlink() or not target.is_file()):
        raise BootstrapError("INPUT_INVALID")
    return target


def _model_payload(path: Path) -> dict[str, Any]:
    try:
        payload, _ = load_json_object(path, MAX_MODEL_BYTES)
    except ContractError as exc:
        raise BootstrapError("MODEL_INVALID") from exc
    return payload


def _model_payload_no_follow(root: Path) -> dict[str, Any]:
    """Read the canonical model from one pinned, no-follow file descriptor."""

    try:
        parent_descriptor, leaf = _open_repo_parent(root, MODEL_RELATIVE_PATH)
    except BootstrapError as exc:
        raise BootstrapError("MODEL_ALREADY_EXISTS_DIFFERENT") from exc
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        try:
            descriptor = os.open(leaf, flags, dir_fd=parent_descriptor)
        except OSError as exc:
            raise BootstrapError("MODEL_ALREADY_EXISTS_DIFFERENT") from exc
        try:
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode):
                raise BootstrapError("MODEL_ALREADY_EXISTS_DIFFERENT")
            if file_stat.st_size > MAX_MODEL_BYTES:
                raise BootstrapError("MODEL_INVALID")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                data = handle.read(MAX_MODEL_BYTES + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    finally:
        os.close(parent_descriptor)
    if len(data) > MAX_MODEL_BYTES:
        raise BootstrapError("MODEL_INVALID")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise BootstrapError("MODEL_INVALID")
            result[key] = value
        return result

    try:
        payload = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BootstrapError("MODEL_INVALID") from exc
    if not isinstance(payload, dict):
        raise BootstrapError("MODEL_INVALID")
    return payload


def _artifacts_satisfied(root: Path, artifacts: list[dict[str, Any]]) -> bool:
    for item in artifacts:
        _, target = _artifact_target(root, item["path"], must_exist=True)
        exists, digest, current_mode = _file_state(target)
        if not exists or digest != item["expected_sha256"]:
            return False
        if item["mode"] == "create" and current_mode != PERMISSIONS[item["permissions"]]:
            return False
    return True


def prepare_repository(root: Path, plan_path: str | Path) -> dict[str, Any]:
    root = _root(root)
    if _active_transactions(root):
        raise BootstrapError("ACTIVE_TRANSACTION_EXISTS")
    plan = _load_plan(root, plan_path)
    model_target = _model_target(root)
    if os.path.lexists(model_target):
        existing = _model_payload_no_follow(root)
        if _semantic_sha256(existing) != plan["model_semantic_sha256"]:
            raise BootstrapError("MODEL_ALREADY_EXISTS_DIFFERENT")
        if plan["legacy_routes"] is not None or not _artifacts_satisfied(
            root, plan["artifacts"]
        ):
            raise BootstrapError("MODEL_INVALID")
        try:
            validate_model(root, plan["model_payload"])
        except (ContractError, OSError) as exc:
            raise BootstrapError("MODEL_INVALID") from exc
        # Linearize after the artifact checks: a concurrent replacement of the
        # canonical model must not be reported as a semantic NOOP.
        live = _model_payload_no_follow(root)
        if _semantic_sha256(live) != plan["model_semantic_sha256"]:
            raise BootstrapError("MODEL_ALREADY_EXISTS_DIFFERENT")
        try:
            validate_model(root, live)
        except (ContractError, OSError) as exc:
            raise BootstrapError("MODEL_INVALID") from exc
        return {"status": "NOOP", "transaction_id": None}

    bootstrap, created_harness = _bootstrap_directory(root, create=True)
    transaction_id = secrets.token_hex(16)
    transaction = bootstrap / transaction_id
    try:
        transaction.mkdir(mode=0o700)
        staged_artifacts = transaction / "staged" / "artifacts"
        staged_artifacts.mkdir(parents=True, mode=0o700)
        (transaction / "backup").mkdir(mode=0o700)
        _write_new(_model_stage(transaction), plan["model_bytes"], 0o600)
        journal_artifacts: list[dict[str, Any]] = []
        for item in plan["artifacts"]:
            record = {key: value for key, value in item.items() if key != "bytes"}
            if item["mode"] == "create":
                _write_new(
                    _artifact_stage(transaction, item["id"]),
                    item["bytes"],
                    PERMISSIONS[item["permissions"]],
                )
            journal_artifacts.append(record)
        journal = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "transaction_id": transaction_id,
            "state": "PREPARED",
            "plan_sha256": plan["plan_sha256"],
            "created_harness_directory": created_harness,
            "model": {
                "raw_sha256": plan["model_raw_sha256"],
                "semantic_sha256": plan["model_semantic_sha256"],
                "state": "STAGED",
            },
            "artifacts": journal_artifacts,
            "legacy_routes": plan["legacy_routes"],
            "verification": None,
            "failure": None,
        }
        _write_journal(transaction, journal)
        try:
            _write_new(
                bootstrap / ACTIVE_FILE,
                (transaction_id + "\n").encode("ascii"),
                0o600,
            )
        except FileExistsError as exc:
            raise BootstrapError("ACTIVE_TRANSACTION_EXISTS") from exc
    except (BootstrapError, OSError):
        if transaction.exists() and not transaction.is_symlink():
            shutil.rmtree(transaction, ignore_errors=True)
        raise
    return {"status": "PREPARED", "transaction_id": transaction_id}


def _verify_staging(transaction: Path, journal: dict[str, Any]) -> None:
    model = _read_bounded(_model_stage(transaction), MAX_MODEL_BYTES)
    if _sha256(model) != journal["model"]["raw_sha256"]:
        raise BootstrapError("RECOVERY_REQUIRED")
    total = len(model)
    for item in journal["artifacts"]:
        if item["mode"] != "create":
            continue
        data = _read_bounded(_artifact_stage(transaction, item["id"]), MAX_ARTIFACT_BYTES)
        total += len(data)
        if _sha256(data) != item["expected_sha256"]:
            raise BootstrapError("RECOVERY_REQUIRED")
    if total > MAX_TOTAL_STAGED_BYTES:
        raise BootstrapError("RECOVERY_REQUIRED")


def _preflight_artifacts(root: Path, journal: dict[str, Any]) -> None:
    for item in journal["artifacts"]:
        _, target = _artifact_target(
            root,
            item["path"],
            must_exist=item["mode"] == "adopt",
        )
        exists, digest, current_mode = _file_state(target)
        if item["mode"] == "adopt":
            if not exists or digest != item["expected_sha256"]:
                raise BootstrapError("PRECONDITION_CHANGED")
            continue
        desired_mode = PERMISSIONS[item["permissions"]]
        if exists and (digest != item["expected_sha256"] or current_mode != desired_mode):
            raise BootstrapError("PRECONDITION_CHANGED")
        if not exists and item["base"]["exists"]:
            raise BootstrapError("PRECONDITION_CHANGED")


def _apply_artifacts(
    root: Path,
    transaction: Path,
    journal: dict[str, Any],
) -> None:
    _verify_staging(transaction, journal)
    _preflight_artifacts(root, journal)
    journal["state"] = "APPLYING"
    journal["failure"] = None
    _write_journal(transaction, journal)
    for item in journal["artifacts"]:
        _, target = _artifact_target(
            root,
            item["path"],
            must_exist=item["mode"] == "adopt",
        )
        if item["mode"] == "adopt":
            item["state"] = "ADOPTED"
            _write_journal(transaction, journal)
            continue
        exists, digest, current_mode = _file_state(target)
        if exists:
            if (
                digest != item["expected_sha256"]
                or current_mode != PERMISSIONS[item["permissions"]]
            ):
                raise BootstrapError("PRECONDITION_CHANGED")
            if item["state"] != "CREATED":
                item["state"] = "UNCHANGED"
            _write_journal(transaction, journal)
            continue
        data = _read_bounded(_artifact_stage(transaction, item["id"]), MAX_ARTIFACT_BYTES)
        try:
            _publish_no_clobber(
                root,
                item["path"],
                data,
                PERMISSIONS[item["permissions"]],
            )
        except FileExistsError:
            exists, digest, current_mode = _file_state(target)
            if (
                not exists
                or digest != item["expected_sha256"]
                or current_mode != PERMISSIONS[item["permissions"]]
            ):
                raise BootstrapError("PRECONDITION_CHANGED")
            item["state"] = "UNCHANGED"
        else:
            item["state"] = "CREATED"
        _write_journal(transaction, journal)
    journal["state"] = "ARTIFACTS_READY"
    journal["failure"] = None
    _write_journal(transaction, journal)


def apply_repository(root: Path, transaction_id: str) -> dict[str, Any]:
    root = _root(root)
    transaction, journal = _load_journal(root, transaction_id)
    if journal["state"] == "ARTIFACTS_READY":
        return {"status": "ARTIFACTS_READY", "transaction_id": transaction_id}
    if journal["state"] != "PREPARED":
        raise BootstrapError("RECOVERY_REQUIRED")
    try:
        _apply_artifacts(root, transaction, journal)
    except BootstrapError as exc:
        _failure(root, transaction, journal, exc.code, "apply")
        raise
    return {"status": "ARTIFACTS_READY", "transaction_id": transaction_id}


def _validate_verification(
    root: Path,
    value: str | Path,
    model_payload: dict[str, Any],
) -> dict[str, Any]:
    candidate = Path(value).expanduser()
    if candidate.is_symlink():
        raise BootstrapError("INPUT_INVALID")
    try:
        path = candidate.resolve(strict=True)
        payload, digest = load_json_object(path, MAX_VERIFICATION_BYTES)
    except (OSError, ContractError) as exc:
        raise BootstrapError("INPUT_INVALID") from exc
    if set(payload) != {"schema_version", "sensor_attempts"}:
        raise BootstrapError("INPUT_INVALID")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise BootstrapError("INPUT_INVALID")
    attempts = payload["sensor_attempts"]
    if not isinstance(attempts, list) or len(attempts) > 64:
        raise BootstrapError("INPUT_INVALID")
    sensors = {
        item.get("id")
        for item in model_payload.get("sensors", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise BootstrapError("INPUT_INVALID")
        required = {"sensor_id", "execution_status", "outcome", "proof_layer"}
        optional = {"exit_code", "evidence_path", "evidence_sha256", "reason_code"}
        if not required.issubset(attempt) or not set(attempt).issubset(required | optional):
            raise BootstrapError("INPUT_INVALID")
        execution_status = attempt["execution_status"]
        outcome = attempt["outcome"]
        proof_layer = attempt["proof_layer"]
        if (
            _identifier(attempt["sensor_id"]) not in sensors
            or not isinstance(execution_status, str)
            or execution_status not in {"completed", "unavailable"}
            or not isinstance(outcome, str)
            or outcome not in {"pass", "fail", "unknown"}
            or not isinstance(proof_layer, str)
            or proof_layer not in PROOF_LAYERS
        ):
            raise BootstrapError("INPUT_INVALID")
        if "exit_code" in attempt and (
            type(attempt["exit_code"]) is not int or not 0 <= attempt["exit_code"] <= 255
        ):
            raise BootstrapError("INPUT_INVALID")
        has_path = "evidence_path" in attempt
        has_digest = "evidence_sha256" in attempt
        if has_path != has_digest:
            raise BootstrapError("INPUT_INVALID")
        if has_path:
            relative = _relative_path(attempt["evidence_path"])
            evidence = _contained_path(root, relative, must_exist=True, must_be_file=True)
            if _sha256(_read_bounded(evidence, MAX_ARTIFACT_BYTES)) != _digest(
                attempt["evidence_sha256"]
            ):
                raise BootstrapError("PRECONDITION_CHANGED")
        if execution_status == "unavailable":
            reason = attempt.get("reason_code")
            if (
                outcome != "unknown"
                or not isinstance(reason, str)
                or reason not in UNAVAILABLE_REASONS
            ):
                raise BootstrapError("INPUT_INVALID")
        elif "reason_code" in attempt and (
            not isinstance(attempt["reason_code"], str)
            or not BLOCKER_CODE.fullmatch(attempt["reason_code"])
        ):
            raise BootstrapError("INPUT_INVALID")
    return {
        "status": "BOOTSTRAP_OBSERVATION",
        "sha256": digest,
        "attempt_count": len(attempts),
        "trusted_receipt": False,
    }


def _live_model_matches(root: Path, semantic_sha256: str) -> bool:
    target = _model_target(root)
    if not target.is_file():
        return False
    return _semantic_sha256(_model_payload(target)) == semantic_sha256


def _verify_ready_artifacts(root: Path, journal: dict[str, Any]) -> None:
    _preflight_artifacts(root, journal)
    for item in journal["artifacts"]:
        _, target = _artifact_target(root, item["path"], must_exist=True)
        exists, digest, current_mode = _file_state(target)
        if not exists or digest != item["expected_sha256"]:
            raise BootstrapError("PRECONDITION_CHANGED")
        if item["mode"] == "create" and current_mode != PERMISSIONS[item["permissions"]]:
            raise BootstrapError("PRECONDITION_CHANGED")


def _retire_legacy(
    root: Path,
    transaction: Path,
    journal: dict[str, Any],
) -> None:
    legacy = journal["legacy_routes"]
    canonical = root / REGISTRY_RELATIVE_PATH
    backup = _legacy_backup(transaction)
    if legacy is None:
        if os.path.lexists(canonical):
            raise BootstrapError("PRECONDITION_CHANGED")
        return
    canonical_exists = os.path.lexists(canonical)
    backup_exists = os.path.lexists(backup)
    if (
        legacy["state"] == "RETIRED"
        and journal["model"]["state"] == "PUBLISHED"
        and not backup_exists
    ):
        if canonical_exists:
            # A legacy authority appearing after the committed retirement is a
            # concurrent resurrection, not a backup to retire again.
            raise BootstrapError("PRECONDITION_CHANGED")
        return
    if canonical_exists and backup_exists:
        raise BootstrapError("RECOVERY_REQUIRED")
    if backup_exists:
        if backup.is_symlink() or not backup.is_file():
            raise BootstrapError("RECOVERY_REQUIRED")
        if _sha256(_read_bounded(backup, MAX_PLAN_BYTES)) != legacy["expected_sha256"]:
            raise BootstrapError("RECOVERY_REQUIRED")
        legacy["state"] = "RETIRED"
        journal["state"] = "LEGACY_RETIRED"
        _write_journal(transaction, journal)
        return
    if not canonical_exists:
        if (
            legacy["state"] == "RETIRED"
            and journal["model"]["state"] == "PUBLISHED"
            and _live_model_matches(root, journal["model"]["semantic_sha256"])
        ):
            return
        raise BootstrapError("PRECONDITION_CHANGED")
    if canonical.is_symlink() or not canonical.is_file():
        raise BootstrapError("PRECONDITION_CHANGED")
    if _sha256(_read_bounded(canonical, MAX_PLAN_BYTES)) != legacy["expected_sha256"]:
        raise BootstrapError("PRECONDITION_CHANGED")
    journal["state"] = "LEGACY_RETIRING"
    _write_journal(transaction, journal)
    try:
        os.rename(canonical, backup)
        _fsync_directory(canonical.parent)
        _fsync_directory(backup.parent)
    except OSError as exc:
        raise BootstrapError("IO_FAILURE") from exc
    legacy["state"] = "RETIRED"
    journal["state"] = "LEGACY_RETIRED"
    _write_journal(transaction, journal)


def _finalize_commit(
    root: Path,
    transaction: Path,
    journal: dict[str, Any],
) -> None:
    legacy = journal["legacy_routes"]
    canonical_legacy = root / REGISTRY_RELATIVE_PATH
    if os.path.lexists(canonical_legacy):
        raise BootstrapError("PRECONDITION_CHANGED")
    if legacy is not None:
        backup = _legacy_backup(transaction)
        if backup.is_file() and not backup.is_symlink():
            if _sha256(_read_bounded(backup, MAX_PLAN_BYTES)) != legacy["expected_sha256"]:
                raise BootstrapError("RECOVERY_REQUIRED")
            try:
                backup.unlink()
                _fsync_directory(backup.parent)
            except OSError as exc:
                raise BootstrapError("IO_FAILURE") from exc
    _safe_cleanup_transaction(
        root,
        transaction,
        journal["created_harness_directory"],
        canonical_legacy_must_be_absent=True,
    )


def _publish_core(
    root: Path,
    transaction: Path,
    journal: dict[str, Any],
    verification: str | Path | None,
) -> None:
    _verify_staging(transaction, journal)
    _verify_ready_artifacts(root, journal)
    try:
        model_payload, _ = load_json_object(_model_stage(transaction), MAX_MODEL_BYTES)
        validate_model(root, model_payload)
    except (ContractError, OSError) as exc:
        raise BootstrapError("MODEL_INVALID") from exc
    if _semantic_sha256(model_payload) != journal["model"]["semantic_sha256"]:
        raise BootstrapError("RECOVERY_REQUIRED")
    if verification is not None:
        observation = _validate_verification(root, verification, model_payload)
        if journal["verification"] is not None and journal["verification"] != observation:
            raise BootstrapError("INPUT_INVALID")
        journal["verification"] = observation
        _write_journal(transaction, journal)
    elif journal["verification"] is None:
        journal["verification"] = {
            "status": "NOT_PROVIDED",
            "sha256": None,
            "attempt_count": 0,
            "trusted_receipt": False,
        }
        _write_journal(transaction, journal)

    target = _model_target(root)
    if target.is_file() and not _live_model_matches(root, journal["model"]["semantic_sha256"]):
        raise BootstrapError("MODEL_ALREADY_EXISTS_DIFFERENT")
    _retire_legacy(root, transaction, journal)
    if not target.is_file():
        journal["state"] = "MODEL_PUBLISHING"
        _write_journal(transaction, journal)
        model_bytes = _read_bounded(_model_stage(transaction), MAX_MODEL_BYTES)
        try:
            _publish_no_clobber(root, MODEL_RELATIVE_PATH, model_bytes, 0o644)
        except FileExistsError:
            if not _live_model_matches(root, journal["model"]["semantic_sha256"]):
                raise BootstrapError("MODEL_ALREADY_EXISTS_DIFFERENT")
    if not _live_model_matches(root, journal["model"]["semantic_sha256"]):
        raise BootstrapError("MODEL_ALREADY_EXISTS_DIFFERENT")
    journal["model"]["state"] = "PUBLISHED"
    journal["state"] = "MODEL_PUBLISHED"
    journal["failure"] = None
    _write_journal(transaction, journal)
    _finalize_commit(root, transaction, journal)


def publish_repository(
    root: Path,
    transaction_id: str,
    verification: str | Path | None,
) -> dict[str, Any]:
    root = _root(root)
    transaction, journal = _load_journal(root, transaction_id)
    if journal["state"] != "ARTIFACTS_READY":
        raise BootstrapError("RECOVERY_REQUIRED")
    try:
        _publish_core(root, transaction, journal, verification)
    except BootstrapError as exc:
        _failure(root, transaction, journal, exc.code, "publish")
        raise
    return {"status": "COMMITTED", "transaction_id": transaction_id}


def _read_quarantined(
    directory_descriptor: int,
    name: str,
) -> tuple[bytes | None, int | None]:
    try:
        file_stat = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
    except OSError as exc:
        raise BootstrapError("IO_FAILURE") from exc
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > MAX_ARTIFACT_BYTES:
        return None, None
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
        with os.fdopen(descriptor, "rb") as handle:
            data = handle.read(MAX_ARTIFACT_BYTES + 1)
    except OSError as exc:
        raise BootstrapError("IO_FAILURE") from exc
    if len(data) > MAX_ARTIFACT_BYTES:
        return None, None
    return data, stat.S_IMODE(file_stat.st_mode)


def _quarantine_created_artifact(
    root: Path,
    transaction: Path,
    item: dict[str, Any],
) -> None:
    """Atomically remove a candidate, then prove it is transaction-owned."""

    try:
        parent_descriptor, leaf = _open_repo_parent(root, item["path"])
    except BootstrapError as exc:
        raise BootstrapError("ROLLBACK_CONFLICT") from exc
    quarantine = transaction / "quarantine"
    try:
        try:
            quarantine.mkdir(mode=0o700)
        except FileExistsError:
            if quarantine.is_symlink() or not quarantine.is_dir():
                raise BootstrapError("ROLLBACK_CONFLICT")
        quarantine_descriptor = os.open(quarantine, _directory_flags())
    except (OSError, BootstrapError) as exc:
        os.close(parent_descriptor)
        if isinstance(exc, BootstrapError):
            raise
        raise BootstrapError("IO_FAILURE") from exc

    quarantine_name = item["id"]
    try:
        try:
            os.stat(
                quarantine_name,
                dir_fd=quarantine_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        else:
            raise BootstrapError("ROLLBACK_CONFLICT")

        try:
            os.rename(
                leaf,
                quarantine_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=quarantine_descriptor,
            )
        except FileNotFoundError:
            return
        except OSError as exc:
            raise BootstrapError("ROLLBACK_CONFLICT") from exc
        os.fsync(parent_descriptor)
        os.fsync(quarantine_descriptor)

        data, current_mode = _read_quarantined(
            quarantine_descriptor,
            quarantine_name,
        )
        owned = (
            data is not None
            and _sha256(data) == item["expected_sha256"]
            and current_mode == PERMISSIONS[item["permissions"]]
        )
        if owned:
            os.unlink(quarantine_name, dir_fd=quarantine_descriptor)
            os.fsync(quarantine_descriptor)
            return

        # Restore a concurrent replacement without clobbering anything that
        # appeared after quarantine. If restoration races, retain the file in
        # quarantine and report a conflict for manual recovery.
        try:
            os.link(
                quarantine_name,
                leaf,
                src_dir_fd=quarantine_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except (FileExistsError, OSError):
            pass
        else:
            os.unlink(quarantine_name, dir_fd=quarantine_descriptor)
            os.fsync(parent_descriptor)
            os.fsync(quarantine_descriptor)
        raise BootstrapError("ROLLBACK_CONFLICT")
    finally:
        os.close(quarantine_descriptor)
        os.close(parent_descriptor)


def _rollback(root: Path, transaction: Path, journal: dict[str, Any]) -> None:
    try:
        model_target = _model_target(root)
    except BootstrapError as exc:
        raise BootstrapError("ROLLBACK_CONFLICT") from exc
    if journal["model"]["state"] == "PUBLISHED" or journal["state"] == "MODEL_PUBLISHED":
        raise BootstrapError("ROLLBACK_CONFLICT")
    if os.path.lexists(model_target):
        raise BootstrapError("ROLLBACK_CONFLICT")

    legacy = journal["legacy_routes"]
    if legacy is not None:
        canonical = root / REGISTRY_RELATIVE_PATH
        backup = _legacy_backup(transaction)
        canonical_exists = os.path.lexists(canonical)
        backup_exists = os.path.lexists(backup)
        if canonical_exists:
            if canonical.is_symlink() or not canonical.is_file():
                raise BootstrapError("ROLLBACK_CONFLICT")
            if _sha256(_read_bounded(canonical, MAX_PLAN_BYTES)) != legacy["expected_sha256"]:
                raise BootstrapError("ROLLBACK_CONFLICT")
        elif not backup_exists:
            raise BootstrapError("ROLLBACK_CONFLICT")
        if backup_exists:
            if backup.is_symlink() or not backup.is_file():
                raise BootstrapError("ROLLBACK_CONFLICT")
            if _sha256(_read_bounded(backup, MAX_PLAN_BYTES)) != legacy["expected_sha256"]:
                raise BootstrapError("ROLLBACK_CONFLICT")
            if not canonical_exists:
                try:
                    os.link(backup, canonical)
                    _fsync_directory(canonical.parent)
                except FileExistsError as exc:
                    raise BootstrapError("ROLLBACK_CONFLICT") from exc
                except OSError as exc:
                    raise BootstrapError("IO_FAILURE") from exc
            try:
                backup.unlink()
                _fsync_directory(backup.parent)
            except OSError as exc:
                raise BootstrapError("IO_FAILURE") from exc

    for item in journal["artifacts"]:
        if item["mode"] != "create" or item["base"]["exists"]:
            continue
        _, target = _artifact_target(root, item["path"], must_exist=False)
        if not os.path.lexists(target):
            continue
        if item["state"] != "CREATED":
            raise BootstrapError("ROLLBACK_CONFLICT")
        _quarantine_created_artifact(root, transaction, item)
    _safe_cleanup_transaction(root, transaction, journal["created_harness_directory"])


def recover_repository(root: Path, transaction_id: str, mode: str) -> dict[str, Any]:
    root = _root(root)
    transaction, journal = _load_journal(root, transaction_id)
    if mode == "rollback":
        _rollback(root, transaction, journal)
        return {"status": "ROLLED_BACK", "transaction_id": transaction_id}
    if mode != "resume":
        raise BootstrapError("INPUT_INVALID")
    try:
        if not _live_model_matches(root, journal["model"]["semantic_sha256"]):
            _apply_artifacts(root, transaction, journal)
        else:
            _verify_ready_artifacts(root, journal)
        _publish_core(root, transaction, journal, None)
    except BootstrapError as exc:
        _failure(root, transaction, journal, exc.code, "recover")
        raise
    return {"status": "COMMITTED", "transaction_id": transaction_id}


def status_repository(root: Path, transaction_id: str | None) -> dict[str, Any]:
    root = _root(root)
    if transaction_id is None:
        active = _active_transactions(root)
        if not active:
            return {"status": "NO_ACTIVE_TRANSACTION", "transaction_id": None}
        if len(active) > 1:
            raise BootstrapError("RECOVERY_REQUIRED")
        transaction_id = active[0]
    _, journal = _load_journal(root, transaction_id)
    return {
        "status": journal["state"],
        "transaction_id": transaction_id,
        "artifact_count": len(journal["artifacts"]),
        "failure": journal["failure"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--repository", required=True)
    prepare.add_argument("--plan", required=True)
    prepare.add_argument("--json", action="store_true")

    apply = subparsers.add_parser("apply")
    apply.add_argument("--repository", required=True)
    apply.add_argument("--transaction", required=True)
    apply.add_argument("--json", action="store_true")

    publish = subparsers.add_parser("publish")
    publish.add_argument("--repository", required=True)
    publish.add_argument("--transaction", required=True)
    publish.add_argument("--verification")
    publish.add_argument("--json", action="store_true")

    recover = subparsers.add_parser("recover")
    recover.add_argument("--repository", required=True)
    recover.add_argument("--transaction", required=True)
    recover.add_argument("--mode", required=True, choices=("resume", "rollback"))
    recover.add_argument("--json", action="store_true")

    status = subparsers.add_parser("status")
    status.add_argument("--repository", required=True)
    status.add_argument("--transaction")
    status.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        root = _root(args.repository)
        if args.command == "prepare":
            result = prepare_repository(root, args.plan)
        elif args.command == "apply":
            result = apply_repository(root, args.transaction)
        elif args.command == "publish":
            result = publish_repository(root, args.transaction, args.verification)
        elif args.command == "recover":
            result = recover_repository(root, args.transaction, args.mode)
        else:
            result = status_repository(root, args.transaction)
        output = {"ok": True, **result}
    except BootstrapError as exc:
        output = {"ok": False, "code": exc.code}
        if args.json:
            print(json.dumps(output, sort_keys=True, separators=(",", ":")))
        else:
            print(f"FAIL: {exc.code}", file=sys.stderr)
        return 1
    except OSError:
        output = {"ok": False, "code": "IO_FAILURE"}
        if args.json:
            print(json.dumps(output, sort_keys=True, separators=(",", ":")))
        else:
            print("FAIL: IO_FAILURE", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    else:
        print(f"PASS: {output['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
