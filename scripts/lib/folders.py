"""Numbered project folders — match workflow steps."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 01 script · 02 audio · 03 transcript · 04 manifest · 05 images · 06 output · 07 upload
# Style lives in project.json at repo root.

DIR_SCRIPT = ROOT / "01-script"
DIR_AUDIO = ROOT / "02-audio"
DIR_TRANSCRIPT = ROOT / "03-transcript"
DIR_MANIFEST = ROOT / "04-manifest"
DIR_IMAGES = ROOT / "05-images"
DIR_OUTPUT = ROOT / "06-output"
DIR_UPLOAD = ROOT / "07-upload"

SCRIPT_FILE = DIR_SCRIPT / "Script.txt"
TRANSCRIPT_FILE = DIR_TRANSCRIPT / "transcript.txt"

COMBINED = DIR_AUDIO / "Combined.mp3"
COMBINED_NORMALIZED = DIR_AUDIO / "Combined_normalized.mp3"
AUDIO_OUTPUT_NAMES = frozenset({"Combined.mp3", "Combined_normalized.mp3"})

PLAN_FILE = DIR_MANIFEST / "image_cut_plan.txt"
MANIFEST_FILE = DIR_MANIFEST / "image_regen_manifest.csv"
PROGRESS_FILE = DIR_MANIFEST / "image_regen_progress.json"

FINAL_MP4 = DIR_OUTPUT / "final.mp4"
PREVIEW_MP4 = DIR_OUTPUT / "preview.mp4"

YOUTUBE_TOKEN = DIR_UPLOAD / "youtube_token.json"
YOUTUBE_THUMBNAIL = DIR_UPLOAD / "thumbnail.png"
YOUTUBE_METADATA = DIR_UPLOAD / "upload_metadata.json"
YOUTUBE_REQUIREMENTS = DIR_UPLOAD / "requirements-youtube.txt"
PROJECT_FILE = ROOT / "project.json"


def youtube_client_secrets() -> Path:
    matches = sorted(DIR_UPLOAD.glob("client_secret*.json"))
    if matches:
        return matches[0]
    return DIR_UPLOAD / "client_secret.json"
