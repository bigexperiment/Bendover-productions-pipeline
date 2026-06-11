# Thumbnail + title rules

YouTube uses **two different strings**. The assistant must never put the full `title` on the thumbnail image.

## `title` vs `thumbnail_text`

| Field | Where it goes | Rules |
|-------|----------------|-------|
| **`title`** | YouTube listing (search, watch page) | Full question or hook, &lt;100 chars, can name the topic |
| **`thumbnail_text`** | **On the PNG only** | 2–5 words, ALL CAPS OK, must **differ** from `title` |

### `title` examples
- `How Ancient Humans Fed Their Babies?`
- `Why Your Brain Needs Iron Before Age Two`

### `thumbnail_text` examples (good)
- `FIRE IS NOT ENOUGH` — lateral, sparks curiosity, no spoiler
- `NOT ON THE PLAQUE` — mystery, not a paraphrase of title
- `STRANGER THAN BERRIES` — from script vibe, oblique

### `thumbnail_text` examples (bad)
- `HOW ANCIENT HUMANS FED BABIES` — repeats the title
- `PRE-CHEWED FOOD` — spoils the story twist
- `ANCIENT BABY FOOD` — too on-the-nose / same topic as title

**Assistant:** offer 5–10 `thumbnail_text` options when user asks. Favor **curiosity + no spoiler + not title-shaped**.

## `thumbnail_frame` (style match)

Thumbnails must look like the video. **Do not** use Codex to paint a new scene by default — it drifts from frame style.

| Field | Purpose |
|-------|---------|
| **`thumbnail_frame`** | Filename in `05-images/` (e.g. `0_26.png`) |

**Default:** `generate_thumbnail.py` auto-picks a manifest row whose scene/transcript matches fire/camp hints, or uses `thumbnail_frame` when set.

**Pipeline:**
1. Crop real frame → 1280×720
2. Dark gradient on top third (text legibility)
3. Pillow overlay of exact `thumbnail_text` (Codex cannot be trusted for typography)

```bash
python3 scripts/05_publish/generate_thumbnail.py
python3 scripts/05_publish/generate_thumbnail.py --frame=0_26.png
python3 scripts/05_publish/generate_thumbnail.py --headline="FIRE IS NOT ENOUGH"
python3 scripts/05_publish/generate_thumbnail.py --codex   # avoid unless no frames exist
```

Output: `07-upload/thumbnail.png`

## Publish gate (mandatory)

1. Save `title`, `description`, `tags` → `project.json` + `07-upload/upload_metadata.json`
2. Set `thumbnail_text` (+ optional `thumbnail_frame`) → run `generate_thumbnail.py`
3. **STOP** — show user title + thumbnail path; wait for explicit approval
4. Only then upload or `--update` live video

Render-step **go** = start prep (steps 1–2). **Not** upload approval.

## Update live video (already published)

When `youtube_video_id` is set and user approves new title/thumbnail:

```bash
.venv-youtube/bin/python scripts/05_publish/upload_to_youtube.py --update
```

Reads `project.json` + `07-upload/thumbnail.png`; updates title, description, tags, and thumbnail via API.

## `project.json` fields

```json
{
  "title": "How Ancient Humans Fed Their Babies?",
  "thumbnail_text": "FIRE IS NOT ENOUGH",
  "thumbnail_frame": "0_26.png",
  "youtube_video_id": "oXrB8JGi-qc"
}
```

Cleared on workspace cleanup (with `title`, `description`, etc.). Not preserved across resets.
