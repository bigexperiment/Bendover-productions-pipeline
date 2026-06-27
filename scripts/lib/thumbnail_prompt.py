"""YouTube thumbnail prompts — Codex renders scene + headline text in the image (no Pillow overlay)."""
from __future__ import annotations

from pathlib import Path


# Variant expressions: one face, one emotion, nothing else
_VARIANT_EXPRESSION = {
    1: "OVERWHELMED — eyes bugged wide, hands pressed to sides of head, mouth open in a silent scream. Pure panic.",
    2: "EXHAUSTED — heavy drooping eyelids, slumped shoulders, one hand propping up the chin. Can't escape the thoughts.",
    3: "DESPERATE — reaching one hand upward toward a glowing lightbulb just out of reach, face full of longing.",
}


def _variant_scene(variant: int) -> str:
    return _VARIANT_EXPRESSION.get(variant, _VARIANT_EXPRESSION[1])


def build_thumbnail_scene(project: dict, headline: str, variant: int = 1) -> str:
    text = headline.strip().upper()
    expression = _variant_scene(variant)

    return f"""YouTube thumbnail. ONE character. ONE emotion. Nothing else.

HEADLINE TEXT (draw this into the image — exact wording, no changes):
"{text}"

CHARACTER:
- Single stickman/cartoon figure, HUGE — fills the bottom 60% of the frame
- Centered horizontally
- Expression: {expression}
- Thick black outlines, bold and graphic
- ONE accent color on the character (bright orange or electric blue) — everything else is black, white, or one neutral

BACKGROUND:
- Solid flat color — cream, white, or very light grey
- Absolutely nothing in the background — no textures, no details, no environment, no objects
- The character and text are the ONLY things in the image

TEXT:
- Headline in the TOP 30% of the frame
- Massive, bold sans-serif ALL CAPS
- Yellow letters with thick black outline — readable at postage-stamp size
- 2 lines max — break it naturally if needed
- Spell it exactly: {text}

COMPOSITION RULES — STRICT:
- If you want to add anything beyond character + background + headline text: DON'T
- No sweat drops, no floating symbols, no speech bubbles, no secondary characters
- No environment, no props, no decorative elements
- Negative space is your friend — emptiness makes the character pop
- Think: magazine cover, not illustration

SIZE CHECK: imagine this at 120×67px on a phone. If any detail disappears at that size, remove it.

FORBIDDEN: multiple characters, busy backgrounds, small details, labels, watermarks, borders, gradients, textures, realism, 3D
"""


def build_thumbnail_prompt(
    project: dict, headline: str, out_path: Path, root: Path, *, variant: int = 1
) -> str:
    scene = build_thumbnail_scene(project, headline, variant=variant)
    rel = out_path.relative_to(root)
    return f"""Create a YouTube thumbnail. Simple, bold, readable at thumbnail size.

{scene}

Output:
- Use the built-in image_gen tool exactly once
- 16:9 landscape (1280×720)
- Save to: {rel}
- Do not generate any other files
"""
