"""Shared, dependency-free contracts for CoH lifecycle hooks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

NAMESPACE_RELATIVE_PATH = ".coh"
LEGACY_NAMESPACE_RELATIVE_PATH = ".hjc-code-harness"
MODEL_RELATIVE_PATH = f"{NAMESPACE_RELATIVE_PATH}/model.json"
REGISTRY_RELATIVE_PATH = f"{NAMESPACE_RELATIVE_PATH}/routes.json"
RECEIPT_NAMESPACE = f"{NAMESPACE_RELATIVE_PATH}/receipts/"
REGISTRY_SCHEMA_VERSION = 1
RECEIPT_SCHEMA_VERSION = 1
MAX_REGISTRY_BYTES = 64 * 1024
MAX_RECEIPT_BYTES = 32 * 1024
MAX_REFERENCED_FILE_BYTES = 2 * 1024 * 1024
MAX_EVIDENCE_FILE_BYTES = 10 * 1024 * 1024
MAX_WORKTREE_FILES = 512
MAX_WORKTREE_BYTES = 20 * 1024 * 1024
MAX_GIT_PATH_OUTPUT_BYTES = 256 * 1024
MAX_PROMPT_CHARS = 64 * 1024

IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
RUN_NONCE = re.compile(r"^[0-9a-f]{32}$")
EXPLICIT_ROUTE_TAG = re.compile(r"\[route:([a-z0-9][a-z0-9._-]{0,63})\]")

PROOF_LAYERS = {
    "static",
    "runtime",
    "browser",
    "live-provider",
    "production",
    "human-review",
}
OBSERVATION_KINDS = {"test", "error", "semantic", "authority"}
OBSERVATION_STATUSES = {"observed", "resolved", "regression"}
OBSERVATION_OUTCOMES = {"pass", "fail", "unknown"}
STRUCTURED_OBSERVATION_KINDS = {"semantic", "authority"}


class ContractError(ValueError):
    """A bounded, machine-readable Harness Model or receipt contract failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def load_json_object(path: Path, maximum_bytes: int) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise ContractError("FILE_MISSING") from exc
    except OSError as exc:
        raise ContractError("FILE_UNREADABLE") from exc
    if len(raw) > maximum_bytes:
        raise ContractError("FILE_TOO_LARGE")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except UnicodeDecodeError as exc:
        raise ContractError("INVALID_UTF8") from exc
    except json.JSONDecodeError as exc:
        raise ContractError("INVALID_JSON") from exc
    if not isinstance(payload, dict):
        raise ContractError("JSON_ROOT_NOT_OBJECT")
    return payload, hashlib.sha256(raw).hexdigest()


def _exact_keys(
    payload: dict[str, Any], required: set[str], optional: set[str], code: str
) -> None:
    keys = set(payload)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        raise ContractError(code)


