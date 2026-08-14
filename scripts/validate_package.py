#!/usr/bin/env python3
"""Validate the public CoH plugin package and its deterministic test suite."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLUGIN_ROOT = REPOSITORY_ROOT / "plugins" / "coh"
MARKETPLACE_PATH = REPOSITORY_ROOT / ".agents" / "plugins" / "marketplace.json"

EXPECTED_SKILLS = {"set-up", "build", "check"}
EXPECTED_HOOK_EVENTS = {"UserPromptSubmit", "Stop"}
ALLOWED_TOP_LEVEL_FILES = {"README.md", "CHANGELOG.md", "LICENSE"}
ALLOWED_DIRECTORIES = {
    ".codex-plugin",
    "assets",
    "hooks",
    "references",
    "schemas",
    "scripts",
    "skills",
}
ALLOWED_SUFFIXES = {".json", ".md", ".png", ".py", ".yaml"}
LOCAL_MODULES = {
    "bootstrap_transaction",
    "coh_hook_common",
    "harness_model",
    "record_episode_review",
    "stop_receipt_collector",
    "summarize_episode_reviews",
    "user_prompt_router",
    "validate_harness_model",
}


class DuplicateJsonKey(ValueError):
    """Raised when a JSON object repeats a field name."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey(key)
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )


def _local_markdown_targets(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    targets = {
        match.group(1)
        for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text)
    }
    targets.update(
        match.group(1)
        for match in re.finditer(r"`((?:\.\.?/)[^`\s]+)`", text)
    )
    return {
        target.split("#", 1)[0]
        for target in targets
        if target
        and not target.startswith(("#", "http://", "https://", "codex://"))
    }


def _validate_reference_closure(
    path: Path,
    plugin_root: Path,
    errors: list[str],
) -> None:
    for target in sorted(_local_markdown_targets(path)):
        candidate = (path.parent / target).resolve()
        try:
            candidate.relative_to(plugin_root)
        except ValueError:
            errors.append(f"{path}: reference escapes plugin root: {target}")
            continue
        if not candidate.exists():
            errors.append(f"{path}: unresolved local reference: {target}")


def _is_standard_library(module: str) -> bool:
    root = module.split(".", 1)[0]
    if root in LOCAL_MODULES or root == "__future__":
        return True
    if root in set(getattr(sys, "stdlib_module_names", ())):
        return True
    try:
        spec = importlib.util.find_spec(root)
    except (ImportError, AttributeError, ValueError):
        return False
    if spec is None or spec.origin is None:
        return False
    if spec.origin in {"built-in", "frozen"}:
        return True
    try:
        origin = Path(spec.origin).resolve()
        stdlib = Path(sysconfig.get_paths()["stdlib"]).resolve()
        origin.relative_to(stdlib)
    except (KeyError, OSError, ValueError):
        return False
    return "site-packages" not in origin.parts and "dist-packages" not in origin.parts


