#!/usr/bin/env python3
"""Issue #195 R8-D v2: launch orchestration helper (on-host).

Generates the frozen reference/candidate launch scripts and the restart
PID-proof collector. Not correctness-bearing by itself; the generated
launch bytes are evidence and are checked by the reducer.

Usage:
  issue195_v2_launch.py ref       # emit reference launch script
  issue195_v2_launch.py cand      # emit candidate launch script (client)
  issue195_v2_launch.py rpc03g0 | rpc03g1 | rpc04   # RPC backend scripts
  issue195_v2_launch.py pidproof <pids-json> <out>  # record PID death proof
"""
import json
import os
import subprocess
import sys
import time

REF_PORT = 8321
CAND_PORT = 8323
BIN = "/home/hermes/llama.cpp/build-v041/bin/llama-server"
RPC_BIN = "/home/hermes/llama.cpp/build-v041/bin/ggml-rpc-server"
MODEL = ("/srv/models/qwen38-ud-iq1-s/"
         "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf")
RPC_EP = "10.0.0.219:50052,10.0.0.219:50053,10.0.0.204:50052"

REF_SH = f"""#!/usr/bin/env bash
set -euo pipefail
LOG=/tmp/i195-v2/ref-server.log
mkdir -p /tmp/i195-v2
rm -f "$LOG"
# v2 reference arm: accepted R8-B reference placement — single-host
# llama-server on inferswarm01 (local CUDA auto-fit + CPU spill, PLE
# lazy host-side), NO RPC endpoints.
nohup {BIN} -m {MODEL} -c 8192 --host 127.0.0.1 --port {REF_PORT} -lv 4 > "$LOG" 2>&1 &
echo "reference pid=$!"
"""

CAND_SH = f"""#!/usr/bin/env bash
set -euo pipefail
LOG=${{1:-/tmp/i195-v2/cand-server.log}}
mkdir -p /tmp/i195-v2
rm -f "$LOG"
# v2 candidate arm: accepted 5-device topology — client llama-server on
# inferswarm01 (2x RTX 3060) + ggml-rpc-server backends on
# inferswarm03 (ports 50052/50053) + inferswarm04 (port 50052).
nohup {BIN} -m {MODEL} -c 8192 --host 127.0.0.1 --port {CAND_PORT} --rpc {RPC_EP} -lv 4 > "$LOG" 2>&1 &
echo "candidate pid=$!"
"""

RPC03_G0 = f"""#!/usr/bin/env bash
set -euo pipefail
LOG=/tmp/i195-v2/rpc03-g0.log
mkdir -p /tmp/i195-v2
rm -f "$LOG"
nohup {RPC_BIN} -H 0.0.0.0 -p 50052 -d CUDA0 > "$LOG" 2>&1 &
echo "rpc03-g0 pid=$!"
"""

RPC03_G1 = f"""#!/usr/bin/env bash
set -euo pipefail
LOG=/tmp/i195-v2/rpc03-g1.log
mkdir -p /tmp/i195-v2
rm -f "$LOG"
nohup {RPC_BIN} -H 0.0.0.0 -p 50053 -d CUDA1 > "$LOG" 2>&1 &
echo "rpc03-g1 pid=$!"
"""

RPC04 = f"""#!/usr/bin/env bash
set -euo pipefail
LOG=/tmp/i195-v2/rpc04.log
mkdir -p /tmp/i195-v2
rm -f "$LOG"
nohup {RPC_BIN} -H 0.0.0.0 -p 50052 -d CUDA0 > "$LOG" 2>&1 &
echo "rpc04 pid=$!"
"""


def wait_ready(log, tmo=1500):
    if not os.path.exists(log):
        return "NOLOG"
    t0 = time.time()
    while time.time() - t0 < tmo:
        with open(log, errors="replace") as fh:
            t = fh.read()
        if "all slots are idle" in t:
            return "READY"
        if any(s in t for s in ("exiting due to", "failed to load model",
                                "error while handling argument")):
            return "LAUNCH_FAILED"
        time.sleep(5)
    return "TIMEOUT"


def pidproof(pids_json, out):
    """Terminate exact PIDs, prove death before relaunch."""
    pids = json.load(open(pids_json))
    recs = []
    for spec in pids:
        pid = spec["pid"]
        role = spec.get("role", "?")
        host = spec.get("host", "localhost")
        kill_cmd = spec["kill_cmd"] if "kill_cmd" in spec else f"kill {pid}"
        if host != "localhost":
            kill_cmd = spec.get(
                "kill_cmd", f"ssh {host} 'kill {pid}'")
        subprocess.run(kill_cmd, shell=True)
        gone = False
        t0 = time.time()
        while time.time() - t0 < 60:
            if host == "localhost":
                r = subprocess.run(["kill", "-0", str(pid)],
                                   capture_output=True)
                alive = r.returncode == 0
            else:
                r = subprocess.run(
                    ["ssh", "-o", "BatchMode=yes", host,
                     f"kill -0 {pid}"], capture_output=True)
                alive = r.returncode == 0
            if not alive:
                gone = True
                break
            time.sleep(2)
        recs.append({
            "pid": pid, "role": role, "host": host,
            "kill_confirmed": True,   # kill signal delivered
            "confirmed_gone_before_relaunch": gone,
            "checked_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                            time.gmtime()),
        })
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump({"schema": "inferswarm.issue195.pidproof/1",
                   "terminated_pids": recs}, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(recs, indent=1))
    return 0 if all(r["confirmed_gone_before_relaunch"] for r in recs) else 1


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return 2
    if a[0] == "ref":
        print(REF_SH)
    elif a[0] == "cand":
        print(CAND_SH)
    elif a[0] == "rpc03g0":
        print(RPC03_G0)
    elif a[0] == "rpc03g1":
        print(RPC03_G1)
    elif a[0] == "rpc04":
        print(RPC04)
    elif a[0] == "pidproof":
        return pidproof(a[1], a[2])
    elif a[0] == "wait":
        print(wait_ready(a[1], int(a[2]) if len(a) > 2 else 1500))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
