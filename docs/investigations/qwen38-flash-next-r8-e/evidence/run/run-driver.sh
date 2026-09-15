#!/usr/bin/env bash
# R8-E physical run driver (Issue #199 Phases 2-3), runs on inferswarm01
# inside /srv/inferswarm/repos/inferswarm-git at the frozen producer
# commit. Executes, in order:
#   A. non-perturbation controls (accepted binary, both arms, both
#      cases, fresh server process per request, incremental state)
#   B. observation captures, incremental state class (decision-faithful:
#      original accepted prompt, hook observes every generated position,
#      byte-identical execution to R8-D) — 2 repeats per arm/case
#   C. observation captures, tf state class (Issue #199 Phase-2
#      teacher-forced construction; retained as a separate state class)
# RPC backends for the candidate arm are launched/stopped by the
# orchestrator host (nodes hold no keys for each other); this driver
# waits on reachability barriers.
set -euo pipefail
REPO=/srv/inferswarm/repos/inferswarm-git
EV=$REPO/docs/investigations/qwen38-flash-next-r8-e/evidence
TMP=/tmp/i199
PY=python3
mkdir -p $TMP $EV/observations $EV/observations-tf $EV/nonperturbation $EV/run

launch_obs () {  # $1 obsfile $2 pos $3 focus $4 port $5 log $6+ extra-args...
  rm -f "$1" "$1".pos*.f32 "$5"
  LLAMA_OBSERVE_LOGITS="$1" LLAMA_OBSERVE_POS="$2" LLAMA_OBSERVE_FOCUS="$3" \
    nohup /home/hermes/llama.cpp/r8e-obs/build-obs/bin/llama-server \
    -m /srv/models/qwen38-ud-iq1-s/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf \
    -c 8192 --host 127.0.0.1 --port "$4" -lv 4 "${@:6}" > "$5" 2>&1 &
  OBS_PID=$!
}
launch_accepted () {  # $1 port $2 log $3 extra-args...
  rm -f "$2"
  nohup /home/hermes/llama.cpp/build-v041/bin/llama-server \
    -m /srv/models/qwen38-ud-iq1-s/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf \
    -c 8192 --host 127.0.0.1 --port "$1" -lv 4 "${@:3}" > "$2" 2>&1 &
  ACC_PID=$!
}
wait_port () { # $1 logfile
  for i in $(seq 1 300); do
    grep -q "listening" "$1" 2>/dev/null && return 0
    sleep 3
  done
  echo "server failed to listen"; tail -5 "$1"; return 1
}
stop_pid () {
  kill "$1" 2>/dev/null || true
  for i in $(seq 1 90); do kill -0 "$1" 2>/dev/null || return 0; sleep 1; done
  kill -9 "$1" 2>/dev/null || true
  return 0
}

cd $REPO
export PYTHONPATH=$REPO/scripts
RPC="--rpc 10.0.0.219:50052,10.0.0.219:50053,10.0.0.204:50052"
MODEL=/srv/models/qwen38-ud-iq1-s/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf

arm_port () { case "$1" in reference) echo 8331;; candidate) echo 8333;; esac; }
arm_rpc  () { case "$1" in reference) echo "";; candidate) echo "$RPC";; esac; }
focus () { case "$1" in case-256) echo 271,34227;; case-4096) echo 328,248046;; esac; }
posof  () { case "$1" in case-256) echo 5;; case-4096) echo 0;; esac; }

# ---- A. non-perturbation controls (accepted binaries, incremental) ----
for CASE in case-256 case-4096; do
  for ARM in reference candidate; do
    if [ "$ARM" = candidate ]; then bash $EV/run/wait_backends.sh; fi
    PORT=$(arm_port $ARM); EX=$(arm_rpc $ARM)
    for I in 1 2; do
      if [ -n "$EX" ]; then
        launch_accepted $PORT $TMP/acc-server.log $EX
      else
        launch_accepted $PORT $TMP/acc-server.log
      fi
      wait_port $TMP/acc-server.log
      $PY scripts/issue199_r8e_capture.py --arm $ARM --case $CASE \
        --mode accepted --out-dir $EV/nonperturbation \
        --label "$CASE-$ARM-accepted$I"
      stop_pid $ACC_PID
    done
  done
done

# ---- B. observation captures: incremental (decision-faithful) ----
for CASE in case-256 case-4096; do
  for ARM in reference candidate; do
    if [ "$ARM" = candidate ]; then bash $EV/run/wait_backends.sh; fi
    PORT=$(arm_port $ARM); EX=$(arm_rpc $ARM); FOCUS=$(focus $CASE)
    POS=$(posof $CASE)
    for I in 1 2; do
      if [ -n "$EX" ]; then
        launch_obs "$EV/observations/obs-$CASE-$ARM-obs$I.jsonl" "$POS" "$FOCUS" \
          $PORT $TMP/obs-server.log $EX
      else
        launch_obs "$EV/observations/obs-$CASE-$ARM-obs$I.jsonl" "$POS" "$FOCUS" \
          $PORT $TMP/obs-server.log
      fi
      wait_port $TMP/obs-server.log
      $PY scripts/issue199_r8e_capture.py --arm $ARM --case $CASE \
        --state incremental --out-dir $EV/observations \
        --label "$CASE-$ARM-obs$I"
      stop_pid $OBS_PID
    done
  done
done

# ---- C. observation captures: tf state class (Issue Phase-2) ----
for CASE in case-256 case-4096; do
  for ARM in reference candidate; do
    if [ "$ARM" = candidate ]; then bash $EV/run/wait_backends.sh; fi
    PORT=$(arm_port $ARM); EX=$(arm_rpc $ARM); FOCUS=$(focus $CASE)
    POS=$(posof $CASE)
    for I in 1 2; do
      if [ -n "$EX" ]; then
        launch_obs "$EV/observations-tf/obs-$CASE-$ARM-tf$I.jsonl" "$POS" "$FOCUS" \
          $PORT $TMP/obs-tf-server.log $EX
      else
        launch_obs "$EV/observations-tf/obs-$CASE-$ARM-tf$I.jsonl" "$POS" "$FOCUS" \
          $PORT $TMP/obs-tf-server.log
      fi
      wait_port $TMP/obs-tf-server.log
      $PY scripts/issue199_r8e_capture.py --arm $ARM --case $CASE \
        --state tf --out-dir $EV/observations-tf \
        --label "$CASE-$ARM-tf$I"
      stop_pid $OBS_PID
    done
  done
done
echo RUN_COMPLETE
