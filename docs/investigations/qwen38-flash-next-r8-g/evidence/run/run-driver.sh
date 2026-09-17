#!/usr/bin/env bash
# R8-G physical run driver (Issue #207 Phases 1-4), runs on inferswarm01
# inside /srv/inferswarm/repos/inferswarm-git at the campaign branch.
# The RPC backends for candidate-arm captures are launched/stopped by the
# ORCHESTRATOR host (nodes hold no keys for each other); this driver
# waits on reachability barriers.
#
# Stages (selected by $1):
#   nonpert   A. non-perturbation + seam-anchor captures (diagnostic
#             binary, both arms, case-4096, 2 repeats)
#   coarse    B. coarse localization (case-4096, both arms, 2 repeats,
#             frozen 18-boundary coarse set + seam anchor)
#   refine    C. refinement inside the first coarse interval (spec
#             supplied by the orchestrator AFTER the frozen refinement
#             plan is derived; mechanically logged here)
#   contrast  D. case-256 contrast (frozen contrast set)
set -euo pipefail
REPO=/srv/inferswarm/repos/inferswarm-git
EV=$REPO/docs/investigations/qwen38-flash-next-r8-g/evidence
TMP=/tmp/i207
PY=python3
STAGE=${1:?stage}
SPEC=${2:?boundary spec}
RUN=$EV/run
mkdir -p $TMP $RUN


# Fail-closed GPU-idle gate (physical finding 2026-09-16: a stray
# leftover process holding GPU memory changes the memory-fit -> layer
# split -> kernel assignment -> float32 bytes, even with identical
# tokens). Refuse to launch any capture unless every local GPU is free
# of compute apps AND memory.used is at the idle floor (< 100 MiB).
gpu_idle_gate () {
  bad=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | wc -l)
  if [ "$bad" != "0" ]; then
    echo "GPU-IDLE GATE: compute apps present:"; nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader
    return 1
  fi
  for M in $(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits); do
    if [ "$M" -gt 100 ]; then echo "GPU-IDLE GATE: memory.used=${M}MiB > 100"; return 1; fi
  done
  return 0
}

arm_port () { case "$1" in reference) echo 8341;; candidate) echo 8343;; esac; }

