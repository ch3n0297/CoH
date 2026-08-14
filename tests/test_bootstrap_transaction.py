from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common import FIXTURE_ROOT, copy_fixture, load_json, sha256_file, write_json

import bootstrap_transaction as bootstrap


class BootstrapTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
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
        write_json(
            self.plan_root / "plan.json",
            {
                "schema_version": 1,
                "model_source": "model.json",
                "artifacts": [
                    {
                        "id": "create-auth-guide",
                        "role": "guide",
                        "mode": "create",
                        "path": "docs/AUTH_GUIDE.md",
                        "source": "guide.md",
                        "permissions": "file"
                    },
                    {
                        "id": "adopt-validation",
                        "role": "sensor",
                        "mode": "adopt",
                        "path": "scripts/validate.sh",
                        "expected_sha256": sha256_file(self.root / "scripts" / "validate.sh")
                    }
                ]
            },
        )
        self.plan = self.plan_root / "plan.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def prepare_and_apply(self) -> str:
        prepared = bootstrap.prepare_repository(self.root, self.plan)
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
        noop = bootstrap.prepare_repository(self.root, self.plan)
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
        prepared = bootstrap.prepare_repository(self.root, self.plan)
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


if __name__ == "__main__":
    unittest.main()
