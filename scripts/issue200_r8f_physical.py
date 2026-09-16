#!/usr/bin/env python3
"""Mechanical validator for Issue #200 Phase-5 physical receipts (schema /4).

Correction round 2.  This remains a verifier, not a fleet runner.  Changes
from /3, each closing a reviewed defect:

- BYTE-COMPLETE cold network proof: the capture contract is the frozen
  from-exec argv with a string limit mechanically derived from the frozen
  payload size; the reducer demands the exact payload bytes as the suffix of
  one complete target-bound record.  Abbreviated (``""...``/ellipsis)
  records are rejections, never identity evidence, and a payload-length
  window is never an identity proof.
- Participant full-release backing: the participant's complete three-member
  release is proven by a raw participant-side verification receipt whose
  member identities must EQUAL the accepted R8-D split-rehash authority and
  whose accepted total is 72,546,461,344 bytes.  A missing member, a wrong
  size, or a tampered receipt is a hard failure.
- Cache freshness is DERIVED: ``entries_before`` comes from a retained
  participant-side directory enumeration performed before staging/client
  contact (raw ``ls``-class receipt with per-entry size and SHA-256), never
  from an assembler constant.
- Staging is DERIVED: a controlled committed helper's canonical measured
  receipt (temp-file write inside the target directory, exact SHA-256/size
  verification before and after the atomic rename, re-read verification of
  the final path) is consumed and independently re-verified against the
  retained range bytes and the FNV-1a filename recomputed from those bytes.
- Runtime/materialization success is DERIVED from the retained client
  launch receipt and client log: exact frozen argv/binary, the recorded
  process identity, and the ``listening on http://`` readiness line in the
  retained log for the arm's exact host:port.
- LOCAL_VERIFIED source attribution is DERIVED from a participant-side
  from-exec strace (file class) of the arm's own ggml-rpc-server: a
  successful ``openat`` of the exact ``<private-cache>/rpc/<FNV>`` file by
  that server PID followed by ``read`` syscalls accounting the exact cached
  payload length.  Authored attribution strings alone cannot satisfy this.
- The repeat arm is a TRUE reuse arm: it re-uses arm B's already-populated
  cache directory with a fresh server and fresh client, MUST NOT re-stage
  (no staging receipt may exist for it), and must retain a pre-check
  receipt proving the cache file already existed with the exact size and
  SHA-256 BEFORE the new server/client started.

Summary booleans are rejected rather than trusted.  FNV-1a is used only to
verify the upstream cache filename calculation -- SHA-256 and the accepted
R8-D authority remain the InferSwarm authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from issue74_methodology import canonical_json_bytes
from issue200_r8f_rpc_cache_mechanism import UPSTREAM_SOURCE_IDENTITY
import issue200_r8f_backing_verify as backing_verify
import issue200_r8f_range_receipt as range_receipt
import issue200_r8f_cache_enum as cache_enum
import issue200_r8f_stage_cache as stage_cache
import issue200_r8f_network_reduce as network_reduce

ROOT = Path(__file__).resolve().parents[1]
AREA = Path("docs/implementation/r8-f-local-backing-source-policy-200")
AUTHORITY_PATH = Path("docs/investigations/qwen38-flash-next-r8-d-v2/evidence/split-identity/split-rehash.json")
HOST_INVENTORY_DIR = Path("docs/investigations/qwen38-flash-next-r8-d-v2/evidence/host-inventory")
PINNED_LLAMA_CPP_COMMIT = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
SCHEMA = "inferswarm.issue200.physical-phase5/4"
ARMS = ("cold_remote", "local_verified", "repeat_local_verified")
PARTICIPANT_BACKING_SCHEMA = "inferswarm.issue200.participant-full-release-receipt/1"
CACHE_ENUM_SCHEMA = "inferswarm.issue200.cache-enumeration-receipt/2"
STAGE_MEASUREMENT_SCHEMA = "inferswarm.issue200.cache-staging-measurement/1"
CLIENT_LAUNCH_SCHEMA = "inferswarm.issue200.client-launch-receipt/1"
RPC_LAUNCH_SCHEMA = "inferswarm.issue200.rpc-server-launch-receipt/1"
PARTICIPANT_READ_SCHEMA = "inferswarm.issue200.participant-cache-read-receipt/1"
FORBIDDEN_SUMMARY_FIELDS = {
    "accepted_release_hashes_matched", "provenance_verified",
    "identical_required_state_and_placement", "zero_reacquisition_bytes_measured",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_key(value: Any) -> str:
    import json as _json
    return _json.dumps(value, sort_keys=True)


def fnv1a64(data: bytes) -> str:
    """The pinned upstream cache-key algorithm, never a trust decision."""
    value = 0xcbf29ce484222325
    for byte in data:
        value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    return f"{value:016x}"


def accepted_model_authority() -> dict[str, Any]:
    """Read (rather than duplicate) the accepted R8-D member authority."""
    authority = json.loads((ROOT / AUTHORITY_PATH).read_text())
    members = authority.get("members")
    if authority.get("schema") != "inferswarm.issue195.split-rehash/2" or not isinstance(members, list):
        raise AssertionError("accepted R8-D split authority is malformed")
    normalized = [{"file": item["file"], "bytes": item["bytes"], "sha256": item["sha256"]}
                  for item in members]
    if len(normalized) != 3 or sum(item["bytes"] for item in normalized) != authority.get("total_bytes"):
        raise AssertionError("accepted R8-D split authority is incomplete")
    return {"authority_path": str(AUTHORITY_PATH), "members": normalized,
            "total_bytes": authority["total_bytes"]}


def accepted_rpc_binary_authority() -> dict[str, str]:
    """Derive accepted RPC-server binary identities from R8-D raw inventory."""
    result = {}
    for path in sorted((ROOT / HOST_INVENTORY_DIR).glob("*-inventory-raw.txt")):
        node_id = path.name.removesuffix("-inventory-raw.txt")
        match = re.search(r"^([0-9a-f]{64})\s+.*?/ggml-rpc-server$", path.read_text(), re.MULTILINE)
        if not match:
            raise AssertionError(f"accepted R8-D inventory lacks RPC binary hash: {path}")
        result[node_id] = match.group(1)
    if not result:
        raise AssertionError("accepted R8-D RPC binary authority missing")
    return result


def accepted_client_binary_authority() -> str:
    """The pinned client llama-server identity from the R8-D raw inventory."""
    inventory = (ROOT / HOST_INVENTORY_DIR / "inferswarm01-inventory-raw.txt").read_text()
    match = re.search(r"^([0-9a-f]{64})\s+.*?/llama-server$", inventory, re.MULTILINE)
    if not match:
        raise AssertionError("accepted R8-D inventory lacks client llama-server hash")
    return match.group(1)


def _read_receipt(base: Path, receipt: Mapping[str, Any], expected_arm: str | None, kind: str):
    path = receipt.get("path")
    claimed = receipt.get("sha256")
    if not isinstance(path, str) or not isinstance(claimed, str):
        raise ValueError(f"{kind} receipt path/sha256 missing")
    target = (base / path).resolve()
    if base.resolve() not in target.parents or not target.is_file():
        raise ValueError(f"{kind} receipt path is missing or escapes evidence root")
    raw = target.read_bytes()
    if _sha256(raw) != claimed:
        raise ValueError(f"{kind} receipt sha256 mismatch")
    document = json.loads(raw)
    if expected_arm is not None and document.get("arm") != expected_arm:
        raise ValueError(f"{expected_arm}: {kind} receipt arm mismatch")
    return document


def _read_raw_bytes(base: Path, receipt: Mapping[str, Any], label: str) -> bytes:
    path, digest = receipt.get("path"), receipt.get("sha256")
    if not isinstance(path, str) or not isinstance(digest, str):
        raise ValueError(f"{label}: raw path/sha256 missing")
    target = (base / path).resolve()
    if base.resolve() not in target.parents or not target.is_file():
        raise ValueError(f"{label}: raw path missing or escapes evidence root")
    raw = target.read_bytes()
    if _sha256(raw) != digest:
        raise ValueError(f"{label}: raw SHA-256 mismatch")
    return raw


def _range_provenance(base: Path, arm: str, source: Mapping[str, Any], member: Mapping[str, Any],
                      expected_participant: str) -> bytes:
    provenance = source.get("provenance_receipt")
    if not isinstance(provenance, dict) or provenance.get("exit_code") != 0:
        raise ValueError(f"{arm}: accepted range has no successful raw provenance invocation")
    command = provenance.get("command")
    if not isinstance(command, list) or "scripts/issue200_r8f_range_receipt.py" not in command:
        raise ValueError(f"{arm}: accepted range provenance command is not the controlled helper")
    stderr = _read_raw_bytes(base, provenance.get("stderr", {}), f"{arm}: range stderr")
    if stderr:
        raise ValueError(f"{arm}: range helper stderr is nonempty")
    measured = json.loads(_read_raw_bytes(base, provenance.get("stdout", {}), f"{arm}: range stdout"))
    required = {"schema": "inferswarm.issue200.accepted-range-measurement/1", "member": member["file"],
                "accepted_member_bytes": member["bytes"], "accepted_member_sha256": member["sha256"],
                "offset": source.get("offset"), "length": source.get("length"),
                "range_sha256": source.get("sha256")}
    if any(measured.get(key) != value for key, value in required.items()):
        raise ValueError(f"{arm}: raw member/range measurement does not match accepted authority/mapping")
    if measured.get("node_id") != expected_participant or not isinstance(measured.get("source_path"), str) or not Path(measured["source_path"]).is_absolute():
        raise ValueError(f"{arm}: range measurement is not on the SET_TENSOR participant/absolute source path")
    if measured.get("tool") != {"path": "scripts/issue200_r8f_range_receipt.py", "sha256": range_receipt.helper_sha256()}:
        raise ValueError(f"{arm}: range helper source identity mismatch")
    retained = _read_raw_bytes(base, provenance.get("retained_range", {}), f"{arm}: retained range")
    if len(retained) != source["length"] or _sha256(retained) != source["sha256"]:
        raise ValueError(f"{arm}: retained range bytes do not match measured member range")
    return retained


def _verify_participant_backing(base: Path, document: Mapping[str, Any],
                                authority: dict[str, Any], participant: str) -> None:
    """Requirement: complete accepted three-member participant backing.

    Correction round 3 (review item 9): the retained raw helper receipt is
    the ONLY authority.  Every measured field is checked directly —
    ``verified:true`` / ``present:true`` never substitute for the actual
    bytes/SHA equality the helper measured.
    """
    block = document.get("participant_backing_verification")
    if not isinstance(block, dict) or block.get("node_id") != participant:
        raise ValueError("participant full-release backing verification is not bound to the participant")
    receipt = json.loads(_read_raw_bytes(base, block.get("receipt", {}), "participant backing receipt"))
    if receipt.get("schema") != PARTICIPANT_BACKING_SCHEMA:
        raise ValueError("participant backing receipt schema mismatch")
    # Helper identity: the exact committed helper source, never a claimed name.
    if receipt.get("tool") != {"path": "scripts/issue200_r8f_backing_verify.py",
                               "sha256": backing_verify.helper_sha256()}:
        raise ValueError("participant backing helper source identity mismatch")
    if not isinstance(receipt.get("authority_path"), str) or not receipt["authority_path"].endswith(str(AUTHORITY_PATH)):
        raise ValueError("participant backing authority path is not the exact committed R8-D authority")
    if receipt.get("node_id") != participant:
        raise ValueError("participant backing receipt is not from the SET_TENSOR participant")
    observed = receipt.get("members")
    if not isinstance(observed, list):
        raise ValueError("participant backing receipt members are malformed")
    # Exactly all accepted members: no extras, no omissions, exact order-independent identity.
    def _norm(item):
        return {"file": item.get("file"),
                "bytes": item.get("expected_bytes", item.get("bytes")),
                "sha256": item.get("expected_sha256", item.get("sha256"))}
    normalized = [_norm(item) for item in observed]
    expected = [_norm(m) for m in authority["members"]]
    if len(normalized) != len(expected) or sorted(map(canonical_key, normalized)) != sorted(map(canonical_key, expected)):
        raise ValueError("participant backing member set does not EQUAL the accepted authority members exactly")
    for item, member in zip(sorted(observed, key=lambda i: i["file"]), sorted(authority["members"], key=lambda m: m["file"])):
        # Measured-field equality: actual == expected == accepted, present and
        # verified true, for EVERY member.  No trusted summary booleans.
        if item.get("file") != member["file"]:
            raise ValueError(f"participant backing member mismatch: {item.get('file')}")
        if item.get("expected_bytes") != member["bytes"] or item.get("expected_sha256") != member["sha256"]:
            raise ValueError(f"participant backing expected identity differs from authority: {item.get('file')}")
        if item.get("actual_bytes") != member["bytes"]:
            raise ValueError(f"participant backing measured size differs from accepted: {item.get('file')}")
        if item.get("actual_sha256") != member["sha256"]:
            raise ValueError(f"participant backing measured SHA-256 differs from accepted: {item.get('file')}")
        if item.get("present") is not True or item.get("verified") is not True:
            raise ValueError(f"participant backing member not live-verified: {item.get('file')}")
    if receipt.get("total_bytes") != authority["total_bytes"]:
        raise ValueError("participant backing total bytes do not equal the accepted total")
    if receipt.get("all_members_verified") is not True:
        raise ValueError("participant backing all_members_verified is not true")
    backing_dir = receipt.get("backing_dir")
    if not isinstance(backing_dir, str) or not backing_dir.startswith("/"):
        raise ValueError("participant backing directory is not an absolute durable path")
    stderr = _read_raw_bytes(base, block.get("stderr", {}), "participant backing helper stderr")
    if stderr:
        raise ValueError("participant backing helper stderr is nonempty")



def _verify_cache_enumeration(base: Path, arm: str, receipt_ref: Mapping[str, Any],
                              cache_dir: str, expected_entries: list[dict[str, Any]],
                              participant: str = "inferswarm04") -> float:
    """A cache enumeration receipt is a retained raw participant-side listing.

    Correction round 3 (review item 11): the receipt must carry the EXACT
    committed enumerator helper identity (path + sha256) and the actual
    executable/argv that ran.  A receipt emitted by any other tool —
    including the pre-correction helper whose argv named a fictitious
    ``cache-enum.sh`` — cannot validate.
    """
    receipt = _read_receipt(base, receipt_ref, arm, "cache enumeration")
    if receipt.get("schema") != CACHE_ENUM_SCHEMA or receipt.get("cache_dir") != cache_dir:
        raise ValueError(f"{arm}: cache enumeration receipt is not bound to the private cache directory")
    if receipt.get("node_id") != participant:
        raise ValueError(f"{arm}: cache enumeration was not performed on the participant")
    if receipt.get("tool") != {"path": "scripts/issue200_r8f_cache_enum.py",
                               "sha256": cache_enum.helper_sha256()}:
        raise ValueError(f"{arm}: cache enumeration helper source identity mismatch")
    command = receipt.get("command")
    if (not isinstance(command, list) or len(command) != 4
            or not command[1].endswith("issue200_r8f_cache_enum.py")
            or command[2] != arm or command[3] != cache_dir):
        raise ValueError(f"{arm}: cache enumeration command is not the exact requested arm/cache-dir invocation")
    measured_at = receipt.get("measured_at")
    if not isinstance(measured_at, (int, float)):
        raise ValueError(f"{arm}: cache enumeration lacks a measurement timestamp")
    entries = receipt.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"{arm}: cache enumeration entries are malformed")
    normalized = [{"name": e.get("name"), "size": e.get("size"), "sha256": e.get("sha256")}
                  for e in entries if isinstance(e, dict)]
    if normalized != expected_entries:
        raise ValueError(f"{arm}: cache enumeration does not show the mechanically required state")
    return measured_at


def _network_bytes(base: Path, arm: str, receipt: Mapping[str, Any], payloads: list[dict[str, Any]],
                   payload_bytes: list[bytes], client_argv: list[str]) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise ValueError(f"{arm}: raw network capture receipt missing")
    allowed = {"arm", "capture_tool", "capture_command", "client_argv", "client_pid", "server_endpoint",
               "raw_capture", "reducer_sha256", "reduction_stdout"}
    if set(receipt) != allowed:
        raise ValueError(f"{arm}: authored network classification/count fields are forbidden")
    raw = _read_raw_bytes(base, receipt.get("raw_capture", {}), f"{arm}: raw network capture")
    if receipt.get("capture_tool") != network_reduce.CAPTURE_TOOL:
        raise ValueError(f"{arm}: capture command/tool identity missing")
    if receipt.get("client_argv") != client_argv:
        raise ValueError(f"{arm}: capture is not bound to the frozen client argv")
    if not isinstance(receipt.get("client_pid"), int) or not isinstance(receipt.get("server_endpoint"), str):
        raise ValueError(f"{arm}: capture PID/endpoint binding missing")
    if receipt.get("arm") != arm:
        raise ValueError(f"{arm}: capture arm binding missing")
    lengths = [int(p["length"]) for p in payloads]
    network_reduce.validate_capture_contract(receipt.get("capture_command"), client_argv, lengths)
    observed_payloads = [{**item, "bytes": data} for item, data in zip(payloads, payload_bytes)]
    derived = network_reduce.reduce_capture(raw, client_pid=receipt["client_pid"],
                                            server_endpoint=receipt["server_endpoint"],
                                            payloads=observed_payloads, client_argv=client_argv)
    if receipt.get("reducer_sha256") != network_reduce.reducer_sha256():
        raise ValueError(f"{arm}: network reducer source identity mismatch")
    stored = _read_raw_bytes(base, receipt.get("reduction_stdout", {}), f"{arm}: network reduction stdout")
    if stored != canonical_json_bytes(derived):
        raise ValueError(f"{arm}: stored network reduction differs from raw-capture derivation")
    expected = sorted(({key: payload[key] for key in ("participant", "observation_id", "order", "offset", "length", "sha256")}
                       for payload in observed_payloads), key=lambda item: item["order"])
    if arm == "cold_remote" and derived["payload_identities"] != expected:
        raise ValueError(f"{arm}: raw capture does not account for every frozen SET_TENSOR payload byte-exactly")
    if arm != "cold_remote" and derived["payload_identities"]:
        raise ValueError(f"{arm}: raw capture moved immutable SET_TENSOR payload")
    return {"immutable_payload": derived["immutable_payload_bytes"],
            "rpc_control": derived["protocol_control_hash_probe_bytes"],
            "total": derived["client_to_server_bytes"], "payload_identities": derived["payload_identities"],
            "client_execve_ts": derived["client_execve_ts"]}


def _verify_client_runtime(base: Path, arm: str, arm_doc: Mapping[str, Any], client_argv: list[str],
                           pinned_client_sha: str) -> dict[str, Any]:
    """Client launch receipt (DEMOTED — review items 5/15).

    Correction round 3: this assembler-generated ``client-launch.json`` is a
    DERIVATIVE CONVENIENCE SUMMARY ONLY.  Client argv is proven from the raw
    capture's first-execve record inside the network reducer (byte-for-byte
    full-argv comparison); the launch summary may only cross-check.  Binary
    identity, log retention, and PID presence still bind here.
    """
    receipt = _read_receipt(base, arm_doc.get("client_launch_receipt", {}), arm, "client launch")
    if receipt.get("schema") != CLIENT_LAUNCH_SCHEMA:
        raise ValueError(f"{arm}: client launch receipt schema mismatch")
    if receipt.get("argv") != client_argv:
        raise ValueError(f"{arm}: client launch summary argv contradicts the frozen client command")
    if receipt.get("binary_sha256") != pinned_client_sha or not isinstance(receipt.get("binary_live_receipt"), dict):
        raise ValueError(f"{arm}: client binary identity is not live-receipt bound")
    live = _read_receipt(base, receipt["binary_live_receipt"], None, "client binary live receipt")
    if live.get("sha256") != pinned_client_sha or live.get("argv") != ["sha256sum", client_argv[0]]:
        raise ValueError(f"{arm}: client binary live receipt does not bind the executed binary")
    log_ref = receipt.get("client_log")
    if not isinstance(log_ref, dict):
        raise ValueError(f"{arm}: client log receipt missing")
    log = _read_raw_bytes(base, log_ref, f"{arm}: client log")
    listening = f"listening on http://127.0.0.1:".encode()
    if listening not in log:
        raise ValueError(f"{arm}: retained client log does not prove the defined listening endpoint")
    if not isinstance(receipt.get("pid"), int) or receipt["pid"] <= 0:
        raise ValueError(f"{arm}: client launch receipt lacks process identity")
    if not isinstance(receipt.get("started_at"), (int, float)):
        raise ValueError(f"{arm}: client launch receipt lacks a start timestamp")
    return {"pid": receipt["pid"], "started_at": receipt["started_at"]}


def _verify_rpc_runtime(base: Path, arm: str, arm_doc: Mapping[str, Any], cache_dir: str,
                        pinned_rpc_sha: str) -> dict[str, Any]:
    """RPC-server launch receipt (DEMINUTURED — review item 15).

    Correction round 3: this assembler-generated ``rpc-launch.json`` is a
    DERIVATIVE CONVENIENCE SUMMARY ONLY.  It must not establish executable,
    argv, or environment authority: those are proven from the retained raw
    participant strace's own first-execve record inside
    ``_verify_participant_read`` (binary path + exact argv) and from the
    exact FNV cache path that server actually opens (effective cache use —
    an authored ``LLAMA_CACHE`` env field is NOT authority).  Here we only
    check the summary is internally consistent (binary identity receipts,
    log retention, PID presence) so a contradicted summary fails closed.
    """
    receipt = _read_receipt(base, arm_doc.get("rpc_server_receipt", {}), arm, "rpc server launch")
    if receipt.get("schema") != RPC_LAUNCH_SCHEMA:
        raise ValueError(f"{arm}: rpc-server launch receipt schema mismatch")
    if receipt.get("binary_sha256") != pinned_rpc_sha or not isinstance(receipt.get("binary_live_receipt"), dict):
        raise ValueError(f"{arm}: rpc-server binary identity is not live-receipt bound")
    live = _read_receipt(base, receipt["binary_live_receipt"], None, "rpc binary live receipt")
    if live.get("sha256") != pinned_rpc_sha:
        raise ValueError(f"{arm}: rpc binary live receipt does not bind the executed binary")
    log_ref = receipt.get("server_log")
    if not isinstance(log_ref, dict):
        raise ValueError(f"{arm}: rpc-server log receipt missing")
    _read_raw_bytes(base, log_ref, f"{arm}: rpc-server log")
    if not isinstance(receipt.get("pid"), int) or receipt["pid"] <= 0:
        raise ValueError(f"{arm}: rpc-server launch receipt lacks process identity")
    if not isinstance(receipt.get("started_at"), (int, float)):
        raise ValueError(f"{arm}: rpc-server launch receipt lacks a start timestamp")
    # Cross-check only (non-authoritative): if the summary still carries an
    # env claim, it must not contradict the cache_dir the raw strace binds.
    env = receipt.get("env", {})
    if isinstance(env, dict) and "LLAMA_CACHE" in env and env["LLAMA_CACHE"] != cache_dir:
        raise ValueError(f"{arm}: rpc-server summary env contradicts the bound cache directory")
    return {"pid": receipt["pid"], "started_at": receipt["started_at"]}


_READ_LINE = re.compile(r"^(?P<pid>\d+)\s+(?P<ts>\S+)\s+(?P<record>.*)$")
_OPENAT = re.compile(r'^openat\((?P<dir>(?:-?\d+|AT_FDCWD)), "(?P<path>(?:[^"\\]|\\.)*)",.*\)\s+=\s+(?P<fd>\d+)$')
_READ = re.compile(r"^read\((?P<fd>\d+),.*\)\s+=\s+(?P<result>\d+)$")

# The exact frozen RPC-server execution the participant-side from-exec strace
# must prove (review item 7): binary path plus host/port/device/cache-enable
# arguments, in order.  Derived from the pinned launch contract, never from
# assembler-authored rpc-launch.json fields.
FROZEN_RPC_EXEC = ("/home/hermes/llama.cpp/build-v041/bin/ggml-rpc-server",
                   ["-H", "0.0.0.0", "-p", "50052", "-d", "CUDA0", "-c"])


def _unescape(text: str) -> str:
    return re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), text)


def _parse_first_execve(capture: bytes, arm: str) -> tuple[int, str, list[str]]:
    """Bind the strace root PID and the exact first-execve argv.

    The participant-side capture is from-exec: its FIRST record must be the
    ggml-rpc-server's own ``execve`` (an attach can never produce this).
    Returns (root_pid, binary_path, argv).  Abbreviated/unparseable execve,
    or a first record that is not the server's execve, is a rejection.
    """
    first_line = capture.split(b"\n", 1)[0].decode("utf-8", "strict")
    match = _READ_LINE.match(first_line)
    if match is None:
        raise ValueError(f"{arm}: participant strace lacks a PID-prefixed first record")
    record = match["record"]
    parsed = network_reduce.parse_execve(record)
    if parsed is None:
        raise ValueError(f"{arm}: participant strace first record is not a parseable complete execve")
    return int(match["pid"]), parsed[0], parsed[1]


def _participant_exec_ts(base: Path, arm: str, arm_doc: Mapping[str, Any]) -> float:
    """The participant server's exec timestamp from the raw strace itself."""
    receipt = _read_receipt(base, arm_doc.get("participant_read_receipt", {}), arm, "participant cache read")
    capture = _read_raw_bytes(base, receipt.get("strace_capture", {}), f"{arm}: participant read strace")
    first_line = capture.split(b"\n", 1)[0].decode("utf-8", "strict")
    _parse_first_execve(capture, arm)  # proves the record is the server's own execve
    match = _READ_LINE.match(first_line)
    if match is None:
        raise ValueError(f"{arm}: participant strace first record is malformed")
    return float(match["ts"])


