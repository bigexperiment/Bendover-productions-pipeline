#!/usr/bin/env bash
# Start the multi-project queue runner — detached, survives terminal close.
#
# Projects are read from queue.json at repo root. Example queue.json:
#   {
#     "projects": [
#       {"path": ".", "name": "Current project"},
#       {"path": "projects/next-topic"},
#       {"path": "/absolute/path/to/project"}
#     ]
#   }
#
# Or pass paths directly:
#   bash scripts/start_queue.sh projects/my-topic projects/other-topic
#
# Monitor:
#   tail -f tracker/queue.log
#   (ntfy alerts sent at each project start and completion)
#
# Stop:
#   bash scripts/stop_queue.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p tracker

PID_FILE="tracker/queue.pid"
LOG_FILE="tracker/queue.log"

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE")"
  if kill -0 "$old_pid" 2>/dev/null; then
    echo "Queue runner already active (PID $old_pid)"
    echo "  Log:  tail -f $LOG_FILE"
    echo "  Stop: bash scripts/stop_queue.sh"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

# Pass any extra args (project paths) to the runner
EXTRA_ARGS=("$@")

echo "Starting queue runner (detached)..."
nohup python3 -u scripts/queue_runner.py "${EXTRA_ARGS[@]}" >> "$LOG_FILE" 2>&1 &
QUEUE_PID=$!
echo "$QUEUE_PID" > "$PID_FILE"
disown "$QUEUE_PID"

echo "  PID:  $QUEUE_PID"
echo "  Log:  tail -f $LOG_FILE"
echo "  Stop: bash scripts/stop_queue.sh"
echo ""
echo "The queue will run all projects in sequence."
echo "Credits auto-wait and resume — no intervention needed."
echo "You will get ntfy alerts at each milestone."
