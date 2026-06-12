# Thumbnail + title rules

YouTube uses **two different strings**. The assistant must never put the full `title` on the thumbnail image.

## `title` vs `thumbnail_text`

| Field | Where it goes | Rules |
|-------|----------------|-------|
| **`title`** | YouTube listing (search, watch page) | Full question or hook, &lt;100 chars, can name the topic |
| **`thumbnail_text`** | **On the PNG only** | 2–5 words, ALL CAPS OK, must **differ** from `title` |

**Assistant:** offer 5–10 `thumbnail_text` options. Favor **curiosity + no spoiler + not title-shaped**.

## Thumbnail workflow (mandatory — 3 stops)

Codex draws scene + text **in the image**. **Never** Pillow text overlay.

### Stop 1 — confirm `thumbnail_text` only

After title/description are drafted:

1. Propose 5–10 `thumbnail_text` options (or take user's wording)
2. **STOP** — wait for user to confirm exact `thumbnail_text`
3. Save confirmed text to `project.json` → `thumbnail_text`
4. **Do not generate any images yet**

### Stop 2 — three variations, user picks one

Only after `thumbnail_text` is confirmed:

1. **You** run Codex **3 times** (different scene angles, same headline text):

```bash
python3 scripts/05_publish/generate_thumbnail.py --variant=1 --output=07-upload/thumbnail_v1.png
python3 scripts/05_publish/generate_thumbnail.py --variant=2 --output=07-upload/thumbnail_v2.png
python3 scripts/05_publish/generate_thumbnail.py --variant=3 --output=07-upload/thumbnail_v3.png
```

2. **STOP** — show all three paths. User picks **1**, **2**, or **3** (or asks for regen)
3. Copy winner → `07-upload/thumbnail.png` (only then is the final thumbnail chosen)
4. User may instead supply their own PNG (e.g. ChatGPT) → save as `07-upload/thumbnail.png`

### Stop 3 — upload approval

Show **title**, **description** (brief), and final **`07-upload/thumbnail.png`**.

- **Do not upload** until user explicitly approves
- Render-step “go” is **not** upload approval

## Generation rules

- Codex renders headline text in the artwork — not post-production overlay
- `--variant=1|2|3` changes scene composition; same `thumbnail_text`
- `--frame` crops a video frame only (no text) — rare fallback

## Publish gate

1. Save `title`, `description`, `tags` → `project.json` + `07-upload/upload_metadata.json`
2. Confirm `thumbnail_text` → generate 3 variants → user picks → `thumbnail.png`
3. **STOP** for upload approval
4. Only then `upload_to_youtube.py`

## `project.json` fields

```json
{
  "title": "How Ancient Humans Fed Their Babies?",
  "thumbnail_text": "FIRE IS NOT ENOUGH",
  "thumbnail_frame": "0_26.png",
  "youtube_video_id": null
}
```
