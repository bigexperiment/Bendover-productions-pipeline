#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f tracker/studio.pid ]]; then
  echo "Not running (no studio.pid). Run: scripts/start_studio.sh"
  exit 1
fi

pid="$(cat tracker/studio.pid)"
port="$(cat tracker/port.txt 2>/dev/null || echo 47829)"

if kill -0 "$pid" 2>/dev/null; then
  echo "Running — PID $pid"
  echo "URL: http://127.0.0.1:${port}/"
  curl -sf "http://127.0.0.1:${port}/" -o /dev/null && echo "Health: OK" || echo "Health: NOT RESPONDING"
else
  echo "Dead — PID $pid not found. Run: scripts/start_studio.sh"
  echo "Last log:"
  tail -10 tracker/studio.log 2>/dev/null || true
  exit 1
fi
