# High-retention educational YouTube script prompt (~5 min)

**When to use:** Step 1 — after the user sets the project title in `project.json` → `name`.

**Trigger:** User accepts the script offer ("yes", "write it", "go ahead") or asks for name + script in one message. If they prefer to paste their own script, do **not** run this prompt.

**Topic:** Replace `[[TOPIC]]` with `project.json` → `name`.

**Agent must:** Read this file fully, research the web first, then write the script and save to `01-script/Script.txt`.

---

## Prompt (copy and run with topic filled in)

Before writing the script, research the topic on the web.
Read multiple reliable sources first. Look for:

- key facts
- dates
- names
- measurements
- scientific or historical explanations
- surprising details
- common myths or misunderstandings

Do not start writing until you understand the topic clearly.
Then write the script.

Your job is not to inform.
Your job is to make the viewer feel the experience of discovering something.
Information is scaffolding. The product is the feeling of understanding.

**TARGET LENGTH:** Less than 5000 characters (~5 minutes spoken narration)

### STRUCTURE

**1. IMMERSION HOOK**

Open in second person ("you").
Drop the viewer directly into a specific moment.
Remove familiar comforts one by one.
Introduce one concrete threat, tension, or impossibility.
Include one subtle dark-humor beat.
State the paradox, not the question.
End by teasing that the answer is stranger than it appears.

**2. STAKES ESCALATION**

Show why the problem is worse than expected.
Use 2–3 specific examples, names, dates, measurements, or events.
Make the challenge feel genuinely difficult.
Create a curiosity gap.

**3. THE PIVOT**

Ask the central question.
Keep it short.
Immediately suggest: "It wasn't one thing. It was several small advantages stacking together."
Transition into the explanation.

**4. THE SOLUTION CHAIN**

Present 3 connected layers of explanation.
For each layer:

- a. Open with a curiosity trigger ("Here's the thing most people never consider...")
- b. Explain through one concrete example
- c. Give emotional weight
- d. Extract a broader principle
- e. Explain why this alone wasn't enough

The solutions should feel like a chain: Simple → Complex → Surprising.

**5. THE THRESHOLD MOMENT**

Identify the moment everything changed.
Not a gradual trend. A threshold.
Show the world before. Show the world after.
Use vivid contrast.

**6. MORAL INVERSION**

Reveal the hidden cost.
The success creates a new problem.
Do not preach. Simply observe the consequence.
Make the viewer reconsider the entire story.

**7. SUBSCRIBE CTA (1 sentence)**

Add one short, natural subscribe line before the final landing line.
Calm and serious, not loud or salesy.
Example tone: "If you want more stories that make the familiar world feel strange again, subscribe."

**8. LANDING LINE**

End with 2 powerful sentences.
Do NOT summarize. Reframe.
Slightly poetic. Slightly unsettling. Memorable enough to quote.

### WRITING RULES

**VOICE**

- Second person ("you") and first-person plural ("we")
- Conversational documentary narration
- Active voice only
- Use "And" and "But" naturally

**SENTENCES**

- Mix short punches with longer explanations
- Frequently use: "Not X, but Y"
- Tricolons ("They survived. They adapted. They changed everything.")
- Occasional parenthetical asides

**HUMOR**

- Dry and understated
- One subtle humor beat every few minutes
- Joke about the situation, never the subject

**INFORMATION**

- Use specific facts as texture
- Define technical terms immediately
- Never over-explain
- Trust the viewer
- Do not include a bibliography or source list in the final script unless asked

**CURIOSITY**

- Open a new question every 60–90 seconds
- Don't answer questions immediately
- Every answer should create a new complication

**AVOID**

- "In this video..."
- Listicle structure
- Wikipedia-style explanations
- Overly academic language
- Early resolution of tension
- Summaries at the end
- A loud YouTuber-style subscribe request

The script should feel like a brilliant friend telling a story they've become obsessed with, not a teacher delivering a lesson.

### OUTPUT FORMAT (mandatory)

Save the final script to **`01-script/Script.txt`** as:

- Plain narration text only
- **No headings** (no section titles, no markdown)
- **No timestamps**
- **No line breaks** — one continuous block of prose (sentences separated by spaces)
- Under 5000 characters

**Topic:** [[TOPIC]]
