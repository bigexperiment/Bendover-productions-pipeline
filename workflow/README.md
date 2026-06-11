# Workflow

Cursor loads `.cursor/rules/video-workflow.mdc` on every chat.

## Numbered folders

| # | Folder | Contents |
|---|--------|----------|
| 1 | `01-script/` | `Script.txt` — assistant offers to write (see script-generation-prompt.md) or user pastes |
| 2 | — | `image_style` in `project.json` (repo root) |
| 3 | `02-audio/` | one narration MP3 (e.g. `narration.mp3`) |
| 4 | `03-transcript/` | `transcript.txt` — empty by default; TurboScribe export |
| 5 | `04-manifest/` | frame list CSV, cut plan (auto-generated) |
| 6 | `05-images/` | generated PNG frames |
| 7 | `06-output/` | rendered MP4 |
| 8 | `07-upload/` | YouTube OAuth, token, thumbnail |

## Chat steps

Assistant runs all scripts — user never gets terminal commands.

| # | Need | Who |
|---|------|-----|
| 0 | `name` | **Offer:** user's own question title **or** assistant suggests one (random seed via `scripts/suggest_topic.py` + [evolutionary-explainer-topics skill](../.cursor/skills/evolutionary-explainer-topics/SKILL.md)); save to `project.json`; mention user can change any settings there |
| 1 | `01-script/Script.txt` | **Right after step 0:** assistant **offers** to write script ([script-generation-prompt.md](script-generation-prompt.md)) or user pastes own; if yes → assistant researches + writes; **done** |
| 2 | `image_style` | User describes style |
| 3 | one file in `02-audio/` | User adds narration MP3, says **done** |
| 4 | `03-transcript/transcript.txt` | User pastes TurboScribe export into empty file, says **done** |
| 5 | `04-manifest/` | Assistant runs preflight, then builds |
| 6 | `style_approved` | User approves samples |
| 7 | all frames in `05-images/` | Assistant starts studio + generates |
| 8 | `06-output/final.mp4` | Assistant renders |
| 9a | title + `07-upload/thumbnail.png` | Assistant drafts metadata + thumbnail, **stops** — user must approve |
| 9b | `youtube_video_id` | Assistant uploads **only after** user approves title + thumbnail (OAuth popup if first time) |
| 10 | fresh workspace | Optional cleanup — assistant warns user to save outputs, then writes + runs Python reset on the fly |

## Step docs

| Step | Doc | Script |
|------|-----|--------|
| Setup | [steps/01-setup.md](steps/01-setup.md) | — |
| Script | [steps/00-script.md](steps/00-script.md) · [script-generation-prompt.md](script-generation-prompt.md) | — |
| Audio | [steps/02-audio.md](steps/02-audio.md) | — |
| Transcript | [steps/03-transcript.md](steps/03-transcript.md) | — |
| Preflight | [preflight.md](preflight.md) | `scripts/preflight.py` |
| Manifest | [steps/04-manifest.md](steps/04-manifest.md) | `scripts/02_manifest/build_plan.py` |
| Images | [steps/04-images.md](steps/04-images.md) | `scripts/03_images/generate_images.py` |
| Render | [steps/05-render.md](steps/05-render.md) | `scripts/04_render/render_draft_video.py` |
| Thumbnail | [thumbnail.md](thumbnail.md) | `scripts/05_publish/generate_thumbnail.py` |
| Upload | [steps/06-publish.md](steps/06-publish.md) | `scripts/05_publish/upload_to_youtube.py` |
| Cleanup | [steps/08-cleanup.md](steps/08-cleanup.md) | none — assistant generates Python on the fly |

```bash
scripts/status_studio.sh   # check first — do not restart if healthy
scripts/start_studio.sh    # detached supervisor; idempotent
scripts/stop_studio.sh
```

**Rules:** [rules.md](rules.md) (Studio section — detached start, check status before start)
