#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import mimetypes
import re
import shutil
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import urlopen, Request as UrlRequest


ROOT = Path(__file__).resolve().parent.parent
TRACKER = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "07_credits"))
from codex_account import read_codex_account  # noqa: E402
from fetch_codex_usage import read_usage_payload  # noqa: E402
from lib.folders import (  # noqa: E402
    AUDIO_EXTS,
    DIR_AUDIO,
    DIR_IMAGES,
    DIR_MANIFEST,
    DIR_OUTPUT,
    DIR_SCRIPT,
    DIR_STYLE_SAMPLES,
    DIR_TRANSCRIPT,
    DIR_UPLOAD,
    FINAL_MP4,
    MANIFEST_FILE,
    PREVIEW_MP4,
    PROGRESS_FILE,
    PROJECT_FILE,
    SCRIPT_FILE,
    STYLE_EXPLORE_RUN,
    STYLE_SAMPLES_MANIFEST,
    TRANSCRIPT_FILE,
    YOUTUBE_THUMBNAIL,
)
from lib.style_presets import apply_style_preset, load_style_presets  # noqa: E402

STYLE_EXPLORE_RUN_DIR = STYLE_EXPLORE_RUN
STYLE_EXPLORE_MANIFEST = STYLE_EXPLORE_RUN_DIR / "manifest.json"
STYLE_EXPLORE_PROGRESS = STYLE_EXPLORE_RUN_DIR / "progress.json"
STYLE_EXPLORE_CREDITS = STYLE_EXPLORE_RUN_DIR / "credits_log.json"
INDEX_FILE = TRACKER / "index.html"
PROJECTS_DIR = ROOT / "projects"
QUEUE_FILE   = TRACKER / "queue.json"
PORT = 47829
HOST = "0.0.0.0"

RUN_LOCK = threading.Lock()
ACTIVE_JOB: dict | None = None

# ── YouTube OAuth helpers ─────────────────────────────────────────────────────

YT_UPLOAD_DIR  = ROOT / "07-upload"
YT_TOKEN_FILE  = YT_UPLOAD_DIR / "youtube_token.json"
YT_SCOPES      = ["https://www.googleapis.com/auth/youtube.upload",
                   "https://www.googleapis.com/auth/youtube"]
YT_OAUTH_REDIRECT = f"http://127.0.0.1:{PORT}/api/youtube/auth/callback"
YT_AUTH_URI    = "https://accounts.google.com/o/oauth2/v2/auth"
YT_TOKEN_URI   = "https://oauth2.googleapis.com/token"


def _yt_client_secrets() -> dict | None:
    matches = sorted(YT_UPLOAD_DIR.glob("client_secret*.json"))
    if not matches:
        return None
    try:
        data = json.loads(matches[0].read_text(encoding="utf-8"))
        return data.get("installed") or data.get("web")
    except Exception:
        return None


def yt_auth_status() -> dict:
    cs = _yt_client_secrets()
    has_secrets = cs is not None
    has_token   = YT_TOKEN_FILE.is_file()
    expired     = False
    if has_token:
        try:
            tok = json.loads(YT_TOKEN_FILE.read_text(encoding="utf-8"))
            # Token is usable if it has a refresh_token (refresh happens automatically at upload time)
            has_token = bool(tok.get("refresh_token") or tok.get("token"))
        except Exception:
            has_token = False
    return {"has_secrets": has_secrets, "has_token": has_token, "expired": expired}


def yt_auth_url() -> str | None:
    cs = _yt_client_secrets()
    if not cs:
        return None
    params = {
        "client_id":     cs["client_id"],
        "redirect_uri":  YT_OAUTH_REDIRECT,
        "response_type": "code",
        "scope":         " ".join(YT_SCOPES),
        "access_type":   "offline",
        "prompt":        "consent",   # always get refresh_token
    }
    return f"{YT_AUTH_URI}?{urlencode(params)}"


