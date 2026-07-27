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

from lib.folders import DIR_THUMBS, FINAL_MP4, MANIFEST_FILE, PROJECT_FILE, SHOT_PLAN_FILE, YOUTUBE_THUMBNAIL, YOUTUBE_TOKEN  # noqa: E402
from lib.notify import send_ntfy  # noqa: E402

LOG_FILE = ROOT / "tracker" / "overnight.log"
PREFLIGHT = SCRIPTS_ROOT / "scripts" / "preflight.py"
BUILD_PLAN = SCRIPTS_ROOT / "scripts" / "02_manifest" / "build_plan.py"
BUILD_SHOT_PLAN = SCRIPTS_ROOT / "scripts" / "02_manifest" / "build_shot_plan.py"
GENERATE = SCRIPTS_ROOT / "scripts" / "03_images" / "generate_images.py"
VERIFY_FRAMES = SCRIPTS_ROOT / "scripts" / "03_images" / "verify_frames.py"
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

    # Creative-director pass — full-video context, recurring cast, varied shot
    # types, sparing on-screen text. Best-effort: if it fails, generate_images.py
    # falls back to the mechanical scene text build_plan.py already wrote.
    if not SHOT_PLAN_FILE.is_file():
        shot_plan_result = run(["python3", str(BUILD_SHOT_PLAN)], "build shot plan (director pass)", check=False)
        if shot_plan_result.returncode != 0:
            log("WARNING: shot plan generation failed — continuing with mechanical scene text")

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

    # Final QA sweep — re-scan every frame for missing / degraded (low-res) /
    # duplicate renders and regenerate the bad ones BEFORE we render or mark done.
    # This is the safety net behind the inline check in generate_images.py.
    log("Running final frame QA sweep…")
    verify_result = subprocess.run(
        ["python3", "-u", str(VERIFY_FRAMES), str(workers)],
        cwd=ROOT,
        text=True,
    )
    if verify_result.returncode != 0:
        log("WARNING: some frames still failed QA after retries — rendering anyway, review needed")
        send_ntfy(f"Pipeline WARNING: {name} has frames that failed QA after retries — check the log")

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

    # Thumbnail — each of the 3 variants gets its OWN distinct headline so the
    # thumbnails differ in wording, not just pose. A manually set thumbnail_text
    # seeds variant 1; the rest come from the auto-generated hook options.
    headlines: list[str] = []
    manual = (project.get("thumbnail_text") or "").strip()
    if manual:
        headlines.append(manual)

    if len(headlines) < 3:
        log("Auto-generating thumbnail headline options...")
        suggest_result = run(["python3", str(SUGGEST_TEXT)], "suggest thumbnail text", check=False)
        options_file = ROOT / "tracker" / "thumbnail_options.json"
        if suggest_result.returncode == 0 and options_file.is_file():
            try:
                import json as _json
                options = _json.loads(options_file.read_text(encoding="utf-8")).get("options") or []
                log(f"Thumbnail headline options: {options}")
                for opt in options:
                    opt = (opt or "").strip()
                    if opt and opt not in headlines:
                        headlines.append(opt)
            except Exception as exc:
                log(f"WARNING: could not read thumbnail options: {exc}")

    if not headlines:
        log("WARNING: no thumbnail text — skipping thumbnail generation")
    else:
        # Persist the first headline as the canonical thumbnail_text.
        if project.get("thumbnail_text") != headlines[0]:
            project["thumbnail_text"] = headlines[0]
            proj_file = ROOT / "project.json"
            import json as _json
            proj_file.write_text(_json.dumps(project, indent=2) + "\n", encoding="utf-8")
        log(f"Thumbnail headlines per variant: {[headlines[(v - 1) % len(headlines)] for v in (1, 2, 3)]}")

        thumb_ok = False
        DIR_THUMBS.mkdir(parents=True, exist_ok=True)
        for variant in (1, 2, 3):
            headline = headlines[(variant - 1) % len(headlines)]
            r = run(
                ["python3", str(THUMBNAIL), f"--variant={variant}", f"--headline={headline}", "--ai"],
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