launch_obs () {  # $1 arm $2 bout $3 bjsonl $4 ljsonl $5 log
  rm -f "$2"/* "$3" "$4" "$5" 2>/dev/null || true
  mkdir -p "$2"
  if [ "$1" = candidate ]; then
    LLAMA_OBSERVE_BOUNDARIES="$SPEC" LLAMA_OBSERVE_BOUNDARY_OUT="$2" \
    LLAMA_OBSERVE_BOUNDARY_JSONL="$3" LLAMA_OBSERVE_LOGITS="$4" \
    LLAMA_OBSERVE_POS=0 \
    nohup /home/hermes/llama.cpp/r8g-obs/build-r8g/bin/llama-server \
      -m /srv/models/qwen38-ud-iq1-s/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf \
      -c 8192 --host 127.0.0.1 --port $(arm_port candidate) -lv 4 --no-warmup \
      --rpc 10.0.0.219:50052,10.0.0.219:50053,10.0.0.204:50052 > "$5" 2>&1 &
  else
    LLAMA_OBSERVE_BOUNDARIES="$SPEC" LLAMA_OBSERVE_BOUNDARY_OUT="$2" \
    LLAMA_OBSERVE_BOUNDARY_JSONL="$3" LLAMA_OBSERVE_LOGITS="$4" \
    LLAMA_OBSERVE_POS=0 \
    nohup /home/hermes/llama.cpp/r8g-obs/build-r8g/bin/llama-server \
      -m /srv/models/qwen38-ud-iq1-s/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf \
      -c 8192 --host 127.0.0.1 --port $(arm_port reference) -lv 4 --no-warmup \
      > "$5" 2>&1 &
  fi
  OBS_PID=$!
}

wait_port () { # $1 logfile
  for i in $(seq 1 300); do
    grep -q "listening" "$1" 2>/dev/null && return 0
    sleep 3
  done
  echo "server failed to listen"; tail -5 "$1"; return 1
}

# llama-server performs a 1-token load-time decode (common_context_can_
# seq_rm cache probe) EVEN with --no-warmup; after the server is
# listening, truncate the observation JSONLs and clear the bounds dir so
# occurrence 0 of every name is the FIRST graph execution of the CAPTURED
# request. (The pre-request rows of the probe run are separately
# retained in the server log; the capture producer re-proves empty
# JSONLs at request time.)
reset_obs () { # $1 bout $2 bjsonl $3 ljsonl
  : > "$2"; : > "$3" 2>/dev/null || true
  rm -rf "$1"; mkdir -p "$1"
}

stop_pid () {
  kill "$1" 2>/dev/null || true
  for i in $(seq 1 90); do kill -0 "$1" 2>/dev/null || return 0; sleep 1; done
  kill -9 "$1" 2>/dev/null || true
}

cd $REPO
export PYTHONPATH=$REPO/scripts

case $STAGE in
nonpert)
  OUT=$EV/nonpert; mkdir -p $OUT
  for ARM in reference candidate; do
    if [ "$ARM" = candidate ]; then bash $RUN/wait_backends.sh; fi
    for I in 1 2; do
      gpu_idle_gate || exit 1
      launch_obs $ARM $TMP/bout-$ARM-$I $TMP/b-$ARM-$I.jsonl \
        $TMP/l-$ARM-$I.jsonl $TMP/obs-server-$ARM-$I.log
      wait_port $TMP/obs-server-$ARM-$I.log
      reset_obs $TMP/bout-$ARM-$I $TMP/b-$ARM-$I.jsonl $TMP/l-$ARM-$I.jsonl
      $PY scripts/issue207_r8g_capture.py --arm $ARM --case case-4096 \
        --phase nonpert --spec "$SPEC" --out-dir $OUT \
        --bounds-dir $TMP/bout-$ARM-$I --bounds-jsonl $TMP/b-$ARM-$I.jsonl \
        --logits-jsonl $TMP/l-$ARM-$I.jsonl \
        --label "case-4096-$ARM-np$I" || exit 1
      stop_pid $OBS_PID
    done
  done
  echo NONPERT_COMPLETE ;;
coarse)
  OUT=$EV/coarse; mkdir -p $OUT
  for ARM in reference candidate; do
    if [ "$ARM" = candidate ]; then bash $RUN/wait_backends.sh; fi
    for I in 1 2; do
      gpu_idle_gate || exit 1
      launch_obs $ARM $TMP/bout-c-$ARM-$I $TMP/b-c-$ARM-$I.jsonl \
        $TMP/l-c-$ARM-$I.jsonl $TMP/obs-server-c-$ARM-$I.log
      wait_port $TMP/obs-server-c-$ARM-$I.log
      reset_obs $TMP/bout-c-$ARM-$I $TMP/b-c-$ARM-$I.jsonl $TMP/l-c-$ARM-$I.jsonl
      $PY scripts/issue207_r8g_capture.py --arm $ARM --case case-4096 \
        --phase coarse --spec "$SPEC" --out-dir $OUT \
        --bounds-dir $TMP/bout-c-$ARM-$I --bounds-jsonl $TMP/b-c-$ARM-$I.jsonl \
        --logits-jsonl $TMP/l-c-$ARM-$I.jsonl \
        --label "case-4096-$ARM-obs$I" || exit 1
      stop_pid $OBS_PID
    done
  done
  echo COARSE_COMPLETE ;;
refine)
  OUT=$EV/refine; mkdir -p $OUT
  for ARM in reference candidate; do
    if [ "$ARM" = candidate ]; then bash $RUN/wait_backends.sh; fi
    for I in 1 2; do
      gpu_idle_gate || exit 1
      launch_obs $ARM $TMP/bout-r-$ARM-$I $TMP/b-r-$ARM-$I.jsonl \
        $TMP/l-r-$ARM-$I.jsonl $TMP/obs-server-r-$ARM-$I.log
      wait_port $TMP/obs-server-r-$ARM-$I.log
      reset_obs $TMP/bout-r-$ARM-$I $TMP/b-r-$ARM-$I.jsonl $TMP/l-r-$ARM-$I.jsonl
      $PY scripts/issue207_r8g_capture.py --arm $ARM --case case-4096 \
        --phase refine --spec "$SPEC" --out-dir $OUT \
        --bounds-dir $TMP/bout-r-$ARM-$I --bounds-jsonl $TMP/b-r-$ARM-$I.jsonl \
        --logits-jsonl $TMP/l-r-$ARM-$I.jsonl \
        --label "case-4096-$ARM-rf$I" || exit 1
      stop_pid $OBS_PID
    done
  done
  echo REFINE_COMPLETE ;;
contrast)
  OUT=$EV/contrast; mkdir -p $OUT
  for ARM in reference candidate; do
    if [ "$ARM" = candidate ]; then bash $RUN/wait_backends.sh; fi
    for I in 1 2; do
      gpu_idle_gate || exit 1
      launch_obs $ARM $TMP/bout-x-$ARM-$I $TMP/b-x-$ARM-$I.jsonl \
        $TMP/l-x-$ARM-$I.jsonl $TMP/obs-server-x-$ARM-$I.log
      wait_port $TMP/obs-server-x-$ARM-$I.log
      reset_obs $TMP/bout-x-$ARM-$I $TMP/b-x-$ARM-$I.jsonl $TMP/l-x-$ARM-$I.jsonl
      $PY scripts/issue207_r8g_capture.py --arm $ARM --case case-256 \
        --phase contrast --spec "$SPEC" --out-dir $OUT \
        --bounds-dir $TMP/bout-x-$ARM-$I --bounds-jsonl $TMP/b-x-$ARM-$I.jsonl \
        --logits-jsonl $TMP/l-x-$ARM-$I.jsonl \
        --label "case-256-$ARM-ct$I" || exit 1
      stop_pid $OBS_PID
    done
  done
  echo CONTRAST_COMPLETE ;;
esac
