#!/usr/bin/env python3
"""YouTube thumbnail generator — fast local version using ffmpeg + PIL.

Extracts a frame from the rendered video, scales to 1280×720,
and burns in the headline text with a styled overlay.

3 variants pick frames at different timestamps for variety.

project.json:
  thumbnail_text  — headline (required, ≠ title)

Add --ai flag to use the original Codex image-generation path instead.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get("PIPELINE_ROOT") or SCRIPTS_ROOT)
sys.path.insert(0, str(SCRIPTS_ROOT / "scripts"))
from lib.folders import DIR_UPLOAD, DIR_OUTPUT, DIR_THUMBS, FINAL_MP4  # noqa: E402

PROJECT_FILE = ROOT / "project.json"
THUMB_W, THUMB_H = 1280, 720
CONDA_PYTHON = "/Users/ganesh/miniconda3/bin/python3"


def load_project() -> dict:
    if PROJECT_FILE.is_file():
        return json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    return {}


def resolve_headline(project: dict, headline_arg: str | None) -> str | None:
    headline = (headline_arg or project.get("thumbnail_text") or "").strip()
    if not headline:
        return None
    title = (project.get("title") or project.get("name") or "").strip()
    if title and headline.lower() == title.lower():
        print("ERROR: thumbnail_text must differ from YouTube title", file=sys.stderr)
        return None
    return headline


def get_video_duration(video_path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 10.0


def extract_frame(video_path: Path, timestamp: float, out_png: Path) -> bool:
    """Extract a single frame from the video at the given timestamp."""
    result = subprocess.run(
        ["ffmpeg", "-ss", str(timestamp), "-i", str(video_path),
         "-vf", f"scale={THUMB_W}:{THUMB_H}:force_original_aspect_ratio=increase,crop={THUMB_W}:{THUMB_H}",
         "-frames:v", "1", "-q:v", "2", str(out_png), "-y"],
        capture_output=True, text=True,
    )
    return result.returncode == 0 and out_png.is_file()


# Inline PIL text-overlay script run under conda python (which has Pillow)
_PIL_SCRIPT = r"""
import sys, json
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

args = json.loads(sys.argv[1])
img_path = args["img"]
out_path = args["out"]
text     = args["text"].upper()

img = Image.open(img_path).convert("RGB")
W, H = img.size
draw = ImageDraw.Draw(img)

