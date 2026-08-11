#!/usr/bin/env python3
"""Validate one repository's canonical .coh/model.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))

from harness_model import load_model
from coh_hook_common import ContractError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "repository", help="Repository root containing .coh/model.json"
    )
    parser.add_argument("--json", action="store_true", help="Emit one machine-readable result")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        root = Path(args.repository).expanduser().resolve(strict=True)
        projection, digest = load_model(root)
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
        "projection_version": projection["projection_version"],
        "enabled": projection["enabled"],
        "runtime_eligible": projection["runtime_eligible"],
        "construction_status": projection["construction_status"],
        "blockers": projection["blockers"],
        "routes": len(projection["routes"]),
        "sensors": len(projection["validations"]),
        "routing_projection_sha256": digest,
    }
    if args.json:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        print(
            "PASS: Harness Model is valid "
            f"(enabled={result['enabled']}, "
            f"construction={result['construction_status']}, "
            f"routes={result['routes']}, sensors={result['sensors']}, "
            f"routing_projection_sha256={digest})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
