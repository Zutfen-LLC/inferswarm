#!/usr/bin/env bash
set -euo pipefail
BIN=/home/hermes/llama.cpp/build-v041/bin/llama-server
MODEL=/srv/models/qwen38-ud-iq1-s/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf
LOG=/tmp/i195/ref-server.log
rm -f "$LOG"
# Reference arm: accepted R8-B reference placement — single-host, local
# CUDA auto-fit + CPU spill, NO RPC endpoints, PLE lazy host-side.
nohup "$BIN" -m "$MODEL" -c 8192 --host 127.0.0.1 --port 8321 -lv 4 > "$LOG" 2>&1 &
echo "reference pid=$!"
