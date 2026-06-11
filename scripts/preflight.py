#!/usr/bin/env python3
"""Validate workspace inputs before build_plan / image generation.

Exit 0 = all checks passed. Exit 1 = fix reported errors before continuing.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.audio_paths import find_narration_audio  # noqa: E402
from lib.folders import (  # noqa: E402
    MANIFEST_FILE,
    PLAN_FILE,
    PROJECT_FILE,
    SCRIPT_FILE,
    TRANSCRIPT_FILE,
)

# Reuse manifest parser so preflight matches build_plan behavior.
from importlib.util import module_from_spec, spec_from_file_location

_spec = spec_from_file_location(
    "build_plan_preflight",
    ROOT / "scripts" / "02_manifest" / "build_plan.py",
)
assert _spec and _spec.loader
_build_plan = module_from_spec(_spec)
sys.modules[_spec.name] = _build_plan
_spec.loader.exec_module(_build_plan)

REQUIRED_PROJECT_KEYS = ("name", "image_style", "style_guide", "text_rules", "tone")


def ok(msg: str) -> None:
    print(f"  OK  {msg}")


def fail(errors: list[str], msg: str) -> None:
    errors.append(msg)
    print(f"  FAIL  {msg}")


def warn(warnings: list[str], msg: str) -> None:
    warnings.append(msg)
    print(f"  WARN  {msg}")


def check_tool(errors: list[str], name: str) -> None:
    if shutil.which(name):
        ok(f"{name} found")
    else:
        fail(errors, f"{name} not found on PATH (required for audio + render)")


def audio_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def run_preflight(*, phase: str = "manifest") -> int:
    errors: list[str] = []
    warnings: list[str] = []

    print("Preflight checks")
    print(f"  phase: {phase}")
    print(f"  root:  {ROOT}\n")

    # --- project.json ---
    if not PROJECT_FILE.is_file():
        fail(errors, "Missing project.json at repo root")
    else:
        try:
            project = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
            ok("project.json is valid JSON")
        except json.JSONDecodeError as exc:
            fail(errors, f"project.json is not valid JSON: {exc}")
            project = {}
        for key in REQUIRED_PROJECT_KEYS:
            if not str(project.get(key, "")).strip():
                fail(errors, f"project.json missing or empty: {key}")
        if project.get("name"):
            ok(f"project name: {project['name']!r}")

    # --- script ---
    if not SCRIPT_FILE.is_file():
        fail(errors, f"Missing {SCRIPT_FILE.relative_to(ROOT)}")
    elif SCRIPT_FILE.stat().st_size < 100:
        fail(errors, "01-script/Script.txt is empty or too short")
    else:
        ok(f"script ({SCRIPT_FILE.stat().st_size} bytes)")

    # --- audio (exactly one file) ---
    try:
        audio = find_narration_audio()
        ok(f"audio: {audio.relative_to(ROOT)}")
    except FileNotFoundError as exc:
        fail(errors, str(exc))
        audio = None

    check_tool(errors, "ffprobe")
    check_tool(errors, "ffmpeg")

    duration = 0.0
    if audio and not errors:
        try:
            duration = audio_duration(audio)
            if duration < 10:
                fail(errors, f"Audio too short ({duration:.1f}s)")
            else:
                ok(f"audio duration ~{duration:.0f}s")
        except (subprocess.CalledProcessError, ValueError) as exc:
            fail(errors, f"Could not read audio duration: {exc}")

    # --- transcript ---
    if not TRANSCRIPT_FILE.is_file():
        fail(errors, f"Missing {TRANSCRIPT_FILE.relative_to(ROOT)}")
    elif TRANSCRIPT_FILE.stat().st_size < 50:
        fail(errors, "03-transcript/transcript.txt is empty or too short")
    else:
        text = TRANSCRIPT_FILE.read_text(encoding="utf-8").strip()
        ok(f"transcript ({len(text)} chars)")
        if duration > 0:
            try:
                segments, source = _build_plan.parse_transcript(text, int(round(duration)))
                ok(f"transcript parses as {source!r} ({len(segments)} segments)")
                if source == "plain":
                    warn(
                        warnings,
                        "No timestamps detected — manifest timing will be estimated. "
                        "Re-export from TurboScribe with Section Timestamps.",
                    )
                last_end = max(seg.end for seg in segments)
                drift = abs(last_end - int(round(duration)))
                if drift > 15:
                    warn(
                        warnings,
                        f"Transcript end ({last_end}s) differs from audio ({duration:.0f}s) by {drift}s",
                    )
            except Exception as exc:
                fail(errors, f"Transcript parse failed: {exc}")

    if phase == "images":
        for path, label in (
            (PLAN_FILE, "image_cut_plan.txt"),
            (MANIFEST_FILE, "image_regen_manifest.csv"),
        ):
            if not path.is_file():
                fail(errors, f"Missing 04-manifest/{label} — run build_plan.py first")
            else:
                ok(f"04-manifest/{label}")

        if PROJECT_FILE.is_file():
            project = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
            if not project.get("style_approved"):
                warn(warnings, "style_approved is false — get sample approval before bulk gen")

        status_script = ROOT / "scripts" / "status_studio.sh"
        if status_script.is_file():
            result = subprocess.run(
                [str(status_script)],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            if result.returncode == 0:
                ok("Studio tracker responds")
            else:
                warn(warnings, "Studio tracker not running (start before image generation)")

    print()
    if warnings:
        print(f"Warnings ({len(warnings)}):")
        for item in warnings:
            print(f"  - {item}")
        print()

    if errors:
        print(f"FAILED — {len(errors)} error(s). Fix before continuing:")
        for item in errors:
            print(f"  - {item}")
        return 1

    print("All preflight checks passed.")
    return 0


def main() -> int:
    phase = "images" if len(sys.argv) > 1 and sys.argv[1] == "--images" else "manifest"
    return run_preflight(phase=phase)


if __name__ == "__main__":
    raise SystemExit(main())
