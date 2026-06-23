#!/usr/bin/env bash
# Stop the overnight runner if it's active.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PID_FILE="tracker/overnight.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "No overnight runner active (no PID file)"
  exit 0
fi

pid="$(cat "$PID_FILE")"
if kill -0 "$pid" 2>/dev/null; then
  echo "Stopping overnight runner (PID $pid)..."
  kill "$pid"
  sleep 2
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
  fi
  echo "Stopped."
else
  echo "PID $pid not running (stale PID file)"
fi

rm -f "$PID_FILE"

# Also kill any codex exec children that might be orphaned
pkill -f "codex exec.*image_generation" 2>/dev/null || true
echo "Done."
