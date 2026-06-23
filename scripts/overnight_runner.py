#!/usr/bin/env python3
"""Overnight automation: manifest → images (with credit-resume) → render → ntfy.

Run detached before bed:
    nohup python3 scripts/overnight_runner.py &

Or via the launcher:
    bash scripts/start_overnight.sh

Requires all creative inputs on disk beforehand:
  - project.json: name, image_style, style_approved: true
  - 01-script/Script.txt
  - 02-audio/narration.mp3 (or similar)
  - 03-transcript/transcript.txt

The runner will:
  1. Validate via preflight
  2. Build manifest (if needed)
  3. Generate all images (credit-gated, auto-resumes after 5h window resets)
  4. Render final.mp4
  5. Ping phone via ntfy
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "07_credits"))

from fetch_codex_usage import read_usage_payload, should_stop_generation, write_usage  # noqa: E402
from lib.folders import (  # noqa: E402
    FINAL_MP4,
    MANIFEST_FILE,
    PROGRESS_FILE,
    PROJECT_FILE,
)
from lib.notify import send_ntfy  # noqa: E402

LOG_FILE = ROOT / "tracker" / "overnight.log"
PREFLIGHT = ROOT / "scripts" / "preflight.py"
BUILD_PLAN = ROOT / "scripts" / "02_manifest" / "build_plan.py"
GENERATE = ROOT / "scripts" / "03_images" / "generate_images.py"
RENDER = ROOT / "scripts" / "04_render" / "render_draft_video.py"
START_STUDIO = ROOT / "scripts" / "start_studio.sh"
STATUS_STUDIO = ROOT / "scripts" / "status_studio.sh"

CREDIT_POLL_INTERVAL = 5 * 60  # check every 5 min while waiting for reset
MAX_GEN_ATTEMPTS = 10  # safety cap on generation retry loops
EXTRA_WAIT_AFTER_RESET = 60  # breathing room after reset time passes


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(args: list[str], label: str, check: bool = True) -> subprocess.CompletedProcess:
    log(f"RUN: {label}")
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        log(f"  exit={result.returncode}")
        if result.stdout.strip():
            for line in result.stdout.strip().splitlines()[-10:]:
                log(f"  stdout: {line}")
        if result.stderr.strip():
            for line in result.stderr.strip().splitlines()[-5:]:
                log(f"  stderr: {line}")
        if check:
            raise RuntimeError(f"{label} failed (exit {result.returncode})")
    else:
        log(f"  OK ({label})")
    return result


def load_project() -> dict:
    return json.loads(PROJECT_FILE.read_text(encoding="utf-8"))


def pending_frames() -> int:
    if not PROGRESS_FILE.is_file():
        return 999
    data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    return int(data.get("pending_frames") or data.get("missing_frames") or 0)


def ensure_studio() -> None:
    result = subprocess.run(
        ["bash", str(STATUS_STUDIO)], cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        run(["bash", str(START_STUDIO)], "start Studio")


def wait_for_credits() -> None:
    """Block until Codex credits are available again."""
    log("Credits exhausted — waiting for 5h window reset...")
    send_ntfy("Overnight: credits hit 0%, waiting for reset...")

    while True:
        usage = write_usage(force=True)
        blocked, reason = should_stop_generation(usage)
        if not blocked:
            log("Credits available again")
            return

        five_hour = usage.get("five_hour") or {}
        resets_at = int(five_hour.get("resets_at") or 0)
        now = int(time.time())

        if resets_at and resets_at > now:
            wait_secs = (resets_at - now) + EXTRA_WAIT_AFTER_RESET
            log(f"  Reset in {wait_secs // 60}m — sleeping until {datetime.fromtimestamp(resets_at + EXTRA_WAIT_AFTER_RESET).strftime('%I:%M %p')}")
            time.sleep(wait_secs)
        else:
            log(f"  Polling every {CREDIT_POLL_INTERVAL // 60}m...")
            time.sleep(CREDIT_POLL_INTERVAL)


def generate_with_resume(workers: int) -> None:
    """Run image generation, auto-resuming after credit resets."""
    attempts = 0

    while attempts < MAX_GEN_ATTEMPTS:
        attempts += 1
        remaining = pending_frames()
        if remaining == 0:
            log("All frames generated")
            return

        log(f"Generation attempt {attempts} — {remaining} frames pending")

        result = subprocess.run(
            ["python3", str(GENERATE), str(workers)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            run(["python3", str(BUILD_PLAN), "refresh"], "refresh manifest", check=False)
            if pending_frames() == 0:
                log("All frames generated")
                return
            log("Exit 0 but frames still pending — retrying...")
            continue

        if result.returncode == 2:
            run(["python3", str(BUILD_PLAN), "refresh"], "refresh manifest", check=False)
            if pending_frames() == 0:
                log("All frames generated (despite exit 2)")
                return
            wait_for_credits()
            continue

        log(f"generate_images exited {result.returncode} (unexpected)")
        if result.stdout:
            log(f"  {result.stdout.strip()[-500:]}")
        raise RuntimeError(f"Image generation failed unexpectedly (exit {result.returncode})")

    raise RuntimeError(f"Exceeded {MAX_GEN_ATTEMPTS} generation attempts")


def main() -> int:
    log("=" * 60)
    log("OVERNIGHT RUNNER — starting")
    log("=" * 60)

    project = load_project()
    name = project.get("name") or "Untitled"
    workers = int(project.get("workers") or 5)
    log(f"Project: {name} | Workers: {workers}")

    if not project.get("style_approved"):
        log("ERROR: style_approved is false — set to true before running overnight")
        log("  → edit project.json or pick a style in Studio and approve")
        return 1

    # Step 1: Preflight
    result = run(["python3", str(PREFLIGHT), "--images"], "preflight --images", check=False)
    if result.returncode != 0:
        log("ABORT: preflight failed — fix errors above before running overnight")
        send_ntfy(f"Overnight FAILED: preflight errors. {name}")
        return 1

    # Step 2: Build manifest (if missing)
    if not MANIFEST_FILE.is_file():
        run(["python3", str(BUILD_PLAN)], "build manifest")
    else:
        run(["python3", str(BUILD_PLAN), "refresh"], "refresh manifest")

    total = pending_frames()
    log(f"Manifest ready — {total} frames to generate")

    if total == 0:
        log("No pending frames — skipping to render")
    else:
        # Step 3: Ensure Studio is up (for monitoring)
        ensure_studio()

        # Step 4: Generate images (with credit-resume loop)
        send_ntfy(f"Overnight started: {name} ({total} frames)")
        generate_with_resume(workers)
        send_ntfy(f"All clips Done! {name}")

    # Step 5: Render
    if FINAL_MP4.is_file():
        FINAL_MP4.unlink()

    run(
        ["python3", str(RENDER), "--output", str(FINAL_MP4)],
        "render final.mp4",
    )

    if FINAL_MP4.is_file():
        size_mb = FINAL_MP4.stat().st_size / (1024 * 1024)
        log(f"Render complete: {FINAL_MP4.name} ({size_mb:.1f} MB)")
        send_ntfy(f"Overnight DONE! {name} — final.mp4 ready ({size_mb:.0f} MB). Review + upload when ready.")
    else:
        log("ERROR: render did not produce final.mp4")
        send_ntfy(f"Overnight: render failed for {name}")
        return 1

    log("=" * 60)
    log("OVERNIGHT RUNNER — finished successfully")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
