#!/usr/bin/env python3
"""Validate and summarize privacy-bounded real-world harness episode reviews."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
DATE_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)
TASK_KINDS = {"feature", "bugfix", "refactor", "maintenance", "investigation", "other"}
EVIDENCE_MODES = {"machine", "human-review", "combined"}
DIMENSIONS = (
    "route-selection",
    "guide-use",
    "authority-selection",
    "implementation-correctness",
    "semantic-validation",
    "validation-integrity",
    "requirement-alignment",
    "clarification-quality",
    "evidence-calibration",
    "followup-actionability",
)
OUTCOMES = ("met", "partial", "missed", "unknown", "not-applicable")
EVIDENCE_KINDS = {
    "receipt",
    "official-evaluator",
    "test-report",
    "diff-review",
    "trace-review",
    "user-feedback",
    "human-review",
}
REVIEW_MIN_EPISODES = 3
REVIEW_MIN_TASKS = 2


class ReviewError(ValueError):
    """A stable episode-review contract failure."""


def exact_keys(
    value: dict[str, Any], required: set[str], optional: set[str], label: str
) -> None:
    keys = set(value)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        raise ReviewError(f"{label}_FIELDS")


def identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ReviewError(label)
    return value


def digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ReviewError(label)
    return value


def timestamp(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 40 or not DATE_TIME.fullmatch(value):
        raise ReviewError("RECORDED_AT")
    try:
        normalized = value.replace("t", "T").replace("z", "Z")
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewError("RECORDED_AT") from exc
    if parsed.tzinfo is None:
        raise ReviewError("RECORDED_AT")
    return value


def decode_record(text: str) -> Any:
    """Decode strict JSON without accepting duplicate keys or non-JSON constants."""

    def object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReviewError("DUPLICATE_JSON_FIELD")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise ReviewError("INVALID_JSON_CONSTANT")

    return json.loads(
        text,
        object_pairs_hook=object_from_pairs,
        parse_constant=reject_constant,
    )


def validate_record(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ReviewError("EPISODE_OBJECT")
    required = {
        "schema_version",
        "episode_id",
        "recorded_at",
        "repo_id",
        "host",
        "route_id",
        "task_kind",
        "task_ref_sha256",
        "registry_sha256",
        "guide_sha256",
        "evidence_mode",
        "dimensions",
        "candidate_codes",
        "guide_update_authorized",
    }
    exact_keys(raw, required, set(), "EPISODE")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise ReviewError("SCHEMA_VERSION")
    if not isinstance(raw["task_kind"], str) or raw["task_kind"] not in TASK_KINDS:
        raise ReviewError("TASK_KIND")
    if not isinstance(raw["evidence_mode"], str) or raw["evidence_mode"] not in EVIDENCE_MODES:
        raise ReviewError("EVIDENCE_MODE")
    if raw["guide_update_authorized"] is not False:
        raise ReviewError("GUIDE_UPDATE_AUTHORIZATION")

    dimensions_raw = raw["dimensions"]
    if not isinstance(dimensions_raw, list) or not 1 <= len(dimensions_raw) <= len(DIMENSIONS):
        raise ReviewError("DIMENSIONS")
    dimensions: list[dict[str, Any]] = []
    seen_dimensions: set[str] = set()
    for item in dimensions_raw:
        if not isinstance(item, dict):
            raise ReviewError("DIMENSION_OBJECT")
        exact_keys(item, {"id", "outcome", "evidence_refs"}, set(), "DIMENSION")
        dimension_id = item["id"]
        if dimension_id not in DIMENSIONS or dimension_id in seen_dimensions:
            raise ReviewError("DIMENSION_ID")
        seen_dimensions.add(dimension_id)
        if item["outcome"] not in OUTCOMES:
            raise ReviewError("DIMENSION_OUTCOME")
        refs_raw = item["evidence_refs"]
        if not isinstance(refs_raw, list) or not 1 <= len(refs_raw) <= 8:
            raise ReviewError("EVIDENCE_REFS")
        refs: list[dict[str, str]] = []
        for ref in refs_raw:
            if not isinstance(ref, dict):
                raise ReviewError("EVIDENCE_REF_OBJECT")
            exact_keys(ref, {"kind", "sha256"}, set(), "EVIDENCE_REF")
            if not isinstance(ref["kind"], str) or ref["kind"] not in EVIDENCE_KINDS:
                raise ReviewError("EVIDENCE_KIND")
            refs.append({"kind": ref["kind"], "sha256": digest(ref["sha256"], "EVIDENCE_SHA256")})
        dimensions.append(
            {"id": dimension_id, "outcome": item["outcome"], "evidence_refs": refs}
        )

    candidates_raw = raw["candidate_codes"]
    if not isinstance(candidates_raw, list) or len(candidates_raw) > 16:
        raise ReviewError("CANDIDATE_CODES")
    candidates = [identifier(value, "CANDIDATE_CODE") for value in candidates_raw]
    if len(set(candidates)) != len(candidates):
        raise ReviewError("DUPLICATE_CANDIDATE_CODE")

    return {
        "schema_version": 1,
        "episode_id": identifier(raw["episode_id"], "EPISODE_ID"),
        "recorded_at": timestamp(raw["recorded_at"]),
        "repo_id": digest(raw["repo_id"], "REPO_ID"),
        "host": identifier(raw["host"], "HOST"),
        "route_id": identifier(raw["route_id"], "ROUTE_ID"),
        "task_kind": raw["task_kind"],
        "task_ref_sha256": digest(raw["task_ref_sha256"], "TASK_REF_SHA256"),
        "registry_sha256": digest(raw["registry_sha256"], "REGISTRY_SHA256"),
        "guide_sha256": digest(raw["guide_sha256"], "GUIDE_SHA256"),
        "evidence_mode": raw["evidence_mode"],
        "dimensions": dimensions,
        "candidate_codes": candidates,
        "guide_update_authorized": False,
    }


def load_records(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    episode_ids: set[str] = set()
    for path in paths:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                raw = decode_record(line)
                record = validate_record(raw)
            except (json.JSONDecodeError, ReviewError) as exc:
                raise ReviewError(f"{path.name}:{line_number}:{exc}") from exc
            if record["episode_id"] in episode_ids:
                raise ReviewError(f"{path.name}:{line_number}:DUPLICATE_EPISODE_ID")
            episode_ids.add(record["episode_id"])
            records.append(record)
    if not records:
        raise ReviewError("NO_EPISODES")
    return records


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    dimension_counts = {name: Counter() for name in DIMENSIONS}
    hosts = Counter()
    task_kinds = Counter()
    candidate_episodes: dict[str, set[str]] = defaultdict(set)
    candidate_tasks: dict[str, set[str]] = defaultdict(set)
    guide_revisions: set[str] = set()
    canonical_records: list[str] = []

    for record in records:
        hosts[record["host"]] += 1
        task_kinds[record["task_kind"]] += 1
        guide_revisions.add(record["guide_sha256"])
        canonical_records.append(json.dumps(record, sort_keys=True, separators=(",", ":")))
        for item in record["dimensions"]:
            dimension_counts[item["id"]][item["outcome"]] += 1
        for code in record["candidate_codes"]:
            candidate_episodes[code].add(record["episode_id"])
            candidate_tasks[code].add(record["task_ref_sha256"])

    dimensions = []
    for name in DIMENSIONS:
        counts = dimension_counts[name]
        assessed = counts["met"] + counts["partial"] + counts["missed"]
        dimensions.append(
            {
                "id": name,
                "assessed": assessed,
                **{outcome: counts[outcome] for outcome in OUTCOMES},
                "met_rate": round(counts["met"] / assessed, 4) if assessed else None,
            }
        )

    candidates = []
    for code in sorted(candidate_episodes):
        episode_count = len(candidate_episodes[code])
        task_count = len(candidate_tasks[code])
        candidates.append(
            {
                "code": code,
                "episodes": episode_count,
                "distinct_tasks": task_count,
                "eligible_for_human_review": (
                    episode_count >= REVIEW_MIN_EPISODES and task_count >= REVIEW_MIN_TASKS
                ),
                "guide_update_authorized": False,
            }
        )

    bundle = "\n".join(sorted(canonical_records)).encode("utf-8")
    return {
        "schema_version": 1,
        "episodes": len(records),
        "review_bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        "hosts": dict(sorted(hosts.items())),
        "task_kinds": dict(sorted(task_kinds.items())),
        "guide_revisions": len(guide_revisions),
        "dimensions": dimensions,
        "candidate_patterns": candidates,
        "review_threshold": {
            "minimum_episodes": REVIEW_MIN_EPISODES,
            "minimum_distinct_tasks": REVIEW_MIN_TASKS,
            "authorizes_update": False,
        },
        "claim_boundary": (
            "Dimension outcomes are descriptive, evidence-linked review labels. "
            "No composite score or candidate automatically authorizes a Guide update."
        ),
    }


def markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Real-world harness episode summary",
        "",
        f"Episodes: **{summary['episodes']}** · Guide revisions: **{summary['guide_revisions']}**",
        "",
        "| Dimension | Assessed | Met | Partial | Missed | Unknown | N/A |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["dimensions"]:
        lines.append(
            f"| {row['id']} | {row['assessed']} | {row['met']} | {row['partial']} | "
            f"{row['missed']} | {row['unknown']} | {row['not-applicable']} |"
        )
    lines.extend(["", "## Report-only candidate patterns", ""])
    if summary["candidate_patterns"]:
        lines.extend(
            [
                "| Candidate | Episodes | Tasks | Eligible for human review |",
                "| --- | ---: | ---: | --- |",
            ]
        )
        for row in summary["candidate_patterns"]:
            lines.append(
                f"| {row['code']} | {row['episodes']} | {row['distinct_tasks']} | "
                f"{'yes' if row['eligible_for_human_review'] else 'no'} |"
            )
    else:
        lines.append("None.")
    lines.extend(["", f"> {summary['claim_boundary']}", ""])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="JSONL episode-review files")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown")
    parser.add_argument("--json-output", type=Path, help="Write the JSON summary")
    parser.add_argument("--markdown-output", type=Path, help="Write the Markdown summary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        records = load_records(args.inputs)
        result = summarize(records)
    except (OSError, ReviewError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    json_text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    markdown_text = markdown(result)
    if args.json_output:
        args.json_output.write_text(json_text, encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.write_text(markdown_text, encoding="utf-8")
    print(json_text if args.json else markdown_text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
