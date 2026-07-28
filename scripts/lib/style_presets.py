"""Style presets from style-explore variants — used by Studio + image generation."""
from __future__ import annotations

import json
from pathlib import Path

from lib.folders import DIR_STYLE_SAMPLES, STYLE_SAMPLES_VARIANTS
from lib.image_prompt import DEFAULT_IMAGE_STYLE

DEFAULT_PRESET_ID = "default"
DEFAULT_PRESET_LABEL = "Classic stick figure explainer"
PREVIEW_URL_PREFIX = "assets/style-samples"

# Selecting this preset in the Studio UI only writes style_guide when "scene"
# is non-empty (see serve.py's set-style handler) — an empty string here left
# preflight.py's required style_guide check permanently unsatisfiable for
# anyone picking the default preset. Ship a real baseline guide instead.
DEFAULT_SCENE_GUIDE = (
    "- Show only one main idea, with at most one supporting element — never a cluttered scene.\n"
    "- Characters should have exaggerated emotions.\n"
    "- Prefer visual storytelling: expressions, poses, ONE symbol or motion line at most — "
    "not a collage of arrows, icons, and impact stars all at once.\n"
    "- Keep the background plain or empty. Do not fill it with scattered objects, icons, or props.\n"
    "- Make it easy to understand in 1 second without reading.\n"
    "- No realism, no cinematic lighting, no detailed textures, no 3D.\n"
    "- If in doubt, remove elements rather than add them."
)


def _default_preset() -> dict:
    return {
        "id": DEFAULT_PRESET_ID,
        "label": DEFAULT_PRESET_LABEL,
        "image_style": DEFAULT_IMAGE_STYLE,
        "scene": DEFAULT_SCENE_GUIDE,
        "preview": None,
        "has_preview": False,
    }


def load_variant_rows() -> list[dict]:
    if not STYLE_SAMPLES_VARIANTS.is_file():
        return []
    data = json.loads(STYLE_SAMPLES_VARIANTS.read_text(encoding="utf-8"))
    return data.get("variants") or []


def preset_from_variant(row: dict) -> dict:
    preset_id = str(row.get("id", "")).strip()
    filename = f"explore_{preset_id}.png"
    preview_rel = f"{PREVIEW_URL_PREFIX}/{filename}"
    has_preview = (DIR_STYLE_SAMPLES / filename).is_file()
    return {
        "id": preset_id,
        "label": row.get("label") or f"Style {preset_id}",
        "image_style": (row.get("image_style") or "").strip(),
        "scene": (row.get("scene") or "").strip(),
        "preview": preview_rel if has_preview else None,
        "has_preview": has_preview,
    }


def load_style_presets(include_default: bool = True) -> list[dict]:
    presets: list[dict] = []
    if include_default:
        presets.append(_default_preset())
    for row in load_variant_rows():
        if not row.get("id") or not row.get("image_style"):
            continue
        presets.append(preset_from_variant(row))
    return presets


def get_style_preset(preset_id: str | None) -> dict | None:
    if not preset_id:
        return None
    for preset in load_style_presets(include_default=True):
        if preset["id"] == preset_id:
            return preset
    return None


def apply_style_preset(project: dict) -> dict:
    """Resolve image_style + label from style_preset_id when set."""
    preset_id = project.get("style_preset_id")
    if not preset_id:
        return project
    preset = get_style_preset(str(preset_id))
    if not preset:
        return project
    updated = {**project}
    updated["style_preset_id"] = preset["id"]
    updated["style_preset_label"] = preset["label"]
    updated["image_style"] = preset["image_style"]
    return updated
