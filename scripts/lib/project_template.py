"""Default and reset templates for project.json."""
from __future__ import annotations

from lib.image_prompt import DEFAULT_IMAGE_STYLE, DEFAULT_STYLE_GUIDE, DEFAULT_TEXT_RULES, DEFAULT_TONE

STYLE_PERSIST_KEYS = (
    "image_style",
    "style_guide",
    "text_rules",
    "tone",
    "workers",
    "privacy",
)

DEFAULT_WORKERS = 5
DEFAULT_PRIVACY = "public"


def default_style_prefs() -> dict:
    return {
        "image_style": DEFAULT_IMAGE_STYLE,
        "style_guide": DEFAULT_STYLE_GUIDE,
        "text_rules": DEFAULT_TEXT_RULES,
        "tone": DEFAULT_TONE,
        "workers": DEFAULT_WORKERS,
        "privacy": DEFAULT_PRIVACY,
    }


def reset_project_dict(current: dict | None = None) -> dict:
    """Blank project for a new video — keeps image/style prefs across cleanup."""
    current = current or {}
    style = default_style_prefs()
    for key in STYLE_PERSIST_KEYS:
        value = current.get(key)
        if value not in (None, ""):
            style[key] = value

    return {
        "name": "",
        "step": "setup",
        "title": "",
        "description": "",
        "tags": [],
        "video_brief": "",
        "style_approved": False,
        "youtube_video_id": None,
        **style,
    }
