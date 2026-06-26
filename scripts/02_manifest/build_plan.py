#!/usr/bin/env python3
"""Build image_cut_plan.txt from a timestamped transcript (TurboScribe format).

Target ~2s per frame, intelligently up to 3s at natural speech breaks.
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


import os
SCRIPTS_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get("PIPELINE_ROOT") or SCRIPTS_ROOT)
sys.path.insert(0, str(SCRIPTS_ROOT / "scripts"))
from lib.audio_paths import find_narration_audio  # noqa: E402
from lib.folders import (  # noqa: E402
    DIR_IMAGES as IMAGES_DIR,
    MANIFEST_FILE,
    PLAN_FILE,
    PROGRESS_FILE,
    TRANSCRIPT_FILE,
)
PROJECT_FILE = ROOT / "project.json"

MIN_SECONDS = 2
TARGET_SECONDS = 2
MAX_SECONDS = 3

# Inline: (0:00) text (0:04) more text
INLINE_MARKER_RE = re.compile(r"\((\d+):(\d{2})\)")
# Line-start TurboScribe section timestamps: [0:00:05] or [0:05:30.5]
LINE_HMS_RE = re.compile(r"^\[(\d+):(\d{2}):(\d{2}(?:\.\d+)?)\]\s*(.*)$")
LINE_MS_RE = re.compile(r"^\[(\d+):(\d{2})\]\s*(.*)$")
# Seconds range: [2060.00 – 2065.00] text
LINE_RANGE_RE = re.compile(r"^\[(\d+(?:\.\d+)?)\s*[–\-]\s*(\d+(?:\.\d+)?)\]\s*(.*)$")
LINE_PAREN_RE = re.compile(r"^\((\d+):(\d{2})\)\s*(.*)$")
SRT_BLOCK_RE = re.compile(
    r"(\d+)\s*\n(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*\n([\s\S]*?)(?=\n\d+\s*\n|\Z)"
)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
PLAN_LINE_RE = re.compile(r"^\[(\d+):(\d{2})\]\s+(.*?)\s+\|\s+Transcript:\s+(.*)$")


@dataclass
class SpeechSegment:
    start: int
    end: int
    text: str


@dataclass
class FramePlan:
    start: int
    transcript: str

    @property
    def timestamp(self) -> str:
        minute, second = divmod(self.start, 60)
        return f"{minute}:{second:02d}"


def audio_seconds() -> float:
    candidate = find_narration_audio()
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(candidate),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def scene_prefix() -> str:
    if PROJECT_FILE.is_file():
        style = json.loads(PROJECT_FILE.read_text(encoding="utf-8")).get("image_style", "")
        if style:
            return "Educational stickman cartoon scene"
    return "Educational stickman cartoon scene"


def to_seconds(hours: int, minutes: int, seconds: float) -> int:
    return int(hours) * 3600 + int(minutes) * 60 + int(round(float(seconds)))


def strip_turboscribe_boilerplate(text: str) -> str:
    chunks: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("(Transcribed by TurboScribe"):
            continue
        chunks.append(stripped)
    return " ".join(chunks)


def parse_plain_transcript(text: str, audio_end: int) -> list[SpeechSegment]:
    cleaned = strip_turboscribe_boilerplate(text)
    sentences = split_sentences(cleaned)
    if not sentences:
        raise ValueError("Transcript is empty after removing TurboScribe boilerplate")

    total_weight = sum(len(sentence) for sentence in sentences) or 1
    segments: list[SpeechSegment] = []
    cursor = 0

    for index, sentence in enumerate(sentences):
        if index == len(sentences) - 1:
            end = audio_end
        else:
            share = len(sentence) / total_weight
            end = min(audio_end, cursor + max(MIN_SECONDS, round(audio_end * share)))
        if end <= cursor:
            end = min(audio_end, cursor + 1)
        segments.append(SpeechSegment(cursor, end, sentence))
        cursor = end

    return segments


def parse_line_timestamped_transcript(text: str, audio_end: int) -> list[SpeechSegment]:
    raw: list[tuple[int, str]] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("(Transcribed by TurboScribe"):
            continue

        matched = False
        for regex, parser in (
            (LINE_HMS_RE, lambda m: (to_seconds(int(m.group(1)), int(m.group(2)), m.group(3)), m.group(4))),
            (LINE_MS_RE, lambda m: (int(m.group(1)) * 60 + int(m.group(2)), m.group(3))),
            (LINE_RANGE_RE, lambda m: (int(round(float(m.group(1)))), m.group(3))),
            (LINE_PAREN_RE, lambda m: (int(m.group(1)) * 60 + int(m.group(2)), m.group(3))),
        ):
            match = regex.match(stripped)
            if match:
                start, chunk = parser(match)
                chunk = re.sub(r"\s+", " ", chunk).strip()
                if chunk:
                    raw.append((start, chunk))
                matched = True
                break

        if not matched and raw:
            raw[-1] = (raw[-1][0], f"{raw[-1][1]} {stripped}".strip())

    if not raw:
        raise ValueError("No TurboScribe section timestamps found")

    segments: list[SpeechSegment] = []
    for index, (start, chunk) in enumerate(raw):
        end = raw[index + 1][0] if index + 1 < len(raw) else audio_end
        if end <= start:
            end = min(audio_end, start + MIN_SECONDS)
        segments.append(SpeechSegment(start=start, end=end, text=chunk))
    return segments


def parse_srt_transcript(text: str, audio_end: int) -> list[SpeechSegment]:
    segments: list[SpeechSegment] = []
    for match in SRT_BLOCK_RE.finditer(text.strip() + "\n"):
        start = to_seconds(int(match.group(2)), int(match.group(3)), f"{match.group(4)}.{match.group(5)}")
        end = to_seconds(int(match.group(6)), int(match.group(7)), f"{match.group(8)}.{match.group(9)}")
        chunk = re.sub(r"\s+", " ", match.group(10)).strip()
        if chunk:
            segments.append(SpeechSegment(start=start, end=end, text=chunk))

    if not segments:
        raise ValueError("No SRT cues found")
    segments[-1] = SpeechSegment(segments[-1].start, audio_end, segments[-1].text)
    return segments


def parse_transcript(text: str, audio_end: int) -> tuple[list[SpeechSegment], str]:
    stripped = text.strip()
    if "-->" in stripped and SRT_BLOCK_RE.search(stripped):
        return parse_srt_transcript(stripped, audio_end), "srt"

    inline_count = len(INLINE_MARKER_RE.findall(stripped))
    if inline_count >= 2:
        return parse_inline_timestamped_transcript(stripped, audio_end), "timestamped"

    for line in stripped.splitlines():
        line = line.strip()
        if not line or line.startswith("(Transcribed by TurboScribe"):
            continue
        if LINE_HMS_RE.match(line) or LINE_MS_RE.match(line) or LINE_RANGE_RE.match(line) or LINE_PAREN_RE.match(line):
            return parse_line_timestamped_transcript(stripped, audio_end), "timestamped"

    if inline_count == 1:
        return parse_inline_timestamped_transcript(stripped, audio_end), "timestamped"
    return parse_plain_transcript(stripped, audio_end), "plain"


def parse_inline_timestamped_transcript(text: str, audio_end: int) -> list[SpeechSegment]:
    matches = list(INLINE_MARKER_RE.finditer(text))
    if not matches:
        raise ValueError("No (M:SS) timestamps found — use TurboScribe export format")

    segments: list[SpeechSegment] = []
    for index, match in enumerate(matches):
        start = int(match.group(1)) * 60 + int(match.group(2))
        content_start = match.end()
        content_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunk = re.sub(r"\s+", " ", text[content_start:content_end]).strip()
        if not chunk:
            continue
        end = (
            int(matches[index + 1].group(1)) * 60 + int(matches[index + 1].group(2))
            if index + 1 < len(matches)
            else audio_end
        )
        segments.append(SpeechSegment(start=start, end=end, text=chunk))

    return segments


def split_text_chunks(text: str, parts: int) -> list[str]:
    words = text.split()
    if parts <= 1 or not words:
        stripped = text.strip()
        return [stripped] if stripped else []
    chunks: list[str] = []
    size = len(words) / parts
    for index in range(parts):
        start = round(index * size)
        end = len(words) if index + 1 == parts else round((index + 1) * size)
        chunk = " ".join(words[start:end]).strip()
        if chunk:
            chunks.append(chunk)
    return chunks or [text.strip()]


def segment_to_frames(segment: SpeechSegment) -> list[FramePlan]:
    duration = max(1, segment.end - segment.start)
    text = segment.text.strip()
    if not text:
        return []

    if duration <= MAX_SECONDS:
        return [FramePlan(start=segment.start, transcript=text)]

    count = max(2, math.ceil(duration / TARGET_SECONDS))
    while count > 1 and duration / count > MAX_SECONDS:
        count += 1
    while count > 1 and duration / count < MIN_SECONDS:
        count -= 1

    texts = split_text_chunks(text, count)
    if not texts:
        return []
    count = len(texts)
    step = duration / count
    frames: list[FramePlan] = []
    for index, chunk in enumerate(texts):
        start = segment.start + int(round(index * step))
        frames.append(FramePlan(start=start, transcript=chunk))
    return frames


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENTENCE_RE.split(text) if p.strip()]
    return parts if parts else [text.strip()]


def pack_frames(segments: list[SpeechSegment]) -> list[FramePlan]:
    frames: list[FramePlan] = []
    for segment in segments:
        frames.extend(segment_to_frames(segment))
    return frames


def write_plan(frames: list[FramePlan]) -> None:
    prefix = scene_prefix()
    lines: list[str] = []
    for frame in frames:
        scene = f"{prefix} illustrating: {frame.transcript[:100]}"
        lines.append(f"[{frame.timestamp}] {scene} | Transcript: {frame.transcript}")
    PLAN_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


@dataclass
class PlanRow:
    minute: int
    second: int
    scene: str
    transcript: str

    @property
    def timestamp(self) -> str:
        return f"{self.minute}:{self.second:02d}"

    @property
    def filename(self) -> str:
        return f"{self.minute}_{self.second:02d}.png"


def parse_plan_file() -> list[PlanRow]:
    rows: list[PlanRow] = []
    for line in PLAN_FILE.read_text(encoding="utf-8").splitlines():
        match = PLAN_LINE_RE.match(line)
        if not match:
            continue
        minute, second, scene, transcript = match.groups()
        rows.append(PlanRow(int(minute), int(second), scene, transcript))
    return rows


def render_bar(done: int, total: int, width: int = 24) -> str:
    if total == 0:
        return "[" + ("-" * width) + "] 0/0"
    filled = round((done / total) * width)
    return "[" + ("#" * filled) + ("-" * (width - filled)) + f"] {done}/{total}"


def _atomic_write_text(path: Path, text: str) -> None:
    """Write text to path atomically via a temp file in the same directory."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    """Write CSV to path atomically via a temp file in the same directory."""
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    _atomic_write_text(path, buf.getvalue())


def write_manifest(rows: list[PlanRow], audio_end: int) -> tuple[int, int, int]:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    existing = {path.name for path in IMAGES_DIR.glob("*.png")}

    csv_rows = []
    total_duration = 0
    for i, row in enumerate(rows):
        row_start = row.minute * 60 + row.second
        if i + 1 < len(rows):
            next_row = rows[i + 1]
            next_start = next_row.minute * 60 + next_row.second
        else:
            next_start = audio_end
        duration = next_start - row_start
        if duration <= 0:
            print(f"  WARN: non-positive duration ({duration}s) for {row.filename} — check transcript timestamps", file=sys.stderr)
            duration = 1
        if duration > 8:
            print(f"  WARN: {row.filename} spans {duration}s (unusually long — possible missing frame)", file=sys.stderr)
        total_duration += duration
        csv_rows.append({
            "timestamp": row.timestamp,
            "filename": row.filename,
            "scene": row.scene,
            "transcript": row.transcript,
            "status": "done" if row.filename in existing else "pending",
            "duration": duration,
        })

    drift = abs(total_duration - audio_end)
    if drift > 2:
        print(f"  WARN: frame timeline covers {total_duration}s but audio is {audio_end}s (drift={drift}s)", file=sys.stderr)

    _atomic_write_csv(MANIFEST_FILE, ["timestamp", "filename", "scene", "transcript", "status", "duration"], csv_rows)

    total = len(rows)
    done = sum(1 for row in rows if row.filename in existing)
    pending = total - done
    _atomic_write_text(
        PROGRESS_FILE,
        json.dumps(
            {
                "total_frames": total,
                "done_frames": done,
                "pending_frames": pending,
                "progress_bar": render_bar(done, total),
            },
            indent=2,
        )
        + "\n",
    )
    return total, done, pending


def refresh_progress() -> int:
    if not PLAN_FILE.is_file() and not MANIFEST_FILE.is_file():
        print("ERROR: No cut plan or manifest found — run build_plan.py first", file=sys.stderr)
        return 1

    rows = parse_plan_file()
    existing = {path.name for path in IMAGES_DIR.glob("*.png")}

    if MANIFEST_FILE.is_file():
        manifest_rows: list[dict[str, str]] = []
        with MANIFEST_FILE.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            has_duration = "duration" in (reader.fieldnames or [])
            for row in reader:
                row["status"] = "done" if row["filename"] in existing else "pending"
                manifest_rows.append(row)

        fieldnames = ["timestamp", "filename", "scene", "transcript", "status"]
        if has_duration:
            fieldnames.append("duration")
        _atomic_write_csv(MANIFEST_FILE, fieldnames, manifest_rows)

        total = len(manifest_rows)
        done = sum(1 for row in manifest_rows if row["status"] == "done")
    else:
        total, done, _ = write_manifest(rows, 0)

    pending = total - done
    _atomic_write_text(
        PROGRESS_FILE,
        json.dumps(
            {
                "total_frames": total,
                "done_frames": done,
                "pending_frames": pending,
                "progress_bar": render_bar(done, total),
            },
            indent=2,
        )
        + "\n",
    )
    print(render_bar(done, total))
    print(f"done={done} pending={pending}")
    return 0


def build_all() -> int:
    if not TRANSCRIPT_FILE.is_file():
        print(
            "ERROR: Missing 03-transcript/transcript.txt\n"
            "Get a timestamped export from https://turboscribe.com\n"
            "TurboScribe: Advanced Export → TXT with Section Timestamps (or export SRT)\n"
            "Formats: [0:00:05] line text  |  (0:00) inline  |  SRT subtitles",
            file=sys.stderr,
        )
        return 1

    duration = audio_seconds()
    audio_end = int(round(duration))
    text = TRANSCRIPT_FILE.read_text(encoding="utf-8").strip()
    segments, source = parse_transcript(text, audio_end)
    if source == "plain":
        print(
            "WARNING: No timestamps in transcript — using estimated timing (~2–3s/frame).\n"
            "Re-export from TurboScribe with Show Timestamps ON → Advanced Export → Section Timestamps.",
            file=sys.stderr,
        )
    frames = pack_frames(segments)
    write_plan(frames)

    durations = []
    for i, frame in enumerate(frames):
        next_start = frames[i + 1].start if i + 1 < len(frames) else audio_end
        durations.append(next_start - frame.start)

    avg = sum(durations) / len(durations) if durations else 0
    plan_rows = parse_plan_file()
    total, done, pending = write_manifest(plan_rows, audio_end)
    print(f"Wrote {PLAN_FILE} — {len(frames)} frames from {source} transcript")
    print(f"Wrote {MANIFEST_FILE} — {total} rows ({done} done, {pending} pending)")
    print(f"Audio ~{audio_end}s · avg frame duration {avg:.1f}s (target {TARGET_SECONDS}s, max {MAX_SECONDS}s)")
    print(render_bar(done, total))
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "refresh":
        return refresh_progress()
    return build_all()


if __name__ == "__main__":
    raise SystemExit(main())