def _verify_participant_read(base: Path, arm: str, arm_doc: Mapping[str, Any],
                             cache_dir: str, fnv: str, payload_length: int,
                             server_pid: int, require_zero: bool = False) -> dict[str, Any]:
    """LOCAL_VERIFIED source attribution derived from the participant-side
    from-exec file strace of this arm's own ggml-rpc-server.

    Correction round 3 (review items 7/8): the SAME retained strace now
    establishes BOTH (a) the server's execution provenance — its first
    record must be the accepted ggml-rpc-server binary's own execve with the
    exact frozen argv including ``-c`` (cache enable) — and (b) effective
    cache use: the bound server PID opens/reads the exact FNV cache path.
    The assembler-authored ``rpc-launch.json`` argv/env is NOT authority; an
    authored ``LLAMA_CACHE`` env field is at most a cross-check, never proof
    (the effective cache use is the FNV path actually opened).

    With ``require_zero`` (cold arm), the derivation instead proves the
    server performed ZERO successful reads of the cache file (the file may
    legitimately be opened for writing — that is the cold cache miss path).
    """
    receipt_ref = arm_doc.get("participant_read_receipt")
    if not isinstance(receipt_ref, dict):
        raise ValueError(f"{arm}: participant cache-read receipt missing")
    receipt = _read_receipt(base, receipt_ref, arm, "participant cache read")
    if receipt.get("schema") != PARTICIPANT_READ_SCHEMA:
        raise ValueError(f"{arm}: participant cache-read receipt schema mismatch")
    capture = _read_raw_bytes(base, receipt.get("strace_capture", {}), f"{arm}: participant read strace")
    if receipt.get("server_pid") != server_pid:
        raise ValueError(f"{arm}: cache-read strace is not bound to the arm's server process")
    # (a) Execution provenance from the capture itself.
    root_pid, exec_path, exec_argv = _parse_first_execve(capture, arm)
    if root_pid != server_pid:
        raise ValueError(f"{arm}: participant strace root PID is not the server PID whose reads carry attribution")
    if exec_path != FROZEN_RPC_EXEC[0]:
        raise ValueError(f"{arm}: participant server did not start from the accepted ggml-rpc-server binary")
    if exec_argv != [FROZEN_RPC_EXEC[0], *FROZEN_RPC_EXEC[1]]:
        raise ValueError(f"{arm}: participant server execve argv does not match the frozen RPC launch byte-for-byte")
    # (b) Effective cache use: the exact FNV cache path this server opens/reads.
    expected_path = f"{cache_dir}/rpc/{fnv}"
    try:
        lines = capture.decode("utf-8", "strict").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError(f"{arm}: participant read strace is not strict UTF-8") from error
    fd = None
    read_total = 0
    read_count = 0
    for line in lines:
        match = _READ_LINE.match(line)
        if match is None:
            continue
        pid, record = int(match["pid"]), match["record"]
        openat = _OPENAT.match(record)
        if openat is not None:
            if fd is not None and int(openat["fd"]) == fd:
                # FD reuse: stop attributing reads to the cache file once the
                # same FD number is opened for a different path (review P2).
                fd = None
            if _unescape(openat["path"]) == expected_path:
                if pid != server_pid:
                    raise ValueError(f"{arm}: cache file was opened by a process other than the bound server")
                fd = int(openat["fd"])
            continue
        read = _READ.match(record)
        if read is not None and fd is not None and int(read["fd"]) == fd:
            if pid != server_pid:
                raise ValueError(f"{arm}: cache file was read by a process other than the bound server")
            result = int(read["result"])
            if result <= 0:
                raise ValueError(f"{arm}: cache-file read returned a nonpositive result")
            read_total += result
            read_count += 1
    if require_zero:
        # COLD-ARM DENIAL: the server may open the cache file (write path on
        # the miss) but must never successfully READ it.  A successful read
        # means the payload came from pre-populated local state, contradicting
        # REMOTE_AUTHORIZED attribution.
        if read_total != 0:
            raise ValueError(f"{arm}: participant server READ {read_total} bytes of the cache file")
        if receipt.get("derived_read_bytes") != 0 or receipt.get("read_syscalls") != 0:
            raise ValueError(f"{arm}: retained cache-read receipt disagrees with the zero-read re-derivation")
        return {"opened_path": expected_path, "read_bytes": 0, "read_syscalls": 0}
    if fd is None:
        raise ValueError(f"{arm}: participant server never opened the exact FNV cache file")
    if read_total != payload_length:
        raise ValueError(f"{arm}: participant cache-file reads account {read_total} bytes, expected exactly {payload_length}")
    if receipt.get("derived_read_bytes") != read_total or receipt.get("read_syscalls") != read_count:
        raise ValueError(f"{arm}: retained cache-read receipt disagrees with the raw strace re-derivation")
    return {"opened_path": expected_path, "read_bytes": read_total, "read_syscalls": read_count}


