#!/usr/bin/env python3
"""Assemble the Issue #200 Phase-5 physical evidence document from the fleet
run's retained raw receipts (correction round 3).

Runs on the orchestration host inside the inferswarm repo root.  Reads the
fleet run at /tmp/issue200-p5c3-evidence and writes
docs/implementation/r8-f-local-backing-source-policy-200/evidence/physical-phase5.json
plus the raw receipt tree it references.

Correction round 3 discipline — the assembler is a PURE COLLECTER/DERIVER
(review item 16).  It establishes NOTHING acceptance-significant from
unretained Python dictionaries:

- It no longer reads the ephemeral ``run-summary.json`` at all.  Every
  acceptance-significant external input is a retained raw receipt under the
  fleet run root, copied byte-for-byte into the committed evidence tree and
  covered by MANIFEST.sha256: the raw captures (which carry the client's own
  execve argv and PID in their first record), the participant-side straces
  (which carry the RPC server's own execve argv, root PID, and cache-file
  opens/reads), the helper stdout/stderr receipts, the retained range bytes,
  the binary identity receipts, and the launch logs.
- The ONLY values it synthesizes are the document skeleton: frozen identity
  constants (identical across arms, checked against the accepted authority
  by the validator), arm labels, and cross-references between copied files.
  Process argv, PID lineage, environment, timestamps, success, cache
  freshness, source attribution, and helper success are all DERIVED by the
  validator (issue200_r8f_physical) from the retained raw bytes.
- The per-arm orchestrator-side launch facts (wall time, started_at) are
  retained as the orchestrator's own raw run-summary artifact
  (``run-summary.json``, byte-copied into the evidence tree and
  MANIFEST-covered) but are NON-AUTHORITATIVE: the closure test proves the
  terminal is re-derivable with this artifact withheld.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import issue200_r8f_network_reduce as network_reduce  # noqa: E402
import issue200_r8f_physical as physical  # noqa: E402
from issue74_methodology import canonical_json_bytes  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs/implementation/r8-f-local-backing-source-policy-200"
RUN = Path("/tmp/issue200-p5c3-evidence")

PARTICIPANT = "inferswarm04"
ENDPOINT = "10.0.0.204:50052"
MEMBER = "Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf"
TENSOR = "blk.24.attn_gate.weight"
OFFSET = 848968992
LENGTH = 10813440
PAYLOAD_SHA = "1c0284d8b85f4966e2dd1990271f3bc470667c11041d5d084be1ca511080f5f4"
FNV = "bbc9ae6a1038b6a6"

# The frozen client argv — proven from the raw capture's first-execve record
# by the reducer, byte-for-byte.  Declared here only to build the capture
# contract cross-check; if the retained capture's actual execve differs from
# this in ANY argument, the reducer rejects.
FROZEN_CLIENT_ARGV = [
    "/home/hermes/llama.cpp/build-v041/bin/llama-server",
    "-m", "/srv/models/qwen38-ud-iq1-s/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf",
    "--rpc", ENDPOINT,
    "-ot", "blk\\.24\\.attn_gate\\.weight=RPC0[10.0.0.204:50052]",
    "--host", "127.0.0.1", "--port", "8341",
    "-ngl", "0", "-c", "8192", "--no-warmup",
]

REQUIRED_STATE = ("sha256:" + hashlib.sha256(canonical_json_bytes(
    {"schema": "issue200.required-state/1", "release": "qwen38-ud-iq1-s",
     "logical_state_units": [f"{MEMBER}:{TENSOR}"],
     "release_total_bytes": 72546461344})).hexdigest())
PARTICIPANT_REQUIREMENTS = ("sha256:" + hashlib.sha256(canonical_json_bytes(
    {"schema": "issue200.participant-requirements/1",
     "participant": PARTICIPANT, "endpoint": ENDPOINT,
     "required_payload": {"member": MEMBER, "tensor": TENSOR,
                          "offset": OFFSET, "length": LENGTH, "sha256": PAYLOAD_SHA},
     "cache_eligible": LENGTH > 10 * 1024 * 1024})).hexdigest())
PLACEMENT = ("sha256:" + hashlib.sha256(canonical_json_bytes(
    {"schema": "issue200.placement/1", "client": "inferswarm01",
     "participants": [{PARTICIPANT: ENDPOINT}],
     "override_tensor": f"{TENSOR}=RPC0[{ENDPOINT}]",
     "other_tensors": "client-local (accepted R8-D placement unchanged)"})).hexdigest())
MATERIALIZATION = ("sha256:" + hashlib.sha256(canonical_json_bytes(
    {"schema": "issue200.materialization/1", "subject": "model-init-no-warmup",
     "request": "llama-server model load to 'listening on http://'",
     "ctx": 8192, "ngl": 0,
     "pinned_client": "de3a8a545e2f5995f80ff23f60776fedc30edca67f0e09f3bc47c845156e3411",
     "pinned_rpc_server": "a897f908add3305658e6b4f996880033d07ede0800fff71dbc46e90230acdfe9"})).hexdigest())


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def copy_in(src: Path, rel: str) -> dict:
    if not src.is_file():
        raise SystemExit(f"HARD FAILURE: required raw receipt missing: {src}")
    dest = AREA / "evidence" / "physical-phase5-raw" / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = src.read_bytes()
    dest.write_bytes(data)
    return {"path": str(dest.relative_to(AREA / "evidence")), "sha256": sha256(data)}


def write_receipt(rel: str, document: dict) -> dict:
    data = canonical_json_bytes(document)
    dest = AREA / "evidence" / "physical-phase5-raw" / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return {"path": str(dest.relative_to(AREA / "evidence")), "sha256": sha256(data)}


_HEX = __import__("re").compile(r"\\x([0-9a-fA-F]{2})")


def _derive_capture_head(raw: bytes):
    """Read the (pid, argv) identity from a capture's OWN first record."""
    import re as _re
    first = raw.split(b"\n", 1)[0].decode("utf-8", "strict")
    prefixed = network_reduce.PID_LINE.match(first)
    if prefixed is None:
        raise SystemExit("HARD FAILURE: capture's first record lacks a PID prefix")
    parsed = network_reduce.parse_execve(prefixed["record"])
    if parsed is None:
        raise SystemExit("HARD FAILURE: capture's first record is not a complete execve")
    pid = int(_re.match(r"(\d+)", first).group(1))
    return pid, parsed[0], parsed[1]


