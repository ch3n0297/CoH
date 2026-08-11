#!/usr/bin/env python3
"""Compatibility validator for a Harness Model or legacy route registry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))

from coh_hook_common import (
    ContractError,
    MODEL_RELATIVE_PATH,
    load_legacy_registry,
    load_registry,
    worktree_sha256,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "repository",
        help="Repository root containing model.json or a legacy routes.json",
    )
    parser.add_argument("--json", action="store_true", help="Emit one machine-readable result")
    parser.add_argument(
        "--worktree-sha256",
        action="store_true",
        help="Also compute the bounded COH_WORKTREE_V2 digest",
    )
    parser.add_argument(
        "--validation-id",
        help="Select the validation whose receipt path is excluded from the worktree digest",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        root = Path(args.repository).expanduser().resolve(strict=True)
        if (root / MODEL_RELATIVE_PATH).is_file():
            registry, digest = load_registry(root)
            source = "model"
        else:
            registry, digest = load_legacy_registry(root)
            source = "legacy-routes"
        worktree_digest = None
        if args.validation_id and not args.worktree_sha256:
            raise ContractError("VALIDATION_ID_REQUIRES_WORKTREE_DIGEST")
        if args.worktree_sha256:
            if args.validation_id:
                selected = registry["validation_by_id"].get(args.validation_id)
                if selected is None:
                    raise ContractError("UNKNOWN_VALIDATION_ID")
                excluded = selected.get("receipt_path")
            else:
                receipt_paths = {
                    item["receipt_path"]
                    for item in registry["validations"]
                    if item.get("receipt_path") is not None
                }
                if len(receipt_paths) > 1:
                    raise ContractError("MULTIPLE_RECEIPT_PATHS_REQUIRE_VALIDATION_ID")
                excluded = next(iter(receipt_paths), None)
            worktree_digest = worktree_sha256(root, excluded)
    except (OSError, ContractError) as exc:
        code = exc.code if isinstance(exc, ContractError) else "REPOSITORY_INVALID"
        result = {"valid": False, "code": code}
        if args.json:
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        else:
            print(f"FAIL: {code}", file=sys.stderr)
        return 1

    result = {
        "valid": True,
        "enabled": registry["enabled"],
        "routes": len(registry["routes"]),
        "validations": len(registry["validations"]),
        "registry_sha256": digest,
        "projection_version": registry.get("projection_version"),
        "source": source,
        "worktree_sha256": worktree_digest,
    }
    if args.json:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        print(
            "PASS: Harness routing projection is valid "
            f"(enabled={result['enabled']}, routes={result['routes']}, "
            f"validations={result['validations']}, source={source}, sha256={digest})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
