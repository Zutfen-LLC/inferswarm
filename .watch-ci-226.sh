#!/bin/bash
# Bounded CI watcher for PR #227 head e0b30497 (issue #226).
# Polls every 90s, exits when the head run completes; notify on exit.
set -u
HEAD_SHA="e0b30497f293ae0d83996a937f287be8d86795ad"
export GH_TOKEN=$(printf 'protocol=https\nhost=github.com\n' | git credential fill 2>/dev/null | grep '^password=' | cut -d= -f2)
deadline=$((SECONDS + 3600))
while [ $SECONDS -lt $deadline ]; do
  status=$(gh run list --repo Zutfen-LLC/inferswarm --commit "$HEAD_SHA" --json status,conclusion,databaseId,workflowName,displayTitle --limit 10 2>/dev/null)
  echo "$(date -u +%H:%M:%S) $status"
  in_progress=$(echo "$status" | python3 -c "import json,sys; rows=json.load(sys.stdin); print(sum(1 for r in rows if r.get('status') not in ('completed','')))" 2>/dev/null)
  total=$(echo "$status" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null)
  if [ "${total:-0}" -gt 0 ] && [ "${in_progress:-1}" = "0" ]; then
    echo "ALL RUNS COMPLETE"
    echo "$status" | python3 -m json.tool
    exit 0
  fi
  sleep 90
done
echo "TIMEOUT after 60 minutes"
exit 1
