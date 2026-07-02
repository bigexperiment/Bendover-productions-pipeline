"""Numbered project folders — match workflow steps."""
import os
from pathlib import Path

# PIPELINE_ROOT lets the queue runner point scripts at any project directory.
ROOT = Path(os.environ.get("PIPELINE_ROOT") or Path(__file__).resolve().parents[2])

# 01 script · 02 audio · 03 transcript · 04 manifest · 05 images · 06 output · 07 upload
# Style lives in project.json at repo root.

DIR_SCRIPT = ROOT / "01-script"
DIR_AUDIO = ROOT / "02-audio"
DIR_TRANSCRIPT = ROOT / "03-transcript"
DIR_MANIFEST = ROOT / "04-manifest"
DIR_IMAGES = ROOT / "05-images"
DIR_OUTPUT = ROOT / "06-output"
DIR_UPLOAD = ROOT / "07-upload"
DIR_STYLE_SAMPLES = ROOT / "assets" / "style-samples"

SCRIPT_FILE = DIR_SCRIPT / "Script.txt"
TRANSCRIPT_FILE = DIR_TRANSCRIPT / "transcript.txt"
NARRATION_FILE = DIR_AUDIO / "narration.mp3"
AUDIO_EXTS = frozenset({".mp3", ".wav", ".m4a"})

PLAN_FILE = DIR_MANIFEST / "image_cut_plan.txt"
MANIFEST_FILE = DIR_MANIFEST / "image_regen_manifest.csv"
PROGRESS_FILE = DIR_MANIFEST / "image_regen_progress.json"
SHOT_PLAN_FILE = DIR_MANIFEST / "shot_plan.json"
CAST_REFERENCE_FILE = DIR_MANIFEST / "cast_reference.png"

FINAL_MP4 = DIR_OUTPUT / "final.mp4"
PREVIEW_MP4 = DIR_OUTPUT / "preview.mp4"

# Per-project thumbnail variants live here (NOT in the shared 07-upload symlink)
DIR_THUMBS = ROOT / "tracker" / "thumbs"
THUMB_V1 = DIR_THUMBS / "thumbnail_v1.png"
THUMB_V2 = DIR_THUMBS / "thumbnail_v2.png"
THUMB_V3 = DIR_THUMBS / "thumbnail_v3.png"

# 07-upload is a symlink to shared YouTube credentials — only write here at upload time
YOUTUBE_TOKEN = DIR_UPLOAD / "youtube_token.json"
YOUTUBE_THUMBNAIL = DIR_UPLOAD / "thumbnail.png"  # final chosen thumb, copied just before upload
YOUTUBE_METADATA = DIR_UPLOAD / "upload_metadata.json"
YOUTUBE_REQUIREMENTS = DIR_UPLOAD / "requirements-youtube.txt"
PROJECT_FILE = ROOT / "project.json"

STYLE_SAMPLES_VARIANTS = DIR_STYLE_SAMPLES / "variants.json"
STYLE_SAMPLES_MANIFEST = DIR_STYLE_SAMPLES / "manifest.json"
STYLE_EXPLORE_RUN = ROOT / "tracker" / "style-explore-run"


def youtube_client_secrets() -> Path:
    matches = sorted(DIR_UPLOAD.glob("client_secret*.json"))
    if matches:
        return matches[0]
    return DIR_UPLOAD / "client_secret.json"
