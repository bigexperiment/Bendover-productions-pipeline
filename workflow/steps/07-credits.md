# 07 — Credits

**Script:** `scripts/07_credits/fetch_codex_usage.py`

```bash
python3 scripts/07_credits/fetch_codex_usage.py --force
cat tracker/usage.json
```

When stopped, tell user:
- `stop_reason` and `five_hour.reset_in`
- `done_frames` / `total_frames` from `image_regen_progress.json`
- Resume image generation per [04-images.md](04-images.md) when user confirms credits back
