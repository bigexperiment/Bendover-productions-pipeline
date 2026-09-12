# Fully automated production flow

The intended unattended flow is:

```text
AI topic selection
  -> research + script
  -> Google TTS (en-US-Chirp3-HD-Charon)
  -> transcript
  -> timestamped shot plan (one concrete visual per audio beat, max 3 seconds)
  -> minimal scene prompt per manifest row
  -> AI images
  -> image/audio synchronization
  -> MP4 render
  -> thumbnail + metadata
  -> YouTube upload
```

## Non-negotiable sync gates

Every manifest row must contain the exact timed narration beat, its complete
sentence-level semantic context, and one concrete visual action. The image
generator writes provenance beside every PNG: the manifest fingerprint and the
PNG's SHA-256 hash. `verify_frames.py` regenerates any legacy or changed frame;
`validate_frames.py` then refuses to render if context, prompt, provenance,
duplicate, or pixel-integrity checks fail. A failed frame QA now aborts the
runner instead of rendering a video that still needs human repair.

Image generation accepts `workers` followed by an optional `limit`, for example:

```bash
PIPELINE_ROOT=/abs/path/to/project python3 -u scripts/03_images/generate_images.py 5 85
```

This means five concurrent workers and at most 85 manifest rows.

## Current completed piece

Narration is automatic. With ADC already configured, generate audio for a project:

```bash
python3 scripts/tts_generate.py projects/<slug>
```

It reads `01-script/Script.txt` and writes `02-audio/narration.mp3` using
`en-US-Chirp3-HD-Charon`.

## What the final controller must do

`scripts/autopilot.py` should own the complete sequence and resume from the last
successful phase. It should use one fixed style and automatically choose the
first valid thumbnail. The controller must write a status file and retry failed
steps so no UI approval is required.

The existing repository already provides the manifest, image generation,
rendering, thumbnail, and YouTube stages. The remaining integration work is to:

1. Add a model-backed topic/script generator.
2. Call `tts_generate.py` instead of waiting for uploaded audio.
3. Start transcript, manifest, creative shot-plan, per-row image prompt, image, render, thumbnail, and upload stages in order.
4. Add retry/resume handling around every stage.

The topic/script model provider still needs to be selected and authenticated;
Google Cloud TTS credentials do not provide text generation or image generation.
