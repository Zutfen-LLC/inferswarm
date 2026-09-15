#!/usr/bin/env bash
# R8-E: stop all ggml-rpc-server backends on 03/04 and prove ports free.
set -euo pipefail
for H in inferswarm03 inferswarm04; do
  ssh -o BatchMode=yes $H 'pkill -f ggml-rpc-server 2>/dev/null; sleep 2
    ss -tln | grep -E "5005[23]" && { echo "port still open on '$H'"; exit 1; } || true
    nvidia-smi --query-gpu=index,memory.used --format=csv,noheader'
done
echo BACKENDS_DOWN
