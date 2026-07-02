"""YouTube thumbnail prompts — Codex renders scene + headline text in the image (no Pillow overlay).

Reuses the video's own cast (from the shot plan / cast reference sheet) so the thumbnail
character matches the video instead of being a generic unrelated stickman, but always as
a fresh, high-impact pose designed for thumbnail size — never a screenshot of the video.
"""
from __future__ import annotations

import json
from pathlib import Path


# Variant emotions: proven high-CTR thumbnail expressions, applied to the video's own cast
_VARIANT_EXPRESSION = {
    1: "SHOCKED — eyes bugged wide, jaw dropped, one hand frozen mid-gesture as if just caught off guard by what they learned.",
    2: "SUSPICIOUS — narrowed eyes, head tilted, one eyebrow raised, studying something warily.",
    3: "TRIUMPHANT — big confident grin, one fist raised, like they just figured out something everyone else missed.",
}


def _variant_scene(variant: int) -> str:
    return _VARIANT_EXPRESSION.get(variant, _VARIANT_EXPRESSION[1])


def load_cast(root: Path) -> dict[str, str]:
    shot_plan_path = root / "04-manifest" / "shot_plan.json"
    if not shot_plan_path.is_file():
        return {}
    try:
        data = json.loads(shot_plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get("cast") or {}


def build_thumbnail_scene(project: dict, headline: str, variant: int, cast: dict[str, str]) -> str:
    text = headline.strip().upper()
    expression = _variant_scene(variant)
    brief = (project.get("video_brief") or "").strip()

    if cast:
        # Rotate through the cast across variants so multiple thumbnails don't all
        # feature the same character.
        names = list(cast)
        name = names[(variant - 1) % len(names)]
        cast_line = (
            f"Feature {name} from the attached reference image — {cast[name]}. "
            f"Draw {name} in the SAME established design (same colors, proportions, "
            "outfit) as the reference, but in a brand new pose and expression made for "
            "this thumbnail. Do not copy a pose from the reference or reuse any existing "
            "frame — this must be a new illustration."
        )
    else:
        cast_line = "Single stickman/cartoon figure — invent one consistent with the video's style."

    return f"""YouTube thumbnail. ONE character. ONE emotion. Nothing else.

VIDEO CONTEXT (use this to make the character's reaction feel earned, not generic):
{brief or "(no brief provided)"}

HEADLINE TEXT (draw this into the image — exact wording, no changes):
"{text}"

CHARACTER:
{cast_line}
- HUGE — fills the bottom 60% of the frame, centered horizontally
- Expression: {expression}
- Thick black outlines, bold and graphic

BACKGROUND:
- Solid flat color — cream, white, or very light grey
- You MAY add exactly ONE simple graphic element that hints at the video's hook (e.g. one
  bold silhouette, icon, or shape tied to the story) — large, flat-colored, low-detail,
  positioned so it doesn't collide with the character or text. This is optional, not
  required — skip it if the character's pose already tells the story on its own.
- No more than one such element. No textures, no clutter, no realistic detail on it.
- The background must still read instantly — it supports the character, never competes with it.

TEXT:
- Headline in the TOP 30% of the frame
- Massive, bold sans-serif ALL CAPS
- Yellow letters with thick black outline — readable at postage-stamp size
- 2 lines max — break it naturally if needed
- Spell it exactly: {text}

COMPOSITION RULES — STRICT:
- Character + text are the priority; at most one background element supports them — nothing more
- No sweat drops, no floating symbols, no speech bubbles, no secondary characters
- No busy environments, no prop clutter, no decorative flourishes
- Think: magazine cover with one strong graphic accent, not a bare void and not an illustration

SIZE CHECK: imagine this at 120×67px on a phone. If any detail disappears at that size, remove it.

FORBIDDEN: multiple characters, busy backgrounds, more than one background element, small details, labels, watermarks, borders, gradients, textures, realism, 3D
"""


def build_thumbnail_prompt(
    project: dict, headline: str, out_path: Path, root: Path, *, variant: int = 1
) -> str:
    cast = load_cast(root)
    scene = build_thumbnail_scene(project, headline, variant, cast)
    rel = out_path.relative_to(root)

    reference_note = ""
    if cast and (root / "04-manifest" / "cast_reference.png").is_file():
        reference_note = (
            "\nAn attached reference image shows this video's established cast — match "
            "the featured character's design exactly (same colors, proportions, outfit), "
            "just in a new pose and expression as described above."
        )

    return f"""Create a YouTube thumbnail. Simple, bold, readable at thumbnail size.

{scene}
{reference_note}

Output:
- Use the built-in image_gen tool exactly once
- 16:9 landscape (1280x720)
- Save to: {rel}
- After saving, verify the file exists at {out_path}
- Do not generate any other files
"""
