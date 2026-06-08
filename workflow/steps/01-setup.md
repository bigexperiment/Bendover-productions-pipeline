# 01 — Setup

## Project name (`project.json`)

Ask the user for the video/project name. Save it to `name` in `project.json` at repo root.

After updating, tell the user: **to change any setting later** (name, style, workers, privacy, etc.), edit `project.json` directly — or ask in chat.

## Folders (numbered = workflow step)

| Folder | You add |
|--------|---------|
| `01-script/Script.txt` | Written script |
| `02-audio/` | Narration MP3 |
| `03-transcript/transcript.txt` | TurboScribe export |
| `04-manifest/` | Auto — assistant builds |
| `05-images/` | Auto — generated frames |
| `06-output/` | Auto — rendered video |
| `07-upload/` | YouTube OAuth + thumbnail |

Style → `project.json` at repo root → `image_style` (no folder — step 2).

Chat workflow in `workflow/README.md`. No UI until image generation.
