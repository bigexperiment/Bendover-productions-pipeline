"""Build Codex image-generation prompts for video frames."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_IMAGE_STYLE = (
    "simple educational cartoon illustration, hand-drawn doodle animation style, "
    "thick black outlines, flat colors, minimal shading, stickman characters, "
    "round white heads, expressive faces, thin black limbs, simple YouTube explainer "
    "animation style, clean background, limited colors, humorous but clear."
)

DEFAULT_STYLE_GUIDE = """- Show only one main idea.
- Characters should have exaggerated emotions.
- Use arrows, labels, motion lines, or impact stars if helpful.
- Keep the background simple.
- Make it easy to understand in 1 second.
- No realism, no cinematic lighting, no detailed textures, no 3D."""

DEFAULT_TONE = (
    "Informative but fun to watch — never boring. "
    "Light humor or dry sarcasm is fine when it helps the point land, "
    "but don't force a joke into every frame."
)


@dataclass
class FrameJob:
    timestamp: str
    filename: str
    scene: str
    transcript: str


def image_style(project: dict) -> str:
    return (project.get("image_style") or DEFAULT_IMAGE_STYLE).strip()


def style_rules(project: dict) -> str:
    custom = (project.get("style_guide") or "").strip()
    if custom.startswith("-"):
        return custom
    if custom:
        return custom
    return DEFAULT_STYLE_GUIDE


def project_brief(project: dict) -> str:
    name = (project.get("name") or "Untitled video").strip()
    brief = (project.get("video_brief") or "").strip()
    if not brief:
        brief = (
            f'Educational YouTube explainer titled "{name}". '
            "Each frame is a still illustration synced to narration — "
            "not a standalone poster. Illustrate the idea being spoken at this moment."
        )
    return name, brief


def build_scene_description(project: dict, job: FrameJob) -> str:
    name, brief = project_brief(project)
    tone = (project.get("tone") or DEFAULT_TONE).strip()
    return (
        f'At {job.timestamp} in "{name}": {job.transcript}\n'
        f"Scene hint: {job.scene}\n"
        f"Tone: {tone}\n"
        f"Context: {brief}"
    )


def build_image_prompt_body(project: dict, scene: str) -> str:
    return f"""Create a static cartoon scene in this style:

Style:
{image_style(project)}

Scene:
{scene}

Important:
{style_rules(project)}"""


def build_frame_prompt(project: dict, job: FrameJob, root: Path, manifest_script: Path) -> str:
    name, _ = project_brief(project)
    scene = build_scene_description(project, job)
    body = build_image_prompt_body(project, scene)

    return f"""{body}

This is frame #{job.filename} for a narrated YouTube video.
Project: {name}
Timestamp: {job.timestamp}
Narrator says: "{job.transcript}"

Output:
- 16:9 landscape
- Use the built-in image_gen tool exactly once
- Save to: 05-images/{job.filename}
- After saving, verify the file exists at {root}/05-images/{job.filename}
- Run: python3 {manifest_script} refresh

Generate exactly one image. Do not create any other files.
"""
