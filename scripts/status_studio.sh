#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

port="$(cat tracker/port.txt 2>/dev/null || echo 47829)"
url="http://127.0.0.1:${port}/"

if curl -sf "$url" -o /dev/null 2>/dev/null; then
  pid="$(cat tracker/studio.pid 2>/dev/null || echo unknown)"
  echo "Running — PID $pid (supervised)"
  echo "URL: $url"
  echo "Health: OK"
  exit 0
fi

if [[ -f tracker/studio.pid ]]; then
  pid="$(cat tracker/studio.pid)"
  if kill -0 "$pid" 2>/dev/null; then
    echo "Supervisor alive (PID $pid) but not responding yet"
    echo "URL: $url"
    echo "Health: STARTING"
    exit 0
  fi
  echo "Dead — stale PID $pid. Run: scripts/start_studio.sh"
else
  echo "Not running. Run: scripts/start_studio.sh"
fi

echo "Last log:"
tail -15 tracker/studio.log 2>/dev/null || true
exit 1