def _identifier(value: Any, code: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ContractError(code)
    return value


def _bounded_list(value: Any, minimum: int, maximum: int, code: str) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ContractError(code)
    return value


def _repo_path(
    root: Path,
    value: Any,
    *,
    code: str,
    must_exist: bool,
    must_be_file: bool = False,
) -> tuple[str, Path]:
    if not isinstance(value, str) or not value or len(value) > 240:
        raise ContractError(code)
    if "\\" in value or any(ord(character) < 32 for character in value):
        raise ContractError(code)
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ContractError(code)
    normalized = pure.as_posix()
    candidate = root.joinpath(*pure.parts)
    try:
        resolved = candidate.resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        raise ContractError(code) from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ContractError(code) from exc
    if must_exist and not resolved.exists():
        raise ContractError(code)
    if must_be_file and not resolved.is_file():
        raise ContractError(code)
    return normalized, resolved


def _path_contains_symlink(root: Path, relative: str, *, code: str) -> bool:
    candidate = root
    for part in PurePosixPath(relative).parts:
        candidate = candidate / part
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise ContractError(code) from exc
        if stat.S_ISLNK(metadata.st_mode):
            return True
    return False


def _paths_overlap(first: str, second: str) -> bool:
    return (
        first == second
        or first.startswith(second + "/")
        or second.startswith(first + "/")
    )


def _same_file_if_exists(first: Path, second: Path, *, code: str) -> bool:
    try:
        return first.exists() and second.exists() and os.path.samefile(first, second)
    except OSError as exc:
        raise ContractError(code) from exc


def _repo_paths_overlap(
    root: Path,
    first_relative: str,
    first_resolved: Path,
    second_relative: str,
    second_resolved: Path,
    *,
    code: str,
) -> bool:
    """Compare two declared repository paths lexically and by live identity."""

    try:
        first_canonical = first_resolved.relative_to(root).as_posix()
        second_canonical = second_resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ContractError(code) from exc
    return (
        _paths_overlap(first_relative, second_relative)
        or _paths_overlap(first_canonical, second_canonical)
        or _same_file_if_exists(first_resolved, second_resolved, code=code)
    )


def _reference(
    root: Path, value: Any, *, code: str, require_anchor: bool
) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ContractError(code)
    _exact_keys(value, {"path", "anchor_token"}, set(), code)
    relative, resolved = _repo_path(
        root, value["path"], code=code, must_exist=True, must_be_file=True
    )
    anchor = value["anchor_token"]
    if (
        not isinstance(anchor, str)
        or not 1 <= len(anchor) <= 160
        or any(ord(character) < 32 for character in anchor)
    ):
        raise ContractError(code)
    if require_anchor:
        try:
            if resolved.stat().st_size > MAX_REFERENCED_FILE_BYTES:
                raise ContractError(code)
            text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ContractError(code) from exc
        if anchor not in text:
            raise ContractError(code)
    return {"path": relative, "anchor_token": anchor}


def validate_registry(
    root: Path,
    payload: dict[str, Any],
    *,
    receipt_namespace: str = RECEIPT_NAMESPACE,
) -> dict[str, Any]:
    """Validate and normalize a strict routes.json payload against live files."""

    root = root.resolve(strict=True)
    _exact_keys(payload, {"schema_version", "enabled", "routes", "validations"}, set(), "REGISTRY_FIELDS")
    if payload["schema_version"] != REGISTRY_SCHEMA_VERSION:
        raise ContractError("REGISTRY_SCHEMA_VERSION")
    if not isinstance(payload["enabled"], bool):
        raise ContractError("REGISTRY_ENABLED")
    routes_raw = _bounded_list(payload["routes"], 0, 64, "REGISTRY_ROUTES")
    validations_raw = _bounded_list(payload["validations"], 0, 64, "REGISTRY_VALIDATIONS")
    if not payload["enabled"]:
        return {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "enabled": False,
            "routes": [],
            "validations": [],
            "validation_by_id": {},
        }
    if not routes_raw or not validations_raw:
        raise ContractError("REGISTRY_EMPTY_WHEN_ENABLED")

    validations: list[dict[str, Any]] = []
    validation_by_id: dict[str, dict[str, Any]] = {}
    receipt_paths: set[str] = set()
    receipt_resolved_paths: list[Path] = []
    receipt_declarations: list[tuple[str, str, Path]] = []
    protected_declarations: list[tuple[str, str, Path]] = []
    for raw in validations_raw:
        if not isinstance(raw, dict):
            raise ContractError("VALIDATION_OBJECT")
        _exact_keys(
            raw,
            {"id", "declaration_ref", "proof_layer"},
            {"receipt_path", "protected_paths"},
            "VALIDATION_FIELDS",
        )
        validation_id = _identifier(raw["id"], "VALIDATION_ID")
        if validation_id in validation_by_id:
            raise ContractError("DUPLICATE_VALIDATION_ID")
        declaration = _reference(
            root, raw["declaration_ref"], code="VALIDATION_DECLARATION", require_anchor=True
        )
        proof_layer = raw["proof_layer"]
        if proof_layer not in PROOF_LAYERS:
            raise ContractError("VALIDATION_PROOF_LAYER")
        receipt_path: str | None = None
        receipt_resolved: Path | None = None
        if "receipt_path" in raw:
            receipt_path, receipt_resolved = _repo_path(
                root,
                raw["receipt_path"],
                code="VALIDATION_RECEIPT_PATH",
                must_exist=False,
            )
            if not receipt_path.startswith(receipt_namespace):
                raise ContractError("VALIDATION_RECEIPT_PATH")
            if _path_contains_symlink(
                root, receipt_path, code="VALIDATION_RECEIPT_PATH"
            ):
                raise ContractError("VALIDATION_RECEIPT_PATH")
            if receipt_resolved.exists():
                try:
                    receipt_metadata = receipt_resolved.stat()
                except OSError as exc:
                    raise ContractError("VALIDATION_RECEIPT_PATH") from exc
                if (
                    not stat.S_ISREG(receipt_metadata.st_mode)
                    or receipt_metadata.st_nlink != 1
                ):
                    raise ContractError("VALIDATION_RECEIPT_PATH")
            declaration_resolved = root.joinpath(
                *PurePosixPath(declaration["path"]).parts
            ).resolve(strict=False)
            if (
                receipt_path == declaration["path"]
                or receipt_resolved == declaration_resolved
                or _same_file_if_exists(
                    receipt_resolved,
                    declaration_resolved,
                    code="VALIDATION_RECEIPT_AUTHORITY_OVERLAP",
                )
            ):
                raise ContractError("VALIDATION_RECEIPT_AUTHORITY_OVERLAP")
            if receipt_path in receipt_paths or any(
                receipt_resolved == existing
                or _same_file_if_exists(
                    receipt_resolved,
                    existing,
                    code="DUPLICATE_VALIDATION_RECEIPT_PATH",
                )
                for existing in receipt_resolved_paths
            ):
                raise ContractError("DUPLICATE_VALIDATION_RECEIPT_PATH")
            receipt_paths.add(receipt_path)
            receipt_resolved_paths.append(receipt_resolved)
            receipt_declarations.append(
                (validation_id, receipt_path, receipt_resolved)
            )
        protected_paths: list[str] = []
        for path_raw in _bounded_list(
            raw.get("protected_paths", []), 0, 16, "VALIDATION_PROTECTED_PATHS"
        ):
            protected_path, protected_resolved = _repo_path(
                root,
                path_raw,
                code="VALIDATION_PROTECTED_PATH",
                must_exist=False,
            )
            if _path_contains_symlink(
                root, protected_path, code="VALIDATION_PROTECTED_PATH"
            ):
                raise ContractError("VALIDATION_PROTECTED_PATH")
            if protected_path in protected_paths or (
                receipt_path is not None
                and receipt_resolved is not None
                and _repo_paths_overlap(
                    root,
                    protected_path,
                    protected_resolved,
                    receipt_path,
                    receipt_resolved,
                    code="VALIDATION_PROTECTED_PATH",
                )
            ):
                raise ContractError("VALIDATION_PROTECTED_PATH")
            protected_paths.append(protected_path)
            protected_declarations.append(
                (validation_id, protected_path, protected_resolved)
            )
        normalized = {
            "id": validation_id,
            "declaration_ref": declaration,
            "proof_layer": proof_layer,
            "receipt_path": receipt_path,
            "protected_paths": protected_paths,
        }
        validations.append(normalized)
        validation_by_id[validation_id] = normalized

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
                code="VALIDATION_PROTECTED_PATH",
            ):
                raise ContractError("VALIDATION_PROTECTED_PATH")

    routes: list[dict[str, Any]] = []
    route_ids: set[str] = set()
    all_tags: set[str] = set()
    owned_prefixes: list[tuple[str, str]] = []
    for raw in routes_raw:
        if not isinstance(raw, dict):
            raise ContractError("ROUTE_OBJECT")
        _exact_keys(
            raw,
            {
                "id",
                "explicit_tags",
                "path_prefixes",
                "agents_paths",
                "guide_paths",
                "fact_ref",
                "validation_id",
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
            if tag in all_tags or tag in tags:
                raise ContractError("DUPLICATE_ROUTE_TAG")
            tags.append(tag)
            all_tags.add(tag)

        prefixes: list[str] = []
        for prefix_raw in _bounded_list(raw["path_prefixes"], 0, 16, "ROUTE_PREFIXES"):
            prefix, _ = _repo_path(
                root, prefix_raw, code="ROUTE_PREFIX", must_exist=True
            )
            if prefix in prefixes:
                raise ContractError("DUPLICATE_ROUTE_PREFIX")
            for other_prefix, _ in owned_prefixes:
                if (
                    prefix == other_prefix
                    or prefix.startswith(other_prefix + "/")
                    or other_prefix.startswith(prefix + "/")
                ):
                    raise ContractError("OVERLAPPING_ROUTE_PREFIX")
            prefixes.append(prefix)
            owned_prefixes.append((prefix, route_id))

        agents_paths: list[str] = []
        for path_raw in _bounded_list(raw["agents_paths"], 1, 8, "ROUTE_AGENTS_PATHS"):
            relative, _ = _repo_path(
                root, path_raw, code="ROUTE_AGENTS_PATH", must_exist=True, must_be_file=True
            )
            if PurePosixPath(relative).name != "AGENTS.md" or relative in agents_paths:
                raise ContractError("ROUTE_AGENTS_PATH")
            agents_paths.append(relative)

        guide_paths: list[str] = []
        for path_raw in _bounded_list(raw["guide_paths"], 1, 8, "ROUTE_GUIDE_PATHS"):
            relative, _ = _repo_path(
                root, path_raw, code="ROUTE_GUIDE_PATH", must_exist=True, must_be_file=True
            )
            if relative in guide_paths:
                raise ContractError("ROUTE_GUIDE_PATH")
            guide_paths.append(relative)

        fact_ref = _reference(root, raw["fact_ref"], code="ROUTE_FACT_REF", require_anchor=True)
        validation_id = _identifier(raw["validation_id"], "ROUTE_VALIDATION_ID")
        if validation_id not in validation_by_id:
            raise ContractError("UNKNOWN_ROUTE_VALIDATION")
        routes.append(
            {
                "id": route_id,
                "explicit_tags": tags,
                "path_prefixes": prefixes,
                "agents_paths": agents_paths,
                "guide_paths": guide_paths,
                "fact_ref": fact_ref,
                "validation_id": validation_id,
            }
        )

    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "enabled": True,
        "routes": routes,
        "validations": validations,
        "validation_by_id": validation_by_id,
    }


def load_registry(root: Path) -> tuple[dict[str, Any], str]:
    """Load the model-backed in-memory routing projection used by hooks.

    The function name remains an internal receipt-runtime boundary.
    ``routes.json`` is never used as a second live source.
    """

    root = root.resolve(strict=True)
    namespace_path = root / NAMESPACE_RELATIVE_PATH
    legacy_namespace_path = root / LEGACY_NAMESPACE_RELATIVE_PATH
    namespace_declared = os.path.lexists(namespace_path)
    legacy_namespace_declared = os.path.lexists(legacy_namespace_path)
    if namespace_declared and legacy_namespace_declared:
        raise ContractError("COH_NAMESPACE_CONFLICT")
    if legacy_namespace_declared:
        raise ContractError("LEGACY_NAMESPACE_UNSUPPORTED")
    if not namespace_declared:
        raise ContractError("MODEL_MISSING")
    if namespace_path.is_symlink() or not namespace_path.is_dir():
        raise ContractError("COH_NAMESPACE_INVALID")

    model_path = root / MODEL_RELATIVE_PATH
    legacy_path = root / REGISTRY_RELATIVE_PATH
    model_declared = os.path.lexists(model_path)
    legacy_declared = os.path.lexists(legacy_path)
    if model_declared and legacy_declared:
        raise ContractError("MODEL_LEGACY_CONFLICT")
    if legacy_declared:
        if legacy_path.is_symlink() or not legacy_path.is_file():
            raise ContractError("REGISTRY_PATH_INVALID")
        raise ContractError("LEGACY_ROUTES_UNSUPPORTED")
    if not model_declared:
        raise ContractError("MODEL_MISSING")
    if model_path.is_symlink() or not model_path.is_file():
        raise ContractError("MODEL_PATH_INVALID")

    # Imported lazily so the model module can reuse the dependency-free path and
    # identifier validators in this module without creating an import cycle.
    from harness_model import load_model

    return load_model(root)


def discover_repository(cwd_value: Any) -> tuple[Path, Path] | None:
    if not isinstance(cwd_value, str) or not cwd_value:
        return None
    try:
        cwd = Path(cwd_value).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not cwd.is_dir():
        return None

    try:
        completed = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        completed = None
    if completed is not None and completed.returncode == 0:
        try:
            root = Path(completed.stdout.strip()).resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        namespace_marker = root / NAMESPACE_RELATIVE_PATH
        legacy_namespace_marker = root / LEGACY_NAMESPACE_RELATIVE_PATH
        if os.path.lexists(namespace_marker):
            return root, namespace_marker
        if os.path.lexists(legacy_namespace_marker):
            return root, legacy_namespace_marker
        return None

    current = cwd
    for _ in range(12):
        namespace_marker = current / NAMESPACE_RELATIVE_PATH
        legacy_namespace_marker = current / LEGACY_NAMESPACE_RELATIVE_PATH
        if os.path.lexists(namespace_marker):
            return current, namespace_marker
        if os.path.lexists(legacy_namespace_marker):
            return current, legacy_namespace_marker
        if current.parent == current:
            break
        current = current.parent
    return None


def select_route(registry: dict[str, Any], prompt_value: Any) -> tuple[str, dict[str, Any] | None]:
    if not isinstance(prompt_value, str):
        return "PROMPT_INVALID", None
    if len(prompt_value) > MAX_PROMPT_CHARS:
        return "PROMPT_TOO_LARGE", None

    routes = registry["routes"]
    tag_to_route = {
        tag: route for route in routes for tag in route["explicit_tags"]
    }
    tag_values = EXPLICIT_ROUTE_TAG.findall(prompt_value)
    if len(set(tag_values)) != len(tag_values):
        return "DUPLICATE_ROUTE_TAG_IN_PROMPT", None
    if any(tag not in tag_to_route for tag in tag_values):
        return "UNKNOWN_ROUTE_TAG", None
    tagged_routes = {tag_to_route[tag]["id"] for tag in tag_values}
    if len(tagged_routes) > 1:
        return "MULTIPLE_ROUTE_TAGS", None

    path_prompt = EXPLICIT_ROUTE_TAG.sub("", prompt_value)
    path_routes: set[str] = set()
    for route in routes:
        for prefix in route["path_prefixes"]:
            pattern = re.compile(
                r"(?<![A-Za-z0-9_./-])"
                + re.escape(prefix)
                + r"(?=$|[/\s:;,)'\]}`\"?#])"
            )
            if pattern.search(path_prompt):
                path_routes.add(route["id"])
                break
    if len(path_routes) > 1:
        return "AMBIGUOUS_PATH_ROUTE", None

    selected_ids = tagged_routes | path_routes
    if len(selected_ids) > 1:
        return "TAG_PATH_CONFLICT", None
    if not selected_ids:
        return "NO_ROUTE_MATCH", None
    selected_id = next(iter(selected_ids))
    return "ROUTED", next(route for route in routes if route["id"] == selected_id)


def git_head(root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = completed.stdout.strip().lower()
    return value if completed.returncode == 0 and COMMIT.fullmatch(value) else None


def _git_path_set(root: Path, arguments: list[str], code: str) -> set[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError(code) from exc
    if completed.returncode != 0 or len(completed.stdout) > MAX_GIT_PATH_OUTPUT_BYTES:
        raise ContractError(code)
    try:
        values = {
            item.decode("utf-8")
            for item in completed.stdout.split(b"\0")
            if item
        }
    except UnicodeDecodeError as exc:
        raise ContractError(code) from exc
    return values


def receipt_path_precondition(root: Path, receipt_path: str) -> str:
    """Classify one dedicated receipt path without trusting it as worktree input."""

    normalized, resolved = _repo_path(
        root,
        receipt_path,
        code="RECEIPT_PATH_INVALID",
        must_exist=False,
    )
    if not normalized.startswith(RECEIPT_NAMESPACE):
        raise ContractError("RECEIPT_PATH_INVALID")
    if _path_contains_symlink(root, normalized, code="RECEIPT_PATH_SYMLINK"):
        raise ContractError("RECEIPT_PATH_SYMLINK")
    tracked = _git_path_set(
        root,
        ["ls-files", "--cached", "-z", "--", f":(literal){normalized}"],
        "RECEIPT_TRACKING_UNAVAILABLE",
    )
    if normalized in tracked:
        raise ContractError("RECEIPT_PATH_TRACKED")
    if resolved.exists():
        try:
            metadata = resolved.stat()
        except OSError as exc:
            raise ContractError("RECEIPT_PATH_INVALID") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise ContractError("RECEIPT_PATH_INVALID")
        if metadata.st_nlink != 1:
            raise ContractError("RECEIPT_PATH_HARDLINK")
        return "UNTRACKED_REGULAR"
    return "ABSENT"


def _worktree_path_sets(
    root: Path, excluded_path: str | None = None
) -> tuple[list[str], set[str]]:
    if excluded_path is not None:
        receipt_path_precondition(root, excluded_path)
    changed = _git_path_set(
        root,
        ["diff", "--no-renames", "--name-only", "-z", "HEAD", "--"],
        "WORKTREE_CHANGED_PATHS_UNAVAILABLE",
    )
    untracked = _git_path_set(
        root,
        ["ls-files", "--others", "--exclude-standard", "-z", "--"],
        "WORKTREE_UNTRACKED_PATHS_UNAVAILABLE",
    )
    paths = sorted(changed | untracked)
    if excluded_path is not None:
        paths = [path for path in paths if path != excluded_path]
    if len(paths) > MAX_WORKTREE_FILES:
        raise ContractError("WORKTREE_TOO_MANY_FILES")
    return paths, untracked


def worktree_sha256(root: Path, excluded_path: str | None = None) -> str:
    """Fingerprint HEAD plus current changed and untracked, non-ignored files."""

    paths, untracked = _worktree_path_sets(root, excluded_path)

    digest = hashlib.sha256()
    digest.update(b"COH_WORKTREE_V2\0")
    head = git_head(root)
    if head is None:
        raise ContractError("CHECKOUT_UNVERIFIABLE")
    digest.update(head.encode("ascii") + b"\0")
    total_bytes = 0
    for relative in paths:
        normalized, _ = _repo_path(
            root,
            relative,
            code="WORKTREE_PATH_INVALID",
            must_exist=False,
        )
        candidate = root.joinpath(*PurePosixPath(normalized).parts)
        category = "U" if relative in untracked else "T"
        digest.update(category.encode("ascii") + b"\0")
        digest.update(normalized.encode("utf-8") + b"\0")
        if not candidate.exists() and not candidate.is_symlink():
            digest.update(b"DELETED\0")
            continue
        if candidate.is_symlink():
            raise ContractError("WORKTREE_SYMLINK_UNSUPPORTED")
        try:
            metadata = candidate.stat()
        except OSError as exc:
            raise ContractError("WORKTREE_PATH_UNREADABLE") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise ContractError("WORKTREE_FILE_TYPE_UNSUPPORTED")
        total_bytes += metadata.st_size
        if total_bytes > MAX_WORKTREE_BYTES:
            raise ContractError("WORKTREE_TOO_LARGE")
        digest.update(f"{stat.S_IMODE(metadata.st_mode):04o}".encode("ascii") + b"\0")
        digest.update(sha256_file(candidate).encode("ascii") + b"\0")
    return digest.hexdigest()


def route_scope_matches(
    root: Path,
    path_prefixes: list[str],
    excluded_path: str | None = None,
) -> bool:
    """Require the selected route to cover the entire receipt-bound worktree."""

    paths, _ = _worktree_path_sets(root, excluded_path)
    for path in paths:
        if not any(
            path == prefix or path.startswith(prefix + "/")
            for prefix in path_prefixes
        ):
            return False
    return True


def protected_authority_status(
    root: Path, protected_paths: list[str] | None
) -> dict[str, Any]:
    """Compare declared validation authorities with HEAD without persisting paths."""

    if not protected_paths:
        return {
            "status": "NOT_DECLARED",
            "change_count": 0,
            "changed_path_hashes": [],
        }
    literal_pathspecs = [f":(literal){path}" for path in protected_paths]
    changed = _git_path_set(
        root,
        ["diff", "--name-only", "-z", "HEAD", "--", *literal_pathspecs],
        "PROTECTED_AUTHORITY_CHANGED_PATHS_UNAVAILABLE",
    )
    untracked = _git_path_set(
        root,
        [
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            *literal_pathspecs,
        ],
        "PROTECTED_AUTHORITY_UNTRACKED_PATHS_UNAVAILABLE",
    )
    paths = sorted(changed | untracked)
    if len(paths) > MAX_WORKTREE_FILES:
        raise ContractError("PROTECTED_AUTHORITY_TOO_MANY_CHANGES")
    return {
        "status": "CHANGED" if paths else "UNCHANGED",
        "change_count": len(paths),
        "changed_path_hashes": [
            hashlib.sha256(path.encode("utf-8")).hexdigest() for path in paths
        ],
    }


def repository_id(root: Path) -> str:
    return hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()


def opaque_id(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def plugin_data_root() -> Path | None:
    # Codex and Claude Code expose different persistent plugin-data variables.
    # Keep the runtime shared and let the generated host package own only the
    # manifest and command-path adapter.
    value = os.environ.get("PLUGIN_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA")
    if not value:
        return None
    try:
        root = Path(value).resolve()
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return root


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def read_json_file(path: Path, maximum_bytes: int = 16 * 1024) -> dict[str, Any] | None:
    try:
        payload, _ = load_json_object(path, maximum_bytes)
    except ContractError:
        return None
    return payload


def state_paths(
    data_root: Path, repo_id: str, session_id: str, turn_id: str | None
) -> tuple[Path | None, Path]:
    state_root = data_root / "state" / repo_id
    session_hash = opaque_id(session_id)
    assert session_hash is not None
    latest = state_root / f"latest-{session_hash}.json"
    exact = state_root / f"turn-{opaque_id(turn_id)}.json" if turn_id else None
    return exact, latest


def append_candidate(data_root: Path, repo_id: str, payload: dict[str, Any]) -> bool:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    path = data_root / "candidates" / repo_id / f"{month}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    event_id = payload.get("event_id")
    if not isinstance(event_id, str):
        return False
    try:
        if path.exists():
            with path.open("rb") as handle:
                size = path.stat().st_size
                handle.seek(max(0, size - 256 * 1024))
                if event_id.encode("ascii") in handle.read():
                    return False
        encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, encoded)
        finally:
            os.close(descriptor)
    except OSError:
        return False
    return True


def pending_candidate_count(data_root: Path, repo_id: str, route_id: str) -> int:
    candidate_root = data_root / "candidates" / repo_id
    if not candidate_root.is_dir():
        return 0
    count = 0
    for path in sorted(candidate_root.glob("*.jsonl"), reverse=True)[:3]:
        try:
            if path.stat().st_size > 1024 * 1024:
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                payload = json.loads(line)
                if payload.get("route_id") == route_id:
                    count += 1
                    if count >= 99:
                        return 99
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    return count


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp(value: Any, code: str) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ContractError(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(code) from exc
    if parsed.tzinfo is None:
        raise ContractError(code)
    return parsed.astimezone(timezone.utc)


def validate_receipt(
    root: Path,
    receipt_path: str | None,
    *,
    validation_id: str,
    registry_digest: str,
    run_nonce: str,
    state_created_at: str,
    receipt_precondition: Any,
    routed_commit_sha: Any,
    route_prefixes: list[str],
    protected_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Return a sanitized receipt verdict; never return raw receipt prose."""

    if receipt_path is None:
        return {"status": "NO_TRUSTED_RESULT", "reason": "RECEIPT_NOT_DECLARED", "observations": []}
    try:
        if receipt_precondition not in {"ABSENT", "UNTRACKED_REGULAR"}:
            raise ContractError("STATE_RECEIPT_PRECONDITION")
        if receipt_path_precondition(root, receipt_path) != "UNTRACKED_REGULAR":
            raise ContractError("RECEIPT_PATH_INVALID")
        _, resolved = _repo_path(
            root,
            receipt_path,
            code="RECEIPT_PATH_INVALID",
            must_exist=True,
            must_be_file=True,
        )
        payload, _ = load_json_object(resolved, MAX_RECEIPT_BYTES)
        _exact_keys(
            payload,
            {
                "schema_version",
                "validation_id",
                "registry_sha256",
                "commit_sha",
                "worktree_sha256",
                "run_nonce",
                "result",
                "exit_code",
                "started_at",
                "finished_at",
                "runner_id",
                "observations",
            },
            set(),
            "RECEIPT_FIELDS",
        )
        if payload["schema_version"] != RECEIPT_SCHEMA_VERSION:
            raise ContractError("RECEIPT_SCHEMA_VERSION")
        if _identifier(payload["validation_id"], "RECEIPT_VALIDATION_ID") != validation_id:
            raise ContractError("RECEIPT_VALIDATION_MISMATCH")
        if not isinstance(payload["registry_sha256"], str) or not DIGEST.fullmatch(payload["registry_sha256"]):
            raise ContractError("RECEIPT_REGISTRY_DIGEST")
        if payload["registry_sha256"] != registry_digest:
            raise ContractError("RECEIPT_REGISTRY_MISMATCH")
        if not isinstance(payload["run_nonce"], str) or not RUN_NONCE.fullmatch(payload["run_nonce"]):
            raise ContractError("RECEIPT_RUN_NONCE")
        if payload["run_nonce"] != run_nonce:
            raise ContractError("RECEIPT_RUN_NONCE_MISMATCH")
        current_commit = git_head(root)
        if current_commit is None:
            raise ContractError("CHECKOUT_UNVERIFIABLE")
        if (
            not isinstance(routed_commit_sha, str)
            or not COMMIT.fullmatch(routed_commit_sha)
        ):
            raise ContractError("STATE_COMMIT")
        if routed_commit_sha != current_commit:
            raise ContractError("ROUTE_CHECKOUT_CHANGED")
        if not isinstance(payload["commit_sha"], str) or not COMMIT.fullmatch(payload["commit_sha"]):
            raise ContractError("RECEIPT_COMMIT")
        if payload["commit_sha"] != current_commit:
            raise ContractError("RECEIPT_COMMIT_MISMATCH")
        if not isinstance(payload["worktree_sha256"], str) or not DIGEST.fullmatch(payload["worktree_sha256"]):
            raise ContractError("RECEIPT_WORKTREE_DIGEST")
        current_worktree = worktree_sha256(root, receipt_path)
        if payload["worktree_sha256"] != current_worktree:
            raise ContractError("RECEIPT_WORKTREE_MISMATCH")
        if not route_scope_matches(root, route_prefixes, receipt_path):
            raise ContractError("ROUTE_SCOPE_MISMATCH")
        if payload["result"] not in {"pass", "fail"}:
            raise ContractError("RECEIPT_RESULT")
        if not isinstance(payload["exit_code"], int) or isinstance(payload["exit_code"], bool):
            raise ContractError("RECEIPT_EXIT_CODE")
        if (payload["result"] == "pass") != (payload["exit_code"] == 0):
            raise ContractError("RECEIPT_RESULT_EXIT_MISMATCH")
        _identifier(payload["runner_id"], "RECEIPT_RUNNER_ID")
        started = _timestamp(payload["started_at"], "RECEIPT_STARTED_AT")
        finished = _timestamp(payload["finished_at"], "RECEIPT_FINISHED_AT")
        state_created = _timestamp(state_created_at, "STATE_CREATED_AT")
        clock_tolerance = timedelta(minutes=5)
        if finished < started or started < state_created - clock_tolerance:
            raise ContractError("RECEIPT_TIME_ORDER")
        if finished > datetime.now(timezone.utc) + clock_tolerance:
            raise ContractError("RECEIPT_TIME_FUTURE")

        observations: list[dict[str, str]] = []
        for raw in _bounded_list(payload["observations"], 0, 16, "RECEIPT_OBSERVATIONS"):
            if not isinstance(raw, dict):
                raise ContractError("RECEIPT_OBSERVATION")
            _exact_keys(
                raw,
                {"code", "kind", "status", "evidence_path", "evidence_sha256"},
                {"claim_id", "outcome"},
                "RECEIPT_OBSERVATION_FIELDS",
            )
            code = _identifier(raw["code"], "RECEIPT_OBSERVATION_CODE")
            if raw["kind"] not in OBSERVATION_KINDS:
                raise ContractError("RECEIPT_OBSERVATION_KIND")
            if raw["status"] not in OBSERVATION_STATUSES:
                raise ContractError("RECEIPT_OBSERVATION_STATUS")
            has_claim = "claim_id" in raw
            has_outcome = "outcome" in raw
            if raw["kind"] in STRUCTURED_OBSERVATION_KINDS and not (
                has_claim and has_outcome
            ):
                raise ContractError("RECEIPT_OBSERVATION_SEMANTICS")
            if has_claim != has_outcome:
                raise ContractError("RECEIPT_OBSERVATION_SEMANTICS")
            claim_id = (
                _identifier(raw["claim_id"], "RECEIPT_OBSERVATION_CLAIM_ID")
                if has_claim
                else None
            )
            outcome = raw.get("outcome")
            if has_outcome and outcome not in OBSERVATION_OUTCOMES:
                raise ContractError("RECEIPT_OBSERVATION_OUTCOME")
            evidence_path, evidence_resolved = _repo_path(
                root,
                raw["evidence_path"],
                code="RECEIPT_EVIDENCE_PATH",
                must_exist=True,
                must_be_file=True,
            )
            if not isinstance(raw["evidence_sha256"], str) or not DIGEST.fullmatch(raw["evidence_sha256"]):
                raise ContractError("RECEIPT_EVIDENCE_DIGEST")
            try:
                if evidence_resolved.stat().st_size > MAX_EVIDENCE_FILE_BYTES:
                    raise ContractError("RECEIPT_EVIDENCE_TOO_LARGE")
            except OSError as exc:
                raise ContractError("RECEIPT_EVIDENCE_PATH") from exc
            if sha256_file(evidence_resolved) != raw["evidence_sha256"]:
                raise ContractError("RECEIPT_EVIDENCE_MISMATCH")
            normalized_observation = {
                "code": code,
                "kind": raw["kind"],
                "status": raw["status"],
                "evidence_path": evidence_path,
                "evidence_sha256": raw["evidence_sha256"],
            }
            if claim_id is not None:
                normalized_observation["claim_id"] = claim_id
                normalized_observation["outcome"] = outcome
            observations.append(normalized_observation)
        authority = protected_authority_status(root, protected_paths)
        if authority["status"] == "CHANGED":
            return {
                "status": "NO_TRUSTED_RESULT",
                "reason": "PROTECTED_AUTHORITY_CHANGED",
                "observations": [],
                "protected_authority": authority,
            }
        if receipt_path_precondition(root, receipt_path) != "UNTRACKED_REGULAR":
            raise ContractError("RECEIPT_PATH_INVALID")
        return {
            "status": "TRUSTED_RECEIPT",
            "reason": "RECEIPT_ACCEPTED",
            "result": payload["result"],
            "exit_code": payload["exit_code"],
            "runner_id": payload["runner_id"],
            "worktree_sha256": payload["worktree_sha256"],
            "started_at": payload["started_at"],
            "finished_at": payload["finished_at"],
            "observations": observations,
            "protected_authority": authority,
        }
    except ContractError as exc:
        return {"status": "NO_TRUSTED_RESULT", "reason": exc.code, "observations": []}
