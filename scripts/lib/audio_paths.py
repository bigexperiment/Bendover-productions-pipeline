"""Resolve the single narration file in 02-audio/."""
from __future__ import annotations

from pathlib import Path

from lib.folders import AUDIO_EXTS, DIR_AUDIO, NARRATION_FILE


def find_narration_audio() -> Path:
    if NARRATION_FILE.is_file():
        return NARRATION_FILE

    if not DIR_AUDIO.is_dir():
        raise FileNotFoundError(
            "No narration audio found. Add one file to 02-audio/ (e.g. narration.mp3)."
        )

    matches = sorted(
        path
        for path in DIR_AUDIO.iterdir()
        if path.is_file() and path.suffix.lower() in AUDIO_EXTS
    )
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(
            "No narration audio found. Add one file to 02-audio/ (e.g. narration.mp3)."
        )
    names = ", ".join(path.name for path in matches)
    raise FileNotFoundError(
        f"Expected exactly one audio file in 02-audio/, found {len(matches)}: {names}"
    )
