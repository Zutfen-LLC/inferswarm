#!/usr/bin/env python3
"""Mechanical validator for Issue #200 Phase-5 physical receipts.

This is deliberately a verifier, not a fleet runner.  A fleet run retains
raw, per-arm receipts beside its JSON document; this module reads those
receipts and derives the predicates used by the terminal reducer.  Summary
booleans are rejected rather than trusted.  FNV-1a is used only to verify the
upstream cache filename calculation -- SHA-256 and the accepted R8-D authority
remain the InferSwarm authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from issue74_methodology import canonical_json_bytes
from issue200_r8f_rpc_cache_mechanism import UPSTREAM_SOURCE_IDENTITY

ROOT = Path(__file__).resolve().parents[1]
AREA = Path("docs/implementation/r8-f-local-backing-source-policy-200")
AUTHORITY_PATH = Path("docs/investigations/qwen38-flash-next-r8-d-v2/evidence/split-identity/split-rehash.json")
HOST_INVENTORY_DIR = Path("docs/investigations/qwen38-flash-next-r8-d-v2/evidence/host-inventory")
PINNED_LLAMA_CPP_COMMIT = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
SCHEMA = "inferswarm.issue200.physical-phase5/2"
ARMS = ("cold_remote", "local_verified", "repeat_local_verified")
FORBIDDEN_SUMMARY_FIELDS = {
    "accepted_release_hashes_matched", "provenance_verified",
    "identical_required_state_and_placement", "zero_reacquisition_bytes_measured",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _read_receipt(base: Path, receipt: Mapping[str, Any], expected_arm: str, kind: str):
    path = receipt.get("path")
    claimed = receipt.get("sha256")
    if not isinstance(path, str) or not isinstance(claimed, str):
        raise ValueError(f"{expected_arm}: {kind} receipt path/sha256 missing")
    target = (base / path).resolve()
    if base.resolve() not in target.parents or not target.is_file():
        raise ValueError(f"{expected_arm}: {kind} receipt path is missing or escapes evidence root")
    raw = target.read_bytes()
    if _sha256(raw) != claimed:
        raise ValueError(f"{expected_arm}: {kind} receipt sha256 mismatch")
    document = json.loads(raw)
    if document.get("arm") != expected_arm:
        raise ValueError(f"{expected_arm}: {kind} receipt arm mismatch")
    return document


def _network_bytes(base: Path, arm: str, receipt: Mapping[str, Any], payloads: list[dict[str, Any]]) -> dict[str, Any]:
    raw = _read_receipt(base, receipt, arm, "network")
    if raw.get("schema") != "inferswarm.issue200.network-receipt/1" or not isinstance(raw.get("events"), list):
        raise ValueError(f"{arm}: network receipt schema/events malformed")
    totals = {"immutable_payload": 0, "rpc_control": 0, "total": 0}
    expected = {(item["offset"], item["length"], item["sha256"]) for item in payloads}
    observed = set()
    for event in raw["events"]:
        if (not isinstance(event, dict) or not isinstance(event.get("bytes"), int)
                or event["bytes"] < 0 or event.get("classification") not in
                {"immutable_model_payload", "rpc_control_or_hash_probe"}):
            raise ValueError(f"{arm}: invalid network event")
        totals["total"] += event["bytes"]
        if event["classification"] == "immutable_model_payload":
            if event["bytes"] == 0:
                continue
            identity = (event.get("offset"), event.get("length"), event.get("sha256"))
            if identity not in expected or event["bytes"] != event.get("length"):
                raise ValueError(f"{arm}: immutable network event is not an observed SET_TENSOR payload")
            observed.add(identity)
            totals["immutable_payload"] += event["bytes"]
        else:
            totals["rpc_control"] += event["bytes"]
    if observed and observed != expected:
        raise ValueError(f"{arm}: immutable network receipt does not cover every observed payload")
    return {**totals, "source_attribution": raw.get("source_attribution"),
            "payload_identities": sorted(observed)}


def _same_keys(values: list[Mapping[str, Any]], keys: tuple[str, ...], label: str):
    baseline = {key: values[0].get(key) for key in keys}
    if any({key: value.get(key) for key in keys} != baseline for value in values[1:]):
        raise ValueError(f"{label} differs across arms")
    return baseline


def _validate_stage_mapping(base: Path, arm: str, mappings: Any, authority: dict[str, Any],
                            payloads: list[dict[str, Any]], cache_dir: str):
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
        if key not in payload_index or source["length"] != payload["length"]:
            raise ValueError(f"{arm}: staging mapping does not cover an observed SET_TENSOR payload")
        if source.get("sha256") != payload.get("sha256"):
            raise ValueError(f"{arm}: staged payload digest differs from verified backing range")
        if staged.get("sha256_before") != payload["sha256"] or staged.get("sha256_after") != payload["sha256"]:
            raise ValueError(f"{arm}: cache content was not SHA-256 verified before and after use")
        if staged.get("length_before") != payload["length"] or staged.get("length_after") != payload["length"]:
            raise ValueError(f"{arm}: cache length differs from SET_TENSOR payload")
        if not isinstance(staged.get("path"), str) or not staged.get("path"):
            raise ValueError(f"{arm}: cache path missing")
        if not staged["path"].startswith(cache_dir.rstrip("/") + "/"):
            raise ValueError(f"{arm}: staged cache path escapes its private cache directory")
        if Path(staged["path"]).name != payload.get("fnv1a_cache_key"):
            raise ValueError(f"{arm}: cache filename is not the payload's FNV-1a key")
        # A raw staging receipt binds the adapter's atomic write/re-read to
        # this mapping. Its raw file itself is checksum-bound above.
        receipt = _read_receipt(base, staged.get("receipt", {}), arm, "cache staging")
        if receipt.get("schema") != "inferswarm.issue200.cache-staging-receipt/1":
            raise ValueError(f"{arm}: cache staging receipt schema")
        if receipt.get("atomic_publish") is not True or receipt.get("cache_sha256") != payload["sha256"]:
            raise ValueError(f"{arm}: cache staging receipt lacks atomic SHA-256 verification")
        payload_path = receipt.get("payload_path")
        if not isinstance(payload_path, str):
            raise ValueError(f"{arm}: raw SET_TENSOR payload bytes must be retained")
        raw_path = (base / payload_path).resolve()
        if base.resolve() not in raw_path.parents or not raw_path.is_file():
            raise ValueError(f"{arm}: staged payload receipt path missing")
        raw_bytes = raw_path.read_bytes()
        if len(raw_bytes) != payload["length"] or _sha256(raw_bytes) != payload["sha256"]:
            raise ValueError(f"{arm}: raw staged payload bytes do not match mapping")
        if fnv1a64(raw_bytes) != payload.get("fnv1a_cache_key"):
            raise ValueError(f"{arm}: FNV cache filename does not match actual payload bytes")
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
        if len(participant_ids) != len(participants) or len(set(participant_ids)) != len(participant_ids):
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
        frozen = document.get("frozen")
        frozen_keys = ("required_state_identity", "participant_requirements_identity",
                       "placement_identity", "materialization_identity")
        if not isinstance(frozen, dict) or any(not isinstance(frozen.get(key), str) or not frozen[key]
                                               for key in frozen_keys):
            raise ValueError("frozen required-state/placement/materialization identities missing")
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
        private_cache_dirs = set()
        for name, arm in zip(ARMS, arm_docs):
            if arm.get("source_policy") != expected_policy[name] or arm.get("source_attribution") != expected_source[name]:
                raise ValueError(f"{name}: Source attribution/policy does not match arm")
            if arm.get("participants") != participant_ids:
                raise ValueError(f"{name}: participants do not match retained receipts")
            for key in frozen_keys:
                if arm.get(key) != frozen[key]:
                    raise ValueError(f"{name}: {key} differs from frozen identity")
            if not isinstance(arm.get("initialization_wall_time_ms"), (int, float)) or arm["initialization_wall_time_ms"] < 0:
                raise ValueError(f"{name}: initialization wall time missing")
            runtime_receipt = _read_receipt(
                evidence_root, arm.get("runtime_receipt", {}), name, "runtime/materialization")
            if runtime_receipt.get("participants") != participant_ids:
                raise ValueError(f"{name}: participants do not match runtime receipt")
            payloads = arm.get("set_tensor_payloads")
            if not isinstance(payloads, list) or not payloads:
                raise ValueError(f"{name}: actual SET_TENSOR payload boundaries missing")
            for payload in payloads:
                if (not isinstance(payload, dict) or not isinstance(payload.get("offset"), int)
                        or not isinstance(payload.get("length"), int) or payload["offset"] < 0
                        or payload["length"] <= 0 or not re.fullmatch(r"[0-9a-f]{64}", str(payload.get("sha256", "")))):
                    raise ValueError(f"{name}: malformed SET_TENSOR boundary")
            if (runtime_receipt.get("set_tensor_payloads") != payloads
                    or runtime_receipt.get("initialization_wall_time_ms") != arm["initialization_wall_time_ms"]
                    or any(runtime_receipt.get(key) != frozen[key] for key in frozen_keys)):
                raise ValueError(f"{name}: runtime receipt does not bind payload/timing/identity")
            local_reads = _read_receipt(
                evidence_root, arm.get("local_read_receipt", {}), name, "local durable/cache read")
            if local_reads.get("source_attribution") != expected_source[name]:
                raise ValueError(f"{name}: local durable/cache receipt lacks Source attribution")
            network[name] = _network_bytes(evidence_root, name, arm.get("network_receipt", {}), payloads)
            if network[name]["source_attribution"] != expected_source[name]:
                raise ValueError(f"{name}: network receipt lacks Source attribution")
            payload_identities.append([(p["offset"], p["length"], p["sha256"]) for p in payloads])
            if name != "cold_remote":
                cache_dir = arm.get("private_cache_dir")
                if not isinstance(cache_dir, str) or not cache_dir or cache_dir in private_cache_dirs:
                    raise ValueError(f"{name}: private fresh cache directory missing or reused")
                private_cache_dirs.add(cache_dir)
                cache_start = _read_receipt(
                    evidence_root, arm.get("cache_initialization_receipt", {}), name, "cache initialization")
                if (cache_start.get("schema") != "inferswarm.issue200.cache-initialization-receipt/1"
                        or cache_start.get("cache_dir") != cache_dir or cache_start.get("entries_before") != []):
                    raise ValueError(f"{name}: cache was not proven fresh/private before staging")
                _validate_stage_mapping(evidence_root, name, arm.get("cache_staging"), authority, payloads, cache_dir)
        if len({canonical_json_bytes(item) for item in payload_identities}) != 1:
            raise ValueError("actual SET_TENSOR payload boundaries differ across arms")
        if network["cold_remote"]["immutable_payload"] <= 0:
            raise ValueError("cold/remote arm did not move immutable model payload")
        if not network["cold_remote"]["payload_identities"]:
            raise ValueError("cold/remote arm did not bind transfer to selected payload boundaries")
        if network["local_verified"]["immutable_payload"] != 0:
            raise ValueError("local verified arm reacquired immutable payload")
        if network["repeat_local_verified"]["immutable_payload"] != 0:
            raise ValueError("repeat local verified arm reacquired immutable payload")
        return {"valid": True, "derived": {
            "accepted_model_authority": authority,
            "network": network,
            "payload_boundaries": payload_identities[0],
            "identities": frozen,
            "participants": participant_ids,
        }}
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        return {"valid": False, "reason": str(error)}
