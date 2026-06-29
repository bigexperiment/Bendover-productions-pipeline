"""Central loader for secrets.json at the repo root."""
from __future__ import annotations

import json
from pathlib import Path

SECRETS_FILE = Path(__file__).resolve().parents[2] / "secrets.json"


def load() -> dict:
    if not SECRETS_FILE.is_file():
        return {}
    return json.loads(SECRETS_FILE.read_text(encoding="utf-8"))


def get(*keys: str, default=None):
    """Read a nested key path, e.g. get('supabase', 'url')."""
    d = load()
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


def save(data: dict) -> None:
    SECRETS_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def update(**top_level_patches) -> None:
    """Merge top-level keys into secrets.json."""
    data = load()
    data.update(top_level_patches)
    save(data)


def update_nested(section: str, patches: dict) -> None:
    """Merge keys into a nested section, e.g. update_nested('supabase', {...})."""
    data = load()
    data.setdefault(section, {}).update(patches)
    save(data)