def _validate_python(path: Path, errors: list[str]) -> None:
    try:
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        errors.append(f"{path}: Python compile failed: {exc}")
        return

    for node in ast.walk(tree):
        module: str | None = None
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if not _is_standard_library(root):
                    errors.append(f"{path}: non-stdlib runtime import: {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            module = node.module
        if module:
            root = module.split(".", 1)[0]
            if not _is_standard_library(root):
                errors.append(f"{path}: non-stdlib runtime import: {module}")


def _validate_skill(skill_dir: Path, plugin_root: Path, errors: list[str]) -> None:
    skill_file = skill_dir / "SKILL.md"
    agent_file = skill_dir / "agents" / "openai.yaml"
    if not skill_file.is_file():
        errors.append(f"missing Skill entrypoint: {skill_file}")
        return
    if not agent_file.is_file():
        errors.append(f"missing Skill agent metadata: {agent_file}")
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        errors.append(f"{skill_file}: missing YAML frontmatter")
    name_match = re.search(r"(?m)^name:\s*([^\s]+)\s*$", text)
    if name_match is None or name_match.group(1) != skill_dir.name:
        errors.append(f"{skill_file}: frontmatter name must equal {skill_dir.name}")
    if not re.search(r"(?m)^description:\s*.+$", text):
        errors.append(f"{skill_file}: frontmatter description is required")
    _validate_reference_closure(skill_file, plugin_root, errors)


def validate_plugin(plugin_root: Path) -> list[str]:
    plugin_root = plugin_root.resolve()
    errors: list[str] = []
    required = {
        plugin_root / ".codex-plugin" / "plugin.json",
        plugin_root / "hooks" / "hooks.json",
        plugin_root / "README.md",
        plugin_root / "CHANGELOG.md",
        plugin_root / "LICENSE",
    }
    for path in sorted(required):
        if not path.is_file():
            errors.append(f"missing required package file: {path}")

    for path in sorted(plugin_root.rglob("*")):
        relative = path.relative_to(plugin_root)
        if path.is_symlink():
            errors.append(f"symlink is not allowed in package: {relative}")
            continue
        if path.is_dir():
            if path.name == "__pycache__":
                errors.append(f"generated cache directory in package: {relative}")
            continue
        if relative.parts[0] not in ALLOWED_DIRECTORIES and relative.as_posix() not in ALLOWED_TOP_LEVEL_FILES:
            errors.append(f"unexpected top-level package file: {relative}")
        if path.suffix not in ALLOWED_SUFFIXES and relative.as_posix() not in ALLOWED_TOP_LEVEL_FILES:
            errors.append(f"unexpected package file type: {relative}")
        if path.suffix in {".pyc", ".pyo"}:
            errors.append(f"compiled Python artifact in package: {relative}")

    manifest_path = plugin_root / ".codex-plugin" / "plugin.json"
    try:
        manifest = load_json(manifest_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKey) as exc:
        errors.append(f"{manifest_path}: invalid JSON: {exc}")
        manifest = {}
    if isinstance(manifest, dict):
        if manifest.get("name") != plugin_root.name:
            errors.append("plugin folder and plugin.json name must match")
        if manifest.get("skills") != "./skills/":
            errors.append("plugin.json skills must be ./skills/")
        if "hooks" in manifest:
            errors.append("plugin.json must not declare unsupported hooks field")
        interface = manifest.get("interface")
        if not isinstance(interface, dict):
            errors.append("plugin.json interface object is required")
        else:
            for key in ("composerIcon", "logo"):
                value = interface.get(key)
                if not isinstance(value, str) or not (plugin_root / value).is_file():
                    errors.append(f"plugin.json interface.{key} must resolve")

    skills_root = plugin_root / "skills"
    actual_skills = {
        path.name for path in skills_root.iterdir() if path.is_dir()
    } if skills_root.is_dir() else set()
    if actual_skills != EXPECTED_SKILLS:
        errors.append(
            f"callable Skills must be exactly {sorted(EXPECTED_SKILLS)}; got {sorted(actual_skills)}"
        )
    for skill_name in sorted(actual_skills):
        _validate_skill(skills_root / skill_name, plugin_root, errors)

    hooks_path = plugin_root / "hooks" / "hooks.json"
    try:
        hooks = load_json(hooks_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKey) as exc:
        errors.append(f"{hooks_path}: invalid JSON: {exc}")
        hooks = {}
    hook_map = hooks.get("hooks") if isinstance(hooks, dict) else None
    if not isinstance(hook_map, dict) or set(hook_map) != EXPECTED_HOOK_EVENTS:
        errors.append(f"hooks.json events must be exactly {sorted(EXPECTED_HOOK_EVENTS)}")
    elif isinstance(hook_map, dict):
        for event, groups in hook_map.items():
            commands = [
                hook.get("command")
                for group in groups if isinstance(group, dict)
                for hook in group.get("hooks", []) if isinstance(hook, dict)
            ]
            if len(commands) != 1 or not isinstance(commands[0], str):
                errors.append(f"hooks.json {event} must declare one command")
                continue
            matches = re.findall(r'\$\{PLUGIN_ROOT\}/([^"\s]+)', commands[0])
            if len(matches) != 1 or not (plugin_root / matches[0]).is_file():
                errors.append(f"hooks.json {event} command path must resolve")

    for path in sorted(plugin_root.rglob("*.json")):
        try:
            load_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKey) as exc:
            errors.append(f"{path}: invalid JSON: {exc}")
    for path in sorted(plugin_root.rglob("*.py")):
        _validate_python(path, errors)
    for path in (plugin_root / "README.md",):
        if path.is_file():
            _validate_reference_closure(path, plugin_root, errors)

    if isinstance(manifest, dict) and isinstance(manifest.get("version"), str):
        version = manifest["version"]
        changelog = plugin_root / "CHANGELOG.md"
        if changelog.is_file() and f"## {version}" not in changelog.read_text(encoding="utf-8"):
            errors.append("CHANGELOG.md must contain the plugin version heading")
    return errors


