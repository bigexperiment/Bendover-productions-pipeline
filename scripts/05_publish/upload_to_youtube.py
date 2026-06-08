from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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
    }


_DEFAULTS = load_upload_defaults()
DEFAULT_TITLE = _DEFAULTS["title"]
DEFAULT_DESCRIPTION = _DEFAULTS["description"]
DEFAULT_PRIVACY = _DEFAULTS["privacy"]
DEFAULT_TAGS = _DEFAULTS["tags"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload a video to YouTube.")
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
        "--no-thumbnail",
        action="store_true",
        help="Skip setting a custom thumbnail.",
    )
    return parser.parse_args()


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
            creds = flow.run_local_server(port=0)
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


def main() -> int:
    args = parse_args()

    creds = get_credentials(args.client_secrets, args.token)
    youtube = build("youtube", "v3", credentials=creds)

    if args.auth_only:
        print(f"Authenticated. Token saved to {args.token}")
        return 0

    if not args.video.is_file():
        print(f"Video not found: {args.video}", file=sys.stderr)
        return 1

    if not args.title.strip():
        print("Missing title — generate metadata in project.json first.", file=sys.stderr)
        return 1

    tags = args.tags or []
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

    print(f"Studio: https://studio.youtube.com/video/{video_id}/edit")
    print(f"Watch:  https://youtu.be/{video_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
