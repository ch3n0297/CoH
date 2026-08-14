from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common import MODEL_VALIDATOR, PLUGIN_ROOT, copy_fixture, load_json

from coh_hook_common import ContractError
from harness_model import (
    CONSTRUCTION_STATUSES,
    EVIDENCE_POLICIES,
    MODEL_SCHEMA_VERSION,
    ROUTING_PROJECTION_VERSION,
    validate_model,
)


class ModelContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="coh-model-contract-")
        self.root = copy_fixture(Path(self.temporary.name) / "repository")
        self.model = load_json(self.root / ".coh" / "model.json")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_ready_fixture_passes_dynamic_validator(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(MODEL_VALIDATOR), str(self.root), "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertTrue(result["valid"])
        self.assertEqual(result["construction_status"], "READY")
        self.assertEqual(result["routes"], 1)
        self.assertEqual(result["sensors"], 1)

    def test_selected_schema_and_runtime_constants_match(self) -> None:
        schema = load_json(PLUGIN_ROOT / "schemas" / "harness-model.schema.json")
        self.assertEqual(
            schema["properties"]["schema_version"]["const"],
            MODEL_SCHEMA_VERSION,
        )
        self.assertEqual(
            set(schema["$defs"]["construction"]["properties"]["status"]["enum"]),
            CONSTRUCTION_STATUSES,
        )
        self.assertEqual(
            set(schema["$defs"]["route"]["properties"]["evidence_policy"]["enum"]),
            EVIDENCE_POLICIES,
        )
        self.assertEqual(ROUTING_PROJECTION_VERSION, 2)

    def test_schema_shape_violation_is_rejected_dynamically(self) -> None:
        invalid = copy.deepcopy(self.model)
        invalid["unexpected"] = True
        with self.assertRaises(ContractError) as raised:
            validate_model(self.root, invalid)
        self.assertEqual(raised.exception.code, "MODEL_FIELDS")

    def test_schema_valid_shape_can_still_fail_live_semantics(self) -> None:
        (self.root / "CODEBASE_MAP.md").write_text(
            "# Fixture codebase map\nanchor removed\n",
            encoding="utf-8",
        )
        with self.assertRaises(ContractError) as raised:
            validate_model(self.root, self.model)
        self.assertEqual(raised.exception.code, "AUTHORITY_ANCHOR")


if __name__ == "__main__":
    unittest.main()
