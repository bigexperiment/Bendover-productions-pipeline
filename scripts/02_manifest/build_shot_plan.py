#!/usr/bin/env python3
"""Creative-director pass: turn the mechanical per-frame transcript slices into a
real shot plan — full-video context, a consistent recurring cast, varied shot
types (scene / text_card / diagram / closeup), and sparing, deliberate on-screen
text instead of none-or-everywhere.

Runs after build_plan.py (which owns frame *timing*) and before generate_images.py
(which turns each shot into a picture). Writes 04-manifest/shot_plan.json and
copies each frame's authored `scene` back into the manifest CSV.

If this step fails or is skipped, generate_images.py / image_prompt.py fall back
to the mechanical scene text build_plan.py already wrote — the pipeline still
works, just less interesting.

Usage:
    python3 scripts/02_manifest/build_shot_plan.py
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get("PIPELINE_ROOT") or SCRIPTS_ROOT)
sys.path.insert(0, str(SCRIPTS_ROOT / "scripts"))
from lib.atomic_io import atomic_write_csv, atomic_write_text  # noqa: E402
from lib.folders import CAST_REFERENCE_FILE, MANIFEST_FILE, PROJECT_FILE, SCRIPT_FILE, SHOT_PLAN_FILE  # noqa: E402
from lib.image_prompt import DEFAULT_IMAGE_STYLE  # noqa: E402

BATCH_SIZE = 90  # frames per Codex call — keeps prompts + JSON output comfortably sized
JOB_TIMEOUT_SEC = 15 * 60
IMAGE_JOB_TIMEOUT_SEC = 15 * 60

TEXT_DISCIPLINE = """TEXT DISCIPLINE — do not overdo it:
- Across this whole batch, put text_on_screen on no more than roughly 1 in 8 frames.
- Never give two consecutive frames text_on_screen.
- Never use text_on_screen to restate a full sentence — 1 to 5 words max, always.
- Default to type "scene" or "diagram" with text_on_screen null unless there's a strong
  reason (a specific stat, a newly named term, a short numbered list, a quote)."""

VARIETY_RULES = """VARIETY — avoid monotony:
- Do not illustrate every frame the same way (e.g. not just "a stickman standing there
  talking"). Mix wide scene shots, close-ups on reactions, and simple diagrams for
  numbers or comparisons.
- Give consecutive frames a sense of flow — an action started in frame N can land or
  pay off in frame N+1, instead of every frame being an unrelated still.
- Reuse the recurring cast and let a visual motif from earlier frames pay off later."""

SIMPLICITY_RULES = """SIMPLICITY — the viewer has under 3 seconds per frame, so each one must read instantly:
- One clear subject doing one clear thing. At most ONE supporting element besides the
  main character(s) — never a scattered collection of props, icons, or background objects.
- Never write a scene with a list of things happening ("X, while Y, and also Z in the
  background") — pick the single strongest image and cut the rest.
- Ban icon clusters and UI-soup entirely: no scattered gear/lock/trash/chart/app icons
  floating around a character. If you need to represent an abstract idea, use ONE simple
  symbol or metaphor, not a collage of them.
- Backgrounds are plain or empty by default. Only add background detail if the story
  genuinely needs that location established, and even then keep it to one or two shapes.
- If a scene description is hard to summarize in a single short sentence, it is too busy —
  simplify it until it is."""


def load_project() -> dict:
    if PROJECT_FILE.is_file():
        return json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    return {}


def load_manifest_rows() -> list[dict]:
    if not MANIFEST_FILE.is_file():
        raise FileNotFoundError(f"Manifest not found: {MANIFEST_FILE} — run build_plan.py first")
    with MANIFEST_FILE.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_batch_prompt(
    *,
    project: dict,
    script_text: str,
    cast_so_far: dict[str, str],
    rows: list[dict],
    batch_index: int,
    total_batches: int,
    total_frames: int,
    start_num: int,
    out_path: Path,
) -> str:
    title = (project.get("name") or project.get("title") or "Untitled video").strip()
    brief = (project.get("video_brief") or "").strip()
    frame_lines = "\n".join(f"[{row['timestamp']}] {row['filename']} | {row['transcript']}" for row in rows)
    cast_block = (
        "\n".join(f"- {name}: {desc}" for name, desc in cast_so_far.items())
        if cast_so_far
        else '(none yet — invent 1 or 2 simple, memorable recurring characters for this video '
        "and describe them precisely enough to draw the same way every time)"
    )

    return f"""You are the creative director for a short-form YouTube explainer video. Design the
VISUAL SHOT PLAN for a batch of frames so the finished video feels like a mixed,
entertaining sequence — not a monotonous slideshow of literal illustrations.

VIDEO
Title: {title}
Brief: {brief or "(none provided)"}
Full narration script (read this fully — every frame you design is one moment inside
this single continuous video, not a standalone poster):
{script_text}

RECURRING CAST (reuse these consistently across every batch of this video):
{cast_block}

FRAMES IN THIS BATCH (batch {batch_index}/{total_batches}, frames {start_num}-{start_num + len(rows) - 1} of {total_frames}):
Each line is [timestamp] filename | narrator's exact words for that frame:
{frame_lines}

YOUR JOB
For each frame above, decide:
- type: one of "scene" (a normal illustrated moment), "text_card" (mostly bold
  on-screen words), "diagram" (a simple split/comparison/flow diagram), "closeup"
  (a tight shot on one character's reaction)
- scene: a specific, visual, non-literal description of what's on screen (avoid just
  restating the narration in picture form — show it through action, metaphor,
  expression, or a diagram)
- characters: which cast members (if any) appear in this frame
- text_on_screen: null by default; only set real words when type is "text_card" or a
  diagram needs a short label

{TEXT_DISCIPLINE}

{VARIETY_RULES}

{SIMPLICITY_RULES}

OUTPUT
Write ONLY valid JSON to the file at this exact path: {out_path}
Shape (one entry per frame above, in the same order, using the exact filenames given):
{{
  "cast": {{ "Name": "short visual description, precise enough to draw consistently" }},
  "frames": [
    {{"filename": "0_02.png", "type": "scene", "scene": "...", "characters": ["Name"], "text_on_screen": null}}
  ]
}}
The "cast" object must include every character you used (existing ones repeated with
their same description, plus any new ones you invented). The "frames" array must have
exactly {len(rows)} entries. Do not include markdown fences or any commentary. Do not
create or modify any other file.
"""


def build_cast_reference_prompt(project: dict, cast: dict[str, str], out_path: Path) -> str:
    title = (project.get("name") or project.get("title") or "Untitled video").strip()
    cast_lines = "\n".join(f"- {name}: {desc}" for name, desc in cast.items())
    style = (project.get("image_style") or DEFAULT_IMAGE_STYLE).strip()

    return f"""Create a character reference sheet for a YouTube explainer video titled "{title}".

Style:
{style}

Show each of these recurring characters side by side, clearly labeled with their name
underneath, in a neutral standing/floating pose, on a plain white background:
{cast_lines}

Every character must be rendered in the exact same flat, evenly-lit coloring style with
the same outline thickness and level of detail — no character should look more polished,
more shaded, or more detailed than another. This image is the single source of truth for
how each character looks for the rest of the video, so get proportions, colors, and style
locked in clearly.

Output:
- 16:9 landscape
- Use the built-in image_gen tool exactly once
- Save to: {out_path.relative_to(ROOT)}
- After saving, verify the file exists at {out_path}

Generate exactly one image. Do not create any other files.
"""


def generate_cast_reference(project: dict, cast: dict[str, str]) -> bool:
    """Best-effort: renders one reference sheet so every later frame can be conditioned
    on it instead of re-imagining each character from a text description alone. This is
    what keeps a character from looking fully-shaded in one frame and flat/crude in the
    next — Codex has no memory between per-frame calls, only what it's shown."""
    if not cast:
        return False

    CAST_REFERENCE_FILE.unlink(missing_ok=True)
    prompt = build_cast_reference_prompt(project, cast, CAST_REFERENCE_FILE)
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    try:
        subprocess.run(
            [
                "codex", "exec",
                "--enable", "image_generation",
                "-s", "workspace-write",
                "--dangerously-bypass-approvals-and-sandbox",
                "-C", str(ROOT),
                prompt,
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=IMAGE_JOB_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        pass
    return CAST_REFERENCE_FILE.is_file()


def run_codex_text(prompt: str) -> None:
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    subprocess.run(
        [
            "codex", "exec",
            "-s", "workspace-write",
            "--dangerously-bypass-approvals-and-sandbox",
            "-C", str(ROOT),
            prompt,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=JOB_TIMEOUT_SEC,
    )


def run_batch(
    *,
    project: dict,
    script_text: str,
    cast_so_far: dict[str, str],
    rows: list[dict],
    batch_index: int,
    total_batches: int,
    total_frames: int,
    start_num: int,
) -> dict:
    batch_out = SHOT_PLAN_FILE.parent / f"shot_plan_batch_{batch_index}.json"
    batch_out.unlink(missing_ok=True)

    prompt = build_batch_prompt(
        project=project,
        script_text=script_text,
        cast_so_far=cast_so_far,
        rows=rows,
        batch_index=batch_index,
        total_batches=total_batches,
        total_frames=total_frames,
        start_num=start_num,
        out_path=batch_out,
    )
    run_codex_text(prompt)

    if not batch_out.is_file():
        raise RuntimeError(f"batch {batch_index}/{total_batches}: Codex did not write {batch_out.name}")

    data = json.loads(batch_out.read_text(encoding="utf-8"))
    batch_out.unlink(missing_ok=True)

    frames = data.get("frames") or []
    expected = {row["filename"] for row in rows}
    got = {frame.get("filename") for frame in frames}
    if len(frames) != len(rows) or got != expected:
        raise RuntimeError(
            f"batch {batch_index}/{total_batches}: expected {len(rows)} frames matching "
            f"manifest filenames, got {len(frames)} ({len(got & expected)} matching)"
        )
    return data


def merge_shot_plan(batches: list[dict]) -> dict:
    cast: dict[str, str] = {}
    frames: list[dict] = []
    for batch in batches:
        cast.update(batch.get("cast") or {})
        frames.extend(batch.get("frames") or [])
    return {"cast": cast, "frames": frames}


def apply_scenes_to_manifest(rows: list[dict], shot_plan: dict) -> None:
    scene_by_filename = {f["filename"]: f.get("scene", "") for f in shot_plan["frames"]}
    for row in rows:
        scene = scene_by_filename.get(row["filename"])
        if scene:
            row["scene"] = scene
    fieldnames = list(rows[0].keys()) if rows else ["timestamp", "filename", "scene", "transcript", "status", "duration"]
    atomic_write_csv(MANIFEST_FILE, fieldnames, rows)


def main() -> int:
    project = load_project()
    rows = load_manifest_rows()
    if not rows:
        print("ERROR: manifest has no rows — run build_plan.py first", file=sys.stderr)
        return 1

    if not SCRIPT_FILE.is_file():
        print(f"ERROR: script not found at {SCRIPT_FILE}", file=sys.stderr)
        return 1
    script_text = SCRIPT_FILE.read_text(encoding="utf-8").strip()

    SHOT_PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)

    total = len(rows)
    batches = [rows[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    total_batches = len(batches)

    cast_so_far: dict[str, str] = {}
    results: list[dict] = []
    start_num = 1
    for index, batch_rows in enumerate(batches, start=1):
        print(f"Directing batch {index}/{total_batches} ({len(batch_rows)} frames)...")
        result = run_batch(
            project=project,
            script_text=script_text,
            cast_so_far=cast_so_far,
            rows=batch_rows,
            batch_index=index,
            total_batches=total_batches,
            total_frames=total,
            start_num=start_num,
        )
        cast_so_far.update(result.get("cast") or {})
        results.append(result)
        start_num += len(batch_rows)

    shot_plan = merge_shot_plan(results)
    atomic_write_text(SHOT_PLAN_FILE, json.dumps(shot_plan, indent=2) + "\n")
    apply_scenes_to_manifest(rows, shot_plan)

    text_frames = sum(1 for f in shot_plan["frames"] if f.get("text_on_screen"))
    print(f"Wrote {SHOT_PLAN_FILE} — {len(shot_plan['frames'])} frames, cast: {list(shot_plan['cast'])}")
    print(f"Text-card frames: {text_frames}/{len(shot_plan['frames'])} ({text_frames / len(shot_plan['frames']) * 100:.0f}%)")

    print("Generating cast reference sheet (keeps every frame's character rendering consistent)...")
    if generate_cast_reference(project, shot_plan["cast"]):
        print(f"Wrote {CAST_REFERENCE_FILE}")
    else:
        print("WARNING: cast reference generation failed — frames will fall back to text-only cast descriptions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
