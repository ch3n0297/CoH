from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from common import (
    COLLECTOR,
    ROUTER,
    additional_context,
    context_payload,
    copy_fixture,
    git,
    load_json,
    repository_snapshot,
    run_hook,
    sha256_file,
    write_json,
)

from coh_hook_common import load_registry, worktree_sha256


class RuntimeHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="coh-runtime-")
        base = Path(self.temporary.name)
        self.root = copy_fixture(base / "repository")
        self.data_root = base / "plugin-data"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def route(self, session: str, turn: str) -> tuple[dict[str, object], dict[str, object]]:
        output = run_hook(
            ROUTER,
            {
                "hook_event_name": "UserPromptSubmit",
                "cwd": str(self.root),
                "session_id": session,
                "turn_id": turn,
                "prompt": "[route:auth] Inspect src/auth/module.py.",
            },
            self.data_root,
        )
        payload = context_payload(output)
        state = next(
            load_json(path)
            for path in sorted((self.data_root / "state").rglob("turn-*.json"))
            if load_json(path).get("session_hash")
            == hashlib.sha256(session.encode("utf-8")).hexdigest()
        )
        return payload, state

    def receipt(self, state: dict[str, object], *, nonce: str | None = None) -> dict[str, object]:
        _, projection_digest = load_registry(self.root)
        receipt_path = ".coh/receipts/repo-validate.json"
        evidence = self.root / "artifacts" / "auth-test.json"
        return {
            "schema_version": 1,
            "validation_id": "repo-validate",
            "registry_sha256": projection_digest,
            "commit_sha": git(self.root, "rev-parse", "HEAD"),
            "worktree_sha256": worktree_sha256(self.root, receipt_path),
            "run_nonce": nonce if nonce is not None else state["run_nonce"],
            "result": "pass",
            "exit_code": 0,
            "started_at": state["created_at"],
            "finished_at": state["created_at"],
            "runner_id": "fixture-runner",
            "observations": [
                {
                    "code": "auth-smoke",
                    "kind": "test",
                    "status": "observed",
                    "evidence_path": "artifacts/auth-test.json",
                    "evidence_sha256": sha256_file(evidence),
                }
            ],
        }

    def candidates(self) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for path in sorted((self.data_root / "candidates").rglob("*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()
        ]

    def test_exact_route_and_trusted_receipt_lifecycle(self) -> None:
        before = repository_snapshot(self.root)
        payload, state = self.route("trusted-session", "trusted-turn")
        self.assertEqual(payload["status"], "ROUTED")
        self.assertEqual(payload["route_id"], "auth")
        self.assertEqual(payload["evidence_policy"], "RECEIPT_REQUIRED")
        self.assertEqual(repository_snapshot(self.root), before)

        receipt_path = self.root / ".coh" / "receipts" / "repo-validate.json"
        write_json(receipt_path, self.receipt(state))
        output = run_hook(
            COLLECTOR,
            {
                "hook_event_name": "Stop",
                "cwd": str(self.root),
                "session_id": "trusted-session",
                "turn_id": "trusted-turn",
                "stop_hook_active": False,
            },
            self.data_root,
        )
        self.assertEqual(output, {"continue": True})
        candidate = self.candidates()[-1]
        self.assertEqual(candidate["evidence_status"], "TRUSTED_RECEIPT")
        self.assertEqual(candidate["reason_code"], "RECEIPT_ACCEPTED")
        self.assertFalse(candidate["guide_update_authorized"])
        persisted = b"".join(
            path.read_bytes() for path in self.data_root.rglob("*") if path.is_file()
        )
        self.assertNotIn(b"Inspect src/auth/module.py", persisted)

    def test_wrong_nonce_remains_report_only(self) -> None:
        _, state = self.route("nonce-session", "nonce-turn")
        receipt_path = self.root / ".coh" / "receipts" / "repo-validate.json"
        write_json(receipt_path, self.receipt(state, nonce="0" * 32))
        run_hook(
            COLLECTOR,
            {
                "hook_event_name": "Stop",
                "cwd": str(self.root),
                "session_id": "nonce-session",
                "turn_id": "nonce-turn",
                "stop_hook_active": False,
            },
            self.data_root,
        )
        candidate = self.candidates()[-1]
        self.assertEqual(candidate["evidence_status"], "NO_TRUSTED_RESULT")
        self.assertEqual(candidate["reason_code"], "RECEIPT_RUN_NONCE_MISMATCH")

    def test_unknown_route_and_legacy_routes_fail_closed_without_repo_writes(self) -> None:
        unknown = run_hook(
            ROUTER,
            {
                "hook_event_name": "UserPromptSubmit",
                "cwd": str(self.root),
                "session_id": "unknown-session",
                "turn_id": "unknown-turn",
                "prompt": "[route:not-declared] Inspect it.",
            },
            self.data_root,
        )
        self.assertEqual(context_payload(unknown)["reason"], "UNKNOWN_ROUTE_TAG")

        (self.root / ".coh" / "model.json").unlink()
        write_json(self.root / ".coh" / "routes.json", {"schema_version": 1})
        before = repository_snapshot(self.root)
        legacy = run_hook(
            ROUTER,
            {
                "hook_event_name": "UserPromptSubmit",
                "cwd": str(self.root),
                "session_id": "legacy-session",
                "turn_id": "legacy-turn",
                "prompt": "[route:auth] Inspect it.",
            },
            self.data_root,
        )
        self.assertIn("LEGACY_ROUTES_UNSUPPORTED", additional_context(legacy))
        self.assertEqual(repository_snapshot(self.root), before)


if __name__ == "__main__":
    unittest.main()
