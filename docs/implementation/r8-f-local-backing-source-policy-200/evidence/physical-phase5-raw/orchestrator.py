#!/usr/bin/env python3
"""Issue #200 Phase-5 bounded physical Qwen proof — fleet orchestrator.

Runs on the orchestration host (zutfen), driving inferswarm01 (client) and
inferswarm04 (RPC participant) over SSH — the nodes hold no keys for each
other.  Executes the frozen three-arm comparison against the pinned R8-D
binaries and the accepted Qwen3.8-Flash-Next UD-IQ1_S release, retaining
every raw receipt the committed validator
(``scripts/issue200_r8f_physical.py``, schema
``inferswarm.issue200.physical-phase5/3``) independently re-derives the
acceptance predicates from.  It authors no acceptance booleans.

Frozen subject (identical across all three arms):
  - client: inferswarm01, pinned llama-server (R8-D binary identity)
  - participant: inferswarm04 RPC0 (RTX 3090), pinned ggml-rpc-server
  - required state: tensor ``blk.24.attn_gate.weight`` (Q5_K, 10,813,440
    bytes — the smallest cache-eligible tensor of the accepted release,
    exceeding the pinned HASH_THRESHOLD of 10 MiB) assigned to RPC0 via
    ``-ot``; every other tensor stays on the client exactly as the accepted
    R8-D placement computed it.
  - load subject: model init to "all slots are idle" with --no-warmup.

Arms:
  A cold_remote     — fresh empty participant cache; PREFER_REMOTE_AUTHORIZED.
  B local_verified  — fresh server process + fresh private cache dir,
                      pre-staged from InferSwarm-verified backing BEFORE any
                      client contact; REQUIRE_LOCAL_VERIFIED.
  C repeat_local    — another fresh server process against a SECOND fresh
                      pre-staged private cache (fresh re-staging from the
                      same verified local backing, zero network); proves
                      repeatable pre-staged consumption AND, separately,
                      the on-disk cache from arm B is retained for the
                      restart-durability observation; REQUIRE_LOCAL_VERIFIED.

Network evidence is the exact process-wide capture contract:
  strace -f --always-show-pid -ttt -xx -s 0 -e trace=network,write,writev -p <pid>

No llama.cpp source or binary is modified anywhere.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

CLIENT_HOST = "inferswarm01"
PARTICIPANT_HOST = "inferswarm04"
PARTICIPANT_ENDPOINT = "10.0.0.204:50052"
RPC_BIN = "/home/hermes/llama.cpp/build-v041/bin/ggml-rpc-server"
LLAMA_SERVER_BIN = "/home/hermes/llama.cpp/build-v041/bin/llama-server"
MODEL_MEMBER1 = "/srv/models/qwen38-ud-iq1-s/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf"
PARTICIPANT_MODEL = ("/srv/models/qwen38-ud-iq1-s/"
                     "Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf")
MEMBER3_BYTES = 22544696352
MEMBER3_SHA256 = "0e25ceaeb89b8a80aa973c6c0c7448943682f7408c2855b2ebd016b7643a861a"
TENSOR_NAME = "blk.24.attn_gate.weight"
TENSOR_ABS_OFFSET = 848968992
TENSOR_LENGTH = 10813440
TENSOR_SHA256 = "1c0284d8b85f4966e2dd1990271f3bc470667c11041d5d084be1ca511080f5f4"
TENSOR_FNV1A = "bbc9ae6a1038b6a6"
CLIENT_PORT = 8341

OUT_ROOT = Path("/tmp/issue200-p5-evidence")
REMOTE_WORK = "/tmp/i200p5"


def sh(host: str, cmd: str, *, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", host, cmd], capture_output=True, text=True,
                          timeout=timeout)


def canonical_json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode()


def stop_client() -> None:
    sh(CLIENT_HOST, "pkill -f 'llama-server.*8341' || true")
    time.sleep(2)


def stop_rpc() -> None:
    sh(PARTICIPANT_HOST, "pkill -f 'ggml-rpc-server' || true")
    deadline = time.time() + 30
    while time.time() < deadline:
        r = sh(PARTICIPANT_HOST, "pgrep -x ggml-rpc-server || true")
        if not (r.stdout or "").strip():
            return
        time.sleep(1)
    raise RuntimeError("rpc-server did not stop")


def start_rpc(cache_dir: str | None, tag: str) -> None:
    stop_rpc()
    env = f"LLAMA_CACHE={cache_dir} " if cache_dir else ""
    flag = "-c" if cache_dir else ""
    log = f"{REMOTE_WORK}/rpc-{tag}.log"
    sh(PARTICIPANT_HOST, f"mkdir -p {REMOTE_WORK}")
    sh(PARTICIPANT_HOST, f"{env}nohup {RPC_BIN} -H 0.0.0.0 -p 50052 -d CUDA0 {flag} > {log} 2>&1 &")
    deadline = time.time() + 30
    while time.time() < deadline:
        check = sh(PARTICIPANT_HOST, "ss -ltn | grep ':50052 '")
        if (check.stdout or "").strip():
            return
        time.sleep(1)
    raise RuntimeError(f"rpc-server did not listen: {sh(PARTICIPANT_HOST, f'tail -5 {log}').stdout}")


def wait_model_loaded(host: str, log: str, timeout: float = 900.0) -> float:
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = sh(host, f"grep -c 'listening on http://' {log} 2>/dev/null || true")
        if (r.stdout or "").strip() not in ("", "0"):
            return time.time() - t0
        r2 = sh(host, f"tail -c 2000 {log} 2>/dev/null")
        text = r2.stdout or ""
        if "exiting due to" in text or "failed to load model" in text:
            raise RuntimeError(f"client failed: {text[-600:]}")
        time.sleep(2)
    raise RuntimeError(f"client not ready within {timeout}s")


def run_arm(arm: str, cache_dir: str | None, stage: bool, out: Path) -> dict:
    arm_dir = out / "raw" / arm
    arm_dir.mkdir(parents=True, exist_ok=True)
    remote_arm_dir = f"{REMOTE_WORK}/{arm}"
    sh(CLIENT_HOST, f"mkdir -p {remote_arm_dir}")
    sh(PARTICIPANT_HOST, f"mkdir -p {REMOTE_WORK}")

    start_rpc(cache_dir, arm)

    # Every arm retains a participant-side measurement of the exact accepted
    # member range (the validator binds each arm's payload mapping to a
    # successful raw provenance invocation on the SET_TENSOR participant).
    r = sh(PARTICIPANT_HOST,
           f"cd /tmp && PYTHONPATH=/tmp python3 /tmp/issue200-range-receipt.py "
           f"--node-id {PARTICIPANT_HOST} --source-path {PARTICIPANT_MODEL} "
           f"--member Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf "
           f"--member-bytes {MEMBER3_BYTES} --member-sha256 {MEMBER3_SHA256} "
           f"--offset {TENSOR_ABS_OFFSET} --length {TENSOR_LENGTH} "
           f"--write-range {remote_arm_dir}/retained-range.bin", timeout=1800)
    (arm_dir / "range.stdout.json").write_bytes(r.stdout.encode())
    (arm_dir / "range.stderr").write_bytes(r.stderr.encode())
    if r.returncode != 0:
        raise RuntimeError(f"range receipt failed: {r.stderr[-500:]}")

    if stage:
        stage_sh = (
            "set -e\n"
            f"mkdir -p {cache_dir}/rpc\n"
            f"cp {remote_arm_dir}/retained-range.bin {cache_dir}/rpc/{TENSOR_FNV1A}.tmp\n"
            "actual=$(sha256sum " + cache_dir + f"/rpc/{TENSOR_FNV1A}.tmp | cut -d' ' -f1)\n"
            f"[ \"$actual\" = \"{TENSOR_SHA256}\" ] || {{ echo \"staged digest mismatch: $actual\"; exit 1; }}\n"
            f"mv {cache_dir}/rpc/{TENSOR_FNV1A}.tmp {cache_dir}/rpc/{TENSOR_FNV1A}\n"
            "after=$(sha256sum " + cache_dir + f"/rpc/{TENSOR_FNV1A} | cut -d' ' -f1)\n"
            "echo \"$after\"\n")
        r2 = sh(PARTICIPANT_HOST, "bash -c '" + stage_sh.replace("'", "'\\''") + "'", timeout=300)
        (arm_dir / "staging.stdout").write_bytes(r2.stdout.encode())
        (arm_dir / "staging.stderr").write_bytes(r2.stderr.encode())
        if r2.returncode != 0:
            raise RuntimeError(f"staging failed: {r2.stderr[-500:]}")

    pre = sh(PARTICIPANT_HOST,
             f"if [ -d {cache_dir}/rpc ]; then ls -la {cache_dir}/rpc/; else echo EMPTY; fi")
    (arm_dir / "cache-before.txt").write_bytes(pre.stdout.encode())

    # Launch client detached on the client host.
    ot = f"blk\\.24\\.attn_gate\\.weight=RPC0[{PARTICIPANT_ENDPOINT}]"
    client_log = f"{remote_arm_dir}/client.log"
    launch = f"""set -e
