"""Thumbnail compose: video frame → 16:9 crop → headline overlay."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

THUMB_SIZE = (1280, 720)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/Supplemental/Impact.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    )
    for path in candidates:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _split_lines(headline: str) -> list[str]:
    words = headline.upper().split()
    if len(words) <= 3:
        return [" ".join(words)]
    mid = (len(words) + 1) // 2
    return [" ".join(words[:mid]), " ".join(words[mid:])]


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _top_gradient(width: int, height: int) -> Image.Image:
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    band = int(height * 0.32)
    for y in range(band):
        alpha = int(200 * (1 - y / band) ** 1.2)
        draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    return layer


def compose_from_frame(frame_path: Path, out_path: Path, headline: str) -> None:
    """Crop a real video frame to 1280×720 and overlay headline — matches video style."""
    tw, th = THUMB_SIZE
    src = Image.open(frame_path).convert("RGBA")
    src_ratio = src.width / src.height
    tgt_ratio = tw / th

    if src_ratio > tgt_ratio:
        new_h = th
        new_w = int(th * src_ratio)
    else:
        new_w = tw
        new_h = int(tw / src_ratio)

    resized = src.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - tw) // 2
    top = (new_h - th) // 2
    canvas = resized.crop((left, top, left + tw, top + th))
    canvas = Image.alpha_composite(canvas, _top_gradient(tw, th))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, format="PNG")
    overlay_headline(out_path, headline)


def overlay_headline(image_path: Path, headline: str) -> None:
    headline = headline.strip().upper()
    if not headline:
        return

    img = Image.open(image_path).convert("RGBA")
    width, height = img.size
    lines = _split_lines(headline)

    font_size = int(height * 0.11)
    font = _load_font(font_size)
    draw = ImageDraw.Draw(img)

    line_heights = []
    line_widths = []
    for line in lines:
        w, h = _text_size(draw, line, font)
        line_widths.append(w)
        line_heights.append(h)

    gap = int(font_size * 0.15)
    block_h = sum(line_heights) + gap * (len(lines) - 1)
    max_w = max(line_widths)
    y = int(height * 0.08)

    for i, line in enumerate(lines):
        x = (width - line_widths[i]) // 2
        # Thick outline
        for ox, oy in (
            (-4, -4), (-4, 0), (-4, 4), (0, -4), (0, 4), (4, -4), (4, 0), (4, 4),
            (-3, -3), (3, 3), (-3, 3), (3, -3),
        ):
            draw.text((x + ox, y + oy), line, font=font, fill=(0, 0, 0, 255))
        # Shadow
        draw.text((x + 3, y + 3), line, font=font, fill=(255, 140, 0, 220))
        # Fill
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_heights[i] + gap

    img.convert("RGB").save(image_path, format="PNG")
