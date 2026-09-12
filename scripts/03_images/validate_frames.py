#!/usr/bin/env python3
"""Fail closed when a render would use missing or reused frame images."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_ROOT / "scripts"))
from lib.image_prompt import FrameJob  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    project = args.project
    manifest = project / "04-manifest" / "image_regen_manifest.csv"
    images = project / "05-images"
    with manifest.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if args.limit is not None:
        rows = rows[:args.limit]
    expected = [images / row["filename"] for row in rows]
    missing = [p.name for p in expected if not p.is_file()]
    if missing:
        print(f"ERROR: {len(missing)} manifest frames are missing; first: {missing[:3]}")
        return 2
    hashes: dict[str, list[str]] = {}
    for path in expected:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes.setdefault(digest, []).append(path.name)
    duplicates = [names for names in hashes.values() if len(names) > 1]
    if duplicates:
        print(f"ERROR: {sum(len(x)-1 for x in duplicates)} reused frame(s); examples: {duplicates[:3]}")
        return 3
    stale = []
    semantic_errors = []
    for row in rows:
        metadata = images / f".{row['filename']}.prompt.json"
        if not metadata.is_file():
            stale.append(row["filename"])
            continue
        try:
            meta = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            semantic_errors.append(f"{row['filename']}: invalid metadata")
            continue
        job = FrameJob(
            timestamp=row.get("timestamp", ""),
            filename=row.get("filename", ""),
            scene=row.get("scene", ""),
            transcript=row.get("transcript", ""),
            context=row.get("context", ""),
        )
        expected_fingerprint = hashlib.sha256(
            "\x1f".join((job.timestamp, job.filename, job.scene, job.transcript, job.context)).encode("utf-8")
        ).hexdigest()
        if meta.get("prompt_fingerprint") != expected_fingerprint:
            semantic_errors.append(f"{row['filename']}: prompt fingerprint does not match manifest")
        if meta.get("image_sha256") != hashlib.sha256((images / row["filename"]).read_bytes()).hexdigest():
            semantic_errors.append(f"{row['filename']}: image was changed after generation")
        if not row.get("context", "").strip():
            semantic_errors.append(f"{row['filename']}: missing full semantic context")
        if not row.get("prompt", "").strip():
            semantic_errors.append(f"{row['filename']}: missing authored prompt")
        elif row["context"].strip() not in row["prompt"]:
            semantic_errors.append(f"{row['filename']}: prompt omits full semantic context")
        if not row.get("scene", "").strip():
            semantic_errors.append(f"{row['filename']}: missing exact visual action")
    if stale:
        print(f"ERROR: {len(stale)} frame(s) have no prompt provenance metadata; first: {stale[:3]}")
        return 4
    if semantic_errors:
        print(f"ERROR: {len(semantic_errors)} semantic/provenance gate failure(s); first: {semantic_errors[:5]}")
        return 5
    print(f"OK: {len(expected)} unique manifest frames validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
