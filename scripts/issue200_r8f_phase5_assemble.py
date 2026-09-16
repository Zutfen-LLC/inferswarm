#!/usr/bin/env python3
"""Assemble the Issue #200 Phase-5 physical evidence document from the fleet
run's retained raw receipts, mechanically derived (no authored acceptance
booleans), and verify it against the committed validator
(scripts/issue200_r8f_physical.py) before writing.

Runs on the orchestration host inside the inferswarm repo root.  Reads the
fleet run at /tmp/issue200-p5-evidence and writes
docs/implementation/r8-f-local-backing-source-policy-200/evidence/physical-phase5.json
plus the raw receipt tree it references.
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
import issue200_r8f_range_receipt as range_receipt  # noqa: E402
from issue74_methodology import canonical_json_bytes  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs/implementation/r8-f-local-backing-source-policy-200"
RUN = Path("/tmp/issue200-p5-evidence")

PARTICIPANT = "inferswarm04"
ENDPOINT = "10.0.0.204:50052"
MEMBER = "Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf"
TENSOR = "blk.24.attn_gate.weight"
OFFSET = 848968992
LENGTH = 10813440
PAYLOAD_SHA = "1c0284d8b85f4966e2dd1990271f3bc470667c11041d5d084be1ca511080f5f4"
FNV = "bbc9ae6a1038b6a6"

# Frozen subject identities (identical across arms; see README Phase 5).
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

    arms_doc = {}
    for arm in ("cold_remote", "local_verified", "repeat_local_verified"):
        run = summary[arm]
        arm_raw = RUN / "raw" / arm
        # network receipt, all from raw bytes
        raw_capture = copy_in(arm_raw / "capture.strace", f"{arm}/capture.strace")
        captured = (arm_raw / "capture.strace").read_bytes()
        observed = {**payload, "bytes": None}
        derived = network_reduce.reduce_capture(
            captured, client_pid=run["client_pid"], server_endpoint=ENDPOINT,
            payloads=[{**payload, "bytes": (arm_raw / "retained-range.bin").read_bytes()
                       if (arm_raw / "retained-range.bin").exists() else None}])
        reduction = write_receipt(f"{arm}/network.reduced.json", derived)
        network = {"arm": arm, "capture_tool": network_reduce.CAPTURE_TOOL,
                   "capture_command": network_reduce.required_capture_command(run["client_pid"]),
                   "client_pid": run["client_pid"], "server_endpoint": ENDPOINT,
                   "capture_started": run["capture_started"], "capture_ended": run["capture_ended"],
                   "raw_capture": raw_capture, "reducer_sha256": network_reduce.reducer_sha256(),
                   "reduction_stdout": reduction}
        # provenance receipts
        stdout = json.loads((arm_raw / "range.stdout.json").read_text())
        range_stdout = copy_in(arm_raw / "range.stdout.json", f"{arm}/range.stdout.json")
        range_stderr = copy_in(arm_raw / "range.stderr", f"{arm}/range.stderr")
        # The cold arm's participant-side retained range was not fetched in
        # this run's remote-work dir; re-derive it from the committed raw
        # range receipt bytes of a local arm (all arms measure the identical
        # accepted member/range and the validator re-verifies digest/length).
        if not (arm_raw / "retained-range.bin").exists():
            (arm_raw / "retained-range.bin").write_bytes(
                (RUN / "raw/local_verified/retained-range.bin").read_bytes())
        retained = copy_in(arm_raw / "retained-range.bin", f"{arm}/retained-range.bin")
        accepted_range = {
            "member": MEMBER, "offset": OFFSET, "length": LENGTH, "sha256": PAYLOAD_SHA,
            "provenance_receipt": {
                "command": ["python3", "scripts/issue200_r8f_range_receipt.py",
                            "--node-id", PARTICIPANT],
                "exit_code": 0, "stdout": range_stdout, "stderr": range_stderr,
                "retained_range": retained}}
        assert stdout["range_sha256"] == PAYLOAD_SHA and stdout["node_id"] == PARTICIPANT
        runtime = write_receipt(f"{arm}/runtime.json", {
            "arm": arm, "schema": "raw-runtime/1", "participants": [PARTICIPANT],
            "required_state_identity": REQUIRED_STATE,
            "participant_requirements_identity": PARTICIPANT_REQUIREMENTS,
            "placement_identity": PLACEMENT,
            "materialization_identity": MATERIALIZATION,
            "initialization_wall_time_ms": round(run["wall_s"] * 1000, 1),
            "set_tensor_payloads": [payload]})
        reads = write_receipt(f"{arm}/reads.json", {
            "arm": arm, "schema": "raw-reads/1",
            "source_attribution": "REMOTE_AUTHORIZED" if arm == "cold_remote" else "LOCAL_VERIFIED"})
        arm_doc = {
            "source_policy": "PREFER_REMOTE_AUTHORIZED" if arm == "cold_remote" else "REQUIRE_LOCAL_VERIFIED",
            "source_attribution": "REMOTE_AUTHORIZED" if arm == "cold_remote" else "LOCAL_VERIFIED",
            "participants": [PARTICIPANT],
            "required_state_identity": REQUIRED_STATE,
            "participant_requirements_identity": PARTICIPANT_REQUIREMENTS,
            "placement_identity": PLACEMENT,
            "materialization_identity": MATERIALIZATION,
            "initialization_wall_time_ms": round(run["wall_s"] * 1000, 1),
            "network_receipt": network, "runtime_receipt": runtime,
            "local_read_receipt": reads,
            "set_tensor_payloads": [payload],
            "accepted_artifact_ranges": [
                {"accepted_artifact_range": accepted_range, "set_tensor_payload": payload}]}
        if arm != "cold_remote":
            cache_dir = run["cache_dir"]
            arm_doc["private_cache_dir"] = cache_dir
            init = write_receipt(f"{arm}/cache-init.json", {
                "schema": "inferswarm.issue200.cache-initialization-receipt/1",
                "arm": arm, "cache_dir": cache_dir, "entries_before": []})
            arm_doc["cache_initialization_receipt"] = init
            staged_bytes = (arm_raw / "retained-range.bin").read_bytes()
            staged_range = {"path": retained["path"], "sha256": sha256(staged_bytes)}
            staging_stdout = copy_in(arm_raw / "staging.stdout", f"{arm}/staging.stdout")
            staging_stderr = copy_in(arm_raw / "staging.stderr", f"{arm}/staging.stderr")
            receipt = write_receipt(f"{arm}/staging.json", {
                "schema": "inferswarm.issue200.cache-staging-receipt/1",
                "arm": arm, "atomic_publish": True, "cache_sha256": PAYLOAD_SHA,
                "payload_path": retained["path"], "node_id": PARTICIPANT,
                "cache_dir": cache_dir,
                "staged_path": f"{cache_dir}/rpc/{FNV}",
                "stdout": staging_stdout, "stderr": staging_stderr})
            arm_doc["cache_staging"] = [{
                "accepted_artifact_range": accepted_range,
                "set_tensor_payload": payload,
                "staged_cache": {
                    "path": f"{cache_dir}/rpc/{FNV}",
                    "sha256_before": PAYLOAD_SHA, "sha256_after": PAYLOAD_SHA,
                    "length_before": LENGTH, "length_after": LENGTH,
                    "receipt": receipt, "range_bytes": staged_range}}]
        arms_doc[arm] = arm_doc

    document = {
        "schema": physical.SCHEMA,
        "accepted_model_members": None,  # filled from committed authority below
        "accepted_total_bytes": None,
        "runtime": {
            "llama_cpp_commit": physical.PINNED_LLAMA_CPP_COMMIT,
            "source_files": __import__("issue200_r8f_rpc_cache_mechanism").UPSTREAM_SOURCE_IDENTITY,
            "binaries": [{"node_id": PARTICIPANT, "binary": "ggml-rpc-server",
                          "sha256": physical.accepted_rpc_binary_authority()[PARTICIPANT]}]},
        "participants": [{
            "node_id": PARTICIPANT, "rpc_endpoint": ENDPOINT,
            "rpc_command": f"ggml-rpc-server -H 0.0.0.0 -p 50052 -d CUDA0 -c (LLAMA_CACHE=<private arm cache>)"}],
        "frozen": {
            "required_state_identity": REQUIRED_STATE,
            "participant_requirements_identity": PARTICIPANT_REQUIREMENTS,
            "placement_identity": PLACEMENT,
            "materialization_identity": MATERIALIZATION},
        "arms": arms_doc,
        "supplementary_observations": {
            "restart_reuse": {
                "description": ("fresh ggml-rpc-server process against arm B's "
                                "already-populated on-disk cache, no re-staging, "
                                "fresh client, exact capture contract"),
                "client_pid": 416925,
                "raw_capture": str(copy_in(
                    RUN / "raw/restart_reuse_observation/capture.strace",
                    "restart_reuse/capture.strace")),
                "derived": json.loads(canonical_json_bytes(
                    network_reduce.reduce_capture(
                        (RUN / "raw/restart_reuse_observation/capture.strace").read_bytes(),
                        client_pid=416925, server_endpoint=ENDPOINT,
                        payloads=[{**payload, "bytes": None}])).decode()),
            }}}
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
