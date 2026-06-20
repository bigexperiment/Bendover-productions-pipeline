"""Style presets from style-explore variants — used by Studio + image generation."""
from __future__ import annotations

import json
from pathlib import Path

from lib.folders import DIR_IMAGES
from lib.image_prompt import DEFAULT_IMAGE_STYLE

ROOT = Path(__file__).resolve().parents[2]
VARIANTS_FILE = ROOT / "scripts" / "03_images" / "style_explore_variants.json"
EXPLORE_DIR = DIR_IMAGES / "style-explore"

DEFAULT_PRESET_ID = "default"
DEFAULT_PRESET_LABEL = "Classic stick figure explainer"


def _default_preset() -> dict:
    return {
        "id": DEFAULT_PRESET_ID,
        "label": DEFAULT_PRESET_LABEL,
        "image_style": DEFAULT_IMAGE_STYLE,
        "scene": "",
        "preview": None,
        "has_preview": False,
    }


def load_variant_rows() -> list[dict]:
    if not VARIANTS_FILE.is_file():
        return []
    data = json.loads(VARIANTS_FILE.read_text(encoding="utf-8"))
    return data.get("variants") or []


def preset_from_variant(row: dict) -> dict:
    preset_id = str(row.get("id", "")).strip()
    filename = f"explore_{preset_id}.png"
    preview_rel = f"style-explore/{filename}"
    has_preview = (EXPLORE_DIR / filename).is_file()
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
