"""Named YouTube channels — all state lives in the central secrets.json.

Everything sits under the top-level "youtube" key:

    "youtube": {
      "app": { "installed": { client_id, client_secret, auth_uri, token_uri, ... } },
      "channels": {
        "the-hidden-epoch": {
          "name", "title", "channel_id", "custom_url", "thumbnail",
          "published_at", "subscribers", "video_count", "view_count",
          "hidden_subscribers", "stats_updated", "pending",
          "token": { ...OAuth authorized-user JSON (the secret)... }
        },
        ...
      }
    }

One OAuth app ("app") is reused to log into every channel; each channel keeps its
own "token". No credential files on disk — one place, secrets.json.
"""
from __future__ import annotations

import re
import time

from lib import secrets as _secrets

STANDARD_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
STANDARD_TOKEN_URI = "https://oauth2.googleapis.com/token"

_META_KEYS = (
    "slug", "name", "title", "channel_id", "custom_url", "description",
    "thumbnail", "published_at", "subscribers", "hidden_subscribers",
    "video_count", "view_count", "stats_updated", "pending",
)


# ── low-level secrets access ──────────────────────────────────────────────────

def _load() -> dict:
    return _secrets.load()


def _channels(data: dict | None = None) -> dict:
    data = data if data is not None else _load()
    return (data.get("youtube") or {}).get("channels") or {}


def _write_channel(slug: str, entry: dict) -> None:
    data = _load()
    yt = dict(data.get("youtube") or {})
    ch = dict(yt.get("channels") or {})
    ch[slug] = entry
    yt["channels"] = ch
    data["youtube"] = yt
    _secrets.save(data)


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return s or "channel"


# ── OAuth app (shared) ────────────────────────────────────────────────────────

def app_client_config() -> dict:
    """The Google OAuth app config used to log into every channel, in the
    google-auth client-config shape ({"installed": {...}})."""
    app = _secrets.get("youtube", "app", default=None)
    if isinstance(app, dict) and app:
        return app
    # Fall back to flat client_id/client_secret in the youtube section.
    cid = _secrets.get("youtube", "client_id")
    cs = _secrets.get("youtube", "client_secret")
    if cid and cs:
        return {"installed": {
            "client_id": cid,
            "client_secret": cs,
            "project_id": _secrets.get("youtube", "project_id") or "",
            "auth_uri": STANDARD_AUTH_URI,
            "token_uri": STANDARD_TOKEN_URI,
            "redirect_uris": ["http://localhost"],
        }}
    return {}


def has_app() -> bool:
    cfg = app_client_config()
    inner = next(iter(cfg.values()), {}) if cfg else {}
    return bool(inner.get("client_id") and inner.get("client_secret"))


# ── channel CRUD ──────────────────────────────────────────────────────────────

def exists(slug: str) -> bool:
    return slug in _channels()


def read_meta(slug: str) -> dict:
    entry = _channels().get(slug) or {}
    return {k: v for k, v in entry.items() if k != "token"}


def write_meta(slug: str, patch: dict) -> None:
    entry = dict(_channels().get(slug) or {})
    entry.update(patch)
    _write_channel(slug, entry)


def get_token(slug: str) -> dict | None:
    entry = _channels().get(slug) or {}
    tok = entry.get("token")
    return tok if isinstance(tok, dict) else None


def set_token(slug: str, token: dict) -> None:
    entry = dict(_channels().get(slug) or {})
    entry["token"] = token
    entry["token_invalid"] = False  # a fresh token clears any expired state
    _write_channel(slug, entry)


def has_token(slug: str) -> bool:
    return get_token(slug) is not None


def create(name: str) -> str:
    slug = slugify(name)
    if not exists(slug):
        _write_channel(slug, {"slug": slug, "name": name})
    else:
        write_meta(slug, {"name": name})
    return slug


def create_pending() -> str:
    """Create an unnamed channel with a unique placeholder slug; its real name is
    filled in from the YouTube API after login."""
    base = f"channel-{int(time.time())}"
    slug, n = base, 1
    existing = _channels()
    while slug in existing:
        n += 1
        slug = f"{base}-{n}"
    _write_channel(slug, {"slug": slug, "name": "New channel", "pending": True})
    return slug


def delete(slug: str) -> bool:
    data = _load()
    yt = dict(data.get("youtube") or {})
    ch = dict(yt.get("channels") or {})
    if slug in ch:
        del ch[slug]
        yt["channels"] = ch
        data["youtube"] = yt
        _secrets.save(data)
        return True
    return False


def info(slug: str) -> dict:
    meta = read_meta(slug)
    return {
        "slug": slug,
        "name": meta.get("name") or slug,
        "title": meta.get("title") or "",
        "channel_id": meta.get("channel_id") or "",
        "authorized": has_token(slug),
        "token_invalid": bool(meta.get("token_invalid")),
        "custom_url": meta.get("custom_url") or "",
        "thumbnail": meta.get("thumbnail") or "",
        "description": meta.get("description") or "",
        "published_at": meta.get("published_at") or "",
        "subscribers": meta.get("subscribers"),
        "video_count": meta.get("video_count"),
        "view_count": meta.get("view_count"),
        "hidden_subscribers": bool(meta.get("hidden_subscribers")),
        "stats_updated": meta.get("stats_updated") or "",
    }


def list_all() -> list[dict]:
    return [info(slug) for slug in sorted(_channels().keys())]


def dedupe(channel_id: str) -> str:
    """Collapse channels that resolve to the same YouTube channel_id, keeping one.
    Prefers a named (non-pending) channel with the shortest slug. Returns kept slug."""
    if not channel_id:
        return ""
    matches = [c["slug"] for c in list_all() if c.get("channel_id") == channel_id]
    if len(matches) <= 1:
        return matches[0] if matches else ""

    def score(slug: str):
        m = read_meta(slug)
        return (1 if m.get("pending") else 0, len(slug), slug)

    matches.sort(key=score)
    keep = matches[0]
    for s in matches[1:]:
        delete(s)
    return keep
