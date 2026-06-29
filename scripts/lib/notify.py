"""Push alerts via ntfy.sh (phone notifications)."""
from __future__ import annotations

import subprocess
import time
from datetime import datetime

from lib.secrets import get as _secret

NTFY_TOPIC = _secret("ntfy_topic") or "bendoverproductions123"


def send_ntfy(message: str, *, topic: str = NTFY_TOPIC, retries: int = 3) -> bool:
    """POST message to ntfy.sh. Retries up to `retries` times with exponential backoff."""
    for attempt in range(retries):
        try:
            subprocess.run(
                ["curl", "-fsS", "-d", message, f"https://ntfy.sh/{topic}"],
                check=True,
                capture_output=True,
                timeout=30,
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"ntfy notify failed after {retries} attempts: {exc}")
    return False


def credits_reset_clock(usage: dict | None) -> str:
    """Local clock time when the blocking Codex window resets (e.g. 2:38 PM)."""
    if not usage:
        return "unknown"
    for key in ("five_hour", "weekly"):
        window = usage.get(key) or {}
        resets_at = window.get("resets_at")
        if resets_at:
            try:
                return datetime.fromtimestamp(int(resets_at)).strftime("%-I:%M %p")
            except (TypeError, ValueError, OSError):
                continue
        reset_in = (window.get("reset_in") or "").strip()
        if reset_in:
            return f"in {reset_in}"
    return "unknown"


def notify_images_complete(project_name: str, *, done: int = 0, total: int = 0) -> bool:
    name = (project_name or "Untitled video").strip()
    return send_ntfy(f"All clips Done! {name}")


def notify_credits_stopped(project_name: str, usage: dict | None = None) -> bool:
    reset_at = credits_reset_clock(usage)
    return send_ntfy(f"Failed! Credits exhausted. Credits reset at {reset_at}")
