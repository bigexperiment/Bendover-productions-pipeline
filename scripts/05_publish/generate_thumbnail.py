#!/usr/bin/env python3
"""Generate YouTube thumbnail via Codex image generation → 07-upload/thumbnail.png"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from lib.folders import DIR_UPLOAD, SCRIPT_FILE, TRANSCRIPT_FILE, YOUTUBE_THUMBNAIL  # noqa: E402
from lib.image_prompt import DEFAULT_IMAGE_STYLE, build_image_prompt_body  # noqa: E402

PROJECT_FILE = ROOT / "project.json"


def load_project() -> dict:
    if PROJECT_FILE.is_file():
        return json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    return {}


def read_snippet(path: Path, limit: int = 800) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def build_prompt(project: dict) -> str:
    name = project.get("name") or project.get("title") or "video"
    title = project.get("title") or name
    script_bit = read_snippet(SCRIPT_FILE)
    scene = (
        f"YouTube thumbnail for \"{title}\". "
        f"One bold focal scene about: {name}. "
        f"Large headline text on image (3–6 words max). "
        f"Script excerpt: {script_bit or '(none)'}"
    )
    body = build_image_prompt_body(project, scene)

    return f"""{body}

Thumbnail output:
- Use the built-in image_gen tool exactly once
- 16:9 landscape (1280×720 style), bold and readable at small size
- High contrast, click-worthy, no clutter, no watermarks
- Save to: 07-upload/thumbnail.png
- After generating, ensure the file exists at {ROOT}/07-upload/thumbnail.png
- Do not generate any other files
"""


def main() -> int:
    project = load_project()
    DIR_UPLOAD.mkdir(parents=True, exist_ok=True)

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
        build_prompt(project),
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
        print(f"Thumbnail generation failed (exit {result.returncode})", file=sys.stderr)
        return result.returncode

    if not YOUTUBE_THUMBNAIL.is_file():
        print(f"ERROR: Expected thumbnail at {YOUTUBE_THUMBNAIL}", file=sys.stderr)
        return 1

    print(f"Thumbnail saved: {YOUTUBE_THUMBNAIL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
