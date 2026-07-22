#!/usr/bin/env python3
"""Bendover Productions Studio — local UI server. No DB, no auth, file-based state."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
                transcript = PROJECTS_DIR / pid / "03-transcript" / "transcript.txt"
                has_transcript = transcript.is_file() and transcript.stat().st_size > 50

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

                self.send_json({
                    **p, "id": pid,
                    "queue_status": resolve_status(p, pid),
                    "audio_ok": has_audio,
                    "transcript_ok": has_transcript,
                    "progress": progress,
                    "thumbs": thumbs,
                    "yt_uploading": yt_uploading,
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
            self._maybe_advance_to_style(pid)
            self.send_json({"ok": True, "filename": fname})
            return

        # ── Upload transcript ─────────────────────────────────────────────────
        if action == "upload-transcript":
            fields = parse_multipart(ct, body)
            f = fields.get("file")
            if not f or not f.get("content"):
                self.err("No file provided")
                return
            dest_dir = PROJECTS_DIR / pid / "03-transcript"
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / "transcript.txt").write_bytes(f["content"])
            self._maybe_advance_to_style(pid)
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

    def _maybe_advance_to_style(self, pid: str) -> None:
        p = load_project(pid)
        if not p:
            return
        audio_dir = PROJECTS_DIR / pid / "02-audio"
        has_audio = audio_dir.is_dir() and any(
            f.suffix.lower() in (".mp3", ".wav", ".m4a")
            for f in audio_dir.iterdir()
            if f.is_file() and f.name != ".gitkeep"
        )
        transcript = PROJECTS_DIR / pid / "03-transcript" / "transcript.txt"
        has_transcript = transcript.is_file() and transcript.stat().st_size > 50
        if has_audio and has_transcript and p.get("queue_status", "upload") == "upload":
            p["queue_status"] = "style"
            save_project(pid, p)


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
