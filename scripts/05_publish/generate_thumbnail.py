#!/usr/bin/env python3
"""YouTube thumbnail → 07-upload/thumbnail.png (or --output path).

Default: Codex generates the full thumbnail (scene + headline text in the image).
Never uses Pillow text overlay.

Use --variant=1|2|3 for different scene angles (assistant generates 3, user picks one).

project.json:
  thumbnail_text  — headline burned into image by Codex (required, ≠ title)
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[2]  # repo root — where scripts/ lives
ROOT = Path(os.environ.get("PIPELINE_ROOT") or SCRIPTS_ROOT)  # project data root
sys.path.insert(0, str(SCRIPTS_ROOT / "scripts"))
from lib.folders import DIR_IMAGES, DIR_UPLOAD, MANIFEST_FILE, YOUTUBE_THUMBNAIL  # noqa: E402

try:
    from PIL import Image
except ImportError as exc:
    raise SystemExit("Pillow required for --frame crop: pip install pillow") from exc

from lib.thumbnail_prompt import build_thumbnail_prompt  # noqa: E402

PROJECT_FILE = ROOT / "project.json"
THUMB_SIZE = (1280, 720)
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


def crop_frame_to_thumbnail(frame_path: Path, out_path: Path) -> None:
    tw, th = THUMB_SIZE
    src = Image.open(frame_path).convert("RGB")
    src_ratio = src.width / src.height
    tgt_ratio = tw / th

    if src_ratio > tgt_ratio:
        new_h = th
        new_w = int(th * src_ratio)
    else:
        new_w = tw
        new_h = int(tw / src_ratio)

    resized = src.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - tw) // 2
    top = (new_h - th) // 2
    canvas = resized.crop((left, top, left + tw, top + th))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG")


def generate_via_codex(project: dict, headline: str, out_path: Path, variant: int) -> int:
    prompt = build_thumbnail_prompt(project, headline, out_path, ROOT, variant=variant)
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
    if not out_path.is_file():
        print(f"ERROR: Expected thumbnail at {out_path}", file=sys.stderr)
        return 1
    return 0


def parse_args() -> tuple[str | None, str | None, Path, bool, int]:
    headline_arg = None
    frame_arg = None
    out_path = YOUTUBE_THUMBNAIL
    frame_only = False
    variant = 1
    for arg in sys.argv[1:]:
        if arg.startswith("--headline="):
            headline_arg = arg.split("=", 1)[1].strip()
        elif arg.startswith("--frame="):
            frame_arg = arg.split("=", 1)[1].strip()
            frame_only = True
        elif arg.startswith("--output="):
            out_path = ROOT / arg.split("=", 1)[1].strip()
        elif arg.startswith("--variant="):
            variant = int(arg.split("=", 1)[1].strip())
        elif arg == "--frame":
            frame_only = True
    return headline_arg, frame_arg, out_path, frame_only, variant


def main() -> int:
    headline_arg, frame_arg, out_path, frame_only, variant = parse_args()
    project = load_project()
    headline = resolve_headline(project, headline_arg)
    DIR_UPLOAD.mkdir(parents=True, exist_ok=True)

    if frame_only:
        frame = resolve_frame(project, frame_arg)
        if not frame:
            print("ERROR: No frame found for --frame crop", file=sys.stderr)
            return 1
        print(f"Cropping {frame.name} → {out_path.name} (no text)…", flush=True)
        crop_frame_to_thumbnail(frame, out_path)
        print(f"Thumbnail saved: {out_path}")
        return 0

    if not headline:
        print(
            "ERROR: Set thumbnail_text in project.json (2–5 words, not the full title)",
            file=sys.stderr,
        )
        return 1

    print(
        f"Generating variant {variant} via Codex ({headline!r}) → {out_path.name}…",
        flush=True,
    )
    code = generate_via_codex(project, headline, out_path, variant)
    if code == 0:
        print(f"Thumbnail saved: {out_path}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
