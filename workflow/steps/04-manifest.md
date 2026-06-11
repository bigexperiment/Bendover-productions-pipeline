# 05 — Manifest

Requires `03-transcript/transcript.txt` + one narration file in `02-audio/`.

~2s frames, max 3s at natural breaks.

```bash
python3 scripts/02_manifest/build_plan.py
python3 scripts/02_manifest/build_plan.py refresh   # after images are generated
```

Output in **`04-manifest/`**:
- `image_cut_plan.txt`
- `image_regen_manifest.csv`
- `image_regen_progress.json`
