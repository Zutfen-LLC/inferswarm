#!/usr/bin/env bash
set -euo pipefail
BIN=/home/hermes/llama.cpp/build-v041/bin/llama-server
MODEL=/srv/models/qwen38-ud-iq1-s/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf
LOG=/tmp/i195/cand-server-restart.log
rm -f "$LOG"
nohup "$BIN" -m "$MODEL" -c 8192 --host 127.0.0.1 --port 8323 --rpc 10.0.0.219:50052,10.0.0.219:50053,10.0.0.204:50052 -lv 4 > "$LOG" 2>&1 &
echo "candidate pid=$!"
