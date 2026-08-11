#!/usr/bin/env python3
"""Route opted-in repositories before broad coding-agent discovery."""

from __future__ import annotations

import json
import secrets
import sys
from datetime import datetime, timezone

from coh_hook_common import (
    ContractError,
    atomic_write_json,
    discover_repository,
    git_head,
    load_registry,
    opaque_id,
    pending_candidate_count,
    plugin_data_root,
    repository_id,
    receipt_path_precondition,
    select_route,
    state_paths,
)


def emit_continue() -> None:
    print(json.dumps({"continue": True}, separators=(",", ":")))


def emit_context(context: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            },
            separators=(",", ":"),
        )
    )


def degraded_context(reason: str, blockers: list[str] | None = None) -> str:
    payload_value: dict[str, object] = {
        "schema_version": 1,
        "status": "DEGRADED",
        "reason": reason,
    }
    if blockers:
        payload_value["blockers"] = blockers
    payload = json.dumps(
        payload_value,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        "COH_ROUTER_V2\n"
        + payload
        + "\nThe repository opted in, but no single safe route was established. "
        "Read only the nearest AGENTS.md and .coh/model.json first. "
        "Do not scan the whole repository. If scope remains ambiguous, ask for a route tag such as [route:<id>]. "
        "This hook is advisory and is not validation evidence."
    )


def routed_context(
    route: dict[str, object],
    validation: dict[str, object] | None,
    *,
    run_nonce: str,
    pending_count: int,
) -> str:
    receipt_path = (
        validation.get("receipt_path")
        if validation is not None and route.get("evidence_policy") == "RECEIPT_REQUIRED"
        else None
    )
    fact_refs = route.get("fact_refs", [])
    if not isinstance(fact_refs, list):
        fact_refs = []
    fact_paths = [
        reference["path"]
        for reference in fact_refs
        if isinstance(reference, dict) and isinstance(reference.get("path"), str)
    ]
    routing_payload = {
        "schema_version": 1,
        "status": "ROUTED",
        "route_id": route["id"],
        "agents_paths": route["agents_paths"],
        "guide_paths": route["guide_paths"],
        "fact_paths": fact_paths,
        "sensor_id": validation["id"] if validation is not None else None,
        "validation_id": validation["id"] if validation is not None else None,
        "validation_declaration_path": (
            validation["declaration_ref"]["path"] if validation is not None else None
        ),
        "proof_layer": validation["proof_layer"] if validation is not None else None,
        "evidence_policy": route.get("evidence_policy", "NO_TRUSTED_RESULT"),
        "receipt_path": receipt_path,
        "protected_paths": validation.get("protected_paths", []) if validation else [],
        "run_nonce": run_nonce or None,
        "pending_report_only_candidates": pending_count,
    }
    return (
        "COH_ROUTER_V2\n"
        + json.dumps(routing_payload, sort_keys=True, separators=(",", ":"))
        + "\nBefore broad discovery, read every listed AGENTS, guide, and fact file from disk and follow their scope. "
        "Use a listed repository-owned validation declaration when present; this plugin does not own or run its command. "
        "Do not create or edit a receipt manually. If that runner implements the receipt contract, pass the shown nonce as COH_RUN_NONCE. "
        "When evidence_policy is NO_TRUSTED_RESULT, do not infer validation success from assistant prose or a missing Sensor. "
        "Treat listed protected paths as validation authorities: changing them may be legitimate work, but it makes this turn's receipt untrusted and report-only until reviewed. "
        "Repository-wide discovery is allowed only when the listed authorities are missing, conflicting, or demonstrably insufficient. "
        "Candidate counts are report-only and never authorize Guide, Fact Map, AGENTS.md, test, or CI changes."
    )


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        emit_continue()
        return 0
    if not isinstance(event, dict) or event.get("hook_event_name") != "UserPromptSubmit":
        emit_continue()
        return 0
    discovered = discover_repository(event.get("cwd"))
    if discovered is None:
        emit_continue()
        return 0
    root, _ = discovered
    data_root = plugin_data_root()
    session_id = event.get("session_id")
    turn_id = event.get("turn_id")
    repo_hash = repository_id(root)
    if data_root is not None and isinstance(session_id, str) and session_id:
        exact, latest = state_paths(
            data_root,
            repo_hash,
            session_id,
            turn_id if isinstance(turn_id, str) and turn_id else None,
        )
        # A new prompt starts a new evidence lifecycle. Clear the session fallback
        # (and a retried exact turn) before any branch can degrade or route without
        # a receipt; only a newly issued nonce may recreate these files below.
        for stale_state in {exact, latest}:
            if stale_state is None:
                continue
            try:
                stale_state.unlink(missing_ok=True)
            except OSError:
                pass

    try:
        registry, registry_digest = load_registry(root)
    except ContractError as exc:
        emit_context(degraded_context(exc.code))
        return 0
    if not registry["enabled"]:
        emit_continue()
        return 0
    if registry.get("construction_status") != "READY":
        blocker_codes = [
            str(item.get("code"))
            for item in registry.get("blockers", [])
            if isinstance(item, dict) and isinstance(item.get("code"), str)
        ]
        emit_context(degraded_context("MODEL_NOT_READY", blocker_codes))
        return 0

    status, route = select_route(registry, event.get("prompt"))
    if status != "ROUTED" or route is None:
        emit_context(degraded_context(status))
        return 0

    validation_id = route.get("validation_id")
    validation = (
        registry["validation_by_id"].get(validation_id)
        if isinstance(validation_id, str)
        else None
    )
    receipt_path = (
        validation.get("receipt_path")
        if validation is not None and route.get("evidence_policy") == "RECEIPT_REQUIRED"
        else None
    )
    routed_commit = git_head(root)
    receipt_precondition = None
    if receipt_path is not None and routed_commit is not None:
        try:
            receipt_precondition = receipt_path_precondition(root, receipt_path)
        except ContractError as exc:
            emit_context(degraded_context(exc.code))
            return 0
    run_nonce = (
        secrets.token_hex(16)
        if receipt_path and routed_commit and receipt_precondition is not None
        else ""
    )
    pending_count = (
        pending_candidate_count(data_root, repo_hash, route["id"])
        if data_root is not None
        else 0
    )

    if (
        data_root is not None
        and isinstance(session_id, str)
        and session_id
        and validation is not None
        and receipt_path is not None
        and routed_commit is not None
    ):
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        state = {
            "schema_version": 1,
            "created_at": now,
            "repo_id": repo_hash,
            "registry_sha256": registry_digest,
            "commit_sha": routed_commit,
            "route_id": route["id"],
            "validation_id": validation["id"],
            "receipt_path": receipt_path,
            "receipt_precondition": receipt_precondition,
            "proof_layer": validation["proof_layer"],
            "run_nonce": run_nonce,
            "session_hash": opaque_id(session_id),
            "turn_hash": opaque_id(turn_id),
        }
        exact, latest = state_paths(
            data_root,
            repo_hash,
            session_id,
            turn_id if isinstance(turn_id, str) and turn_id else None,
        )
        try:
            atomic_write_json(latest, state)
            if exact is not None:
                atomic_write_json(exact, state)
        except OSError:
            pass

    emit_context(
        routed_context(
            route,
            validation,
            run_nonce=run_nonce,
            pending_count=pending_count,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 - lifecycle hooks must fail open
        emit_continue()
        raise SystemExit(0)
