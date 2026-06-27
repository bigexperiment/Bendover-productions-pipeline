# /start — Video session setup

Run this workflow whenever the user wants to set up one or more videos for the pipeline.

## What you do

You are the AI orchestrator. Walk the user through setting up their video queue, one video at a time. After all videos are configured, launch the Studio UI where they'll handle audio + transcript uploads.

The server must be running first. Check and start it:
```
bash scripts/start_studio.sh
```

## Step-by-step flow (repeat for each video)

### 1. Brainstorm / choose a title

Ask the user: **"What's the video about? Give me a topic, keyword, or rough idea — or say 'brainstorm' and I'll suggest some."**

- If they give a topic/title directly → use it
- If they say "brainstorm" → suggest 5 specific, curiosity-driven YouTube video ideas (title + one-line brief each). Let them pick one or mix ideas.
- Once a title is confirmed, also confirm or suggest a one-line brief (what the viewer learns).

### 2. Script

Ask: **"Want me to write the full script, or will you paste it?"**

- If **write**: Write a complete narration script for the video. Educational stickman-explainer style. Spoken words only — no stage directions, no [MUSIC], no host name. Punchy sentences, clear paragraphs. Aim for ~600–900 words (3–5 min video). Show the script to the user. Ask: "Happy with this? Any changes?" — revise until approved.
- If **paste**: Tell them "Paste the script below and I'll save it." Wait for them to paste it. Confirm receipt.

### 3. Save the project

Once title + script are confirmed, call the API to create the project and save the script:

```bash
# 1. Create project (returns project id)
curl -s -X POST http://127.0.0.1:47829/api/projects/create \
  -H 'Content-Type: application/json' \
  -d '{"title": "VIDEO TITLE HERE", "brief": "ONE LINE BRIEF HERE"}'

# 2. Save script (use the id returned above)
curl -s -X POST http://127.0.0.1:47829/api/text-content \
  -H 'Content-Type: application/json' \
  -d '{"kind": "script", "project_id": "PROJECT_ID_HERE", "content": "SCRIPT CONTENT HERE"}'
```

Tell the user: **"✅ [Title] added to queue."**

### 4. More videos?

Ask: **"Want to add another video to the pipeline?"**

- Yes → go back to step 1
- No → proceed to finish

## Finish

Once all videos are added:

1. Print a summary of what's queued:
   ```
   Videos ready for production:
   1. [Title 1]
   2. [Title 2]
   ...
   ```

2. Tell the user:
   **"Open the Studio UI at http://127.0.0.1:47829 — your videos are already there with scripts. For each one, upload the audio file (mp3) and transcript (txt from TurboScribe). Then pick a style and the pipeline runs automatically."**

3. Open the URL if possible:
   ```bash
   open http://127.0.0.1:47829
   ```

## Notes

- Keep tone conversational and quick — don't over-explain
- If the user wants to change the script later they can edit it in the UI
- The UI won't ask for the title again — it's already saved
- Credentials for YouTube are shared across all projects (07-upload/ symlink)