nohup {LLAMA_SERVER_BIN} -m {MODEL_MEMBER1} --rpc {PARTICIPANT_ENDPOINT} \\
  -ot '{ot}' --host 127.0.0.1 --port {CLIENT_PORT} -ngl 0 -c 8192 --no-warmup \\
  > {client_log} 2>&1 &
echo $!
"""
    r = sh(CLIENT_HOST, launch)
    pid = int((r.stdout or "").strip().splitlines()[-1])
    time.sleep(3)
    alive = sh(CLIENT_HOST, f"kill -0 {pid} && echo alive || echo dead")
    if "alive" not in (alive.stdout or ""):
        raise RuntimeError(f"client died at start: {sh(CLIENT_HOST, f'cat {client_log}').stdout[-500:]}")

    capture = (f"strace -f --always-show-pid -ttt -xx -s 0 "
               f"-e trace=network,write,writev -p {pid}")
    t_start = time.time()
    strace_launch = (f"nohup {capture} > {remote_arm_dir}/capture.strace 2>&1 & echo $!")
    rs = sh(CLIENT_HOST, strace_launch)
    strace_pid = int((rs.stdout or "").strip().splitlines()[-1])
    try:
        wall = wait_model_loaded(CLIENT_HOST, client_log)
    finally:
        t_end = time.time()
        sh(CLIENT_HOST, f"kill {strace_pid} || true")
        time.sleep(1)
        sh(CLIENT_HOST, f"kill {pid} || true; sleep 2; kill -9 {pid} 2>/dev/null || true")

    post = sh(PARTICIPANT_HOST,
              f"if [ -d {cache_dir}/rpc ]; then ls -la {cache_dir}/rpc/; else echo EMPTY; fi")
    (arm_dir / "cache-after.txt").write_bytes(post.stdout.encode())

    for name, remote in (("client.log", client_log),
                         ("capture.strace", f"{remote_arm_dir}/capture.strace"),
                         ("retained-range.bin", f"{remote_arm_dir}/retained-range.bin")):
        fetch = subprocess.run(["ssh", CLIENT_HOST if name != "retained-range.bin" or stage is False
                                else PARTICIPANT_HOST, f"cat {remote}"],
                               capture_output=True, timeout=600)
        if fetch.returncode == 0 and fetch.stdout is not None:
            (arm_dir / name).write_bytes(fetch.stdout)
    server_log = subprocess.run(["ssh", PARTICIPANT_HOST, f"cat {REMOTE_WORK}/rpc-{arm}.log"],
                                capture_output=True, timeout=120)
    (arm_dir / "rpc-server.log").write_bytes(server_log.stdout or b"")

    return {"arm": arm, "client_pid": pid, "strace_pid": strace_pid,
            "wall_s": round(wall, 3),
            "capture_started": str(t_start), "capture_ended": str(t_end),
            "cache_dir": cache_dir or "",
            "rpc_endpoint": PARTICIPANT_ENDPOINT}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT_ROOT)
    args = parser.parse_args()
    out: Path = args.out
    if out.exists():
        shutil.rmtree(out)
    (out / "raw").mkdir(parents=True)

    stop_client()
    results = {}

    cache_a = f"{REMOTE_WORK}/armA-cache"
    sh(PARTICIPANT_HOST, f"rm -rf {cache_a} && mkdir -p {cache_a}/rpc")
    results["cold_remote"] = run_arm("cold_remote", cache_a, stage=False, out=out)
    stop_client()

    cache_b = f"{REMOTE_WORK}/armB-cache"
    sh(PARTICIPANT_HOST, f"rm -rf {cache_b} && mkdir -p {cache_b}/rpc")
    results["local_verified"] = run_arm("local_verified", cache_b, stage=True, out=out)
    stop_client()

    cache_c = f"{REMOTE_WORK}/armC-cache"
    sh(PARTICIPANT_HOST, f"rm -rf {cache_c} && mkdir -p {cache_c}/rpc")
    results["repeat_local_verified"] = run_arm("repeat_local_verified", cache_c, stage=True, out=out)
    stop_client()
    stop_rpc()

    (out / "run-summary.json").write_bytes(canonical_json_bytes(results))
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
