#!/usr/bin/env bash
# Start the overnight runner — detached so it survives terminal/Cursor exit.
#
# Prerequisites (do these BEFORE running):
#   1. project.json → name set, style_approved: true
#   2. 01-script/Script.txt filled
#   3. 02-audio/ has narration MP3
#   4. 03-transcript/transcript.txt pasted from TurboScribe
#
# Usage:
#   bash scripts/start_overnight.sh
#
# Monitor:
#   tail -f tracker/overnight.log
#   http://127.0.0.1:47829/ (Studio UI)
#
# Stop:
#   bash scripts/stop_overnight.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p tracker

PID_FILE="tracker/overnight.pid"
LOG_FILE="tracker/overnight.log"

# Check if already running
if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE")"
  if kill -0 "$old_pid" 2>/dev/null; then
    echo "Overnight runner already active (PID $old_pid)"
    echo "  Log:  $LOG_FILE"
    echo "  Stop: bash scripts/stop_overnight.sh"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

# Quick validation before detaching
echo "Pre-launch checks..."
python3 scripts/preflight.py --images
if [[ $? -ne 0 ]]; then
  echo ""
  echo "ABORT: Fix preflight errors above before running overnight."
  exit 1
fi

# Check style_approved
approved=$(python3 -c "import json; print(json.load(open('project.json')).get('style_approved', False))")
if [[ "$approved" != "True" ]]; then
  echo "ABORT: style_approved is false in project.json"
  echo "  → Set style_approved: true (approve style in Studio or edit project.json)"
  exit 1
fi

echo ""
echo "Starting overnight runner (detached)..."
echo "==========================================="

# Launch detached — nohup + disown
nohup python3 -u scripts/overnight_runner.py >> "$LOG_FILE" 2>&1 &
RUNNER_PID=$!
echo "$RUNNER_PID" > "$PID_FILE"
disown "$RUNNER_PID"

echo "  PID:  $RUNNER_PID"
echo "  Log:  tail -f $LOG_FILE"
echo "  Stop: bash scripts/stop_overnight.sh"
echo ""
echo "Phone alerts via ntfy.sh/bendoverproductions123"
echo "Go to sleep — you'll get a ping when the MP4 is ready."
