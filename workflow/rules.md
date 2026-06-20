# Rules

## Who does what

| Actor | Does |
|-------|------|
| **Assistant** | After user sets project name: **offer** to write script or let user paste own. On yes → generate per `workflow/script-generation-prompt.md`. Runs every other script. Updates `project.json`. |
| **User** | Project title/topic; accepts script offer or pastes own script; `02-audio`, `03-transcript`, TurboScribe export, style approval, browser OAuth when prompted, says **done**. |

**Never** tell the user to run terminal commands. Run them yourself.

## Chat phases (no UI)

Steps 0–6, 8–10: name, script, style, audio, transcript, manifest, style approval, render, upload, cleanup — **chat only** (except browser OAuth on first YouTube login).

Script (step 1): **After step 0**, if `Script.txt` is empty, **offer** assistant-written script vs user paste. When generating, **must** follow `workflow/script-generation-prompt.md` (web research first; high-retention 5-min structure; continuous prose in `01-script/Script.txt` — no headings, timestamps, or line breaks).

Transcript: user pastes timestamped export from [turboscribe.com](https://turboscribe.com) into `03-transcript/transcript.txt` (empty by default).

Manifest: intelligent cuts ~2s (max 3s) from transcript — not fixed-interval script chop.

**Preflight (mandatory):** Before `build_plan.py` and before image generation, run `python3 scripts/preflight.py` (add `--images` for step 7). Fix all errors; only then run the next script. See [preflight.md](preflight.md).

## Studio UI (image generation only)

Start when bulk image gen begins. **Assistant runs these — never raw `serve.py`.**

```bash
scripts/status_studio.sh    # check first — skip start if already OK
scripts/start_studio.sh     # detached supervisor; idempotent; survives agent shell exit
scripts/stop_studio.sh      # explicit shutdown only
```

`start_studio.sh` → `tracker/studio_supervisor.py --detach` → `tracker/serve.py` (auto-restart on crash).

**Do not** re-run start every chat turn. Agent-started non-detached processes die when the harness closes the shell; detached mode fixes that.

## Auto-run (assistant)

- Combine audio when user says done on audio step
- Build manifest when transcript ready
- Refresh manifest during generation
- `scripts/03_images/generate_images.py` if `style_approved: true`
- Render when images complete: `scripts/04_render/render_draft_video.py --output 06-output/final.mp4`
- **Upload prep (Phase A — assistant generates, then STOPS):**
  - Write `title`, `description`, `tags` from script + transcript → `project.json` + `07-upload/upload_metadata.json`
  - Confirm `thumbnail_text` with user first (STOP), then generate 3 Codex variants (`thumbnail_v1/v2/v3.png`), user picks → `thumbnail.png` (see **`workflow/thumbnail.md`**)
  - Show user title, description, and final thumbnail — **wait for explicit upload approval**
  - **Never** upload on the same turn as prep. Render-step “go” is **not** upload approval.
- **Upload (Phase B — only after user approves title + thumbnail):**
  - `pip3 install -r 07-upload/requirements-youtube.txt`
  - If no token: `--auth-only` (user completes browser login)
  - `python3 scripts/05_publish/upload_to_youtube.py` (new upload) or `--update` (live title/thumbnail)
  - Save `youtube_video_id` to `project.json`, set `step: "upload"`
- Stop when credits hit 0%
- **Cleanup (optional, step 10):**
  - Warn user cleanup deletes project artifacts — they must save `final.mp4`, YouTube link, metadata, thumbnail, script, etc. **before** confirming
  - Wait for explicit user OK
  - Write a one-off Python reset script on the fly (no repo cleanup script); run it yourself; call `ensure_workspace_template_files()` + `reset_project_dict()` so empty `Script.txt`/`transcript.txt` and style prefs survive

## Style approval (step 6)

Default: offer 3–5 sample frames before bulk gen.

**Skip samples:** If the user says to skip samples / start the process / they'll stop after a few generations if they don't like it — set `style_approved: true` and start step 7 immediately. They can halt in Studio or ask you to stop; do not insist on samples.

## Ask first

- Style approval (3–5 samples) before bulk gen — **unless** user opts to skip (see above)
- Thumbnail text confirmation, then 3 thumbnail variants — user picks before upload prep is final
- Worker count (default 5)
- **Mandatory** approval of title + thumbnail before upload — assistant must stop after prep; user says “upload” / “approved” / equivalent
- Resume after credit stop
- **Cleanup** — always warn + get confirmation before resetting the workspace

## Commands (assistant runs these — not the user)

```bash
python3 scripts/02_manifest/build_plan.py
python3 scripts/02_manifest/build_plan.py refresh
python3 scripts/03_images/generate_images.py
python3 scripts/04_render/render_draft_video.py --output 06-output/final.mp4
python3 scripts/05_publish/generate_thumbnail.py
pip3 install -r 07-upload/requirements-youtube.txt
python3 scripts/05_publish/upload_to_youtube.py --auth-only
python3 scripts/05_publish/upload_to_youtube.py
python3 scripts/05_publish/upload_to_youtube.py --update
scripts/status_studio.sh   # check first
scripts/start_studio.sh    # if down — detached, idempotent
scripts/stop_studio.sh     # stop when done
python3 scripts/07_credits/fetch_codex_usage.py --force
```
