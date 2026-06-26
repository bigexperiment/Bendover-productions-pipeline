#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/tracker/queue.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "No queue runner PID file found — already stopped?"
  exit 0
fi

pid="$(cat "$PID_FILE")"
if kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  echo "Queue runner stopped (PID $pid)"
  rm -f "$PID_FILE"
else
  echo "Queue runner (PID $pid) is not running"
  rm -f "$PID_FILE"
fi
