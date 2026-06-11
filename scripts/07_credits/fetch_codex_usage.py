from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CREDITS_FRESH_SECONDS = 20 * 60


ROOT = Path(__file__).resolve().parents[2]
USAGE_FILE = ROOT / "tracker" / "usage.json"
CODEX_HOME = Path.home() / ".codex"
SESSIONS_DIR = CODEX_HOME / "sessions"


def fmt_reset(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "--"
    hours, rem = divmod(int(seconds), 3600)
    minutes = rem // 60
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def parse_rate_limits(payload: dict | None) -> dict | None:
    if not payload or payload.get("type") != "token_count":
        return None
    rate_limits = payload.get("rate_limits") or (payload.get("info") or {}).get("rate_limits")
    return rate_limits or None


def parse_event_timestamp(value: str | None) -> int | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return int(datetime.fromisoformat(normalized).timestamp())
    except ValueError:
        return None


def latest_rate_limits() -> tuple[dict | None, str | None, int | None]:
    if not SESSIONS_DIR.exists():
        return None, "No Codex sessions directory found", None

    session_files = sorted(
        SESSIONS_DIR.rglob("*.jsonl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    for session_file in session_files[:80]:
        try:
            lines = session_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines[-400:]):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = event.get("payload", {})
            rate_limits = parse_rate_limits(payload)
            if rate_limits:
                event_at = parse_event_timestamp(event.get("timestamp"))
                return rate_limits, str(session_file), event_at
    return None, "No recent Codex rate-limit events found", None


def credits_are_fresh(event_at: int | None, now: int | None = None) -> bool:
    if not event_at:
        return False
    now = now or int(time.time())
    return (now - event_at) <= CREDITS_FRESH_SECONDS


def should_stop_generation(payload: dict) -> tuple[bool, str]:
    credits = payload.get("credits") or {}
    if credits.get("has_credits") is True or credits.get("unlimited") is True:
        return False, ""

    five_hour = payload.get("five_hour")
    if five_hour and float(five_hour.get("remaining_percent") or 0) <= 0:
        return True, "5-hour Codex limit reached (0% remaining)"

    if credits.get("has_credits") is False:
        return True, "Workspace credits exhausted"

    return False, ""


def enrich_usage_payload(payload: dict) -> dict:
    now = int(time.time())
    event_at = payload.get("event_at")
    if event_at:
        payload["event_age_seconds"] = max(0, now - int(event_at))
    fresh = credits_are_fresh(event_at, now) if event_at else False
    payload["credits_fresh"] = fresh
    if not fresh:
        payload["credits_stale_reason"] = payload.get("credits_stale_reason") or (
            "No recent Codex usage — run a command or refresh to update limits"
        )
    for key in ("five_hour", "weekly"):
        window = payload.get(key)
        if not window:
            continue
        resets_at = int(window.get("resets_at") or 0)
        if resets_at:
            secs = max(0, resets_at - now)
            remaining = float(window.get("remaining_percent") or 0)
            window = {
                **window,
                "reset_in_seconds": secs,
                "reset_in": fmt_reset(secs) if secs else "0m",
                "reset_elapsed": secs == 0 and remaining <= 5,
            }
            payload[key] = window
    return payload


def read_usage_payload(force: bool = False, max_cache_age: int = 30) -> dict:
    """Read usage; re-scan Codex session logs if cache file is older than max_cache_age."""
    if not force and USAGE_FILE.exists():
        try:
            age = time.time() - USAGE_FILE.stat().st_mtime
            if age > max_cache_age:
                return write_usage(force=True)
            payload = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
            return enrich_usage_payload(payload)
        except json.JSONDecodeError:
            pass
    return write_usage(force=True)


def build_usage_payload(rate_limits: dict) -> dict:
    now = int(time.time())
    primary = rate_limits.get("primary") or {}
    secondary = rate_limits.get("secondary") or {}
    credits = rate_limits.get("credits") or {}

    primary_used = float(primary.get("used_percent") or 0)
    secondary_used = float(secondary.get("used_percent") or 0)
    primary_reset_at = int(primary.get("resets_at") or 0)
    secondary_reset_at = int(secondary.get("resets_at") or 0)

    return {
        "updated_at": now,
        "plan_type": rate_limits.get("plan_type"),
        "five_hour": {
            "used_percent": primary_used,
            "remaining_percent": max(0.0, 100.0 - primary_used),
            "resets_at": primary_reset_at,
            "reset_in_seconds": max(0, primary_reset_at - now) if primary_reset_at else None,
            "reset_in": fmt_reset(primary_reset_at - now if primary_reset_at else None),
        },
        "weekly": {
            "used_percent": secondary_used,
            "remaining_percent": max(0.0, 100.0 - secondary_used),
            "resets_at": secondary_reset_at,
            "reset_in_seconds": max(0, secondary_reset_at - now) if secondary_reset_at else None,
            "reset_in": fmt_reset(secondary_reset_at - now if secondary_reset_at else None),
        },
        "credits": {
            "has_credits": credits.get("has_credits"),
            "unlimited": credits.get("unlimited"),
            "balance": credits.get("balance"),
        },
        "source_updated_at": datetime.now(timezone.utc).isoformat(),
    }


def write_usage(force: bool = False, cache_seconds: int = 30) -> dict:
    if (
        not force
        and USAGE_FILE.exists()
        and time.time() - USAGE_FILE.stat().st_mtime < cache_seconds
    ):
        return enrich_usage_payload(json.loads(USAGE_FILE.read_text(encoding="utf-8")))

    rate_limits, source, event_at = latest_rate_limits()
    now = int(time.time())
    if not rate_limits:
        payload = {
            "updated_at": now,
            "error": source,
            "five_hour": None,
            "weekly": None,
            "credits": None,
            "credits_fresh": False,
            "credits_stale_reason": source or "No recent usage data",
        }
    else:
        payload = build_usage_payload(rate_limits)
        payload["source"] = source
        payload["event_at"] = event_at
        payload["event_age_seconds"] = (now - event_at) if event_at else None
        payload["credits_fresh"] = credits_are_fresh(event_at, now)
        if not payload["credits_fresh"]:
            payload["credits_stale_reason"] = (
                "Usage data is older than 20 minutes — run Codex or refresh to update"
            )

    blocked, reason = should_stop_generation(payload)
    payload["generation_blocked"] = blocked
    payload["stop_reason"] = reason if blocked else ""

    USAGE_FILE.write_text(json.dumps(enrich_usage_payload(payload), indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    force = "--force" in sys.argv
    payload = write_usage(force=force)
    if payload.get("error"):
        print(payload["error"])
        return 1
    print(
        f"5h remaining {payload['five_hour']['remaining_percent']:.0f}% "
        f"(resets in {payload['five_hour']['reset_in']})"
    )
    print(
        f"weekly remaining {payload['weekly']['remaining_percent']:.0f}% "
        f"(resets in {payload['weekly']['reset_in']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
