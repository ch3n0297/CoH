#!/usr/bin/env python3
"""One-way, fail-closed migration from legacy routes.json to canonical Model v1."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))

from harness_model import MAX_MODEL_BYTES, validate_model
from coh_hook_common import (
    MAX_REGISTRY_BYTES,
    MODEL_RELATIVE_PATH,
    PROOF_LAYERS,
    REGISTRY_RELATIVE_PATH,
    ContractError,
    _bounded_list,
    _exact_keys,
    _identifier,
    _reference,
    _repo_path,
    load_json_object,
    validate_registry,
)

MIGRATION_BLOCKER_CODE = "MAINTENANCE_POLICY_UNCONFIRMED"
LEGACY_BACKUP_DIRECTORY_PREFIX = ".routes-migration-"
LEGACY_BACKUP_FILE_NAME = "routes.json"
AUTHORITY_ID_PREFIX = {
    "agent-instructions": "agent",
    "guide": "guide",
    "fact": "fact",
    "validation-declaration": "validation",
}


def _canonical_bytes(payload: object, *, pretty: bool) -> bytes:
    if pretty:
        serialized = json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
    else:
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    return (serialized + "\n").encode("utf-8")


def _authority_id(kind: str, reference: dict[str, str]) -> str:
    material = _canonical_bytes({"kind": kind, "ref": reference}, pretty=False).rstrip(b"\n")
    digest = hashlib.sha256(material).hexdigest()[:24]
    return f"{AUTHORITY_ID_PREFIX[kind]}-{digest}"


def _model_output_bytes(payload: dict[str, Any]) -> bytes:
    pretty = _canonical_bytes(payload, pretty=True)
    if len(pretty) <= MAX_MODEL_BYTES:
        return pretty
    compact = _canonical_bytes(payload, pretty=False)
    if len(compact) <= MAX_MODEL_BYTES:
        return compact
    raise ContractError("FILE_TOO_LARGE")


def convert_legacy_registry(registry: dict[str, Any]) -> dict[str, Any]:
    """Convert one already-normalized legacy registry without inventing ownership."""

    authorities_by_signature: dict[str, dict[str, Any]] = {}
    authorities_by_id: dict[str, dict[str, Any]] = {}

    def register(kind: str, reference: dict[str, str]) -> str:
        normalized_reference = dict(reference)
        signature = json.dumps(
            {"kind": kind, "ref": normalized_reference},
            sort_keys=True,
            separators=(",", ":"),
        )
        existing = authorities_by_signature.get(signature)
        if existing is not None:
            return existing["id"]
        authority_id = _authority_id(kind, normalized_reference)
        authority = {"id": authority_id, "kind": kind, "ref": normalized_reference}
        collision = authorities_by_id.get(authority_id)
        if collision is not None and collision != authority:
            raise ContractError("MIGRATION_AUTHORITY_ID_COLLISION")
        authorities_by_signature[signature] = authority
        authorities_by_id[authority_id] = authority
        return authority_id

    sensors: list[dict[str, Any]] = []
    receipt_by_sensor_id: dict[str, str | None] = {}
    for validation in registry["validations"]:
        declaration_id = register(
            "validation-declaration", validation["declaration_ref"]
        )
        receipt_path = validation.get("receipt_path")
        receipt_by_sensor_id[validation["id"]] = receipt_path
        sensor: dict[str, Any] = {
            "id": validation["id"],
            "declaration_authority_id": declaration_id,
            "proof_layer": validation["proof_layer"],
            "protected_paths": list(validation.get("protected_paths", [])),
        }
        if receipt_path is not None:
            sensor["receipt_path"] = receipt_path
        sensors.append(sensor)

    routes: list[dict[str, Any]] = []
    for route in registry["routes"]:
        agent_ids = [
            register("agent-instructions", {"path": path})
            for path in route["agents_paths"]
        ]
        guide_ids = [register("guide", {"path": path}) for path in route["guide_paths"]]
        fact_ids = [register("fact", route["fact_ref"])]
        sensor_id = route["validation_id"]
        routes.append(
            {
                "id": route["id"],
                "explicit_tags": list(route["explicit_tags"]),
                "path_prefixes": list(route["path_prefixes"]),
                "authorities": {
                    "agents": agent_ids,
                    "guides": guide_ids,
                    "facts": fact_ids,
                },
                "sensor_id": sensor_id,
                "evidence_policy": (
                    "RECEIPT_REQUIRED"
                    if receipt_by_sensor_id[sensor_id] is not None
                    else "NO_TRUSTED_RESULT"
                ),
            }
        )

    return {
        "schema_version": 1,
        "enabled": registry["enabled"],
        "construction": {
            "status": "BLOCKED",
            "blockers": [
                {
                    "code": MIGRATION_BLOCKER_CODE,
                    "authority_ids": [],
                    "paths": [],
                }
            ],
        },
        "authorities": sorted(authorities_by_id.values(), key=lambda item: item["id"]),
        "routes": routes,
        "sensors": sensors,
        "maintenance": {"owner_authority_ids": [], "triggers": []},
    }


def _normalize_validation_only_legacy(
    root: Path,
    raw_validations: list[Any],
    *,
    receipt_namespace: str = ".coh/receipts/",
) -> list[dict[str, Any]]:
    """Validate dormant validation declarations when a disabled registry has no routes."""

    validations: list[dict[str, Any]] = []
    validation_ids: set[str] = set()
    for raw in raw_validations:
        if not isinstance(raw, dict):
            raise ContractError("VALIDATION_OBJECT")
        _exact_keys(
            raw,
            {"id", "declaration_ref", "proof_layer"},
            {"receipt_path", "protected_paths"},
            "VALIDATION_FIELDS",
        )
        validation_id = _identifier(raw["id"], "VALIDATION_ID")
        if validation_id in validation_ids:
            raise ContractError("DUPLICATE_VALIDATION_ID")
        validation_ids.add(validation_id)
        declaration = _reference(
            root,
            raw["declaration_ref"],
            code="VALIDATION_DECLARATION",
            require_anchor=True,
        )
        proof_layer = raw["proof_layer"]
        if not isinstance(proof_layer, str) or proof_layer not in PROOF_LAYERS:
            raise ContractError("VALIDATION_PROOF_LAYER")
        receipt_path: str | None = None
        if "receipt_path" in raw:
            receipt_path, receipt_resolved = _repo_path(
                root,
                raw["receipt_path"],
                code="VALIDATION_RECEIPT_PATH",
                must_exist=False,
            )
            if not receipt_path.startswith(receipt_namespace):
                raise ContractError("VALIDATION_RECEIPT_PATH")
            if receipt_resolved.exists() and not receipt_resolved.is_file():
                raise ContractError("VALIDATION_RECEIPT_PATH")
        protected_paths: list[str] = []
        for path_raw in _bounded_list(
            raw.get("protected_paths", []), 0, 16, "VALIDATION_PROTECTED_PATHS"
        ):
            protected_path, _ = _repo_path(
                root,
                path_raw,
                code="VALIDATION_PROTECTED_PATH",
                must_exist=False,
            )
            if protected_path in protected_paths or protected_path == receipt_path:
                raise ContractError("VALIDATION_PROTECTED_PATH")
            protected_paths.append(protected_path)
        validations.append(
            {
                "id": validation_id,
                "declaration_ref": declaration,
                "proof_layer": proof_layer,
                "receipt_path": receipt_path,
                "protected_paths": protected_paths,
            }
        )
    return validations


def _load_legacy_for_migration(
    root: Path,
    path: Path,
    *,
    receipt_namespace: str = ".coh/receipts/",
) -> tuple[dict[str, Any], str]:
    """Load raw legacy content so disabled dormant declarations are never discarded."""

    raw, digest = load_json_object(path, MAX_REGISTRY_BYTES)
    return (
        normalize_legacy_registry_for_migration(
            root,
            raw,
            receipt_namespace=receipt_namespace,
        ),
        digest,
    )


def normalize_legacy_registry_for_migration(
    root: Path,
    raw: dict[str, Any],
    *,
    receipt_namespace: str = ".coh/receipts/",
) -> dict[str, Any]:
    """Normalize raw legacy content without discarding disabled declarations."""

    if type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
        raise ContractError("REGISTRY_SCHEMA_VERSION")
    normalized = validate_registry(root, raw, receipt_namespace=receipt_namespace)
    if raw["enabled"]:
        return normalized

    raw_routes = raw["routes"]
    raw_validations = raw["validations"]
    if raw_routes:
        enabled_copy = dict(raw)
        enabled_copy["enabled"] = True
        normalized = validate_registry(
            root,
            enabled_copy,
            receipt_namespace=receipt_namespace,
        )
        normalized["enabled"] = False
        return normalized
    if raw_validations:
        normalized["validations"] = _normalize_validation_only_legacy(
            root,
            raw_validations,
            receipt_namespace=receipt_namespace,
        )
        normalized["validation_by_id"] = {
            item["id"]: item for item in normalized["validations"]
        }
    return normalized


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_create_model(path: Path, payload: dict[str, Any]) -> tuple[int, int, str]:
    data = _model_output_bytes(payload)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".model.json.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o644)
        try:
            os.link(temporary_path, path)
        except FileExistsError as exc:
            raise ContractError("MODEL_LEGACY_CONFLICT") from exc
        except OSError as exc:
            raise ContractError("MODEL_WRITE_FAILED") from exc
        _fsync_directory(path.parent)
        try:
            owned = temporary_path.stat()
        except OSError as exc:
            raise ContractError("MODEL_WRITE_FAILED") from exc
        return owned.st_dev, owned.st_ino, hashlib.sha256(data).hexdigest()
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _restore_legacy_backup(backup: Path, path: Path) -> None:
    try:
        os.link(backup, path)
    except FileExistsError as exc:
        raise ContractError("LEGACY_CHANGED_DURING_MIGRATION") from exc
    except OSError as exc:
        raise ContractError("LEGACY_RESTORE_FAILED") from exc
    try:
        backup.unlink()
        _fsync_directory(path.parent)
    except OSError as exc:
        raise ContractError("LEGACY_RESTORE_FAILED") from exc


def _remove_backup_reservation(reservation: Path) -> None:
    try:
        reservation.rmdir()
        _fsync_directory(reservation.parent)
    except OSError as exc:
        raise ContractError("LEGACY_REMOVE_FAILED") from exc


def _finish_interrupted_legacy_restore(backup: Path, live: Path) -> None:
    """Collapse the one provable crash state left by restore's link/unlink pair."""

    try:
        if not os.path.samefile(backup, live):
            raise ContractError("LEGACY_MIGRATION_BACKUP_CONFLICT")
        backup.unlink()
        _fsync_directory(backup.parent)
    except ContractError:
        raise
    except OSError as exc:
        raise ContractError("LEGACY_MIGRATION_BACKUP_CONFLICT") from exc
    _remove_backup_reservation(backup.parent)