def _derive_cache_read(raw: bytes, cache_dir: str, fnv: str, server_pid: int, length: int):
    """Derive cache-file open/read accounting from the raw participant strace."""
    import re as _re
    def unesc(s):
        return _HEX.sub(lambda m: chr(int(m.group(1), 16)), s)
    expected_path = f"{cache_dir}/rpc/{fnv}"
    fd = None
    total = 0
    count = 0
    for line in raw.decode("utf-8", "strict").splitlines():
        m = _re.match(r"^(\d+) \S+ openat\((?:-?\d+|AT_FDCWD), \"((?:[^\"\\]|\\.)*)\",.*\)\s+=\s+(\d+)$", line)
        if m and unesc(m.group(2)) == expected_path:
            fd = int(m.group(3))
            continue
        r = _re.match(r"^(\d+) \S+ read\((\d+),.*\)\s+=\s+(\d+)$", line)
        if r and fd is not None and int(r.group(2)) == fd:
            total += int(r.group(3))
            count += 1
    return total, count


def main() -> int:
    evidence = AREA / "evidence"
    rawdir = evidence / "physical-phase5-raw"
    if rawdir.exists():
        subprocess.run(["rm", "-rf", str(rawdir)], check=True)
    rawdir.mkdir(parents=True)

    payload = {"offset": OFFSET, "length": LENGTH, "sha256": PAYLOAD_SHA,
               "fnv1a_cache_key": FNV, "participant": PARTICIPANT,
               "observation_id": f"set-{TENSOR}", "order": 1}

    # Retain the orchestrator's own raw run summary byte-for-byte (retention
    # only — NON-AUTHORITATIVE; the closure test proves the terminal is
    # re-derivable without it).
    run_summary_ref = copy_in(RUN / "run-summary.json", "run-summary.json")
    # Retain the orchestrator source itself, provenance-bound (review item 4).
    orchestrator_ref = copy_in(ROOT / "scripts/issue200_r8f_phase5_orchestrator.py",
                               "issue200_r8f_phase5_orchestrator.py")

    # Participant full-release backing verification (raw, from the run).
    backing_receipt = copy_in(RUN / "backing-verify.stdout", "backing-verify.stdout.json")
    backing_stderr = copy_in(RUN / "backing-verify.stderr", "backing-verify.stderr")
    backing_block = {
        "node_id": PARTICIPANT,
        "command": ["python3", "scripts/issue200_r8f_backing_verify.py",
                    "--node-id", PARTICIPANT],
        "receipt": backing_receipt,
        "stderr": backing_stderr,
    }

    arms_doc = {}
    for arm in ("cold_remote", "local_verified", "repeat_local_verified"):
        arm_raw = RUN / "raw" / arm
        # byte-complete network capture, reduced from raw bytes
        raw_capture = copy_in(arm_raw / "capture.strace", f"{arm}/capture.strace")
        captured = (arm_raw / "capture.strace").read_bytes()
        client_pid, exec_path, exec_argv = _derive_capture_head(captured)
        if exec_argv != FROZEN_CLIENT_ARGV:
            raise SystemExit(f"HARD FAILURE: {arm} capture head argv is not the frozen client argv")
        range_bin = copy_in(arm_raw / "retained-range.bin", f"{arm}/retained-range.bin")
        retained_bytes = (arm_raw / "retained-range.bin").read_bytes()
        if len(retained_bytes) != LENGTH or sha256(retained_bytes) != PAYLOAD_SHA:
            raise SystemExit(f"HARD FAILURE: {arm} retained-range.bin does not match the frozen payload identity")
        derived = network_reduce.reduce_capture(
            captured, client_pid=client_pid, server_endpoint=ENDPOINT,
            payloads=[{**payload, "bytes": retained_bytes}],
            client_argv=FROZEN_CLIENT_ARGV)
        reduction = write_receipt(f"{arm}/network.reduced.json", derived)
        capture_command = network_reduce.required_capture_command(FROZEN_CLIENT_ARGV, [LENGTH])
        network = {"arm": arm, "capture_tool": network_reduce.CAPTURE_TOOL,
                   "capture_command": capture_command,
                   "client_argv": FROZEN_CLIENT_ARGV, "client_pid": client_pid,
                   "server_endpoint": ENDPOINT,
                   "raw_capture": raw_capture, "reducer_sha256": network_reduce.reducer_sha256(),
                   "reduction_stdout": reduction}
        # range provenance (raw)
        range_stdout = copy_in(arm_raw / "range.stdout.json", f"{arm}/range.stdout.json")
        range_stderr = copy_in(arm_raw / "range.stderr", f"{arm}/range.stderr")
        accepted_range = {
            "member": MEMBER, "offset": OFFSET, "length": LENGTH, "sha256": PAYLOAD_SHA,
            "provenance_receipt": {
                "command": ["python3", "scripts/issue200_r8f_range_receipt.py",
                            "--node-id", PARTICIPANT],
                "exit_code": 0, "stdout": range_stdout, "stderr": range_stderr,
                "retained_range": range_bin}}
        # client launch summary (DERIVATIVE convenience only; argv authority
        # is the raw capture's own execve, binary identity the live receipts;
        # started_at is the capture's own first-record -ttt timestamp)
        client_bin = json.loads((arm_raw / "client-binary.json").read_text())
        client_bin_ref = copy_in(arm_raw / "client-binary.json", f"{arm}/client-binary.json")
        client_log = copy_in(arm_raw / "client.log", f"{arm}/client.log")
        client_exec_ts = network_reduce.reduce_capture(
            captured, client_pid=client_pid, server_endpoint=ENDPOINT,
            payloads=[{**payload, "bytes": retained_bytes}],
            client_argv=FROZEN_CLIENT_ARGV)["client_execve_ts"]
        client_launch = write_receipt(f"{arm}/client-launch.json", {
            "arm": arm, "schema": "inferswarm.issue200.client-launch-receipt/1",
            "argv": exec_argv, "pid": client_pid,
            "started_at": client_exec_ts,
            "exit_status": "terminated-after-listening",
            "binary_path": exec_path, "binary_sha256": client_bin["sha256"],
            "binary_live_receipt": {"path": client_bin_ref["path"], "sha256": client_bin_ref["sha256"]},
            "client_log": {"path": client_log["path"], "sha256": client_log["sha256"]},
            "note": "derivative summary; argv/PID authority is the raw capture's first execve record"})
        # rpc-server launch summary (DERIVATIVE convenience only; argv/PID/
        # cache-use authority is the raw participant strace's first execve
        # and its openat/read records)
        rpc_bin = json.loads((arm_raw / "rpc-binary.json").read_text())
        rpc_bin_ref = copy_in(arm_raw / "rpc-binary.json", f"{arm}/rpc-binary.json")
        rpc_log = copy_in(arm_raw / "rpc-server.log", f"{arm}/rpc-server.log")
        read_strace_raw = (arm_raw / "participant-reads.strace").read_bytes()
        rpc_pid, rpc_exec_path, rpc_exec_argv = _derive_capture_head(read_strace_raw)
        if rpc_exec_argv != [physical.FROZEN_RPC_EXEC[0], *physical.FROZEN_RPC_EXEC[1]]:
            raise SystemExit(f"HARD FAILURE: {arm} participant strace head argv is not the frozen RPC argv")
        _head = network_reduce.PID_LINE.match(
            read_strace_raw.split(b"\n", 1)[0].decode("utf-8", "strict"))
        if _head is None:
            raise SystemExit(f"HARD FAILURE: {arm} participant strace head is malformed")
        rpc_exec_ts = float(_head["ts"])
        cache_dir = f"/tmp/i200p5c3/{'local_verified' if arm == 'repeat_local_verified' else arm}-cache"
        rpc_launch = write_receipt(f"{arm}/rpc-launch.json", {
            "arm": arm, "schema": "inferswarm.issue200.rpc-server-launch-receipt/1",
            "argv": rpc_exec_argv[1:], "env": {"LLAMA_CACHE": cache_dir}, "pid": rpc_pid,
            "started_at": rpc_exec_ts,
            "binary_sha256": rpc_bin["sha256"],
            "binary_live_receipt": {"path": rpc_bin_ref["path"], "sha256": rpc_bin_ref["sha256"]},
            "server_log": {"path": rpc_log["path"], "sha256": rpc_log["sha256"]},
            "note": "derivative summary; executable/argv/PID/cache-use authority is the raw participant strace"})
        # participant cache-read strace (raw)
        read_strace = copy_in(arm_raw / "participant-reads.strace", f"{arm}/participant-reads.strace")
        read_bytes, read_syscalls = _derive_cache_read(read_strace_raw, cache_dir, FNV, rpc_pid, LENGTH)
        read_receipt = write_receipt(f"{arm}/participant-read.json", {
            "arm": arm, "schema": "inferswarm.issue200.participant-cache-read-receipt/1",
            "server_pid": rpc_pid, "cache_dir": cache_dir,
            "strace_capture": read_strace,
            "derived_read_bytes": read_bytes, "read_syscalls": read_syscalls,
            "note": "derived_read_bytes/read_syscalls re-derived by the validator from strace_capture"})
        arm_doc = {
            "source_policy": "PREFER_REMOTE_AUTHORIZED" if arm == "cold_remote" else "REQUIRE_LOCAL_VERIFIED",
            "source_attribution": "REMOTE_AUTHORIZED" if arm == "cold_remote" else "LOCAL_VERIFIED",
            "participants": [PARTICIPANT],
            "required_state_identity": REQUIRED_STATE,
            "participant_requirements_identity": PARTICIPANT_REQUIREMENTS,
            "placement_identity": PLACEMENT,
            "materialization_identity": MATERIALIZATION,
            "network_receipt": network,
            "client_launch_receipt": {"path": client_launch["path"], "sha256": client_launch["sha256"]},
            "rpc_server_receipt": {"path": rpc_launch["path"], "sha256": rpc_launch["sha256"]},
            "participant_read_receipt": {"path": read_receipt["path"], "sha256": read_receipt["sha256"]},
            "private_cache_dir": cache_dir,
            "set_tensor_payloads": [payload],
            "accepted_artifact_ranges": [
                {"accepted_artifact_range": accepted_range, "set_tensor_payload": payload}]}
        if arm == "cold_remote":
            enum_ref = copy_in(arm_raw / "cache-init.json", f"{arm}/cache-init.json")
            arm_doc["cache_initialization_receipt"] = enum_ref
        elif arm == "local_verified":
            enum_ref = copy_in(arm_raw / "cache-init.json", f"{arm}/cache-init.json")
            after_ref = copy_in(arm_raw / "cache-after-staging.json", f"{arm}/cache-after-staging.json")
            staging_stdout = copy_in(arm_raw / "staging.stdout", f"{arm}/staging.stdout")
            staging_stderr = copy_in(arm_raw / "staging.stderr", f"{arm}/staging.stderr")
            arm_doc["cache_initialization_receipt"] = enum_ref
            arm_doc["cache_after_staging_receipt"] = after_ref
            staging_stdout_doc = json.loads((arm_raw / "staging.stdout").read_text())
            arm_doc["cache_staging"] = [{
                "accepted_artifact_range": accepted_range,
                "set_tensor_payload": payload,
                "staged_cache": {
                    "path": staging_stdout_doc["staged_path"],
                    "raw_stdout": staging_stdout,
                    "raw_stderr": staging_stderr,
                    "range_bytes": {"path": range_bin["path"], "sha256": range_bin["sha256"]}}}]
        else:  # repeat_local_verified: true reuse, pre-check receipt only
            pre_ref = copy_in(arm_raw / "cache-precheck.json", f"{arm}/cache-precheck.json")
            arm_doc["cache_precheck_receipt"] = pre_ref
        arms_doc[arm] = arm_doc

    document = {
        "schema": physical.SCHEMA,
        "accepted_model_members": None,
        "accepted_total_bytes": None,
        "runtime": {
            "llama_cpp_commit": physical.PINNED_LLAMA_CPP_COMMIT,
            "source_files": __import__("issue200_r8f_rpc_cache_mechanism").UPSTREAM_SOURCE_IDENTITY,
            "binaries": [{"node_id": PARTICIPANT, "binary": "ggml-rpc-server",
                          "sha256": physical.accepted_rpc_binary_authority()[PARTICIPANT]},
                         {"node_id": "inferswarm01", "binary": "llama-server",
                          "sha256": physical.accepted_client_binary_authority()}]},
        "participants": [{
            "node_id": PARTICIPANT, "rpc_endpoint": ENDPOINT,
            "rpc_command": "ggml-rpc-server -H 0.0.0.0 -p 50052 -d CUDA0 -c (LLAMA_CACHE=<private arm cache>)"}],
        "frozen": {
            "required_state_identity": REQUIRED_STATE,
            "participant_requirements_identity": PARTICIPANT_REQUIREMENTS,
            "placement_identity": PLACEMENT,
            "materialization_identity": MATERIALIZATION},
        "frozen_client_argv": FROZEN_CLIENT_ARGV,
        "run_summary_retained": {"retention_only": True, **run_summary_ref},
        "orchestrator_source": {"retained_producer": True, **orchestrator_ref},
        "participant_backing_verification": backing_block,
        "arms": arms_doc,
    }
    authority = physical.accepted_model_authority()
    document["accepted_model_members"] = authority["members"]
    document["accepted_total_bytes"] = authority["total_bytes"]

    target = evidence / "physical-phase5.json"
    target.write_bytes(canonical_json_bytes(document))
    validation = physical.validate_physical_evidence(document, evidence_root=evidence)
    print(json.dumps({k: validation[k] for k in ("valid", "reason") if k in validation}, indent=1))
    if not validation.get("valid"):
        return 1
    derived = validation["derived"]
    print(json.dumps({arm: {k: derived["network"][arm][k] for k in
                            ("immutable_payload", "rpc_control", "total")}
                      for arm in derived["network"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
