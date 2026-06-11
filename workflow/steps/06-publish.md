# 08 — Upload

**Agent step — two phases.** Assistant generates metadata + thumbnail, **stops for approval**, then uploads only when user confirms. User: OAuth popup (first time) on first upload.

**Hard rule:** Do **not** run `upload_to_youtube.py` in the same turn as thumbnail generation. Render-step “go” means start **prep only**, not publish.

**Folder:** `07-upload/` — `thumbnail.png`, `upload_metadata.json`, OAuth files

## Assistant checklist

### 1. Title + description (agent writes)

From `01-script/Script.txt` + `03-transcript/transcript.txt` + `project.json` name:

- `title` — under 100 chars, specific, click-worthy
- `description` — hook + summary paragraphs
- `tags` — 5–15 relevant tags
- `privacy` — from user or default `public`

Save to `project.json` + `07-upload/upload_metadata.json`.

### 2. Thumbnail (agent sets hook text + frame, then runs script)

Full rules: **[thumbnail.md](../thumbnail.md)** — `title` vs `thumbnail_text`, curiosity without spoilers, frame-based style match.

Summary:
- **`title`** → YouTube listing only
- **`thumbnail_text`** → 2–5 words on the image; must **≠ title**; lateral curiosity, don’t spoil
- **`thumbnail_frame`** → `05-images/` PNG (optional; auto-pick if unset)

```bash
python3 scripts/05_publish/generate_thumbnail.py
```

→ `07-upload/thumbnail.png`

### 3. **STOP — user approval required**

Show the user:
- **Title** (full string)
- **Description** (hook + first paragraph, or brief summary)
- **Thumbnail** — path `07-upload/thumbnail.png` (they open it in the IDE)

Ask: “Approve title + thumbnail, or tell me what to change?”

- Revise metadata or rerun thumbnail on request.
- **Wait** for explicit OK: “upload”, “approved”, “publish”, “ship it”, etc.
- **Do not** upload until they confirm.

### 4. Upload or update (agent runs script — Phase B only)

1. `pip3 install -r 07-upload/requirements-youtube.txt` (or `.venv-youtube`)
2. No token → `--auth-only` (user: browser popup)
3. New video: `python3 scripts/05_publish/upload_to_youtube.py`
4. Live video already up: `python3 scripts/05_publish/upload_to_youtube.py --update`
5. Saves `youtube_video_id`, set `step: "upload"`

Do **not** paste commands to the user.

Next optional step: [08-cleanup.md](08-cleanup.md) — reset workspace for the next video (assistant generates Python on the fly; user must save outputs first).

Thumbnail A/B tests → YouTube Studio only (not automated).
