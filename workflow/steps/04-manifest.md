# 05 — Manifest

Requires `03-transcript/transcript.txt` + `02-audio/Combined.mp3`.

~2s frames, up to 4s at natural breaks.

```bash
python3 scripts/02_manifest/build_plan.py
python3 scripts/02_manifest/build_plan.py refresh   # after images are generated
```

Output in **`04-manifest/`**:
- `image_cut_plan.txt`
- `image_regen_manifest.csv`
- `image_regen_progress.json`
