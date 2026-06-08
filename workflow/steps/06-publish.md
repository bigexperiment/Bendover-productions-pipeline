# 08 — Upload

**Agent step** — assistant generates metadata, thumbnail, then uploads. User: OAuth popup (first time) + optional title/thumbnail approval.

**Folder:** `07-upload/` — `thumbnail.png`, `upload_metadata.json`, OAuth files

## Assistant checklist

### 1. Title + description (agent writes)

From `01-script/Script.txt` + `03-transcript/transcript.txt` + `project.json` name:

- `title` — under 100 chars, specific, click-worthy
- `description` — hook + summary paragraphs
- `tags` — 5–15 relevant tags
- `privacy` — from user or default `public`

Save to `project.json` + `07-upload/upload_metadata.json`. Show user; revise on request.

### 2. Thumbnail (agent runs script)

```bash
python3 scripts/05_publish/generate_thumbnail.py
```

→ `07-upload/thumbnail.png`. Show user; rerun if rejected.

### 3. Upload (agent runs script)

1. `pip3 install -r 07-upload/requirements-youtube.txt`
2. No token → `--auth-only` (user: browser popup)
3. `python3 scripts/05_publish/upload_to_youtube.py` (auto-reads `project.json`)
4. Save `youtube_video_id`, set `step: "upload"`

Do **not** paste commands to the user.

Next optional step: [08-cleanup.md](08-cleanup.md) — reset workspace for the next video (assistant generates Python on the fly; user must save outputs first).

Thumbnail A/B tests → YouTube Studio only (not automated).
