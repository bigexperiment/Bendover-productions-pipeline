# Bendover Productions Pipeline

AI-assisted YouTube video pipeline. Stickman educational explainer channel.

---

## The two-part workflow

```
Part 1 — Claude Code (here)     Part 2 — Studio UI
────────────────────────────    ────────────────────────────────────────
Brainstorm topic                http://127.0.0.1:47829
Write / approve script          Upload audio (.mp3)
Create project folder           Upload transcript (.txt from TurboScribe)
Open Studio UI                  Pick visual style (preset or custom)
Done — hand off                 ▶ Start Generation
                                  (auto-pauses on credits, auto-resumes)
                                  (ntfy ping when thumbnails are ready)
                                Pick thumbnail
                                Upload to YouTube
```

**Rule:** Claude Code handles title + script only. Everything after that happens in the Studio UI. The user never needs to run terminal commands after `/start`.

---

## /start — step-by-step

Run `/start` when the user wants to make a video. Follow these steps in order, do not skip.

### Step 1 — Brainstorm

Ask the user what topic they want. If they have one, clarify angle. If not, suggest 3 strong candidates with one-line hooks.

Confirm the final title before writing anything.

### Step 2 — Write the script

Follow `workflow/script-generation-prompt.md` exactly:

- **Research first** — use WebSearch; gather facts, stats, stories
- **Continuous prose only** — no headings, no timestamps, no line breaks between sentences
- **Length:** 4–6 min at ~130 wpm = 520–780 words
- **Structure:** Hook (15s) → Problem/Conflict → Explanation → Payoff/Insight → Memorable closing line
- **Tone:** Conversational, never lecture-y; stickman channel = light and educational

Show the full script to the user. Iterate until approved. Do not proceed until the user says the script is good.

### Step 3 — Create the project

After the script is approved, run these two commands:

```bash
bash scripts/new_project.sh "Exact Approved Title Here"
```

Note the slug printed (e.g. `why-we-dream`). Then write the script:

```bash
python3 - <<'PYEOF'
import pathlib
slug = "the-slug-here"
script = """Paste the full approved script here."""
p = pathlib.Path("projects") / slug / "01-script" / "Script.txt"
p.write_text(script.strip() + "\n", encoding="utf-8")
print("Written:", p, f"({p.stat().st_size} bytes)")
PYEOF
```

Verify the script file was written (check the byte count is non-zero).

### Step 4 — Start Studio UI (if not already running)

```bash
bash scripts/status_studio.sh || bash scripts/start_studio.sh
```

### Step 5 — Hand off

Tell the user:

> Script is ready. Open **http://127.0.0.1:47829**, select "**[Title]**" in the sidebar, then upload your audio and transcript. The UI will walk you through the rest.

**Stop here.** Do not run anything else. The Studio UI owns everything from this point.

---

## For multiple videos in one session

Repeat Steps 1–3 for each additional video. Each video gets its own project. They queue up independently in the Studio UI and can be processed one at a time.

---

## Commands Claude runs (never ask the user to run these)

| Command | Purpose |
|---------|---------|
| `bash scripts/new_project.sh "Title"` | Create project after script approved |
| `bash scripts/status_studio.sh` | Check if Studio is up |
| `bash scripts/start_studio.sh` | Start Studio (detached, survives shell exit) |
| `bash scripts/stop_studio.sh` | Shut down Studio |
| `PIPELINE_ROOT=projects/<slug> python3 scripts/preflight.py` | Diagnose pipeline issues |

---

## Studio UI — what it does (for context)

The Studio UI at `http://127.0.0.1:47829` handles everything after the script:

1. **Upload** — audio (.mp3) and TurboScribe transcript (.txt)
2. **Style** — choose from visual presets or define a custom style prompt
3. **Generate** — validates, queues the project; pipeline runs automatically
   - Image generation auto-pauses when Codex credits run out
   - Auto-resumes when credits reset — no user action needed
   - ntfy notification fires when thumbnails are ready
4. **Thumbnails** — pick from 3 AI-generated variants
5. **YouTube** — one-click upload from the UI

All state is file-based. No database, no auth, no external services.

---

## Project structure

```
projects/<slug>/
  project.json              ← status, style settings
  01-script/Script.txt      ← written by Claude in /start
  02-audio/                 ← user uploads narration .mp3 via Studio UI
  03-transcript/            ← user uploads TurboScribe .txt via Studio UI
  04-manifest/              ← auto-generated frame plan
  05-images/                ← AI-generated frames
  06-output/final.mp4       ← rendered video
  07-upload/                ← YouTube credentials (shared symlink)
  tracker/overnight.log     ← pipeline log
  tracker/thumbs/           ← thumbnail variants v1/v2/v3
```

Queue: `tracker/queue.json` — list of `{id, title, status}`

---

## queue_status values

| Status | Meaning |
|--------|---------|
| `upload` | Waiting for audio + transcript uploads |
| `style` | Files ready, waiting for style selection |
| `queued` | Style set, in queue |
| `running` | Pipeline generating |
| `thumbnails` | Generation done, user picks thumbnail |
| `done` | Uploaded to YouTube |
| `failed` | Error — check `tracker/overnight.log` |

---

## Hard rules

- **Never** tell the user to run `python3 scripts/...` pipeline commands
- **Never** upload to YouTube from Claude Code — always let the user do it in Studio UI
- **Never** reference Supabase, any review page, or external sync services
- **Never** start the pipeline yourself — Studio UI does it after the user clicks Start
- **Do not** call `start_studio.sh` if Studio is already responding on port 47829
- **Always** verify the script file has non-zero bytes after writing it

---

## Script quality rules (from workflow/script-generation-prompt.md)

- Research first — never write from memory alone
- No headings, no bullet points, no timestamps in the script file
- Every sentence must be speakable aloud naturally
- Hook must create curiosity or tension in the first 15 seconds
- Closing line should be memorable — the thing the viewer quotes
- Stickman aesthetic = clear, slightly absurd, always visual; write for images that will be generated

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Studio not loading | `bash scripts/start_studio.sh` |
| Preflight errors | `PIPELINE_ROOT=projects/<slug> python3 scripts/preflight.py` |
| Generation stuck on credits | Normal — auto-resumes; check log to confirm |
| Queue not moving | Studio UI auto-restarts queue runner when user clicks Start |
| Script file empty | Re-run the python3 write command; check the slug matches |
