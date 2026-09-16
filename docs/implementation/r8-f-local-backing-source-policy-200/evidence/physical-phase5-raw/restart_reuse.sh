#!/usr/bin/env bash
# Supplementary restart-durability observation: fresh ggml-rpc-server process
# against arm B's ALREADY-POPULATED cache (no re-staging, no network rebuild),
# fresh client, exact capture contract. Proves on-disk cache durability across
# server restart, complementing the fresh-pre-staged arms.
set -euo pipefail
W=/tmp/i200p5
OUT=/tmp/issue200-p5-evidence/raw/restart_reuse_observation
mkdir -p "$OUT"
pkill -f 'llama-server.*8341' || true
sleep 0
true
sleep 0
LLAMA_CACHE=$W/armB-cache nohup /home/hermes/llama.cpp/build-v041/bin/ggml-rpc-server \
  -H 0.0.0.0 -p 50052 -d CUDA0 -c > "$OUT/rpc-server.log" 2>&1 &
RPC_PID=$!
sleep 2
ss -ltn | grep 50052
nohup /home/hermes/llama.cpp/build-v041/bin/llama-server \
  -m /srv/models/qwen38-ud-iq1-s/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf \
  --rpc 10.0.0.204:50052 -ot 'blk\.24\.attn_gate\.weight=RPC0[10.0.0.204:50052]' \
  --host 127.0.0.1 --port 8341 -ngl 0 -c 8192 --no-warmup > "$OUT/client.log" 2>&1 &
CLIENT_PID=$!
echo "client pid=$CLIENT_PID"
sleep 3
strace -f --always-show-pid -ttt -xx -s 0 -e trace=network,write,writev \
  -p "$CLIENT_PID" > "$OUT/capture.strace" 2>&1 &
STRACE_PID=$!
T0=$(date +%s.%N)
for i in $(seq 1 300); do
  if grep -q 'listening on http://' "$OUT/client.log" 2>/dev/null; then break; fi
  sleep 2
done
T1=$(date +%s.%N)
echo "start=$T0 end=$T1" > "$OUT/boundaries.txt"
kill "$STRACE_PID" || true
sleep 0
kill "$CLIENT_PID" || true
sleep 2
kill -9 "$CLIENT_PID" 2>/dev/null || true
kill "$RPC_PID" || true
echo done
