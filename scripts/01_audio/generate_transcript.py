#!/usr/bin/env python3
"""Transcribe narration audio locally with Whisper (faster-whisper) — replaces
manual TurboScribe export. Writes 03-transcript/transcript.txt in the
`[M:SS] text` line format that scripts/02_manifest/build_plan.py already
parses (LINE_MS_RE), so nothing downstream needs to change.

Runs against the dedicated .venv-whisper (faster-whisper + ctranslate2 aren't
installed in the ambient/system Python). Model weights are downloaded once
from Hugging Face and cached in ~/.cache/huggingface.

Usage:
    .venv-whisper/bin/python3 scripts/01_audio/generate_transcript.py
    .venv-whisper/bin/python3 scripts/01_audio/generate_transcript.py --audio path/to.mp3
    .venv-whisper/bin/python3 scripts/01_audio/generate_transcript.py --model medium.en

PIPELINE_ROOT env var (same convention as the rest of the pipeline) points
this at a specific projects/<slug>/ directory instead of the repo root.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.folders import DIR_TRANSCRIPT, NARRATION_FILE, TRANSCRIPT_FILE, DIR_AUDIO, AUDIO_EXTS  # noqa: E402

# medium.en: ~4min to transcribe 6.5min of clean single-speaker narration on an
# M1 CPU, word-for-word accurate against ElevenLabs TTS audio in testing.
# large-v3 is ~2x more accurate on noisy/accented audio but 3-4x slower on CPU —
# not worth it for this channel's clean narration. Override with --model if needed.
DEFAULT_MODEL = "medium.en"


def write_progress(path: Path | None, data: dict) -> None:
    if path is None:
        return
    try:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".progress-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except Exception:
        pass


def find_audio() -> Path | None:
    if NARRATION_FILE.is_file():
        return NARRATION_FILE
    if DIR_AUDIO.is_dir():
        for f in sorted(DIR_AUDIO.iterdir()):
            if f.is_file() and f.suffix.lower() in AUDIO_EXTS and f.name != ".gitkeep":
                return f
    return None


def fmt_marker(seconds: float) -> str:
    total = int(round(seconds))
    m, s = divmod(total, 60)
    return f"[{m}:{s:02d}]"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--audio", type=Path, default=None, help="Audio file (default: 02-audio/narration.* )")
    p.add_argument("--output", type=Path, default=TRANSCRIPT_FILE, help="Where to write the transcript")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help="faster-whisper model size/name (default: large-v3; try medium.en for speed)")
    p.add_argument("--language", default="en", help="Language code, or 'auto' to detect (default: en)")
    p.add_argument("--device", default="cpu", choices=["cpu", "auto"], help="Inference device (default: cpu)")
    p.add_argument("--compute-type", default="int8",
                   help="ctranslate2 compute type — int8 (fast, CPU) or float32 (max precision)")
    p.add_argument("--progress-file", type=Path, default=None,
                   help="Write JSON progress updates here (for the Studio UI progress bar)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    progress = args.progress_file

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        msg = (
            "faster-whisper is not installed in this Python. Run:\n"
            "  .venv-whisper/bin/python3 scripts/01_audio/generate_transcript.py\n"
            "(or: .venv-whisper/bin/pip install faster-whisper)"
        )
        print(msg, file=sys.stderr)
        write_progress(progress, {"status": "error", "error": msg})
        return 1

    audio_path = args.audio or find_audio()
    if not audio_path or not audio_path.is_file():
        msg = f"No audio file found (looked in {DIR_AUDIO})"
        print(msg, file=sys.stderr)
        write_progress(progress, {"status": "error", "error": msg})
        return 1

    print(f"Audio:  {audio_path}")
    print(f"Model:  {args.model} ({args.device}, {args.compute_type})")
    t0 = time.time()
    write_progress(progress, {"status": "running", "pct": 0, "stage": "loading model"})

    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)

    language = None if args.language == "auto" else args.language
    write_progress(progress, {"status": "running", "pct": 0, "stage": "transcribing"})
    segments, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=True,
    )

    print(f"Detected language: {info.language} (p={info.language_probability:.2f})")
    duration = info.duration or 0

    DIR_TRANSCRIPT.mkdir(parents=True, exist_ok=True)
    lines = []
    n = 0
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        lines.append(f"{fmt_marker(seg.start)} {text}")
        n += 1
        print(f"  {fmt_marker(seg.start)} {text}")
        pct = min(99, int(seg.end / duration * 100)) if duration else 0
        write_progress(progress, {
            "status": "running", "pct": pct, "stage": "transcribing",
            "current": seg.end, "duration": duration,
        })

    if not lines:
        msg = "Whisper produced no speech segments — check the audio file."
        print(msg, file=sys.stderr)
        write_progress(progress, {"status": "error", "error": msg})
        return 1

    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elapsed = time.time() - t0
    print(f"\nWrote {n} segments ({args.output.stat().st_size} bytes) to {args.output}")
    print(f"Done in {elapsed:.0f}s")
    write_progress(progress, {"status": "done", "pct": 100, "segments": n, "elapsed": elapsed})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
