from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import channels  # noqa: E402
from lib.notify import send_ntfy  # noqa: E402
from lib.folders import (  # noqa: E402
    FINAL_MP4,
    PROJECT_FILE,
    YOUTUBE_METADATA,
    YOUTUBE_THUMBNAIL,
    YOUTUBE_TOKEN,
    youtube_client_secrets,
)

DEFAULT_CLIENT_SECRETS = youtube_client_secrets()
DEFAULT_TOKEN = YOUTUBE_TOKEN
DEFAULT_VIDEO = FINAL_MP4
DEFAULT_THUMBNAIL = YOUTUBE_THUMBNAIL

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def load_upload_defaults() -> dict:
    project: dict = {}
    if PROJECT_FILE.is_file():
        project = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    meta: dict = {}
    if YOUTUBE_METADATA.is_file():
        meta = json.loads(YOUTUBE_METADATA.read_text(encoding="utf-8"))
    merged = {**meta, **{k: v for k, v in project.items() if v}}
    return {
        "title": merged.get("title") or merged.get("name") or "",
        "description": merged.get("description") or "",
        "privacy": merged.get("privacy") or "public",
        "tags": merged.get("tags") or [],
        "youtube_video_id": merged.get("youtube_video_id"),
    }


_DEFAULTS = load_upload_defaults()
DEFAULT_TITLE = _DEFAULTS["title"]
DEFAULT_DESCRIPTION = _DEFAULTS["description"]
DEFAULT_PRIVACY = _DEFAULTS["privacy"]
DEFAULT_TAGS = _DEFAULTS["tags"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload or update a video on YouTube.")
    parser.add_argument(
        "--video",
        type=Path,
        default=DEFAULT_VIDEO,
        help="Path to the MP4 file to upload.",
    )
    parser.add_argument(
        "--thumbnail",
        type=Path,
        default=DEFAULT_THUMBNAIL,
        help="Path to the thumbnail image (PNG/JPG).",
    )
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION)
    parser.add_argument(
        "--privacy",
        choices=("private", "unlisted", "public"),
        default=DEFAULT_PRIVACY,
        help="Upload visibility. Default: from project.json.",
    )
    parser.add_argument(
        "--tags",
        nargs="*",
        default=DEFAULT_TAGS if DEFAULT_TAGS else None,
        help="Tags (default: from project.json or upload_metadata.json).",
    )
    parser.add_argument(
        "--video-id",
        default=_DEFAULTS.get("youtube_video_id"),
        help="Existing video ID for --update (default: project.json youtube_video_id).",
    )
    parser.add_argument(
        "--channel",
        default=None,
        help="Named channel slug (07-upload/channels/<slug>) — selects its own "
        "client_secret + token. Overrides --client-secrets/--token defaults.",
    )
    parser.add_argument(
        "--client-secrets",
        type=Path,
        default=DEFAULT_CLIENT_SECRETS,
        help="OAuth client secrets JSON from Google Cloud.",
    )
    parser.add_argument(
        "--token",
        type=Path,
        default=DEFAULT_TOKEN,
        help="Saved OAuth token JSON (created on first login).",
    )
    parser.add_argument(
        "--auth-only",
        action="store_true",
        help="Run browser login and save token without uploading.",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Update title/description/tags/thumbnail on an existing video (--video-id or youtube_video_id).",
    )
    parser.add_argument(
        "--no-thumbnail",
        action="store_true",
        help="Skip setting a custom thumbnail.",
    )
    return parser.parse_args()


def _run_login_flow(client_config: dict) -> Credentials:
    if not client_config:
        raise RuntimeError("No Google OAuth app configured in secrets.json (youtube.app)")
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    # select_account forces the account chooser so each channel can log in as a
    # different Google account; consent+offline yields a refresh token.
    return flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="select_account consent",
    )


def get_channel_credentials(slug: str) -> Credentials:
    """Build credentials for a named channel entirely from secrets.json — the
    shared OAuth app plus this channel's stored token — refreshing/logging in as
    needed and saving the token back to secrets.json."""
    client_config = channels.app_client_config()
    token_info = channels.get_token(slug)

    creds: Credentials | None = None
    if token_info:
        creds = Credentials.from_authorized_user_info(token_info, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                # Refresh token expired/revoked — flag it so the UI shows "log in again".
                channels.write_meta(slug, {"token_invalid": True})
                raise RuntimeError(f"Channel '{slug}' login expired — log in again") from None
        else:
            creds = _run_login_flow(client_config)
        channels.set_token(slug, json.loads(creds.to_json()))

    return creds


def get_credentials(client_secrets: Path, token_path: Path) -> Credentials:
    if not client_secrets.is_file():
        raise FileNotFoundError(f"Client secrets not found: {client_secrets}")

    creds: Credentials | None = None
    if token_path.is_file():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(client_secrets), SCOPES
            )
            creds = flow.run_local_server(
                port=0,
                access_type="offline",
                prompt="select_account consent",
            )
        token_path.write_text(creds.to_json())

    return creds


def upload_video(
    youtube,
    video_path: Path,
    title: str,
    description: str,
    privacy: str,
    tags: list[str],
) -> str:
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "17",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=8 * 1024 * 1024,
    )
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"Upload progress: {pct}%")

    video_id = response["id"]
    print(f"Upload complete. Video ID: {video_id}")
    return video_id


