from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from common import (
    FIXTURE_ROOT,
    copy_fixture,
    git,
    load_json,
    repository_snapshot,
    sha256_file,
    write_json,
)

import bootstrap_transaction as bootstrap
import build_plan
from coh_hook_common import repository_id


class BootstrapTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_task_id = os.environ.get("CODEX_THREAD_ID")
        os.environ["CODEX_THREAD_ID"] = "coh-bootstrap-test-task"
        self.temporary = tempfile.TemporaryDirectory(prefix="coh-bootstrap-")
        base = Path(self.temporary.name)
        self.root = copy_fixture(
            base / "repository",
            include_model=False,
            include_guide=False,
        )
        self.plan_root = base / "plan"
        self.plan_root.mkdir()
        (self.plan_root / "guide.md").write_text(
            "# Authentication fixture Guide\n\nCreated by an accepted Build Plan.\n",
            encoding="utf-8",
        )
        model = load_json(FIXTURE_ROOT / ".coh" / "model.json")
        write_json(self.plan_root / "model.json", model)
        model_source = self.plan_root / "model.json"
        guide_source = self.plan_root / "guide.md"
        observed_inputs = []
        for relative in (
            ".coh/model.json",
            "AGENTS.md",
            "CODEBASE_MAP.md",
            "docs/AUTH_GUIDE.md",
            "scripts/validate.sh",
        ):
            candidate = self.root / relative
            if candidate.is_file():
                observed_inputs.append(
                    {
                        "path": relative,
                        "state": "PRESENT",
                        "sha256": sha256_file(candidate),
                    }
                )
            else:
                observed_inputs.append({"path": relative, "state": "ABSENT"})
        self.plan_payload = {
            "plan_version": 1,
            "task_id_sha256": build_plan.current_task_id_sha256(),
            "repository_id": repository_id(self.root),
            "base_head_sha": git(self.root, "rev-parse", "HEAD"),
            "observed_inputs": observed_inputs,
            "model": {
                "source": "model.json",
                "raw_sha256": sha256_file(model_source),
                "semantic_sha256": build_plan.semantic_sha256(model),
            },
            "operations": [
                    {
                        "id": "create-auth-guide",
                        "role": "guide",
                        "mode": "create",
                        "path": "docs/AUTH_GUIDE.md",
                        "source": "guide.md",
                        "expected_sha256": sha256_file(guide_source),
                        "permissions": "file",
                    },
                    {
                        "id": "adopt-validation",
                        "role": "sensor",
                        "mode": "adopt",
                        "path": "scripts/validate.sh",
                        "expected_sha256": sha256_file(
                            self.root / "scripts" / "validate.sh"
                        ),
                    },
            ],
            "proof_boundaries": ["static", "runtime"],
        }
        self.plan = self.plan_root / "plan.json"
        self.write_current_plan()

    def write_current_plan(self) -> None:
        observed_inputs = []
        for item in self.plan_payload["observed_inputs"]:
            candidate = self.root / item["path"]
            if candidate.is_file():
                observed_inputs.append(
                    {
                        "path": item["path"],
                        "state": "PRESENT",
                        "sha256": sha256_file(candidate),
                    }
                )
            else:
                observed_inputs.append({"path": item["path"], "state": "ABSENT"})
        self.plan_payload["observed_inputs"] = observed_inputs
        self.plan.write_bytes(build_plan.canonical_json(self.plan_payload))
        self.accepted_plan_sha256 = hashlib.sha256(self.plan.read_bytes()).hexdigest()

    def tearDown(self) -> None:
        self.temporary.cleanup()
        if self.previous_task_id is None:
            os.environ.pop("CODEX_THREAD_ID", None)
        else:
            os.environ["CODEX_THREAD_ID"] = self.previous_task_id

    def prepare_and_apply(self) -> str:
        prepared = bootstrap.prepare_repository(
            self.root,
            self.plan,
            self.accepted_plan_sha256,
        )
        self.assertEqual(prepared["status"], "PREPARED")
        transaction_id = prepared["transaction_id"]
        self.assertIsInstance(transaction_id, str)
        self.assertFalse((self.root / ".coh" / "model.json").exists())
        applied = bootstrap.apply_repository(self.root, transaction_id)
        self.assertEqual(applied["status"], "ARTIFACTS_READY")
        self.assertTrue((self.root / "docs" / "AUTH_GUIDE.md").is_file())
        self.assertFalse((self.root / ".coh" / "model.json").exists())
        return transaction_id

    def test_model_last_commit_and_semantic_noop(self) -> None:
        transaction_id = self.prepare_and_apply()
        published = bootstrap.publish_repository(self.root, transaction_id, None)
        self.assertEqual(published["status"], "COMMITTED")
        self.assertTrue((self.root / ".coh" / "model.json").is_file())
        self.assertEqual(
            bootstrap.status_repository(self.root, None)["status"],
            "NO_ACTIVE_TRANSACTION",
        )
        with self.assertRaises(bootstrap.BootstrapError) as raised:
            bootstrap.prepare_repository(
                self.root,
                self.plan,
                self.accepted_plan_sha256,
            )
        self.assertEqual(raised.exception.code, "PLAN_INPUT_CHANGED")
        self.write_current_plan()
        noop = bootstrap.prepare_repository(
            self.root, self.plan, self.accepted_plan_sha256
        )
        self.assertEqual(noop, {"status": "NOOP", "transaction_id": None})

    def test_publish_failure_can_resume_without_clobber(self) -> None:
        transaction_id = self.prepare_and_apply()
        original = bootstrap._publish_no_clobber

        def fail_model_publish(root, relative, data, mode):
            if relative == bootstrap.MODEL_RELATIVE_PATH:
                raise bootstrap.BootstrapError("IO_FAILURE")
            return original(root, relative, data, mode)

        bootstrap._publish_no_clobber = fail_model_publish
        try:
            with self.assertRaises(bootstrap.BootstrapError) as raised:
                bootstrap.publish_repository(self.root, transaction_id, None)
            self.assertEqual(raised.exception.code, "IO_FAILURE")
        finally:
            bootstrap._publish_no_clobber = original

        status = bootstrap.status_repository(self.root, transaction_id)
        self.assertEqual(status["status"], "RECOVERY_REQUIRED")
        recovered = bootstrap.recover_repository(self.root, transaction_id, "resume")
        self.assertEqual(recovered["status"], "COMMITTED")
        self.assertTrue((self.root / ".coh" / "model.json").is_file())

    def test_concurrent_target_is_preserved_and_fails_closed(self) -> None:
        prepared = bootstrap.prepare_repository(
            self.root,
            self.plan,
            self.accepted_plan_sha256,
        )
        transaction_id = prepared["transaction_id"]
        concurrent = self.root / "docs" / "AUTH_GUIDE.md"
        concurrent.write_text("# Concurrent human-owned Guide\n", encoding="utf-8")
        with self.assertRaises(bootstrap.BootstrapError) as raised:
            bootstrap.apply_repository(self.root, transaction_id)
        self.assertEqual(raised.exception.code, "PRECONDITION_CHANGED")
        self.assertEqual(
            concurrent.read_text(encoding="utf-8"),
            "# Concurrent human-owned Guide\n",
        )
        self.assertFalse((self.root / ".coh" / "model.json").exists())
        self.assertEqual(
            bootstrap.status_repository(self.root, transaction_id)["status"],
            "RECOVERY_REQUIRED",
        )

    def test_accepted_digest_must_match_canonical_plan_bytes(self) -> None:
        changed = copy.deepcopy(self.plan_payload)
        changed["proof_boundaries"] = ["static"]
        self.plan.write_bytes(build_plan.canonical_json(changed))
        with self.assertRaises(bootstrap.BootstrapError) as raised:
            bootstrap.prepare_repository(
                self.root,
                self.plan,
                self.accepted_plan_sha256,
            )
        self.assertEqual(raised.exception.code, "PLAN_ACCEPTANCE_MISMATCH")

    def test_noncanonical_plan_is_rejected(self) -> None:
        write_json(self.plan, self.plan_payload)
        digest = hashlib.sha256(self.plan.read_bytes()).hexdigest()
        with self.assertRaises(bootstrap.BootstrapError) as raised:
            bootstrap.prepare_repository(self.root, self.plan, digest)
        self.assertEqual(raised.exception.code, "PLAN_NOT_CANONICAL")

    def test_cross_task_and_cross_repository_replay_are_rejected(self) -> None:
        os.environ["CODEX_THREAD_ID"] = "another-task"
        with self.assertRaises(bootstrap.BootstrapError) as task_error:
            bootstrap.prepare_repository(
                self.root,
                self.plan,
                self.accepted_plan_sha256,
            )
        self.assertEqual(task_error.exception.code, "PLAN_TASK_MISMATCH")

        os.environ["CODEX_THREAD_ID"] = "coh-bootstrap-test-task"
        second_root = copy_fixture(
            Path(self.temporary.name) / "second-repository",
            include_model=False,
            include_guide=False,
        )
        with self.assertRaises(bootstrap.BootstrapError) as repository_error:
            bootstrap.prepare_repository(
                second_root,
                self.plan,
                self.accepted_plan_sha256,
            )
        self.assertEqual(
            repository_error.exception.code,
            "PLAN_REPOSITORY_MISMATCH",
        )

    def test_stale_head_and_changed_authority_are_rejected(self) -> None:
        (self.root / "src" / "auth" / "module.py").write_text(
            "VALUE = 2\n",
            encoding="utf-8",
        )
        git(self.root, "add", "src/auth/module.py")
        git(self.root, "commit", "-q", "-m", "advance head")
        with self.assertRaises(bootstrap.BootstrapError) as head_error:
            bootstrap.prepare_repository(
                self.root,
                self.plan,
                self.accepted_plan_sha256,
            )
        self.assertEqual(head_error.exception.code, "PLAN_HEAD_STALE")

        self.plan_payload["base_head_sha"] = git(self.root, "rev-parse", "HEAD")
        self.write_current_plan()
        (self.root / "AGENTS.md").write_text(
            "# Concurrent authority change\n",
            encoding="utf-8",
        )
        with self.assertRaises(bootstrap.BootstrapError) as input_error:
            bootstrap.prepare_repository(
                self.root,
                self.plan,
                self.accepted_plan_sha256,
            )
        self.assertEqual(input_error.exception.code, "PLAN_INPUT_CHANGED")

    def test_legacy_plan_and_repository_marker_are_rejected_without_writes(self) -> None:
        legacy_plan = copy.deepcopy(self.plan_payload)
        legacy_plan["legacy_routes"] = {
            "path": ".coh/routes.json",
            "expected_sha256": "0" * 64,
        }
        self.plan.write_bytes(build_plan.canonical_json(legacy_plan))
        digest = hashlib.sha256(self.plan.read_bytes()).hexdigest()
        before = repository_snapshot(self.root)
        with self.assertRaises(bootstrap.BootstrapError) as plan_error:
            bootstrap.prepare_repository(self.root, self.plan, digest)
        self.assertEqual(plan_error.exception.code, "PLAN_INVALID")
        self.assertEqual(repository_snapshot(self.root), before)

        self.write_current_plan()
        legacy_routes = self.root / ".coh" / "routes.json"
        legacy_routes.write_text('{"schema_version":1}\n', encoding="utf-8")
        before = repository_snapshot(self.root)
        with self.assertRaises(bootstrap.BootstrapError) as marker_error:
            bootstrap.prepare_repository(
                self.root,
                self.plan,
                self.accepted_plan_sha256,
            )
        self.assertEqual(marker_error.exception.code, "LEGACY_ROUTES_UNSUPPORTED")
        self.assertEqual(repository_snapshot(self.root), before)

    def test_existing_legacy_journal_is_rollback_only(self) -> None:
        prepared = bootstrap.prepare_repository(
            self.root,
            self.plan,
            self.accepted_plan_sha256,
        )
        transaction_id = prepared["transaction_id"]
        transaction = self.root / ".coh" / ".bootstrap" / transaction_id
        legacy_bytes = b'{"schema_version":1}\n'
        backup = transaction / "backup" / "routes.json"
        backup.write_bytes(legacy_bytes)
        journal_path = transaction / "journal.json"
        journal = load_json(journal_path)
        journal["state"] = "LEGACY_RETIRED"
        journal["legacy_routes"] = {
            "expected_sha256": hashlib.sha256(legacy_bytes).hexdigest(),
            "mode": 0o644,
            "state": "RETIRED",
        }
        write_json(journal_path, journal)

        before = repository_snapshot(self.root)
        for operation in (
            lambda: bootstrap.apply_repository(self.root, transaction_id),
            lambda: bootstrap.publish_repository(self.root, transaction_id, None),
            lambda: bootstrap.recover_repository(self.root, transaction_id, "resume"),
        ):
            with self.assertRaises(bootstrap.BootstrapError) as raised:
                operation()
            self.assertEqual(
                raised.exception.code,
                "LEGACY_RECOVERY_ROLLBACK_ONLY",
            )
            self.assertEqual(repository_snapshot(self.root), before)

        status = bootstrap.status_repository(self.root, transaction_id)
        self.assertEqual(status["status"], "LEGACY_RETIRED")
        rolled_back = bootstrap.recover_repository(
            self.root,
            transaction_id,
            "rollback",
        )
        self.assertEqual(rolled_back["status"], "ROLLED_BACK")
        self.assertEqual((self.root / ".coh" / "routes.json").read_bytes(), legacy_bytes)
        self.assertFalse(transaction.exists())


if __name__ == "__main__":
    unittest.main()
