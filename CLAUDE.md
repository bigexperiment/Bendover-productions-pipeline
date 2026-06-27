# Bendover Productions Pipeline

AI-assisted YouTube video pipeline. Stickman educational explainer channel.

## How to start a new video session

Run `/start` — I'll brainstorm ideas with you, write scripts, set up the project queue, then send you to the Studio UI to upload audio + transcripts.

## Full workflow

```
Claude Code (/start)          Studio UI (http://127.0.0.1:47829)
─────────────────────         ─────────────────────────────────────
1. Brainstorm ideas      →    (already has title + script)
2. Write / approve script
3. Add to queue          →    Upload audio (.mp3)
   Repeat for more           Upload transcript (.txt from TurboScribe)
   videos                    Pick visual style
                             "Approve & add to queue"
                        →    Pipeline runs automatically:
                             frames → render → 3 thumbnails → description
                             (auto-pauses/resumes on credit limits)
                        →    Pick thumbnail
                             Upload to YouTube
```

## Key commands

| Command | What it does |
|---------|-------------|
| `/start` | Start a new video session (brainstorm → script → queue) |
| `bash scripts/start_studio.sh` | Start the Studio UI server |
| `bash scripts/start_queue.sh` | Start the pipeline queue runner |
| `bash scripts/stop_studio.sh` | Stop Studio UI |
| `python3 scripts/clear_workspace.py` | Reset root workspace (not project dirs) |

## Project structure

Each video lives in `projects/<slug>/`:
```
projects/
  my-video-slug/
    project.json          ← title, style, status
    01-script/Script.txt  ← written by AI in /start session
    02-audio/             ← user uploads narration mp3
    03-transcript/        ← user uploads TurboScribe txt
    04-manifest/          ← auto-generated
    05-images/            ← AI-generated frames
    06-output/final.mp4   ← rendered video
    07-upload/            ← symlink to shared YouTube credentials
    tracker/overnight.log ← per-project pipeline log
```

Queue state lives in `tracker/queue.json`. Pipeline runner reads it in order.

## Studio UI

The server runs on port 47829. Start with `bash scripts/start_studio.sh`.

Project statuses: `script → upload → style → queued → running → thumbnails → done`

## Technical notes

- `PIPELINE_ROOT` env var points scripts at a project directory
- YouTube credentials are shared: `07-upload/` at repo root, symlinked per project
- Credits auto-pause/resume: 5-hour and weekly Codex windows tracked
- ntfy alerts at: pipeline start, each milestone, completion
- Python for YouTube upload: `/Users/ganesh/miniconda3/bin/python3` (conda 3.10.8 — has google-auth)
