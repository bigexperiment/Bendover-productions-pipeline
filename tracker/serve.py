#!/usr/bin/env python3
"""Bendover Productions Studio — local UI server. No DB, no auth, file-based state."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parent.parent
TRACKER = Path(__file__).resolve().parent
PROJECTS_DIR = ROOT / "projects"
QUEUE_FILE = TRACKER / "queue.json"
QUEUE_PID_FILE = TRACKER / "queue.pid"
INDEX_FILE = TRACKER / "index.html"
PORT = 47829

sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "07_credits"))

from lib import channels  # noqa: E402

try:
    from fetch_codex_usage import enrich_usage_payload, read_usage_payload  # noqa: E402
    _HAS_CREDITS = True
except ImportError:
    _HAS_CREDITS = False

_yt_lock = threading.Lock()
_yt_running: set[str] = set()

def has_audio_file(pid: str) -> bool:
    audio_dir = PROJECTS_DIR / pid / "02-audio"
    return audio_dir.is_dir() and any(
        f.suffix.lower() in (".mp3", ".wav", ".m4a")
        for f in audio_dir.iterdir()
        if f.is_file() and f.name != ".gitkeep"
    )


def has_transcript_file(pid: str) -> bool:
    transcript = PROJECTS_DIR / pid / "03-transcript" / "transcript.txt"
    return transcript.is_file() and transcript.stat().st_size > 50


def maybe_advance_to_style(pid: str) -> None:
    p = load_project(pid)
    if not p:
        return
    if has_audio_file(pid) and has_transcript_file(pid) and p.get("queue_status", "upload") == "upload":
        p["queue_status"] = "style"
        save_project(pid, p)


# ── Transcription (local Whisper — replaces manual TurboScribe upload) ────────
WHISPER_PYTHON = ROOT / ".venv-whisper" / "bin" / "python3"
TRANSCRIBE_SCRIPT = ROOT / "scripts" / "01_audio" / "generate_transcript.py"
_transcribing: set[str] = set()
_transcribe_lock = threading.Lock()


def transcribe_progress_path(pid: str) -> Path:
    return PROJECTS_DIR / pid / "tracker" / "transcribe_progress.json"


def load_transcribe_progress(pid: str) -> dict | None:
    pf = transcribe_progress_path(pid)
    if not pf.is_file():
        return None
    try:
        return json.loads(pf.read_text(encoding="utf-8"))
    except Exception:
        return None


def start_transcription(pid: str) -> None:
    """Kick off local Whisper transcription in the background. Deletes any
    stale transcript first so has_transcript_file() can't false-positive on
    an old file while the new one is being generated."""
    with _transcribe_lock:
        if pid in _transcribing:
            return
        _transcribing.add(pid)

    proj_dir = PROJECTS_DIR / pid
    old_transcript = proj_dir / "03-transcript" / "transcript.txt"
    old_transcript.unlink(missing_ok=True)
    progress_file = transcribe_progress_path(pid)
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    progress_file.write_text(json.dumps({"status": "running", "pct": 0}), encoding="utf-8")

    def run() -> None:
        try:
            env = {**os.environ, "PIPELINE_ROOT": str(proj_dir)}
            result = subprocess.run(
                [str(WHISPER_PYTHON), "-u", str(TRANSCRIBE_SCRIPT),
                 "--model", "medium.en", "--progress-file", str(progress_file)],
                cwd=ROOT, env=env, timeout=1800,
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                lines = [ln.strip() for ln in (result.stderr or result.stdout or "").splitlines() if ln.strip()]
                err = lines[-1] if lines else f"Transcription failed (exit {result.returncode})"
                progress_file.write_text(json.dumps({"status": "error", "error": err}), encoding="utf-8")
        except subprocess.TimeoutExpired:
            progress_file.write_text(json.dumps({"status": "error", "error": "Transcription timed out"}), encoding="utf-8")
        except Exception as exc:
            progress_file.write_text(json.dumps({"status": "error", "error": str(exc) or "Transcription failed"}), encoding="utf-8")
        finally:
            with _transcribe_lock:
                _transcribing.discard(pid)
            maybe_advance_to_style(pid)

    threading.Thread(target=run, daemon=True).start()


# ── Ideas (Supabase video_ideas table — shared topic backlog) ─────────────────
IDEAS_TABLE_FIELDS = {"channel_name", "video_title", "hook", "slug", "script", "video_status", "youtube_link"}


def supabase_config() -> dict | None:
    secrets_file = ROOT / "secrets.json"
    if not secrets_file.is_file():
        return None
    try:
        cfg = json.loads(secrets_file.read_text()).get("supabase")
    except Exception:
        return None
    if not cfg or not cfg.get("url") or not cfg.get("anon_key"):
        return None
    return cfg


def supabase_request(method: str, path: str, body=None):
    cfg = supabase_config()
    if not cfg:
        raise RuntimeError("Supabase not configured (secrets.json)")
    req = urllib.request.Request(
        f"{cfg['url']}/rest/v1/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "apikey": cfg["anon_key"],
            "Authorization": f"Bearer {cfg['anon_key']}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
            "User-Agent": "curl/7.88.1",  # Cloudflare blocks Python's default UA
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def list_ideas() -> list[dict]:
    return supabase_request("GET", "video_ideas?select=*&order=id.desc") or []


def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", "", title.lower())
    return re.sub(r" +", "-", s.strip())


def create_project_from_idea(idea: dict) -> str:
    """Mirror scripts/new_project.sh, then seed 01-script/Script.txt from the
    idea's script field. Returns the new project slug."""
    title = idea.get("video_title") or "Untitled"
    base_slug = slugify(title) or f"idea-{idea['id']}"
    slug = base_slug
    n = 2
    while (PROJECTS_DIR / slug).exists():
        slug = f"{base_slug}-{n}"
        n += 1

    proj_dir = PROJECTS_DIR / slug
    for sub in ("01-script", "02-audio", "03-transcript", "04-manifest",
                "05-images", "06-output", "07-upload", "tracker", "tracker/thumbs"):
        (proj_dir / sub).mkdir(parents=True, exist_ok=True)

    assets_link = proj_dir / "assets"
    if (ROOT / "assets").is_dir() and not assets_link.exists():
        try:
            assets_link.symlink_to(ROOT / "assets")
        except OSError:
            pass

    project = {
        "name": title,
        "queue_status": "upload",
        "style_approved": False,
        "image_style": "",
        "style_preset_id": "",
        "style_preset_label": "",
        "style_guide": "",
        "text_rules": "",
        "tone": "",
        "workers": 10,
    }
    (proj_dir / "project.json").write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")
    script = (idea.get("script") or "").strip()
    (proj_dir / "01-script" / "Script.txt").write_text(script + "\n" if script else "", encoding="utf-8")
    (proj_dir / "03-transcript" / "transcript.txt").write_text("", encoding="utf-8")
    return slug


