"""Read safe Codex account metadata from local auth (no tokens exposed)."""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path

AUTH_FILE = Path.home() / ".codex" / "auth.json"
OPENAI_AUTH_CLAIM = "https://api.openai.com/auth"


def decode_jwt_payload(token: str) -> dict:
    segment = token.split(".")[1]
    segment += "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(segment))


def read_codex_account() -> dict:
    if not AUTH_FILE.is_file():
        return {
            "logged_in": False,
            "session_expired": False,
            "auth_mode": None,
            "reason": "Not logged in — run codex login",
        }

    try:
        auth = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "logged_in": False,
            "session_expired": False,
            "auth_mode": None,
            "reason": "Could not read Codex auth file",
        }

    auth_mode = auth.get("auth_mode")
    tokens = auth.get("tokens") or {}
    id_token = tokens.get("id_token")
    access_token = tokens.get("access_token")

    if not id_token and not access_token:
        return {
            "logged_in": False,
            "session_expired": False,
            "auth_mode": auth_mode,
            "reason": "No token stored — run codex login",
        }

    now = int(time.time())
    profile: dict = {}
    id_exp = 0
    access_exp = 0

    if id_token:
        try:
            profile = decode_jwt_payload(id_token)
            id_exp = int(profile.get("exp") or 0)
        except (ValueError, json.JSONDecodeError, IndexError):
            profile = {}

    if access_token and access_token.count(".") >= 2:
        try:
            access_claims = decode_jwt_payload(access_token)
            access_exp = int(access_claims.get("exp") or 0)
            openai_from_access = access_claims.get(OPENAI_AUTH_CLAIM) or {}
        except (ValueError, json.JSONDecodeError, IndexError):
            openai_from_access = {}
    else:
        openai_from_access = {}

    openai_auth = profile.get(OPENAI_AUTH_CLAIM) or openai_from_access or {}
    orgs = openai_auth.get("organizations") or []
    default_org = next((org for org in orgs if org.get("is_default")), orgs[0] if orgs else {})

    access_valid = bool(access_exp and access_exp > now)
    id_valid = bool(id_exp and id_exp > now)
    logged_in = access_valid or id_valid

    session_exp = access_exp or id_exp
    account = {
        "logged_in": logged_in,
        "session_expired": not logged_in,
        "auth_mode": auth_mode,
        "email": profile.get("email"),
        "name": profile.get("name"),
        "email_verified": profile.get("email_verified"),
        "plan_type": openai_auth.get("chatgpt_plan_type"),
        "organization": default_org.get("title"),
        "organization_role": default_org.get("role"),
        "token_expires_at": session_exp or None,
        "token_expires_in_seconds": max(0, session_exp - now) if session_exp else None,
        "last_refresh": auth.get("last_refresh"),
    }
    if not logged_in:
        account["reason"] = "Session expired — run codex login"
    return account
