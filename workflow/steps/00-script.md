# 01 — Script (`01-script/Script.txt`)

## When it starts

**Right after** the user gives the project title/topic (step 0) and `01-script/Script.txt` is still empty:

1. **Offer** both paths in one short message:
   - *"Want me to write the script for you?"* (you follow this prompt)
   - *"Or paste your own into `01-script/Script.txt`"*
2. **If they say yes** (write it, go ahead, do the script, etc.) → research + write immediately; no extra confirmation.
3. **If they gave title + script request in one message** → skip the offer; write immediately.
4. **If they paste their own** → wait for **done**.

## Who writes it

- **Assistant** — when user accepts the offer or asks in one go.
- **User** — paste into `01-script/Script.txt` instead.

## Mandatory prompt

Follow **`workflow/script-generation-prompt.md`** exactly:

1. **Research first** — web search; multiple reliable sources; no writing until the topic is clear.
2. **Structure** — immersion hook → stakes → pivot → 3-layer solution chain → threshold → moral inversion → subscribe CTA → landing line.
3. **Voice & rules** — as specified in that file (second person, dry humor, curiosity gaps, etc.).
4. **Output** — save to `01-script/Script.txt`:
   - Raw narration only
   - No headings, timestamps, or markdown
   - No line breaks (one continuous prose block)
   - Under 5000 characters (~5 min spoken)

Replace `[[TOPIC]]` with `project.json` → `name`.

## After save

Show the user a **short** preview (first ~2 sentences) and character count.
User says **done** to advance to style / audio steps.
