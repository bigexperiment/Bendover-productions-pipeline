#!/usr/bin/env python3
"""Multi-project pipeline queue — runs projects one after another, unattended.

Each project's image generation auto-waits when credits run out and resumes
when the 5-hour window resets. You set up the projects and leave the computer.

Usage:
    python3 scripts/queue_runner.py           # reads queue.json
    python3 scripts/queue_runner.py path/to/project1 path/to/project2

Monitor:
    tail -f tracker/queue.log
    (ntfy alerts sent at project start, completion, and failures)

Stop:
    bash scripts/stop_queue.sh
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_ROOT / "scripts"))
from lib.notify import send_ntfy  # noqa: E402

QUEUE_FILE = SCRIPTS_ROOT / "queue.json"
LOG_FILE = SCRIPTS_ROOT / "tracker" / "queue.log"
PID_FILE = SCRIPTS_ROOT / "tracker" / "queue.pid"
OVERNIGHT_RUNNER = SCRIPTS_ROOT / "scripts" / "overnight_runner.py"


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_projects() -> list[Path]:
    """Resolve project directories from CLI args or queue.json."""
    if len(sys.argv) > 1:
        dirs = []
        for arg in sys.argv[1:]:
            p = Path(arg).expanduser()
            dirs.append(p if p.is_absolute() else SCRIPTS_ROOT / p)
        return dirs

    if not QUEUE_FILE.is_file():
        # Default: run the current project at repo root
        return [SCRIPTS_ROOT]

    data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    dirs = []
    for item in data.get("projects", []):
        raw = item if isinstance(item, str) else item.get("path", "")
        p = Path(raw).expanduser()
        dirs.append(p if p.is_absolute() else SCRIPTS_ROOT / p)
    return dirs


def project_name(project_dir: Path) -> str:
    pf = project_dir / "project.json"
    if pf.is_file():
        try:
            return json.loads(pf.read_text(encoding="utf-8")).get("name") or project_dir.name
        except (json.JSONDecodeError, OSError):
            pass
    return project_dir.name


def is_complete(project_dir: Path) -> bool:
    """Return True if this project's final.mp4 already exists."""
    return (project_dir / "06-output" / "final.mp4").is_file()


def run_project(project_dir: Path) -> bool:
    """Run the full pipeline for one project directory. Returns True on success."""
    name = project_name(project_dir)

    if not (project_dir / "project.json").is_file():
        log(f"SKIP {name}: no project.json in {project_dir}")
        return False

    if is_complete(project_dir):
        log(f"SKIP {name}: final.mp4 already exists")
        return True

    log(f"{'=' * 60}")
    log(f"START: {name}")
    log(f"  Dir: {project_dir}")
    log(f"{'=' * 60}")
    send_ntfy(f"Queue: starting {name}")

    env = os.environ.copy()
    env["PIPELINE_ROOT"] = str(project_dir)

    result = subprocess.run(
        ["python3", "-u", str(OVERNIGHT_RUNNER)],
        env=env,
        cwd=SCRIPTS_ROOT,
        text=True,
    )

    if result.returncode != 0:
        log(f"FAILED: {name} (exit {result.returncode})")
        send_ntfy(f"Queue FAILED: {name}")
        return False

    log(f"DONE: {name}")
    return True


def main() -> int:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()) + "\n")

    try:
        projects = load_projects()
    except Exception as exc:
        log(f"ERROR loading project list: {exc}")
        return 1

    if not projects:
        log("No projects to run — add entries to queue.json")
        return 1

    log(f"Queue: {len(projects)} project(s)")
    for p in projects:
        log(f"  · {project_name(p)} — {p}")
    send_ntfy(f"Pipeline queue started: {len(projects)} project(s)")

    successes = failures = 0
    for project_dir in projects:
        try:
            ok = run_project(project_dir)
            if ok:
                successes += 1
            else:
                failures += 1
        except KeyboardInterrupt:
            log("Interrupted by user")
            break
        except Exception as exc:
            log(f"ERROR: {project_dir}: {exc}")
            failures += 1

    summary = f"Queue complete — {successes} done, {failures} failed"
    log(summary)
    send_ntfy(summary)

    PID_FILE.unlink(missing_ok=True)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
