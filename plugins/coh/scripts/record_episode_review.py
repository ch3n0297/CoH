#!/usr/bin/env python3
"""Validate one v1 episode review and atomically append canonical JSONL."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

from summarize_episode_reviews import ReviewError, decode_record, validate_record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="JSON episode-review record")
    parser.add_argument("--output", required=True, type=Path, help="JSONL review collection")
    return parser.parse_args()


def read_input(path: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ReviewError("INPUT_UTF8") from exc
    return validate_record(decode_record(text))


def read_existing(path: Path) -> tuple[bytes, set[str], int | None]:
    if not path.exists():
        return b"", set(), None
    original = path.read_bytes()
    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReviewError("OUTPUT_UTF8") from exc

    episode_ids: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = validate_record(decode_record(line))
        except (json.JSONDecodeError, ReviewError) as exc:
            raise ReviewError(f"OUTPUT_LINE_{line_number}:{exc}") from exc
        episode_id = record["episode_id"]
        if episode_id in episode_ids:
            raise ReviewError(f"OUTPUT_LINE_{line_number}:DUPLICATE_EPISODE_ID")
        episode_ids.add(episode_id)
    mode = stat.S_IMODE(path.stat().st_mode)
    return original, episode_ids, mode


def append_atomically(path: Path, original: bytes, line: bytes, mode: int | None) -> None:
    descriptor = -1
    temporary_name = ""
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        if mode is not None:
            os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(original)
            if original and not original.endswith((b"\n", b"\r")):
                stream.write(b"\n")
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        temporary_name = ""
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def main() -> int:
    args = parse_args()
    try:
        destination = args.output.resolve()
        record = read_input(args.input)
        original, episode_ids, mode = read_existing(destination)
        if record["episode_id"] in episode_ids:
            raise ReviewError("DUPLICATE_EPISODE_ID")
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        append_atomically(destination, original, canonical + b"\n", mode)
    except (json.JSONDecodeError, OSError, ReviewError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