def _same_keys(values: list[Mapping[str, Any]], keys: tuple[str, ...], label: str):
    baseline = {key: values[0].get(key) for key in keys}
    if any({key: value.get(key) for key in keys} != baseline for value in values[1:]):
        raise ValueError(f"{label} differs across arms")
    return baseline


def _validate_payload_ranges(base: Path, arm: str, mappings: Any, authority: dict[str, Any],
                             payloads: list[dict[str, Any]], participant_ids: list[str]) -> list[bytes]:
    """Bind every observed SET_TENSOR payload to actual accepted-member bytes."""
    if not isinstance(mappings, list) or len(mappings) != len(payloads):
        raise ValueError(f"{arm}: every SET_TENSOR payload needs one accepted-range provenance receipt")
    members = {member["file"]: member for member in authority["members"]}
    payload_index = {(p["offset"], p["length"], p["sha256"]): p for p in payloads}
    result: list[bytes] = []
    seen = set()
    for mapping in mappings:
        if not isinstance(mapping, dict) or not isinstance(mapping.get("accepted_artifact_range"), dict):
            raise ValueError(f"{arm}: malformed accepted range mapping")
        source, payload = mapping["accepted_artifact_range"], mapping.get("set_tensor_payload")
        member = members.get(source.get("member"))
        if not member or not isinstance(source.get("offset"), int) or not isinstance(source.get("length"), int):
            raise ValueError(f"{arm}: accepted range member/offset/length malformed")
        if source["offset"] < 0 or source["length"] <= 0 or source["offset"] + source["length"] > member["bytes"]:
            raise ValueError(f"{arm}: accepted range exceeds accepted member")
        key = (payload.get("offset"), payload.get("length"), payload.get("sha256")) if isinstance(payload, dict) else None
        if (key not in payload_index or payload != payload_index[key]
                or source["length"] != payload["length"] or source.get("sha256") != payload["sha256"]):
            raise ValueError(f"{arm}: accepted range is not this observed SET_TENSOR payload")
        if key in seen:
            raise ValueError(f"{arm}: duplicate accepted range mapping")
        seen.add(key)
        result.append(_range_provenance(base, arm, source, member, payload_index[key]["participant"]))
    if seen != set(payload_index):
        raise ValueError(f"{arm}: accepted ranges do not cover all observed payloads")
    return result


