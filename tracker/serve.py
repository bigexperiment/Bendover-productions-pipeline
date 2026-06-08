#!/usr/bin/env python3
from __future__ import annotations

import argparse
import cgi
import csv
import json
import mimetypes
import re
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent.parent
TRACKER = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
from lib.folders import (  # noqa: E402
    COMBINED,
    COMBINED_NORMALIZED,
    DIR_AUDIO,
    DIR_IMAGES,
    DIR_MANIFEST,
    DIR_OUTPUT,
    DIR_SCRIPT,
    DIR_TRANSCRIPT,
    FINAL_MP4,
    MANIFEST_FILE,
    PREVIEW_MP4,
    PROGRESS_FILE,
    SCRIPT_FILE,
    TRANSCRIPT_FILE,
)
PROJECT_FILE = ROOT / "project.json"
INDEX_FILE = TRACKER / "index.html"
PORT = 47829
HOST = "0.0.0.0"

RUN_LOCK = threading.Lock()
ACTIVE_JOB: dict | None = None

STEP_LABELS = {
    "setup": "Setup",
    "audio": "Audio",
    "manifest": "Manifest",
    "images": "Images",
    "render": "Render",
    "publish": "Publish",
}

def load_json(path: Path, default: dict | list | None = None):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def save_project(data: dict) -> None:
    PROJECT_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_project() -> dict:
    return load_json(PROJECT_FILE, {
        "name": "my-video",
        "step": "setup",
        "title": "",
        "description": "",
        "privacy": "public",
        "workers": 5,
        "image_style": "minimal cartoon, stick figures, bold outlines, flat colors, 16:9",
        "style_approved": False,
        "youtube_video_id": None,
    })


def script_path() -> Path | None:
    if SCRIPT_FILE.is_file():
        return SCRIPT_FILE
    if TRANSCRIPT_FILE.is_file():
        return TRANSCRIPT_FILE
    return None


def audio_status() -> dict:
    parts = [ROOT / f"Part{i}.mp3" for i in range(1, 4)]
    singles = sorted(DIR_AUDIO.glob("*")) if DIR_AUDIO.is_dir() else []
    singles = [p for p in singles if p.suffix.lower() in {".mp3", ".wav", ".m4a"}]

    return {
        "combined": COMBINED.is_file(),
        "normalized": COMBINED_NORMALIZED.is_file(),
        "parts": [p.name for p in parts if p.is_file()],
        "singles": [p.name for p in singles],
        "ready": COMBINED.is_file() or bool(singles) or all(p.is_file() for p in parts),
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
    if audio["combined"] or audio["normalized"]:
        return "manifest"
    if script and (audio["ready"] or audio["singles"] or audio["parts"]):
        return "audio"
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


def paginate_frames(
    *,
    status_filter: str = "all",
    offset: int = 0,
    limit: int = 60,
) -> dict:
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
    usage = load_json(TRACKER / "usage.json", {})
    recent = load_json(TRACKER / "recent.json", {})
    script = script_path()
    audio = audio_status()
    manifest = MANIFEST_FILE.is_file()
    final_mp4 = FINAL_MP4.is_file()

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
        "recent": recent,
    }


def run_command(label: str, args: list[str]) -> None:
    global ACTIVE_JOB
    with RUN_LOCK:
        ACTIVE_JOB = {"label": label, "args": args, "status": "running"}

    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)

    with RUN_LOCK:
        ACTIVE_JOB = {
            "label": label,
            "status": "done" if proc.returncode == 0 else "error",
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-4000:],
        }


def start_job(label: str, args: list[str]) -> dict:
    if ACTIVE_JOB and ACTIVE_JOB.get("status") == "running":
        return {"ok": False, "error": f"Already running: {ACTIVE_JOB['label']}"}
    threading.Thread(target=run_command, args=(label, args), daemon=True).start()
    return {"ok": True, "started": label}


def handle_run(body: dict) -> dict:
    action = body.get("action")
    project = load_project()
    workers = int(body.get("workers") or project.get("workers") or 5)
    force = bool(body.get("force"))

    actions = {
        "combine_audio": (["python3", "scripts/01_audio/combine_mp3s.py"], "Combine audio"),
        "build_plan": (["python3", "scripts/02_manifest/build_plan.py"], "Build cut plan + manifest"),
        "refresh_manifest": (["python3", "scripts/02_manifest/build_plan.py", "refresh"], "Refresh manifest"),
        "generate_images": (
            ["python3", "scripts/03_images/generate_images.py", str(workers)] + (["--force"] if force else []),
            f"Generate images ({workers} workers)",
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

    rel = path.lstrip("/")
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
            self._send_json(build_status())
            return
        if path == "/api/project":
            self._send_json(load_project())
            return
        if path == "/api/frames":
            query = parse_qs(parsed.query)
            status_filter = (query.get("status") or ["all"])[0]
            offset = int((query.get("offset") or ["0"])[0])
            limit = min(int((query.get("limit") or ["80"])[0]), 200)
            self._send_json(paginate_frames(status_filter=status_filter, offset=offset, limit=limit))
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
            self._send_json({"ok": True, "project": current})
            return

        if path == "/api/run":
            result = handle_run(self._read_json())
            self._send_json(result, 200 if result.get("ok") else 400)
            return

        if path == "/api/upload":
            self._handle_upload()
            return

        self.send_error(404)

    def _handle_upload(self) -> None:
        env = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": self.headers.get("Content-Type", ""),
            "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
        }
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ=env)

        kind = form.getvalue("kind", "script")
        item = form["file"] if "file" in form else None
        if item is None or not item.filename:
            self._send_json({"ok": False, "error": "No file"}, 400)
            return

        filename = Path(item.filename).name
        if kind == "script":
            DIR_SCRIPT.mkdir(exist_ok=True)
            SCRIPT_FILE.write_bytes(item.file.read())
            self._send_json({"ok": True, "path": f"01-script/{SCRIPT_FILE.name}"})
            return

        if kind == "audio":
            DIR_AUDIO.mkdir(exist_ok=True)
            dest = DIR_AUDIO / filename
            dest.write_bytes(item.file.read())
            start_job("Combine audio", ["python3", "scripts/01_audio/combine_mp3s.py"])
            self._send_json({"ok": True, "path": f"02-audio/{filename}", "combining": True})
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
