#!/usr/bin/env python3
"""Add an authored, per-shot Imagen prompt to the timing manifest.

Generation is not allowed to start until this file exists and every row has a
non-empty prompt. The prompt is intentionally scoped to one audio beat.
"""
from __future__ import annotations

import csv
import os
import re
from difflib import SequenceMatcher
from pathlib import Path


STYLE = (
    "minimal educational cartoon, thick black outlines, flat colors, almost no shading, "
    "one clear subject doing one action, empty background, limited palette, no text, "
    "no collage, no unrelated objects, 16:9 landscape"
)

STYLE_LOCK = (
    "STYLE LOCK: keep the same flat hand-drawn educational cartoon language in every frame: "
    "thick black outlines, flat limited colors, almost no shading, simple expressive characters, "
    "plain cream/white background, clean 16:9 composition; never photorealistic, 3D, anime, "
    "detailed painting, stick figures, or a different line style."
)


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def semantic_contexts(beats: list[str], sentences: list[str]) -> list[str]:
    """Map beats to their sentence, tolerating transcription spacing/punctuation.

    The old character-offset search failed on harmless ASR variants such as
    ``Papermaking`` versus ``Paper making`` and then shifted every later beat
    onto the wrong sentence. Matching normalized compact text first, followed
    by a monotonic fuzzy fallback, keeps the semantic context attached to the
    audio beat that actually contains it.
    """
    def compact(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    def words(value: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", value.lower()))

    results: list[str] = []
    start_index = 0
    for beat in beats:
        needle = compact(beat)
        beat_words = words(beat)
        exact = next(
            (index for index in range(start_index, len(sentences)) if needle and needle in compact(sentences[index])),
            None,
        )
        if exact is None:
            candidates = list(range(start_index, len(sentences))) or list(range(len(sentences)))
            def score(index: int) -> tuple[float, int]:
                sentence_words = words(sentences[index])
                overlap = len(beat_words & sentence_words) / max(1, len(beat_words))
                fuzzy = SequenceMatcher(None, needle, compact(sentences[index])).ratio()
                return (overlap * 0.7 + fuzzy * 0.3, -index)
            exact = max(candidates, key=score) if candidates else 0
        results.append(sentences[exact] if sentences else beat)
        start_index = min(exact, max(0, len(sentences) - 1))
    return results


def make_prompt(text: str, context: str) -> str:
    return (
        f"Create one image for this exact narration beat: {text}\n"
        f"Full semantic sentence: {context}\n"
        "VISUAL CONTRACT: the short narration beat is the primary instruction. "
        "Depict the concrete subject, action, or consequence named by that beat. "
        "Use the full sentence only to resolve fragments; never replace the beat with a generic image for the topic. "
        "If the beat describes distribution, show distribution; if it describes falling cost, show falling cost; "
        "if it describes comparison, show comparison.\n"
        "Show one clear visual moment, at most one supporting object, and no unrelated historical details. "
        "No readable words, labels, captions, arrows, icons, collage, magic effects, or decorative symbols. "
        f"{STYLE_LOCK} Style: {STYLE}. The viewer must understand it in one second."
    )


def main() -> int:
    root = Path(os.environ.get("PIPELINE_ROOT") or Path(__file__).resolve().parents[2])
    path = root / "04-manifest" / "image_regen_manifest.csv"
    script = root / "01-script" / "Script.txt"
    sentences = split_sentences(script.read_text(encoding="utf-8"))
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    if "prompt" not in fields:
        fields.append("prompt")
    if "context" not in fields:
        fields.append("context")
    contexts = semantic_contexts([row["transcript"].strip() for row in rows], sentences)
    for row, context in zip(rows, contexts):
        row["context"] = context
        row["prompt"] = make_prompt(row["transcript"].strip(), row["context"])
        row["status"] = "pending"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote authored image manifest: {path} ({len(rows)} prompts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
