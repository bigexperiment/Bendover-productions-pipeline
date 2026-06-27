#!/usr/bin/env python3
"""Single entry point to start the pipeline for a new video.

Run this after you have:
  - 01-script/Script.txt
  - 02-audio/narration.mp3  (or .wav / .m4a)
  - 03-transcript/transcript.txt
  - Style approved (run Studio style picker + confirm with Claude Code first)

Usage:
    python3 scripts/begin.py

Everything after this runs automatically:
  frames → render → 3 thumbnail variants → ntfy alert
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib.folders import (  # noqa: E402
    AUDIO_EXTS, DIR_AUDIO, DIR_SCRIPT, DIR_TRANSCRIPT,
    NARRATION_FILE, PROJECT_FILE, SCRIPT_FILE, TRANSCRIPT_FILE,
)
from lib.project_template import reset_project_dict  # noqa: E402

START_OVERNIGHT = ROOT / "scripts" / "start_overnight.sh"
PID_FILE = ROOT / "tracker" / "overnight.pid"


def check(condition: bool, msg: str) -> None:
    if not condition:
        print(f"  MISSING  {msg}")
        sys.exit(1)
    print(f"  OK       {msg}")


def find_audio() -> Path | None:
    for ext in AUDIO_EXTS:
        for f in DIR_AUDIO.iterdir() if DIR_AUDIO.exists() else []:
            if f.suffix.lower() == ext and f.name != ".gitkeep":
                return f
    return None


def ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    val = input(f"{prompt}{hint}: ").strip()
    return val or default


def main() -> int:
    print()
    print("=" * 54)
    print("  BENDOVER PRODUCTIONS — pipeline setup")
    print("=" * 54)
    print()

    # --- Check already running ---
    if PID_FILE.is_file():
        pid = PID_FILE.read_text().strip()
        try:
            import os
            os.kill(int(pid), 0)
            print(f"Pipeline already running (PID {pid}).")
            print("  Monitor: tail -f tracker/overnight.log")
            print("  Stop:    bash scripts/stop_overnight.sh")
            return 0
        except (OSError, ValueError):
            PID_FILE.unlink(missing_ok=True)

    # --- File checks ---
    print("Checking files...")
    check(SCRIPT_FILE.is_file() and SCRIPT_FILE.stat().st_size > 0, "01-script/Script.txt")
    audio = find_audio()
    check(audio is not None, "02-audio/narration.mp3 (or .wav/.m4a)")
    check(TRANSCRIPT_FILE.is_file() and TRANSCRIPT_FILE.stat().st_size > 0, "03-transcript/transcript.txt")
    print()

    # --- Load existing project.json ---
    if PROJECT_FILE.is_file():
        current = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    else:
        current = {}

    # --- Style check ---
    if not current.get("style_approved"):
        print("Style not approved yet.")
        print()
        print("  → Open Studio, pick a style, then confirm with Claude Code.")
        print("  → Once style_approved is true in project.json, re-run this script.")
        return 1
    preset = current.get("style_preset_label") or current.get("image_style", "")[:40]
    print(f"Style:    {preset}  ✓")
    print()

    # --- Video info ---
    existing_title = current.get("title") or current.get("name") or ""
    existing_brief = current.get("video_brief") or ""

    print("Video details (press Enter to keep existing value):")
    title = ask("  Title", existing_title)
    if not title:
        print("ERROR: title is required")
        return 1
    brief = ask("  One-line brief", existing_brief)
    if not brief:
        print("ERROR: brief is required (used for thumbnail + description generation)")
        return 1
    print()

    # --- Write project.json ---
    fresh = reset_project_dict(current)
    fresh["name"] = title
    fresh["title"] = title
    fresh["video_brief"] = brief
    fresh["style_approved"] = True
    fresh["step"] = "images"
    PROJECT_FILE.write_text(json.dumps(fresh, indent=2) + "\n", encoding="utf-8")
    print(f"project.json saved.")
    print()

    # --- Confirm + launch ---
    print("Ready to start:")
    print(f"  Title:  {title}")
    print(f"  Brief:  {brief}")
    print(f"  Audio:  {audio.name}")
    print()
    print("The pipeline will run automatically:")
    print("  1. Build frame manifest from transcript")
    print("  2. Generate all frames (pauses + resumes on credit limit)")
    print("  3. Render final.mp4")
    print("  4. Generate 3 thumbnail variants")
    print("  5. Send you an ntfy alert with thumbnails ready")
    print()
    confirm = input("Start now? (y/n): ").strip().lower()
    if confirm != "y":
        print("Cancelled. Run again when ready.")
        return 0

    print()
    print("Launching...")
    result = subprocess.run(["bash", str(START_OVERNIGHT)], cwd=ROOT)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
