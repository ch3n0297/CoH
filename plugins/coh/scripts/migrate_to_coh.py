#!/usr/bin/env python3
"""Recoverably migrate one predecessor repository namespace to .coh."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from harness_model import MAX_MODEL_BYTES, validate_model
from coh_hook_common import MAX_REGISTRY_BYTES, ContractError
from migrate_routes_to_model import (
    _model_output_bytes,
    convert_legacy_registry,
    normalize_legacy_registry_for_migration,
)

LEGACY_NAMESPACE = ".hjc-code-harness"
COH_NAMESPACE = ".coh"
LEGACY_RECEIPT_NAMESPACE = f"{LEGACY_NAMESPACE}/receipts/"
JOURNAL_NAME = ".namespace-migration.json"
JOURNAL_SCHEMA_VERSION = 1
MAX_JOURNAL_BYTES = 16 * 1024
MIGRATION_ID_LENGTH = 32
SOURCE_NAMES = {"model": "model.json", "routes": "routes.json"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ContractError("DUPLICATE_JSON_KEY")
        payload[key] = value
    return payload


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


def _open_directory(path: Path) -> int:
    try:
        return os.open(path, _directory_flags())
    except OSError as exc:
        raise ContractError("MIGRATION_NAMESPACE_CHANGED") from exc


def _read_named_descriptor(
    directory_descriptor: int,
    name: str,
    maximum: int,
) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ContractError("MIGRATION_SOURCE_INVALID")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
    except FileNotFoundError as exc:
        raise ContractError("MIGRATION_SOURCE_MISSING") from exc
    except ContractError:
        raise
    except OSError as exc:
        raise ContractError("MIGRATION_SOURCE_INVALID") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        raise ContractError("MIGRATION_SOURCE_CHANGED")
    if len(data) > maximum:
        raise ContractError("FILE_TOO_LARGE")
    return data, after


def _namespace_path(root: Path, name: str) -> Path:
    return root / name


def _validate_namespace(path: Path, code: str) -> os.stat_result:
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ContractError(code) from exc
    if not stat.S_ISDIR(metadata.st_mode) or resolved != path:
        raise ContractError(code)
    return metadata


def _read_named_file(directory: Path, name: str, maximum: int) -> tuple[bytes, os.stat_result]:
    directory_descriptor = _open_directory(directory)
    try:
        return _read_named_descriptor(directory_descriptor, name, maximum)
    finally:
        os.close(directory_descriptor)


def _load_named_json(
    directory: Path,
    name: str,
    maximum: int,
) -> tuple[dict[str, Any], str]:
    data, _ = _read_named_file(directory, name, maximum)
    try:
        payload = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except UnicodeDecodeError as exc:
        raise ContractError("INVALID_UTF8") from exc
    except json.JSONDecodeError as exc:
        raise ContractError("INVALID_JSON") from exc
    if not isinstance(payload, dict):
        raise ContractError("JSON_ROOT_NOT_OBJECT")
    return payload, _sha256(data)


def _atomic_write(path: Path, data: bytes, *, create_only: bool) -> None:
    directory = path.parent
    temporary_name = f".{path.name}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    directory_descriptor = _open_directory(directory)
    try:
        descriptor = os.open(
            temporary_name,
            flags,
            0o600,
            dir_fd=directory_descriptor,
        )
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), 0o644)
        if create_only:
            try:
                os.link(
                    temporary_name,
                    path.name,
                    src_dir_fd=directory_descriptor,
                    dst_dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise ContractError("MIGRATION_TARGET_CHANGED") from exc
        else:
            os.replace(
                temporary_name,
                path.name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
            )
        os.fsync(directory_descriptor)
    except ContractError:
        raise
    except OSError as exc:
        raise ContractError("MIGRATION_WRITE_FAILED") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary_name, dir_fd=directory_descriptor)
        except OSError:
            pass
        os.close(directory_descriptor)


def _journal_bytes(payload: dict[str, Any]) -> bytes:
    data = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if len(data) > MAX_JOURNAL_BYTES:
        raise ContractError("MIGRATION_JOURNAL_INVALID")
    return data


def _validate_journal(payload: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "schema_version",
        "migration_id",
        "state",
        "source_kind",
        "source_sha256",
        "expected_model_sha256",
        "rewritten_path_count",
    }
    if set(payload) != expected:
        raise ContractError("MIGRATION_JOURNAL_INVALID")
    migration_id = payload["migration_id"]
    if (
        payload["schema_version"] != JOURNAL_SCHEMA_VERSION
        or not isinstance(migration_id, str)
        or len(migration_id) != MIGRATION_ID_LENGTH
        or any(character not in "0123456789abcdef" for character in migration_id)
        or payload["state"] not in {"PREPARED", "NAMESPACE_RENAMED"}
        or payload["source_kind"] not in SOURCE_NAMES
        or not isinstance(payload["source_sha256"], str)
        or len(payload["source_sha256"]) != 64
        or not isinstance(payload["expected_model_sha256"], str)
        or len(payload["expected_model_sha256"]) != 64
        or type(payload["rewritten_path_count"]) is not int
        or not 0 <= payload["rewritten_path_count"] <= 100_000
    ):
        raise ContractError("MIGRATION_JOURNAL_INVALID")
    return payload


def _load_journal(namespace: Path) -> dict[str, Any] | None:
    path = namespace / JOURNAL_NAME
    if not os.path.lexists(path):
        return None
    if path.is_symlink() or not path.is_file():
        raise ContractError("MIGRATION_JOURNAL_INVALID")
    payload, _ = _load_named_json(namespace, JOURNAL_NAME, MAX_JOURNAL_BYTES)
    return _validate_journal(payload)


def _rewrite_path(value: str) -> tuple[str, bool]:
    if value == LEGACY_NAMESPACE:
        return COH_NAMESPACE, True
    prefix = LEGACY_NAMESPACE + "/"
    if value.startswith(prefix):
        return COH_NAMESPACE + value[len(LEGACY_NAMESPACE) :], True
    return value, False


def _rewrite_list(values: list[str]) -> tuple[list[str], int]:
    rewritten: list[str] = []
    count = 0
    for value in values:
        item, changed = _rewrite_path(value)
        rewritten.append(item)
        count += int(changed)
    return rewritten, count


def _rewrite_reference(reference: dict[str, Any]) -> int:
    path, changed = _rewrite_path(reference["path"])
    reference["path"] = path
    return int(changed)


def rewrite_model_paths(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Rewrite only Model v1 fields whose schema declares repository paths."""

    model = copy.deepcopy(payload)
    count = 0
    for blocker in model["construction"]["blockers"]:
        blocker["paths"], changed = _rewrite_list(blocker.get("paths", []))
        count += changed
    for authority in model["authorities"]:
        count += _rewrite_reference(authority["ref"])
    for route in model["routes"]:
        route["path_prefixes"], changed = _rewrite_list(route["path_prefixes"])
        count += changed
    for sensor in model["sensors"]:
        if "receipt_path" in sensor:
            sensor["receipt_path"], changed = _rewrite_path(sensor["receipt_path"])
            count += int(changed)
        sensor["protected_paths"], changed = _rewrite_list(
            sensor.get("protected_paths", [])
        )
        count += changed
    return model, count