def validate_repository(repository_root: Path, plugin_root: Path) -> list[str]:
    errors: list[str] = []
    try:
        marketplace = load_json(MARKETPLACE_PATH)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKey) as exc:
        return [f"{MARKETPLACE_PATH}: invalid JSON: {exc}"]
    plugins = marketplace.get("plugins") if isinstance(marketplace, dict) else None
    entry = next(
        (
            item for item in plugins
            if isinstance(item, dict) and item.get("name") == "coh"
        ),
        None,
    ) if isinstance(plugins, list) else None
    if entry is None:
        errors.append("marketplace must contain the coh entry")
    else:
        source = entry.get("source")
        if source != {"source": "local", "path": "./plugins/coh"}:
            errors.append("marketplace coh source must be ./plugins/coh")
        policy = entry.get("policy")
        if not isinstance(policy, dict) or policy.get("installation") not in {
            "AVAILABLE", "INSTALLED_BY_DEFAULT", "NOT_AVAILABLE"
        } or policy.get("authentication") not in {"ON_INSTALL", "ON_USE"}:
            errors.append("marketplace coh policy is invalid")

    manifest = load_json(plugin_root / ".codex-plugin" / "plugin.json")
    version = manifest.get("version") if isinstance(manifest, dict) else None
    root_readme = repository_root / "README.md"
    if not isinstance(version, str) or f"`{version}`" not in root_readme.read_text(encoding="utf-8"):
        errors.append("root README version must match plugin.json")
    for path in (
        repository_root / "tests",
        repository_root / ".github" / "workflows" / "validate.yml",
    ):
        if not path.exists():
            errors.append(f"missing public assurance path: {path}")
    plugin_readme = (plugin_root / "README.md").read_text(encoding="utf-8")
    if "Native Windows" not in plugin_readme or "POSIX" not in plugin_readme:
        errors.append("plugin README must declare the host support boundary")
    if "READY only means" not in plugin_readme:
        errors.append("plugin README must define READY construction closure")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-root", type=Path, default=DEFAULT_PLUGIN_ROOT)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plugin_root = args.plugin_root.resolve()
    errors = validate_plugin(plugin_root)
    is_repository_package = plugin_root == DEFAULT_PLUGIN_ROOT.resolve()
    if is_repository_package:
        errors.extend(validate_repository(REPOSITORY_ROOT, plugin_root))
    if not errors and is_repository_package and not args.skip_tests:
        test_environment = os.environ.copy()
        test_environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                str(REPOSITORY_ROOT / "tests"),
                "-v",
            ],
            cwd=REPOSITORY_ROOT,
            env=test_environment,
            check=False,
        )
        if completed.returncode != 0:
            errors.append("public deterministic test suite failed")

    result = {
        "ok": not errors,
        "plugin_root": str(plugin_root),
        "errors": errors,
    }
    if args.json:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    elif errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
    else:
        print("PASS: CoH package structure, runtime imports, public fixtures, and deterministic tests")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
