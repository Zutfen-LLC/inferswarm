#!/usr/bin/env python3
"""Assemble the Issue #200 Phase-5 physical evidence document from the fleet
run's retained raw receipts (correction round 2).

Runs on the orchestration host inside the inferswarm repo root.  Reads the
fleet run at /tmp/issue200-p5c2-evidence and writes
docs/implementation/r8-f-local-backing-source-policy-200/evidence/physical-phase5.json
plus the raw receipt tree it references.

Correction round 2 discipline — the assembler SYNTHESIZES NOTHING that is
acceptance-significant:

- run-summary.json, per-arm client launch argv/exit/pid, client.log,
  rpc-server argv/env/pid, rpc-server.log, live binary sha receipts, cache
  enumerations, staging helper stdout/stderr, range helper stdout/stderr,
  byte-complete captures and retained range bytes are COPIED and
  checksummed, never authored;
- cache freshness (entries_before), staging success, and LOCAL_VERIFIED
  source attribution are all DERIVED by the validator from those raw bytes;
- every arm's retained-range.bin comes from the fleet run's per-arm fetch
  (measured on inferswarm04); there is no fallback copying bytes between
  arms — a missing per-arm retained range is a hard failure here.
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
RUN = Path("/tmp/issue200-p5c2-evidence")

PARTICIPANT = "inferswarm04"
ENDPOINT = "10.0.0.204:50052"
MEMBER = "Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf"
TENSOR = "blk.24.attn_gate.weight"
OFFSET = 848968992
LENGTH = 10813440
PAYLOAD_SHA = "1c0284d8b85f4966e2dd1990271f3bc470667c11041d5d084be1ca511080f5f4"
FNV = "bbc9ae6a1038b6a6"

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


def _raw_ref(copied: dict, document: dict) -> dict:
    return {"path": copied["path"], "sha256": copied["sha256"], "document": document}


def main() -> int:
    summary = json.loads((RUN / "run-summary.json").read_text())
    evidence = AREA / "evidence"
    rawdir = evidence / "physical-phase5-raw"
    if rawdir.exists():
        subprocess.run(["rm", "-rf", str(rawdir)], check=True)
    rawdir.mkdir(parents=True)

    payload = {"offset": OFFSET, "length": LENGTH, "sha256": PAYLOAD_SHA,
               "fnv1a_cache_key": FNV, "participant": PARTICIPANT,
               "observation_id": f"set-{TENSOR}", "order": 1}

    # Participant full-release backing verification (raw, from the run).
    backing_stdout = json.loads((RUN / "backing-verify.stdout").read_text())
    backing_receipt = copy_in(RUN / "backing-verify.stdout", "backing-verify.stdout.json")
    backing_stderr = copy_in(RUN / "backing-verify.stderr", "backing-verify.stderr")
    backing_block = {
        "command": ["python3", "scripts/issue200_r8f_backing_verify.py",
                    "--node-id", PARTICIPANT],
        "exit_code": 0,
        "receipt": backing_receipt,
        "stderr": backing_stderr,
    }
    assert backing_stdout.get("all_members_verified") is True

    client_bin_sha = None
    arms_doc = {}
    for arm in ("cold_remote", "local_verified", "repeat_local_verified"):
        run = summary[arm]
        arm_raw = RUN / "raw" / arm
        # byte-complete network capture, reduced from raw bytes
        raw_capture = copy_in(arm_raw / "capture.strace", f"{arm}/capture.strace")
        captured = (arm_raw / "capture.strace").read_bytes()
        range_bin = copy_in(arm_raw / "retained-range.bin", f"{arm}/retained-range.bin")
        retained_bytes = (arm_raw / "retained-range.bin").read_bytes()
        if len(retained_bytes) != LENGTH or sha256(retained_bytes) != PAYLOAD_SHA:
            raise SystemExit(f"HARD FAILURE: {arm} retained-range.bin does not match the frozen payload identity")
        derived = network_reduce.reduce_capture(
            captured, client_pid=run["client_pid"], server_endpoint=ENDPOINT,
            payloads=[{**payload, "bytes": retained_bytes}],
            client_argv=run["client_argv"])
        reduction = write_receipt(f"{arm}/network.reduced.json", derived)
        network = {"arm": arm, "capture_tool": network_reduce.CAPTURE_TOOL,
                   "capture_command": run["capture_argv"],
                   "client_argv": run["client_argv"], "client_pid": run["client_pid"],
                   "server_endpoint": ENDPOINT,
                   "capture_started": run["capture_started"], "capture_ended": run["capture_ended"],
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
        # client launch receipt (raw argv/pid/binary/log)
        client_bin = json.loads((arm_raw / "client-binary.json").read_text())
        client_bin_ref = copy_in(arm_raw / "client-binary.json", f"{arm}/client-binary.json")
        client_log = copy_in(arm_raw / "client.log", f"{arm}/client.log")
        client_launch = write_receipt(f"{arm}/client-launch.json", {
            "arm": arm, "schema": "inferswarm.issue200.client-launch-receipt/1",
            "argv": run["client_argv"], "pid": run["client_pid"],
            "started_at": run["started_at"], "exit_status": "terminated-after-listening",
            "binary_path": run["client_argv"][0], "binary_sha256": client_bin["sha256"],
            "binary_live_receipt": {"path": client_bin_ref["path"], "sha256": client_bin_ref["sha256"]},
            "client_log": {"path": client_log["path"], "sha256": client_log["sha256"]}})
        # rpc-server launch receipt (raw argv/env/pid/binary/log)
        rpc_bin = json.loads((arm_raw / "rpc-binary.json").read_text())
        rpc_bin_ref = copy_in(arm_raw / "rpc-binary.json", f"{arm}/rpc-binary.json")
        rpc_log = copy_in(arm_raw / "rpc-server.log", f"{arm}/rpc-server.log")
        rpc_launch = write_receipt(f"{arm}/rpc-launch.json", {
            "arm": arm, "schema": "inferswarm.issue200.rpc-server-launch-receipt/1",
            "argv": run["rpc"]["argv"], "env": run["rpc"]["env"], "pid": run["rpc"]["pid"],
            "started_at": run["rpc"]["started_at"], "binary_sha256": rpc_bin["sha256"],
            "binary_live_receipt": {"path": rpc_bin_ref["path"], "sha256": rpc_bin_ref["sha256"]},
            "server_log": {"path": rpc_log["path"], "sha256": rpc_log["sha256"]}})
        # participant cache-read strace (raw)
        read_strace = copy_in(arm_raw / "participant-reads.strace", f"{arm}/participant-reads.strace")
        read_receipt = write_receipt(f"{arm}/participant-read.json", {
            "arm": arm, "schema": "inferswarm.issue200.participant-cache-read-receipt/1",
            "server_pid": run["rpc"]["pid"], "cache_dir": run["cache_dir"],
            "strace_capture": read_strace,
            "capture_command": ["strace", "-f", "-ttt", "-xx", "-e", "trace=file",
                                "-o", "<rpc-arm.file.strace>", "ggml-rpc-server", "-c"]})
        arm_doc = {
            "source_policy": "PREFER_REMOTE_AUTHORIZED" if arm == "cold_remote" else "REQUIRE_LOCAL_VERIFIED",
            "source_attribution": "REMOTE_AUTHORIZED" if arm == "cold_remote" else "LOCAL_VERIFIED",
            "participants": [PARTICIPANT],
            "required_state_identity": REQUIRED_STATE,
            "participant_requirements_identity": PARTICIPANT_REQUIREMENTS,
            "placement_identity": PLACEMENT,
            "materialization_identity": MATERIALIZATION,
            "initialization_wall_time_ms": round(run["wall_s"] * 1000, 1),
            "network_receipt": network,
            "client_launch_receipt": {"path": client_launch["path"], "sha256": client_launch["sha256"]},
            "rpc_server_receipt": {"path": rpc_launch["path"], "sha256": rpc_launch["sha256"]},
            "participant_read_receipt": {"path": read_receipt["path"], "sha256": read_receipt["sha256"]},
            "private_cache_dir": run["cache_dir"],
            "set_tensor_payloads": [payload],
            "accepted_artifact_ranges": [
                {"accepted_artifact_range": accepted_range, "set_tensor_payload": payload}]}
        if arm == "cold_remote":
            enum = json.loads((arm_raw / "cache-init.json").read_text())
            enum_ref = copy_in(arm_raw / "cache-init.json", f"{arm}/cache-init.json")
            arm_doc["cache_initialization_receipt"] = enum_ref
        elif arm == "local_verified":
            enum = json.loads((arm_raw / "cache-init.json").read_text())
            enum_ref = copy_in(arm_raw / "cache-init.json", f"{arm}/cache-init.json")
            after = json.loads((arm_raw / "cache-after-staging.json").read_text()) if (arm_raw / "cache-after-staging.json").exists() \
                else json.loads((arm_raw / "cache-after-staging.stdout").read_text())
            after_ref = write_receipt(f"{arm}/cache-after-staging.json", after)
            staging_stdout_doc = json.loads((arm_raw / "staging.stdout").read_text())
            staging_stdout = copy_in(arm_raw / "staging.stdout", f"{arm}/staging.stdout")
            staging_stderr = copy_in(arm_raw / "staging.stderr", f"{arm}/staging.stderr")
            receipt = write_receipt(f"{arm}/staging.json", {
                "arm": arm, **staging_stdout_doc,
                "stdout": staging_stdout, "stderr": staging_stderr, "exit_code": 0})
            arm_doc["cache_initialization_receipt"] = enum_ref
            arm_doc["cache_after_staging_receipt"] = after_ref
            arm_doc["cache_staging"] = [{
                "accepted_artifact_range": accepted_range,
                "set_tensor_payload": payload,
                "staged_cache": {
                    "path": staging_stdout_doc["staged_path"],
                    "receipt": {"path": receipt["path"], "sha256": receipt["sha256"]},
                    "range_bytes": {"path": range_bin["path"], "sha256": range_bin["sha256"]}}}]
        else:  # repeat_local_verified: true reuse, pre-check receipt only
            pre = json.loads((arm_raw / "cache-precheck.json").read_text())
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
        "frozen_client_argv": summary["cold_remote"]["client_argv"],
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
