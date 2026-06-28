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

import os
SCRIPTS_ROOT = Path(__file__).resolve().parents[1]  # repo root — where scripts/ lives
ROOT = Path(os.environ.get("PIPELINE_ROOT") or SCRIPTS_ROOT)  # project data root
sys.path.insert(0, str(SCRIPTS_ROOT / "scripts"))

from lib.folders import DIR_THUMBS, FINAL_MP4, MANIFEST_FILE, PROJECT_FILE, YOUTUBE_THUMBNAIL, YOUTUBE_TOKEN  # noqa: E402
from lib.notify import send_ntfy  # noqa: E402

LOG_FILE = ROOT / "tracker" / "overnight.log"
PREFLIGHT = SCRIPTS_ROOT / "scripts" / "preflight.py"
BUILD_PLAN = SCRIPTS_ROOT / "scripts" / "02_manifest" / "build_plan.py"
GENERATE = SCRIPTS_ROOT / "scripts" / "03_images" / "generate_images.py"
RENDER = SCRIPTS_ROOT / "scripts" / "04_render" / "render_draft_video.py"
THUMBNAIL = SCRIPTS_ROOT / "scripts" / "05_publish" / "generate_thumbnail.py"
SUGGEST_TEXT = SCRIPTS_ROOT / "scripts" / "05_publish" / "suggest_thumbnail_text.py"
SUGGEST_DESC = SCRIPTS_ROOT / "scripts" / "05_publish" / "suggest_description.py"
UPLOAD = SCRIPTS_ROOT / "scripts" / "05_publish" / "upload_to_youtube.py"
START_STUDIO = SCRIPTS_ROOT / "scripts" / "start_studio.sh"
STATUS_STUDIO = SCRIPTS_ROOT / "scripts" / "status_studio.sh"


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

    # Preflight (manifest check only — before build_plan runs)
    result = run(["python3", str(PREFLIGHT)], "preflight", check=False)
    if result.returncode != 0:
        log("ABORT: preflight failed")
        send_ntfy(f"Pipeline FAILED: preflight errors. {name}")
        return 1

    # Build manifest
    if not MANIFEST_FILE.is_file():
        run(["python3", str(BUILD_PLAN)], "build manifest")
    else:
        run(["python3", str(BUILD_PLAN), "refresh"], "refresh manifest")

    # Preflight again now that manifest exists
    result = run(["python3", str(PREFLIGHT), "--images"], "preflight (images)", check=False)
    if result.returncode != 0:
        log("ABORT: preflight (images) failed")
        send_ntfy(f"Pipeline FAILED: preflight errors after build_plan. {name}")
        return 1

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
    else:
        log("ERROR: render did not produce final.mp4")
        send_ntfy(f"Pipeline: render failed for {name}")
        return 1

    # Thumbnail — auto-generate headline if not set, then produce 3 variants
    thumbnail_text = project.get("thumbnail_text") or ""
    if not thumbnail_text:
        log("Auto-generating thumbnail headline options...")
        suggest_result = run(["python3", str(SUGGEST_TEXT)], "suggest thumbnail text", check=False)
        options_file = ROOT / "tracker" / "thumbnail_options.json"
        if suggest_result.returncode == 0 and options_file.is_file():
            try:
                import json as _json
                options = _json.loads(options_file.read_text(encoding="utf-8")).get("options") or []
                thumbnail_text = options[0].strip() if options else ""
                log(f"Thumbnail headline options: {options}")
                log(f"Using: {thumbnail_text!r}")
                # Write chosen text back to project.json so thumbnail script can read it
                if thumbnail_text:
                    project["thumbnail_text"] = thumbnail_text
                    proj_file = ROOT / "project.json"
                    proj_file.write_text(
                        _json.dumps(project, indent=2) + "\n", encoding="utf-8"
                    )
            except Exception as exc:
                log(f"WARNING: could not read thumbnail options: {exc}")
        if not thumbnail_text:
            log("WARNING: no thumbnail text — skipping thumbnail generation")

    if thumbnail_text:
        thumb_ok = False
        DIR_THUMBS.mkdir(parents=True, exist_ok=True)
        for variant in (1, 2, 3):
            r = run(
                ["python3", str(THUMBNAIL), f"--variant={variant}"],
                f"thumbnail v{variant}",
                check=False,
            )
            out = DIR_THUMBS / f"thumbnail_v{variant}.png"
            if r.returncode == 0 and out.is_file():
                thumb_ok = True
            else:
                log(f"WARNING: thumbnail variant {variant} failed")
        if not thumb_ok:
            log("WARNING: all thumbnail variants failed")

    # Description
    if not project.get("description"):
        desc_result = run(["python3", str(SUGGEST_DESC)], "generate description", check=False)
        if desc_result.returncode != 0:
            log("WARNING: description generation failed — upload without description or add it manually")
        else:
            project = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))

    send_ntfy(
        f"Thumbnails ready: {name} ({size_mb:.0f} MB)\n"
        "Open Studio UI to pick a thumbnail and upload to YouTube → http://127.0.0.1:47829"
    )

    log("=" * 60)
    log("PIPELINE RUNNER — finished")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
