#!/usr/bin/env python3
"""Auto-generate a YouTube video description using Codex.

Reads project.json (title + video_brief) and writes a description to
tracker/description_draft.txt, then saves it back to project.json.

Usage:
    python3 scripts/05_publish/suggest_description.py
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

DRAFT_FILE = ROOT / "tracker" / "description_draft.txt"


def load_project() -> dict:
    if PROJECT_FILE.is_file():
        return json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    return {}


def generate_description(project: dict) -> str:
    title = (project.get("title") or project.get("name") or "").strip()
    brief = (project.get("video_brief") or "").strip()

    prompt = f"""Write a YouTube video description for this educational explainer video.

Video title: {title}
Video brief: {brief}

Requirements:
- First 2-3 lines are the hook (shown before "Show more") — make them punchy and curiosity-driven
- Then a short paragraph explaining what the viewer will learn
- End with a simple CTA: "Like and subscribe for more."
- Total length: 100-180 words
- Plain text only — no markdown, no hashtags, no emoji, no timestamps
- Write as if narrating to a curious general audience

Write ONLY the description text to the file tracker/description_draft.txt.
Do not include any other commentary. Do not modify any other files.
"""

    DRAFT_FILE.parent.mkdir(parents=True, exist_ok=True)
    if DRAFT_FILE.is_file():
        DRAFT_FILE.unlink()

    env = os.environ.copy()
    env["TERM"] = "xterm-256color"

    subprocess.run(
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

    if not DRAFT_FILE.is_file():
        print("ERROR: Codex did not write description_draft.txt", file=sys.stderr)
        return ""

    return DRAFT_FILE.read_text(encoding="utf-8").strip()


def save_to_project(description: str) -> None:
    if not PROJECT_FILE.is_file():
        return
    project = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    project["description"] = description
    PROJECT_FILE.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    project = load_project()
    description = generate_description(project)
    if not description:
        print("ERROR: No description generated", file=sys.stderr)
        return 1
    save_to_project(description)
    print("Description saved to project.json:")
    print()
    print(description)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
