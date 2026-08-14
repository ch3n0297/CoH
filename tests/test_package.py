from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

from common import PLUGIN_ROOT, REPOSITORY_ROOT


VALIDATOR_PATH = REPOSITORY_ROOT / "scripts" / "validate_package.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_package", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load package validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackageValidationTests(unittest.TestCase):
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
            cache.mkdir()
            (cache / "runtime.pyc").write_bytes(b"not-a-real-bytecode-file")
            errors = validator.validate_plugin(installed)
            self.assertTrue(
                any("generated cache directory" in error for error in errors),
                errors,
            )


if __name__ == "__main__":
    unittest.main()
