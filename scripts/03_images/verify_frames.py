#!/usr/bin/env python3
"""Final QA sweep over generated frames — catches bad frames the inline check in
generate_images.py might have let through, and regenerates them BEFORE the video
is rendered / marked done.

A frame is considered BAD if any of these hold:
  - missing:    it's in the manifest but no file exists on disk
  - degraded:   the file is a low-res/low-detail render (size < MIN_FRAME_BYTES).
                Codex's image tool occasionally returns a ~1600x900, 15-33 KB
                render instead of a full ~1672x941, 500KB-1MB+ frame.
  - duplicate:  it's a byte-for-byte copy of another frame (wrong cached PNG got
                picked up under parallel load) — keeps the first, redoes the rest.

For every bad frame: delete it, mark it pending in the manifest, and re-run image
generation for just those frames. Repeat up to MAX_ROUNDS. Exit 0 only when every
manifest frame is present and clean; exit 1 if some frames are still bad after all
rounds (so the caller can warn instead of silently shipping a broken video).

Usage:
    PIPELINE_ROOT=/abs/path/to/project python3 scripts/03_images/verify_frames.py [--workers N] [--rounds N]
"""
from __future__ import annotations

import csv
import hashlib
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get("PIPELINE_ROOT") or SCRIPTS_ROOT)
sys.path.insert(0, str(SCRIPTS_ROOT / "scripts"))
from lib.folders import DIR_IMAGES as IMAGES_DIR, MANIFEST_FILE  # noqa: E402

# Same floor generate_images.py uses — keep them in sync via the env var.
MIN_FRAME_BYTES = int(os.environ.get("MIN_FRAME_BYTES") or 100_000)
MAX_ROUNDS = int(os.environ.get("VERIFY_MAX_ROUNDS") or 3)

BUILD_PLAN = SCRIPTS_ROOT / "scripts" / "02_manifest" / "build_plan.py"
GENERATE = SCRIPTS_ROOT / "scripts" / "03_images" / "generate_images.py"


def manifest_frames() -> list[str]:
    if not MANIFEST_FILE.is_file():
        return []
    with MANIFEST_FILE.open("r", encoding="utf-8", newline="") as handle:
        return [row["filename"] for row in csv.DictReader(handle) if row.get("filename")]


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_bad_frames() -> list[tuple[str, str]]:
    """Return [(filename, reason)] for every frame that must be regenerated."""
    bad: list[tuple[str, str]] = []
    hashes: dict[str, str] = {}  # digest -> first filename that had it
    dup_groups: dict[str, list[str]] = defaultdict(list)

    for filename in manifest_frames():
        path = IMAGES_DIR / filename
        if not path.is_file():
            bad.append((filename, "missing"))
            continue
        try:
            size = path.stat().st_size
        except OSError:
            bad.append((filename, "unreadable"))
            continue
        if size < MIN_FRAME_BYTES:
            bad.append((filename, f"degraded ({size // 1024}KB < {MIN_FRAME_BYTES // 1024}KB)"))
            continue
        digest = file_hash(path)
        dup_groups[digest].append(filename)

    # Any hash shared by 2+ frames: keep the first, redo the others.
    for digest, names in dup_groups.items():
        if len(names) > 1:
            first, *rest = names
            for name in rest:
                bad.append((name, f"duplicate (matches {first})"))
    return bad


def run(cmd: list[str], label: str) -> int:
    print(f"[verify] {label}…", flush=True)
    result = subprocess.run(cmd, cwd=ROOT)
    return result.returncode


def main() -> int:
    workers = "5"
    rounds = MAX_ROUNDS
    for arg in sys.argv[1:]:
        if arg.startswith("--workers"):
            workers = arg.split("=", 1)[1] if "=" in arg else workers
        elif arg.startswith("--rounds"):
            rounds = int(arg.split("=", 1)[1]) if "=" in arg else rounds

    for attempt in range(1, rounds + 1):
        bad = find_bad_frames()
        if not bad:
            print(f"[verify] all {len(manifest_frames())} frames clean.")
            return 0

        print(f"[verify] round {attempt}/{rounds}: {len(bad)} bad frame(s):")
        for filename, reason in bad:
            print(f"           {filename} — {reason}")
            (IMAGES_DIR / filename).unlink(missing_ok=True)

        # Mark the deleted frames pending, then regenerate just those.
        run(["python3", str(BUILD_PLAN), "refresh"], "refresh manifest")
        run(["python3", "-u", str(GENERATE), workers], "regenerate bad frames")

    remaining = find_bad_frames()
    if remaining:
        print(f"[verify] FAILED: {len(remaining)} frame(s) still bad after {rounds} rounds:", file=sys.stderr)
        for filename, reason in remaining:
            print(f"           {filename} — {reason}", file=sys.stderr)
        return 1
    print(f"[verify] all frames clean after {rounds} round(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
