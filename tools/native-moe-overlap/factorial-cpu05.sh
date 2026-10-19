#!/usr/bin/env bash
# FUTURE CPU05 dispatch only, inside the existing long-lived ssh -A controller.
# Coding this launcher does not authorize a hardware dispatch.
set -euo pipefail
if [[ $# != 4 ]]; then
  printf 'usage: bash %s EXACT_HEAD_REPO AUTHENTICATED_SOURCE_ARCHIVE FRESH_BUILD FRESH_RESULT\n' "$0" >&2
  exit 2
fi
repo=$(realpath "$1")
archive=$(realpath "$2")
build=$3
result=$4
[[ $(hostname -s) == inferswarm05 ]] || { printf 'requires CPU05\n' >&2; exit 2; }
[[ -n ${SSH_AUTH_SOCK:-} && -S $SSH_AUTH_SOCK ]] || { printf 'requires established agent-forwarded controller lifetime\n' >&2; exit 2; }
[[ ! -e $build && ! -e $result ]] || { printf 'fresh output paths required\n' >&2; exit 2; }
[[ -z $(git -C "$repo" status --porcelain) ]] || { printf 'exact clean checkout required\n' >&2; exit 2; }
mkdir "$result"
result=$(realpath "$result")
git -C "$repo" rev-parse HEAD >"$result/experiment-head.txt"
token=$(python3 -c 'import secrets;print(secrets.token_hex(16))')
printf '%s\n' "$token" >"$result/owner-token.txt"
control="$result/ssh-control.sock"
remote=hermes@100.77.187.38
helper="$repo/tools/native-moe-overlap/factorial_remote.py"
worker_ssh=
tunnel=
benchmark=
start_attempted=0
cleanup() {
  rc=$?
  trap - EXIT INT TERM
  set +e
  if [[ -n $benchmark ]]; then
    kill -TERM -- "-$benchmark" 2>/dev/null
    wait "$benchmark" 2>/dev/null
  fi
  if (( start_attempted )); then
    timeout --signal=TERM --kill-after=2 20 \
      ssh -S "$control" -o BatchMode=yes -o ConnectTimeout=5 "$remote" \
      python3 - cleanup "$token" <"$helper" >"$result/cleanup.json" 2>"$result/cleanup.log"
    cleanup_rc=$?
    if (( cleanup_rc != 0 )); then
      printf 'remote cleanup failed/unknown rc=%s; preserved logs; 360-second backstop applies\n' "$cleanup_rc" >>"$result/cleanup.log"
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
  python3 - "$result" <<'PY'
import pathlib,sys
root=pathlib.Path(sys.argv[1]); size=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
if size>8*1024**3: raise SystemExit('8 GiB complete result evidence cap exceeded; STOP')
PY
  storage_rc=$?
  (( storage_rc == 0 || rc != 0 )) || rc=2
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# The full preparation cap includes both native build and offline helper build.
# No worker, SSH tunnel or GPU activity precedes successful preparation.
timeout --signal=TERM --kill-after=5 900 bash -c '
  set -euo pipefail
  python3 "$1/tools/native-moe-overlap/factorial-build.py" --archive "$2" --output "$3"
  c++ -O3 -std=c++17 -shared -fPIC -mf16c -ffp-contract=off \
    "$1/tools/native-moe-overlap/layer7_arithmetic.cpp" -o "$3/helper.so"
' _ "$repo" "$archive" "$build" >"$result/preparation.log" 2>&1
python3 - "$result" "$build" <<'PY'
import hashlib,json,pathlib,shutil,sys
root=pathlib.Path(sys.argv[1]); build=pathlib.Path(sys.argv[2])
memory={line.split(':',1)[0]:int(line.split()[1])*1024 for line in pathlib.Path('/proc/meminfo').read_text().splitlines()}
free=shutil.disk_usage(root).free
record=dict(cpu_mem_available_bytes=memory['MemAvailable'],minimum_cpu_available_bytes=8*1024**3,
            result_filesystem_free_bytes=free,minimum_result_free_bytes=9*1024**3,evidence_cap_bytes=8*1024**3,
            helper_sha256=hashlib.sha256((build/'helper.so').read_bytes()).hexdigest(),
            gpu_minimum_free_mib=2048,additional_gpu_allocation_envelope_mib=512,
            note='conservative feasibility floors for full synthetic CPU weights, native arenas, staging and CUDA context; not measured memory fit')
(root/'preflight.json').write_text(json.dumps(record,sort_keys=True,indent=2)+'\n')
if memory['MemAvailable']<8*1024**3 or free<9*1024**3: raise SystemExit('CPU RAM/disk headroom floor failed; no worker started')
PY
# One -L and no -R. This same master owns worker start and explicit cleanup.
ssh -M -S "$control" -o BatchMode=yes -o ConnectTimeout=10 -o ExitOnForwardFailure=yes \
  -N -L 127.0.0.1:50060:127.0.0.1:50060 "$remote" >"$result/tunnel.log" 2>&1 &
tunnel=$!
for i in {1..100}; do
  kill -0 "$tunnel"
  [[ -S $control ]] && break
  sleep 0.05
done
kill -0 "$tunnel"
[[ -S $control ]] || { printf 'SSH master not ready; STOP\n' >&2; exit 2; }
start_attempted=1
ssh -S "$control" -o BatchMode=yes -o ConnectTimeout=10 "$remote" \
  python3 - start "$token" <"$helper" >"$result/worker03.log" 2>&1 &
worker_ssh=$!
python3 - "$result/worker03.log" "$worker_ssh" "$tunnel" <<'PY'
import os,pathlib,sys,time
log=pathlib.Path(sys.argv[1]); deadline=time.monotonic()+10
while time.monotonic()<deadline:
    for pid in sys.argv[2:]: os.kill(int(pid),0)
    if 'H5_LAYER7_WORKER_READY pid=' in log.read_text(errors='replace'): break
    time.sleep(.05)
else: raise SystemExit('owned worker readiness absent; STOP without retry')
PY
# Fixed default: T1 mixed/T4 varied, five warmup/twenty measured fixture blocks,
# CPU plus four cells; one excluded same-fixture prime immediately per arm.
setsid python3 "$repo/tools/native-moe-overlap/factorial_run.py" \
  --build-receipt "$build/factorial-candidate-receipt.json" \
  --output "$result/benchmark" --endpoint 127.0.0.1:50060 --threads 14 --timeout 300 \
  --comparison-mode cpu-cuda &
benchmark=$!
wait "$benchmark"
benchmark=
# EXIT proves owned worker/listener absence. Only then run the separate offline
# checker, outside this launcher and its 360-second worker lifetime.