def _delete_verified_backup(path: Path, expected_digest: str) -> None:
    try:
        current_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ContractError("LEGACY_CHANGED_DURING_MIGRATION") from exc
    if current_digest != expected_digest:
        raise ContractError("LEGACY_CHANGED_DURING_MIGRATION")
    try:
        path.unlink()
        _fsync_directory(path.parent)
    except OSError as exc:
        raise ContractError("LEGACY_REMOVE_FAILED") from exc


def _snapshot_model_guard(
    path: Path, expected_payload: dict[str, Any]
) -> tuple[int, int, str]:
    try:
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
        payload = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("MODEL_CHANGED_DURING_MIGRATION") from exc
    if (
        path.is_symlink()
        or not path.is_file()
        or len(data) > MAX_MODEL_BYTES
        or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
        or payload != expected_payload
    ):
        raise ContractError("MODEL_CHANGED_DURING_MIGRATION")
    return after.st_dev, after.st_ino, hashlib.sha256(data).hexdigest()


def _model_matches_guard(path: Path, guard: tuple[int, int, str]) -> bool:
    try:
        if path.is_symlink() or not path.is_file():
            return False
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
    except OSError:
        return False
    return (
        len(data) <= MAX_MODEL_BYTES
        and (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
        and (after.st_dev, after.st_ino) == guard[:2]
        and hashlib.sha256(data).hexdigest() == guard[2]
    )


def _remove_legacy(
    path: Path,
    expected_digest: str,
    *,
    model_path: Path,
    model_guard: tuple[int, int, str],
) -> None:
    try:
        reservation = Path(
            tempfile.mkdtemp(prefix=LEGACY_BACKUP_DIRECTORY_PREFIX, dir=path.parent)
        )
    except OSError as exc:
        raise ContractError("LEGACY_REMOVE_FAILED") from exc
    backup = reservation / LEGACY_BACKUP_FILE_NAME
    try:
        os.rename(path, backup)
    except OSError as exc:
        _remove_backup_reservation(reservation)
        raise ContractError("LEGACY_CHANGED_DURING_MIGRATION") from exc
    try:
        current_digest = hashlib.sha256(backup.read_bytes()).hexdigest()
        if current_digest != expected_digest:
            raise ContractError("LEGACY_CHANGED_DURING_MIGRATION")
        if not _model_matches_guard(model_path, model_guard):
            raise ContractError("MODEL_CHANGED_DURING_MIGRATION")
        _delete_verified_backup(backup, expected_digest)
    except ContractError:
        _restore_legacy_backup(backup, path)
        _remove_backup_reservation(reservation)
        raise
    _remove_backup_reservation(reservation)


def _discover_legacy_backup(root: Path) -> tuple[Path | None, list[Path]]:
    backups: list[Path] = []
    empty_reservations: list[Path] = []
    try:
        candidates = sorted(root.glob(f"{LEGACY_BACKUP_DIRECTORY_PREFIX}*"))
    except OSError as exc:
        raise ContractError("LEGACY_MIGRATION_BACKUP_CONFLICT") from exc
    for reservation in candidates:
        if reservation.is_symlink() or not reservation.is_dir():
            raise ContractError("LEGACY_MIGRATION_BACKUP_CONFLICT")
        try:
            entries = list(reservation.iterdir())
        except OSError as exc:
            raise ContractError("LEGACY_MIGRATION_BACKUP_CONFLICT") from exc
        if not entries:
            empty_reservations.append(reservation)
            continue
        if (
            len(entries) != 1
            or entries[0].name != LEGACY_BACKUP_FILE_NAME
            or entries[0].is_symlink()
            or not entries[0].is_file()
        ):
            raise ContractError("LEGACY_MIGRATION_BACKUP_CONFLICT")
        backups.append(entries[0])
    if len(backups) > 1 or (backups and empty_reservations):
        raise ContractError("LEGACY_MIGRATION_BACKUP_CONFLICT")
    return (backups[0] if backups else None), empty_reservations


def migrate_repository(root: Path, *, write: bool) -> dict[str, Any]:
    """Plan or execute the single supported routes.json -> model.json transaction."""

    root = root.resolve(strict=True)
    model_path = root / MODEL_RELATIVE_PATH
    legacy_path = root / REGISTRY_RELATIVE_PATH
    harness_directory = legacy_path.parent
    if not os.path.lexists(harness_directory):
        raise ContractError("LEGACY_ROUTES_MISSING")
    if harness_directory.is_symlink() or not harness_directory.is_dir():
        raise ContractError("HARNESS_DIRECTORY_INVALID")
    try:
        resolved_harness_directory = harness_directory.resolve(strict=True)
        resolved_harness_directory.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ContractError("HARNESS_DIRECTORY_INVALID") from exc
    if resolved_harness_directory != harness_directory:
        raise ContractError("HARNESS_DIRECTORY_INVALID")
    if os.path.lexists(model_path) and (model_path.is_symlink() or not model_path.is_file()):
        raise ContractError("MODEL_PATH_INVALID")
    if os.path.lexists(legacy_path) and (
        legacy_path.is_symlink() or not legacy_path.is_file()
    ):
        raise ContractError("REGISTRY_PATH_INVALID")

    legacy_backup_path, empty_reservations = _discover_legacy_backup(harness_directory)
    if empty_reservations:
        if not write:
            raise ContractError("LEGACY_MIGRATION_BACKUP_CONFLICT")
        for reservation in empty_reservations:
            _remove_backup_reservation(reservation)
    model_exists = model_path.is_file()
    legacy_exists = legacy_path.is_file()
    backup_exists = legacy_backup_path is not None
    if backup_exists and legacy_exists:
        if not write:
            raise ContractError("LEGACY_MIGRATION_BACKUP_CONFLICT")
        assert legacy_backup_path is not None
        _finish_interrupted_legacy_restore(legacy_backup_path, legacy_path)
        legacy_backup_path = None
        backup_exists = False
    if backup_exists and not model_exists:
        raise ContractError("LEGACY_MIGRATION_BACKUP_CONFLICT")
    if model_exists and not legacy_exists and not backup_exists:
        payload, _ = load_json_object(model_path, MAX_MODEL_BYTES)
        validate_model(root, payload)
        return {"status": "NO_CHANGES", "wrote_model": False, "removed_legacy": False}
    if not legacy_exists and not backup_exists:
        raise ContractError("LEGACY_ROUTES_MISSING")

    legacy_source = legacy_backup_path if legacy_backup_path is not None else legacy_path
    legacy_registry, legacy_digest = _load_legacy_for_migration(root, legacy_source)
    expected_model = convert_legacy_registry(legacy_registry)
    validate_model(root, expected_model)
    _model_output_bytes(expected_model)

    if model_exists:
        existing_model, _ = load_json_object(model_path, MAX_MODEL_BYTES)
        if existing_model != expected_model:
            raise ContractError("MODEL_LEGACY_CONFLICT")
        model_guard = _snapshot_model_guard(model_path, expected_model)
        if not write:
            return {
                "status": "RECOVERY_REQUIRED",
                "wrote_model": False,
                "removed_legacy": False,
            }
        if backup_exists:
            assert legacy_backup_path is not None
            if not _model_matches_guard(model_path, model_guard):
                _restore_legacy_backup(legacy_backup_path, legacy_path)
                _remove_backup_reservation(legacy_backup_path.parent)
                raise ContractError("MODEL_CHANGED_DURING_MIGRATION")
            _delete_verified_backup(legacy_backup_path, legacy_digest)
            _remove_backup_reservation(legacy_backup_path.parent)
        else:
            _remove_legacy(
                legacy_path,
                legacy_digest,
                model_path=model_path,
                model_guard=model_guard,
            )
        return {"status": "RECOVERED", "wrote_model": False, "removed_legacy": True}

    if not write:
        return {
            "status": "WOULD_MIGRATE",
            "wrote_model": False,
            "removed_legacy": False,
        }

    model_guard = _atomic_create_model(model_path, expected_model)
    _remove_legacy(
        legacy_path,
        legacy_digest,
        model_path=model_path,
        model_guard=model_guard,
    )
    return {"status": "MIGRATED", "wrote_model": True, "removed_legacy": True}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "repository", help="Repository root containing legacy .coh/routes.json"
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Atomically create model.json and then remove routes.json",
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
