#!/usr/bin/env python3
"""Strict sequential credit calibration — one image at a time, precise before/after."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "07_credits"))

from fetch_codex_usage import read_usage_payload, should_stop_generation  # noqa: E402

# Reuse explore generator helpers
sys.path.insert(0, str(ROOT / "scripts" / "03_images"))
from generate_style_explore import (  # noqa: E402
    EXPLORE_DIR,
    ExploreJob,
    build_prompt,
    load_project,
    read_pending_jobs,
    refresh_usage,
    usage_snapshot,
)

OUT_FILE = EXPLORE_DIR / "credit_calibration.json"
SETTLE_POLLS = 6
SETTLE_INTERVAL = 2.0
JOB_TIMEOUT = 20 * 60


def wait_usage_stable(before: dict) -> dict:
    """Poll until used% increases, then wait for stable reading."""
    prev = before
    for _ in range(60):
        time.sleep(SETTLE_INTERVAL)
        snap = usage_snapshot(refresh_usage(force=True))
        if snap["five_hour_used"] > prev["five_hour_used"] or snap["weekly_used"] > prev["weekly_used"]:
            stable = snap
            for _ in range(SETTLE_POLLS):
                time.sleep(SETTLE_INTERVAL)
                nxt = usage_snapshot(refresh_usage(force=True))
                if nxt["five_hour_used"] == stable["five_hour_used"] and nxt["weekly_used"] == stable["weekly_used"]:
                    stable = nxt
                else:
                    stable = nxt
            return stable
        prev = snap
    return usage_snapshot(refresh_usage(force=True))


def run_one(job: ExploreJob, project: dict) -> tuple[int, dict, dict]:
    before = usage_snapshot(refresh_usage(force=True))
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    cmd = [
        "codex", "exec", "--enable", "image_generation",
        "-s", "workspace-write",
        "--dangerously-bypass-approvals-and-sandbox",
        "-C", str(ROOT),
        build_prompt(project, job),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT, env=env)
    try:
        code = proc.wait(timeout=JOB_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        return 1, before, before
    if code != 0 or not (EXPLORE_DIR / job.filename).is_file():
        return code, before, usage_snapshot(refresh_usage(force=True))
    after = wait_usage_stable(before)
    return 0, before, after


def print_report(data: dict) -> None:
    baseline = data["baseline"]
    samples = data["samples"]
    print("\n=== Precise credit calibration ===")
    print(f"Baseline: 5h {baseline['five_hour_used']:.0f}% used | weekly {baseline['weekly_used']:.0f}% used")
    print(f"{'#':<3} {'Label':<24} {'5h cost':>8} {'5h left':>8} {'wk cost':>8} {'wk left':>8}")
    for i, s in enumerate(samples, 1):
        print(
            f"{i:<3} {s['label'][:24]:<24} "
            f"+{s['five_hour_delta']:>5.1f}% {s['five_hour_after_remaining']:>6.1f}% "
            f"+{s['weekly_delta']:>5.1f}% {s['weekly_after_remaining']:>6.1f}%"
        )
    n = len(samples)
    if not n:
        return
    fh = [s["five_hour_delta"] for s in samples]
    wk = [s["weekly_delta"] for s in samples]
    print(f"\nTotal ({n} images):  5h +{sum(fh):.1f}%  |  weekly +{sum(wk):.1f}%")
    print(f"Average:           5h +{sum(fh)/n:.2f}%  |  weekly +{sum(wk)/n:.2f}%")
    print(f"Median:            5h +{sorted(fh)[n//2]:.1f}%  |  weekly +{sorted(wk)[n//2]:.1f}%")
    print(f"Min / Max:         5h {min(fh):.1f}–{max(fh):.1f}%  |  weekly {min(wk):.1f}–{max(wk):.1f}%")


def main() -> int:
    count = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 5
    project = load_project()
    pending = read_pending_jobs(limit=count)
    if not pending:
        print("No pending explore images.")
        return 1

    usage = refresh_usage(force=True)
    blocked, reason = should_stop_generation(usage)
    if blocked:
        print(f"Blocked: {reason}")
        return 2

    data = {
        "baseline": usage_snapshot(usage),
        "samples": [],
        "started_at": int(time.time()),
    }
    EXPLORE_DIR.mkdir(parents=True, exist_ok=True)

    for job in pending:
        print(f"Generating {job.filename} ({job.label})...")
        code, before, after = run_one(job, project)
        sample = {
            "filename": job.filename,
            "label": job.label,
            "five_hour_delta": round(after["five_hour_used"] - before["five_hour_used"], 2),
            "weekly_delta": round(after["weekly_used"] - before["weekly_used"], 2),
            "five_hour_before_remaining": before["five_hour_remaining"],
            "five_hour_after_remaining": after["five_hour_remaining"],
            "weekly_before_remaining": before["weekly_remaining"],
            "weekly_after_remaining": after["weekly_remaining"],
            "exit_code": code,
        }
        data["samples"].append(sample)
        OUT_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        if code == 0:
            print(f"  → 5h +{sample['five_hour_delta']}% (now {sample['five_hour_after_remaining']:.0f}% left) | "
                  f"weekly +{sample['weekly_delta']}% (now {sample['weekly_after_remaining']:.0f}% left)")
        else:
            print(f"  → failed exit={code}")

    print_report(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
