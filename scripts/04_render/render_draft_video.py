from __future__ import annotations

import argparse
import math
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from lib.audio_paths import find_narration_audio  # noqa: E402
from lib.folders import DIR_IMAGES as IMAGES_DIR, FINAL_MP4  # noqa: E402

DEFAULT_OUTPUT = FINAL_MP4


def timestamp_from_stem(stem: str) -> int:
    minutes, seconds = stem.split("_", 1)
    return int(minutes) * 60 + int(seconds)


def ordered_images() -> list[Path]:
    files = sorted(IMAGES_DIR.glob("*.png"), key=lambda path: timestamp_from_stem(path.stem))
    if not files:
        raise FileNotFoundError(f"No PNG files found in {IMAGES_DIR}")
    return files


def audio_duration_seconds(audio_file: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_file),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def build_segments(
    files: list[Path], limit: int | None, audio_file: Path
) -> tuple[list[tuple[Path, int]], float]:
    if limit is not None and limit <= 0:
        raise ValueError("Image limit must be greater than zero")
    if limit is not None and len(files) <= limit:
        raise ValueError(
            f"Need at least {limit + 1} images to infer the end time for the first {limit} images"
        )

    selected = files if limit is None else files[:limit]
    total_duration = audio_duration_seconds(audio_file)
    timeline: list[tuple[Path, int]] = []

    for index, image in enumerate(selected):
        start = timestamp_from_stem(image.stem)
        if index + 1 < len(selected):
            end = timestamp_from_stem(selected[index + 1].stem)
        elif limit is None:
            end = math.ceil(total_duration)
        else:
            end = timestamp_from_stem(files[limit].stem)
        duration = end - start
        if duration <= 0:
            raise ValueError(f"Non-positive duration detected for {image.name}")
        timeline.append((image, duration))

    return timeline, total_duration


def render_video(
    timeline: list[tuple[Path, int]],
    total_duration: float,
    output_file: Path,
    audio_file: Path,
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
        concat_path = Path(handle.name)
        for image, duration in timeline:
            handle.write(f"file '{image.resolve()}'\n")
            handle.write(f"duration {duration}\n")
        # Repeat the last file so concat demuxer honors the final duration.
        handle.write(f"file '{timeline[-1][0].resolve()}'\n")

    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-i",
            str(audio_file),
            "-t",
            str(total_duration),
            "-vf",
            "scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-pix_fmt",
            "yuv420p",
            "-shortest",
            str(output_file),
        ]
        subprocess.run(cmd, check=True)
    finally:
        concat_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a draft MP4 from timestamped images and 02-audio/ narration."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Number of timestamped images to include from the start of the sequence. Omit to use all images.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "full_timed_images.mp4",
        help="Destination MP4 path.",
    )
    parser.add_argument(
        "--audio",
        type=Path,
        default=None,
        help="Audio track to mux. Defaults to the single file in 02-audio/.",
    )
    args = parser.parse_args()

    audio_file = args.audio or find_narration_audio()
    if not audio_file.exists():
        raise FileNotFoundError(f"Missing audio file: {audio_file}")

    files = ordered_images()
    timeline, total_duration = build_segments(files, args.limit, audio_file)
    render_video(timeline, total_duration, args.output, audio_file)
    image_count = len(timeline)
    mode = f"first {args.limit}" if args.limit is not None else "all"
    print(f"Rendered {args.output} using {mode} images ({image_count} total) through {total_duration:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
