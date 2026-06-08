#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p tracker

if [[ -f tracker/studio.pid ]]; then
  old_pid="$(cat tracker/studio.pid)"
  kill "$old_pid" 2>/dev/null || true
fi

for port in $(seq 47829 47838); do
  lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true
done

: > tracker/studio.log
nohup python3 -u tracker/serve.py >> tracker/studio.log 2>&1 &
pid=$!
echo "$pid" > tracker/studio.pid

PORT=47829
for i in $(seq 1 20); do
  sleep 0.5
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "ERROR: Server process died. Log:"
    cat tracker/studio.log
    exit 1
  fi
  PORT="$(cat tracker/port.txt 2>/dev/null || echo 47829)"
  if curl -sf "http://127.0.0.1:${PORT}/" -o /dev/null; then
    echo "Image tracker running"
    echo "  PID:  $pid"
    echo "  URL:  http://127.0.0.1:${PORT}/"
    echo "  Log:  tracker/studio.log"
    command -v open >/dev/null && open "http://127.0.0.1:${PORT}/" || true
    exit 0
  fi
done

echo "ERROR: Server started but not responding on port ${PORT}"
cat tracker/studio.log
exit 1
