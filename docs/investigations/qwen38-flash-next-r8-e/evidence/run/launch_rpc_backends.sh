#!/usr/bin/env bash
# R8-E: launch the 3 accepted RPC backends (03:50052 CUDA0, 03:50053
# CUDA1, 04:50052 CUDA0) using the ACCEPTED uninstrumented binaries.
set -euo pipefail
ssh -o BatchMode=yes zutfen@10.0.0.219 '
  pgrep -f "ggml-rpc-server.*50052" >/dev/null || (nohup /home/hermes/llama.cpp/build-v041/bin/ggml-rpc-server -H 0.0.0.0 -p 50052 -d CUDA0 > /tmp/i199-rpc03-g0.log 2>&1 &)
  pgrep -f "ggml-rpc-server.*50053" >/dev/null || (nohup /home/hermes/llama.cpp/build-v041/bin/ggml-rpc-server -H 0.0.0.0 -p 50053 -d CUDA1 > /tmp/i199-rpc03-g1.log 2>&1 &)
  sleep 1; pgrep -af ggml-rpc-server' || \
ssh -o BatchMode=yes zutfen@10.0.0.219 'true'
ssh -o BatchMode=yes inferswarm03 '
  pgrep -f "ggml-rpc-server.*50052" >/dev/null || (nohup /home/hermes/llama.cpp/build-v041/bin/ggml-rpc-server -H 0.0.0.0 -p 50052 -d CUDA0 > /tmp/i199-rpc03-g0.log 2>&1 &)
  pgrep -f "ggml-rpc-server.*50053" >/dev/null || (nohup /home/hermes/llama.cpp/build-v041/bin/ggml-rpc-server -H 0.0.0.0 -p 50053 -d CUDA1 > /tmp/i199-rpc03-g1.log 2>&1 &)
  sleep 1; pgrep -af ggml-rpc-server'
ssh -o BatchMode=yes inferswarm04 '
  pgrep -f "ggml-rpc-server.*50052" >/dev/null || (nohup /home/hermes/llama.cpp/build-v041/bin/ggml-rpc-server -H 0.0.0.0 -p 50052 -d CUDA0 > /tmp/i199-rpc04.log 2>&1 &)
  sleep 1; pgrep -af ggml-rpc-server'
echo BACKENDS_UP
