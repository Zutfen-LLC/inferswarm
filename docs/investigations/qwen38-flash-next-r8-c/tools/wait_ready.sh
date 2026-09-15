#!/usr/bin/env bash
# Fail-fast readiness waiter: <logfile> [timeout_s]
# Succeeds on "all slots are idle"; fails immediately on process death,
# "exiting due to", "error while handling argument", or "failed to load".
LOG="$1"; TMO="${2:-420}"
[ -f "$LOG" ] || { echo "NOLOG"; exit 2; }
START=$(date +%s)
while true; do
  grep -q "all slots are idle" "$LOG" 2>/dev/null && { echo READY; exit 0; }
  if grep -qE "exiting due to|error while handling argument|failed to load model|unknown buffer type|error loading model" "$LOG" 2>/dev/null; then
    echo "LAUNCH_FAILED"; sed -n '1,12p' "$LOG" | grep -iE "error|usage" | head -5; exit 1
  fi
  NOW=$(date +%s)
  [ $((NOW-START)) -ge "$TMO" ] && { echo "TIMEOUT after ${TMO}s"; tail -3 "$LOG"; exit 3; }
  sleep 3
done
