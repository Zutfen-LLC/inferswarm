#!/usr/bin/env python3
"""Bounded non-Qwen RPC local-cache experiment against the pinned llama.cpp
commit b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 ggml-rpc-server / RPC client
backend, exercised through an unmodified external driver
(r8f_rpc_cache_probe/driver.cpp) that calls only the pinned public backend
API (ggml_backend_rpc_buffer_type, ggml_backend_alloc_ctx_tensors_from_buft,
ggml_backend_tensor_set, ggml_backend_tensor_get). Network bytes are measured
independently of any llama.cpp instrumentation via strace on the client
process's own send()/recv() syscalls, bucketed into the SET phase and the
GET (verification-only) phase using wall-clock markers the driver prints.

Phases: see module docstring in the previous revision; summarized in
docs/implementation/r8-f-local-backing-source-policy-200/README.md.

None of this modifies llama.cpp. All ports/dirs are process-local and
loopback-only.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import hashlib
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_ROOT = "/tmp/claude-0/-home-user-inferswarm/814f5c21-e0bf-55e5-aefa-383a311de85c/scratchpad/llamacpp-src"
RPC_SERVER_BIN = os.path.join(SRC_ROOT, "build", "bin", "ggml-rpc-server")
DRIVER_BIN = os.path.join(HERE, "driver")
FIXTURE_PATH = os.path.join(HERE, "fixture.bin")
WORK = os.path.join(HERE, "work")
PINNED_COMMIT = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"

sys.path.insert(0, HERE)
from fnv1a_reference import hash_hex  # noqa: E402

SEND_RE = re.compile(r"^(\d+)\s+(\d\d:\d\d:\d\d\.\d+)\s+send(?:to)?\([^)]*\)\s*=\s*(\d+)")
RECV_RE = re.compile(r"^(\d+)\s+(\d\d:\d\d:\d\d\.\d+)\s+recv(?:from)?\([^)]*\)\s*=\s*(-?\d+)")
MARKER_RE = re.compile(r"\[driver\] marker=(\w+) epoch=(\d+)\.(\d+)")

TODAY = datetime.date.today()
EPOCH_DATE = datetime.date(1970, 1, 1)


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=isinstance(cmd, str), check=False,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, **kw)


def wait_port(port, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def start_server(port, cache_root, log_path):
    os.makedirs(cache_root, exist_ok=True)
    env = dict(os.environ)
    env["LLAMA_CACHE"] = cache_root
    logf = open(log_path, "w")
    proc = subprocess.Popen(
        [RPC_SERVER_BIN, "-H", "127.0.0.1", "-p", str(port), "-c", "-d", "CPU"],
        env=env, stdout=logf, stderr=subprocess.STDOUT)
    ok = wait_port(port)
    if not ok:
        proc.kill()
        proc.wait()
        logf.close()
        raise RuntimeError(f"server did not open port {port}; see {log_path}")
    return proc, logf


def stop_server(proc, logf):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    logf.close()


def strace_ts_to_epoch(ts: str) -> float:
    h, m, s = ts.split(":")
    days_since_epoch = (TODAY - EPOCH_DATE).days
    return (days_since_epoch * 86400) + int(h) * 3600 + int(m) * 60 + float(s)


def run_driver_straced(endpoint, fixture_path, mode, tag):
    strace_log = os.path.join(WORK, f"strace-{tag}.log")
    cmd = ["strace", "-f", "-tt", "-e", "trace=network", "-s", "0",
           "-o", strace_log, "--", DRIVER_BIN, endpoint, fixture_path, mode]
    r = sh(cmd)

    markers = {}
    for line in r.stdout.splitlines():
        m = MARKER_RE.search(line)
        if m:
            name, sec, usec = m.groups()
            markers[name] = float(f"{sec}.{usec}")

    events = []  # (epoch, direction, nbytes)
    if os.path.exists(strace_log):
        with open(strace_log, errors="replace") as fh:
            for line in fh:
                line = line.strip()
                m = SEND_RE.match(line)
                if m:
                    events.append((strace_ts_to_epoch(m.group(2)), "send", int(m.group(3))))
                    continue
                m = RECV_RE.match(line)
                if m and int(m.group(3)) > 0:
                    events.append((strace_ts_to_epoch(m.group(2)), "recv", int(m.group(3))))

    def bucket(lo, hi):
        s = r_ = 0
        for ts, direction, n in events:
            if (lo is None or ts >= lo) and (hi is None or ts < hi):
                if direction == "send":
                    s += n
                else:
                    r_ += n
        return {"sent": s, "recv": r_}

    total = bucket(None, None)
    set_bytes = bucket(markers.get("ALLOC_DONE"), markers.get("SET_DONE"))
    get_bytes = bucket(markers.get("SET_DONE"), markers.get("GET_DONE")) if "GET_DONE" in markers else None
    pre_alloc_bytes = bucket(None, markers.get("ALLOC_DONE"))

    return {
        "tag": tag, "mode": mode, "exit_code": r.returncode,
        "driver_stderr": r.stdout.strip(),
        "markers": markers,
        "bytes_total_on_wire": total,
        "bytes_pre_alloc_handshake_and_buffer_type_query": pre_alloc_bytes,
        "bytes_set_phase_alloc_to_set_done": set_bytes,
        "bytes_get_phase_verification_only": get_bytes,
        "strace_log": os.path.relpath(strace_log, HERE),
    }


def cache_file_path(cache_root, hexhash):
    return os.path.join(cache_root, "rpc", hexhash)


def list_cache(cache_root):
    d = os.path.join(cache_root, "rpc")
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        out.append({"name": name, "size_bytes": os.path.getsize(p)})
    return out


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    if os.path.exists(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)

    if not os.path.exists(FIXTURE_PATH):
        raise RuntimeError("fixture.bin missing; run gen_fixture.py first")
    fixture_bytes = open(FIXTURE_PATH, "rb").read()
    fixture_sha256 = hashlib.sha256(fixture_bytes).hexdigest()
    predicted_hex = hash_hex(fixture_bytes)

    results = {
        "schema": "inferswarm.issue200.rpc-cache-experiment/1",
        "pinned_llama_cpp_commit": PINNED_COMMIT,
        "method_note": (
            "Network bytes are measured by strace on the client driver's own "
            "send()/recv() syscalls (trace=network), independent of any "
            "llama.cpp instrumentation. bytes_set_phase_alloc_to_set_done is "
            "the metric that matters for the cache question: it isolates the "
            "SET_TENSOR_HASH/SET_TENSOR exchange from the unconditional "
            "verification-only GET_TENSOR the driver performs afterwards "
            "(GET_TENSOR has no cache shortcut in this pinned build and "
            "always transfers the full tensor back, in every phase)."
        ),
        "fixture": {
            "size_bytes": len(fixture_bytes),
            "sha256": fixture_sha256,
            "predicted_fnv1a_cache_key": predicted_hex,
            "note": ("SHA-256 is the InferSwarm-style provenance identity used "
                     "in this experiment; the FNV-1a value is upstream's own "
                     "internal cache-dedup key and is recorded only to predict "
                     "the cache filename, never treated as provenance authority."),
        },
        "phases": {},
    }

    def run_phase(name, description, port, cache_root, reuse_cache_root=None, prestage=None, extra=None):
        cr = reuse_cache_root or cache_root
        os.makedirs(os.path.join(cr, "rpc"), exist_ok=True)
        if prestage is not None:
            path = cache_file_path(cr, predicted_hex)
            with open(path, "wb") as fh:
                fh.write(prestage)
        log_path = os.path.join(WORK, f"server-{name}.log")
        proc, logf = start_server(port, cr, log_path)
        try:
            r = run_driver_straced(f"127.0.0.1:{port}", FIXTURE_PATH, "setget", name)
        finally:
            stop_server(proc, logf)
        entry = {
            "description": description,
            "cache_dir_listing_after": list_cache(cr),
            "server_log": os.path.relpath(log_path, HERE),
            "result": r,
        }
        if prestage is not None:
            p = cache_file_path(cr, predicted_hex)
            entry["prestaged_file"] = {"path": os.path.relpath(p, HERE), "sha256": sha256_file(p),
                                        "size_bytes": os.path.getsize(p)}
        if extra:
            entry.update(extra)
        results["phases"][name] = entry
        return cr

    cache_a = os.path.join(WORK, "cache-a")
    run_phase("A_cold", "First-ever SET_TENSOR for this content on a fresh empty cache dir.",
               58301, cache_a)
    actual_hex_a = results["phases"]["A_cold"]["cache_dir_listing_after"]
    results["phases"]["A_cold"]["predicted_vs_actual_cache_filename_match"] = (
        len(actual_hex_a) == 1 and actual_hex_a[0]["name"] == predicted_hex)

    run_phase("B_warm_restart",
               "Fresh server process (new PID, fresh connections) restarted against the "
               "SAME on-disk cache dir populated in phase A -- proves durability across "
               "process restart, not merely an in-memory/same-connection effect.",
               58302, None, reuse_cache_root=cache_a)

    cache_c = os.path.join(WORK, "cache-c")
    run_phase("C_prestaged",
               "Brand-new empty cache dir + brand-new server that has NEVER seen this "
               "content; the exact fixture bytes are written to the predicted cache path "
               "BEFORE the driver ever runs (simulating a bounded external adapter "
               "materializing InferSwarm-verified local backing into the RPC cache). "
               "First-ever contact with this server is the measured event.",
               58303, cache_c, prestage=fixture_bytes)

    wrong_bytes = (hashlib.sha256(b"wrong-content-collision-substitution-probe").digest()
                   * (len(fixture_bytes) // 32 + 1))[:len(fixture_bytes)]
    cache_d = os.path.join(WORK, "cache-d")
    run_phase("D_wrong_content",
               "Adversarial: file at the predicted cache path holds DIFFERENT bytes than "
               "the fixture (collision/corruption simulation). Demonstrates whether the "
               "pinned server detects this or blindly trusts the filename.",
               58304, cache_d, prestage=wrong_bytes,
               extra={"wrong_content_sha256": hashlib.sha256(wrong_bytes).hexdigest()})
    d = results["phases"]["D_wrong_content"]["result"]
    results["phases"]["D_wrong_content"]["cache_blindly_trusted_wrong_content"] = (d["exit_code"] == 2)

    truncated_bytes = fixture_bytes[: len(fixture_bytes) // 2]
    cache_e = os.path.join(WORK, "cache-e")
    run_phase("E_truncated",
              "Adversarial: file at the predicted cache path is a truncated (half-length) "
              "prefix of the fixture. Demonstrates whether the pinned server rejects a "
              "short cache entry or silently accepts it, leaving the tensor tail unwritten.",
               58305, cache_e, prestage=truncated_bytes,
               extra={"truncated_size_bytes": len(truncated_bytes)})
    e = results["phases"]["E_truncated"]["result"]
    results["phases"]["E_truncated"]["cache_silently_accepted_short_entry"] = (e["exit_code"] == 2)

    out_path = os.path.join(HERE, "rpc-cache-experiment.json")
    with open(out_path, "w") as fh:
        json.dump(results, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(results, indent=2, sort_keys=True))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
