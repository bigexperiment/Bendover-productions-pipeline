# 04 — Transcript

**Not the same as `01-script/Script.txt`.**

Generated automatically — no manual export needed. Once `02-audio/` has a
narration file, the Studio UI runs local Whisper (`.venv-whisper`,
`scripts/01_audio/generate_transcript.py`, model `medium.en`) and writes
**`03-transcript/transcript.txt`** itself, with a progress bar in the UI.
The queue advances to the style step automatically once it's done.

Output format (`[M:SS] text` per line — same shape `build_plan.py` already
parses):

```
[0:00] Picture the dream, a million followers,
[0:04] brands sliding into your DMs...
```

Retry from the UI (**Retry transcription**) if a run fails or the audio
gets replaced. Manual override still works if ever needed — write directly
to `03-transcript/transcript.txt` in any of these formats:

```
[0:00:05] You woke up this morning.
[0:00:12] Maybe you checked your phone...
```

```
(0:00) First line. (0:04) Next line.
```

SRT subtitle format also works.
