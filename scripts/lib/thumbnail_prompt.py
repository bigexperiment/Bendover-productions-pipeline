"""YouTube thumbnail prompts — visual only; headline added by thumbnail_overlay.py."""
from __future__ import annotations

from pathlib import Path

from lib.image_prompt import image_style


def build_thumbnail_scene(project: dict, headline: str) -> str:
    title = (project.get("title") or project.get("name") or "").strip()

    return f"""YouTube thumbnail BACKGROUND ONLY — do NOT draw any letters, words, or typography.
Headline "{headline}" will be added in post-production.

YouTube title (never render as text): "{title}"

VISUAL (supports "fire isn't enough" — no spoilers):
- ONE prehistoric stickman kneeling by a campfire, staring at a large raw antelope haunch on the ground
- Puzzled/frustrated expression: fire is roaring but the meat is still uncooked and unchewable
- NO baby, NO feeding, NO spoon, NO mouth-to-mouth, NO text of any kind
- Bright hunter-gatherer camp: simple tent, blue sky, clean doodle style — thick black outlines, flat colors
- Leave the upper 35% of the frame relatively clear (sky/simple background) for text overlay
- 16:9 landscape, high contrast, click-worthy

FORBIDDEN: any written text, letters, numbers, labels, speech bubbles, watermarks, baby feeding scenes
"""


def build_thumbnail_prompt(project: dict, headline: str, out_path: Path, root: Path) -> str:
    scene = build_thumbnail_scene(project, headline)
    rel = out_path.relative_to(root)
    return f"""Create a YouTube thumbnail background (NO TEXT).

Style:
{image_style(project)}

Scene:
{scene}

Thumbnail output:
- Use the built-in image_gen tool exactly once
- 16:9 landscape (1280×720), no typography in the image
- Save to: {rel}
- After generating, ensure the file exists at {out_path}
- Do not generate any other files
"""
