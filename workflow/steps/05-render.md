# 05 — Render

**Script:** `scripts/04_render/render_draft_video.py`

```bash
python3 scripts/04_render/render_draft_video.py --output 06-output/final.mp4
```

Preview:

```bash
python3 scripts/04_render/render_draft_video.py --limit 30 --output 06-output/preview.mp4
```

Uses `02-audio/Combined_normalized.mp3` if present, else `02-audio/Combined.mp3`.

Set `step: "publish"` when done.
