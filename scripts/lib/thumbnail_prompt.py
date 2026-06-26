"""YouTube thumbnail prompts — Codex renders scene + headline text in the image (no Pillow overlay)."""
from __future__ import annotations

from pathlib import Path

from lib.image_prompt import image_style


def _variant_scene(project: dict, variant: int) -> str:
    brief = (project.get("video_brief") or "").strip()
    ctx = f" Context: {brief[:200]}" if brief else ""
    if variant == 2:
        return (
            "Choice hook: two stickmen face a decision — left path looks bad (dark, red X symbol), "
            "right path looks good (bright, green checkmark). Character caught between both options, "
            f"worried expression.{ctx}"
        )
    if variant == 3:
        return (
            "Breakthrough hook: single stickman with a big AHA lightbulb moment — eyes wide open, "
            "huge smile, bright energy burst radiating outward. Discovery energy, upbeat and dynamic "
            f"composition.{ctx}"
        )
    # Variant 1 default
    return (
        "Pain/problem hook: main stickman character visibly struggling with the central problem — "
        "exaggerated distress, sweat drops, question marks floating around head, stressed expression. "
        f"Simple single-character composition, character dominant in frame.{ctx}"
    )


def build_thumbnail_scene(project: dict, headline: str, variant: int = 1) -> str:
    title = (project.get("title") or project.get("name") or "").strip()
    brief = (project.get("video_brief") or "").strip()
    if not brief:
        brief = f'Educational stickman explainer about: "{title}"'

    text = headline.strip().upper()
    scene_angle = _variant_scene(project, variant)

    return f"""YouTube thumbnail — draw the scene AND the headline text in one image.

HEADLINE (render as large text in the image — exact wording):
"{text}"

YouTube listing title (do NOT use this as the thumbnail text): "{title}"

TEXT RULES:
- Place headline in the TOP third, centered, clear of character faces
- Bold sans-serif, ALL CAPS, yellow letters with thick black outline
- Split to 2 lines if it reads better
- Readable at phone thumbnail size — high contrast
- Spell the headline exactly — do NOT paraphrase
- Do NOT use the full YouTube title as thumbnail text

VIDEO CONTEXT:
{brief}

THIS VARIATION (make it visually distinct from other variants):
{scene_angle}

COMPOSITION:
- 16:9 landscape, 1280×720
- Characters and action in the BOTTOM 55–60% only
- Headline text in the top — not overlapping faces

STYLE: stickman doodle explainer — thick black outlines, flat colors, exaggerated expressions

FORBIDDEN: UI boxes, title bars, lower-thirds, watermarks, speech bubbles, Pillow overlays
FORBIDDEN: realism, 3D, cinematic lighting, gore
"""


def build_thumbnail_prompt(
    project: dict, headline: str, out_path: Path, root: Path, *, variant: int = 1
) -> str:
    scene = build_thumbnail_scene(project, headline, variant=variant)
    rel = out_path.relative_to(root)
    return f"""Create a complete YouTube thumbnail (scene + headline text in the image).

Style:
{image_style(project)}

Scene:
{scene}

Thumbnail output:
- Use the built-in image_gen tool exactly once
- 16:9 landscape (1280×720)
- Include the headline text drawn into the artwork — do not leave text for post-production
- Save to: {rel}
- After generating, ensure the file exists at {out_path}
- Do not generate any other files
"""
