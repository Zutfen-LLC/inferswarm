#!/usr/bin/env bash
# R8-E: barrier — RPC backends are stopped by the ORCHESTRATOR host
# (nodes hold no keys for each other). This script proves from
# inferswarm01 that all three endpoints are DOWN before continuing
# (fail-closed: refuses to let the run proceed with backends up).
set -euo pipefail
for EP in 10.0.0.219:50052 10.0.0.219:50053 10.0.0.204:50052; do
  H=${EP%:*}; P=${EP#*:}
  still=""
  for I in $(seq 1 40); do
    if timeout 3 bash -c "echo > /dev/tcp/$H/$P" 2>/dev/null; then
      still=1
      sleep 3
    else
      still=""
      break
    fi
  done
  if [ -n "$still" ]; then
    echo "$EP STILL reachable"
    exit 1
  fi
  echo "$EP down"
done
echo BACKENDS_CONFIRMED_DOWN
