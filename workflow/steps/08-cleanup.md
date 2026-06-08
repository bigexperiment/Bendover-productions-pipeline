# 10 — Cleanup (optional)

After upload succeeds. Prepares the workspace for the **next** video.

**There is no cleanup script in the repo.** The assistant writes Python on the fly when the user asks for cleanup.

## Before anything runs

Tell the user cleanup is **destructive**. They must save anything they want to keep:

- `06-output/final.mp4`
- YouTube URL / `youtube_video_id` from `project.json`
- `title`, `description`, `tags`
- `07-upload/thumbnail.png`
- `01-script/Script.txt` or other source files

Wait for explicit confirmation. Do not run cleanup unprompted.

## Assistant does

1. Write a one-off Python script (tailored to current folder layout — see `scripts/lib/folders.py`)
2. Script should typically:
   - Clear generated content in `01-script/` … `06-output/` (and tracker logs if needed)
   - Reset `project.json` to a blank template (`step: "setup"`, empty name/title, etc.)
   - **Keep** `07-upload/` OAuth token + `client_secret` unless user says otherwise
3. Run the script yourself
4. Delete the temp script after success (unless user asks to keep it)
5. Set `step: "setup"` in `project.json`

## User says

“clean up” / “reset for next video” / **done** (after saving what they need)
