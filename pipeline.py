#!/usr/bin/env python3
"""Single-command autonomous video pipeline.

Usage:
    python3 pipeline.py projects/my-video

The manifest is the only timing/source-of-truth artifact. Each stage fails
closed: no render is attempted until image integrity, provenance, prompt
contract, and audio/video alignment all pass.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent


def run(label: str, command: list[str], root: Path) -> None:
    print(f"\n== {label} ==", flush=True)
    env = os.environ.copy()
    env["PIPELINE_ROOT"] = str(root)
    result = subprocess.run(command, cwd=REPO, env=env)
    if result.returncode:
        raise SystemExit(f"STOPPED: {label} failed with exit {result.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--force-audio", action="store_true")
    parser.add_argument("--force-manifest", action="store_true")
    parser.add_argument("--no-publish", action="store_true", help="skip thumbnails and description")
    args = parser.parse_args()
    root = args.project.resolve()
    if not (root / "project.json").is_file():
        raise SystemExit(f"Not a project directory: {root}")

    audio = root / "02-audio" / "narration.mp3"
    transcript = root / "03-transcript" / "transcript.txt"
    manifest = root / "04-manifest" / "image_regen_manifest.csv"
    output = root / "06-output" / "final.mp4"

    if args.force_audio or not audio.is_file():
        tts_python = os.environ.get("TTS_PYTHON", sys.executable)
        run("Google Charon TTS", [tts_python, str(REPO / "scripts/tts_generate.py"), str(root)], root)
    transcript_ready = transcript.is_file() and len(transcript.read_text(encoding="utf-8").strip()) >= 40
    if args.force_audio or not transcript_ready:
        whisper_python = os.environ.get("WHISPER_PYTHON", sys.executable)
        run("Whisper transcript", [whisper_python, str(REPO / "scripts/01_audio/generate_transcript.py")], root)
    run("preflight", ["python3", str(REPO / "scripts/preflight.py")], root)
    if args.force_manifest or not manifest.is_file():
        run("timed manifest", ["python3", str(REPO / "scripts/02_manifest/build_plan.py")], root)
        run("transcript-first prompts", ["python3", str(REPO / "scripts/02_manifest/build_image_manifest.py")], root)
    else:
        run("refresh manifest", ["python3", str(REPO / "scripts/02_manifest/build_plan.py"), "refresh"], root)

    workers = str(args.workers or 5)
    run("image generation", ["python3", "-u", str(REPO / "scripts/03_images/generate_images.py"), workers], root)
    run("image integrity and retry gate", ["python3", "-u", str(REPO / "scripts/03_images/verify_frames.py"), workers], root)
    run("manifest/provenance gate", ["python3", str(REPO / "scripts/03_images/validate_frames.py"), str(root)], root)
    run("transcript-first contract gate", ["python3", str(REPO / "scripts/03_images/semantic_manifest_gate.py")], root)
    output.parent.mkdir(parents=True, exist_ok=True)
    run("render", ["python3", str(REPO / "scripts/04_render/render_draft_video.py"), "--output", str(output)], root)
    run("render/audio audit", ["python3", str(REPO / "scripts/04_render/audit_render.py"), str(output)], root)

    if not args.no_publish:
        run("thumbnail text", ["python3", str(REPO / "scripts/05_publish/suggest_thumbnail_text.py")], root)
        run("description", ["python3", str(REPO / "scripts/05_publish/suggest_description.py")], root)
    print(f"\nDONE: {output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
