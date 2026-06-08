# 04 — Images

**Script:** `scripts/03_images/generate_images.py`

Requires `style_approved: true` in `project.json`.

## Before starting

```bash
python3 scripts/02_manifest/build_plan.py          # cut plan + manifest
python3 scripts/02_manifest/build_plan.py refresh  # update done/pending counts
python3 scripts/07_credits/fetch_codex_usage.py --force        # check credits
```

Manifest rows start as `pending`. Every row should get a PNG in `05-images/` during this step.

## Generate (parallel Codex)

```bash
python3 scripts/03_images/generate_images.py          # 5 workers (default)
python3 scripts/03_images/generate_images.py 10     # 10 workers
python3 scripts/03_images/generate_images.py --force  # ignore credit stop
```

Start the tracker while generating:

```bash
scripts/start_studio.sh   # http://127.0.0.1:47829/
```

The script:
1. Reads all `pending` rows from `image_regen_manifest.csv`
2. Runs N Codex workers in parallel (credit-gated)
3. Refreshes manifest progress after each completion
4. **Stops** when Codex credits hit 0% — tell user reset time ([07-credits.md](07-credits.md))
5. Resume when user confirms credits back (`--force` to override)

## Monitor

```bash
cat image_regen_progress.json
cat tracker/usage.json
scripts/start_studio.sh
```

## Done when

`pending_frames: 0` in `image_regen_progress.json` → set `step: "render"`.
