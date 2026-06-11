---
name: evolutionary-explainer-topics
description: >-
  Brainstorm YouTube explainer video topics in The Thought Vortex style —
  evolutionary anthropology, ancient humans, curiosity-gap question titles.
  Use when the user asks for video topic ideas, title ideas, channel research,
  Thought Vortex-style hooks, or "how did ancient humans" / "why do humans" angles.
---

# Evolutionary Explainer Topic Ideas

Generate **question-format** video topics for stick-figure / educational explainer channels in the style of **The Thought Vortex** (@the_thought_vortex).

## What this style IS

- One **big question** about humans — not era-specific procedural history
- **Ancient humans** as one time bucket (or humans broadly), not "how Victorians did laundry"
- Answer ties **prehistory → why we behave/feel this way today**
- Biology + behavior + light anthropology — visual, relatable, slightly provocative
- **Title is always a question** (see formats below)

## What this style is NOT

Avoid narrow procedural history unless the user explicitly asks for it:

- ❌ How Romans took baths / Victorians did laundry / medieval castle building
- ❌ Infrastructure deep dives (aqueducts, ration books) without a human-behavior hook
- ❌ Pure mechanics with no modern emotional hook ("how did they wake up on time")
- ❌ Statement titles ("Your Ancestors Would KILL for Sugar") — convert to questions

## Reference channel — performance signals

Use these as calibration when ranking new ideas (views at time of research, Jun 2026):

| Views | Title | Pattern |
|-------|-------|---------|
| 1.8M | How Humans Accidentally Created Dogs | accidentally created |
| 275K | Cats Domesticated Humans. We Just Let It Happen. | role reversal *(convert to question for new titles)* |
| 271K | Why are Human Babies So Useless? | why we're weird |
| 184K | How did Ancient Humans Mate? | edgy anthropology |
| 131K | Why Most Ancient Humans Died Before 30 | survival shock |
| 129K | Why Do Humans Want to Pet Everything? | modern behavior |
| 53K | What Happened To The Worst Person In The Tribe? | tribal social |
| 13K | How Humans Accidentally Created Music | accidentally created |
| 3.5K–8.7K | Teeth, sugar, earthquakes, wake-up time | mechanics / niche belief / weaker hook |

**Takeaway:** Winners connect ancient life to **felt human experience today** (pets, babies, cravings, mating, mortality). Underperformers are **narrow mechanics** or **belief trivia** without a personal hook.

---

## Title rules (mandatory)

1. **Question format only** — every suggested title ends with `?`
2. Start with **How**, **Why**, **What**, or **Did**
3. Prefer **Humans** / **Ancient Humans** / **Your Ancestors** — not a specific dynasty or century
4. One idea per title — no subtitles or colons
5. Under ~70 characters when possible (YouTube title comfort zone)
6. Curiosity gap: the answer should feel non-obvious

### Approved title templates

| Template | Example |
|----------|---------|
| How Did Humans Accidentally Create ___? | How Did Humans Accidentally Create Cooking? |
| Why Are Human ___ So ___? | Why Are Human Babies So Useless? |
| Why Do Humans ___? | Why Do Humans Want to Pet Everything? |
| How Did Ancient Humans ___? | How Did Ancient Humans Mate? |
| Why Did Most Ancient Humans ___? | Why Did Most Ancient Humans Die Before 30? |
| What Did Ancient Humans Think ___ Was? | What Did Ancient Humans Think Thunder Was? |
| What Happened to the ___ Person in the Tribe? | What Happened to the Worst Person in the Tribe? |
| Did ___ Really Domesticate Humans? | Did Cats Really Domesticate Humans? |
| Why Would Your Ancestors Kill for ___? | Why Would Your Ancestors Kill for Salt? |

### Statement → question conversion