# ── Archive ───────────────────────────────────────────────────────────────────
# Finished videos can be "archived" out of the repo into the user's Documents
# folder, kept for later upload. Never committed/pushed (it's outside the repo).
ARCHIVE_ROOT = Path.home() / "Documents" / "Bendover Productions"
DELETED_ROOT = ARCHIVE_ROOT / ".deleted"
_archive_running: set[str] = set()


def archive_dir(slug: str) -> Path:
    return ARCHIVE_ROOT / slug


def load_archive_meta(slug: str) -> dict | None:
    pf = archive_dir(slug) / "project.json"
    if not pf.is_file():
        return None
    try:
        return json.loads(pf.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_archive_meta(slug: str, meta: dict) -> None:
    pf = archive_dir(slug) / "project.json"
    pf.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def list_archived() -> list[dict]:
    if not ARCHIVE_ROOT.is_dir():
        return []
    items: list[dict] = []
    for d in sorted(ARCHIVE_ROOT.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        meta = load_archive_meta(d.name)
        if meta is None:
            continue
        video = d / "06-output" / "final.mp4"
        thumb = d / "07-upload" / "thumbnail.png"
        script = d / "01-script" / "Script.txt"
        items.append({
            "id": d.name,
            "title": meta.get("name") or meta.get("title") or d.name,
            "description": meta.get("description") or "",
            "youtube_channel": meta.get("youtube_channel"),
            "youtube_video_id": meta.get("youtube_video_id"),
            "thumbnail_variant": meta.get("thumbnail_variant"),
            "archived_at": meta.get("archived_at"),
            "video_ok": video.is_file() and video.stat().st_size > 0,
            "thumb_ok": thumb.is_file() and thumb.stat().st_size > 0,
            "script_ok": script.is_file() and script.stat().st_size > 0,
            "uploading": d.name in _archive_running,
            "upload_error": meta.get("upload_error"),
        })
    # Newest first.
    items.sort(key=lambda x: x.get("archived_at") or "", reverse=True)
    return items


# ── YouTube stats ─────────────────────────────────────────────────────────────

def _first_authorized_channel() -> str | None:
    for c in channels.list_all():
        if c.get("authorized"):
            return c["slug"]
    return None


def _yt_access_token(channel: str | None = None) -> str:
    """Return a valid access token for a channel, refreshing if expired. Token
    material lives in secrets.json (youtube.channels.<slug>.token)."""
    import urllib.request, urllib.parse, urllib.error

    slug = channel or _first_authorized_channel()
    if not slug:
        raise FileNotFoundError("No authorized YouTube channel")
    d = channels.get_token(slug)
    if not d:
        raise FileNotFoundError(f"Channel '{slug}' is not authorized yet")

    expiry = d.get("expiry", "")
    try:
        from datetime import datetime, timezone
        exp_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        still_valid = exp_dt > datetime.now(timezone.utc)
    except Exception:
        still_valid = False

    if still_valid and d.get("token"):
        return d["token"]

    # Refresh
    refresh_token = d.get("refresh_token")
    client_id = d.get("client_id")
    client_secret = d.get("client_secret")
    if not (refresh_token and client_id and client_secret):
        channels.write_meta(slug, {"token_invalid": True})
        raise RuntimeError("Cannot refresh token — missing refresh_token/client credentials")

    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            new_tokens = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        # invalid_grant → refresh token expired/revoked; needs a fresh login.
        if exc.code in (400, 401):
            channels.write_meta(slug, {"token_invalid": True})
            raise RuntimeError("Login expired — please log in again") from exc
        raise

    d["token"] = new_tokens["access_token"]
    from datetime import datetime, timezone, timedelta
    d["expiry"] = (datetime.now(timezone.utc) + timedelta(seconds=new_tokens.get("expires_in", 3600))).isoformat()
    channels.set_token(slug, d)
    if channels.read_meta(slug).get("token_invalid"):
        channels.write_meta(slug, {"token_invalid": False})
    return d["token"]


def fetch_channel_details(slug: str) -> dict:
    """Re-pull a channel's title/stats/avatar via its stored token and save to meta."""
    import urllib.request
    from datetime import datetime, timezone

    access_token = _yt_access_token(slug)
    url = ("https://www.googleapis.com/youtube/v3/channels"
           "?part=snippet,statistics&mine=true")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    items = data.get("items") or []
    if not items:
        raise ValueError("No channel on this account")
    it = items[0]
    sn = it.get("snippet", {})
    st = it.get("statistics", {})
    thumbs = sn.get("thumbnails", {})
    thumb = (thumbs.get("default") or thumbs.get("medium") or {}).get("url", "")
    title = sn.get("title", "")
    channels.write_meta(slug, {
        "title": title,
        "name": title,
        "channel_id": it.get("id", ""),
        "custom_url": sn.get("customUrl", ""),
        "description": sn.get("description", ""),
        "thumbnail": thumb,
        "published_at": sn.get("publishedAt", ""),
        "subscribers": None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount", 0)),
        "hidden_subscribers": bool(st.get("hiddenSubscriberCount")),
        "video_count": int(st.get("videoCount", 0)),
        "view_count": int(st.get("viewCount", 0)),
        "stats_updated": datetime.now(timezone.utc).isoformat(),
        "pending": False,
    })
    channels.dedupe(it.get("id", ""))
    return channels.info(slug)


def fetch_youtube_stats(video_id: str, channel: str | None = None) -> dict:
    """Fetch view/like/comment counts via YouTube Data API using existing OAuth token."""
    import urllib.request

    access_token = _yt_access_token(channel)
    url = f"https://www.googleapis.com/youtube/v3/videos?part=statistics,snippet&id={video_id}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())

    items = data.get("items") or []
    if not items:
        raise ValueError("Video not found or not accessible")

    stats = items[0].get("statistics", {})
    snippet = items[0].get("snippet", {})
    return {
        "video_id": video_id,
        "title": snippet.get("title", ""),
        "views": int(stats.get("viewCount", 0)),
        "likes": int(stats.get("likeCount", 0)),
        "comments": int(stats.get("commentCount", 0)),
        "published_at": snippet.get("publishedAt", ""),
    }


# ── Queue helpers ─────────────────────────────────────────────────────────────

def load_queue() -> list[dict]:
    if not QUEUE_FILE.is_file():
        return []
    try:
        return json.loads(QUEUE_FILE.read_text())
    except Exception:
        return []


def save_queue(q: list[dict]) -> None:
    QUEUE_FILE.write_text(json.dumps(q, indent=2) + "\n")


def ensure_queue_runner() -> None:
    if QUEUE_PID_FILE.is_file():
        try:
            pid = int(QUEUE_PID_FILE.read_text().strip())
            os.kill(pid, 0)
            return
        except (ValueError, ProcessLookupError, OSError):
            QUEUE_PID_FILE.unlink(missing_ok=True)
    log_path = TRACKER / "queue.log"
    with log_path.open("a") as lf:
        subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "scripts" / "queue_runner.py")],
            stdout=lf, stderr=subprocess.STDOUT,
            start_new_session=True, cwd=ROOT,
        )


