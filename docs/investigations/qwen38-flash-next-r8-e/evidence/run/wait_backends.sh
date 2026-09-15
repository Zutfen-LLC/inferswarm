#!/usr/bin/env bash
# R8-E: wait for the 3 accepted RPC backends to be reachable from
# inferswarm01 (backends are launched/stopped by the orchestrator host
# over its own SSH; nodes hold no keys for each other). Proves the exact
# endpoint set is connectable before any candidate-arm request.
set -euo pipefail
for EP in 10.0.0.219:50052 10.0.0.219:50053 10.0.0.204:50052; do
  H=${EP%:*}; P=${EP#*:}
  for I in $(seq 1 100); do
    if timeout 3 bash -c "echo > /dev/tcp/$H/$P" 2>/dev/null; then
      echo "$EP reachable"; break
    fi
    sleep 3
    [ "$I" = 100 ] && { echo "$EP NOT reachable"; exit 1; }
  fi
done
echo BACKENDS_REACHABLE
