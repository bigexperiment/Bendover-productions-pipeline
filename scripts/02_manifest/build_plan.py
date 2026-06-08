#!/usr/bin/env python3
"""Build image_cut_plan.txt from a timestamped transcript (TurboScribe format).

Target ~2s per frame, intelligently up to 4s at natural speech breaks.
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from lib.audio_paths import COMBINED, COMBINED_NORMALIZED  # noqa: E402
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
MAX_SECONDS = 4

MARKER_RE = re.compile(r"\((\d+):(\d{2})\)")
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
    for candidate in (COMBINED_NORMALIZED, COMBINED):
        if candidate.is_file():
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
    raise FileNotFoundError("Run combine_mp3s.py first — need 02-audio/Combined.mp3")


def scene_prefix() -> str:
    if PROJECT_FILE.is_file():
        style = json.loads(PROJECT_FILE.read_text(encoding="utf-8")).get("image_style", "")
        if style:
            return style.split(",")[0].strip()
    return "Minimal explainer scene"


def parse_timestamped_transcript(text: str, audio_end: int) -> list[SpeechSegment]:
    matches = list(MARKER_RE.finditer(text))
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


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENTENCE_RE.split(text) if p.strip()]
    return parts if parts else [text.strip()]


def subsplit_segment(segment: SpeechSegment) -> list[SpeechSegment]:
    duration = segment.end - segment.start
    if duration <= MAX_SECONDS:
        return [segment]

    sentences = split_sentences(segment.text)
    if len(sentences) <= 1:
        mid = segment.start + duration // 2
        words = segment.text.split()
        if len(words) < 2:
            return [segment]
        half = len(words) // 2
        return [
            SpeechSegment(segment.start, mid, " ".join(words[:half])),
            SpeechSegment(mid, segment.end, " ".join(words[half:])),
        ]

    pieces: list[SpeechSegment] = []
    bucket: list[str] = []
    bucket_weight = 0
    total_weight = sum(len(s) for s in sentences) or 1
    cursor = segment.start

    for sentence in sentences:
        weight = len(sentence)
        bucket.append(sentence)
        bucket_weight += weight
        share = bucket_weight / total_weight
        projected_end = segment.start + round(duration * share)
        piece_duration = projected_end - cursor
        if piece_duration >= TARGET_SECONDS or sentence == sentences[-1]:
            end = min(segment.end, max(cursor + MIN_SECONDS, projected_end))
            if end <= cursor:
                end = min(segment.end, cursor + MIN_SECONDS)
            pieces.append(SpeechSegment(cursor, end, " ".join(bucket)))
            cursor = end
            bucket = []
            bucket_weight = 0

    if bucket:
        pieces.append(SpeechSegment(cursor, segment.end, " ".join(bucket)))

    return pieces or [segment]


def ends_cleanly(text: str) -> bool:
    return bool(re.search(r"[.!?][\"')\]]*$", text.strip()))


def pack_frames(segments: list[SpeechSegment]) -> list[FramePlan]:
    flat: list[SpeechSegment] = []
    for segment in segments:
        flat.extend(subsplit_segment(segment))

    frames: list[FramePlan] = []
    index = 0
    while index < len(flat):
        start = flat[index].start
        texts = [flat[index].text]
        end = flat[index].end
        cursor = index + 1

        while cursor < len(flat):
            duration = flat[cursor].end - start
            if duration > MAX_SECONDS:
                break
            next_text = " ".join(texts + [flat[cursor].text])
            candidate_end = flat[cursor].end
            duration = candidate_end - start

            if duration < MIN_SECONDS:
                texts.append(flat[cursor].text)
                end = candidate_end
                cursor += 1
                continue

            if duration <= MAX_SECONDS and (
                duration >= TARGET_SECONDS and ends_cleanly(next_text)
                or duration >= MAX_SECONDS
            ):
                texts.append(flat[cursor].text)
                end = candidate_end
                cursor += 1
                break

            if duration < TARGET_SECONDS:
                texts.append(flat[cursor].text)
                end = candidate_end
                cursor += 1
                continue

            break

        frames.append(FramePlan(start=start, transcript=" ".join(texts).strip()))
        index = cursor if cursor > index else index + 1

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


def write_manifest(rows: list[PlanRow]) -> tuple[int, int, int]:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    existing = {path.name for path in IMAGES_DIR.glob("*.png")}

    with MANIFEST_FILE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["timestamp", "filename", "scene", "transcript", "status"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "timestamp": row.timestamp,
                    "filename": row.filename,
                    "scene": row.scene,
                    "transcript": row.transcript,
                    "status": "done" if row.filename in existing else "pending",
                }
            )

    total = len(rows)
    done = sum(1 for row in rows if row.filename in existing)
    pending = total - done
    PROGRESS_FILE.write_text(
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
        encoding="utf-8",
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
            for row in csv.DictReader(handle):
                row["status"] = "done" if row["filename"] in existing else "pending"
                manifest_rows.append(row)

        with MANIFEST_FILE.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["timestamp", "filename", "scene", "transcript", "status"],
            )
            writer.writeheader()
            writer.writerows(manifest_rows)

        total = len(manifest_rows)
        done = sum(1 for row in manifest_rows if row["status"] == "done")
    else:
        total, done, _ = write_manifest(rows)

    pending = total - done
    PROGRESS_FILE.write_text(
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
        encoding="utf-8",
    )
    print(render_bar(done, total))
    print(f"done={done} pending={pending}")
    return 0


def build_all() -> int:
    if not TRANSCRIPT_FILE.is_file():
        print(
            "ERROR: Missing 03-transcript/transcript.txt\n"
            "Get a timestamped transcript from https://turboscribe.com\n"
            "Format: (0:00) First line. (0:04) Next line.",
            file=sys.stderr,
        )
        return 1

    duration = audio_seconds()
    audio_end = int(round(duration))
    text = TRANSCRIPT_FILE.read_text(encoding="utf-8").strip()
    segments = parse_timestamped_transcript(text, audio_end)
    frames = pack_frames(segments)
    write_plan(frames)

    durations = []
    for i, frame in enumerate(frames):
        next_start = frames[i + 1].start if i + 1 < len(frames) else audio_end
        durations.append(next_start - frame.start)

    avg = sum(durations) / len(durations) if durations else 0
    plan_rows = parse_plan_file()
    total, done, pending = write_manifest(plan_rows)
    print(f"Wrote {PLAN_FILE} — {len(frames)} frames from timestamped transcript")
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
