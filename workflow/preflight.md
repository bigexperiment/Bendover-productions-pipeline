# Preflight — test before build / image gen

**Assistant must run preflight before `build_plan.py` and again before bulk image generation.**

```bash
python3 scripts/preflight.py              # before manifest (step 5)
python3 scripts/preflight.py --images   # before Studio + generate_images (step 7)
```

Exit **0** = safe to continue. Exit **1** = fix errors first (do not run downstream scripts).

## What it checks

| Check | Why |
|-------|-----|
| `project.json` valid + `name`, `image_style`, guides | Image prompts and tracker need these |
| `01-script/Script.txt` non-empty | Source material for metadata later |
| Exactly **one** audio file in `02-audio/` | `build_plan` + render need a single narration |
| `ffprobe` + `ffmpeg` on PATH | Duration probe + final render |
| Audio duration readable and ≥ 10s | Catches corrupt or wrong file |
| `03-transcript/transcript.txt` non-empty | Manifest is transcript-driven |
| Transcript parses (inline, section, or SRT) | Same parser as `build_plan.py` |
| Transcript vs audio drift (warn if > 15s) | Catches wrong export or wrong MP3 |
| `--images`: manifest files exist | Bulk gen needs CSV + cut plan |
| `--images`: `style_approved` (warn) | User should approve samples first |
| `--images`: Studio status (warn if down) | Tracker UI for step 7 |

## When to run

1. **After user says done on transcript (step 4)** → `preflight.py` → if OK, `build_plan.py`
2. **Before starting Studio + `generate_images.py` (step 7)** → `preflight.py --images`

Never skip preflight because the user asked to hurry. Warnings can be acknowledged; **errors block** the next script.
