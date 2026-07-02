"""Build Codex image-generation prompts for video frames.

Two layers of context feed each frame's prompt:
1. Full-video context — title, brief, and the whole narration script — so every
   frame is illustrated as one moment in a continuous story, not a standalone
   poster of its own 2-second transcript slice.
2. The shot plan (04-manifest/shot_plan.json, written by build_shot_plan.py) —
   a director's per-frame decision on shot type, recurring cast, and whether
   this particular frame is one of the sparing few that carries on-screen text.

If no shot plan exists yet (director step skipped or failed), frames fall back
to a plain illustrated scene with no on-screen text — the pipeline still works.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_IMAGE_STYLE = (
    "simple educational cartoon illustration, hand-drawn doodle animation style, "
    "thick black outlines, flat colors, minimal shading, stickman characters, "
    "round white heads, expressive faces, thin black limbs, simple YouTube explainer "
    "animation style, clean background, limited colors, humorous but clear."
)

DEFAULT_STYLE_GUIDE = """- Show only one main idea, with at most one supporting element — never a cluttered scene.
- Characters should have exaggerated emotions.
- Prefer visual storytelling: expressions, poses, ONE symbol or motion line at most — not a
  collage of arrows, icons, and impact stars all at once.
- Keep the background plain or empty. Do not fill it with scattered objects, icons, or props.
- Make it easy to understand in 1 second without reading.
- No realism, no cinematic lighting, no detailed textures, no 3D.
- If in doubt, remove elements rather than add them."""

DEFAULT_TEXT_RULES = """- Default: NO text — no speech bubbles, captions, subtitles, titles, or labels.
- The viewer hears narration; the image should not repeat or paraphrase it in writing.
- Use text only when absolutely necessary and the idea cannot be shown visually (rare).
- If you must use text: 1–3 words max, large and bold, part of the scene (sign, map label) — never a sentence.
- Never add text just for humor or emphasis when expression/action would work."""

TEXT_CARD_RULES = """- This frame IS a deliberate text card — the on-screen words below are the point of the frame.
- Render exactly those words, large and bold, as the dominant element, centered or clearly the focus.
- Keep any accompanying doodle small and secondary to the text.
- Do not add any other words beyond the exact text given."""

DEFAULT_TONE = (
    "Informative but fun to watch — never boring. "
    "Light humor or dry sarcasm is fine when it helps the point land, "
    "but don't force a joke into every frame."
)

SHOT_TYPE_HINTS = {
    "scene": "A normal illustrated moment — action, setting, or interaction.",
    "text_card": "Mostly bold on-screen text, with a small secondary doodle.",
    "diagram": "A simple split, comparison, or flow diagram — not a literal scene.",
    "closeup": "A tight shot on one character's face/reaction — no wide background.",
}


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


def text_rules(project: dict) -> str:
    custom = (project.get("text_rules") or "").strip()
    if custom.startswith("-"):
        return custom
    if custom:
        return custom
    return DEFAULT_TEXT_RULES


def project_brief(project: dict) -> tuple[str, str]:
    name = (project.get("name") or "Untitled video").strip()
    brief = (project.get("video_brief") or "").strip()
    if not brief:
        brief = (
            f'Educational YouTube explainer titled "{name}". '
            "Each frame is a still illustration synced to narration — "
            "not a standalone poster. Illustrate the idea being spoken at this moment."
        )
    return name, brief


def load_full_script(root: Path) -> str:
    path = root / "01-script" / "Script.txt"
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def load_shot_plan(root: Path) -> dict | None:
    path = root / "04-manifest" / "shot_plan.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    data["frames_by_filename"] = {
        frame["filename"]: frame for frame in data.get("frames") or [] if frame.get("filename")
    }
    return data


def build_video_context_block(project: dict, root: Path) -> str:
    name, brief = project_brief(project)
    script = load_full_script(root)
    lines = [f'Title: "{name}"', f"Brief: {brief}"]
    if script:
        lines.append(f"Full narration script (this frame is one moment inside this single continuous video):\n{script}")
    return "\n".join(lines)


def build_cast_block(shot_plan: dict | None, shot: dict | None) -> str:
    if not shot_plan or not shot_plan.get("cast"):
        return ""
    cast = shot_plan["cast"]
    here = set(shot.get("characters") or []) if shot else set()
    lines = [
        f"- {name}: {desc}" + ("  (appears in this frame)" if name in here else "")
        for name, desc in cast.items()
    ]
    return "Recurring cast (keep visually consistent with earlier frames):\n" + "\n".join(lines)


def build_scene_description(project: dict, job: FrameJob, root: Path, shot_plan: dict | None) -> str:
    tone = (project.get("tone") or DEFAULT_TONE).strip()
    shot = shot_plan["frames_by_filename"].get(job.filename) if shot_plan else None
    scene_text = (shot.get("scene") if shot else None) or job.scene
    shot_type = (shot.get("type") if shot else None) or "scene"

    parts = [
        build_video_context_block(project, root),
        "",
        f'At {job.timestamp}, narrator says: "{job.transcript}"',
        f"Shot type: {shot_type} — {SHOT_TYPE_HINTS.get(shot_type, '')}",
        f"Scene: {scene_text}",
        f"Tone: {tone}",
    ]
    cast_block = build_cast_block(shot_plan, shot)
    if cast_block:
        parts.append(cast_block)
    return "\n".join(p for p in parts if p)


def build_image_prompt_body(project: dict, scene: str, shot: dict | None) -> str:
    if shot and shot.get("text_on_screen"):
        rules = TEXT_CARD_RULES
        text_line = f"\nExact text to render: {shot['text_on_screen']}"
    else:
        rules = text_rules(project)
        text_line = ""

    return f"""Create a static cartoon scene in this style:

Style:
{image_style(project)}

Scene:
{scene}

Important:
{style_rules(project)}

Text (sparingly — default none):
{rules}{text_line}"""


def build_frame_prompt(project: dict, job: FrameJob, root: Path, manifest_script: Path) -> str:
    name, _ = project_brief(project)
    shot_plan = load_shot_plan(root)
    shot = shot_plan["frames_by_filename"].get(job.filename) if shot_plan else None
    scene = build_scene_description(project, job, root, shot_plan)
    body = build_image_prompt_body(project, scene, shot)

    reference_note = ""
    if (root / "04-manifest" / "cast_reference.png").is_file():
        reference_note = (
            "\nAn attached reference image shows the exact established look of the recurring "
            "cast. Any character from that reference who appears in this frame MUST be drawn "
            "with the same face, proportions, line weight, and flat coloring as shown there — "
            "copy their design, do not reinterpret it. This holds no matter how dramatic or "
            "abstract the scene is: never simplify a character into geometric shapes, silhouettes, "
            "or a different art style to fit a mood or effect. Effects (motion lines, fading "
            "silhouettes of OTHER things, sparkles, etc.) happen around the character, never to "
            "the character's own design."
        )

    return f"""{body}
{reference_note}
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
