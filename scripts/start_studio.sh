#!/usr/bin/env bash
# Start Studio tracker — idempotent: leaves a healthy server alone.
#
# Uses tracker/studio_supervisor.py --detach (double-fork) so Studio survives
# when the Cursor agent shell closes. Supervisor auto-restarts serve.py on crash.
#
# Assistant: run scripts/status_studio.sh first; only run this if down.
# Stop: scripts/stop_studio.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p tracker

port="$(cat tracker/port.txt 2>/dev/null || echo 47829)"

if curl -sf "http://127.0.0.1:${port}/" -o /dev/null 2>/dev/null; then
  pid="$(cat tracker/studio.pid 2>/dev/null || echo unknown)"
  echo "Studio already running"
  echo "  PID:  $pid"
  echo "  URL:  http://127.0.0.1:${port}/"
  echo "  Log:  tracker/studio.log"
  command -v open >/dev/null && open "http://127.0.0.1:${port}/" || true
  exit 0
fi

# Not responding — stop stale supervisor/processes, then start fresh.
if [[ -f tracker/studio.pid ]]; then
  old_pid="$(cat tracker/studio.pid)"
  kill "$old_pid" 2>/dev/null || true
  sleep 0.5
  kill -9 "$old_pid" 2>/dev/null || true
  rm -f tracker/studio.pid
fi

for p in $(seq 47829 47838); do
  lsof -tiTCP:"$p" -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true
done

{
  echo ""
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') studio start ====="
} >> tracker/studio.log

# --detach: double-fork so Cursor/agent terminal exit does not kill Studio
python3 -u tracker/studio_supervisor.py --detach >> tracker/studio.log 2>&1

for i in $(seq 1 30); do
  sleep 0.5
  pid="$(cat tracker/studio.pid 2>/dev/null || true)"
  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    continue
  fi
  port="$(cat tracker/port.txt 2>/dev/null || echo 47829)"
  if curl -sf "http://127.0.0.1:${port}/" -o /dev/null; then
    echo "Studio running (detached + supervised)"
    echo "  PID:  $pid"
    echo "  URL:  http://127.0.0.1:${port}/"
    echo "  Log:  tracker/studio.log"
    echo "  Stop: scripts/stop_studio.sh"
    command -v open >/dev/null && open "http://127.0.0.1:${port}/" || true
    exit 0
  fi
done

echo "ERROR: Studio not responding on port ${port}"
tail -30 tracker/studio.log
exit 1
