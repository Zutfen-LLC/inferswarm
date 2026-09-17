#!/usr/bin/env python3
"""Issue #207 R8-G: launch orchestration helper (on-host, inferswarm01).

Emits the frozen observation-arm launch script. The observation arms use
the accepted placements with the SAME launch semantics as R8-D v2/R8-E,
with two differences, both authorized by Issue #207:
  - the observation servers run the R8-G DIAGNOSTIC binary
    llama-server-r8g (observation-only patch from the exact accepted
    source b29c606e; accepted binaries used for all non-perturbation
    token-equality proofs);
  - the servers run with --no-warmup so NO graph executes before the
    request (occurrence 0 of every boundary name is provably the first
    graph execution of the captured request; the capture producer
    additionally proves the boundary JSONL is empty pre-request).
RPC backends (candidate arm) run the ACCEPTED ggml-rpc-server binaries
UNCHANGED.

Not correctness-bearing by itself; the generated launch bytes are
evidence and are checked by the terminal reducer.
"""
import argparse

REF_PORT = 8341
CAND_PORT = 8343
ACCEPTED_BIN = "/home/hermes/llama.cpp/build-v041/bin/llama-server"
OBS_BIN = "/home/hermes/llama.cpp/r8g-obs/build-r8g/bin/llama-server"
RPC_BIN = "/home/hermes/llama.cpp/build-v041/bin/ggml-rpc-server"
MODEL = ("/srv/models/qwen38-ud-iq1-s/"
         "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf")
RPC_EP = "10.0.0.219:50052,10.0.0.219:50053,10.0.0.204:50052"
TMP = "/tmp/i207"

LAUNCH_SH = f"""#!/usr/bin/env bash
# R8-G observation-arm server launcher (generated; Issue #207).
# $1 = arm (reference|candidate)
# $2 = boundary-out dir; $3 = boundary jsonl; $4 = logits jsonl
# $5 = boundary spec; $6 = log file
set -euo pipefail
ARM=$1; BOUT=$2; BJSONL=$3; LJSONL=$4; SPEC=$5; LOG=$6
mkdir -p "$BOUT" "$TMP"; rm -f "$LOG"
if [ "$ARM" = candidate ]; then
  EX="--rpc {RPC_EP}"
else
  EX=""
fi
LLAMA_OBSERVE_BOUNDARIES="$SPEC" \\
LLAMA_OBSERVE_BOUNDARY_OUT="$BOUT" \\
LLAMA_OBSERVE_BOUNDARY_JSONL="$BJSONL" \\
LLAMA_OBSERVE_LOGITS="$LJSONL" \\
nohup {OBS_BIN} -m {MODEL} -c 8192 --host 127.0.0.1 \\
  --port $([ "$ARM" = candidate ] && echo {CAND_PORT} || echo {REF_PORT}) \\
  -lv 4 --no-warmup $EX > "$LOG" 2>&1 &
echo "obs pid=$!"
"""

LAUNCH_ACCEPTED_SH = f"""#!/usr/bin/env bash
# R8-G non-perturbation control: ACCEPTED uninstrumented binary,
# accepted placements (identical to R8-D v2 / R8-E accepted launches).
set -euo pipefail
ARM=${{1:-reference}}; LOG=${{2:-{TMP}/acc-server.log}}
mkdir -p {TMP}; rm -f "$LOG"
if [ "$ARM" = candidate ]; then EX="--rpc {RPC_EP}"; else EX=""; fi
nohup {ACCEPTED_BIN} -m {MODEL} -c 8192 --host 127.0.0.1 \\
  --port $([ "$ARM" = candidate ] && echo {CAND_PORT} || echo {REF_PORT}) \\
  -lv 4 $EX > "$LOG" 2>&1 &
echo "accepted pid=$!"
"""

