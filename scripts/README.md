# Scripts

Run from project root.

| Step | Folder | Script |
|------|--------|--------|
| Audio | `01_audio/` | `combine_mp3s.py` → `02-audio/Combined.mp3` |
| Manifest | `02_manifest/` | `build_plan.py` |
| Images | `03_images/` | `generate_images.py` |
| Render | `04_render/` | `render_draft_video.py` |
| Upload | `05_publish/` | `generate_thumbnail.py`, `upload_to_youtube.py` → `07-upload/` |
| Credits | `07_credits/` | `fetch_codex_usage.py` |

## Studio tracker

```bash
scripts/start_studio.sh
scripts/status_studio.sh
```

UI server: `tracker/serve.py`
