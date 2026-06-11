# Scripts

Run from project root.

| Step | Folder | Script |
|------|--------|--------|
| Audio | — | one narration file in `02-audio/` |
| Manifest | `02_manifest/` | `build_plan.py` |
| Images | `03_images/` | `generate_images.py` |
| Render | `04_render/` | `render_draft_video.py` |
| Upload | `05_publish/` | `generate_thumbnail.py`, `upload_to_youtube.py` → `07-upload/` |
| Credits | `07_credits/` | `fetch_codex_usage.py` |

## Studio tracker

**Assistant: always use these scripts.** Never run `tracker/serve.py` directly.

| Script | Purpose |
|--------|---------|
| `scripts/status_studio.sh` | Check health — run **before** start |
| `scripts/start_studio.sh` | Start if down; **idempotent** + **detached** |
| `scripts/stop_studio.sh` | Stop supervisor + free port |

Flow: `start_studio.sh` → `tracker/studio_supervisor.py --detach` → `tracker/serve.py`

- **Detached** — double-fork so Studio survives when the Cursor agent shell closes.
- **Supervised** — supervisor restarts `serve.py` after crashes.
- **Idempotent** — if http://127.0.0.1:47829/ already responds, start does nothing (won't kill a live server).

Do **not** re-run start every chat message. Check status first; start once per image-gen session.

Log: `tracker/studio.log` · PID: `tracker/studio.pid` · port: `tracker/port.txt`
