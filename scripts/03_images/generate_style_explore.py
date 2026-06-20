#!/usr/bin/env python3
"""Generate style-exploration frames — each one a unique scene + style.

Outputs to tracker/style-explore-run/ (ephemeral — not production frames).
Committed previews live in assets/style-samples/.
Runs sequentially (1 worker) by default so credit tracking is accurate.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from lib.image_prompt import DEFAULT_STYLE_GUIDE, DEFAULT_TEXT_RULES, DEFAULT_TONE  # noqa: E402
from lib.folders import (  # noqa: E402
    PROJECT_FILE,
    STYLE_EXPLORE_RUN,
    STYLE_SAMPLES_MANIFEST,
    STYLE_SAMPLES_VARIANTS,
)
from lib.notify import notify_credits_stopped  # noqa: E402

EXPLORE_DIR = STYLE_EXPLORE_RUN
VARIANTS_FILE = STYLE_SAMPLES_VARIANTS
MANIFEST_FILE = EXPLORE_DIR / "manifest.json"
PROGRESS_FILE = EXPLORE_DIR / "progress.json"
CREDITS_LOG = EXPLORE_DIR / "credits_log.json"
TRACKER_DIR = ROOT / "tracker"
TRACKER_STATUS = TRACKER_DIR / "status.json"
TRACKER_RECENT = TRACKER_DIR / "recent.json"
TRACKER_LOGS = TRACKER_DIR / "logs"
RUNNER_LOG = TRACKER_DIR / "runner.log"
CREDITS_DIR = ROOT / "scripts" / "07_credits"
DEFAULT_WORKERS = 1  # sequential — accurate per-image credit measurement
USAGE_SETTLE_SEC = 4  # wait for Codex rate-limit events after each image
JOB_TIMEOUT_SEC = 20 * 60

sys.path.insert(0, str(CREDITS_DIR))
from fetch_codex_usage import read_usage_payload, should_stop_generation  # noqa: E402


@dataclass
class ExploreJob:
    variant_id: str
    label: str
    filename: str
    image_style: str
    scene: str


def load_variants() -> list[dict]:
    data = json.loads(VARIANTS_FILE.read_text(encoding="utf-8"))
    return data.get("variants") or []


def load_project() -> dict:
    if PROJECT_FILE.is_file():
        return json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    return {}


def build_jobs() -> list[ExploreJob]:
    jobs = []
    for v in load_variants():
        jobs.append(
            ExploreJob(
                variant_id=v["id"],
                label=v["label"],
                filename=f"explore_{v['id']}.png",
                image_style=v["image_style"],
                scene=v["scene"],
            )
        )
    return jobs


def write_manifest(jobs: list[ExploreJob]) -> None:
    EXPLORE_DIR.mkdir(parents=True, exist_ok=True)
    variants = load_variants()
    payload = {
        "version": 2,
        "note": "Each frame is a unique scene, composition, and art style.",
        "total": len(jobs),
        "variants": [
            {
                "id": j.variant_id,
                "label": j.label,
                "filename": j.filename,
                "image_style": j.image_style,
                "scene": j.scene,
                "status": "done" if (EXPLORE_DIR / j.filename).is_file() else "pending",
            }
            for j in jobs
        ],
    }
    MANIFEST_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_pending_jobs(limit: int | None = None) -> list[ExploreJob]:
    jobs = build_jobs()
    pending = [j for j in jobs if not (EXPLORE_DIR / j.filename).is_file()]
    return pending[:limit] if limit else pending


def usage_snapshot(usage: dict) -> dict:
    five = usage.get("five_hour") or {}
    week = usage.get("weekly") or {}
    return {
        "five_hour_used": float(five.get("used_percent") or 0),
        "five_hour_remaining": float(five.get("remaining_percent") or 0),
        "weekly_used": float(week.get("used_percent") or 0),
        "weekly_remaining": float(week.get("remaining_percent") or 0),
    }


def refresh_usage(force: bool = False) -> dict:
    subprocess.run(
        ["python3", str(CREDITS_DIR / "fetch_codex_usage.py")] + (["--force"] if force else []),
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    return read_usage_payload(force=force)


def settle_usage(before: dict, timeout: float = 12.0) -> dict:
    """Poll until usage changes or timeout — avoids stale parallel readings."""
    deadline = time.time() + timeout
    latest = refresh_usage(force=True)
    snap = usage_snapshot(latest)
    while time.time() < deadline:
        if snap["five_hour_used"] > before["five_hour_used"] or snap["weekly_used"] > before["weekly_used"]:
            time.sleep(USAGE_SETTLE_SEC)
            latest = refresh_usage(force=True)
            return usage_snapshot(latest)
        time.sleep(1.5)
        latest = refresh_usage(force=True)
        snap = usage_snapshot(latest)
    return snap


def build_prompt(project: dict, job: ExploreJob) -> str:
    style_guide = (project.get("style_guide") or DEFAULT_STYLE_GUIDE).strip()
    text_rules = (project.get("text_rules") or DEFAULT_TEXT_RULES).strip()
    tone = (project.get("tone") or DEFAULT_TONE).strip()
    out_path = EXPLORE_DIR / job.filename

    return f"""Create a static cartoon illustration for a YouTube history explainer.

