"""Build Codex image-generation prompts for video frames."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class FrameJob:
    timestamp: str
    filename: str
    scene: str
    transcript: str


def project_context(project: dict) -> tuple[str, str, str, str]:
    name = (project.get("name") or "Untitled video").strip()
    brief = (project.get("video_brief") or "").strip()
    if not brief:
        brief = (
            f'Educational YouTube explainer titled "{name}". '
            "Each frame is a still illustration synced to narration — "
            "not a standalone poster. Illustrate the idea being spoken at this moment."
        )
    style_short = (project.get("image_style") or "minimal cartoon explainer, 16:9").strip()
    style_guide = (project.get("style_guide") or "").strip()
    if not style_guide:
        style_guide = (
            f"{style_short}. "
            "Stick-figure or simple cartoon characters with bold outlines and flat colors. "
            "Clean 16:9 composition, 2–3 focal elements, uncluttered background. "
            "Readable on a phone. No photorealism, no watermarks, no logos."
        )
    tone = (project.get("tone") or "").strip()
    if not tone:
        tone = (
            "Informative but fun to watch — never boring. "
            "Light humor or dry sarcasm is fine when it helps the point land, "
            "but don't force a joke into every frame."
        )
    return name, brief, style_guide, tone


def build_frame_prompt(project: dict, job: FrameJob, root: Path, manifest_script: Path) -> str:
    name, brief, style_guide, tone = project_context(project)

    return f"""You are generating ONE frame for a narrated YouTube explainer video.

## Project
Title: {name}
{brief}

## Tone
{tone}

## What this frame is
- Frame #{job.filename} shown at {job.timestamp} in the final video
- The viewer hears narration while this still image is on screen
- Your job: make the spoken idea instantly clear — and interesting to look at

## Visual style (follow closely)
{style_guide}

## This moment in the narration
Timestamp: {job.timestamp}
Narrator says: "{job.transcript}"
Scene hint: {job.scene}

## Text in the image (sparingly)
- Prefer showing the idea visually — expression, symbols, action
- Text is optional, not default. Use only when a short label, sign, scroll heading,
  or coin inscription makes the joke or concept land faster
- If you use text: 1–4 words max, large and bold, part of the scene (sign, tablet,
  banner) — never a paragraph, never subtitles of the narration
- Skip text entirely if the scene already reads clearly without it

## Composition rules
- 16:9 landscape
- One clear story beat — what is happening and why it matters
- Max 2–3 main elements; simple background that supports the idea
- Entertaining and slightly witty when it fits — never dull, never try-hard silly
- No collage, no split panels, no tiny unreadable detail

## Output
- Use the built-in image_gen tool exactly once
- Save to: 05-images/{job.filename}
- After saving, verify the file exists at {root}/05-images/{job.filename}
- Run: python3 {manifest_script} refresh

Generate exactly one image. Do not create any other files.
"""