def rewrite_registry_paths(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Rewrite only normalized route-registry fields whose schema declares paths."""

    registry = copy.deepcopy(payload)
    count = 0
    for route in registry["routes"]:
        for field in ("path_prefixes", "agents_paths", "guide_paths"):
            route[field], changed = _rewrite_list(route[field])
            count += changed
        count += _rewrite_reference(route["fact_ref"])
    for validation in registry["validations"]:
        count += _rewrite_reference(validation["declaration_ref"])
        if validation.get("receipt_path") is not None:
            validation["receipt_path"], changed = _rewrite_path(
                validation["receipt_path"]
            )
            count += int(changed)
        validation["protected_paths"], changed = _rewrite_list(
            validation.get("protected_paths", [])
        )
        count += changed
    if "validation_by_id" in registry:
        registry["validation_by_id"] = {
            item["id"]: item for item in registry["validations"]
        }
    return registry, count


def _source_state(
    root: Path,
    namespace: Path,
    source_kind: str,
    migration_id: str | None = None,
) -> tuple[dict[str, Any], bytes, str, int]:
    source_name = SOURCE_NAMES[source_kind]
    backup_name = f".namespace-migration-{migration_id}-{source_name}" if migration_id else None
    source_path = namespace / source_name
    backup_path = namespace / backup_name if backup_name else None
    if backup_path is not None and os.path.lexists(backup_path):
        source_path = backup_path
    if source_kind == "model":
        payload, digest = _load_named_json(namespace, source_path.name, MAX_MODEL_BYTES)
        expected, rewritten_count = rewrite_model_paths(payload)
        if namespace.name == LEGACY_NAMESPACE:
            validate_model(root, payload, receipt_namespace=LEGACY_RECEIPT_NAMESPACE)
        else:
            validate_model(root, expected)
    else:
        raw, digest = _load_named_json(namespace, source_path.name, MAX_REGISTRY_BYTES)
        if namespace.name == LEGACY_NAMESPACE:
            registry = normalize_legacy_registry_for_migration(
                root,
                raw,
                receipt_namespace=LEGACY_RECEIPT_NAMESPACE,
            )
            rewritten_registry, rewritten_count = rewrite_registry_paths(registry)
        else:
            rewritten_raw, rewritten_count = rewrite_registry_paths(raw)
            rewritten_registry = normalize_legacy_registry_for_migration(
                root,
                rewritten_raw,
            )
        expected = convert_legacy_registry(rewritten_registry)
    output = _model_output_bytes(expected)
    return expected, output, digest, rewritten_count


def _detect_source(namespace: Path) -> str:
    declared = {
        kind: os.path.lexists(namespace / name) for kind, name in SOURCE_NAMES.items()
    }
    if all(declared.values()):
        raise ContractError("LEGACY_MODEL_ROUTES_CONFLICT")
    if not any(declared.values()):
        raise ContractError("LEGACY_MODEL_OR_ROUTES_MISSING")
    source_kind = next(kind for kind, present in declared.items() if present)
    path = namespace / SOURCE_NAMES[source_kind]
    if path.is_symlink() or not path.is_file():
        raise ContractError("MIGRATION_SOURCE_INVALID")
    return source_kind


def _assert_no_inflight_bootstrap(namespace: Path) -> None:
    if os.path.lexists(namespace / ".bootstrap"):
        raise ContractError("LEGACY_BOOTSTRAP_INCOMPLETE")


def _model_guard(path: Path, expected_digest: str) -> tuple[int, int, str]:
    data, metadata = _read_named_file(path.parent, path.name, MAX_MODEL_BYTES)
    digest = _sha256(data)
    if digest != expected_digest:
        raise ContractError("MIGRATION_TARGET_CHANGED")
    return metadata.st_dev, metadata.st_ino, digest


def _publish_model(namespace: Path, expected_bytes: bytes, expected_digest: str) -> None:
    model_path = namespace / "model.json"
    if os.path.lexists(model_path):
        data, _ = _read_named_file(namespace, "model.json", MAX_MODEL_BYTES)
        if _sha256(data) != expected_digest:
            raise ContractError("MIGRATION_TARGET_CHANGED")
        return
    _atomic_write(model_path, expected_bytes, create_only=True)


def _quarantine_source(
    namespace: Path,
    source_name: str,
    backup_name: str,
    source_digest: str,
) -> Path:
    source = namespace / source_name
    backup = namespace / backup_name
    if os.path.lexists(backup):
        data, _ = _read_named_file(namespace, backup_name, max(MAX_MODEL_BYTES, MAX_REGISTRY_BYTES))
        if _sha256(data) != source_digest:
            raise ContractError("MIGRATION_SOURCE_CHANGED")
        return backup
    directory_descriptor = _open_directory(namespace)
    try:
        data, _ = _read_named_descriptor(
            directory_descriptor,
            source_name,
            max(MAX_MODEL_BYTES, MAX_REGISTRY_BYTES),
        )
        if _sha256(data) != source_digest:
            raise ContractError("MIGRATION_SOURCE_CHANGED")
        os.rename(
            source_name,
            backup_name,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        os.fsync(directory_descriptor)
        data, _ = _read_named_descriptor(
            directory_descriptor,
            backup_name,
            max(MAX_MODEL_BYTES, MAX_REGISTRY_BYTES),
        )
        if _sha256(data) != source_digest:
            raise ContractError("MIGRATION_SOURCE_CHANGED")
    except ContractError:
        raise
    except OSError as exc:
        raise ContractError("MIGRATION_SOURCE_CHANGED") from exc
    finally:
        os.close(directory_descriptor)
    return backup


def _retire_backup(backup: Path, model_path: Path, guard: tuple[int, int, str]) -> None:
    directory_descriptor = _open_directory(backup.parent)
    try:
        model_data, model_metadata = _read_named_descriptor(
            directory_descriptor,
            model_path.name,
            MAX_MODEL_BYTES,
        )
        if (
            (model_metadata.st_dev, model_metadata.st_ino) != guard[:2]
            or _sha256(model_data) != guard[2]
        ):
            raise ContractError("MIGRATION_TARGET_CHANGED")
        os.unlink(backup.name, dir_fd=directory_descriptor)
        os.fsync(directory_descriptor)
    except ContractError:
        raise
    except OSError as exc:
        raise ContractError("MIGRATION_SOURCE_RETIRE_FAILED") from exc
    finally:
        os.close(directory_descriptor)


def _unlink_named(directory: Path, name: str, code: str) -> None:
    directory_descriptor = _open_directory(directory)
    try:
        os.unlink(name, dir_fd=directory_descriptor)
        os.fsync(directory_descriptor)
    except OSError as exc:
        raise ContractError(code) from exc
    finally:
        os.close(directory_descriptor)


def _finish_new_namespace(
    root: Path,
    namespace: Path,
    journal: dict[str, Any],
    *,
    recovered: bool,
) -> dict[str, Any]:
    _assert_no_inflight_bootstrap(namespace)
    source_kind = journal["source_kind"]
    source_name = SOURCE_NAMES[source_kind]
    backup_name = f".namespace-migration-{journal['migration_id']}-{source_name}"
    source = namespace / source_name
    backup = namespace / backup_name
    model_path = namespace / "model.json"

    expected_payload: dict[str, Any] | None = None
    expected_bytes: bytes | None = None
    if os.path.lexists(source) or os.path.lexists(backup):
        expected_payload, expected_bytes, digest, rewritten_count = _source_state(
            root,
            namespace,
            source_kind,
            journal["migration_id"],
        )
        if (
            digest != journal["source_sha256"]
            or _sha256(expected_bytes) != journal["expected_model_sha256"]
            or rewritten_count != journal["rewritten_path_count"]
        ):
            raise ContractError("MIGRATION_SOURCE_CHANGED")

    if source_kind == "model":
        if os.path.lexists(source) and not os.path.lexists(backup):
            _quarantine_source(
                namespace,
                source_name,
                backup_name,
                journal["source_sha256"],
            )
        if expected_bytes is None:
            if not os.path.lexists(model_path):
                raise ContractError("MIGRATION_SOURCE_MISSING")
        else:
            _publish_model(
                namespace,
                expected_bytes,
                journal["expected_model_sha256"],
            )
        guard = _model_guard(model_path, journal["expected_model_sha256"])
        if os.path.lexists(backup):
            _retire_backup(backup, model_path, guard)
    else:
        if expected_bytes is None and not os.path.lexists(model_path):
            raise ContractError("MIGRATION_SOURCE_MISSING")
        if expected_bytes is not None:
            _publish_model(
                namespace,
                expected_bytes,
                journal["expected_model_sha256"],
            )
        guard = _model_guard(model_path, journal["expected_model_sha256"])
        if os.path.lexists(source) and not os.path.lexists(backup):
            _quarantine_source(
                namespace,
                source_name,
                backup_name,
                journal["source_sha256"],
            )
        if os.path.lexists(backup):
            _retire_backup(backup, model_path, guard)

    payload, _ = _load_named_json(namespace, model_path.name, MAX_MODEL_BYTES)
    validate_model(root, payload)
    _model_guard(model_path, journal["expected_model_sha256"])
    _unlink_named(namespace, JOURNAL_NAME, "MIGRATION_JOURNAL_REMOVE_FAILED")
    return {
        "status": "RECOVERED" if recovered else "MIGRATED",
        "source_kind": source_kind,
        "rewritten_paths": journal["rewritten_path_count"],
        "invalidated_legacy_receipts": True,
    }


def migrate_repository(root: Path, *, write: bool) -> dict[str, Any]:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ContractError("REPOSITORY_INVALID")
    legacy = _namespace_path(root, LEGACY_NAMESPACE)
    target = _namespace_path(root, COH_NAMESPACE)
    legacy_declared = os.path.lexists(legacy)
    target_declared = os.path.lexists(target)

    if legacy_declared and target_declared:
        raise ContractError("COH_NAMESPACE_CONFLICT")
    if target_declared:
        _validate_namespace(target, "COH_NAMESPACE_INVALID")
        journal = _load_journal(target)
        if journal is None:
            raise ContractError("COH_NAMESPACE_ALREADY_EXISTS")
        if not write:
            return {
                "status": "RECOVERY_REQUIRED",
                "source_kind": journal["source_kind"],
                "rewritten_paths": journal["rewritten_path_count"],
                "invalidated_legacy_receipts": True,
            }
        return _finish_new_namespace(root, target, journal, recovered=True)
    if not legacy_declared:
        raise ContractError("LEGACY_NAMESPACE_MISSING")

    source_metadata = _validate_namespace(legacy, "LEGACY_NAMESPACE_INVALID")
    _assert_no_inflight_bootstrap(legacy)
    journal = _load_journal(legacy)
    recovered = journal is not None
    if journal is None:
        source_kind = _detect_source(legacy)
        expected, expected_bytes, source_digest, rewritten_count = _source_state(
            root,
            legacy,
            source_kind,
        )
        del expected
        journal = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "migration_id": secrets.token_hex(16),
            "state": "PREPARED",
            "source_kind": source_kind,
            "source_sha256": source_digest,
            "expected_model_sha256": _sha256(expected_bytes),
            "rewritten_path_count": rewritten_count,
        }
        if not write:
            return {
                "status": "WOULD_MIGRATE",
                "source_kind": source_kind,
                "rewritten_paths": rewritten_count,
                "invalidated_legacy_receipts": True,
            }
        _atomic_write(legacy / JOURNAL_NAME, _journal_bytes(journal), create_only=True)
    elif not write:
        return {
            "status": "RECOVERY_REQUIRED",
            "source_kind": journal["source_kind"],
            "rewritten_paths": journal["rewritten_path_count"],
            "invalidated_legacy_receipts": True,
        }

    _assert_no_inflight_bootstrap(legacy)
    current_metadata = _validate_namespace(legacy, "LEGACY_NAMESPACE_INVALID")
    if (source_metadata.st_dev, source_metadata.st_ino) != (
        current_metadata.st_dev,
        current_metadata.st_ino,
    ):
        raise ContractError("LEGACY_NAMESPACE_CHANGED")
    if os.path.lexists(target):
        raise ContractError("COH_NAMESPACE_CONFLICT")
    try:
        os.rename(legacy, target)
        _fsync_directory(root)
    except OSError as exc:
        raise ContractError("NAMESPACE_RENAME_FAILED") from exc
    moved_metadata = _validate_namespace(target, "COH_NAMESPACE_INVALID")
    if (moved_metadata.st_dev, moved_metadata.st_ino) != (
        source_metadata.st_dev,
        source_metadata.st_ino,
    ):
        raise ContractError("LEGACY_NAMESPACE_CHANGED")
    journal = {**journal, "state": "NAMESPACE_RENAMED"}
    _atomic_write(target / JOURNAL_NAME, _journal_bytes(journal), create_only=False)
    return _finish_new_namespace(root, target, journal, recovered=recovered)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", help="Repository root containing .hjc-code-harness")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Execute the recoverable one-way namespace migration",
    )
    parser.add_argument("--json", action="store_true", help="Emit one machine-readable result")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        root = Path(args.repository).expanduser().resolve(strict=True)
        result = {"ok": True, **migrate_repository(root, write=args.write)}
    except (OSError, ContractError) as exc:
        code = exc.code if isinstance(exc, ContractError) else "REPOSITORY_INVALID"
        result = {"ok": False, "code": code}
        if args.json:
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        else:
            print(f"FAIL: {code}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        print(f"PASS: {result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
