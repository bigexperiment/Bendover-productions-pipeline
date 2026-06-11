#!/usr/bin/env bash
# Stop the Studio tracker supervisor and server.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

port="$(cat tracker/port.txt 2>/dev/null || echo 47829)"

if [[ -f tracker/studio.pid ]]; then
  pid="$(cat tracker/studio.pid)"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.25
    done
    kill -9 "$pid" 2>/dev/null || true
    echo "Stopped supervisor PID $pid"
  fi
  rm -f tracker/studio.pid
fi

if lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
  lsof -tiTCP:"$port" -sTCP:LISTEN | xargs kill -9 2>/dev/null || true
  echo "Freed port $port"
fi

echo "Studio stopped"
