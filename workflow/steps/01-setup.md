# 01 — Setup

## Project name (`project.json`)

Ask the user for the video/project name. Save it to `name` in `project.json` at repo root.

Fresh clone: copy `project.json.example` → `project.json` (project file is local-only, not in git).

After updating, tell the user: **to change any setting later** (name, style, workers, privacy, etc.), edit `project.json` directly — or ask in chat.

## Default workspace files

These exist **empty** in every fresh or reset workspace (user fills them in):

| File | Step |
|------|------|
| `01-script/Script.txt` | 1 — paste written script |
| `03-transcript/transcript.txt` | 4 — paste TurboScribe export |

Cleanup clears their contents but **keeps the files**. Other numbered folders use `.gitkeep` until generated content appears.

## Folders (numbered = workflow step)

| Folder | You add |
|--------|---------|
| `01-script/Script.txt` | Written script (empty file exists by default) |
| `02-audio/` | Narration MP3 (e.g. `narration.mp3`) |
| `03-transcript/transcript.txt` | TurboScribe export (empty file exists by default) |
| `04-manifest/` | Auto — assistant builds |
| `05-images/` | Auto — generated frames |
| `06-output/` | Auto — rendered video |
| `07-upload/` | YouTube OAuth + thumbnail |

Style → `project.json` at repo root → `image_style` (no folder — step 2).

Chat workflow in `workflow/README.md`. No UI until image generation.