def update_video_metadata(
    youtube,
    video_id: str,
    title: str,
    description: str,
    tags: list[str],
) -> None:
    youtube.videos().update(
        part="snippet",
        body={
            "id": video_id,
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "17",
            },
        },
    ).execute()
    print(f"Updated metadata for {video_id}")


MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024


def prepare_thumbnail(thumbnail_path: Path) -> tuple[Path, tempfile.TemporaryDirectory | None]:
    if thumbnail_path.stat().st_size <= MAX_THUMBNAIL_BYTES:
        return thumbnail_path, None

    tmp = tempfile.TemporaryDirectory()
    out = Path(tmp.name) / "thumbnail_upload.jpg"
    subprocess.run(
        [
            "sips",
            "-s",
            "format",
            "jpeg",
            "-s",
            "formatOptions",
            "80",
            str(thumbnail_path),
            "--out",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    print(
        f"Compressed {thumbnail_path.name} "
        f"({thumbnail_path.stat().st_size // 1024} KB → {out.stat().st_size // 1024} KB)"
    )
    return out, tmp


def set_thumbnail(youtube, video_id: str, thumbnail_path: Path) -> None:
    upload_path, tmp = prepare_thumbnail(thumbnail_path)
    try:
        mimetype = "image/jpeg" if upload_path.suffix.lower() in {".jpg", ".jpeg"} else None
        media = MediaFileUpload(str(upload_path), mimetype=mimetype)
        youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
        print(f"Thumbnail set from {thumbnail_path.name}")
    finally:
        if tmp is not None:
            tmp.cleanup()


def save_video_id_to_project(video_id: str, channel: str | None = None) -> None:
    if not PROJECT_FILE.is_file():
        return
    project = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    project["youtube_video_id"] = video_id
    if channel:
        project["youtube_channel"] = channel
    project["step"] = "upload"
    PROJECT_FILE.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")


def capture_channel_title(youtube, slug: str) -> None:
    """Record the real YouTube channel title, id and stats so the UI can show a
    rich card, then collapse any duplicate of the same channel."""
    try:
        resp = youtube.channels().list(
            part="snippet,statistics", mine=True
        ).execute()
        items = resp.get("items") or []
        if not items:
            return
        it = items[0]
        sn = it.get("snippet", {})
        st = it.get("statistics", {})
        thumbs = sn.get("thumbnails", {})
        thumb = (thumbs.get("default") or thumbs.get("medium") or {}).get("url", "")
        title = sn.get("title", "")
        channels.write_meta(slug, {
            "title": title,
            "name": title,
            "channel_id": it.get("id", ""),
            "custom_url": sn.get("customUrl", ""),
            "description": sn.get("description", ""),
            "thumbnail": thumb,
            "published_at": sn.get("publishedAt", ""),
            "subscribers": None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount", 0)),
            "hidden_subscribers": bool(st.get("hiddenSubscriberCount")),
            "video_count": int(st.get("videoCount", 0)),
            "view_count": int(st.get("viewCount", 0)),
            "stats_updated": _now_iso(),
            "pending": False,
        })
        channels.dedupe(it.get("id", ""))
    except Exception:
        pass


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    args = parse_args()

    if args.channel:
        creds = get_channel_credentials(args.channel)
    else:
        creds = get_credentials(args.client_secrets, args.token)
    youtube = build("youtube", "v3", credentials=creds)

    if args.auth_only:
        if args.channel:
            capture_channel_title(youtube, args.channel)
        print(f"Authenticated. Token saved to {args.token}")
        return 0

    if not args.title.strip():
        print("Missing title — generate metadata in project.json first.", file=sys.stderr)
        return 1

    tags = args.tags or []

    if args.update:
        video_id = (args.video_id or "").strip()
        if not video_id:
            print("Missing --video-id or youtube_video_id in project.json", file=sys.stderr)
            return 1
        print(f"Updating {video_id}…")
        update_video_metadata(
            youtube, video_id, args.title, args.description, tags
        )
        if not args.no_thumbnail and args.thumbnail.is_file():
            set_thumbnail(youtube, video_id, args.thumbnail)
        elif not args.no_thumbnail:
            print(f"No thumbnail at {args.thumbnail}; skipping.")
        print(f"Studio: https://studio.youtube.com/video/{video_id}/edit")
        print(f"Watch:  https://youtu.be/{video_id}")
        return 0

    if not args.video.is_file():
        print(f"Video not found: {args.video}", file=sys.stderr)
        return 1

    print(f"Uploading {args.video.name} as {args.privacy}...")
    video_id = upload_video(
        youtube,
        args.video,
        args.title,
        args.description,
        args.privacy,
        tags,
    )

    if not args.no_thumbnail and args.thumbnail.is_file():
        set_thumbnail(youtube, video_id, args.thumbnail)
    elif not args.no_thumbnail:
        print(f"No thumbnail at {args.thumbnail}; skipping.")

    save_video_id_to_project(video_id, args.channel)
    if args.channel:
        capture_channel_title(youtube, args.channel)
    print(f"Studio: https://studio.youtube.com/video/{video_id}/edit")
    print(f"Watch:  https://youtu.be/{video_id}")
    title = args.title.strip() or "Video"
    send_ntfy(f"✅ Uploaded: {title}\nhttps://youtu.be/{video_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
