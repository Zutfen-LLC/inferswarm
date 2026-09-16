#!/usr/bin/env python3
"""Issue #200 Phase-5 bounded physical Qwen proof — fleet orchestrator (v3).

Correction round 3.  Drives inferswarm01 (client) and inferswarm04 (RPC
participant) over SSH from the orchestration host.  This script is a
COMMITTED, PROVENANCE-BOUND producer (review item 4): the assembler copies
it byte-for-byte into the retained evidence tree and the evidence graph
binds its exact SHA-256.

Changes vs the round-2 orchestrator (/tmp/i200p5c2_orchestrator.py):

- Deploys the HARDENED committed helpers (backing_verify, cache_enum with
  tool identity + real argv, stage_cache, range_receipt) to the participant
  and invokes those exact bytes, so every helper receipt carries the exact
  committed helper SHA-256 the validator demands.
- Fresh private cache/run IDs under /tmp/i200p5c3 (review item 4's rerun
  condition): /tmp/i200p5c3/<arm>-cache.
- The run summary retains only orchestrator-side wall-clock facts and is
  explicitly NON-AUTHORITATIVE (the assembler no longer consumes it for any
  acceptance-significant field; client/RPC argv and PIDs are read from the
  captures' own first execve records).
- Retains the capture's strace argv for cross-check only.

Arms:
  A cold_remote     — fresh empty participant cache; PREFER_REMOTE_AUTHORIZED.
  B local_verified  — fresh private cache dir, pre-staged from verified
                      participant backing BEFORE any client contact.
  C repeat_local_verified — fresh server + fresh client against arm B's
                      already-populated cache, NO restaging.
"""
from __future__ import annotations

import hashlib
import json
import shlex as _shlex_mod
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path("/home/zutfen/code/inferswarm/scripts")))
import issue200_r8f_network_reduce as network_reduce  # noqa: E402


def _shlex_quote(text: str) -> str:
    return _shlex_mod.quote(text)


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
STRACE_LIMIT = TENSOR_LENGTH + 4096

BACKING_DIR = "/srv/models/qwen38-ud-iq1-s"
REMOTE_WORK = "/tmp/i200p5c3"
OUT_ROOT = Path("/tmp/issue200-p5c3-evidence")
REPO_SCRIPTS = Path("/home/zutfen/code/inferswarm/scripts")

HELPERS = ["issue200_r8f_backing_verify.py", "issue200_r8f_cache_enum.py",
           "issue200_r8f_range_receipt.py", "issue200_r8f_stage_cache.py",
           "issue74_methodology.py"]

# Authorities staged to the participant for the helpers' exact-byte identity.
AUTHORITY_LOCAL = REPO_SCRIPTS.parent / "docs/investigations/qwen38-flash-next-r8-d-v2/evidence/split-identity/split-rehash.json"


