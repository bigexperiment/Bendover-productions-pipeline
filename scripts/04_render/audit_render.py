#!/usr/bin/env python3
"""Audit a rendered MP4 against the authoritative image manifest."""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PIPELINE_ROOT") or Path(__file__).resolve().parents[2])
MANIFEST = ROOT / "04-manifest" / "image_regen_manifest.csv"
AUDIO = ROOT / "02-audio" / "narration.mp3"


def duration(path: Path) -> float:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)], text=True)
    return float(out.strip())


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: audit_render.py OUTPUT.mp4", file=sys.stderr)
        return 2
    video = Path(sys.argv[1])
    if not video.is_file() or not MANIFEST.is_file() or not AUDIO.is_file():
        print("FAILED: output, manifest, and audio are all required", file=sys.stderr)
        return 1
    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8", newline="")))
    expected = sum(float(r.get("duration") or 0) for r in rows)
    actual_video = duration(video)
    actual_audio = duration(AUDIO)
    errors = []
    if len(rows) == 0:
        errors.append("manifest is empty")
    # Manifest timings are stored as whole seconds; the final audio duration
    # can therefore differ by less than one second after rounding.
    if abs(expected - actual_audio) > 0.5:
        errors.append(f"manifest/audio drift {expected:.3f}s vs {actual_audio:.3f}s")
    if abs(actual_video - actual_audio) > 0.5:
        errors.append(f"video/audio drift {actual_video:.3f}s vs {actual_audio:.3f}s")
    if any(float(r.get("duration") or 0) <= 0 for r in rows):
        errors.append("non-positive manifest duration")
    report = {
        "video": str(video),
        "frames": len(rows),
        "manifest_duration": round(expected, 3),
        "audio_duration": round(actual_audio, 3),
        "video_duration": round(actual_video, 3),
        "errors": errors,
        "status": "pass" if not errors else "fail",
    }
    out = ROOT / "tracker" / "render_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    # Always leave a compact visual audit artifact beside the machine report.
    # It samples the entire timeline, so reviewers/vision QA can inspect the
    # actual rendered frames rather than only the source PNG directory.
    samples = ROOT / "tracker" / "render_samples.jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video),
         "-vf", "fps=1/4,scale=240:-1,tile=8x6", "-frames:v", "1", str(samples)],
        check=False,
    )
    if errors:
        print("FAILED: render audit", file=sys.stderr)
        print("\n".join(f"- {e}" for e in errors), file=sys.stderr)
        return 1
    print(f"OK: render audit passed ({len(rows)} frames, {actual_video:.2f}s video, {actual_audio:.2f}s audio)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
