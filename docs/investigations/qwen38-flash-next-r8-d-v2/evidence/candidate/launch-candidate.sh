#!/usr/bin/env bash
set -euo pipefail
LOG=${1:-/tmp/i195-v2/cand-server.log}
mkdir -p /tmp/i195-v2
rm -f "$LOG"
# v2 candidate arm: accepted 5-device topology — client llama-server on
# inferswarm01 (2x RTX 3060) + ggml-rpc-server backends on
# inferswarm03 (ports 50052/50053) + inferswarm04 (port 50052).
nohup /home/hermes/llama.cpp/build-v041/bin/llama-server -m /srv/models/qwen38-ud-iq1-s/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf -c 8192 --host 127.0.0.1 --port 8323 --rpc 10.0.0.219:50052,10.0.0.219:50053,10.0.0.204:50052 -lv 4 > "$LOG" 2>&1 &
echo "candidate pid=$!"

