#!/usr/bin/env python3
"""Collect sanitized, report-only validation candidates after a routed turn."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone

from coh_hook_common import (
    ContractError,
    append_candidate,
    discover_repository,
    git_head,
    load_registry,
    plugin_data_root,
    read_json_file,
    repository_id,
    state_paths,
    validate_receipt,
)


def emit_continue() -> None:
    print(json.dumps({"continue": True}, separators=(",", ":")))


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        emit_continue()
        return 0
    if not isinstance(event, dict) or event.get("hook_event_name") != "Stop":
        emit_continue()
        return 0
    if event.get("stop_hook_active") is True:
        emit_continue()
        return 0
    discovered = discover_repository(event.get("cwd"))
    data_root = plugin_data_root()
    session_id = event.get("session_id")
    if discovered is None or data_root is None or not isinstance(session_id, str) or not session_id:
        emit_continue()
        return 0
    root, _ = discovered
    repo_hash = repository_id(root)
    turn_id = event.get("turn_id")
    exact_turn_id = turn_id if isinstance(turn_id, str) and turn_id else None
    exact, latest = state_paths(
        data_root,
        repo_hash,
        session_id,
        exact_turn_id,
    )
    # Hosts that provide a turn id must bind Stop to that exact prompt. Only
    # turn-less hosts may use the session-latest compatibility state.
    state_path = exact if exact is not None else latest
    state = read_json_file(state_path)
    if state is None:
        emit_continue()
        return 0
    consumable_states = {state_path}
    if exact is not None and read_json_file(latest) == state:
        consumable_states.add(latest)

    try:
        registry, registry_digest = load_registry(root)
    except ContractError:
        emit_continue()
        return 0
    if not registry.get("runtime_eligible"):
        # A nonce issued while the model was routable must not survive a later
        # BLOCKED or disabled transition. A new eligible prompt must issue a
        # new nonce even though the Stop hook also checks the projection digest.
        for invalid_state in consumable_states:
            try:
                invalid_state.unlink(missing_ok=True)
            except OSError:
                pass
        emit_continue()
        return 0
    if (
        state.get("repo_id") != repo_hash
        or state.get("registry_sha256") != registry_digest
    ):
        emit_continue()
        return 0
    route = next(
        (item for item in registry["routes"] if item["id"] == state.get("route_id")),
        None,
    )
    if (
        route is None
        or route.get("evidence_policy") != "RECEIPT_REQUIRED"
        or route["validation_id"] != state.get("validation_id")
    ):
        emit_continue()
        return 0
    validation = registry["validation_by_id"][route["validation_id"]]
    verdict = validate_receipt(
        root,
        validation.get("receipt_path"),
        validation_id=validation["id"],
        registry_digest=registry_digest,
        run_nonce=state.get("run_nonce", ""),
        state_created_at=state.get("created_at", ""),
        receipt_precondition=state.get("receipt_precondition"),
        routed_commit_sha=state.get("commit_sha"),
        route_prefixes=route["path_prefixes"],
        protected_paths=validation.get("protected_paths", []),
    )
    recorded_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    event_material = "|".join(
        [
            str(state.get("session_hash", "")),
            str(state.get("turn_hash", "")),
            repo_hash,
            registry_digest,
            str(route["id"]),
            str(state.get("run_nonce", "")),
        ]
    )
    candidate = {
        "schema_version": 1,
        "event_id": hashlib.sha256(event_material.encode("utf-8")).hexdigest(),
        "recorded_at": recorded_at,
        "repo_id": repo_hash,
        "commit_sha": git_head(root),
        "worktree_sha256": verdict.get("worktree_sha256"),
        "registry_sha256": registry_digest,
        "route_id": route["id"],
        "validation_id": validation["id"],
        "proof_layer": validation["proof_layer"],
        "evidence_status": verdict["status"],
        "reason_code": verdict["reason"],
        "validation_result": verdict.get("result"),
        "exit_code": verdict.get("exit_code"),
        "runner_id": verdict.get("runner_id"),
        "observations": verdict["observations"],
        "protected_authority": verdict.get(
            "protected_authority",
            {"status": "UNVERIFIED", "change_count": 0, "changed_path_hashes": []},
        ),
        "guide_update_authorized": False,
    }
    appended = append_candidate(data_root, repo_hash, candidate)
    if appended:
        for consumed_state in consumable_states:
            try:
                consumed_state.unlink(missing_ok=True)
            except OSError:
                pass
    emit_continue()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 - lifecycle hooks must fail open
        emit_continue()
        raise SystemExit(0)