# Try to load a bold system font; fall back to default
font_candidates = [
    "/System/Library/Fonts/Supplemental/Verdana Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
]
font_size = max(60, W // 14)
font = None
for fc in font_candidates:
    try:
        font = ImageFont.truetype(fc, font_size)
        break
    except Exception:
        pass
if font is None:
    font = ImageFont.load_default()

# Wrap text to fit width
words = text.split()
lines, line = [], []
for w in words:
    test = " ".join(line + [w])
    bbox = draw.textbbox((0, 0), test, font=font)
    if bbox[2] - bbox[0] > W - 80 and line:
        lines.append(" ".join(line))
        line = [w]
    else:
        line.append(w)
if line:
    lines.append(" ".join(line))

# Measure total text block
line_h = int(font_size * 1.25)
block_h = line_h * len(lines) + 20
pad = 24

# Dark gradient strip at bottom
strip_top = H - block_h - pad * 2
for y in range(strip_top, H):
    alpha = min(1.0, (y - strip_top) / (H - strip_top) * 1.8)
    overlay = Image.new("RGBA", (W, 1), (0, 0, 0, int(alpha * 200)))
    img.paste(Image.new("RGB", (W, 1), (0, 0, 0)),
              (0, y),
              overlay)

# Draw text lines centered
y = strip_top + pad
for ln in lines:
    bbox = draw.textbbox((0, 0), ln, font=font)
    tw = bbox[2] - bbox[0]
    x = (W - tw) // 2
    # Shadow
    draw.text((x + 3, y + 3), ln, font=font, fill=(0, 0, 0, 180))
    draw.text((x, y), ln, font=font, fill=(255, 255, 255))
    y += line_h

img.save(out_path, format="PNG")
print(f"Saved: {out_path}")
"""


def add_text_overlay(frame_png: Path, out_path: Path, text: str) -> bool:
    """Run PIL text overlay via conda python (which has Pillow)."""
    import tempfile, json as _json
    script_file = Path(tempfile.mktemp(suffix=".py"))
    script_file.write_text(_PIL_SCRIPT, encoding="utf-8")
    args = _json.dumps({"img": str(frame_png), "out": str(out_path), "text": text})
    try:
        result = subprocess.run(
            [CONDA_PYTHON, str(script_file), args],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            return False
        return out_path.is_file()
    finally:
        script_file.unlink(missing_ok=True)


def generate_fast(project: dict, headline: str, out_path: Path, variant: int) -> int:
    """Fast path: frame extract + PIL text overlay. No AI credits."""
    # Find the rendered video
    video = FINAL_MP4
    if not video.is_file():
        # Fall back to any mp4 in 06-output
        candidates = list(DIR_OUTPUT.glob("*.mp4")) if DIR_OUTPUT.is_dir() else []
        if not candidates:
            print("ERROR: No final.mp4 found — run render first", file=sys.stderr)
            return 1
        video = candidates[0]

    duration = get_video_duration(video)
    # Pick timestamp: variant 1=30%, 2=55%, 3=15% — different frames for visual variety
    pcts = {1: 0.30, 2: 0.55, 3: 0.15}
    ts = max(0.5, duration * pcts.get(variant, 0.30))

    print(f"Variant {variant}: extracting frame at {ts:.1f}s from {video.name}…", flush=True)

    import tempfile
    frame_tmp = Path(tempfile.mktemp(suffix=".png"))
    try:
        if not extract_frame(video, ts, frame_tmp):
            print("ERROR: ffmpeg frame extraction failed", file=sys.stderr)
            return 1

        print(f"Adding text overlay: {headline!r}…", flush=True)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if not add_text_overlay(frame_tmp, out_path, headline):
            print("ERROR: text overlay failed", file=sys.stderr)
            return 1

        size_kb = out_path.stat().st_size // 1024
        print(f"Thumbnail saved: {out_path.name} ({size_kb} KB)")
        return 0
    finally:
        frame_tmp.unlink(missing_ok=True)


def generate_via_codex(project: dict, headline: str, out_path: Path, variant: int) -> int:
    """Slow AI path: Codex image generation. Use --ai flag to enable."""
    from lib.thumbnail_prompt import build_thumbnail_prompt  # noqa: E402
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    command = [
        "codex", "exec", "--enable", "image_generation",
        "-s", "workspace-write",
        "--dangerously-bypass-approvals-and-sandbox",
        "-C", str(ROOT),
        build_thumbnail_prompt(project, headline, out_path, ROOT, variant=variant),
    ]
    result = subprocess.run(command, stdin=subprocess.DEVNULL, cwd=ROOT,
                            env=env, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout); print(result.stderr, file=sys.stderr)
        return result.returncode
    if not out_path.is_file():
        print(f"ERROR: Expected thumbnail at {out_path}", file=sys.stderr)
        return 1
    return 0


def parse_args():
    headline_arg = None
    out_path = DIR_THUMBS / "thumbnail_v1.png"
    variant = 1
    use_ai = False
    for arg in sys.argv[1:]:
        if arg.startswith("--headline="):
            headline_arg = arg.split("=", 1)[1].strip()
        elif arg.startswith("--output="):
            out_path = ROOT / arg.split("=", 1)[1].strip()
        elif arg.startswith("--variant="):
            variant = int(arg.split("=", 1)[1].strip())
            out_path = DIR_THUMBS / f"thumbnail_v{variant}.png"
        elif arg == "--ai":
            use_ai = True
    return headline_arg, out_path, variant, use_ai


def main() -> int:
    headline_arg, out_path, variant, use_ai = parse_args()
    project = load_project()
    headline = resolve_headline(project, headline_arg)
    if not headline:
        print("ERROR: Set thumbnail_text in project.json (2–5 words, not the full title)",
              file=sys.stderr)
        return 1

    if use_ai:
        print(f"Generating variant {variant} via Codex ({headline!r}) → {out_path.name}…", flush=True)
        return generate_via_codex(project, headline, out_path, variant)
    else:
        return generate_fast(project, headline, out_path, variant)


if __name__ == "__main__":
    raise SystemExit(main())