def _validate_stage_mapping(base: Path, arm: str, mappings: Any, authority: dict[str, Any],
                            payloads: list[dict[str, Any]], cache_dir: str, participant_ids: list[str]):
    if not isinstance(mappings, list) or not mappings:
        raise ValueError(f"{arm}: cache staging mapping missing")
    members = {member["file"]: member for member in authority["members"]}
    payload_index = {(p["offset"], p["length"], p["sha256"]): p for p in payloads}
    seen = set()
    for mapping in mappings:
        source, payload, staged = (mapping.get("accepted_artifact_range"), mapping.get("set_tensor_payload"),
                                   mapping.get("staged_cache"))
        if not all(isinstance(item, dict) for item in (source, payload, staged)):
            raise ValueError(f"{arm}: malformed staging mapping")
        member = members.get(source.get("member"))
        if not member or not isinstance(source.get("offset"), int) or not isinstance(source.get("length"), int):
            raise ValueError(f"{arm}: unknown or malformed accepted source range")
        if source["offset"] < 0 or source["length"] <= 0 or source["offset"] + source["length"] > member["bytes"]:
            raise ValueError(f"{arm}: source range outside accepted member")
        key = (payload.get("offset"), payload.get("length"), payload.get("sha256"))
        if key not in payload_index or payload != payload_index[key] or source["length"] != payload["length"]:
            raise ValueError(f"{arm}: staging mapping does not cover an observed SET_TENSOR payload")
        if source.get("sha256") != payload.get("sha256"):
            raise ValueError(f"{arm}: staged payload digest differs from verified backing range")
        expected_participant = payload_index[key]["participant"]
        measured_bytes = _range_provenance(base, arm, source, member, expected_participant)
        if measured_bytes != _read_raw_bytes(base, staged.get("range_bytes", {}), f"{arm}: staged range bytes"):
            raise ValueError(f"{arm}: staged range bytes differ from measured accepted member range")
        fnv = payload.get("fnv1a_cache_key")
        if not isinstance(fnv, str) or fnv1a64(measured_bytes) != fnv:
            raise ValueError(f"{arm}: FNV cache filename does not match actual payload bytes")
        # STAGING PROVENANCE (review item 13): the controlled helper's RAW
        # CANONICAL STDOUT is the authority, consumed directly.  It must
        # carry the exact committed helper identity; the assembler wrapper
        # ("staging.json" + authored exit_code) is derivative only.
        raw_stdout_ref = staged.get("raw_stdout")
        if not isinstance(raw_stdout_ref, dict):
            raise ValueError(f"{arm}: staging raw helper stdout is missing")
        raw_stdout = _read_raw_bytes(base, raw_stdout_ref, f"{arm}: staging raw stdout")
        measurement = json.loads(raw_stdout)
        if measurement.get("schema") != STAGE_MEASUREMENT_SCHEMA:
            raise ValueError(f"{arm}: staging raw stdout is not the controlled helper's measurement")
        if measurement.get("tool") != {"path": "scripts/issue200_r8f_stage_cache.py",
                                       "sha256": stage_cache.helper_sha256()}:
            raise ValueError(f"{arm}: staging helper source identity mismatch")
        raw_stderr_ref = staged.get("raw_stderr")
        if not isinstance(raw_stderr_ref, dict):
            raise ValueError(f"{arm}: staging raw helper stderr is missing")
        if _read_raw_bytes(base, raw_stderr_ref, f"{arm}: staging raw stderr"):
            raise ValueError(f"{arm}: staging helper stderr is nonempty")
        if (measurement.get("node_id") != expected_participant or measurement.get("cache_dir") != cache_dir
                or measurement.get("staged_path") != staged.get("path")):
            raise ValueError(f"{arm}: cache staging receipt is not bound to the payload participant/cache path")
        if (measurement.get("range_sha256") != payload["sha256"]
                or measurement.get("tmp_sha256") != payload["sha256"] or measurement.get("final_sha256") != payload["sha256"]
                or measurement.get("tmp_size") != payload["length"] or measurement.get("final_size") != payload["length"]
                or measurement.get("offset") != source["offset"] or measurement.get("length") != payload["length"]
                or measurement.get("fnv1a_cache_key") != fnv
                or measurement.get("member") != source["member"]):
            raise ValueError(f"{arm}: staging measurement does not verify exact digest/size before and after publish")
        if not isinstance(measurement.get("tmp_path"), str) or not measurement["tmp_path"].startswith(cache_dir.rstrip("/") + "/"):
            raise ValueError(f"{arm}: staging temporary file was not written inside the target cache directory")
        if measurement.get("atomic_publish") != "os.rename after fsync inside target directory":
            raise ValueError(f"{arm}: staging measurement does not document atomic-publish semantics")
        if not staged["path"].startswith(cache_dir.rstrip("/") + "/") or Path(staged["path"]).name != fnv:
            raise ValueError(f"{arm}: staged cache path is not the FNV-keyed final path inside its private cache directory")
        seen.add(key)
    if seen != set(payload_index):
        raise ValueError(f"{arm}: every observed SET_TENSOR payload needs one staging mapping")


