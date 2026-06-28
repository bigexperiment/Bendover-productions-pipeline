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
mkdir -p "$PROJECT_DIR/tracker/thumbs"

# Link shared assets (style previews etc.)
if [[ -d "$ROOT/assets" ]]; then
  ln -s "$ROOT/assets" "$PROJECT_DIR/assets" 2>/dev/null || true
fi

# project.json — queue_status "upload" so Studio UI shows the upload step
cat > "$PROJECT_DIR/project.json" <<EOF
{
  "name": "$TITLE",
  "queue_status": "upload",
  "style_approved": false,
  "image_style": "",
  "style_preset_id": "",
  "style_preset_label": "",
  "style_guide": "",
  "text_rules": "",
  "tone": "",
  "workers": 10
}
EOF

# Script placeholder — Claude will fill this in
cat > "$PROJECT_DIR/01-script/Script.txt" <<'EOF'
EOF

# Transcript placeholder
cat > "$PROJECT_DIR/03-transcript/transcript.txt" <<'EOF'
EOF

echo ""
echo "✓ Project created: projects/$SLUG"
echo ""
echo "Next: paste the approved script into projects/$SLUG/01-script/Script.txt"
echo "Then open the Studio UI → http://127.0.0.1:47829"
