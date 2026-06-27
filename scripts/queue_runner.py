#!/usr/bin/env python3
"""Multi-project pipeline queue — reads tracker/queue.json, runs queued projects one at a time.

Project lifecycle:
  script → upload → style → queued → running → thumbnails → done

Start:  bash scripts/start_queue.sh
Stop:   bash scripts/stop_queue.sh
Log:    tail -f tracker/queue.log
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT   = Path(__file__).resolve().parents[1]
TRACKER     = REPO_ROOT / "tracker"
PROJECTS    = REPO_ROOT / "projects"
QUEUE_FILE  = TRACKER / "queue.json"
LOG_FILE    = TRACKER / "queue.log"
PID_FILE    = TRACKER / "queue.pid"
OVERNIGHT   = REPO_ROOT / "scripts" / "overnight_runner.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib.notify import send_ntfy  # noqa: E402


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_queue() -> list[dict]:
    if not QUEUE_FILE.is_file():
        return []
    return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))


def save_queue(q: list[dict]) -> None:
    QUEUE_FILE.write_text(json.dumps(q, indent=2) + "\n", encoding="utf-8")


def set_status(project_id: str, status: str, extra: dict | None = None) -> None:
    q = load_queue()
    for p in q:
        if p["id"] == project_id:
            p["status"] = status
            if extra:
                p.update(extra)
            break
    save_queue(q)
    # Mirror into project.json
    pf = PROJECTS / project_id / "project.json"
    if pf.is_file():
        data = json.loads(pf.read_text(encoding="utf-8"))
        data["queue_status"] = status
        pf.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def run_project(entry: dict) -> bool:
    pid_file = TRACKER / "overnight.pid"
    project_id = entry["id"]
    proj_dir   = PROJECTS / project_id
    title      = entry.get("title") or project_id

    log(f"{'=' * 56}")
    log(f"START  {title}")
    log(f"  dir: {proj_dir}")
    log(f"{'=' * 56}")
    send_ntfy(f"▶ Starting: {title}")
    set_status(project_id, "running")

    # Per-project log mirrors to both queue.log and projects/<id>/tracker/overnight.log
    proj_log = proj_dir / "tracker" / "overnight.log"
    proj_log.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PIPELINE_ROOT"] = str(proj_dir)
    env["TERM"] = "xterm-256color"

    proc = subprocess.Popen(
        [sys.executable, "-u", str(OVERNIGHT)],
        env=env, cwd=REPO_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    pid_file.write_text(str(proc.pid), encoding="utf-8")

    for line in proc.stdout:  # type: ignore[union-attr]
        sys.stdout.write(line); sys.stdout.flush()
        with LOG_FILE.open("a") as f:  f.write(line)
        with proj_log.open("a")  as f: f.write(line)

    proc.wait()
    pid_file.unlink(missing_ok=True)

    if proc.returncode == 0:
        log(f"DONE  {title}")
        pf = proj_dir / "project.json"
        yt_id = None
        if pf.is_file():
            yt_id = json.loads(pf.read_text(encoding="utf-8")).get("youtube_video_id")
        next_status = "done" if yt_id else "thumbnails"
        set_status(project_id, next_status, {"youtube_video_id": yt_id} if yt_id else None)
        send_ntfy(f"✅ Done: {title}" + (f"\nhttps://youtu.be/{yt_id}" if yt_id else " — pick a thumbnail"))
        return True
    else:
        log(f"FAILED  {title} (exit {proc.returncode})")
        set_status(project_id, "failed")
        send_ntfy(f"❌ Failed: {title}")
        return False


def main() -> int:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()) + "\n", encoding="utf-8")
    log("Queue runner started — watching tracker/queue.json")

    try:
        while True:
            q = load_queue()
            pending = [p for p in q if p.get("status") == "queued"]
            if not pending:
                time.sleep(20)
                continue
            run_project(pending[0])
            time.sleep(3)
    except KeyboardInterrupt:
        log("Queue runner stopped")
    finally:
        PID_FILE.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
