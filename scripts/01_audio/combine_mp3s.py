from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.audio_paths import AUDIO_DIR, COMBINED, COMBINED_NORMALIZED, OUTPUT_NAMES  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PARTS = [PROJECT_ROOT / f"Part{i}.mp3" for i in range(1, 4)]
LIST_FILE = PROJECT_ROOT / "mp3_concat_list.txt"
TEMP_FILE = AUDIO_DIR / "Combined.tmp.mp3"
AUDIO_EXTS = {".mp3", ".wav", ".m4a"}


def normalize_to_output(source: Path, output: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(output),
        ],
        check=True,
    )


def concat_parts() -> None:
    lines = [f"file '{path.name}'" for path in PARTS]
    LIST_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(LIST_FILE),
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
                str(TEMP_FILE),
            ],
            check=True,
        )
        TEMP_FILE.replace(COMBINED)
    finally:
        if LIST_FILE.exists():
            LIST_FILE.unlink()
        if TEMP_FILE.exists():
            TEMP_FILE.unlink()


def single_audio_files() -> list[Path]:
    if not AUDIO_DIR.is_dir():
        return []
    return sorted(
        p
        for p in AUDIO_DIR.iterdir()
        if p.suffix.lower() in AUDIO_EXTS and p.name not in OUTPUT_NAMES
    )


def concat_singles(files: list[Path]) -> None:
    list_path = AUDIO_DIR / "mp3_concat_list.txt"
    lines = [f"file '{path.name}'" for path in files]
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
                str(TEMP_FILE),
            ],
            check=True,
            cwd=str(AUDIO_DIR),
        )
        TEMP_FILE.replace(COMBINED)
    finally:
        if list_path.exists():
            list_path.unlink()
        if TEMP_FILE.exists():
            TEMP_FILE.unlink()


def main() -> int:
    AUDIO_DIR.mkdir(exist_ok=True)
    if COMBINED_NORMALIZED.exists():
        COMBINED_NORMALIZED.unlink()

    if all(path.exists() for path in PARTS):
        concat_parts()
        print(f"Wrote {COMBINED} from Part1/2/3")
        return 0

    singles = single_audio_files()
    if len(singles) == 1:
        normalize_to_output(singles[0], COMBINED)
        print(f"Wrote {COMBINED} from {singles[0]}")
        return 0

    if len(singles) > 1:
        concat_singles(singles)
        print(f"Wrote {COMBINED} from {len(singles)} files in 02-audio/")
        return 0

    if COMBINED.is_file():
        print(f"{COMBINED} already exists")
        return 0

    missing = [p.name for p in PARTS if not p.exists()]
    raise FileNotFoundError(
        "No audio found. Add Part1/2/3.mp3 or one file in 02-audio/"
        + (f" (missing parts: {', '.join(missing)})" if missing else "")
    )


if __name__ == "__main__":
    sys.exit(main())
