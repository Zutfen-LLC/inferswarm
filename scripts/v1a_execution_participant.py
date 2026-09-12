#!/usr/bin/env python3
"""Issue #154 generic internal execution-participant control-plane seam."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


class ParticipantError(RuntimeError):
    """A required internal participant invariant was not satisfied."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise ParticipantError("identity facts must be canonical JSON") from error


def _digest(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _candidate_id(unit: Mapping[str, Any], resource: Mapping[str, Any],
                  capability: Mapping[str, Any]) -> str:
    memory = resource.get("memory_resource", {})
    return "candidate-" + _digest({
        "node_id": resource.get("node_id"),
        "execution_unit_id": unit.get("execution_unit_id"),
        "execution_contract_id": unit.get("execution_contract_id"),
        "compute_unit_id": resource.get("compute_unit_id"),
        "memory_resource_id": memory.get("memory_resource_id"),
        "physical_device_bdf": capability.get("physical_device_bdf"),
        "implementation_id": capability.get("implementation_id"),
        "qualification_evidence_id": capability.get("qualification_evidence_id"),
        "qualification_digest": capability.get("qualification_digest"),
        "runtime_identity": capability.get("runtime_identity"),
    })


def _eligibility(unit: Mapping[str, Any], resource: Mapping[str, Any],
                 capability: Mapping[str, Any]) -> str | None:
    memory = resource.get("memory_resource", {})
    if not _nonempty(resource.get("node_id")):
        return "NODE_IDENTITY_MISSING"
    if capability.get("bound_node_id") != resource.get("node_id"):
        return "CAPABILITY_NODE_BINDING_MISMATCH"
    if capability.get("execution_contract_id") != unit.get("execution_contract_id"):
        return "EXECUTION_CONTRACT_UNSUPPORTED"
    if capability.get("bound_compute_unit_id") != resource.get("compute_unit_id"):
        return "CAPABILITY_COMPUTE_UNIT_BINDING_MISMATCH"
    if capability.get("bound_memory_resource_id") != memory.get("memory_resource_id"):
        return "CAPABILITY_MEMORY_RESOURCE_BINDING_MISMATCH"
    if capability.get("bound_execution_unit_id") != unit.get("execution_unit_id"):
        return "CAPABILITY_EXECUTION_UNIT_BINDING_MISMATCH"
    if not _nonempty(resource.get("physical_device_bdf")) or not _nonempty(capability.get("physical_device_bdf")):
        return "PHYSICAL_IDENTITY_MISSING"
    if capability.get("physical_device_bdf") != resource.get("physical_device_bdf"):
        return "CAPABILITY_PHYSICAL_IDENTITY_MISMATCH"
    if not all(_nonempty(capability.get(key)) for key in ("implementation_id", "evidence_id")):
        return "CAPABILITY_IDENTITY_MISSING"
    if not all(_nonempty(capability.get(key)) for key in ("qualification_evidence_id", "qualification_digest")):
        return "QUALIFICATION_EVIDENCE_MISSING"
    if not isinstance(capability.get("runtime_identity"), Mapping) or not capability["runtime_identity"]:
        return "CAPABILITY_RUNTIME_IDENTITY_MISSING"
    _canonical(dict(capability["runtime_identity"]))
    if not capability.get("evidence_fresh", False):
        return "EVIDENCE_STALE"
    if capability.get("integrity_status") != unit.get("required_integrity_status"):
        return "CORRECTNESS_TRUST_INSUFFICIENT"
    if unit.get("required_representation") not in capability.get("representations", []):
        return "REPRESENTATION_UNSUPPORTED"
    if not set(unit.get("required_features", [])).issubset(capability.get("required_features", [])):
        return "REQUIRED_CAPABILITY_MISSING"
    required = unit.get("required_memory_bytes", 0) + unit.get("required_headroom_bytes", 0)
    if not isinstance(required, int) or isinstance(required, bool) or memory.get("bytes", 0) < required:
        return "MEMORY_HEADROOM_INSUFFICIENT"
    return None


def plan_execution_unit(*, execution_unit: Mapping[str, Any],
                        compute_units: Sequence[Mapping[str, Any]], objective: str) -> dict[str, Any]:
    """Apply generic eligibility, deterministic ranking, and explanations."""
    if objective != "MIN_OBJECTIVE_VALUE":
        raise ParticipantError("unsupported objective")
    rows: list[dict[str, Any]] = []
    for resource in compute_units:
        for capability in resource.get("capabilities", []):
            memory = resource.get("memory_resource", {})
            candidate = {
                "candidate_id": _candidate_id(execution_unit, resource, capability),
                "node_id": resource.get("node_id"), "compute_unit_id": resource.get("compute_unit_id"),
                "memory_resource_id": memory.get("memory_resource_id"),
                "execution_unit_id": execution_unit.get("execution_unit_id"),
                "execution_contract_id": execution_unit.get("execution_contract_id"),
                "implementation_id": capability.get("implementation_id"), "evidence_id": capability.get("evidence_id"),
                "qualification_evidence_id": capability.get("qualification_evidence_id"),
                "qualification_digest": capability.get("qualification_digest"),
                "physical_device_bdf": capability.get("physical_device_bdf"),
                "runtime_identity": deepcopy(capability.get("runtime_identity")),
            }
            reason = _eligibility(execution_unit, resource, capability)
            value = capability.get("economics", {}).get("objective_value") if reason is None else None
            if reason is None and (not isinstance(value, (int, float)) or isinstance(value, bool)
                                   or not math.isfinite(value) or value < 0):
                reason = "ECONOMICS_MISSING"
            rows.append({"candidate": candidate, "reason": reason, "ranking_value": value})
    ranked = sorted((r for r in rows if r["reason"] is None), key=lambda r: (r["ranking_value"], r["candidate"]["candidate_id"]))
    selected = deepcopy(ranked[0]["candidate"]) if ranked else None
    selected_id = selected["candidate_id"] if selected else None
    explanations = []
    for row in sorted(rows, key=lambda r: r["candidate"]["candidate_id"]):
        disposition, reason = ("EXCLUDED", row["reason"]) if row["reason"] else (("SELECTED", "SELECTED_BY_OBJECTIVE") if row["candidate"]["candidate_id"] == selected_id else ("LOWER_RANKED", "LOWER_RANKED_BY_OBJECTIVE"))
        explanations.append({"candidate_id": row["candidate"]["candidate_id"], "disposition": disposition, "reason": reason})
    return {"schema": "inferswarm.v1a.internal-plan/1", "objective": objective, "selected_candidate": selected,
            "selected_candidate_id": selected_id, "candidates": [{**deepcopy(row["candidate"]), "reason": row["reason"], "ranking_value": row["ranking_value"]} for row in rows], "explanations": explanations}


def freeze_plan(*, decision: Mapping[str, Any], execution_unit: Mapping[str, Any]) -> dict[str, Any]:
    candidate = decision.get("selected_candidate")
    if not isinstance(candidate, Mapping):
        raise ParticipantError("cannot freeze without a selected candidate")
    body = {"schema": "inferswarm.v1a.internal-frozen-plan/1", "objective": decision.get("objective"), "execution_unit": deepcopy(dict(execution_unit)), "candidate": deepcopy(dict(candidate))}
    return {**body, "plan_digest": _digest(body)}


def validate_frozen_plan(plan: Mapping[str, Any]) -> None:
    required = {"schema", "objective", "execution_unit", "candidate", "plan_digest"}
    if set(plan) != required or plan.get("schema") != "inferswarm.v1a.internal-frozen-plan/1":
        raise ParticipantError("malformed frozen plan")
    body = {key: plan[key] for key in required - {"plan_digest"}}
    if _digest(body) != plan["plan_digest"]:
        raise ParticipantError("frozen plan digest mismatch")
    unit, candidate = plan["execution_unit"], plan["candidate"]
    fields = ("candidate_id", "node_id", "compute_unit_id", "memory_resource_id", "execution_unit_id", "execution_contract_id", "implementation_id", "evidence_id", "qualification_evidence_id", "qualification_digest", "physical_device_bdf")
    if not all(_nonempty(candidate.get(key)) for key in fields):
        raise ParticipantError("frozen candidate identity incomplete")
    if candidate.get("execution_unit_id") != unit.get("execution_unit_id") or candidate.get("execution_contract_id") != unit.get("execution_contract_id"):
        raise ParticipantError("frozen candidate contradicts execution unit")
    _canonical(candidate.get("runtime_identity"))
    reconstructed = _candidate_id(unit, {"node_id": candidate["node_id"], "compute_unit_id": candidate["compute_unit_id"], "memory_resource": {"memory_resource_id": candidate["memory_resource_id"]}}, candidate)
    if reconstructed != candidate["candidate_id"]:
        raise ParticipantError("frozen candidate identity digest mismatch")


_PROOF_SEAL = object()


@dataclass(frozen=True)
class AdapterCanonicalExecutionProof:
    """Opaque adapter-validated canonical runtime identity capsule."""
    plan_digest: str
    candidate_id: str
    node_id: str
    compute_unit_id: str
    memory_resource_id: str
    execution_unit_id: str
    implementation_id: str
    evidence_id: str
    physical_device_bdf: str
    runtime_identity: dict[str, Any]
    execution_evidence_id: str
    stdout_sha256: str
    stderr_sha256: str
    backend_observation_digest: str
    proof_digest: str
    seal: object


def _adapter_canonical_proof(*, facts: Mapping[str, Any]) -> AdapterCanonicalExecutionProof:
    """Internal factory used only after a backend adapter validates runtime facts."""
    body = deepcopy(dict(facts))
    if not all(_nonempty(body.get(key)) for key in ("plan_digest", "candidate_id", "node_id", "compute_unit_id", "memory_resource_id", "execution_unit_id", "implementation_id", "evidence_id", "physical_device_bdf", "execution_evidence_id", "stdout_sha256", "stderr_sha256", "backend_observation_digest")):
        raise ParticipantError("adapter canonical proof identity incomplete")
    if not isinstance(body.get("runtime_identity"), Mapping):
        raise ParticipantError("adapter canonical proof runtime identity missing")
    digest = _digest(body)
    return AdapterCanonicalExecutionProof(**body, proof_digest=digest, seal=_PROOF_SEAL)


def _validate_adapter_canonical_proof(proof: Any) -> None:
    if not isinstance(proof, AdapterCanonicalExecutionProof) or proof.seal is not _PROOF_SEAL:
        raise ParticipantError("adapter-sealed canonical proof required")
    body = {key: getattr(proof, key) for key in proof.__dataclass_fields__ if key not in {"proof_digest", "seal"}}
    if _digest(body) != proof.proof_digest:
        raise ParticipantError("adapter canonical proof is altered")


def execution_receipt(*, plan: Mapping[str, Any], output: bytes, canonical_proof: Any) -> dict[str, Any]:
    """Mint result attribution only from a matching adapter-sealed proof."""
    validate_frozen_plan(plan)
    _validate_adapter_canonical_proof(canonical_proof)
    candidate = plan["candidate"]
    fields = ("plan_digest", "candidate_id", "node_id", "compute_unit_id", "memory_resource_id", "execution_unit_id", "implementation_id", "evidence_id", "physical_device_bdf", "runtime_identity")
    expected = {"plan_digest": plan["plan_digest"], **{key: candidate[key] for key in fields if key != "plan_digest"}}
    if any(getattr(canonical_proof, key) != value for key, value in expected.items()):
        raise ParticipantError("canonical proof does not match frozen plan")
    return {"plan_digest": plan["plan_digest"], "candidate_id": candidate["candidate_id"], "canonical_proof_digest": canonical_proof.proof_digest, "output_sha256": sha256(output).hexdigest()}


def source_token_audit(path: Path, forbidden_tokens: Sequence[str]) -> dict[str, list[str]]:
    text = path.read_text(encoding="utf-8").lower()
    return {"matches": sorted(token for token in forbidden_tokens if token.lower() in text)}
