#!/usr/bin/env python3
"""Issue #199 R8-E: launch orchestration helper (on-host, inferswarm01).

Emits the frozen observation-arm launch scripts. The observation arms use
the accepted placements with the SAME launch semantics as R8-D v2, with
two differences, both authorized by Issue #199:
  - reference/candidate observation servers run the DIAGNOSTIC binary
    llama-server-obs (observation-only patch; accepted binary used for
    all non-perturbation token-equality proofs);
  - RPC backends (candidate arm) run the ACCEPTED ggml-rpc-server
    binaries UNCHANGED (no instrumentation exists or is needed there —
    sampling runs in the client llama-server process).

Not correctness-bearing by itself; the generated launch bytes are
evidence and are checked by the terminal reducer.
"""
import argparse

REF_PORT = 8331
CAND_PORT = 8333
ACCEPTED_BIN = "/home/hermes/llama.cpp/build-v041/bin/llama-server"
OBS_BIN = "/home/hermes/llama.cpp/build-obs/bin/llama-server"
RPC_BIN = "/home/hermes/llama.cpp/build-v041/bin/ggml-rpc-server"
MODEL = ("/srv/models/qwen38-ud-iq1-s/"
         "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf")
RPC_EP = "10.0.0.219:50052,10.0.0.219:50053,10.0.0.204:50052"
TMP = "/tmp/i199"

REF_OBS_SH = f"""#!/usr/bin/env bash
set -euo pipefail
LOG=${{1:-{TMP}/ref-obs-server.log}}
mkdir -p {TMP}
rm -f "$LOG"
# R8-E reference observation arm: accepted R8-D reference placement
# (single-host llama-server on inferswarm01, NO RPC), DIAGNOSTIC binary.
nohup {OBS_BIN} -m {MODEL} -c 8192 --host 127.0.0.1 --port {REF_PORT} -lv 4 > "$LOG" 2>&1 &
echo "ref-obs pid=$!"
"""

REF_ACCEPTED_SH = f"""#!/usr/bin/env bash
set -euo pipefail
LOG=${{1:-{TMP}/ref-accepted-server.log}}
mkdir -p {TMP}
rm -f "$LOG"
# R8-E non-perturbation control: ACCEPTED uninstrumented binary,
# accepted reference placement (identical to R8-D v2 reference launch).
nohup {ACCEPTED_BIN} -m {MODEL} -c 8192 --host 127.0.0.1 --port {REF_PORT} -lv 4 > "$LOG" 2>&1 &
echo "ref-accepted pid=$!"
"""

CAND_OBS_SH = f"""#!/usr/bin/env bash
set -euo pipefail
LOG=${{1:-{TMP}/cand-obs-server.log}}
mkdir -p {TMP}
rm -f "$LOG"
# R8-E candidate observation arm: accepted 5-device topology (client on
# inferswarm01 + RPC backends 03:50052/03:50053/04:50052), DIAGNOSTIC
# client binary; RPC backends are the ACCEPTED uninstrumented binaries.
nohup {OBS_BIN} -m {MODEL} -c 8192 --host 127.0.0.1 --port {CAND_PORT} --rpc {RPC_EP} -lv 4 > "$LOG" 2>&1 &
echo "cand-obs pid=$!"
"""

CAND_ACCEPTED_SH = f"""#!/usr/bin/env bash
set -euo pipefail
LOG=${{1:-{TMP}/cand-accepted-server.log}}
mkdir -p {TMP}
rm -f "$LOG"
# R8-E non-perturbation control: ACCEPTED uninstrumented client binary,
# accepted 5-device placement (identical to R8-D v2 candidate launch).
nohup {ACCEPTED_BIN} -m {MODEL} -c 8192 --host 127.0.0.1 --port {CAND_PORT} --rpc {RPC_EP} -lv 4 > "$LOG" 2>&1 &
echo "cand-accepted pid=$!"
"""

RPC03_G0 = f"""#!/usr/bin/env bash
set -euo pipefail
LOG={TMP}/rpc03-g0.log
mkdir -p {TMP}
rm -f "$LOG"
nohup {RPC_BIN} -H 0.0.0.0 -p 50052 -d CUDA0 > "$LOG" 2>&1 &
echo "rpc03-g0 pid=$!"
"""

RPC03_G1 = f"""#!/usr/bin/env bash
set -euo pipefail
LOG={TMP}/rpc03-g1.log
mkdir -p {TMP}
rm -f "$LOG"
nohup {RPC_BIN} -H 0.0.0.0 -p 50053 -d CUDA1 > "$LOG" 2>&1 &
echo "rpc03-g1 pid=$!"
"""

RPC04 = f"""#!/usr/bin/env bash
set -euo pipefail
LOG=/tmp/i199/rpc04.log
mkdir -p /tmp/i199
rm -f "$LOG"
nohup {RPC_BIN} -H 0.0.0.0 -p 50052 -d CUDA0 > "$LOG" 2>&1 &
echo "rpc04 pid=$!"
"""

SCRIPTS = {
    "ref-obs": REF_OBS_SH, "ref-accepted": REF_ACCEPTED_SH,
    "cand-obs": CAND_OBS_SH, "cand-accepted": CAND_ACCEPTED_SH,
    "rpc03g0": RPC03_G0, "rpc03g1": RPC03_G1, "rpc04": RPC04,
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
        json.dump({"pids": recs, "all_gone": ok}, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("which", choices=list(SCRIPTS) + ["pidproof"])
    ap.add_argument("args", nargs="*")
    a = ap.parse_args()
    if a.which == "pidproof":
        return pidproof(a.args[0].split(","), a.args[1])
    print(SCRIPTS[a.which])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
