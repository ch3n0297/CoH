from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

from common import PLUGIN_ROOT, REPOSITORY_ROOT, load_json

import build_plan


VALIDATOR_PATH = REPOSITORY_ROOT / "scripts" / "validate_package.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_package", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load package validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackageValidationTests(unittest.TestCase):
    def test_build_plan_schema_matches_runtime_contract(self) -> None:
        schema = load_json(PLUGIN_ROOT / "schemas" / "build-plan.schema.json")
        properties = schema["properties"]
        definitions = schema["$defs"]
        self.assertEqual(
            properties["plan_version"]["const"],
            build_plan.BUILD_PLAN_VERSION,
        )
        self.assertNotIn("legacy_routes", properties)
        self.assertEqual(
            {
                definitions["adoptOperation"]["allOf"][1]["properties"]["mode"]["const"],
                definitions["createOperation"]["allOf"][1]["properties"]["mode"]["const"],
            },
            build_plan.MODES,
        )
        self.assertEqual(
            set(properties["proof_boundaries"]["items"]["enum"]),
            set(build_plan.PROOF_LAYERS),
        )

    def test_current_plugin_tree_is_valid(self) -> None:
        validator = load_validator()
        self.assertEqual(validator.validate_plugin(PLUGIN_ROOT), [])

    def test_isolated_installed_tree_is_self_contained(self) -> None:
        validator = load_validator()
        with tempfile.TemporaryDirectory(prefix="coh-installed-tree-") as temporary:
            installed = Path(temporary) / "coh"
            shutil.copytree(PLUGIN_ROOT, installed)
            self.assertEqual(validator.validate_plugin(installed), [])

    def test_compiled_artifact_is_rejected(self) -> None:
        validator = load_validator()
        with tempfile.TemporaryDirectory(prefix="coh-package-negative-") as temporary:
            installed = Path(temporary) / "coh"
            shutil.copytree(PLUGIN_ROOT, installed)
            cache = installed / "hooks" / "__pycache__"
            cache.mkdir(exist_ok=True)
            (cache / "runtime.pyc").write_bytes(b"not-a-real-bytecode-file")
            errors = validator.validate_plugin(installed)
            self.assertTrue(
                any("generated cache directory" in error for error in errors),
                errors,
            )


if __name__ == "__main__":
    unittest.main()