# ── Project helpers ───────────────────────────────────────────────────────────

def load_project(pid: str) -> dict | None:
    pf = PROJECTS_DIR / pid / "project.json"
    if not pf.is_file():
        return None
    try:
        return json.loads(pf.read_text())
    except Exception:
        return None


def save_project(pid: str, data: dict) -> None:
    pf = PROJECTS_DIR / pid / "project.json"
    pf.write_text(json.dumps(data, indent=2) + "\n")


def resolve_status(p: dict, slug: str = "") -> str:
    status = p.get("queue_status") or "upload"
    if status == "script":  # legacy value
        status = "upload"
    if status == "thumbnails" and p.get("youtube_video_id"):
        status = "done"
    # "failed" that was actually a user-initiated stop
    if status == "failed" and slug:
        if (PROJECTS_DIR / slug / "tracker" / "stopped.flag").is_file():
            status = "paused"
    return status


def project_summary(slug: str) -> dict:
    p = load_project(slug) or {}
    return {
        "id": slug,
        "title": p.get("name") or p.get("title") or slug,
        "status": resolve_status(p, slug),
        "youtube_video_id": p.get("youtube_video_id"),
        "youtube_channel": p.get("youtube_channel"),
    }


def list_projects() -> list[dict]:
    if not PROJECTS_DIR.is_dir():
        return []
    out = []
    for d in sorted(PROJECTS_DIR.iterdir()):
        if d.is_dir() and not d.name.startswith(".") and (d / "project.json").is_file():
            out.append(project_summary(d.name))
    return out


def get_style_presets() -> list[dict]:
    try:
        from lib.style_presets import load_style_presets
        return load_style_presets()
    except Exception:
        return [{"id": "default", "label": "Classic stick figure explainer",
                 "image_style": "", "preview": None, "has_preview": False}]


# ── Multipart upload parser ───────────────────────────────────────────────────

def parse_multipart(content_type: str, body: bytes) -> dict[str, dict]:
    boundary = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part[9:].strip('"')
    if not boundary:
        return {}
    sep = ("--" + boundary).encode()
    result: dict[str, dict] = {}
    for raw in body.split(sep)[1:]:
        if raw in (b"", b"--\r\n", b"--"):
            continue
        raw = raw.lstrip(b"\r\n")
        last_boundary = b"\r\n"
        if raw.endswith(b"\r\n"):
            raw = raw[:-2]
        hdr_end = raw.find(b"\r\n\r\n")
        if hdr_end == -1:
            continue
        hdr = raw[:hdr_end].decode("utf-8", errors="replace")
        data = raw[hdr_end + 4:]
        name = filename = None
        for line in hdr.split("\r\n"):
            if "Content-Disposition" in line:
                for token in line.split(";"):
                    token = token.strip()
                    if token.startswith("name="):
                        name = token[5:].strip('"')
                    elif token.startswith("filename="):
                        filename = token[9:].strip('"')
        if name:
            result[name] = {"filename": filename, "content": data}
    return result


# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass  # silent

    def send_json(self, data: dict | list, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, mime: str, no_cache: bool = False) -> None:
        if not path.is_file():
            self.send_response(404)
            self.end_headers()
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        if no_cache:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(data)

    def serve_range(self, file_path: Path, mime: str) -> None:
        """Serve a file with HTTP range support (needed for browser video/audio seeking)."""
        if not file_path.is_file():
            self.err("Not found", 404)
            return
        file_size = file_path.stat().st_size
        range_hdr = self.headers.get("Range", "")
        if range_hdr.startswith("bytes="):
            spec = range_hdr[6:]
            s_str, _, e_str = spec.partition("-")
            start = int(s_str) if s_str else 0
            end = int(e_str) if e_str else file_size - 1
            end = min(end, file_size - 1)
            length = end - start + 1
            with file_path.open("rb") as f:
                f.seek(start)
                chunk = f.read(length)
            self.send_response(206)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(length))
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(chunk)
        else:
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(file_size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with file_path.open("rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

    def err(self, msg: str, status: int = 400) -> None:
        self.send_json({"ok": False, "error": msg}, status)

    def read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if path == "/":
            self.send_file(INDEX_FILE, "text/html; charset=utf-8", no_cache=True)
            return

        if path == "/api/projects":
            self.send_json(list_projects())
            return

        if path == "/api/archive":
            self.send_json(list_archived())
            return

        if path == "/api/ideas":
            try:
                self.send_json(list_ideas())
            except Exception as exc:
                self.send_json({"error": str(exc)}, 500)
            return

        if path == "/api/styles":
            self.send_json(get_style_presets())
            return

        if path == "/api/channels":
            items = channels.list_all()
            with _yt_lock:
                for c in items:
                    c["authorizing"] = f"__auth__{c['slug']}" in _yt_running
            self.send_json(items)
            return

        if path == "/api/credits":
            force = "force" in qs
            try:
                if force:
                    # Run a minimal codex exec to write a fresh session file with current rate limits
                    subprocess.Popen(
                        ["codex", "exec", "hi"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    time.sleep(2.5)  # wait for session file to appear
                if _HAS_CREDITS:
                    data = read_usage_payload(force=force, max_cache_age=30)
                else:
                    usage_file = TRACKER / "usage.json"
                    if not usage_file.is_file():
                        self.send_json({"error": "No usage data — run Codex to populate"}, 404)
                        return
                    data = json.loads(usage_file.read_text())
                # Flag windows whose reset time has already passed
                now = int(time.time())
                for key in ("five_hour", "weekly"):
                    w = data.get(key)
                    if isinstance(w, dict):
                        resets_at = int(w.get("resets_at") or 0)
                        w["window_reset"] = bool(resets_at and now >= resets_at)
                self.send_json(data)
            except Exception as exc:
                self.send_json({"error": str(exc)}, 500)
            return

        if path.startswith("/api/project/"):
            rest = path[len("/api/project/"):].strip("/").split("/")
            pid = rest[0] if rest else ""
            action = rest[1] if len(rest) > 1 else ""

            p = load_project(pid)
            if p is None:
                self.err("Project not found", 404)
                return

            if action == "":
                audio_dir = PROJECTS_DIR / pid / "02-audio"
                has_audio = audio_dir.is_dir() and any(
                    f.suffix.lower() in (".mp3", ".wav", ".m4a")
                    for f in audio_dir.iterdir()
                    if f.is_file() and f.name != ".gitkeep"
                )
                has_transcript = has_transcript_file(pid)
                transcribe = load_transcribe_progress(pid)
                if transcribe and pid not in _transcribing and transcribe.get("status") == "running":
                    # Stale progress file from a crashed/killed run — don't show a spinner forever.
                    transcribe = {"status": "error", "error": "Transcription stopped unexpectedly"}

                prog_file = PROJECTS_DIR / pid / "04-manifest" / "image_regen_progress.json"
                progress = None
                if prog_file.is_file():
                    try:
                        progress = json.loads(prog_file.read_text())
                    except Exception:
                        pass

                thumbs_dir = PROJECTS_DIR / pid / "tracker" / "thumbs"
                thumbs = {f"v{i}": (thumbs_dir / f"thumbnail_v{i}.png").is_file() for i in (1, 2, 3)}

                yt_uploading = pid in _yt_running

                final_video = PROJECTS_DIR / pid / "06-output" / "final.mp4"
                video_ok = final_video.is_file() and final_video.stat().st_size > 0

                self.send_json({
                    **p, "id": pid,
                    "queue_status": resolve_status(p, pid),
                    "audio_ok": has_audio,
                    "transcript_ok": has_transcript,
                    "transcribing": pid in _transcribing,
                    "transcribe": transcribe,
                    "progress": progress,
                    "thumbs": thumbs,
                    "yt_uploading": yt_uploading,
                    "video_ok": video_ok,
                })
                return

            if action == "log":
                lines = int(qs.get("lines", ["80"])[0])
                log_path = PROJECTS_DIR / pid / "tracker" / "overnight.log"
                if not log_path.is_file():
                    log_path = TRACKER / "queue.log"
                text = ""
                if log_path.is_file():
                    all_lines = log_path.read_text(errors="replace").splitlines()
                    text = "\n".join(all_lines[-lines:])
                self.send_json({"log": text})
                return

            if action == "thumbs":
                thumbs_dir = PROJECTS_DIR / pid / "tracker" / "thumbs"
                self.send_json({f"v{i}": (thumbs_dir / f"thumbnail_v{i}.png").is_file() for i in (1, 2, 3)})
                return

            if action == "youtube-stats":
                video_id = p.get("youtube_video_id")
                if not video_id:
                    self.send_json({"error": "No YouTube video ID"}, 404)
                    return
                try:
                    stats = fetch_youtube_stats(video_id, p.get("youtube_channel"))
                    self.send_json(stats)
                except Exception as exc:
                    self.send_json({"error": str(exc)}, 500)
                return

            if action == "frames":
                import csv as _csv
                manifest = PROJECTS_DIR / pid / "04-manifest" / "image_regen_manifest.csv"
                images_dir = PROJECTS_DIR / pid / "05-images"
                if not manifest.is_file():
                    self.send_json({"frames": []})
                    return
                frames = []
                with open(manifest, newline="", encoding="utf-8") as f:
                    for row in _csv.DictReader(f):
                        ts = row.get("timestamp", "0:00")
                        parts_ts = ts.split(":")
                        ts_sec = int(parts_ts[0]) * 60 + int(parts_ts[1]) if len(parts_ts) == 2 else 0
                        fname = row.get("filename", "")
                        frames.append({
                            "filename": fname,
                            "timestamp": ts,
                            "timestamp_seconds": ts_sec,
                            "transcript": row.get("transcript", ""),
                            "duration": int(row.get("duration", 2)),
                            "status": row.get("status", "pending"),
                            "exists": (images_dir / fname).is_file() if fname else False,
                        })
                self.send_json({"frames": frames, "total": len(frames)})
                return

        # Static assets
        if path.startswith("/thumbs/"):
            parts = path[len("/thumbs/"):].split("/", 1)
            if len(parts) == 2:
                pid, fname = parts
                self.send_file(PROJECTS_DIR / pid / "tracker" / "thumbs" / fname, "image/png")
                return

        if path.startswith("/assets/style-samples/"):
            fname = path[len("/assets/style-samples/"):]
            self.send_file(ROOT / "assets" / "style-samples" / fname, "image/png")
            return

        # Serve generated frame images
        if path.startswith("/images/"):
            parts = path[len("/images/"):].split("/", 1)
            if len(parts) == 2:
                slug, fname = parts
                img = PROJECTS_DIR / slug / "05-images" / fname
                if img.is_file() and img.suffix.lower() in (".png", ".jpg", ".jpeg"):
                    self.send_file(img, "image/png")
                    return
            self.err("Not found", 404)
            return

        # Serve the rendered final.mp4 with range support (needed for browser seeking)
        if path.startswith("/video/"):
            slug = path[len("/video/"):].strip("/")
            self.serve_range(PROJECTS_DIR / slug / "06-output" / "final.mp4", "video/mp4")
            return

        # Serve an ARCHIVED video / thumbnail (from ~/Documents/Bendover Productions)
        if path.startswith("/video-archive/"):
            slug = path[len("/video-archive/"):].strip("/")
            self.serve_range(archive_dir(slug) / "06-output" / "final.mp4", "video/mp4")
            return
        if path.startswith("/thumb-archive/"):
            slug = path[len("/thumb-archive/"):].strip("/")
            self.send_file(archive_dir(slug) / "07-upload" / "thumbnail.png", "image/png")
            return
        if path.startswith("/script-archive/"):
            slug = path[len("/script-archive/"):].strip("/")
            self.send_file(archive_dir(slug) / "01-script" / "Script.txt", "text/plain; charset=utf-8")
            return

        # Serve project audio with range request support (needed for browser seeking)
        if path.startswith("/audio/"):
            slug = path[len("/audio/"):].strip("/")
            audio_dir = PROJECTS_DIR / slug / "02-audio"
            audio_file = None
            if audio_dir.is_dir():
                for f in audio_dir.iterdir():
                    if f.suffix.lower() in (".mp3", ".wav", ".m4a") and f.name != ".gitkeep" and f.is_file():
                        audio_file = f
                        break
            if audio_file is None:
                self.err("No audio", 404)
                return
            mime = {"mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4"}.get(
                audio_file.suffix.lower().lstrip("."), "audio/mpeg"
            )
            file_size = audio_file.stat().st_size
            range_hdr = self.headers.get("Range", "")
            if range_hdr.startswith("bytes="):
                spec = range_hdr[6:]
                s_str, _, e_str = spec.partition("-")
                start = int(s_str) if s_str else 0
                end = int(e_str) if e_str else file_size - 1
                end = min(end, file_size - 1)
                length = end - start + 1
                with audio_file.open("rb") as af:
                    af.seek(start)
                    chunk = af.read(length)
                self.send_response(206)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(length))
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                self.wfile.write(chunk)
            else:
                data = audio_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(file_size))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                self.wfile.write(data)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        body = self.read_body()
        ct = self.headers.get("Content-Type", "")

        # ── Channel management (not project-scoped) ───────────────────────────
        if path == "/api/channels/create":
            # Name is optional — when omitted, an unnamed pending channel is made
            # and its real name is fetched from YouTube after login.
            try:
                data = json.loads(body or b"{}")
            except Exception:
                data = {}
            name = str(data.get("name", "")).strip()
            slug = channels.create(name) if name else channels.create_pending()
            self.send_json({"ok": True, "slug": slug, "channel": channels.info(slug)})
            return

        if path == "/api/channels/check":
            # Validate each authorized channel's login (forces a refresh attempt);
            # marks token_invalid on failure so the UI can show "log in again".
            for c in channels.list_all():
                if c.get("authorized"):
                    try:
                        _yt_access_token(c["slug"])
                    except Exception:
                        pass
            self.send_json({"ok": True, "channels": channels.list_all()})
            return

        # ── Ideas (Supabase video_ideas table) ─────────────────────────────────
        if path == "/api/ideas":
            try:
                data = json.loads(body) if body else {}
            except Exception:
                data = {}
            title = str(data.get("video_title") or "").strip()
            if not title:
                self.err("video_title is required")
                return
            row = {k: data.get(k) for k in IDEAS_TABLE_FIELDS if k in data}
            row["video_title"] = title
            row.setdefault("video_status", "idea")
            try:
                result = supabase_request("POST", "video_ideas", [row])
                self.send_json({"ok": True, "idea": (result or [None])[0]})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 500)
            return

        if path.startswith("/api/ideas/"):
            rest = path[len("/api/ideas/"):].strip("/").split("/")
            idea_id = rest[0] if rest else ""
            iaction = rest[1] if len(rest) > 1 else ""
            if not idea_id.isdigit():
                self.err("Invalid idea id", 404)
                return

            if iaction == "delete":
                try:
                    supabase_request("DELETE", f"video_ideas?id=eq.{idea_id}")
                    self.send_json({"ok": True})
                except Exception as exc:
                    self.send_json({"ok": False, "error": str(exc)}, 500)
                return

            if iaction == "start":
                try:
                    rows = supabase_request("GET", f"video_ideas?id=eq.{idea_id}&select=*")
                    idea = (rows or [None])[0]
                    if not idea:
                        self.send_json({"ok": False, "error": "Idea not found"}, 404)
                        return
                    if idea.get("slug"):
                        self.send_json({"ok": True, "slug": idea["slug"]})
                        return
                    if not (idea.get("script") or "").strip():
                        self.send_json({"ok": False, "error": "Write a script before starting"})
                        return
                    slug = create_project_from_idea(idea)
                    supabase_request("PATCH", f"video_ideas?id=eq.{idea_id}",
                                      {"slug": slug, "video_status": "writing"})
                    self.send_json({"ok": True, "slug": slug})
                except Exception as exc:
                    self.send_json({"ok": False, "error": str(exc)}, 500)
                return

            if iaction == "":
                try:
                    data = json.loads(body) if body else {}
                except Exception:
                    data = {}
                patch = {k: v for k, v in data.items() if k in IDEAS_TABLE_FIELDS}
                if not patch:
                    self.err("No valid fields to update")
                    return
                try:
                    result = supabase_request("PATCH", f"video_ideas?id=eq.{idea_id}", patch)
                    self.send_json({"ok": True, "idea": (result or [None])[0]})
                except Exception as exc:
                    self.send_json({"ok": False, "error": str(exc)}, 500)
                return

            self.err("Unknown idea action", 404)
            return

        if path.startswith("/api/channels/"):
            rest = path[len("/api/channels/"):].strip("/").split("/")
            slug = rest[0] if rest else ""
            caction = rest[1] if len(rest) > 1 else ""
            if not slug or not channels.exists(slug):
                self.err("Channel not found", 404)
                return

            if caction == "authorize":
                with _yt_lock:
                    key = f"__auth__{slug}"
                    if key in _yt_running:
                        self.send_json({"ok": False, "error": "Authorization already in progress"})
                        return
                    if not channels.has_app():
                        self.send_json({"ok": False, "error": "No Google OAuth app configured in secrets.json (youtube.app)"})
                        return
                    _yt_running.add(key)

                def do_auth() -> None:
                    try:
                        script = ROOT / "scripts" / "05_publish" / "upload_to_youtube.py"
                        subprocess.run(
                            [sys.executable, str(script), "--channel", slug, "--auth-only"],
                            cwd=ROOT, env={**os.environ}, timeout=300,
                        )
                    except Exception:
                        pass
                    finally:
                        with _yt_lock:
                            _yt_running.discard(f"__auth__{slug}")

                threading.Thread(target=do_auth, daemon=True).start()
                self.send_json({"ok": True, "message": "Browser login opened — poll /api/channels for authorized"})
                return

            if caction == "refresh":
                try:
                    info = fetch_channel_details(slug)
                    self.send_json({"ok": True, "channel": info})
                except Exception as exc:
                    self.send_json({"ok": False, "error": str(exc)}, 200)
                return

            if caction == "delete":
                channels.delete(slug)
                self.send_json({"ok": True})
                return

            self.err("Unknown channel action", 404)
            return

        # ── Archive actions (operate on ~/Documents, not a live project) ──────
        if path.startswith("/api/archive/"):
            arest = path[len("/api/archive/"):].strip("/").split("/")
            aslug = arest[0] if arest else ""
            aaction = arest[1] if len(arest) > 1 else ""
            meta = load_archive_meta(aslug)
            if not aslug or meta is None:
                self.err("Archived project not found", 404)
                return

            if aaction == "delete":
                src = archive_dir(aslug)
                if src.is_dir():
                    DELETED_ROOT.mkdir(parents=True, exist_ok=True)
                    stamp = time.strftime("%Y%m%dT%H%M%S")
                    dest = DELETED_ROOT / f"{aslug}__{stamp}"
                    shutil.move(str(src), str(dest))
                self.send_json({"ok": True})
                return

            if aaction == "upload":
                try:
                    data = json.loads(body) if body else {}
                except Exception:
                    data = {}
                channel = str(data.get("channel") or meta.get("youtube_channel") or "").strip()
                if not channel:
                    self.send_json({"ok": False, "error": "Select a channel to upload to"})
                    return
                if not channels.exists(channel):
                    self.send_json({"ok": False, "error": f"Unknown channel '{channel}'"})
                    return
                if not channels.has_token(channel):
                    self.send_json({"ok": False, "error": f"Channel '{channel}' is not authorized yet"})
                    return
                meta["youtube_channel"] = channel
                meta.pop("upload_error", None)
                save_archive_meta(aslug, meta)

                with _yt_lock:
                    if aslug in _archive_running:
                        self.send_json({"ok": False, "error": "Upload already in progress"})
                        return
                    _archive_running.add(aslug)

                adir = str(archive_dir(aslug))

                def do_archive_upload() -> None:
                    error: str | None = None
                    try:
                        env = {**os.environ, "PIPELINE_ROOT": adir}
                        upload_script = ROOT / "scripts" / "05_publish" / "upload_to_youtube.py"
                        result = subprocess.run(
                            [sys.executable, str(upload_script), "--channel", channel],
                            cwd=ROOT, env=env, timeout=600,
                            capture_output=True, text=True,
                        )
                        if result.returncode != 0:
                            lines = [
                                ln.strip() for ln in (result.stderr or result.stdout or "").splitlines()
                                if ln.strip()
                            ]
                            error = lines[-1] if lines else f"Upload failed (exit code {result.returncode})"
                    except subprocess.TimeoutExpired:
                        error = "Upload timed out after 10 minutes"
                    except Exception as exc:
                        error = str(exc) or "Upload failed"
                    finally:
                        with _yt_lock:
                            _archive_running.discard(aslug)
                        m = load_archive_meta(aslug) or meta
                        if error:
                            m["upload_error"] = error
                        else:
                            m.pop("upload_error", None)
                        save_archive_meta(aslug, m)

                threading.Thread(target=do_archive_upload, daemon=True).start()
                self.send_json({"ok": True, "message": "Upload started — poll /api/archive for youtube_video_id"})
                return

            self.err("Unknown archive action", 404)
            return

        if not path.startswith("/api/project/"):
            self.err("Not found", 404)
            return

        rest = path[len("/api/project/"):].strip("/").split("/")
        pid = rest[0] if rest else ""
        action = rest[1] if len(rest) > 1 else ""

        if not pid or load_project(pid) is None:
            self.err("Project not found", 404)
            return

        # ── Upload audio ──────────────────────────────────────────────────────
        if action == "upload-audio":
            fields = parse_multipart(ct, body)
            f = fields.get("file")
            if not f or not f.get("content"):
                self.err("No file provided")
                return
            dest_dir = PROJECTS_DIR / pid / "02-audio"
            dest_dir.mkdir(parents=True, exist_ok=True)
            for old in dest_dir.iterdir():
                if old.is_file() and old.suffix.lower() in (".mp3", ".wav", ".m4a"):
                    old.unlink()
            fname = f.get("filename") or "narration.mp3"
            (dest_dir / fname).write_bytes(f["content"])
            start_transcription(pid)
            self.send_json({"ok": True, "filename": fname})
            return

        # ── Upload transcript (manual override — auto-transcription is the
        # default path now; this stays available for edge cases) ─────────────
        if action == "upload-transcript":
            fields = parse_multipart(ct, body)
            f = fields.get("file")
            if not f or not f.get("content"):
                self.err("No file provided")
                return
            dest_dir = PROJECTS_DIR / pid / "03-transcript"
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / "transcript.txt").write_bytes(f["content"])
            maybe_advance_to_style(pid)
            self.send_json({"ok": True})
            return

        # ── Retry transcription ─────────────────────────────────────────────
        if action == "retranscribe":
            if not has_audio_file(pid):
                self.send_json({"ok": False, "error": "No audio uploaded yet"})
                return
            start_transcription(pid)
            self.send_json({"ok": True})
            return

        # ── Set style ─────────────────────────────────────────────────────────
        if action == "set-style":
            try:
                data = json.loads(body)
            except Exception:
                self.err("Bad JSON")
                return
            p = load_project(pid)
            preset_id = data.get("preset_id")
            if preset_id:
                try:
                    preset = next((x for x in get_style_presets() if x["id"] == preset_id), None)
                    if preset:
                        p["style_preset_id"] = preset["id"]
                        p["style_preset_label"] = preset.get("label", "")
                        p["image_style"] = preset.get("image_style", "")
                        if preset.get("scene"):
                            p["style_guide"] = preset["scene"]
                except Exception:
                    pass
            if data.get("custom_style"):
                p["image_style"] = data["custom_style"]
                p["style_preset_id"] = "custom"
                p["style_preset_label"] = "Custom"
            if data.get("style_guide"):
                p["style_guide"] = data["style_guide"]
            if data.get("tone"):
                p["tone"] = data["tone"]
            if data.get("text_rules"):
                p["text_rules"] = data["text_rules"]
            p["queue_status"] = "style"
            save_project(pid, p)
            self.send_json({"ok": True})
            return

        # ── Validate & queue ──────────────────────────────────────────────────
        if action == "queue":
            p = load_project(pid)
            if not p.get("image_style"):
                self.send_json({"ok": False, "preflight": "No style selected. Go back to the Style step."})
                return

            proj_dir = str(PROJECTS_DIR / pid)
            env = {**os.environ, "PIPELINE_ROOT": proj_dir}
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "preflight.py")],
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
            )
            preflight_out = (result.stdout + result.stderr).strip()

            if result.returncode != 0:
                self.send_json({"ok": False, "preflight": preflight_out or "Preflight failed."})
                return

            # Mark style approved and queue the project
            p["style_approved"] = True
            p["queue_status"] = "queued"
            save_project(pid, p)

            # Clear stopped flag if this is a restart after pausing
            (PROJECTS_DIR / pid / "tracker" / "stopped.flag").unlink(missing_ok=True)

            q = load_queue()
            title = p.get("name") or p.get("title") or pid
            existing = next((x for x in q if x["id"] == pid), None)
            if existing:
                existing["status"] = "queued"
                existing["title"] = title
            else:
                q.append({"id": pid, "title": title, "status": "queued"})
            save_queue(q)
            ensure_queue_runner()
            self.send_json({"ok": True, "preflight": preflight_out})
            return

        # ── Stop generation ──────────────────────────────────────────────────
        if action == "stop":
            proj_path = str(PROJECTS_DIR / pid)

            # Write stopped flag FIRST so generate_images.py self-terminates on next loop tick
            (PROJECTS_DIR / pid / "tracker" / "stopped.flag").touch()

            # Kill overnight runner
            night_pid_file = TRACKER / "overnight.pid"
            if night_pid_file.is_file():
                try:
                    night_pid = int(night_pid_file.read_text().strip())
                    os.kill(night_pid, 15)  # SIGTERM
                    time.sleep(0.3)
                    try:
                        os.kill(night_pid, 9)
                    except ProcessLookupError:
                        pass
                except (ValueError, ProcessLookupError, OSError):
                    pass
                night_pid_file.unlink(missing_ok=True)

            # Kill all codex worker processes that were spawned for this project.
            # They are identified by having the project path in their command line.
            try:
                subprocess.run(
                    ["pkill", "-9", "-f", proj_path],
                    capture_output=True,
                )
            except Exception:
                pass

            p = load_project(pid)
            p["queue_status"] = "paused"
            save_project(pid, p)

            q = load_queue()
            for entry in q:
                if entry["id"] == pid:
                    entry["status"] = "paused"
            save_queue(q)
            self.send_json({"ok": True})
            return

        # ── Pick thumbnail ────────────────────────────────────────────────────
        if action == "pick-thumb":
            try:
                data = json.loads(body)
            except Exception:
                self.err("Bad JSON")
                return
            variant = str(data.get("variant", "v1")).lstrip("v") or "1"
            src = PROJECTS_DIR / pid / "tracker" / "thumbs" / f"thumbnail_v{variant}.png"
            if not src.is_file():
                self.err(f"Thumbnail v{variant} not found")
                return
            # Copy to shared upload dir so upload_to_youtube.py can find it
            shared = ROOT / "07-upload"
            shared.mkdir(exist_ok=True)
            shutil.copy2(src, shared / "thumbnail.png")
            proj_upload = PROJECTS_DIR / pid / "07-upload"
            if proj_upload.is_dir() and not proj_upload.is_symlink():
                shutil.copy2(src, proj_upload / "thumbnail.png")
            p = load_project(pid)
            p["selected_thumbnail_variant"] = int(variant)
            save_project(pid, p)
            self.send_json({"ok": True})
            return

        # ── Set target channel (persist the choice on the project) ────────────
        if action == "set-channel":
            try:
                data = json.loads(body) if body else {}
            except Exception:
                data = {}
            channel = str(data.get("channel") or "").strip()
            if channel and not channels.exists(channel):
                self.send_json({"ok": False, "error": f"Unknown channel '{channel}'"})
                return
            proj = load_project(pid)
            proj["youtube_channel"] = channel
            save_project(pid, proj)
            self.send_json({"ok": True})
            return

        # ── Archive for later (move deliverables to ~/Documents) ──────────────
        if action == "archive":
            proj = load_project(pid)
            src_video = PROJECTS_DIR / pid / "06-output" / "final.mp4"
            if not (src_video.is_file() and src_video.stat().st_size > 0):
                self.send_json({"ok": False, "error": "No rendered video to archive yet"})
                return

            # Chosen thumbnail: the picked variant, else the first one that exists.
            thumbs_dir = PROJECTS_DIR / pid / "tracker" / "thumbs"
            variant = proj.get("selected_thumbnail_variant")
            src_thumb = None
            if variant and (thumbs_dir / f"thumbnail_v{variant}.png").is_file():
                src_thumb = thumbs_dir / f"thumbnail_v{variant}.png"
            else:
                for i in (1, 2, 3):
                    cand = thumbs_dir / f"thumbnail_v{i}.png"
                    if cand.is_file():
                        src_thumb = cand
                        variant = i
                        break

            dest = archive_dir(pid)
            (dest / "06-output").mkdir(parents=True, exist_ok=True)
            (dest / "07-upload").mkdir(parents=True, exist_ok=True)
            (dest / "01-script").mkdir(parents=True, exist_ok=True)

            # Move the video (frees project disk); copy the thumbnail + script.
            dest_video = dest / "06-output" / "final.mp4"
            dest_video.unlink(missing_ok=True)
            shutil.move(str(src_video), str(dest_video))
            if src_thumb:
                shutil.copy2(src_thumb, dest / "07-upload" / "thumbnail.png")
            src_script = PROJECTS_DIR / pid / "01-script" / "Script.txt"
            if src_script.is_file() and src_script.stat().st_size > 0:
                shutil.copy2(src_script, dest / "01-script" / "Script.txt")

            archived_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            meta = {
                "name": proj.get("name") or proj.get("title") or pid,
                "title": proj.get("name") or proj.get("title") or pid,
                "description": proj.get("description") or "",
                "tags": proj.get("tags") or [],
                "privacy": proj.get("privacy") or "public",
                "youtube_channel": proj.get("youtube_channel"),
                "youtube_video_id": proj.get("youtube_video_id"),
                "slug": pid,
                "thumbnail_variant": variant,
                "archived_at": archived_at,
            }
            save_archive_meta(pid, meta)

            proj["queue_status"] = "archived"
            proj["archived"] = True
            proj["archived_at"] = archived_at
            proj["archive_path"] = str(dest)
            save_project(pid, proj)
            self.send_json({"ok": True, "archive_path": str(dest)})
            return

        # ── YouTube upload ────────────────────────────────────────────────────
        if action == "youtube-upload":
            try:
                data = json.loads(body) if body else {}
            except Exception:
                data = {}
            proj = load_project(pid)
            channel = str(data.get("channel") or proj.get("youtube_channel") or "").strip()
            if not channel:
                self.send_json({"ok": False, "error": "Select a channel to upload to"})
                return
            if not channels.exists(channel):
                self.send_json({"ok": False, "error": f"Unknown channel '{channel}'"})
                return
            if not channels.has_token(channel):
                self.send_json({"ok": False, "error": f"Channel '{channel}' is not authorized yet"})
                return
            # Persist the chosen channel so stats/updates use the right token
            proj["youtube_channel"] = channel
            save_project(pid, proj)

            with _yt_lock:
                if pid in _yt_running:
                    self.send_json({"ok": False, "error": "Upload already in progress"})
                    return
                _yt_running.add(pid)

            proj_dir = str(PROJECTS_DIR / pid)

            def do_upload() -> None:
                try:
                    env = {**os.environ, "PIPELINE_ROOT": proj_dir}
                    upload_script = ROOT / "scripts" / "05_publish" / "upload_to_youtube.py"
                    subprocess.run(
                        [sys.executable, str(upload_script), "--channel", channel],
                        cwd=ROOT, env=env, timeout=600,
                    )
                except Exception:
                    pass
                finally:
                    with _yt_lock:
                        _yt_running.discard(pid)

            threading.Thread(target=do_upload, daemon=True).start()
            self.send_json({"ok": True, "message": "Upload started — poll project status for youtube_video_id"})
            return

        self.err("Unknown action", 404)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    PROJECTS_DIR.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    (TRACKER / "port.txt").write_text(str(PORT))
    print(f"Studio → http://127.0.0.1:{PORT}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
