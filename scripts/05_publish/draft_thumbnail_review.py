#!/usr/bin/env python3
"""Draft YouTube thumbnail for review — does not overwrite 07-upload/thumbnail.png.

Output: 07-upload/thumbnail_review.png

Uses project.json style + name/title. Run anytime to iterate before publish.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from lib.folders import DIR_UPLOAD  # noqa: E402
from lib.thumbnail_prompt import build_thumbnail_prompt  # noqa: E402

PROJECT_FILE = ROOT / "project.json"
DEFAULT_OUT = DIR_UPLOAD / "thumbnail_review.png"


def load_project() -> dict:
    if PROJECT_FILE.is_file():
        return json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    return {}


def build_prompt(project: dict, out_path: Path, headline: str) -> str:
    prompt = build_thumbnail_prompt(project, headline, out_path, ROOT)
    return prompt + "\n- Do not overwrite 07-upload/thumbnail.png\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a review thumbnail (not the final upload file).")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output path (default: {DEFAULT_OUT.relative_to(ROOT)})",
    )
    parser.add_argument(
        "--headline",
        default=None,
        help="Thumbnail hook text (must differ from YouTube title). Default: project.json thumbnail_text",
    )
    args = parser.parse_args()
    out_path = args.output if args.output.is_absolute() else ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)

    project = load_project()
    headline = (args.headline or project.get("thumbnail_text") or "").strip()
    if not headline:
        print("ERROR: Set --headline or thumbnail_text in project.json", file=sys.stderr)
        return 1
    title = (project.get("title") or project.get("name") or "").strip()
    if headline.lower() == title.lower():
        print("ERROR: Thumbnail headline must differ from YouTube title", file=sys.stderr)
        return 1
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
        build_prompt(project, out_path, headline),
    ]
    print(f"Generating review thumbnail → {out_path}", flush=True)
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        print(result.stdout)
    if result.returncode != 0:
        if result.stderr.strip():
            print(result.stderr, file=sys.stderr)
        print(f"Thumbnail draft failed (exit {result.returncode})", file=sys.stderr)
        return result.returncode

    if not out_path.is_file():
        print(f"ERROR: Expected thumbnail at {out_path}", file=sys.stderr)
        return 1

    print(f"Review thumbnail saved: {out_path}")
    print("Open it to review. Re-run this script to iterate; publish uses generate_thumbnail.py → thumbnail.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
