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
SUPABASE_SYNC = SCRIPTS_ROOT / "scripts" / "supabase_sync.py"
SUPABASE_CONFIG = ROOT / "tracker" / "supabase_config.json"


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


def supabase_sync(cmd: str = "sync") -> None:
    """Push current state to Supabase (best-effort, never blocks pipeline)."""
    if not SUPABASE_CONFIG.is_file():
        return
    try:
        subprocess.run(
            ["python3", str(SUPABASE_SYNC), cmd],
            cwd=ROOT, timeout=60, capture_output=True,
        )
    except Exception as exc:
        log(f"WARNING: supabase_sync {cmd} failed: {exc}")


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
    supabase_sync()
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

    # Upload as UNLISTED to YouTube for remote preview (no thumbnail yet)
    client_secrets = sorted((ROOT / "07-upload").glob("client_secret*.json"))
    unlisted_video_id = project.get("unlisted_video_id") or ""
    if not unlisted_video_id and YOUTUBE_TOKEN.is_file() and client_secrets:
        log("Uploading as UNLISTED for remote review preview…")
        ul_result = run(
            ["/Users/ganesh/miniconda3/bin/python3", str(UPLOAD),
             "--privacy", "unlisted", "--no-thumbnail"],
            "upload unlisted preview",
            check=False,
        )
        if ul_result.returncode == 0:
            # Read back the video ID that upload_to_youtube.py wrote to project.json
            project = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
            vid_id = project.get("youtube_video_id") or ""
            if vid_id:
                project["unlisted_video_id"] = vid_id
                project["youtube_video_id"] = None  # clear — will be set again on final publish
                PROJECT_FILE.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")
                unlisted_video_id = vid_id
                log(f"Unlisted preview: https://youtu.be/{vid_id}")
        else:
            log("WARNING: unlisted upload failed — review page will show no video preview")
    elif unlisted_video_id:
        log(f"Already have unlisted preview: {unlisted_video_id}")
    else:
        log("SKIP unlisted upload: no YouTube credentials")

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

    # Push thumbnails + video to Supabase for remote review
    supabase_sync()
    log("Supabase sync done — review at tracker/review.html")
    send_ntfy(f"🖼️ Review ready: {name}\nOpen the review page to pick a thumbnail")

    # Description
    if not project.get("description"):
        desc_result = run(["python3", str(SUGGEST_DESC)], "generate description", check=False)
        if desc_result.returncode != 0:
            log("WARNING: description generation failed — uploading without description")
        else:
            project = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))

    # YouTube upload
    if project.get("auto_upload"):
        client_secrets = sorted((ROOT / "07-upload").glob("client_secret*.json"))
        if not YOUTUBE_TOKEN.is_file():
            log("SKIP upload: no youtube_token.json — run upload_to_youtube.py --auth-only first")
            send_ntfy(f"DONE! {name} ({size_mb:.0f} MB) — upload skipped, no auth token.")
        elif not client_secrets:
            log("SKIP upload: no client_secret*.json in 07-upload/")
            send_ntfy(f"DONE! {name} ({size_mb:.0f} MB) — upload skipped, no client secrets.")
        else:
            # Copy selected thumbnail variant to 07-upload/ just before uploading
            import shutil as _shutil
            selected_variant = project.get("selected_thumbnail_variant", 1)
            chosen_thumb = DIR_THUMBS / f"thumbnail_v{selected_variant}.png"
            if chosen_thumb.is_file():
                _shutil.copy2(chosen_thumb, YOUTUBE_THUMBNAIL)
                log(f"Copied thumbnail_v{selected_variant}.png → {YOUTUBE_THUMBNAIL.name}")
            upload_args = ["python3", str(UPLOAD)]
            if YOUTUBE_THUMBNAIL.is_file():
                upload_args += ["--thumbnail", str(YOUTUBE_THUMBNAIL)]
            else:
                upload_args += ["--no-thumbnail"]
            upload_result = run(upload_args, "upload to YouTube", check=False)
            if upload_result.returncode == 0:
                log("Upload complete.")
                supabase_sync()  # update youtube_video_id in Supabase
                send_ntfy(
                    f"DONE! {name} uploaded to YouTube with thumbnail v1. "
                    "Check 07-upload/thumbnail_v1/v2/v3.png — swap if you prefer another."
                )
            else:
                log("WARNING: YouTube upload failed — video is ready locally.")
                send_ntfy(f"DONE! {name} ({size_mb:.0f} MB) — upload failed, check logs.")
    else:
        log("SKIP upload: set auto_upload: true in project.json to enable")
        send_ntfy(
            f"DONE! {name} — final.mp4 ready ({size_mb:.0f} MB). "
            "3 thumbnail variants in 07-upload/ — review before uploading."
        )

    log("=" * 60)
    log("PIPELINE RUNNER — finished")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
