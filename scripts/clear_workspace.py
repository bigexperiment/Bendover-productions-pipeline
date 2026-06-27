#!/usr/bin/env python3
"""Reset the current project workspace for a new video.

Clears all per-video content (script, audio, images, manifest, output, upload assets)
and resets project.json to defaults, preserving style settings and credentials.

Usage:
    python3 scripts/clear_workspace.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib.folders import (  # noqa: E402
    DIR_AUDIO, DIR_IMAGES, DIR_MANIFEST, DIR_OUTPUT, DIR_SCRIPT,
    DIR_TRANSCRIPT, DIR_UPLOAD, PROJECT_FILE,
)
from lib.project_template import reset_project_dict  # noqa: E402

# Files to keep inside 07-upload/ (credentials + deps — not project content)
UPLOAD_KEEP = {"requirements-youtube.txt", "reels"}


def clear_dir(path: Path, keep: set[str] | None = None) -> int:
    if not path.exists():
        return 0
    removed = 0
    for item in path.iterdir():
        if item.name == ".gitkeep":
            continue
        if keep and item.name in keep:
            continue
        if item.name.startswith("client_secret") and item.suffix == ".json":
            continue
        if item.name == "youtube_token.json":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
        removed += 1
    return removed


def main() -> int:
    print("Clearing workspace...")

    dirs = [
        (DIR_SCRIPT,    None),
        (DIR_AUDIO,     None),
        (DIR_TRANSCRIPT, None),
        (DIR_MANIFEST,  None),
        (DIR_IMAGES,    None),
        (DIR_OUTPUT,    None),
        (DIR_UPLOAD,    UPLOAD_KEEP),
    ]

    for path, keep in dirs:
        n = clear_dir(path, keep)
        print(f"  {path.name}/  — {n} file(s) removed")

    # Clear tracker runtime files (logs, status, usage)
    tracker = ROOT / "tracker"
    tracker_keep = {"studio.pid"}
    if tracker.exists():
        n = clear_dir(tracker, tracker_keep)
        print(f"  tracker/  — {n} file(s) removed")

    # Reset project.json, preserving style settings
    if PROJECT_FILE.is_file():
        current = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    else:
        current = {}
    fresh = reset_project_dict(current)
    PROJECT_FILE.write_text(json.dumps(fresh, indent=2) + "\n", encoding="utf-8")
    print("  project.json  — reset (style settings kept)")

    print("\nWorkspace cleared. Ready for a new video.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
