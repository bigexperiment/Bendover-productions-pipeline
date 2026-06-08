# Rules

## Who does what

| Actor | Does |
|-------|------|
| **Assistant** | Runs every script (combine, manifest, generate, render, upload, credits). Updates `project.json`. |
| **User** | Adds files (`01-script`, `02-audio`, `03-transcript`), TurboScribe export, style approval, browser OAuth when prompted, says **done**. |

**Never** tell the user to run terminal commands. Run them yourself.

## Chat phases (no UI)

Steps 0–6, 8–10: name, script, style, audio, transcript, manifest, style approval, render, upload, cleanup — **chat only** (except browser OAuth on first YouTube login).

Transcript: user gets timestamped export from [turboscribe.com](https://turboscribe.com) → `03-transcript/transcript.txt`.

Manifest: intelligent cuts ~2s (up to 4s) from transcript — not fixed-interval script chop.

## Studio UI (image generation only)

Start when bulk image gen begins:

```bash
scripts/start_studio.sh
```

## Auto-run (assistant)

- Combine audio when user says done on audio step
- Build manifest when transcript ready
- Refresh manifest during generation
- `scripts/03_images/generate_images.py` if `style_approved: true`
- Render when images complete: `scripts/04_render/render_draft_video.py --output 06-output/final.mp4`
- **Upload prep (assistant generates — not the user):**
  - Write `title`, `description`, `tags` from script + transcript → `project.json` + `07-upload/upload_metadata.json`
  - `python3 scripts/05_publish/generate_thumbnail.py` → `07-upload/thumbnail.png`
  - Show user title/description/thumbnail for quick approval
- **Upload when approved:**
  - `pip3 install -r 07-upload/requirements-youtube.txt`
  - If no token: `--auth-only` (user completes browser login)
  - `python3 scripts/05_publish/upload_to_youtube.py` (reads `project.json` automatically)
  - Save `youtube_video_id` to `project.json`, set `step: "upload"`
- Stop when credits hit 0%
- **Cleanup (optional, step 10):**
  - Warn user cleanup deletes project artifacts — they must save `final.mp4`, YouTube link, metadata, thumbnail, script, etc. **before** confirming
  - Wait for explicit user OK
  - Write a one-off Python reset script on the fly (no repo cleanup script); run it yourself; reset `project.json` for the next video

## Ask first

- Style approval (3–5 samples) before bulk gen
- Worker count (default 5)
- Quick approval of generated title/description/thumbnail before upload (revise if user rejects)
- Resume after credit stop
- **Cleanup** — always warn + get confirmation before resetting the workspace

## Commands (assistant runs these — not the user)

```bash
python3 scripts/01_audio/combine_mp3s.py
python3 scripts/02_manifest/build_plan.py
python3 scripts/02_manifest/build_plan.py refresh
python3 scripts/03_images/generate_images.py
python3 scripts/04_render/render_draft_video.py --output 06-output/final.mp4
python3 scripts/05_publish/generate_thumbnail.py
pip3 install -r 07-upload/requirements-youtube.txt
python3 scripts/05_publish/upload_to_youtube.py --auth-only
python3 scripts/05_publish/upload_to_youtube.py
python3 scripts/07_credits/fetch_codex_usage.py --force
```
