#!/usr/bin/env python3
"""YouTube thumbnail → 07-upload/thumbnail.png

Default: crop a real frame from 05-images/ (matches video style) + overlay thumbnail_text.
Fallback: --codex generates a new scene (often mismatches frame style).

project.json:
  thumbnail_text  — headline on image (required, ≠ title)
  thumbnail_frame — PNG in 05-images/ (default: auto-pick fire/camp frame)
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from lib.folders import DIR_IMAGES, DIR_UPLOAD, MANIFEST_FILE, YOUTUBE_THUMBNAIL  # noqa: E402

try:
    from lib.thumbnail_overlay import compose_from_frame  # noqa: E402
except ImportError as exc:
    raise SystemExit("Pillow required: pip install pillow") from exc

from lib.thumbnail_prompt import build_thumbnail_prompt  # noqa: E402
from lib.thumbnail_overlay import overlay_headline  # noqa: E402

PROJECT_FILE = ROOT / "project.json"

FIRE_FRAME_HINTS = ("fire", "camp", "woodsmoke", "campfire", "flame")


def load_project() -> dict:
    if PROJECT_FILE.is_file():
        return json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    return {}


def resolve_headline(project: dict, headline_arg: str | None) -> str | None:
    headline = (headline_arg or project.get("thumbnail_text") or "").strip()
    if not headline:
        return None
    title = (project.get("title") or project.get("name") or "").strip()
    if title and headline.lower() == title.lower():
        print("ERROR: thumbnail_text must differ from YouTube title", file=sys.stderr)
        return None
    return headline


def pick_frame_from_manifest() -> Path | None:
    if not MANIFEST_FILE.is_file():
        return None
    rows: list[dict[str, str]] = []
    with MANIFEST_FILE.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("status") != "done":
                continue
            path = DIR_IMAGES / row["filename"]
            if not path.is_file():
                continue
            rows.append(row)

    for hint in FIRE_FRAME_HINTS:
        for row in rows:
            blob = f"{row.get('scene', '')} {row.get('transcript', '')}".lower()
            if hint in blob:
                return DIR_IMAGES / row["filename"]

    return DIR_IMAGES / rows[0]["filename"] if rows else None


def resolve_frame(project: dict, frame_arg: str | None) -> Path | None:
    name = (frame_arg or project.get("thumbnail_frame") or "").strip()
    if name:
        path = DIR_IMAGES / Path(name).name
        return path if path.is_file() else None
    return pick_frame_from_manifest()


def generate_via_codex(project: dict, headline: str) -> int:
    prompt = build_thumbnail_prompt(project, headline, YOUTUBE_THUMBNAIL, ROOT)
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    command = [
        "codex",
        "exec",
        "--enable",
        "image_generation",
        "-s",
        "workspace-write",
        "--dangerously-bypass-approvals-and-sandbox",
        "-C",
        str(ROOT),
        prompt,
    ]
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        return result.returncode
    if not YOUTUBE_THUMBNAIL.is_file():
        print(f"ERROR: Expected thumbnail at {YOUTUBE_THUMBNAIL}", file=sys.stderr)
        return 1
    overlay_headline(YOUTUBE_THUMBNAIL, headline)
    return 0


def main() -> int:
    headline_arg = None
    frame_arg = None
    use_codex = False
    for arg in sys.argv[1:]:
        if arg.startswith("--headline="):
            headline_arg = arg.split("=", 1)[1].strip()
        elif arg.startswith("--frame="):
            frame_arg = arg.split("=", 1)[1].strip()
        elif arg == "--codex":
            use_codex = True

    project = load_project()
    headline = resolve_headline(project, headline_arg)
    if not headline:
        print(
            "ERROR: Set thumbnail_text in project.json (2–5 words, not the full title)",
            file=sys.stderr,
        )
        return 1

    DIR_UPLOAD.mkdir(parents=True, exist_ok=True)

    if not use_codex:
        frame = resolve_frame(project, frame_arg)
        if frame:
            print(f"Composing from video frame {frame.name} + headline {headline!r}…", flush=True)
            compose_from_frame(frame, YOUTUBE_THUMBNAIL, headline)
            print(f"Thumbnail saved: {YOUTUBE_THUMBNAIL}")
            return 0
        print("No frame found — falling back to Codex generation", file=sys.stderr)

    print(f"Generating via Codex (headline: {headline!r})…", flush=True)
    code = generate_via_codex(project, headline)
    if code == 0:
        print(f"Thumbnail saved (with headline overlay): {YOUTUBE_THUMBNAIL}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