WAIT_SH = """#!/usr/bin/env bash
# R8-G: wait for the 3 accepted RPC backends (launched/stopped by the
# orchestrator host; nodes hold no keys for each other).
set -euo pipefail
for EP in 10.0.0.219:50052 10.0.0.219:50053 10.0.0.204:50052; do
  H=${EP%:*}; P=${EP#*:}
  ok=""
  for I in $(seq 1 100); do
    if timeout 3 bash -c "echo > /dev/tcp/$H/$P" 2>/dev/null; then ok=1; break; fi
    sleep 3
  done
  [ -n "$ok" ] || { echo "$EP NOT reachable"; exit 1; }
  echo "$EP reachable"
done
echo BACKENDS_REACHABLE
"""

STOP_SH = """#!/usr/bin/env bash
# R8-G: barrier — RPC backends are stopped by the ORCHESTRATOR host.
# Proves from inferswarm01 that all three endpoints are DOWN (fail-closed).
set -euo pipefail
for EP in 10.0.0.219:50052 10.0.0.219:50053 10.0.0.204:50052; do
  H=${EP%:*}; P=${EP#*:}
  still=""
  for I in $(seq 1 40); do
    if timeout 3 bash -c "echo > /dev/tcp/$H/$P" 2>/dev/null; then
      still=1; sleep 3
    else
      still=""; break
    fi
  done
  [ -z "$still" ] || { echo "$EP STILL reachable"; exit 1; }
  echo "$EP down"
done
echo BACKENDS_CONFIRMED_DOWN
"""

RPC_SCRIPTS = {
    "rpc03g0": f"""#!/usr/bin/env bash
set -euo pipefail
LOG={TMP}/rpc03-g0.log
mkdir -p {TMP}; rm -f "$LOG"
nohup {RPC_BIN} -H 0.0.0.0 -p 50052 -d CUDA0 > "$LOG" 2>&1 &
echo "rpc03-g0 pid=$!"
""",
    "rpc03g1": f"""#!/usr/bin/env bash
set -euo pipefail
LOG={TMP}/rpc03-g1.log
mkdir -p {TMP}; rm -f "$LOG"
nohup {RPC_BIN} -H 0.0.0.0 -p 50053 -d CUDA1 > "$LOG" 2>&1 &
echo "rpc03-g1 pid=$!"
""",
    "rpc04": """#!/usr/bin/env bash
set -euo pipefail
LOG=/tmp/i207/rpc04.log
mkdir -p /tmp/i207; rm -f "$LOG"
nohup %s -H 0.0.0.0 -p 50052 -d CUDA0 > "$LOG" 2>&1 &
echo "rpc04 pid=$!"
""" % RPC_BIN,
}


def pidproof(pids, out):
    """Terminate exact PIDs by SIGTERM, prove death before return."""
    import json
    import os
    import signal
    import time
    recs = []
    for pid in pids:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.time() + 60
    for pid in pids:
        gone = False
        while time.time() < deadline:
            try:
                os.kill(int(pid), 0)
                time.sleep(1)
            except ProcessLookupError:
                gone = True
                break
        recs.append({"pid": int(pid), "confirmed_gone": gone})
    ok = all(r["confirmed_gone"] for r in recs)
    with open(out, "w") as fh:
        json.dump({"pids": recs, "all_gone": ok}, fh, indent=2,
                  sort_keys=True)
        fh.write("\n")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("which", choices=["emit"] + list(RPC_SCRIPTS) +
                    ["pidproof"])
    ap.add_argument("args", nargs="*")
    a = ap.parse_args()
    if a.which == "pidproof":
        return pidproof(a.args[0].split(","), a.args[1])
    if a.which in RPC_SCRIPTS:
        print(RPC_SCRIPTS[a.which])
        return 0
    import os
    import stat
    os.makedirs(a.args[0], exist_ok=True)
    for name, body in (("r8g-launch-obs.sh", LAUNCH_SH),
                       ("r8g-launch-accepted.sh", LAUNCH_ACCEPTED_SH),
                       ("wait_backends.sh", WAIT_SH),
                       ("stop_backends_barrier.sh", STOP_SH)):
        p = os.path.join(a.args[0], name)
        with open(p, "w") as fh:
            fh.write(body)
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
        print("wrote", p)


if __name__ == "__main__":
    raise SystemExit(main())
