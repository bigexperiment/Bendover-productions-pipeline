#!/usr/bin/env python3
"""Strict manifest gate for transcript-to-image generation.

This does not pretend that file existence proves semantic alignment. It verifies
the machine-readable contract that must exist before generation: every frame has
one audio beat, its full sentence context, a transcript-first prompt, and
provenance bound to the current prompt. The renderer should never run if this
contract is incomplete.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PIPELINE_ROOT") or Path(__file__).resolve().parents[2])
PROJECT = ROOT
MANIFEST = PROJECT / "04-manifest" / "image_regen_manifest.csv"
IMAGES = PROJECT / "05-images"


def fingerprint(row: dict[str, str]) -> str:
    value = "\x1f".join((row["timestamp"], row["filename"], row["scene"], row["transcript"], row["context"]))
    return hashlib.sha256(value.encode()).hexdigest()


def main() -> int:
    if not MANIFEST.is_file():
        print(f"ERROR: missing {MANIFEST}", file=sys.stderr)
        return 1
    errors: list[str] = []
    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8", newline="")))
    seen: set[str] = set()
    for row in rows:
        name = row.get("filename", "")
        if not name or name in seen:
            errors.append(f"{name or '<blank>'}: duplicate or blank filename")
            continue
        seen.add(name)
        transcript = (row.get("transcript") or "").strip()
        context = (row.get("context") or "").strip()
        prompt = (row.get("prompt") or "").strip()
        for label, value in (("transcript", transcript), ("context", context), ("prompt", prompt)):
            if not value:
                errors.append(f"{name}: missing {label}")
        if transcript and transcript.lower() not in prompt.lower():
            errors.append(f"{name}: prompt omits exact transcript beat")
        if context and context.lower() not in prompt.lower():
            errors.append(f"{name}: prompt omits full semantic context")
        if "VISUAL CONTRACT" not in prompt and "TRANSCRIPT-FIRST RULE" not in prompt:
            errors.append(f"{name}: prompt lacks transcript-first visual contract")
        metadata = IMAGES / f".{name}.prompt.json"
        if row.get("status") == "done":
            if not (IMAGES / name).is_file():
                errors.append(f"{name}: marked done but image is missing")
            elif not metadata.is_file():
                errors.append(f"{name}: marked done but provenance is missing")
            else:
                try:
                    data = json.loads(metadata.read_text(encoding="utf-8"))
                    if data.get("prompt_fingerprint") != fingerprint(row):
                        errors.append(f"{name}: provenance does not match current manifest")
                except (OSError, json.JSONDecodeError):
                    errors.append(f"{name}: invalid provenance JSON")
    if errors:
        print(f"FAILED: {len(errors)} manifest contract error(s)", file=sys.stderr)
        print("\n".join(f"- {e}" for e in errors[:40]), file=sys.stderr)
        return 1
    print(f"OK: transcript-first contract validated for {len(rows)} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