def validate_physical_evidence(document: Mapping[str, Any], *, evidence_root: Path) -> dict[str, Any]:
    """Derive Phase-5 acceptance facts from raw receipts, fail closed."""
    try:
        if not isinstance(document, dict) or document.get("schema") != SCHEMA:
            raise ValueError("schema mismatch")
        forbidden = sorted(FORBIDDEN_SUMMARY_FIELDS & document.keys())
        if forbidden:
            raise ValueError(f"authored summary predicates are forbidden: {forbidden}")
        authority = accepted_model_authority()
        observed = document.get("accepted_model_members")
        if observed != authority["members"] or document.get("accepted_total_bytes") != authority["total_bytes"]:
            raise ValueError("accepted member identities, digests, sizes, or total do not match R8-D authority")
        runtime = document.get("runtime")
        participants = document.get("participants")
        if (not isinstance(runtime, dict) or runtime.get("llama_cpp_commit") != PINNED_LLAMA_CPP_COMMIT
                or not isinstance(participants, list) or not participants):
            raise ValueError("pinned runtime or participant identities missing")
        if runtime.get("source_files") != UPSTREAM_SOURCE_IDENTITY:
            raise ValueError("pinned llama.cpp source identities do not match retained Phase-4 authority")
        participant_ids = [p.get("node_id") for p in participants if isinstance(p, dict)]
        if len(participant_ids) != len(participants) or len(set(participant_ids)) != len(participants):
            raise ValueError("participant Node identities are empty or non-unique")
        if any(not p.get("rpc_endpoint") or not p.get("rpc_command") for p in participants):
            raise ValueError("exact RPC endpoints/process commands missing")
        if not isinstance(runtime.get("binaries"), list) or not runtime["binaries"]:
            raise ValueError("pinned runtime binary identities missing")
        accepted_binaries = accepted_rpc_binary_authority()
        observed_binaries = {item.get("node_id"): item.get("sha256") for item in runtime["binaries"]
                             if isinstance(item, dict) and item.get("binary") == "ggml-rpc-server"}
        if (set(observed_binaries) != set(participant_ids)
                or any(accepted_binaries.get(node_id) != digest
                       for node_id, digest in observed_binaries.items())):
            raise ValueError("pinned RPC binary identities do not match accepted R8-D inventory")
        pinned_client_sha = accepted_client_binary_authority()
        participant_id = participant_ids[0]
        if not isinstance(participant_id, str) or not participant_id:
            raise ValueError("primary participant identity missing")
        frozen = document.get("frozen")
        frozen_keys = ("required_state_identity", "participant_requirements_identity",
                       "placement_identity", "materialization_identity")
        if not isinstance(frozen, dict) or any(not isinstance(frozen.get(key), str) or not frozen[key]
                                               for key in frozen_keys):
            raise ValueError("frozen required-state/placement/materialization identities missing")
        client_argv = document.get("frozen_client_argv")
        if (not isinstance(client_argv, list) or len(client_argv) < 2
                or not all(isinstance(item, str) and item for item in client_argv)):
            raise ValueError("frozen client argv missing")
        _verify_participant_backing(evidence_root, document, authority, participant_id)
        arms = document.get("arms")
        if not isinstance(arms, dict) or set(arms) != set(ARMS):
            raise ValueError("exact cold/local/repeat arms missing")
        arm_docs = [arms[name] for name in ARMS]
        if any(not isinstance(arm, dict) for arm in arm_docs):
            raise ValueError("arm is not an object")
        expected_policy = {"cold_remote": "PREFER_REMOTE_AUTHORIZED",
                           "local_verified": "REQUIRE_LOCAL_VERIFIED",
                           "repeat_local_verified": "REQUIRE_LOCAL_VERIFIED"}
        expected_source = {"cold_remote": "REMOTE_AUTHORIZED",
                           "local_verified": "LOCAL_VERIFIED",
                           "repeat_local_verified": "LOCAL_VERIFIED"}
        network = {}
        payload_identities = []
        local_cache_dir = None
        for name, arm in zip(ARMS, arm_docs):
            if arm.get("source_policy") != expected_policy[name] or arm.get("source_attribution") != expected_source[name]:
                raise ValueError(f"{name}: Source attribution/policy does not match arm")
            if arm.get("participants") != participant_ids:
                raise ValueError(f"{name}: participants do not match retained receipts")
            for key in frozen_keys:
                if arm.get(key) != frozen[key]:
                    raise ValueError(f"{name}: {key} differs from frozen identity")
            client_info = _verify_client_runtime(evidence_root, name, arm, client_argv, pinned_client_sha)
            if arm.get("network_receipt", {}).get("client_pid") != client_info["pid"]:
                raise ValueError(f"{name}: network capture PID is not the launched client process")
            payloads = arm.get("set_tensor_payloads")
            if not isinstance(payloads, list) or not payloads:
                raise ValueError(f"{name}: actual SET_TENSOR payload boundaries missing")
            for payload in payloads:
                if (not isinstance(payload, dict) or not isinstance(payload.get("offset"), int)
                        or not isinstance(payload.get("length"), int) or payload["offset"] < 0
                        or payload["length"] <= 0 or not re.fullmatch(r"[0-9a-f]{64}", str(payload.get("sha256", "")))):
                    raise ValueError(f"{name}: malformed SET_TENSOR boundary")
                if not isinstance(payload.get("observation_id"), str) or not payload["observation_id"] or not isinstance(payload.get("order"), int):
                    raise ValueError(f"{name}: SET_TENSOR observation/order identity missing")
                if payload.get("participant") not in participant_ids:
                    raise ValueError(f"{name}: SET_TENSOR participant identity missing")
            payload_bytes = _validate_payload_ranges(evidence_root, name, arm.get("accepted_artifact_ranges"),
                                                     authority, payloads, participant_ids)
            network[name] = _network_bytes(evidence_root, name, arm.get("network_receipt", {}), payloads,
                                           payload_bytes, client_argv)
            payload_identities.append(payloads)
            cache_dir = arm.get("private_cache_dir")
            if not isinstance(cache_dir, str) or not cache_dir:
                raise ValueError(f"{name}: private cache directory missing")
            fnv = payloads[0].get("fnv1a_cache_key")
            rpc_info = _verify_rpc_runtime(evidence_root, name, arm, cache_dir,
                                           accepted_binaries[participant_id])
            # Effective server start time: derived from the participant strace's
            # OWN first-record -ttt timestamp (raw evidence), never from an
            # assembler-authored started_at field.
            read_receipt_ts = _participant_exec_ts(evidence_root, name, arm)
            if name == "cold_remote":
                _verify_cache_enumeration(evidence_root, name, arm.get("cache_initialization_receipt", {}),
                                          cache_dir, [], participant_id)
                if "cache_staging" in arm:
                    raise ValueError(f"{name}: cold arm must not stage cache content")
                # COLD-ARM CACHE-READ DENIAL (review L2-1): REMOTE_AUTHORIZED
                # attribution requires proving the cold server never READ the
                # payload from a pre-populated cache.  Re-derive from the raw
                # participant strace: zero successful read() syscalls on the
                # FNV cache file by the bound server PID.  A forged
                # participant-read receipt that masks a local read must be
                # rejected here, not merely digest-bound.
                cold_read = _verify_participant_read(evidence_root, name, arm, cache_dir, fnv,
                                                     payloads[0]["length"], rpc_info["pid"],
                                                     require_zero=True)
                if cold_read["read_bytes"] != 0:
                    raise ValueError(f"{name}: cold/remote arm's server READ the cache file locally")
            elif name == "local_verified":
                if local_cache_dir is not None and cache_dir == local_cache_dir:
                    raise ValueError(f"{name}: cache directory collision")
                local_cache_dir = cache_dir
                _verify_cache_enumeration(evidence_root, name, arm.get("cache_initialization_receipt", {}),
                                          cache_dir, [], participant_id)
                _verify_cache_enumeration(evidence_root, name, arm.get("cache_after_staging_receipt", {}),
                                          cache_dir, [{"name": f"rpc/{fnv}", "size": payloads[0]["length"],
                                                       "sha256": payloads[0]["sha256"]}], participant_id)
                _validate_stage_mapping(evidence_root, name, arm.get("cache_staging"), authority, payloads,
                                        cache_dir, participant_ids)
                read = _verify_participant_read(evidence_root, name, arm, cache_dir, fnv,
                                                payloads[0]["length"], rpc_info["pid"])
                if read["opened_path"] != f"{cache_dir}/rpc/{fnv}":
                    raise ValueError(f"{name}: participant read is not of this arm's staged cache file")
            else:  # repeat_local_verified — the TRUE reuse arm
                if local_cache_dir is None or cache_dir != local_cache_dir:
                    raise ValueError(f"{name}: reuse arm does not reuse the local-verified arm's cache directory")
                if "cache_staging" in arm or "cache_initialization_receipt" in arm:
                    raise ValueError(f"{name}: reuse arm must not stage or freshly initialize a cache")
                # The precheck is a full hardened enumeration receipt (item 12):
                # exact helper identity + exact requested arm/cache-dir/node.
                _verify_cache_enumeration(evidence_root, name, arm.get("cache_precheck_receipt", {}),
                                          cache_dir, [{"name": f"rpc/{fnv}", "size": payloads[0]["length"],
                                                        "sha256": payloads[0]["sha256"]}], participant_id)
                precheck = _read_receipt(evidence_root, arm.get("cache_precheck_receipt", {}), name, "cache precheck")
                if precheck.get("schema") != CACHE_ENUM_SCHEMA or precheck.get("cache_dir") != cache_dir:
                    raise ValueError(f"{name}: cache precheck receipt is not bound to the reused cache directory")
                entries = [{"name": e.get("name"), "size": e.get("size"), "sha256": e.get("sha256")}
                           for e in precheck.get("entries", []) if isinstance(e, dict)]
                if entries != [{"name": f"rpc/{fnv}", "size": payloads[0]["length"], "sha256": payloads[0]["sha256"]}]:
                    raise ValueError(f"{name}: reused cache file did not already exist with exact size/SHA before the new server/client")
                measured = precheck.get("measured_at")
                if not isinstance(measured, (int, float)):
                    raise ValueError(f"{name}: cache precheck lacks a measurement timestamp")
                # Ordering authority (review item 8/L1-P2-02 disposition):
                # the before/after proof compares the enumerator's measured_at
                # against process start times DERIVED FROM THE RAW CAPTURES'
                # own -ttt first-record timestamps, never against
                # assembler-authored started_at fields.
                client_exec_ts = network[name]["client_execve_ts"]
                if not (measured < client_exec_ts and measured < read_receipt_ts):
                    raise ValueError(f"{name}: cache precheck was not measured before the new server/client started")
                read = _verify_participant_read(evidence_root, name, arm, cache_dir, fnv,
                                                payloads[0]["length"], rpc_info["pid"])
                if read["opened_path"] != f"{cache_dir}/rpc/{fnv}":
                    raise ValueError(f"{name}: participant read is not of the reused cache file")
        if len({canonical_json_bytes(item) for item in payload_identities}) != 1:
            raise ValueError("actual SET_TENSOR payload boundaries differ across arms")
        if network["cold_remote"]["immutable_payload"] <= 0:
            raise ValueError("cold/remote arm did not move immutable model payload")
        if not network["cold_remote"]["payload_identities"]:
            raise ValueError("cold/remote arm did not bind transfer to selected payload boundaries")
        if network["local_verified"]["immutable_payload"] != 0:
            raise ValueError("local verified arm reacquired immutable payload")
        if network["repeat_local_verified"]["immutable_payload"] != 0:
            raise ValueError("reuse arm reacquired immutable payload")
        return {"valid": True, "derived": {
            "accepted_model_authority": authority,
            "network": network,
            "payload_boundaries": payload_identities[0],
            "identities": frozen,
            "participants": participant_ids,
        }}
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        return {"valid": False, "reason": str(error)}
