#!/usr/bin/env python3
"""Generate all pending frames from the manifest via parallel Codex workers."""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from lib.folders import DIR_IMAGES as IMAGES_DIR, MANIFEST_FILE, PROGRESS_FILE  # noqa: E402
from lib.image_prompt import FrameJob, build_frame_prompt  # noqa: E402
PROJECT_FILE = ROOT / "project.json"
TRACKER_DIR = ROOT / "tracker"
TRACKER_STATUS = TRACKER_DIR / "status.json"
TRACKER_RECENT = TRACKER_DIR / "recent.json"
TRACKER_LOGS = TRACKER_DIR / "logs"
RUNNER_LOG = TRACKER_DIR / "runner.log"
MANIFEST_SCRIPT = ROOT / "scripts/02_manifest/build_plan.py"
CREDITS_DIR = ROOT / "scripts/07_credits"
DEFAULT_WORKERS = 5
JOB_TIMEOUT_SEC = 20 * 60  # kill hung codex exec per frame

sys.path.insert(0, str(CREDITS_DIR))
from fetch_codex_usage import read_usage_payload, should_stop_generation  # noqa: E402


def load_project() -> dict:
    if PROJECT_FILE.is_file():
        return json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    return {}


def read_pending_jobs(limit: int | None = None) -> list[FrameJob]:
    if not MANIFEST_FILE.is_file():
        raise FileNotFoundError(f"Manifest not found: {MANIFEST_FILE}")

    jobs: list[FrameJob] = []
    with MANIFEST_FILE.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("status") != "pending":
                continue
            if (IMAGES_DIR / row["filename"]).exists():
                continue
            jobs.append(
                FrameJob(
                    timestamp=row["timestamp"],
                    filename=row["filename"],
                    scene=row["scene"],
                    transcript=row["transcript"],
                )
            )
    return jobs[:limit] if limit else jobs


def launch_job(job: FrameJob, project: dict) -> subprocess.Popen[str]:
    TRACKER_LOGS.mkdir(parents=True, exist_ok=True)
    log_path = TRACKER_LOGS / f"{job.filename}.log"
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    command = [
        "codex",
        "exec",
        "--enable",
        "image_generation",
        "-s",
        "workspace-write",
        "--dangerously-bypass-approvals-and-sandbox",
        "-C",
        str(ROOT),
        build_frame_prompt(project, job, ROOT, MANIFEST_SCRIPT),
    ]
    log_handle = log_path.open("w", encoding="utf-8")
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=ROOT,
        env=env,
    )


def append_log(message: str) -> None:
    TRACKER_DIR.mkdir(parents=True, exist_ok=True)
    with RUNNER_LOG.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def refresh_manifest() -> None:
    subprocess.run(
        ["python3", str(MANIFEST_SCRIPT), "refresh"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )


def refresh_usage(force: bool = False) -> dict:
    subprocess.run(
        ["python3", str(CREDITS_DIR / "fetch_codex_usage.py")] + (["--force"] if force else []),
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    return read_usage_payload(force=force)


def write_status(
    *,
    workers: int,
    total: int,
    completed: int,
    failed: int,
    running: int,
    queued: int,
    phase: str,
    stop_reason: str = "",
) -> None:
    progress = {}
    if PROGRESS_FILE.is_file():
        progress = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))

    existing = {}
    if TRACKER_STATUS.is_file():
        try:
            existing = json.loads(TRACKER_STATUS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    now = int(time.time())
    started_at = existing.get("started_at")
    if phase == "running" and not started_at:
        started_at = now
    if phase in ("complete", "stopped_credits") and started_at:
        started_at = existing.get("started_at")

    payload = {
        "phase": phase,
        "workers": workers,
        "total_jobs": total,
        "completed_jobs": completed,
        "failed_jobs": failed,
        "running_jobs": running,
        "queued_jobs": queued,
        "done_frames": progress.get("done_frames", 0),
        "pending_frames": progress.get("pending_frames", 0),
        "progress_bar": progress.get("progress_bar", ""),
        "stop_reason": stop_reason,
        "started_at": started_at,
        "updated_at": now,
    }
    TRACKER_STATUS.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    refresh_usage()


def write_recent(limit: int = 8) -> None:
    images = sorted(IMAGES_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    TRACKER_RECENT.write_text(
        json.dumps(
            {"recent_filenames": [p.name for p in images[:limit]], "updated_at": int(time.time())},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def parse_args() -> tuple[int, int | None, bool]:
    workers = DEFAULT_WORKERS
    limit = None
    force = False
    for arg in sys.argv[1:]:
        if arg == "--force":
            force = True
        elif arg.isdigit():
            if workers == DEFAULT_WORKERS and limit is None:
                workers = int(arg)
            else:
                limit = int(arg)
    return workers, limit, force


def main() -> int:
    workers, limit, force = parse_args()
    project = load_project()

    if not project.get("style_approved"):
        print("ERROR: Set style_approved: true in project.json after user approves samples.")
        return 1

    jobs = read_pending_jobs(limit=limit)
    total = len(jobs)

    if not jobs:
        refresh_manifest()
        print("No pending frames — manifest is complete.")
        write_status(workers=workers, total=0, completed=0, failed=0, running=0, queued=0, phase="complete")
        return 0

    usage = refresh_usage(force=True)
    blocked, reason = should_stop_generation(usage)
    if blocked and not force:
        append_log(f"not started: {reason}")
        write_status(workers=workers, total=total, completed=0, failed=0, running=0, queued=total, phase="stopped_credits", stop_reason=reason)
        print(f"Stopped: {reason}")
        return 2

    queue = jobs[:]
    running: dict[str, tuple[FrameJob, subprocess.Popen[str], float]] = {}
    completed = failed = 0
    stopped = False
    stop_reason = ""

    append_log(f"generate_images workers={workers} pending={total}")
    write_status(workers=workers, total=total, completed=0, failed=0, running=0, queued=total, phase="running")

    while queue or running:
        usage = refresh_usage(force=True)
        if should_stop_generation(usage)[0]:
            stopped = True
            stop_reason = should_stop_generation(usage)[1]
            for _, (_, proc, _) in list(running.items()):
                if proc.poll() is None:
                    proc.terminate()
            break

        while queue and len(running) < workers:
            job = queue.pop(0)
            running[job.filename] = (job, launch_job(job, project), time.time())

        done_now: list[str] = []
        for filename, (job, proc, started) in running.items():
            code = proc.poll()
            if code is None:
                if time.time() - started > JOB_TIMEOUT_SEC:
                    append_log(f"timeout {filename} after {JOB_TIMEOUT_SEC}s")
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    done_now.append(filename)
                    failed += 1
                continue
            done_now.append(filename)
            if code == 0 and (IMAGES_DIR / filename).is_file():
                completed += 1
            else:
                failed += 1
                append_log(f"failed {filename} exit={code}")

        for filename in done_now:
            del running[filename]

        refresh_manifest()
        write_recent()
        write_status(
            workers=workers,
            total=total,
            completed=completed,
            failed=failed,
            running=len(running),
            queued=len(queue),
            phase="stopped_credits" if stopped else "running",
            stop_reason=stop_reason,
        )
        if not done_now and running:
            time.sleep(2)

    phase = "stopped_credits" if stopped else "complete"
    write_status(workers=workers, total=total, completed=completed, failed=failed, running=0, queued=len(queue), phase=phase, stop_reason=stop_reason)
    refresh_manifest()
    print(f"Done. completed={completed} failed={failed} queued={len(queue)}")
    return 0 if not stopped else 2


if __name__ == "__main__":
    raise SystemExit(main())
