#!/usr/bin/env bash
# Scaffold a new project directory under projects/<slug>/
#
# Usage:
#   bash scripts/new_project.sh "Why We Dream"
#   bash scripts/new_project.sh "Why We Dream" my-custom-slug

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ $# -lt 1 ]]; then
  echo "Usage: bash scripts/new_project.sh \"Video Title\" [optional-slug]"
  exit 1
fi

TITLE="$1"
if [[ $# -ge 2 ]]; then
  SLUG="$2"
else
  SLUG="$(python3 -c "
import re, sys
t = sys.argv[1].lower()
t = re.sub(r'[^a-z0-9 ]', '', t)
t = re.sub(r' +', '-', t.strip())
print(t)
" "$TITLE")"
fi

PROJECT_DIR="$ROOT/projects/$SLUG"

if [[ -d "$PROJECT_DIR" ]]; then
  echo "Project already exists: $PROJECT_DIR"
  exit 1
fi

# Create directory structure
mkdir -p "$PROJECT_DIR/01-script"
mkdir -p "$PROJECT_DIR/02-audio"
mkdir -p "$PROJECT_DIR/03-transcript"
mkdir -p "$PROJECT_DIR/04-manifest"
mkdir -p "$PROJECT_DIR/05-images"
mkdir -p "$PROJECT_DIR/06-output"
mkdir -p "$PROJECT_DIR/07-upload"
mkdir -p "$PROJECT_DIR/tracker"

# Copy style presets (shared assets, read-only reference)
if [[ -d "$ROOT/assets" ]]; then
  ln -s "$ROOT/assets" "$PROJECT_DIR/assets" 2>/dev/null || true
fi

# Write project.json template
cat > "$PROJECT_DIR/project.json" <<EOF
{
  "name": "$TITLE",
  "step": "script",
  "style_approved": false,
  "image_style": "",
  "style_preset_label": "",
  "style_guide": "",
  "text_rules": "",
  "tone": "",
  "workers": 10
}
EOF

# Write script placeholder
cat > "$PROJECT_DIR/01-script/Script.txt" <<EOF
[Paste or write your script here]
EOF

# Write transcript placeholder
cat > "$PROJECT_DIR/03-transcript/transcript.txt" <<EOF
[Paste TurboScribe transcript here — include (M:SS) inline timestamps]
EOF

# Add to queue.json
QUEUE_FILE="$ROOT/queue.json"
if [[ -f "$QUEUE_FILE" ]]; then
  # Append the new project path to the projects array
  python3 - <<PYEOF
import json
q = json.loads(open("$QUEUE_FILE").read())
q.setdefault("projects", [])
entry = {"path": "projects/$SLUG", "name": "$TITLE"}
# Avoid duplicates
if not any(p.get("path") == "projects/$SLUG" for p in q["projects"] if isinstance(p, dict)):
    q["projects"].append(entry)
open("$QUEUE_FILE", "w").write(json.dumps(q, indent=2) + "\n")
print("Added to queue.json")
PYEOF
else
  cat > "$QUEUE_FILE" <<EOF
{
  "projects": [
    {"path": "projects/$SLUG", "name": "$TITLE"}
  ]
}
EOF
  echo "Created queue.json"
fi

echo ""
echo "Project created: projects/$SLUG"
echo ""
echo "Next steps:"
echo "  1. Edit projects/$SLUG/project.json  — set image_style, style_guide, tone, text_rules"
echo "  2. Paste script → projects/$SLUG/01-script/Script.txt"
echo "  3. Add audio   → projects/$SLUG/02-audio/<narration>.mp3"
echo "  4. Add transcript → projects/$SLUG/03-transcript/transcript.txt"
echo "  5. Run preflight: PIPELINE_ROOT=projects/$SLUG python3 scripts/preflight.py"
echo "  6. Set style_approved: true in project.json when ready"
echo ""
echo "Then add more projects and run:  bash scripts/start_queue.sh"
