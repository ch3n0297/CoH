"""Strict, dependency-free validation for the canonical Harness Model v1."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

from coh_hook_common import (
    LEGACY_NAMESPACE_RELATIVE_PATH,
    MODEL_RELATIVE_PATH,
    PROOF_LAYERS,
    REGISTRY_RELATIVE_PATH,
    ContractError,
    _bounded_list,
    _exact_keys,
    _identifier,
    _path_contains_symlink,
    _reference,
    _repo_path,
    _repo_paths_overlap,
    _same_file_if_exists,
    load_json_object,
)

MODEL_SCHEMA_VERSION = 1
ROUTING_PROJECTION_VERSION = 2
MAX_MODEL_BYTES = 64 * 1024
MAX_AUTHORITIES = 2048
MAX_ROUTES = 64
MAX_SENSORS = 64

AUTHORITY_KINDS = {
    "agent-instructions",
    "guide",
    "fact",
    "validation-declaration",
}
ANCHORED_AUTHORITY_KINDS = {"fact", "validation-declaration"}
EVIDENCE_POLICIES = {"RECEIPT_REQUIRED", "NO_TRUSTED_RESULT"}
CONSTRUCTION_STATUSES = {"READY", "BLOCKED"}
BLOCKER_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _identifier_list(
    value: Any,
    minimum: int,
    maximum: int,
    *,
    list_code: str,
    item_code: str,
    duplicate_code: str,
) -> list[str]:
    normalized: list[str] = []
    for raw in _bounded_list(value, minimum, maximum, list_code):
        item = _identifier(raw, item_code)
        if item in normalized:
            raise ContractError(duplicate_code)
        normalized.append(item)
    return normalized


def _normalize_authority_ref(
    root: Path,
    value: Any,
    *,
    kind: str,
    ready: bool,
) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ContractError("AUTHORITY_REF")
    _exact_keys(value, {"path"}, {"anchor_token"}, "AUTHORITY_REF_FIELDS")

    relative, resolved = _repo_path(
        root,
        value["path"],
        code="AUTHORITY_PATH",
        must_exist=ready,
        must_be_file=ready,
    )
    if not ready and resolved.exists() and not resolved.is_file():
        raise ContractError("AUTHORITY_PATH")
    if kind == "agent-instructions" and PurePosixPath(relative).name != "AGENTS.md":
        raise ContractError("AGENT_AUTHORITY_PATH")

    anchor = value.get("anchor_token")
    if anchor is not None and kind not in ANCHORED_AUTHORITY_KINDS:
        raise ContractError("AUTHORITY_ANCHOR_NOT_ALLOWED")
    if anchor is None:
        if ready and kind in ANCHORED_AUTHORITY_KINDS:
            raise ContractError("AUTHORITY_ANCHOR_REQUIRED")
        return {"path": relative}
    if (
        not isinstance(anchor, str)
        or not 1 <= len(anchor) <= 160
        or any(ord(character) < 32 for character in anchor)
    ):
        raise ContractError("AUTHORITY_ANCHOR")
    if ready:
        return _reference(
            root,
            {"path": relative, "anchor_token": anchor},
            code="AUTHORITY_ANCHOR",
            require_anchor=True,
        )
    return {"path": relative, "anchor_token": anchor}


def _normalize_blockers(
    root: Path, value: Any, status: str, authority_ids: set[str]
) -> list[dict[str, Any]]:
    minimum = 0 if status == "READY" else 1
    maximum = 0 if status == "READY" else 32
    blockers: list[dict[str, Any]] = []
    codes: set[str] = set()
    for raw in _bounded_list(value, minimum, maximum, "CONSTRUCTION_BLOCKERS"):
        if not isinstance(raw, dict):
            raise ContractError("CONSTRUCTION_BLOCKER_OBJECT")
        _exact_keys(
            raw,
            {"code"},
            {"authority_ids", "paths"},
            "CONSTRUCTION_BLOCKER_FIELDS",
        )
        code = raw["code"]
        if not isinstance(code, str) or not BLOCKER_CODE.fullmatch(code):
            raise ContractError("CONSTRUCTION_BLOCKER_CODE")
        if code in codes:
            raise ContractError("DUPLICATE_CONSTRUCTION_BLOCKER")
        codes.add(code)
        referenced_authorities = _identifier_list(
            raw.get("authority_ids", []),
            0,
            16,
            list_code="CONSTRUCTION_BLOCKER_AUTHORITIES",
            item_code="CONSTRUCTION_BLOCKER_AUTHORITY_ID",
            duplicate_code="DUPLICATE_CONSTRUCTION_BLOCKER_AUTHORITY",
        )
        if any(item not in authority_ids for item in referenced_authorities):
            raise ContractError("UNKNOWN_CONSTRUCTION_BLOCKER_AUTHORITY")
        paths: list[str] = []
        for path_raw in _bounded_list(
            raw.get("paths", []), 0, 16, "CONSTRUCTION_BLOCKER_PATHS"
        ):
            path, _ = _repo_path(
                root,
                path_raw,
                code="CONSTRUCTION_BLOCKER_PATH",
                must_exist=False,
            )
            if path in paths:
                raise ContractError("DUPLICATE_CONSTRUCTION_BLOCKER_PATH")
            paths.append(path)
        blockers.append(
            {"code": code, "authority_ids": referenced_authorities, "paths": paths}
        )
    return blockers


def validate_model(
    root: Path,
    payload: dict[str, Any],
    *,
    receipt_namespace: str = ".coh/receipts/",
) -> dict[str, Any]:
    """Validate Model v1 against live repository state and return its routing projection."""

    root = root.resolve(strict=True)
    _exact_keys(
        payload,
        {
            "schema_version",
            "enabled",
            "construction",
            "authorities",
            "routes",
            "sensors",
            "maintenance",
        },
        set(),
        "MODEL_FIELDS",
    )
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != MODEL_SCHEMA_VERSION
    ):
        raise ContractError("MODEL_SCHEMA_VERSION")
    if not isinstance(payload["enabled"], bool):
        raise ContractError("MODEL_ENABLED")

    construction = payload["construction"]
    if not isinstance(construction, dict):
        raise ContractError("CONSTRUCTION_OBJECT")
    _exact_keys(
        construction,
        {"status", "blockers"},
        set(),
        "CONSTRUCTION_FIELDS",
    )
    status = construction["status"]
    if not isinstance(status, str) or status not in CONSTRUCTION_STATUSES:
        raise ContractError("CONSTRUCTION_STATUS")
    ready = status == "READY"

    authority_by_id: dict[str, dict[str, Any]] = {}
    authority_signatures: set[str] = set()
    for raw in _bounded_list(
        payload["authorities"], 0, MAX_AUTHORITIES, "MODEL_AUTHORITIES"
    ):
        if not isinstance(raw, dict):
            raise ContractError("AUTHORITY_OBJECT")
        _exact_keys(raw, {"id", "kind", "ref"}, set(), "AUTHORITY_FIELDS")
        authority_id = _identifier(raw["id"], "AUTHORITY_ID")
        if authority_id in authority_by_id:
            raise ContractError("DUPLICATE_AUTHORITY_ID")
        kind = raw["kind"]
        if not isinstance(kind, str) or kind not in AUTHORITY_KINDS:
            raise ContractError("AUTHORITY_KIND")
        reference = _normalize_authority_ref(root, raw["ref"], kind=kind, ready=ready)
        signature = json.dumps(
            {"kind": kind, "ref": reference},
            sort_keys=True,
            separators=(",", ":"),
        )
        if signature in authority_signatures:
            raise ContractError("DUPLICATE_AUTHORITY_REF")
        authority_signatures.add(signature)
        authority_by_id[authority_id] = {
            "id": authority_id,
            "kind": kind,
            "ref": reference,
        }

    blockers = _normalize_blockers(root, construction["blockers"], status, set(authority_by_id))
    blocker_authority_ids = {
        authority_id
        for blocker in blockers
        for authority_id in blocker["authority_ids"]
    }
    blocker_paths = {path for blocker in blockers for path in blocker["paths"]}
    if not ready:
        for authority_id, authority in authority_by_id.items():
            if (
                authority_id in blocker_authority_ids
                or authority["ref"]["path"] in blocker_paths
            ):
                continue
            authority["ref"] = _normalize_authority_ref(
                root,
                authority["ref"],
                kind=authority["kind"],
                ready=True,
            )

    sensors: list[dict[str, Any]] = []
    validation_by_id: dict[str, dict[str, Any]] = {}
    receipt_paths: set[str] = set()
    receipt_resolved_paths: list[Path] = []
    receipt_declarations: list[tuple[str, str, Path]] = []
    protected_declarations: list[tuple[str, str, Path]] = []
    for raw in _bounded_list(payload["sensors"], 0, MAX_SENSORS, "MODEL_SENSORS"):
        if not isinstance(raw, dict):
            raise ContractError("SENSOR_OBJECT")
        _exact_keys(
            raw,
            {"id", "declaration_authority_id", "proof_layer"},
            {"receipt_path", "protected_paths"},
            "SENSOR_FIELDS",
        )
        sensor_id = _identifier(raw["id"], "SENSOR_ID")
        if sensor_id in validation_by_id:
            raise ContractError("DUPLICATE_SENSOR_ID")
        declaration_authority_id = _identifier(
            raw["declaration_authority_id"], "SENSOR_DECLARATION_AUTHORITY_ID"
        )
        declaration = authority_by_id.get(declaration_authority_id)
        if declaration is None:
            raise ContractError("UNKNOWN_SENSOR_DECLARATION_AUTHORITY")
        if declaration["kind"] != "validation-declaration":
            raise ContractError("SENSOR_DECLARATION_AUTHORITY_KIND")
        proof_layer = raw["proof_layer"]
        if not isinstance(proof_layer, str) or proof_layer not in PROOF_LAYERS:
            raise ContractError("SENSOR_PROOF_LAYER")

        receipt_path: str | None = None
        receipt_resolved: Path | None = None
        if "receipt_path" in raw:
            receipt_path, receipt_resolved = _repo_path(
                root,
                raw["receipt_path"],
                code="SENSOR_RECEIPT_PATH",
                must_exist=False,
            )
            if not receipt_path.startswith(receipt_namespace):
                raise ContractError("SENSOR_RECEIPT_PATH")
            if _path_contains_symlink(
                root, receipt_path, code="SENSOR_RECEIPT_PATH"
            ):
                raise ContractError("SENSOR_RECEIPT_PATH")
            if receipt_resolved.exists():
                try:
                    receipt_metadata = receipt_resolved.stat()
                except OSError as exc:
                    raise ContractError("SENSOR_RECEIPT_PATH") from exc
                if not receipt_resolved.is_file() or receipt_metadata.st_nlink != 1:
                    raise ContractError("SENSOR_RECEIPT_PATH")
            if any(
                authority["ref"]["path"] == receipt_path
                or root.joinpath(
                    *PurePosixPath(authority["ref"]["path"]).parts
                ).resolve(strict=False)
                == receipt_resolved
                or _same_file_if_exists(
                    root.joinpath(
                        *PurePosixPath(authority["ref"]["path"]).parts
                    ).resolve(strict=False),
                    receipt_resolved,
                    code="SENSOR_RECEIPT_AUTHORITY_OVERLAP",
                )
                for authority in authority_by_id.values()
            ):
                raise ContractError("SENSOR_RECEIPT_AUTHORITY_OVERLAP")
            if receipt_path in receipt_paths or any(
                receipt_resolved == existing
                or _same_file_if_exists(
                    receipt_resolved,
                    existing,
                    code="DUPLICATE_SENSOR_RECEIPT_PATH",
                )
                for existing in receipt_resolved_paths
            ):
                raise ContractError("DUPLICATE_SENSOR_RECEIPT_PATH")
            receipt_paths.add(receipt_path)
            receipt_resolved_paths.append(receipt_resolved)
            receipt_declarations.append((sensor_id, receipt_path, receipt_resolved))

        protected_paths: list[str] = []
        for path_raw in _bounded_list(
            raw.get("protected_paths", []), 0, 16, "SENSOR_PROTECTED_PATHS"
        ):
            protected_path, protected_resolved = _repo_path(
                root,
                path_raw,
                code="SENSOR_PROTECTED_PATH",
                must_exist=False,
            )
            if _path_contains_symlink(
                root, protected_path, code="SENSOR_PROTECTED_PATH"
            ):
                raise ContractError("SENSOR_PROTECTED_PATH")
            if protected_path in protected_paths or (
                receipt_path is not None
                and receipt_resolved is not None
                and _repo_paths_overlap(
                    root,
                    protected_path,
                    protected_resolved,
                    receipt_path,
                    receipt_resolved,
                    code="SENSOR_PROTECTED_PATH",
                )
            ):
                raise ContractError("SENSOR_PROTECTED_PATH")
            protected_paths.append(protected_path)
            protected_declarations.append(
                (sensor_id, protected_path, protected_resolved)
            )

        normalized_sensor = {
            "id": sensor_id,
            "declaration_ref": declaration["ref"],
            "proof_layer": proof_layer,
            "receipt_path": receipt_path,
            "protected_paths": protected_paths,
        }
        sensors.append(normalized_sensor)
        validation_by_id[sensor_id] = normalized_sensor

    for receipt_owner, receipt_path, receipt_resolved in receipt_declarations:
        for protected_owner, protected_path, protected_resolved in protected_declarations:
            if receipt_owner == protected_owner:
                continue
            if _repo_paths_overlap(
                root,
                receipt_path,
                receipt_resolved,
                protected_path,
                protected_resolved,
                code="SENSOR_PROTECTED_PATH",
            ):
                raise ContractError("SENSOR_PROTECTED_PATH")

    routes: list[dict[str, Any]] = []
    route_ids: set[str] = set()
    all_tags: set[str] = set()
    owned_prefixes: list[str] = []
    for raw in _bounded_list(payload["routes"], 0, MAX_ROUTES, "MODEL_ROUTES"):
        if not isinstance(raw, dict):
            raise ContractError("ROUTE_OBJECT")
        _exact_keys(
            raw,
            {
                "id",
                "explicit_tags",
                "path_prefixes",
                "authorities",
                "sensor_id",
                "evidence_policy",
            },
            set(),
            "ROUTE_FIELDS",
        )
        route_id = _identifier(raw["id"], "ROUTE_ID")
        if route_id in route_ids:
            raise ContractError("DUPLICATE_ROUTE_ID")
        route_ids.add(route_id)

        tags: list[str] = []
        for tag_raw in _bounded_list(raw["explicit_tags"], 1, 8, "ROUTE_TAGS"):
            tag = _identifier(tag_raw, "ROUTE_TAG")
            if tag in tags or tag in all_tags:
                raise ContractError("DUPLICATE_ROUTE_TAG")
            tags.append(tag)
            all_tags.add(tag)

        prefixes: list[str] = []
        for prefix_raw in _bounded_list(raw["path_prefixes"], 0, 16, "ROUTE_PREFIXES"):
            prefix, _ = _repo_path(
                root,
                prefix_raw,
                code="ROUTE_PREFIX",
                must_exist=False,
            )
            if ready or prefix not in blocker_paths:
                prefix, _ = _repo_path(
                    root,
                    prefix,
                    code="ROUTE_PREFIX",
                    must_exist=True,
                )
            if prefix in prefixes:
                raise ContractError("DUPLICATE_ROUTE_PREFIX")
            if any(
                prefix == other
                or prefix.startswith(other + "/")
                or other.startswith(prefix + "/")
                for other in owned_prefixes
            ):
                raise ContractError("OVERLAPPING_ROUTE_PREFIX")
            prefixes.append(prefix)
            owned_prefixes.append(prefix)

        route_authorities = raw["authorities"]
        if not isinstance(route_authorities, dict):
            raise ContractError("ROUTE_AUTHORITIES_OBJECT")
        _exact_keys(
            route_authorities,
            {"agents", "guides", "facts"},
            set(),
            "ROUTE_AUTHORITIES_FIELDS",
        )
        minimum_required = 1 if ready else 0
        authority_groups: dict[str, list[str]] = {}
        expected_kinds = {
            "agents": "agent-instructions",
            "guides": "guide",
            "facts": "fact",
        }
        for group, expected_kind in expected_kinds.items():
            identifiers = _identifier_list(
                route_authorities[group],
                minimum_required if group != "facts" else 0,
                8,
                list_code=f"ROUTE_{group.upper()}_AUTHORITIES",
                item_code=f"ROUTE_{group.upper()}_AUTHORITY_ID",
                duplicate_code=f"DUPLICATE_ROUTE_{group.upper()}_AUTHORITY",
            )
            for authority_id in identifiers:
                authority = authority_by_id.get(authority_id)
                if authority is None:
                    raise ContractError(f"UNKNOWN_ROUTE_{group.upper()}_AUTHORITY")
                if authority["kind"] != expected_kind:
                    raise ContractError(f"ROUTE_{group.upper()}_AUTHORITY_KIND")
            authority_groups[group] = identifiers

        sensor_raw = raw["sensor_id"]
        if sensor_raw is None:
            sensor_id = None
        else:
            sensor_id = _identifier(sensor_raw, "ROUTE_SENSOR_ID")
            if sensor_id not in validation_by_id:
                raise ContractError("UNKNOWN_ROUTE_SENSOR")
        evidence_policy = raw["evidence_policy"]
        if not isinstance(evidence_policy, str) or evidence_policy not in EVIDENCE_POLICIES:
            raise ContractError("ROUTE_EVIDENCE_POLICY")
        if evidence_policy == "RECEIPT_REQUIRED":
            if sensor_id is None:
                raise ContractError("RECEIPT_POLICY_REQUIRES_SENSOR")
            if validation_by_id[sensor_id]["receipt_path"] is None:
                raise ContractError("RECEIPT_POLICY_REQUIRES_PATH")

        agents_paths = [authority_by_id[item]["ref"]["path"] for item in authority_groups["agents"]]
        guide_paths = [authority_by_id[item]["ref"]["path"] for item in authority_groups["guides"]]
        fact_refs = [authority_by_id[item]["ref"] for item in authority_groups["facts"]]
        normalized_route: dict[str, Any] = {
            "id": route_id,
            "explicit_tags": tags,
            "path_prefixes": prefixes,
            "agents_paths": agents_paths,
            "guide_paths": guide_paths,
            "fact_refs": fact_refs,
            "validation_id": sensor_id,
            "evidence_policy": evidence_policy,
        }
        if len(fact_refs) == 1:
            normalized_route["fact_ref"] = fact_refs[0]
        routes.append(normalized_route)

    maintenance = payload["maintenance"]
    if not isinstance(maintenance, dict):
        raise ContractError("MAINTENANCE_OBJECT")
    _exact_keys(
        maintenance,
        {"owner_authority_ids", "triggers"},
        set(),
        "MAINTENANCE_FIELDS",
    )
    owners = _identifier_list(
        maintenance["owner_authority_ids"],
        1 if ready else 0,
        8,
        list_code="MAINTENANCE_OWNERS",
        item_code="MAINTENANCE_OWNER_AUTHORITY_ID",
        duplicate_code="DUPLICATE_MAINTENANCE_OWNER",
    )
    if any(owner not in authority_by_id for owner in owners):
        raise ContractError("UNKNOWN_MAINTENANCE_OWNER")
    _identifier_list(
        maintenance["triggers"],
        1 if ready else 0,
        16,
        list_code="MAINTENANCE_TRIGGERS",
        item_code="MAINTENANCE_TRIGGER",
        duplicate_code="DUPLICATE_MAINTENANCE_TRIGGER",
    )

    if ready and not routes:
        raise ContractError("MODEL_EMPTY_WHEN_READY")

    if not payload["enabled"]:
        routes = []
        sensors = []
        validation_by_id = {}

    return {
        "schema_version": MODEL_SCHEMA_VERSION,
        "projection_version": ROUTING_PROJECTION_VERSION,
        "enabled": payload["enabled"],
        "runtime_eligible": payload["enabled"] and ready,
        "routes": routes,
        "validations": sensors,
        "validation_by_id": validation_by_id,
        "construction_status": status,
        "blockers": blockers,
        "source": "model",
    }


def routing_projection_sha256(projection: dict[str, Any]) -> str:
    """Hash only semantic runtime routing fields, never raw or construction-only state."""

    if not isinstance(projection, dict):
        raise ContractError("ROUTING_PROJECTION_INVALID")
    try:
        digest_payload = {
            "schema_version": projection["schema_version"],
            "projection_version": projection["projection_version"],
            "enabled": projection["enabled"],
            "runtime_eligible": projection["runtime_eligible"],
            "routes": projection["routes"],
            "validations": projection["validations"],
        }
        encoded = json.dumps(
            digest_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("ROUTING_PROJECTION_INVALID") from exc
    return hashlib.sha256(encoded).hexdigest()


def load_model(root: Path) -> tuple[dict[str, Any], str]:
    """Load Model v1 and return its normalized routing projection plus projection digest."""

    root = root.resolve(strict=True)
    if os.path.lexists(root / LEGACY_NAMESPACE_RELATIVE_PATH):
        raise ContractError("COH_NAMESPACE_CONFLICT")
    if os.path.lexists(root / REGISTRY_RELATIVE_PATH):
        raise ContractError("MODEL_LEGACY_CONFLICT")
    _, model_path = _repo_path(
        root,
        MODEL_RELATIVE_PATH,
        code="MODEL_PATH_INVALID",
        must_exist=True,
        must_be_file=True,
    )
    payload, _ = load_json_object(model_path, MAX_MODEL_BYTES)
    projection = validate_model(root, payload)
    return projection, routing_projection_sha256(projection)
