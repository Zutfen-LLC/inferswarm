#!/usr/bin/env bash
# R8-E physical run driver (Issue #199 Phases 2-3), runs on inferswarm01
# inside /srv/inferswarm/repos/inferswarm-git at the frozen producer
# commit. Executes, in order:
#   A. non-perturbation controls (accepted binary, both arms, both
#      cases, fresh server process per request)
#   B. observation captures (diagnostic binary, both arms, both cases,
#      2 repeats each, fresh server process per request)
# Every server process is launched with the observation env bound to
# that capture's output path; reference arm runs single-host, candidate
# arm requires the 3 RPC backends (accepted binaries) already running.
set -euo pipefail
REPO=/srv/inferswarm/repos/inferswarm-git
EV=$REPO/docs/investigations/qwen38-flash-next-r8-e/evidence
TMP=/tmp/i199
PY=python3
mkdir -p $TMP $EV/observations $EV/nonperturbation $EV/run

launch_ref_obs () {  # $1 obsfile
  rm -f "$1" "$1".pos*.f32
  LLAMA_OBSERVE_LOGITS="$1" LLAMA_OBSERVE_POS="$2" LLAMA_OBSERVE_FOCUS="$3" \
    nohup /home/hermes/llama.cpp/r8e-obs/build-obs/bin/llama-server \
    -m /srv/models/qwen38-ud-iq1-s/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf \
    -c 8192 --host 127.0.0.1 --port 8331 -lv 4 > $TMP/ref-server.log 2>&1 &
  REF_PID=$!
}
launch_cand_obs () {  # $1 obsfile
  rm -f "$1" "$1".pos*.f32
  LLAMA_OBSERVE_LOGITS="$1" LLAMA_OBSERVE_POS="$2" LLAMA_OBSERVE_FOCUS="$3" \
    nohup /home/hermes/llama.cpp/r8e-obs/build-obs/bin/llama-server \
    -m /srv/models/qwen38-ud-iq1-s/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf \
    -c 8192 --host 127.0.0.1 --port 8333 \
    --rpc 10.0.0.219:50052,10.0.0.219:50053,10.0.0.204:50052 \
    -lv 4 > $TMP/cand-server.log 2>&1 &
  CAND_PID=$!
}
wait_port () { # port logfile
  for i in $(seq 1 300); do
    grep -q "listening" "$2" 2>/dev/null && return 0
    sleep 3
  done
  echo "server on $1 failed to listen"; tail -5 "$2"; return 1
}
stop_pid () {
  [ -n "${2:-}" ] || return 0
  kill "$2" 2>/dev/null || true
  for i in $(seq 1 60); do kill -0 "$2" 2>/dev/null || return 0; sleep 1; done
  kill -9 "$2" 2>/dev/null || true
}

cd $REPO
export PYTHONPATH=$REPO/scripts

# ---- A. non-perturbation controls (accepted binaries) ----
for CASE in case-256 case-4096; do
  # reference accepted x2
  for I in 1 2; do
    rm -f $TMP/ref-acc-server.log
    nohup /home/hermes/llama.cpp/build-v041/bin/llama-server \
      -m /srv/models/qwen38-ud-iq1-s/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf \
      -c 8192 --host 127.0.0.1 --port 8331 -lv 4 > $TMP/ref-acc-server.log 2>&1 &
    P=$!
    wait_port 8331 $TMP/ref-acc-server.log
    $PY scripts/issue199_r8e_capture.py --arm reference --case $CASE \
      --mode accepted --out-dir $EV/nonperturbation \
      --label "$CASE-reference-accepted$I"
    stop_pid "$CASE" $P
  done
done
# candidate accepted x2 (needs RPC backends up — launched/stopped by the
# orchestrator host; here we only prove reachability)
bash $EV/run/wait_backends.sh
for CASE in case-256 case-4096; do
  for I in 1 2; do
    rm -f $TMP/cand-acc-server.log
    nohup /home/hermes/llama.cpp/build-v041/bin/llama-server \
      -m /srv/models/qwen38-ud-iq1-s/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf \
      -c 8192 --host 127.0.0.1 --port 8333 \
      --rpc 10.0.0.219:50052,10.0.0.219:50053,10.0.0.204:50052 \
      -lv 4 > $TMP/cand-acc-server.log 2>&1 &
    P=$!
    wait_port 8333 $TMP/cand-acc-server.log
    $PY scripts/issue199_r8e_capture.py --arm candidate --case $CASE \
      --mode accepted --out-dir $EV/nonperturbation \
      --label "$CASE-candidate-accepted$I"
    stop_pid "$CASE" $P
  done
done
bash $EV/run/stop_rpc_backends.sh

# ---- B. observation captures (diagnostic binary) ----
focus () { case "$1" in case-256) echo 271,34227;; case-4096) echo 328,248046;; esac; }
posof  () { case "$1" in case-256) echo 5;; case-4096) echo 0;; esac; }

for CASE in case-256 case-4096; do
  POS=$(posof $CASE); FOCUS=$(focus $CASE)
  for I in 1 2; do
    launch_ref_obs "$EV/observations/obs-$CASE-reference-obs$I.jsonl" "$POS" "$FOCUS"
    wait_port 8331 $TMP/ref-server.log
    $PY scripts/issue199_r8e_capture.py --arm reference --case $CASE \
      --out-dir $EV/observations --label "$CASE-reference-obs$I"
    stop_pid x $REF_PID
  done
done
bash $EV/run/wait_backends.sh
for CASE in case-256 case-4096; do
  POS=$(posof $CASE); FOCUS=$(focus $CASE)
  for I in 1 2; do
    launch_cand_obs "$EV/observations/obs-$CASE-candidate-obs$I.jsonl" "$POS" "$FOCUS"
    wait_port 8333 $TMP/cand-server.log
    $PY scripts/issue199_r8e_capture.py --arm candidate --case $CASE \
      --out-dir $EV/observations --label "$CASE-candidate-obs$I"
    stop_pid x $CAND_PID
  done
done
bash $EV/run/stop_rpc_backends.sh
echo RUN_COMPLETE