def sh(host: str, cmd: str, *, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", "-n", host, cmd], capture_output=True, text=True, timeout=timeout)


def canonical_json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode()


def deploy_helpers() -> None:
    """Copy the exact committed helper bytes to the participant and record
    their deployed digests (the receipts' tool.sha256 must equal these)."""
    sh(PARTICIPANT_HOST, f"mkdir -p {REMOTE_WORK}")
    for name in HELPERS:
        local = REPO_SCRIPTS / name
        data = local.read_bytes()
        r = subprocess.run(["ssh", PARTICIPANT_HOST, f"cat > {REMOTE_WORK}/{name}"],
                           input=data, capture_output=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"deploy {name} failed: {r.stderr.decode()[-200:]}")
        check = sh(PARTICIPANT_HOST, f"sha256sum {REMOTE_WORK}/{name}")
        deployed = (check.stdout or "").split()[0]
        if deployed != hashlib.sha256(data).hexdigest():
            raise RuntimeError(f"deployed helper digest mismatch: {name}")
    # Stage the authority JSON for the backing verifier at a path whose
    # suffix equals the committed repo-relative authority path, so receipts
    # record an exact-path binding to the committed authority (content is
    # independently verified by member identity against the repo copy).
    authority_remote = (f"{REMOTE_WORK}/docs/investigations/qwen38-flash-next-r8-d-v2/"
                        f"evidence/split-identity/split-rehash.json")
    data = AUTHORITY_LOCAL.read_bytes()
    r = subprocess.run(["ssh", PARTICIPANT_HOST, f"mkdir -p $(dirname {authority_remote}) && cat > {authority_remote}"],
                       input=data, capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("deploy authority failed")
    print("helpers deployed")


def stop_client() -> None:
    sh(CLIENT_HOST, "pkill -f 'llama-server.*8341' || true")
    time.sleep(2)


def stop_rpc() -> None:
    sh(PARTICIPANT_HOST, "pkill -x ggml-rpc-server || true")
    deadline = time.time() + 30
    while time.time() < deadline:
        r = sh(PARTICIPANT_HOST, "pgrep -x ggml-rpc-server || true")
        if not (r.stdout or "").strip():
            return
        time.sleep(1)
    raise RuntimeError("rpc-server did not stop")


def start_rpc_straced(cache_dir: str, arm: str, out: Path) -> dict:
    """Launch the participant ggml-rpc-server UNDER strace -f -e trace=%file,read
    (from exec), LLAMA_CACHE=<cache_dir>, -c enabled.  Returns launch facts."""
    log = f"{REMOTE_WORK}/rpc-{arm}.log"
    strace_log = f"{REMOTE_WORK}/rpc-{arm}.file.strace"
    sh(PARTICIPANT_HOST, f"rm -f {strace_log}")
    started = time.time()
    inner = (f"cd {REMOTE_WORK} && LLAMA_CACHE={cache_dir} nohup strace -f -ttt -xx -s 4096 "
             f"-e trace=%file,read -o {strace_log} {RPC_BIN} -H 0.0.0.0 -p 50052 -d CUDA0 -c "
             f"> {log} 2>&1 < /dev/null & echo $! > {REMOTE_WORK}/rpc-{arm}.pid")
    launch = 'setsid bash -c ' + _shlex_quote(inner) + ' < /dev/null > /dev/null 2>&1; exit 0'
    sh(PARTICIPANT_HOST, launch)
    import re as _re
    pid = 0
    for _ in range(40):
        r = sh(PARTICIPANT_HOST, f"head -c 200 {strace_log} 2>/dev/null || true")
        m = _re.match(r"\s*(\d+)", r.stdout or "")
        if m:
            pid = int(m.group(1))
            break
        time.sleep(0.5)
    if pid <= 0:
        raise RuntimeError(f"{arm}: rpc-server capture did not start")
    deadline = time.time() + 30
    while time.time() < deadline:
        check = sh(PARTICIPANT_HOST, "ss -ltn | grep ':50052 '")
        if (check.stdout or "").strip():
            return {"arm": arm, "pid": pid, "started_at": started, "server_log": log,
                    "strace_log": strace_log, "argv": ["ggml-rpc-server", "-H", "0.0.0.0",
                                                       "-p", "50052", "-d", "CUDA0", "-c"],
                    "env": {"LLAMA_CACHE": cache_dir}}
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


def fetch(host: str, remote: str, dest: Path) -> None:
    r = subprocess.run(["ssh", host, f"cat {remote}"], capture_output=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f"fetch {host}:{remote} failed: {r.stderr.decode()[-300:]}")
    dest.write_bytes(r.stdout)


def live_binary_receipt(host: str, binary: str, out: Path, name: str) -> dict:
    r = sh(host, f"sha256sum {binary}")
    digest = (r.stdout or "").split()[0]
    path = out / name
    path.write_bytes(canonical_json_bytes({"argv": ["sha256sum", binary], "sha256": digest}))
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "binary_digest": digest, "argv": ["sha256sum", binary]}


def run_arm(arm: str, cache_dir: str, stage: bool, reuse_of: str | None, out: Path,
            summary: dict) -> dict:
    arm_dir = out / "raw" / arm
    arm_dir.mkdir(parents=True, exist_ok=True)
    remote_arm_dir = f"{REMOTE_WORK}/{arm}"
    sh(CLIENT_HOST, f"mkdir -p {remote_arm_dir}")
    sh(PARTICIPANT_HOST, f"mkdir -p {REMOTE_WORK}")

    # 1. Fresh-cache initialization / reuse pre-check receipt.
    if reuse_of is None:
        r = sh(PARTICIPANT_HOST,
               f"python3 {REMOTE_WORK}/issue200_r8f_cache_enum.py {arm} {cache_dir}")
        (arm_dir / "cache-init.stdout").write_bytes((r.stdout or "").encode())
        (arm_dir / "cache-init.stderr").write_bytes((r.stderr or "").encode())
        if r.returncode != 0:
            raise RuntimeError(f"cache enum failed: {r.stderr[-300:]}")
        data = json.loads(r.stdout)
        (arm_dir / "cache-init.json").write_bytes(canonical_json_bytes(data))
        if data["entries"] != []:
            raise RuntimeError(f"{arm}: cache was not fresh: {data['entries']}")
    else:
        r = sh(PARTICIPANT_HOST,
               f"python3 {REMOTE_WORK}/issue200_r8f_cache_enum.py {arm} {cache_dir}")
        (arm_dir / "cache-precheck.stdout").write_bytes((r.stdout or "").encode())
        (arm_dir / "cache-precheck.stderr").write_bytes((r.stderr or "").encode())
        if r.returncode != 0:
            raise RuntimeError(f"cache precheck failed: {r.stderr[-300:]}")
        data = json.loads(r.stdout)
        (arm_dir / "cache-precheck.json").write_bytes(canonical_json_bytes(data))
        entries = data["entries"]
        if len(entries) != 1 or entries[0]["name"] != f"rpc/{TENSOR_FNV1A}" \
                or entries[0]["size"] != TENSOR_LENGTH or entries[0]["sha256"] != TENSOR_SHA256:
            raise RuntimeError(f"{arm}: reused cache precheck mismatch: {entries}")

    # 2. Per-arm participant-side range receipt (ALWAYS, from the participant).
    range_remote = f"{remote_arm_dir}/retained-range.bin"
    r = sh(PARTICIPANT_HOST,
           f"cd {REMOTE_WORK} && PYTHONPATH={REMOTE_WORK} python3 "
           f"{REMOTE_WORK}/issue200_r8f_range_receipt.py "
           f"--node-id {PARTICIPANT_HOST} --source-path {PARTICIPANT_MODEL} "
           f"--member Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf "
           f"--member-bytes {MEMBER3_BYTES} --member-sha256 {MEMBER3_SHA256} "
           f"--offset {TENSOR_ABS_OFFSET} --length {TENSOR_LENGTH} "
           f"--write-range {range_remote}", timeout=1800)
    (arm_dir / "range.stdout.json").write_bytes((r.stdout or "").encode())
    (arm_dir / "range.stderr").write_bytes((r.stderr or "").encode())
    if r.returncode != 0:
        raise RuntimeError(f"range receipt failed: {r.stderr[-500:]}")

    # 3. Staging (only for the fresh local arm) via the controlled helper.
    if stage:
        r2 = sh(PARTICIPANT_HOST,
                f"cd {REMOTE_WORK} && PYTHONPATH={REMOTE_WORK} python3 "
                f"{REMOTE_WORK}/issue200_r8f_stage_cache.py "
                f"--node-id {PARTICIPANT_HOST} --source-path {PARTICIPANT_MODEL} "
                f"--member Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf "
                f"--member-bytes {MEMBER3_BYTES} --member-sha256 {MEMBER3_SHA256} "
                f"--offset {TENSOR_ABS_OFFSET} --length {TENSOR_LENGTH} "
                f"--cache-dir {cache_dir}", timeout=600)
        (arm_dir / "staging.stdout").write_bytes((r2.stdout or "").encode())
        (arm_dir / "staging.stderr").write_bytes((r2.stderr or "").encode())
        if r2.returncode != 0:
            raise RuntimeError(f"staging failed: {r2.stderr[-500:]}")
        # post-staging enumeration (before any client contact)
        r3 = sh(PARTICIPANT_HOST,
                f"python3 {REMOTE_WORK}/issue200_r8f_cache_enum.py {arm} {cache_dir}")
        (arm_dir / "cache-after-staging.json").write_bytes(canonical_json_bytes(json.loads(r3.stdout)))
        (arm_dir / "cache-after-staging.stderr").write_bytes((r3.stderr or "").encode())
        if r3.returncode != 0:
            raise RuntimeError("post-staging cache enum failed")

    # 4. Start the participant server under file-strace (from exec).
    rpc_info = start_rpc_straced(cache_dir, arm, arm_dir)

    # 5. Launch the client UNDER strace FROM EXEC.
    ot = f"blk\\.24\\.attn_gate\\.weight=RPC0[{PARTICIPANT_ENDPOINT}]"
    client_argv = [LLAMA_SERVER_BIN, "-m", MODEL_MEMBER1, "--rpc", PARTICIPANT_ENDPOINT,
                   "-ot", ot, "--host", "127.0.0.1", "--port", str(CLIENT_PORT),
                   "-ngl", "0", "-c", "8192", "--no-warmup"]
    client_log = f"{remote_arm_dir}/client.log"
    capture_remote = f"{remote_arm_dir}/capture.strace"
    capture_argv = network_reduce.required_capture_command(client_argv, [TENSOR_LENGTH])
    started_at = time.time()
    quoted = " ".join(_shlex_mod.quote(item) for item in client_argv[1:])
    inner = (f"cd {remote_arm_dir} && nohup strace -f --always-show-pid -ttt -xx "
             f"-s {STRACE_LIMIT} -e trace=network,write,writev,execve "
             f"-o {capture_remote} {client_argv[0]} {quoted} > {client_log} 2>&1 < /dev/null"
             f" & echo $! > {remote_arm_dir}/client.strace.pid")
    launch = 'setsid bash -c ' + _shlex_quote(inner) + ' < /dev/null > /dev/null 2>&1; exit 0'
    sh(CLIENT_HOST, launch)
    import re as _re
    pid = 0
    for _ in range(40):
        r = sh(CLIENT_HOST, f"head -c 200 {capture_remote} 2>/dev/null || true")
        m = _re.match(r"\s*(\d+)", r.stdout or "")
        if m:
            pid = int(m.group(1))
            break
        time.sleep(0.5)
    if pid <= 0:
        raise RuntimeError(f"{arm}: client capture did not start")
    try:
        wall = wait_model_loaded(CLIENT_HOST, client_log)
    finally:
        sh(CLIENT_HOST, f"kill {pid} || true; sleep 2; kill -9 {pid} 2>/dev/null || true")

    # 6. Fetch every raw receipt.
    fetch(CLIENT_HOST, client_log, arm_dir / "client.log")
    fetch(CLIENT_HOST, capture_remote, arm_dir / "capture.strace")
    fetch(PARTICIPANT_HOST, range_remote, arm_dir / "retained-range.bin")
    fetch(PARTICIPANT_HOST, rpc_info["server_log"], arm_dir / "rpc-server.log")
    fetch(PARTICIPANT_HOST, rpc_info["strace_log"], arm_dir / "participant-reads.strace")
    bin_receipt = live_binary_receipt(CLIENT_HOST, LLAMA_SERVER_BIN, arm_dir, "client-binary.json")
    rpc_bin_receipt = live_binary_receipt(PARTICIPANT_HOST, RPC_BIN, arm_dir, "rpc-binary.json")
    sh(PARTICIPANT_HOST, "pkill -x ggml-rpc-server || true")
    time.sleep(1)

    result = {
        "arm": arm, "client_pid": pid, "wall_s": round(wall, 3),
        "capture_argv": capture_argv,
        "cache_dir": cache_dir, "rpc_endpoint": PARTICIPANT_ENDPOINT,
        "client_argv": client_argv,
        "rpc": {k: v for k, v in rpc_info.items() if k != "strace_log"},
        "client_binary": bin_receipt, "rpc_binary": rpc_bin_receipt,
        "started_at": started_at,
        "note": ("orchestrator-side convenience facts only; NON-AUTHORITATIVE — "
                 "argv/PID authority is each capture's own first execve record"),
    }
    if reuse_of is not None:
        result["reuses_cache_of"] = reuse_of
    summary[arm] = result
    (out / "run-summary.json").write_bytes(canonical_json_bytes(summary))
    return result


def main() -> int:
    out = OUT_ROOT
    if out.exists():
        import shutil
        shutil.rmtree(out)
    out.mkdir(parents=True)
    summary: dict = {}

    deploy_helpers()

    # 0. Participant full-release backing verification (all three members).
    r = sh(PARTICIPANT_HOST,
           f"cd {REMOTE_WORK} && PYTHONPATH={REMOTE_WORK} python3 {REMOTE_WORK}/issue200_r8f_backing_verify.py "
           f"--node-id {PARTICIPANT_HOST} --backing-dir {BACKING_DIR} "
           f"--authority {REMOTE_WORK}/docs/investigations/qwen38-flash-next-r8-d-v2/"
           f"evidence/split-identity/split-rehash.json", timeout=3600)
    (out / "backing-verify.stdout").write_bytes((r.stdout or "").encode())
    (out / "backing-verify.stderr").write_bytes((r.stderr or "").encode())
    if r.returncode != 0:
        raise RuntimeError(f"backing verification failed: {r.stderr[-500:]}")

    stop_client()
    cache_a = f"{REMOTE_WORK}/cold_remote-cache"
    sh(PARTICIPANT_HOST, f"rm -rf {cache_a} && mkdir -p {cache_a}/rpc")
    run_arm("cold_remote", cache_a, stage=False, reuse_of=None, out=out, summary=summary)
    stop_client()

    cache_b = f"{REMOTE_WORK}/local_verified-cache"
    sh(PARTICIPANT_HOST, f"rm -rf {cache_b} && mkdir -p {cache_b}/rpc")
    run_arm("local_verified", cache_b, stage=True, reuse_of=None, out=out, summary=summary)
    stop_client()
    stop_rpc()

    # TRUE reuse arm: fresh server + fresh client, arm B's cache, NO staging.
    run_arm("repeat_local_verified", cache_b, stage=False, reuse_of="local_verified",
            out=out, summary=summary)
    stop_client()
    stop_rpc()

    (out / "run-summary.json").write_bytes(canonical_json_bytes(summary))
    print(json.dumps({k: {"client_pid": v["client_pid"], "wall_s": v["wall_s"],
                          "cache_dir": v["cache_dir"]} for k, v in summary.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
