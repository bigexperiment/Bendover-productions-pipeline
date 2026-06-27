#!/usr/bin/env python3
"""Supabase sync — push pipeline state + thumbnails to Supabase.

Video preview uses the unlisted YouTube video ID (no storage upload needed).

Usage:
    python3 scripts/supabase_sync.py sync      # push project state + thumbnails
    python3 scripts/supabase_sync.py poll      # check + act on approvals
    python3 scripts/supabase_sync.py watch     # sync + poll loop (every 30s)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("PIPELINE_ROOT") or SCRIPTS_ROOT)
sys.path.insert(0, str(SCRIPTS_ROOT / "scripts"))

from lib.folders import DIR_THUMBS, PROJECT_FILE  # noqa: E402

CONFIG_FILE = SCRIPTS_ROOT / "tracker" / "supabase_config.json"
UA = "curl/7.88.1"  # Cloudflare blocks Python default UA


# ── Config ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if not CONFIG_FILE.is_file():
        print(f"ERROR: Missing {CONFIG_FILE}", file=sys.stderr)
        sys.exit(1)
    return json.loads(CONFIG_FILE.read_text())


# ── REST helpers ──────────────────────────────────────────────────────────────

def _db_headers(cfg: dict) -> dict:
    return {
        "apikey": cfg["anon_key"],
        "Authorization": f"Bearer {cfg['anon_key']}",
        "Content-Type": "application/json",
        "User-Agent": UA,
    }


def _storage_headers(cfg: dict) -> dict:
    key = cfg.get("service_key") or cfg["anon_key"]
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "User-Agent": UA,
    }


def _req(url: str, method: str, body: dict | None, headers: dict) -> dict | list | None:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            body_obj = json.loads(raw)
            msg = body_obj.get("message", str(body_obj))[:200]
        except Exception:
            msg = raw.decode()[:200]
        print(f"  HTTP {e.code}: {msg}", file=sys.stderr)
        return None


def upsert_project(cfg: dict, row: dict) -> None:
    base = cfg["url"].rstrip("/")
    headers = _db_headers(cfg)
    headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
    _req(f"{base}/rest/v1/projects", "POST", row, headers)


def get_pending_approvals(cfg: dict, project_id: str) -> list[dict]:
    base = cfg["url"].rstrip("/")
    url = f"{base}/rest/v1/approvals?project_id=eq.{project_id}&processed_at=is.null&order=created_at.asc"
    result = _req(url, "GET", None, _db_headers(cfg))
    return result or []


def mark_approval_processed(cfg: dict, approval_id: int) -> None:
    base = cfg["url"].rstrip("/")
    now = datetime.now(timezone.utc).isoformat()
    headers = _db_headers(cfg)
    headers["Prefer"] = "return=minimal"
    _req(f"{base}/rest/v1/approvals?id=eq.{approval_id}", "PATCH",
         {"processed_at": now}, headers)


# ── Storage helpers ───────────────────────────────────────────────────────────

def upload_thumbnail(cfg: dict, project_id: str, variant: int, file_path: Path) -> str | None:
    """Upload a thumbnail PNG to Supabase Storage. Returns public URL."""
    if not file_path.is_file():
        return None
    base = cfg["url"].rstrip("/")
    storage_path = f"{project_id}/v{variant}.png"
    url = f"{base}/storage/v1/object/thumbnails/{storage_path}"
    headers = _storage_headers(cfg)
    headers["Content-Type"] = "image/png"
    headers["x-upsert"] = "true"
    data = file_path.read_bytes()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp.read()
        return f"{base}/storage/v1/object/public/thumbnails/{storage_path}"
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        if e.code == 409 or "already exists" in raw.lower():
            return f"{base}/storage/v1/object/public/thumbnails/{storage_path}"
        print(f"  Storage upload v{variant} failed: {e.code} {raw[:100]}", file=sys.stderr)
        return None


# ── Project state ─────────────────────────────────────────────────────────────

def build_row(project: dict, thumb_urls: dict) -> dict:
    done_frames, total_frames = 0, 0
    manifest_file = ROOT / "04-manifest" / "manifest.json"
    if manifest_file.is_file():
        try:
            manifest = json.loads(manifest_file.read_text())
            total_frames = len(manifest.get("scenes", []))
            images_dir = ROOT / "05-images"
            if images_dir.is_dir():
                done_frames = len(list(images_dir.glob("frame_*.png")))
        except Exception:
            pass

    return {
        "id": project["id"],
        "title": project.get("title") or project.get("name") or project["id"],
        "queue_status": project.get("queue_status") or project.get("status") or "unknown",
        "done_frames": done_frames,
        "total_frames": total_frames,
        "thumbnail_text": project.get("thumbnail_text") or "",
        "description": project.get("description") or "",
        "youtube_video_id": project.get("youtube_video_id") or None,
        "unlisted_video_id": project.get("unlisted_video_id") or None,
        "selected_thumbnail_variant": project.get("selected_thumbnail_variant") or 1,
        "thumbnail_urls": thumb_urls or {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Commands ──────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def cmd_sync() -> int:
    cfg = load_config()
    if not PROJECT_FILE.is_file():
        print("No project.json found", file=sys.stderr)
        return 1

    project = json.loads(PROJECT_FILE.read_text())
    project_id = project["id"]
    log(f"Syncing: {project_id}")

    # Upload thumbnails that exist
    thumb_urls: dict = {}
    for variant in (1, 2, 3):
        thumb = DIR_THUMBS / f"thumbnail_v{variant}.png"
        if thumb.is_file():
            log(f"  Uploading thumbnail v{variant} ({thumb.stat().st_size // 1024} KB)…")
            url = upload_thumbnail(cfg, project_id, variant, thumb)
            if url:
                thumb_urls[f"v{variant}"] = url
                log(f"  → uploaded")

    row = build_row(project, thumb_urls)
    log(f"  Upserting row (status={row['queue_status']})…")
    upsert_project(cfg, row)
    log("  Done.")
    return 0


def cmd_poll() -> int:
    cfg = load_config()
    if not PROJECT_FILE.is_file():
        return 0

    project = json.loads(PROJECT_FILE.read_text())
    project_id = project["id"]
    approvals = get_pending_approvals(cfg, project_id)
    if not approvals:
        return 0

    log(f"Found {len(approvals)} pending approval(s)")
    changed = False

    for ap in approvals:
        action = ap.get("action")
        data = ap.get("data") or {}
        log(f"  Action: {action} data={data}")

        if action == "select_thumbnail":
            variant = int(data.get("variant") or 1)
            project["selected_thumbnail_variant"] = variant
            changed = True
            log(f"  → selected_thumbnail_variant = {variant}")

        elif action == "regenerate_thumbnails":
            log("  → Regenerating 3 thumbnail variants…")
            THUMBNAIL = SCRIPTS_ROOT / "scripts" / "05_publish" / "generate_thumbnail.py"
            DIR_THUMBS.mkdir(parents=True, exist_ok=True)
            ok = False
            for variant in (1, 2, 3):
                r = subprocess.run(
                    ["python3", str(THUMBNAIL), f"--variant={variant}"],
                    cwd=ROOT, capture_output=True, text=True,
                )
                if r.returncode == 0:
                    ok = True
                    log(f"    v{variant}: OK")
                else:
                    log(f"    v{variant}: FAILED — {r.stderr.strip()[-150:]}")
            if ok:
                cmd_sync()

        elif action == "publish":
            # Make the unlisted video public and set the selected thumbnail
            log("  → Publishing video publicly…")
            _publish_video(project)
            project = json.loads(PROJECT_FILE.read_text())  # reload after publish

        mark_approval_processed(cfg, ap["id"])

    if changed:
        PROJECT_FILE.write_text(json.dumps(project, indent=2) + "\n")
        cmd_sync()

    return 0


def _publish_video(project: dict) -> None:
    """Change unlisted video to public and set selected thumbnail."""
    import shutil
    video_id = project.get("unlisted_video_id") or project.get("youtube_video_id")
    if not video_id:
        log("    No video_id to publish")
        return

    UPLOAD = SCRIPTS_ROOT / "scripts" / "05_publish" / "upload_to_youtube.py"
    CONDA = "/Users/ganesh/miniconda3/bin/python3"

    # Set thumbnail first
    selected = project.get("selected_thumbnail_variant", 1)
    thumb = DIR_THUMBS / f"thumbnail_v{selected}.png"
    from lib.folders import YOUTUBE_THUMBNAIL  # noqa: E402
    if thumb.is_file():
        shutil.copy2(thumb, YOUTUBE_THUMBNAIL)

    # Update video: make public + set thumbnail
    args = [CONDA, str(UPLOAD), "--update", "--video-id", video_id]
    if YOUTUBE_THUMBNAIL.is_file():
        args += ["--thumbnail", str(YOUTUBE_THUMBNAIL)]
    else:
        args += ["--no-thumbnail"]

    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if result.returncode == 0:
        log("    Published! Video is now public.")
        # Update project.json: store as the main youtube_video_id
        project["youtube_video_id"] = video_id
        project["queue_status"] = "done"
        PROJECT_FILE.write_text(json.dumps(project, indent=2) + "\n")
    else:
        log(f"    Publish failed: {result.stderr.strip()[-200:]}")


def cmd_watch(interval: int = 30) -> int:
    log(f"Watching for approvals every {interval}s — Ctrl+C to stop")
    while True:
        try:
            cmd_poll()
        except Exception as exc:
            log(f"Poll error: {exc}")
        time.sleep(interval)


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sync"
    if cmd == "sync":
        return cmd_sync()
    elif cmd == "poll":
        return cmd_poll()
    elif cmd == "watch":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        return cmd_watch(interval)
    else:
        print(f"Unknown command: {cmd}. Use: sync | poll | watch")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