| Statement (don't use) | Question (use) |
|-----------------------|----------------|
| Cats Domesticated Humans | Did Cats Really Domesticate Humans? |
| Your Ancestors Would KILL for Sugar | Why Would Your Ancestors Kill for Sugar? |
| Ancient Humans Had Perfect Teeth | Why Did Ancient Humans Have Perfect Teeth? |

---

## How to generate new topics (workflow)

Copy this checklist when brainstorming:

```
Topic brainstorm:
- [ ] Step 1: Pick a hook pattern (see below)
- [ ] Step 2: Pick a human universal (body, food, fear, love, sleep, social, animals)
- [ ] Step 3: Frame as ancient-humans or humans-evolution lens
- [ ] Step 4: Add modern relatability ("why you still...")
- [ ] Step 5: Write question title using template
- [ ] Step 6: Score against validation checklist
- [ ] Step 7: Return 10–15 ideas, ranked high → low confidence
```

### Step 1 — Hook patterns (pick one)

1. **Accidentally created** — co-evolution / unintended civilization (dogs, cooking, language)
2. **Why we're weird** — modern behavior explained by evolution (babies, petting, crying)
3. **Role reversal** — X domesticated/changed us more than we changed it (cats, grain, houses)
4. **Survival shock** — mortality, danger, exhaustion stats that surprise viewers
5. **Scarcity craving** — sugar, salt, fat — "your brain still thinks..."
6. **Edgy anthropology** — mating, family, jealousy, death rituals (tasteful, educational)
7. **Tribal social** — freeloaders, gossip, outcasts, hierarchy
8. **Ancient beliefs** — only if paired with strong human emotion (fear, grief, wonder)

### Step 2 — Human universals (mix with hook)

Body · sleep · pain · teeth · babies · aging · death  
Food · hunger · cravings · cooking · sharing meals  
Animals · pets · fear of snakes · domestication  
Social · friends · gossip · jealousy · tribe · loneliness  
Senses · fire · music · laughter · dreams · thunder  
Reproduction · partners · family recognition  

### Step 3 — Scope guardrails

| Too narrow ❌ | Right breadth ✅ |
|---------------|------------------|
| How Did Romans Heat Their Baths? | How Did Humans Accidentally Create Bathing Rituals? |
| How Did Victorians Do Laundry? | Why Would Your Ancestors Kill for Clean Water? |
| How Tang China Ran Night Markets? | Why Can't Humans Sit Still? |

Stay **one species, deep time** — not one civilization, one century.

### Step 6 — Validation checklist

Score each idea; prefer 4+ yes:

- [ ] Title is a **question**
- [ ] Viewer cares **today** (not just historical trivia)
- [ ] Answer is **visual** for stick-figure animation
- [ ] Claim is **counterintuitive** or has a twist
- [ ] Not pure **procedure** (no "5 steps to make bread in 1200 AD")
- [ ] Not duplicate of a **recent hit** on the reference channel
- [ ] Edgy topics stay **educational**, not gratuitous

### Step 7 — Output format

When user asks for topic ideas, respond with:

```markdown
## Highest confidence
1. **Question title?** — one-line why it fits the pattern

## Solid
...

## Wildcards (higher risk)
...

## Avoid for this style
1–2 examples of what you filtered out and why
```

Offer to save chosen topic to `project.json` `name` field and write script per `workflow/script-generation-prompt.md`.

---

## Step 0 — project start (offer suggestion or user's own)

When `project.json` has empty `name` and user is starting a new video:

1. **Offer two options** — do not only ask “what’s the video about?”
   - **Your own topic** — user supplies a question title
   - **Suggest one for me** — assistant generates a single suggestion
2. **If user wants a suggestion** (or says “suggest”, “pick for me”, “roll”, “surprise me”):
   - Run `python3 scripts/suggest_topic.py` (repo root)
   - Read stdout: `hook`, `seed`, `title_hint`
   - Polish into one question title per title rules above
   - Show **one** suggestion only (not a ranked list) unless they asked for brainstorm
   - User can accept, paste their own instead, or say **roll again** → re-run script (new random seed)
3. **Randomness rules** — critical:
   - **Always** run `suggest_topic.py` for single suggestions at step 0
   - **Never** walk the static “highest-confidence” list in order
   - **Never** return the same default suggestion across sessions without re-rolling
   - For `--count N` or explicit brainstorm requests, each line should come from a separate script roll or matrix combo
4. Save accepted title → `project.json` → `name`, advance `step`

### Static examples (reference only — not for step-0 picks)

These calibrated hits are for **pattern study**, not default suggestions:

How Did Humans Accidentally Create Cooking? · Why Are Human Babies So Loud? · Why Would Your Ancestors Kill for Salt? · Did Cows Domesticate Humans? · Why Did Most Ancient Humans Never Meet Their Grandparents?

---

## Full example bank

See [examples.md](examples.md) for the complete categorized list (~45 question titles), reference channel catalog, and anti-examples from brainstorming sessions.

## Related project files

- Script writing after topic pick: `workflow/script-generation-prompt.md`
- Project name save: `project.json` → `name` + `step: "script"`
- Video pipeline: `workflow/README.md`
