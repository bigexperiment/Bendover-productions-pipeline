#!/usr/bin/env python3
"""Full pipeline automation: manifest → images → render → ntfy.

Since generate_images.py now auto-waits for credits internally, this runner
simply chains the steps and sends a final "MP4 ready" alert.

Run detached:
    bash scripts/start_overnight.sh

Or directly:
    nohup python3 -u scripts/overnight_runner.py &
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.folders import FINAL_MP4, MANIFEST_FILE, PROJECT_FILE  # noqa: E402
from lib.notify import send_ntfy  # noqa: E402

LOG_FILE = ROOT / "tracker" / "overnight.log"
PREFLIGHT = ROOT / "scripts" / "preflight.py"
BUILD_PLAN = ROOT / "scripts" / "02_manifest" / "build_plan.py"
GENERATE = ROOT / "scripts" / "03_images" / "generate_images.py"
RENDER = ROOT / "scripts" / "04_render" / "render_draft_video.py"
START_STUDIO = ROOT / "scripts" / "start_studio.sh"
STATUS_STUDIO = ROOT / "scripts" / "status_studio.sh"


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


def ensure_studio() -> None:
    result = subprocess.run(
        ["bash", str(STATUS_STUDIO)], cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        run(["bash", str(START_STUDIO)], "start Studio")


def main() -> int:
    log("=" * 60)
    log("PIPELINE RUNNER — starting")
    log("=" * 60)

    project = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    name = project.get("name") or "Untitled"
    workers = int(project.get("workers") or 5)
    log(f"Project: {name} | Workers: {workers}")

    if not project.get("style_approved"):
        log("ERROR: style_approved is false")
        send_ntfy(f"Pipeline FAILED: style not approved. {name}")
        return 1

    # Preflight
    result = run(["python3", str(PREFLIGHT), "--images"], "preflight", check=False)
    if result.returncode != 0:
        log("ABORT: preflight failed")
        send_ntfy(f"Pipeline FAILED: preflight errors. {name}")
        return 1

    # Build manifest
    if not MANIFEST_FILE.is_file():
        run(["python3", str(BUILD_PLAN)], "build manifest")
    else:
        run(["python3", str(BUILD_PLAN), "refresh"], "refresh manifest")

    # Studio for monitoring
    ensure_studio()

    # Generate (auto-waits for credits internally)
    send_ntfy(f"Pipeline started: {name}")
    log("Starting image generation (auto credit-resume enabled)")
    gen_result = subprocess.run(
        ["python3", "-u", str(GENERATE), str(workers)],
        cwd=ROOT,
        text=True,
    )
    if gen_result.returncode != 0:
        log(f"Image generation exited {gen_result.returncode}")
        send_ntfy(f"Pipeline FAILED: image gen error. {name}")
        return 1

    # Render
    if FINAL_MP4.is_file():
        FINAL_MP4.unlink()
    run(["python3", str(RENDER), "--output", str(FINAL_MP4)], "render final.mp4")

    if FINAL_MP4.is_file():
        size_mb = FINAL_MP4.stat().st_size / (1024 * 1024)
        log(f"Render complete: {FINAL_MP4.name} ({size_mb:.1f} MB)")
        send_ntfy(f"DONE! {name} — final.mp4 ready ({size_mb:.0f} MB). Review + upload when ready.")
    else:
        log("ERROR: render did not produce final.mp4")
        send_ntfy(f"Pipeline: render failed for {name}")
        return 1

    log("=" * 60)
    log("PIPELINE RUNNER — finished")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
