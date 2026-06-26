#!/usr/bin/env python3
"""Auto-generate thumbnail headline options using Codex.

Reads project.json (title + video_brief) and writes 3 short punchy
YouTube thumbnail headlines to tracker/thumbnail_options.json.

Usage:
    python3 scripts/05_publish/suggest_thumbnail_text.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get("PIPELINE_ROOT") or SCRIPTS_ROOT)
sys.path.insert(0, str(SCRIPTS_ROOT / "scripts"))
from lib.folders import PROJECT_FILE  # noqa: E402

OPTIONS_FILE = ROOT / "tracker" / "thumbnail_options.json"


def load_project() -> dict:
    if PROJECT_FILE.is_file():
        return json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    return {}


def generate_options(project: dict) -> list[str]:
    title = (project.get("title") or project.get("name") or "").strip()
    brief = (project.get("video_brief") or "").strip()

    if not title and not brief:
        print("ERROR: Set title or video_brief in project.json", file=sys.stderr)
        return []

    prompt = f"""You are writing YouTube thumbnail hooks for an educational stickman-explainer channel.

Video title: {title}
Video brief: {brief}

Generate exactly 3 short thumbnail hook phrases that make viewers click.

Rules:
- 2–5 words each
- Punchy, curiosity-driven — tease the answer without giving it away
- Must be DIFFERENT from the video title — a hook, not a repeat
- No hashtags, no punctuation except a dash or question mark if it helps
- Examples: "Your Brain Is Lying", "You've Been Doing It Wrong", "This Changes Everything", "The Hidden Cost"
- Output ONLY valid JSON to the file tracker/thumbnail_options.json — no other text, no markdown:
  {{"options": ["Hook One", "Hook Two", "Hook Three"]}}
- Do not create or modify any other files
"""

    OPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if OPTIONS_FILE.is_file():
        OPTIONS_FILE.unlink()

    env = os.environ.copy()
    env["TERM"] = "xterm-256color"

    result = subprocess.run(
        [
            "codex", "exec",
            "-s", "workspace-write",
            "--dangerously-bypass-approvals-and-sandbox",
            "-C", str(ROOT),
            prompt,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    if not OPTIONS_FILE.is_file():
        tail = (result.stdout or "")[-400:]
        print(f"WARNING: Codex did not write {OPTIONS_FILE.name}", file=sys.stderr)
        if tail:
            print(tail, file=sys.stderr)
        return []

    try:
        data = json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
        options = [o.strip() for o in (data.get("options") or []) if o.strip()]
        return options[:3]
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR: Could not parse {OPTIONS_FILE.name}: {exc}", file=sys.stderr)
        return []


def main() -> int:
    project = load_project()
    options = generate_options(project)
    if not options:
        print("ERROR: No thumbnail options generated", file=sys.stderr)
        return 1

    print("Thumbnail headline options:")
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
