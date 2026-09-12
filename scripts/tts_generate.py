#!/usr/bin/env python3
"""Generate project narration with Google Cloud TTS and the Charon voice."""
from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

from google.cloud import texttospeech


VOICE = "en-US-Chirp3-HD-Charon"
MAX_BYTES = 4500


def chunks(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.replace("\n", " ").strip())
    result: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate.encode("utf-8")) > MAX_BYTES:
            result.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        result.append(current)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--rate", type=float, default=0.95)
    args = parser.parse_args()

    script = args.project / "01-script" / "Script.txt"
    audio_dir = args.project / "02-audio"
    output = audio_dir / "narration.mp3"
    text = script.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit(f"Empty script: {script}")

    audio_dir.mkdir(parents=True, exist_ok=True)
    client = texttospeech.TextToSpeechClient()
    pieces = chunks(text)
    with tempfile.TemporaryDirectory(prefix="tts-") as temp:
        temp_path = Path(temp)
        concat = temp_path / "concat.txt"
        with concat.open("w", encoding="utf-8") as manifest:
            for index, piece in enumerate(pieces):
                piece_path = temp_path / f"piece-{index:04d}.mp3"
                if not piece_path.exists():
                    response = client.synthesize_speech(
                        input=texttospeech.SynthesisInput(text=piece),
                        voice=texttospeech.VoiceSelectionParams(language_code="en-US", name=VOICE),
                        audio_config=texttospeech.AudioConfig(
                            audio_encoding=texttospeech.AudioEncoding.MP3,
                            speaking_rate=args.rate,
                        ),
                    )
                    piece_path.write_bytes(response.audio_content)
                manifest.write(f"file '{piece_path}'\n")
                print(f"TTS chunk {index + 1}/{len(pieces)} complete")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(output)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
    print(f"Created {output} ({output.stat().st_size} bytes, {len(pieces)} chunks, voice={VOICE})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