Style ({job.label}):
{job.image_style}

Scene (this frame only — unique composition):
{job.scene}

Tone: {tone}

Important:
{style_guide}

Text (sparingly — default none):
{text_rules}

Frame #{job.variant_id} — "{job.label}".
This must be visually distinct from other frames: different setting, action, and layout.
Characters should have personality — NOT generic stick figures.

Output:
- 16:9 landscape
- Use the built-in image_gen tool exactly once
- Save to: tracker/style-explore-run/{job.filename}
- Verify file exists at {out_path}
- Do not create any other files

Generate exactly one image.
"""


def launch_job(job: ExploreJob, project: dict) -> subprocess.Popen[str]:
    TRACKER_LOGS.mkdir(parents=True, exist_ok=True)
    log_path = TRACKER_LOGS / f"explore_{job.filename}.log"
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
        build_prompt(project, job),
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


def load_credits_log() -> dict:
    if CREDITS_LOG.is_file():
        try:
            return json.loads(CREDITS_LOG.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"baseline": None, "samples": [], "summary": {}}


def save_credits_log(data: dict) -> None:
    EXPLORE_DIR.mkdir(parents=True, exist_ok=True)
    CREDITS_LOG.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def recompute_summary(log: dict) -> None:
    baseline = log.get("baseline") or {}
    samples = log.get("samples") or []
    if not samples:
        log["summary"] = {}
        return

    fh_deltas = [s["five_hour_delta"] for s in samples if s.get("five_hour_delta", 0) > 0]
    wk_deltas = [s["weekly_delta"] for s in samples if s.get("weekly_delta", 0) > 0]

    last = samples[-1]
    total_fh = round(last.get("five_hour_after_used", last.get("five_hour_used_after", 0)) - baseline.get("five_hour_used", 0), 2)
    total_wk = round(last.get("weekly_after_used", last.get("weekly_used_after", 0)) - baseline.get("weekly_used", 0), 2)
    n = len(samples)

    avg_fh = round(total_fh / n, 2) if n else None
    avg_wk = round(total_wk / n, 2) if n else None

    log["summary"] = {
        "images_completed": n,
        "total_five_hour_spent": total_fh,
        "total_weekly_spent": total_wk,
        "avg_five_hour_per_image": avg_fh,
        "avg_weekly_per_image": avg_wk,
        "median_five_hour_per_image": round(sorted(fh_deltas)[len(fh_deltas) // 2], 2) if fh_deltas else avg_fh,
        "median_weekly_per_image": round(sorted(wk_deltas)[len(wk_deltas) // 2], 2) if wk_deltas else avg_wk,
        "projected_50_five_hour": round(50 * avg_fh, 1) if avg_fh else None,
        "projected_50_weekly": round(50 * avg_wk, 1) if avg_wk else None,
        "note": "Per-image cost = (total used since baseline) / images done. Sequential runs only.",
    }


def record_credit_sample(log: dict, job: ExploreJob, before: dict, after: dict) -> None:
    fh_delta = round(after["five_hour_used"] - before["five_hour_used"], 2)
    wk_delta = round(after["weekly_used"] - before["weekly_used"], 2)
    sample = {
        "filename": job.filename,
        "label": job.label,
        "variant_id": job.variant_id,
        "timestamp": int(time.time()),
        "five_hour_before_used": before["five_hour_used"],
        "five_hour_after_used": after["five_hour_used"],
        "five_hour_delta": fh_delta,
        "five_hour_before_remaining": before["five_hour_remaining"],
        "five_hour_after_remaining": after["five_hour_remaining"],
        "weekly_before_used": before["weekly_used"],
        "weekly_after_used": after["weekly_used"],
        "weekly_delta": wk_delta,
        "weekly_before_remaining": before["weekly_remaining"],
        "weekly_after_remaining": after["weekly_remaining"],
    }
    log["samples"].append(sample)
    recompute_summary(log)
    save_credits_log(log)


def write_progress(done: int, total: int, pending: int) -> None:
    EXPLORE_DIR.mkdir(parents=True, exist_ok=True)
    bar_len = 40
    filled = int(bar_len * done / total) if total else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    PROGRESS_FILE.write_text(
        json.dumps(
            {
                "mode": "style_explore",
                "version": 2,
                "total_frames": total,
                "done_frames": done,
                "pending_frames": pending,
                "progress_bar": f"[{bar}] {done}/{total}",
                "updated_at": int(time.time()),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


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
    all_jobs = build_jobs()
    done = sum(1 for j in all_jobs if (EXPLORE_DIR / j.filename).is_file())
    total_all = len(all_jobs)
    pending = total_all - done
    write_progress(done, total_all, pending)

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

    progress_data = {}
    if PROGRESS_FILE.is_file():
        try:
            progress_data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    payload = {
        "phase": phase,
        "mode": "style_explore",
        "workers": workers,
        "total_jobs": total,
        "completed_jobs": completed,
        "failed_jobs": failed,
        "running_jobs": running,
        "queued_jobs": queued,
        "done_frames": done,
        "pending_frames": pending,
        "total_frames": total_all,
        "progress_bar": progress_data.get("progress_bar", ""),
        "stop_reason": stop_reason,
        "started_at": started_at,
        "updated_at": now,
    }
    TRACKER_STATUS.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    refresh_usage()


def write_recent(limit: int = 8) -> None:
    images = sorted(EXPLORE_DIR.glob("explore_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    TRACKER_RECENT.write_text(
        json.dumps(
            {
                "mode": "style_explore",
                "recent_filenames": [f"style-explore-run/{p.name}" for p in images[:limit]],
                "updated_at": int(time.time()),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def parse_args() -> tuple[int, int | None, bool, bool, bool]:
    workers = DEFAULT_WORKERS
    limit = None
    force = False
    fresh = False
    recalibrate = False
    for arg in sys.argv[1:]:
        if arg == "--force":
            force = True
        elif arg == "--fresh":
            fresh = True
        elif arg == "--recalibrate":
            recalibrate = True
        elif arg.isdigit():
            if workers == DEFAULT_WORKERS and limit is None:
                workers = int(arg)
            else:
                limit = int(arg)
    return workers, limit, force, fresh, recalibrate


def wipe_explore_outputs() -> None:
    if EXPLORE_DIR.is_dir():
        for path in EXPLORE_DIR.glob("explore_*.png"):
            path.unlink()
    for path in (CREDITS_LOG, PROGRESS_FILE):
        if path.is_file():
            path.unlink()


def print_calibration_report(log: dict) -> None:
    baseline = log.get("baseline") or {}
    samples = log.get("samples") or []
    summary = log.get("summary") or {}
    if not samples:
        return
    print("\n=== Credit calibration (per image) ===")
    print(f"Baseline: 5h {baseline.get('five_hour_used')}% used ({baseline.get('five_hour_remaining')}% left) | "
          f"weekly {baseline.get('weekly_used')}% used ({baseline.get('weekly_remaining')}% left)")
    print(f"{'#':<3} {'Image':<22} {'5h Δ':>6} {'5h left':>8} {'wk Δ':>6} {'wk left':>8}")
    for i, s in enumerate(samples, 1):
        print(
            f"{i:<3} {s['label'][:22]:<22} "
            f"+{s['five_hour_delta']:>4.1f}% {s['five_hour_after_remaining']:>6.1f}% "
            f"+{s['weekly_delta']:>4.1f}% {s['weekly_after_remaining']:>6.1f}%"
        )
    print(f"\nTotals ({len(samples)} images): 5h +{summary.get('total_five_hour_spent')}% | weekly +{summary.get('total_weekly_spent')}%")
    print(f"Average per image:      5h +{summary.get('avg_five_hour_per_image')}% | weekly +{summary.get('avg_weekly_per_image')}%")
    print(f"Median per image:       5h +{summary.get('median_five_hour_per_image')}% | weekly +{summary.get('median_weekly_per_image')}%")


def main() -> int:
    workers, limit, force, fresh, recalibrate = parse_args()
    project = load_project()

    if fresh:
        wipe_explore_outputs()
        append_log("style_explore --fresh wiped prior outputs")

    all_jobs = build_jobs()
    write_manifest(all_jobs)

    jobs = read_pending_jobs(limit=limit)
    total = len(jobs)
    total_all = len(all_jobs)

    if not jobs:
        done = sum(1 for j in all_jobs if (EXPLORE_DIR / j.filename).is_file())
        write_status(workers=workers, total=0, completed=0, failed=0, running=0, queued=0, phase="complete")
        write_recent()
        print(f"Style explore complete — {done}/{total_all} variants on disk.")
        return 0

    usage = refresh_usage(force=True)
    blocked, reason = should_stop_generation(usage)
    if blocked and not force:
        append_log(f"style_explore not started: {reason}")
        write_status(workers=workers, total=total, completed=0, failed=0, running=0, queued=total, phase="stopped_credits", stop_reason=reason)
        print(f"Stopped: {reason}")
        return 2

    credits_log = load_credits_log()
    if recalibrate or not credits_log.get("baseline"):
        credits_log = {
            "baseline": usage_snapshot(usage),
            "samples": [],
            "summary": {},
            "recalibrated_at": int(time.time()),
        }
        save_credits_log(credits_log)
        append_log(f"style_explore recalibrate baseline 5h={credits_log['baseline']['five_hour_used']}% weekly={credits_log['baseline']['weekly_used']}%")

    if workers > 1:
        append_log(f"WARNING: workers={workers} — credit per-image stats will be approximate; use 1 worker for accuracy")

    queue = jobs[:]
    running: dict[str, tuple[ExploreJob, subprocess.Popen[str], float, dict]] = {}
    completed = failed = 0
    stopped = False
    stop_reason = ""
    last_stable = usage_snapshot(usage)

    append_log(f"style_explore v2 workers={workers} pending={total}")
    write_status(workers=workers, total=total, completed=0, failed=0, running=0, queued=total, phase="running")

    while queue or running:
        usage = refresh_usage(force=True)
        if should_stop_generation(usage)[0] and not force:
            stopped = True
            stop_reason = should_stop_generation(usage)[1]
            for _, (_, proc, _, _) in list(running.items()):
                if proc.poll() is None:
                    proc.terminate()
            break

        while queue and len(running) < workers:
            job = queue.pop(0)
            before = dict(last_stable)
            running[job.filename] = (job, launch_job(job, project), time.time(), before)

        done_now: list[str] = []
        for filename, (job, proc, started, before) in running.items():
            code = proc.poll()
            if code is None:
                if time.time() - started > JOB_TIMEOUT_SEC:
                    append_log(f"style_explore timeout {filename}")
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    done_now.append(filename)
                    failed += 1
                continue
            done_now.append(filename)
            if code == 0 and (EXPLORE_DIR / filename).is_file():
                completed += 1
                after = settle_usage(before)
                record_credit_sample(credits_log, job, before, after)
                last_stable = after
                summary = credits_log.get("summary", {})
                print(
                    f"  {job.label}: 5h +{after['five_hour_used'] - before['five_hour_used']:.1f}% "
                    f"weekly +{after['weekly_used'] - before['weekly_used']:.1f}% "
                    f"(avg {summary.get('avg_five_hour_per_image')}% / {summary.get('avg_weekly_per_image')}% per img)"
                )
            else:
                failed += 1
                append_log(f"style_explore failed {filename} exit={code}")

        for filename in done_now:
            del running[filename]

        write_manifest(build_jobs())
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
    write_manifest(build_jobs())
    write_recent()

    if stopped:
        usage = refresh_usage(force=True)
        notify_credits_stopped("Style explore", usage)

    credits_log = load_credits_log()
    summary = credits_log.get("summary", {})
    print(f"Done. completed={completed} failed={failed} queued={len(queue)}")
    if summary:
        print_calibration_report(credits_log)
    return 0 if not stopped else 2


if __name__ == "__main__":
    raise SystemExit(main())
