#!/usr/bin/env bash
LOG="$1"; TMO="${2:-900}"
[ -f "$LOG" ] || { echo NOLOG; exit 2; }
START=$(date +%s)
while true; do
  grep -q "all slots are idle" "$LOG" 2>/dev/null && { echo READY; exit 0; }
  if grep -qE "exiting due to|error while handling argument|failed to load model|error loading model" "$LOG" 2>/dev/null; then
    echo "LAUNCH_FAILED"; grep -iE "error|usage" "$LOG" | head -5; exit 1; fi
  [ $(( $(date +%s)-START )) -ge "$TMO" ] && { echo TIMEOUT; tail -3 "$LOG"; exit 3; }
  sleep 5
done