def yt_exchange_code(code: str) -> dict:
    cs = _yt_client_secrets()
    if not cs:
        return {"ok": False, "error": "No client_secret file found in 07-upload/"}
    body = urlencode({
        "code":          code,
        "client_id":     cs["client_id"],
        "client_secret": cs["client_secret"],
        "redirect_uri":  YT_OAUTH_REDIRECT,
        "grant_type":    "authorization_code",
    }).encode()
    try:
        req = UrlRequest(YT_TOKEN_URI, data=body,
                         headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urlopen(req, timeout=15) as resp:
            tok = json.loads(resp.read().decode())
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    if "error" in tok:
        return {"ok": False, "error": tok.get("error_description", tok["error"])}

    # Save in google-auth compatible format
    token_data = {
        "token":         tok.get("access_token"),
        "refresh_token": tok.get("refresh_token"),
        "token_uri":     YT_TOKEN_URI,
        "client_id":     cs["client_id"],
        "client_secret": cs["client_secret"],
        "scopes":        YT_SCOPES,
    }
    YT_TOKEN_FILE.write_text(json.dumps(token_data, indent=2) + "\n", encoding="utf-8")
    return {"ok": True}

STEP_LABELS = {
    "setup": "Setup",
    "audio": "Audio",
    "manifest": "Manifest",
    "images": "Images",
    "render": "Render",
    "publish": "Publish",
}

def parse_multipart_form(body: bytes, content_type: str) -> dict[str, dict[str, bytes | str | None]]:
    """Minimal multipart/form-data parser (replaces removed stdlib cgi)."""
    if "boundary=" not in content_type:
        raise ValueError("Expected multipart/form-data")
    boundary = content_type.split("boundary=", 1)[1].split(";", 1)[0].strip().strip('"').encode()
    fields: dict[str, dict[str, bytes | str | None]] = {}
    for part in body.split(b"--" + boundary):
        chunk = part.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        header_block, _, content = chunk.partition(b"\r\n\r\n")
        if not header_block:
            continue
        name = filename = None
        for line in header_block.decode("utf-8", errors="replace").split("\r\n"):
            if not line.lower().startswith("content-disposition:"):
                continue
            for token in line.split(";", 1)[1].split(";"):
                token = token.strip()
                if token.startswith("name="):
                    name = token[5:].strip('"')
                elif token.startswith("filename="):
                    filename = token[9:].strip('"') or None
        if name:
            fields[name] = {"filename": filename, "data": content.rstrip(b"\r\n")}
    return fields


def load_json(path: Path, default: dict | list | None = None):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def save_project(data: dict) -> None:
    data = apply_style_preset(data)
    PROJECT_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_project() -> dict:
    project = load_json(PROJECT_FILE, {
        "name": "my-video",
        "step": "setup",
        "title": "",
        "description": "",
        "privacy": "public",
        "workers": 5,
        "style_preset_id": "",
        "style_preset_label": "",
        "image_style": (
            "simple educational cartoon illustration, hand-drawn doodle animation style, "
            "thick black outlines, flat colors, minimal shading, stickman characters, "
            "round white heads, expressive faces, thin black limbs, simple YouTube explainer "
            "animation style, clean background, limited colors, humorous but clear."
        ),
        "style_approved": False,
        "youtube_video_id": None,
    })
    return apply_style_preset(project)


def script_path() -> Path | None:
    if SCRIPT_FILE.is_file():
        return SCRIPT_FILE
    if TRANSCRIPT_FILE.is_file():
        return TRANSCRIPT_FILE
    return None


def audio_status() -> dict:
    from lib.audio_paths import find_narration_audio

    narration = None
    ready = False
    error = ""
    try:
        narration = find_narration_audio()
        ready = True
    except FileNotFoundError as exc:
        error = str(exc)

    return {
        "narration": narration.name if narration else None,
        "url": f"02-audio/{narration.name}" if narration else None,
        "ready": ready,
        "error": error,
    }


def infer_step(project: dict, script: Path | None, audio: dict, manifest: bool, total: int, pending: int, final_mp4: bool) -> str:
    if project.get("youtube_video_id"):
        return "publish"
    if final_mp4:
        return "publish"
    if total > 0 and pending == 0:
        return "render"
    if manifest and total > 0:
        return "images"
    transcript_ready = TRANSCRIPT_FILE.is_file() and TRANSCRIPT_FILE.read_text(encoding="utf-8").strip()
    if transcript_ready and audio["ready"]:
        return "manifest"
    if script and project.get("image_style"):
        return "audio"
    return "setup"


def count_images_on_disk() -> int:
    if not DIR_IMAGES.is_dir():
        return 0
    return sum(1 for _ in DIR_IMAGES.glob("*.png"))


def load_manifest_frames() -> list[dict]:
    if not MANIFEST_FILE.is_file():
        return []

    frames: list[dict] = []
    with MANIFEST_FILE.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            filename = row.get("filename", "")
            exists = (DIR_IMAGES / filename).is_file() if filename else False
            status = row.get("status") or ("done" if exists else "pending")
            frames.append(
                {
                    "timestamp": row.get("timestamp", ""),
                    "filename": filename,
                    "scene": row.get("scene", ""),
                    "transcript": row.get("transcript", ""),
                    "status": status,
                    "exists": exists,
                }
            )
    return frames


def load_disk_frames() -> list[dict]:
    if not DIR_IMAGES.is_dir():
        return []
    frames = []
    for path in sorted(DIR_IMAGES.glob("*.png")):
        stem = path.stem
        match = re.match(r"^(\d+)_(\d{2})$", stem)
        timestamp = f"{match.group(1)}:{match.group(2)}" if match else stem
        frames.append(
            {
                "timestamp": timestamp,
                "filename": path.name,
                "scene": "",
                "transcript": "",
                "status": "done",
                "exists": True,
            }
        )
    return frames


def get_all_frames() -> list[dict]:
    manifest_frames = load_manifest_frames()
    if manifest_frames:
        return manifest_frames
    return load_disk_frames()


def load_style_explore() -> dict:
    progress = load_json(STYLE_EXPLORE_PROGRESS, {})
    manifest = load_json(STYLE_EXPLORE_MANIFEST, {})
    credits = load_json(STYLE_EXPLORE_CREDITS, {})
    runner = load_json(TRACKER / "status.json", {})
    active = runner.get("mode") == "style_explore" or bool(progress.get("mode") == "style_explore")
    variants = manifest.get("variants") or []
    done = sum(1 for v in variants if (STYLE_EXPLORE_RUN_DIR / v.get("filename", "")).is_file())
    total = int(manifest.get("total") or len(variants) or 0)
    return {
        "active": active,
        "scene": manifest.get("scene", ""),
        "total": total,
        "done": done,
        "pending": max(0, total - done),
        "progress": progress,
        "credits": credits,
        "variants": variants,
    }


def paginate_style_explore_frames(
    *,
    status_filter: str = "all",
    offset: int = 0,
    limit: int = 60,
) -> dict:
    manifest = load_json(STYLE_EXPLORE_MANIFEST, {})
    frames: list[dict] = []
    for row in manifest.get("variants") or []:
        filename = row.get("filename", "")
        rel = f"style-explore-run/{filename}" if filename else ""
        exists = (STYLE_EXPLORE_RUN_DIR / filename).is_file() if filename else False
        status = "done" if exists else row.get("status", "pending")
        frames.append(
            {
                "timestamp": row.get("id", ""),
                "filename": rel,
                "label": row.get("label", ""),
                "scene": manifest.get("scene", ""),
                "transcript": row.get("label", ""),
                "status": status,
                "exists": exists,
            }
        )
    if status_filter == "done":
        frames = [f for f in frames if f["exists"]]
    elif status_filter == "pending":
        frames = [f for f in frames if not f["exists"]]
    total = len(frames)
    page = frames[offset : offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "frames": page, "mode": "style_explore"}


def paginate_frames(
    *,
    status_filter: str = "all",
    offset: int = 0,
    limit: int = 60,
    mode: str = "production",
) -> dict:
    if mode == "style_explore":
        return paginate_style_explore_frames(status_filter=status_filter, offset=offset, limit=limit)
    frames = get_all_frames()
    if status_filter == "done":
        frames = [f for f in frames if f["exists"] or f["status"] == "done"]
    elif status_filter == "pending":
        frames = [f for f in frames if not f["exists"] and f["status"] != "done"]

    total = len(frames)
    page = frames[offset : offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "frames": page}


def sync_project_step(project: dict, inferred: str) -> dict:
    order = ("setup", "audio", "manifest", "images", "render", "publish")
    current = project.get("step") or "setup"
    if current not in order:
        current = "setup"
    if order.index(inferred) > order.index(current):
        project = {**project, "step": inferred}
        save_project(project)
    return project


def build_status() -> dict:
    project = load_project()
    progress = load_json(PROGRESS_FILE, {})
    runner = load_json(TRACKER / "status.json", {})
    usage = read_usage_payload(force=False, max_cache_age=30)
    account = read_codex_account()
    recent = load_json(TRACKER / "recent.json", {})
    style_explore = load_style_explore()
    script = script_path()
    audio = audio_status()
    manifest = MANIFEST_FILE.is_file()
    final_mp4 = FINAL_MP4.is_file()

    explore_active = runner.get("mode") == "style_explore" or recent.get("mode") == "style_explore"
    if explore_active and style_explore.get("total"):
        total = int(style_explore.get("total") or 0)
        done = int(style_explore.get("done") or 0)
        pending = int(style_explore.get("pending") or 0)
        progress = style_explore.get("progress") or progress
    else:
        total = int(progress.get("total_frames") or 0)
        done = int(progress.get("done_frames") or 0)
        pending = int(progress.get("pending_frames") or progress.get("missing_frames") or 0)

    inferred = infer_step(project, script, audio, manifest, total, pending, final_mp4)
    project = sync_project_step(project, inferred)

    images_on_disk = count_images_on_disk()
    step_id = project.get("step") or "setup"

    return {
        "project": project,
        "dashboard": {
            "step_id": step_id,
            "step_label": STEP_LABELS.get(step_id, step_id.title()),
            "total_frames": total,
            "done_frames": done,
            "pending_frames": pending,
            "images_on_disk": images_on_disk,
            "percent": round((done / total) * 100, 1) if total else 0,
            "progress_bar": progress.get("progress_bar", ""),
        },
        "progress": progress,
        "runner": runner,
        "usage": usage,
        "account": account,
        "recent": recent,
        "style_explore": style_explore,
        "style_presets": load_style_presets(),
        "audio": audio,
    }


def pipeline_running() -> bool:
    pid_file = TRACKER / "overnight.pid"
    if not pid_file.is_file():
        return False
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        import os
        os.kill(pid, 0)
        return True
    except (ValueError, OSError):
        return False


AI_DRAFT = TRACKER / "ai_draft.txt"


def call_codex_text(codex_prompt: str, timeout: int = 180) -> str:
    """Run codex exec and return text from the ai_draft.txt response file."""
    if AI_DRAFT.is_file():
        AI_DRAFT.unlink()

    env = os.environ.copy()
    env["TERM"] = "xterm-256color"

    subprocess.run(
        [
            "codex", "exec",
            "-s", "workspace-write",
            "--dangerously-bypass-approvals-and-sandbox",
            "-C", str(ROOT),
            codex_prompt,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if AI_DRAFT.is_file():
        return AI_DRAFT.read_text(encoding="utf-8").strip()
    raise RuntimeError("Codex did not write tracker/ai_draft.txt — check codex is authenticated")


def build_ai_prompt(task: str, user_request: str, context: dict) -> tuple[str, bool]:
    """Return (codex_prompt, save_to_script_file)."""
    title  = context.get("title", "")
    brief  = context.get("brief", "")
    script = context.get("script", "")
    pid    = context.get("project_id", "")
    draft  = str(AI_DRAFT.relative_to(ROOT))

    # Script output path: per-project if pid given, else root
    if pid:
        script_rel = f"projects/{pid}/01-script/Script.txt"
    else:
        script_rel = "01-script/Script.txt"

    if task == "write_script":
        ctx = f"Video title: {title}\nBrief: {brief}\n" if (title or brief) else ""
        return (
            f"You are a YouTube video script writer for an educational stickman-explainer channel.\n"
            f"{ctx}"
            f"User request: {user_request}\n\n"
            f"Write a complete narration script. Spoken words only — no stage directions, no [MUSIC], "
            f"no host name, no scene labels. Clear paragraphs, punchy sentences.\n\n"
            f"Write the script to {script_rel} — overwrite it completely. "
            f"Do not create any other files."
        ), True

    if task == "improve_script":
        return (
            f"You are a YouTube script editor.\n"
            f"Video title: {title}\n\n"
            f"Here is the current script:\n---\n{script}\n---\n\n"
            f"User notes: {user_request or 'Tighten and improve generally.'}\n\n"
            f"Return an improved version: tighten sentences, add a stronger opening hook, "
            f"improve flow. Keep the same structure and meaning. Spoken words only.\n\n"
            f"Write the improved script to {script_rel} — overwrite it completely. "
            f"Do not create any other files."
        ), True

    if task == "ideas":
        ctx = f"Channel topic / niche: {user_request}" if user_request else "general educational YouTube"
        return (
            f"You are a YouTube content strategist.\n{ctx}\n\n"
            f"Generate 5 specific, curiosity-driven video ideas. For each idea give:\n"
            f"- Title (punchy, 5-10 words)\n"
            f"- One-sentence brief (what the viewer learns)\n\n"
            f"Write your response as plain text to {draft}. No other files."
        ), False

    # generic chat / anything else
    ctx_parts = []
    if title:  ctx_parts.append(f"Video title: {title}")
    if brief:  ctx_parts.append(f"Brief: {brief}")
    if script: ctx_parts.append(f"Script (first 300 chars): {script[:300]}…")
    ctx_str = ("\n".join(ctx_parts) + "\n\n") if ctx_parts else ""
    return (
        f"You are a helpful YouTube production assistant.\n{ctx_str}"
        f"User request: {user_request}\n\n"
        f"Write your response to {draft}. Plain text, no markdown headers. No other files."
    ), False


# ── Project / Queue management ────────────────────────────────────

def load_queue() -> list[dict]:
    if not QUEUE_FILE.is_file():
        return []
    try:
        return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def save_queue(q: list[dict]) -> None:
    TRACKER.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(q, indent=2) + "\n", encoding="utf-8")


def project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def create_project(title: str, brief: str = "") -> dict:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "my-video"
    q = load_queue()
    existing = {p["id"] for p in q}
    uid, n = slug, 2
    while uid in existing:
        uid = f"{slug}-{n}"; n += 1

    pd = PROJECTS_DIR / uid
    for sub in ("01-script", "02-audio", "03-transcript", "04-manifest", "05-images", "06-output", "tracker"):
        (pd / sub).mkdir(parents=True, exist_ok=True)

    # Symlink shared upload dir (credentials stay at repo root)
    upload_link = pd / "07-upload"
    if not upload_link.exists():
        upload_link.symlink_to(ROOT / "07-upload")

    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from lib.image_prompt import DEFAULT_IMAGE_STYLE, DEFAULT_STYLE_GUIDE, DEFAULT_TEXT_RULES, DEFAULT_TONE
    except Exception:
        DEFAULT_IMAGE_STYLE = DEFAULT_STYLE_GUIDE = DEFAULT_TEXT_RULES = DEFAULT_TONE = ""

    pj: dict = {
        "id": uid, "name": uid, "title": title, "video_brief": brief,
        "step": "script", "queue_status": "script",
        "style_preset_id": "", "style_preset_label": "",
        "image_style": DEFAULT_IMAGE_STYLE,
        "style_guide": DEFAULT_STYLE_GUIDE,
        "text_rules": DEFAULT_TEXT_RULES,
        "tone": DEFAULT_TONE,
        "workers": 5, "privacy": "public",
        "style_approved": False, "auto_upload": False, "youtube_video_id": None,
        "thumbnail_text": "", "description": "", "tags": [],
    }
    (pd / "project.json").write_text(json.dumps(pj, indent=2) + "\n", encoding="utf-8")

    entry: dict = {"id": uid, "title": title, "status": "script"}
    q.append(entry)
    save_queue(q)
    return entry


def get_project_detail(project_id: str) -> dict:
    pd = project_dir(project_id)
    q  = load_queue()
    entry = next((p for p in q if p["id"] == project_id), {"id": project_id, "status": "unknown"})

    pf = pd / "project.json"
    proj = json.loads(pf.read_text(encoding="utf-8")) if pf.is_file() else {}

    script_f = pd / "01-script" / "Script.txt"
    script_t = script_f.read_text(encoding="utf-8").strip() if script_f.is_file() else ""

    audio_d = pd / "02-audio"
    has_audio = any(f.suffix.lower() in AUDIO_EXTS for f in (audio_d.iterdir() if audio_d.exists() else []) if f.name != ".gitkeep")

    trans_f = pd / "03-transcript" / "transcript.txt"
    trans_t = trans_f.read_text(encoding="utf-8").strip() if trans_f.is_file() else ""

    # Thumbnail variants (per-project, in tracker/thumbs/)
    thumbs = []
    for n in (1, 2, 3):
        p2 = pd / "tracker" / "thumbs" / f"thumbnail_v{n}.png"
        thumbs.append({"n": n, "exists": p2.is_file()})

    # Per-project log
    log_f = pd / "tracker" / "overnight.log"
    log_lines: list[str] = []
    if log_f.is_file():
        log_lines = log_f.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]

    return {
        **entry,
        "title": proj.get("title") or entry.get("title", ""),
        "brief": proj.get("video_brief", ""),
        "style_preset_id": proj.get("style_preset_id", ""),
        "style_preset_label": proj.get("style_preset_label", ""),
        "style_approved": bool(proj.get("style_approved")),
        "youtube_video_id": proj.get("youtube_video_id"),
        "has_script": bool(script_t),
        "script_chars": len(script_t),
        "has_audio": has_audio,
        "has_transcript": bool(trans_t),
        "transcript_chars": len(trans_t),
        "thumbnails": thumbs,
        "log_lines": log_lines,
    }


def get_project_progress(project_id: str) -> dict:
    """Rich real-time status for a running project."""
    pd2 = project_dir(project_id)

    # project.json
    pf = pd2 / "project.json"
    proj = json.loads(pf.read_text(encoding="utf-8")) if pf.is_file() else {}

    # Image generation status (written by generate_images.py)
    status_f = pd2 / "tracker" / "status.json"
    img_status: dict = {}
    if status_f.is_file():
        try: img_status = json.loads(status_f.read_text(encoding="utf-8"))
        except Exception: pass

    done_frames  = img_status.get("done_frames", 0)
    total_frames = img_status.get("total_frames", 0)
    img_phase    = img_status.get("phase", "")       # running | waiting_credits | complete
    stop_reason  = img_status.get("stop_reason", "")

    # Usage (credits)
    usage: dict = {}
    try:
        payload = read_usage_payload()
        usage = payload or {}
    except Exception:
        pass

    # Thumbnails
    thumbs = []
    for n in (1, 2, 3):
        p2 = pd2 / "tracker" / "thumbs" / f"thumbnail_v{n}.png"
        thumbs.append({"n": n, "exists": p2.is_file()})

    # final.mp4
    has_mp4 = (pd2 / "06-output" / "final.mp4").is_file()

    # Description
    has_desc = bool(proj.get("description", "").strip())

    # Determine pipeline stage from log tail
    log_f = pd2 / "tracker" / "overnight.log"
    log_lines: list[str] = []
    stage = "images"
    if log_f.is_file():
        log_lines = log_f.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = "\n".join(log_lines[-20:])
        if "Upload complete" in tail or proj.get("youtube_video_id"):
            stage = "done"
        elif "Upload" in tail or "youtube" in tail.lower():
            stage = "uploading"
        elif thumbs[0]["exists"] or thumbs[1]["exists"] or thumbs[2]["exists"]:
            stage = "thumbnails"
        elif "thumbnail" in tail.lower() or "description" in tail.lower():
            stage = "thumbnails"
        elif has_mp4 or "Render complete" in tail:
            stage = "render_done"
        elif "Rendering" in tail or "render" in tail.lower():
            stage = "rendering"
        elif img_phase == "complete" or (done_frames > 0 and done_frames >= total_frames and total_frames > 0):
            stage = "render_pending"
        else:
            stage = "images"

    # Credit windows
    fh = usage.get("five_hour") or {}
    wk = usage.get("weekly") or {}
    five_hour = {"pct": fh.get("remaining_percent"), "reset": fh.get("reset_in", "")}
    weekly    = {"pct": wk.get("remaining_percent"), "reset": wk.get("reset_in", "")}

    return {
        "stage": stage,
        "img_phase": img_phase,
        "done_frames": done_frames,
        "total_frames": total_frames,
        "stop_reason": stop_reason,
        "has_mp4": has_mp4,
        "has_desc": has_desc,
        "thumbnails": thumbs,
        "youtube_video_id": proj.get("youtube_video_id"),
        "five_hour": five_hour,
        "weekly": weekly,
        "log_lines": log_lines[-25:],
    }


def update_project_queue_status(project_id: str, status: str) -> None:
    q = load_queue()
    for p in q:
        if p["id"] == project_id:
            p["status"] = status
            break
    save_queue(q)
    pf = project_dir(project_id) / "project.json"
    if pf.is_file():
        data = json.loads(pf.read_text(encoding="utf-8"))
        data["queue_status"] = status
        pf.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def queue_runner_running() -> bool:
    pf = TRACKER / "queue.pid"
    if not pf.is_file():
        return False
    try:
        pid = int(pf.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, OSError):
        return False


# ── Text file helpers ─────────────────────────────────────────────

def _text_file_for_kind(kind: str) -> "Path | None":
    if kind == "script":
        return SCRIPT_FILE
    if kind == "transcript":
        return TRANSCRIPT_FILE
    return None


def build_setup_status() -> dict:
    project = load_project()
    script_text = SCRIPT_FILE.read_text(encoding="utf-8").strip() if SCRIPT_FILE.is_file() else ""
    transcript_text = TRANSCRIPT_FILE.read_text(encoding="utf-8").strip() if TRANSCRIPT_FILE.is_file() else ""
    audio = audio_status()
    return {
        "script": bool(script_text),
        "script_chars": len(script_text),
        "audio": audio["ready"],
        "transcript": bool(transcript_text),
        "transcript_chars": len(transcript_text),
        "style_approved": bool(project.get("style_approved")),
        "pipeline_running": pipeline_running(),
        "title": project.get("title", ""),
        "brief": project.get("video_brief", ""),
    }


def begin_pipeline(title: str, brief: str) -> dict:
    try:
        project = load_project()
        name = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "my-video"
        project["name"] = name
        project["title"] = title
        project["video_brief"] = brief
        project["style_approved"] = True
        project["step"] = "images"
        save_project(project)
        subprocess.Popen(
            ["bash", "scripts/start_overnight.sh"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def get_pipeline_log(lines: int = 30) -> dict:
    log_file = TRACKER / "overnight.log"
    if not log_file.is_file():
        return {"lines": []}
    try:
        text = log_file.read_text(encoding="utf-8", errors="replace")
        all_lines = text.splitlines()
        return {"lines": all_lines[-lines:]}
    except OSError:
        return {"lines": []}


def get_thumbnails() -> dict:
    variants = []
    for n in (1, 2, 3):
        rel = f"07-upload/thumbnail_v{n}.png"
        path = ROOT / rel
        variants.append({"n": n, "url": rel, "exists": path.is_file()})
    selected = None
    if YOUTUBE_THUMBNAIL.is_file():
        selected = f"07-upload/{YOUTUBE_THUMBNAIL.name}"
    return {"variants": variants, "selected": selected}


def select_thumbnail(variant: int) -> dict:
    src = DIR_UPLOAD / f"thumbnail_v{variant}.png"
    if not src.is_file():
        return {"ok": False, "error": f"thumbnail_v{variant}.png not found"}
    try:
        shutil.copy2(src, YOUTUBE_THUMBNAIL)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def run_command(label: str, args: list[str], env: dict | None = None) -> None:
    global ACTIVE_JOB
    with RUN_LOCK:
        ACTIVE_JOB = {"label": label, "args": args, "status": "running"}

    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, env=env)

    with RUN_LOCK:
        ACTIVE_JOB = {
            "label": label,
            "status": "done" if proc.returncode == 0 else "error",
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-4000:],
        }


def start_job(label: str, args: list[str], env: dict | None = None) -> dict:
    if ACTIVE_JOB and ACTIVE_JOB.get("status") == "running":
        return {"ok": False, "error": f"Already running: {ACTIVE_JOB['label']}"}
    threading.Thread(target=run_command, args=(label, args, env), daemon=True).start()
    return {"ok": True, "started": label}


def handle_run(body: dict) -> dict:
    action = body.get("action")
    project = load_project()
    workers = int(body.get("workers") or project.get("workers") or 5)
    force = bool(body.get("force"))

    actions = {
        "build_plan": (["python3", "scripts/02_manifest/build_plan.py"], "Build cut plan + manifest"),
        "refresh_manifest": (["python3", "scripts/02_manifest/build_plan.py", "refresh"], "Refresh manifest"),
        "generate_images": (
            ["python3", "scripts/03_images/generate_images.py", str(workers)] + (["--force"] if force else []),
            f"Generate images ({workers} workers)",
        ),
        "generate_style_explore": (
            ["python3", "scripts/03_images/generate_style_explore.py", str(workers)] + (["--force"] if force else []),
            f"Style explore ({workers} workers)",
        ),
        "refresh_usage": (["python3", "scripts/07_credits/fetch_codex_usage.py", "--force"], "Refresh Codex usage"),
        "render_preview": (["python3", "scripts/04_render/render_draft_video.py", "--limit", "30", "--output", "06-output/preview.mp4"], "Render preview"),
        "render_final": (["python3", "scripts/04_render/render_draft_video.py", "--output", "06-output/final.mp4"], "Render final"),
    }

    if action == "generate_images" and not project.get("style_approved"):
        return {"ok": False, "error": "Enable style_approved in project settings first"}

    if action in actions:
        args, label = actions[action]
        return start_job(label, args)

    return {"ok": False, "error": f"Unknown action: {action}"}


def resolve_file(url_path: str) -> Path | None:
    path = urlparse(url_path).path
    if path in ("", "/"):
        path = "/tracker/index.html"
    if path in ("/favicon.ico", "/favicon.svg"):
        fav = TRACKER / "favicon.svg"
        return fav if fav.is_file() else None

    rel = unquote(path.lstrip("/"))
    if not rel:
        return None

    candidate = (ROOT / rel).resolve()
    root_resolved = ROOT.resolve()

    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None

    return candidate if candidate.is_file() else None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - [%s] %s\n" % (self.address_string(), self.command, fmt % args))

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _send_file(self, file_path: Path) -> None:
        mime, _ = mimetypes.guess_type(str(file_path))
        mime = mime or "application/octet-stream"
        size = file_path.stat().st_size
        range_header = self.headers.get("Range")

        if range_header and mime.startswith("video/"):
            match = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if match:
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
                end = min(end, size - 1)
                if start <= end:
                    with file_path.open("rb") as handle:
                        handle.seek(start)
                        chunk = handle.read(end - start + 1)
                    self.send_response(206)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.send_header("Content-Length", str(len(chunk)))
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(chunk)
                    return

        with file_path.open("rb") as handle:
            content = handle.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        if mime.startswith("video/"):
            self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/status":
            try:
                self._send_json(build_status())
            except Exception as exc:
                self._send_json({"error": str(exc), "project": load_project()}, 500)
            return
        if path == "/api/project":
            self._send_json(load_project())
            return
        if path == "/api/style-presets":
            self._send_json({"presets": load_style_presets()})
            return
        if path == "/api/frames":
            query = parse_qs(parsed.query)
            status_filter = (query.get("status") or ["all"])[0]
            offset = int((query.get("offset") or ["0"])[0])
            limit = min(int((query.get("limit") or ["80"])[0]), 200)
            mode = (query.get("mode") or ["production"])[0]
            self._send_json(paginate_frames(status_filter=status_filter, offset=offset, limit=limit, mode=mode))
            return
        if path == "/api/setup-status":
            self._send_json(build_setup_status())
            return
        if path == "/api/pipeline/log":
            self._send_json(get_pipeline_log())
            return
        if path == "/api/thumbnails":
            self._send_json(get_thumbnails())
            return
        if path == "/api/text-content":
            kind = parse_qs(urlparse(self.path).query).get("kind", [""])[0]
            project_id = parse_qs(urlparse(self.path).query).get("project", [""])[0]
            if project_id:
                fp = project_dir(project_id) / ("01-script/Script.txt" if kind == "script" else "03-transcript/transcript.txt")
            else:
                fp = _text_file_for_kind(kind)
            if fp is None:
                self._send_json({"ok": False, "error": "unknown kind"}, 400)
                return
            if fp.is_file():
                content = fp.read_text(encoding="utf-8")
                self._send_json({"ok": True, "content": content, "chars": len(content.strip())})
            else:
                self._send_json({"ok": True, "content": "", "chars": 0})
            return

        if path == "/api/job/status":
            self._send_json(ACTIVE_JOB or {"status": "idle"})
            return

        if path == "/api/youtube/auth/status":
            self._send_json(yt_auth_status())
            return

        if path == "/api/youtube/auth/start":
            url = yt_auth_url()
            if not url:
                self._send_json({"error": "No client_secret*.json found in 07-upload/"}, 400)
                return
            self.send_response(302)
            self.send_header("Location", url)
            self.end_headers()
            return

        if path == "/api/youtube/auth/callback":
            qs = parse_qs(urlparse(self.path).query)
            code = (qs.get("code") or [""])[0]
            error = (qs.get("error") or [""])[0]
            if error or not code:
                html = f"<h2>Auth failed: {error or 'no code returned'}</h2><a href='/'>Back to Studio</a>"
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(html.encode())
                return
            result = yt_exchange_code(code)
            if result["ok"]:
                self.send_response(302)
                self.send_header("Location", "/?yt_auth=ok")
                self.end_headers()
            else:
                html = f"<h2>Token exchange failed</h2><p>{result['error']}</p><a href='/'>Back</a>"
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(html.encode())
            return

        if path == "/api/projects":
            q = load_queue()
            self._send_json({"projects": q, "queue_running": queue_runner_running()})
            return

        if path == "/api/queue/log":
            log_f = TRACKER / "queue.log"
            lines: list[str] = []
            if log_f.is_file():
                lines = log_f.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
            self._send_json({"lines": lines, "running": queue_runner_running()})
            return

        if path == "/review" or path == "/tracker/review.html":
            review_html = TRACKER / "review.html"
            if review_html.is_file():
                content = review_html.read_text(encoding="utf-8")
                cfg_file = TRACKER / "supabase_config.json"
                if cfg_file.is_file():
                    try:
                        cfg = json.loads(cfg_file.read_text())
                        content = content.replace(
                            '"REPLACE_WITH_SUPABASE_URL"',
                            json.dumps(cfg.get("url", ""))
                        ).replace(
                            '"REPLACE_WITH_SUPABASE_ANON_KEY"',
                            json.dumps(cfg.get("anon_key", ""))
                        )
                    except Exception:
                        pass
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(content.encode())
            else:
                self.send_error(404, "review.html not found")
            return

        if path.startswith("/api/projects/") and path.endswith("/progress"):
            project_id = path[len("/api/projects/"):-len("/progress")]
            self._send_json(get_project_progress(project_id))
            return

        if path.startswith("/api/projects/"):
            project_id = path[len("/api/projects/"):]
            if "/" in project_id:
                self.send_error(404, "not found"); return
            try:
                self._send_json(get_project_detail(project_id))
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)
            return

        file_path = resolve_file(self.path)
        if file_path:
            self._send_file(file_path)
            return

        self.send_error(404, f"Not found: {path} (root: {ROOT})")

    def do_POST(self) -> None:
        path = urlparse(self.path).path

        if path == "/api/project":
            data = self._read_json()
            current = load_project()
            current.update(data)
            save_project(current)
            self._send_json({"ok": True, "project": load_project()})
            return

        if path == "/api/text-content":
            data = self._read_json()
            kind = str(data.get("kind", ""))
            content = str(data.get("content", ""))
            pid = str(data.get("project_id", ""))
            if pid:
                fp = project_dir(pid) / ("01-script/Script.txt" if kind == "script" else "03-transcript/transcript.txt")
            else:
                fp = _text_file_for_kind(kind)
            if fp is None:
                self._send_json({"ok": False, "error": "unknown kind"}, 400)
                return
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            self._send_json({"ok": True, "chars": len(content.strip())})
            return

        if path == "/api/text-content/delete":
            data = self._read_json()
            kind = str(data.get("kind", ""))
            pid = str(data.get("project_id", ""))
            if pid:
                fp = project_dir(pid) / ("01-script/Script.txt" if kind == "script" else "03-transcript/transcript.txt")
            else:
                fp = _text_file_for_kind(kind)
            if fp is None:
                self._send_json({"ok": False, "error": "unknown kind"}, 400)
                return
            if fp.is_file():
                fp.unlink()
            self._send_json({"ok": True})
            return

        # ── Project management ────────────────────────────────────
        if path == "/api/projects/create":
            data = self._read_json()
            title = str(data.get("title", "")).strip()
            brief = str(data.get("brief", "")).strip()
            if not title:
                self._send_json({"ok": False, "error": "title required"}, 400); return
            try:
                entry = create_project(title, brief)
                self._send_json({"ok": True, "project": entry})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return

        if path.startswith("/api/projects/") and path.endswith("/update"):
            project_id = path[len("/api/projects/"):-len("/update")]
            data = self._read_json()
            pd2 = project_dir(project_id)
            pf = pd2 / "project.json"
            if not pf.is_file():
                self._send_json({"ok": False, "error": "project not found"}, 404); return
            proj = json.loads(pf.read_text(encoding="utf-8"))
            proj.update(data)
            pf.write_text(json.dumps(proj, indent=2) + "\n", encoding="utf-8")
            # Sync title / status to queue
            q = load_queue()
            for p in q:
                if p["id"] == project_id:
                    if "title" in data: p["title"] = data["title"]
                    if "status" in data: p["status"] = data["status"]
                    break
            save_queue(q)
            self._send_json({"ok": True})
            return

        if path.startswith("/api/projects/") and path.endswith("/queue"):
            project_id = path[len("/api/projects/"):-len("/queue")]
            update_project_queue_status(project_id, "queued")
            self._send_json({"ok": True})
            # Auto-start queue runner if not running
            if not queue_runner_running():
                subprocess.Popen(
                    ["bash", "scripts/start_queue.sh"],
                    cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            return

        if path.startswith("/api/projects/") and path.endswith("/thumbnail/select"):
            project_id = path[len("/api/projects/"):-len("/thumbnail/select")]
            data = self._read_json()
            variant = int(data.get("variant", 1))
            pd2 = project_dir(project_id)
            src = pd2 / "tracker" / "thumbs" / f"thumbnail_v{variant}.png"
            if src.is_file():
                # Save selection to project.json for upload step
                pf2 = pd2 / "project.json"
                if pf2.is_file():
                    import json as _j
                    pdata = _j.loads(pf2.read_text(encoding="utf-8"))
                    pdata["selected_thumbnail_variant"] = variant
                    pf2.write_text(_j.dumps(pdata, indent=2) + "\n", encoding="utf-8")
                self._send_json({"ok": True})
            else:
                self._send_json({"ok": False, "error": "variant not found"}, 404)
            return

        if path.startswith("/api/projects/") and path.endswith("/upload/youtube"):
            project_id = path[len("/api/projects/"):-len("/upload/youtube")]
            pd2 = project_dir(project_id)
            # Copy selected thumbnail to 07-upload/ before uploading
            import shutil as _shu, json as _j2
            pf2 = pd2 / "project.json"
            if pf2.is_file():
                pdata = _j2.loads(pf2.read_text(encoding="utf-8"))
                variant = pdata.get("selected_thumbnail_variant", 1)
                src_thumb = pd2 / "tracker" / "thumbs" / f"thumbnail_v{variant}.png"
                dst_thumb = pd2 / "07-upload" / "thumbnail.png"
                if src_thumb.is_file():
                    _shu.copy2(src_thumb, dst_thumb)
            env = os.environ.copy()
            env["PIPELINE_ROOT"] = str(pd2)
            # Use conda python — has google-auth installed
            conda_python = "/Users/ganesh/miniconda3/bin/python3"
            upload_script = str(ROOT / "scripts" / "05_publish" / "upload_to_youtube.py")
            result = start_job(
                "Upload to YouTube",
                [conda_python, upload_script],
                env=env,
            )
            self._send_json(result)
            return

        if path.startswith("/api/projects/") and path.endswith("/upload"):
            # File upload for a specific project
            project_id = path[len("/api/projects/"):-len("/upload")]
            self._handle_upload(project_id=project_id)
            return

        if path == "/api/ai":
            data = self._read_json()
            task         = str(data.get("task", "chat"))
            user_request = str(data.get("prompt", "")).strip()
            context      = data.get("context", {})
            pid          = str(data.get("project_id", "")).strip()

            if not user_request and task not in ("improve_script",):
                self._send_json({"ok": False, "error": "prompt is required"}, 400)
                return

            # For script tasks, override the output path if project_id given
            if pid:
                context["project_id"] = pid

            try:
                codex_prompt, saves_to_script = build_ai_prompt(task, user_request, context)
                call_codex_text(codex_prompt)

                if saves_to_script:
                    fp = (project_dir(pid) / "01-script" / "Script.txt") if pid else SCRIPT_FILE
                    content = fp.read_text(encoding="utf-8").strip() if fp.is_file() else ""
                    self._send_json({"ok": True, "saved_to": "script", "content": content, "chars": len(content)})
                else:
                    content = AI_DRAFT.read_text(encoding="utf-8").strip() if AI_DRAFT.is_file() else ""
                    self._send_json({"ok": True, "response": content})
            except subprocess.TimeoutExpired:
                self._send_json({"ok": False, "error": "Codex timed out (>180s) — try a shorter request"}, 500)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return

        if path == "/api/queue/start":
            already = queue_runner_running()
            if not already:
                subprocess.Popen(
                    ["bash", "scripts/start_queue.sh"],
                    cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            self._send_json({"ok": True, "already_running": already})
            return

        if path == "/api/queue/stop":
            stopped = False
            # Kill queue runner
            pf = TRACKER / "queue.pid"
            if pf.is_file():
                try:
                    pid = int(pf.read_text().strip())
                    os.kill(pid, 15)  # SIGTERM
                    stopped = True
                except (ValueError, OSError):
                    pass
                pf.unlink(missing_ok=True)
            # Kill overnight runner / generate_images if running
            opf = TRACKER / "overnight.pid"
            if opf.is_file():
                try:
                    pid = int(opf.read_text().strip())
                    os.kill(pid, 15)
                except (ValueError, OSError):
                    pass
                opf.unlink(missing_ok=True)
            # Also kill any lingering generate_images / overnight_runner by name
            subprocess.run(
                ["pkill", "-f", "generate_images.py"], capture_output=True
            )
            subprocess.run(
                ["pkill", "-f", "overnight_runner.py"], capture_output=True
            )
            # Reset any "running" projects back to "queued" so they re-run next time
            q = load_queue()
            changed = False
            for p in q:
                if p.get("status") == "running":
                    p["status"] = "queued"
                    changed = True
            if changed:
                save_queue(q)
            self._send_json({"ok": True, "stopped": stopped})
            return

        if path == "/api/reset":
            try:
                subprocess.run(
                    [sys.executable, str(ROOT / "scripts" / "clear_workspace.py")],
                    cwd=ROOT, check=True, capture_output=True,
                )
                self._send_json({"ok": True})
            except subprocess.CalledProcessError as exc:
                self._send_json({"ok": False, "error": exc.stderr.decode()}, 500)
            return

        if path == "/api/run":
            result = handle_run(self._read_json())
            self._send_json(result, 200 if result.get("ok") else 400)
            return

        if path == "/api/upload":
            self._handle_upload()
            return
        if path == "/api/pipeline/begin":
            body = self._read_json()
            result = begin_pipeline(
                title=str(body.get("title", "")).strip(),
                brief=str(body.get("brief", "")).strip(),
            )
            self._send_json(result, 200 if result.get("ok") else 400)
            return
        if path == "/api/thumbnail/select":
            body = self._read_json()
            variant = int(body.get("variant", 0))
            if variant not in (1, 2, 3):
                self._send_json({"ok": False, "error": "variant must be 1, 2, or 3"}, 400)
                return
            result = select_thumbnail(variant)
            self._send_json(result, 200 if result.get("ok") else 400)
            return
        if path == "/api/youtube/upload":
            result = start_job(
                "upload to YouTube",
                ["/Users/ganesh/miniconda3/bin/python3", "scripts/05_publish/upload_to_youtube.py"],
            )
            self._send_json(result, 200 if result.get("ok") else 400)
            return

        if path == "/api/supabase/sync":
            result = start_job("supabase sync", ["python3", "scripts/supabase_sync.py", "sync"])
            self._send_json(result, 200 if result.get("ok") else 400)
            return

        if path == "/api/supabase/config":
            cfg_file = ROOT / "tracker" / "supabase_config.json"
            if cfg_file.is_file():
                try:
                    cfg = json.loads(cfg_file.read_text())
                    self._send_json({"ok": True, "url": cfg.get("url", ""), "configured": True})
                except Exception:
                    self._send_json({"ok": False, "configured": False})
            else:
                self._send_json({"ok": False, "configured": False})
            return

        if path == "/api/supabase/save-config":
            body = self._read_json()
            url = (body.get("url") or "").strip()
            key = (body.get("anon_key") or "").strip()
            if not url or not key:
                self._send_json({"ok": False, "error": "url and anon_key required"}, 400)
                return
            cfg_file = ROOT / "tracker" / "supabase_config.json"
            cfg_file.write_text(json.dumps({"url": url, "anon_key": key}, indent=2) + "\n")
            self._send_json({"ok": True})
            return

        self.send_error(404)

    def _handle_upload(self, project_id: str = "") -> None:
        content_type = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            form = parse_multipart_form(body, content_type)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 400)
            return

        kind_field = form.get("kind", {})
        kind = kind_field.get("data", b"script")
        kind = kind.decode("utf-8") if isinstance(kind, bytes) else "script"
        item = form.get("file")
        if not item or not item.get("filename"):
            self._send_json({"ok": False, "error": "No file"}, 400)
            return

        filename = Path(str(item["filename"])).name
        file_data = item["data"]
        if not isinstance(file_data, bytes):
            self._send_json({"ok": False, "error": "No file data"}, 400)
            return

        # Resolve target directories (per-project or root)
        if project_id:
            pd2 = project_dir(project_id)
            d_script = pd2 / "01-script"; sf = d_script / "Script.txt"
            d_audio  = pd2 / "02-audio"
            d_trans  = pd2 / "03-transcript"; tf = d_trans / "transcript.txt"
        else:
            d_script = DIR_SCRIPT; sf = SCRIPT_FILE
            d_audio  = DIR_AUDIO
            d_trans  = DIR_TRANSCRIPT; tf = TRANSCRIPT_FILE

        if kind == "script":
            d_script.mkdir(parents=True, exist_ok=True)
            sf.write_bytes(file_data)
            chars = len(file_data.decode("utf-8", errors="replace").strip())
            self._send_json({"ok": True, "chars": chars})
            return

        if kind == "audio":
            d_audio.mkdir(parents=True, exist_ok=True)
            for p in d_audio.iterdir():
                if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
                    p.unlink()
            dest = d_audio / filename
            dest.write_bytes(file_data)
            self._send_json({"ok": True, "path": f"02-audio/{dest.name}"})
            return

        if kind == "transcript":
            d_trans.mkdir(parents=True, exist_ok=True)
            tf.write_bytes(file_data)
            chars = len(file_data.decode("utf-8", errors="replace").strip())
            self._send_json({"ok": True, "chars": chars})
            return

        self._send_json({"ok": False, "error": f"Unknown kind: {kind}"}, 400)


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((HOST, port))
        except OSError:
            return False
    return True


def pick_port(preferred: int) -> int:
    for port in range(preferred, preferred + 10):
        if port_is_free(port):
            return port
    raise SystemExit(
        f"ERROR: No free port in {preferred}-{preferred + 9}. "
        f"Kill stale server: lsof -tiTCP:{preferred}-sTCP:LISTEN | xargs kill"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Video studio UI server")
    parser.add_argument("--port", type=int, default=PORT, help=f"Preferred port (default {PORT})")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not INDEX_FILE.is_file():
        print(f"ERROR: Missing {INDEX_FILE}", file=sys.stderr)
        sys.exit(1)

    port = pick_port(args.port)
    if port != args.port:
        print(f"NOTE: Port {args.port} busy, using {port} instead")

    port_file = TRACKER / "port.txt"
    port_file.write_text(f"{port}\n", encoding="utf-8")

    print(f"Project root: {ROOT}")
    print(f"Studio UI:  http://127.0.0.1:{port}/")
    print(f"            http://0.0.0.0:{port}/ (all interfaces)")

    ThreadingHTTPServer.allow_reuse_address = True
    try:
        with ThreadingHTTPServer((HOST, port), Handler) as httpd:
            httpd.serve_forever()
    except OSError as exc:
        print(f"ERROR: Could not bind port {port}: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
