#!/usr/bin/env bash
# FUTURE CPU05 dispatch only, inside the established ssh -A controller.
set -euo pipefail
if [[ $# != 4 && ! ( ( $# == 5 || $# == 6 ) && ( $5 == --diagnostic-pair13 || $5 == --diagnostic-stages || $5 == --operand-profile ) ) ]]; then
  printf 'usage: bash %s REPO AUTHENTICATED_SOURCE_ARCHIVE FRESH_BUILD FRESH_RESULT [--diagnostic-pair13|--diagnostic-stages [RETAINED_RUN_ARCHIVE]|--operand-profile]\n' "$0" >&2
  exit 2
fi
repo=$(realpath "$1")
archive=$(realpath "$2")
build=$3
result=$4
benchmark_args=(--tokens 1,2,4,8,16)
if [[ ${5:-} == --operand-profile ]]; then
  [[ $# == 5 ]] || { printf 'operand profile takes no retained archive\n' >&2; exit 2; }
  benchmark_args=(--tokens 1,2,4,8 --pairs 1 --warmup 0 --operand-replay)
fi
if [[ ${5:-} == --diagnostic-pair13 || ${5:-} == --diagnostic-stages ]]; then
  benchmark_args=(--diagnostic-pair13 --failure-dump)
  if [[ ${5:-} == --diagnostic-stages ]]; then benchmark_args+=(--capture-stages); fi
  if [[ $# == 6 ]]; then benchmark_args+=(--retained-run "$(realpath "$6")"); fi
fi
[[ $(hostname -s) == inferswarm05 ]] || { printf 'requires CPU05\n' >&2; exit 2; }
[[ ! -e $build && ! -e $result ]] || { printf 'fresh output paths required\n' >&2; exit 2; }
python3 "$repo/tools/native-moe-overlap/hot-build-composed.py" \
  --archive "$archive" --output "$build" --benchmark-only
mkdir "$result"
result=$(realpath "$result")
# Fresh token binds a remote artifact and one owned process GROUP, not a name
# match or a local SSH PID. Keep the control artifact/logs on every outcome.
token=$(python3 -c 'import secrets;print(secrets.token_hex(16))')
printf '%s\n' "$token" >"$result/owner-token.txt"
control="$result/ssh-control.sock"
remote=hermes@100.77.187.38
helper="$repo/tools/native-moe-overlap/layer7_remote.py"
worker_ssh=
tunnel=
benchmark=
start_attempted=0
cleanup() {
  rc=$?
  trap - EXIT INT TERM
  set +e
  # Stop the supervisor first: it must never continue/relaunch after a signal.
  if [[ -n $benchmark ]]; then
    kill -TERM -- "-$benchmark" 2>/dev/null
    wait "$benchmark" 2>/dev/null
  fi
  if (( start_attempted )); then
    # Explicit bounded request over the existing master, BEFORE closing it.
    # Nonzero/connection loss is UNKNOWN/FAILED, never cleanup success.
    timeout --signal=TERM --kill-after=2 20 \
      ssh -S "$control" -o BatchMode=yes -o ConnectTimeout=5 "$remote" \
      python3 - cleanup "$token" <"$helper" >"$result/cleanup.json" 2>"$result/cleanup.log"
    cleanup_rc=$?
    if (( cleanup_rc != 0 )); then
      printf 'remote cleanup failed/unknown rc=%s; retained logs; timeout backstop still applies\n' "$cleanup_rc" >>"$result/cleanup.log"
      if [[ ! -s $result/cleanup.json ]]; then printf '{"cleanup":"unknown"}\n' >"$result/cleanup.json"; fi
      (( rc != 0 )) || rc=2
    elif ! python3 - "$result/cleanup.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]))
assert r['cleanup']=='verified' and r['owned_worker_absent'] and r['owned_listener_absent']
PY
    then
      (( rc != 0 )) || rc=2
    fi
  else
    printf '{"cleanup":"not-started"}\n' >"$result/cleanup.json"
  fi
  for pid in "$worker_ssh" "$tunnel"; do
    if [[ -n $pid ]]; then kill -TERM "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; fi
  done
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# One -L, no -R; the same SSH master carries start and cleanup requests.
# ExitOnForwardFailure refuses existing local listeners rather than replacing.
ssh -M -S "$control" -o BatchMode=yes -o ConnectTimeout=10 -o ExitOnForwardFailure=yes \
  -N -L 127.0.0.1:50060:127.0.0.1:50060 "$remote" >"$result/tunnel.log" 2>&1 &
tunnel=$!
for i in {1..100}; do
  kill -0 "$tunnel"
  [[ -S $control ]] && break
  sleep 0.05
done
kill -0 "$tunnel"
start_attempted=1
ssh -S "$control" -o BatchMode=yes -o ConnectTimeout=10 "$remote" \
  python3 - start "$token" <"$helper" >"$result/worker03.log" 2>&1 &
worker_ssh=$!
python3 - "$result/worker03.log" "$worker_ssh" "$tunnel" <<'PY'
import os,pathlib,sys,time
log=pathlib.Path(sys.argv[1]);deadline=time.monotonic()+10
while time.monotonic()<deadline:
    for pid in sys.argv[2:]:os.kill(int(pid),0)
    if 'H5_LAYER7_WORKER_READY pid=' in log.read_text(errors='replace'):break
    time.sleep(.05)
else:raise SystemExit('owned worker readiness absent; stop without benchmark/retry')
PY
# Defaults: production dimensions, 5 warm + 20 measured pairs per case.
# #346 batch sweep: widths 1,2,4,8,16, both set variants per width>1. Width 1
# is the historical single-token compatibility case. Bounded time budget:
# 18 cases x 25 pairs at these dimensions fit well inside the 300-second cap
# measured at T<=16 on loopback (about 0.2-2 ms per pair; the tunnel adds the
# 05->03 dispatch cost per step, still bounded by the worker's external cap).
setsid python3 "$repo/tools/native-moe-overlap/layer7_bench.py" \
  --build-receipt "$build/hot-candidate-receipt.json" \
  --output "$result/benchmark" --endpoint 127.0.0.1:50060 --threads 14 --timeout 300 \
  "${benchmark_args[@]}" \
  --comparison-mode cpu-cuda &
benchmark=$!
wait "$benchmark"
benchmark=
# EXIT performs acknowledged remote group termination and owned-listener proof.
# Refusal/signal/cleanup failure is terminal; no retry or optional second run.
