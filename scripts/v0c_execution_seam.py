#!/usr/bin/env python3
"""Issue #143 generic S2 planning, plan freezing, and execution accounting.

This is deliberately a CPU-only control-plane module. A participant adapter
collects its own implementation identity and physical observations, converts
them to the generic records accepted here, and performs any accelerator work
outside this module. The planner therefore only consumes opaque capability,
representation, integrity, evidence, and economics facts.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


class SeamError(RuntimeError):
    """A fail-closed S2 seam validation failure."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _candidate_id(unit: Mapping[str, Any], compute_unit: Mapping[str, Any],
                  capability: Mapping[str, Any]) -> str:
    """Derive an unambiguous opaque identifier from structured identity facts."""
    memory = compute_unit.get("memory_resource", compute_unit)
    fields = {
        "execution_unit_id": unit.get("execution_unit_id"),
        "execution_contract_id": unit.get("execution_contract_id"),
        "compute_unit_id": compute_unit.get("compute_unit_id"),
        "memory_resource_id": memory.get("memory_resource_id"),
        "implementation_id": capability.get("implementation_id"),
        "evidence_id": capability.get("evidence_id"),
        "physical_device_bdf": capability.get("physical_device_bdf"),
        "runtime_identity": capability.get("runtime_identity"),
        "observation_evidence_id": capability.get("observation_evidence_id"),
        "observation_digest": capability.get("observation_digest"),
    }
    try:
        return f"candidate-{_digest(fields)}"
    except (TypeError, ValueError) as error:
        raise SeamError("candidate identity facts must be canonical") from error


def _eligibility(unit: Mapping[str, Any], compute_unit: Mapping[str, Any],
                 capability: Mapping[str, Any]) -> str | None:
    required_contract = unit.get("execution_contract_id")
    implemented_contract = capability.get("execution_contract_id")
    if (not isinstance(required_contract, str) or not required_contract
            or implemented_contract != required_contract):
        return "EXECUTION_CONTRACT_UNSUPPORTED"
    identity_fields = ("implementation_id", "evidence_id", "physical_device_bdf",
                       "observation_evidence_id", "observation_digest")
    if not all(isinstance(capability.get(field), str) and capability[field]
               for field in identity_fields):
        return "CAPABILITY_OBSERVATION_MISSING"
    if capability.get("bound_compute_unit_id") != compute_unit["compute_unit_id"]:
        return "CAPABILITY_DEVICE_BINDING_MISMATCH"
    memory = compute_unit.get("memory_resource", {})
    if capability.get("bound_memory_resource_id") != memory.get("memory_resource_id"):
        return "CAPABILITY_MEMORY_BINDING_MISMATCH"
    if capability.get("bound_execution_unit_id") != unit.get("execution_unit_id"):
        return "CAPABILITY_EXECUTION_UNIT_BINDING_MISMATCH"
    if capability.get("physical_device_bdf") != compute_unit.get("physical_device_bdf"):
        return "CAPABILITY_DEVICE_BINDING_MISMATCH"
    if capability.get("observation_evidence_id") != capability.get("evidence_id"):
        return "CAPABILITY_OBSERVATION_EVIDENCE_MISMATCH"
    observation_digest = capability.get("observation_digest")
    runtime_identity = capability.get("runtime_identity")
    if (not isinstance(observation_digest, str) or not observation_digest
            or not isinstance(runtime_identity, Mapping) or not runtime_identity):
        return "CAPABILITY_OBSERVATION_MISSING"
    try:
        _canonical_bytes(dict(runtime_identity))
    except (TypeError, ValueError):
        return "CAPABILITY_OBSERVATION_MISSING"
    if not capability.get("evidence_fresh", False):
        return "EVIDENCE_STALE"
    if capability.get("integrity_status") != unit["required_integrity_status"]:
        return "CORRECTNESS_TRUST_INSUFFICIENT"
    if unit["required_representation"] not in capability.get("representations", []):
        return "REPRESENTATION_UNSUPPORTED"
    available = set(capability.get("required_features", []))
    if not set(unit.get("required_features", [])).issubset(available):
        return "REQUIRED_CAPABILITY_MISSING"
    memory = compute_unit.get("memory_resource", {})
    required = unit["required_memory_bytes"] + unit["required_headroom_bytes"]
    if memory.get("bytes", 0) < required:
        return "MEMORY_HEADROOM_INSUFFICIENT"
    return None


def plan_execution_unit(*, execution_unit: Mapping[str, Any],
                        compute_units: Sequence[Mapping[str, Any]],
                        objective: str) -> dict[str, Any]:
    """Expose, gate, rank, and explain opaque unit implementations.

    The only supported objective is deliberately simple for this spike. It is
    an observed capability-economics field, not a hardware-class preference.
    """
    if objective != "MIN_STARTUP_SECONDS":
        raise SeamError(f"unsupported objective {objective!r}")
    rows: list[dict[str, Any]] = []
    for compute_unit in compute_units:
        for capability in compute_unit.get("capabilities", []):
            candidate = {
                "candidate_id": _candidate_id(execution_unit, compute_unit, capability),
                "execution_unit_id": execution_unit["execution_unit_id"],
                "execution_contract_id": execution_unit.get("execution_contract_id"),
                "compute_unit_id": compute_unit["compute_unit_id"],
                "memory_resource_id": compute_unit["memory_resource"]["memory_resource_id"],
                "implementation_id": capability.get("implementation_id"),
                "evidence_id": capability.get("evidence_id"),
                "physical_device_bdf": capability.get("physical_device_bdf"),
                "runtime_identity": deepcopy(capability.get("runtime_identity")),
                "observation_evidence_id": capability.get("observation_evidence_id"),
                "observation_digest": capability.get("observation_digest"),
                "required_representation": execution_unit["required_representation"],
            }
            reason = _eligibility(execution_unit, compute_unit, capability)
            economics = capability.get("economics", {})
            value = economics.get("startup_seconds") if reason is None else None
            if (reason is None and (not isinstance(value, (int, float))
                                   or isinstance(value, bool)
                                   or not math.isfinite(value)
                                   or value < 0)):
                reason = "ECONOMICS_MISSING"
            rows.append({"candidate": candidate, "reason": reason, "ranking_value": value})
    rankable = sorted((row for row in rows if row["reason"] is None),
                      key=lambda row: (row["ranking_value"], row["candidate"]["candidate_id"]))
    selected = rankable[0]["candidate"] if rankable else None
    selected_id = selected["candidate_id"] if selected else None
    explanations = []
    for row in sorted(rows, key=lambda row: row["candidate"]["candidate_id"]):
        if row["reason"] is not None:
            reason = row["reason"]
            disposition = "EXCLUDED"
        elif row["candidate"]["candidate_id"] == selected_id:
            reason = "SELECTED_BY_OBJECTIVE"
            disposition = "SELECTED"
        else:
            reason = "LOWER_RANKED_BY_OBJECTIVE"
            disposition = "LOWER_RANKED"
        explanations.append({"candidate_id": row["candidate"]["candidate_id"],
                             "disposition": disposition, "reason": reason})
    return {"schema": "inferswarm.v0c.generic-plan/1", "objective": objective,
            "selected_candidate_id": selected_id,
            "selected_candidate": deepcopy(selected),
            "explanations": explanations,
            "candidates": [{**deepcopy(row["candidate"]), "reason": row["reason"],
                            "ranking_value": row["ranking_value"]} for row in rows]}


def freeze_plan(*, decision: Mapping[str, Any], execution_unit: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze the selected generic decision before realization."""
    candidate = decision.get("selected_candidate")
    if not isinstance(candidate, Mapping):
        raise SeamError("cannot freeze a decision with no selected candidate")
    body = {"schema": "inferswarm.v0c.frozen-plan/1",
            "execution_unit": deepcopy(dict(execution_unit)),
            "candidate": deepcopy(dict(candidate)),
            "objective": decision.get("objective")}
    body["plan_digest"] = _digest(body)
    return body


def validate_frozen_plan(plan: Mapping[str, Any]) -> None:
    """Verify plan self-identity and minimum identity coherence."""
    required = {"schema", "execution_unit", "candidate", "objective", "plan_digest"}
    if set(plan) != required or plan.get("schema") != "inferswarm.v0c.frozen-plan/1":
        raise SeamError("malformed frozen plan")
    body = {key: deepcopy(plan[key]) for key in required if key != "plan_digest"}
    if _digest(body) != plan["plan_digest"]:
        raise SeamError("frozen plan identity mismatch")
    unit = plan["execution_unit"]
    candidate = plan["candidate"]
    scalar_fields = ("execution_unit_id", "execution_contract_id", "compute_unit_id", "memory_resource_id",
                     "implementation_id", "evidence_id", "physical_device_bdf",
                     "observation_evidence_id", "observation_digest")
    if (not all(isinstance(candidate.get(field), str) and candidate[field]
                for field in scalar_fields)
            or not isinstance(candidate.get("runtime_identity"), Mapping)
            or not candidate["runtime_identity"]):
        raise SeamError("candidate proof identity is incomplete")
    try:
        _canonical_bytes(dict(candidate["runtime_identity"]))
    except (TypeError, ValueError) as error:
        raise SeamError("candidate runtime identity is not canonical") from error
    if candidate.get("execution_unit_id") != unit.get("execution_unit_id"):
        raise SeamError("candidate execution unit differs from frozen plan")
    if candidate.get("execution_contract_id") != unit.get("execution_contract_id"):
        raise SeamError("candidate execution contract differs from frozen plan")
    expected_id = _candidate_id(
        unit,
        {"compute_unit_id": candidate.get("compute_unit_id"),
         "memory_resource_id": candidate.get("memory_resource_id")},
        {"implementation_id": candidate.get("implementation_id"),
         "evidence_id": candidate.get("evidence_id"),
         "physical_device_bdf": candidate.get("physical_device_bdf"),
         "runtime_identity": candidate.get("runtime_identity"),
         "observation_evidence_id": candidate.get("observation_evidence_id"),
         "observation_digest": candidate.get("observation_digest")},
    )
    if candidate.get("candidate_id") != expected_id:
        raise SeamError("candidate does not belong to frozen execution unit")


def expected_materialization(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Return the sole planned residency/accounting record for realization."""
    validate_frozen_plan(plan)
    unit = plan["execution_unit"]
    candidate = plan["candidate"]
    return {
        "plan_digest": plan["plan_digest"],
        "compute_unit_id": candidate["compute_unit_id"],
        "memory_resource_id": candidate["memory_resource_id"],
        "representation": unit["required_representation"],
        "resident_model_bytes": unit["required_memory_bytes"],
        "reserved_headroom_bytes": unit["required_headroom_bytes"],
        "unexplained_persistent_host_mirror_bytes": 0,
        "source_fetches_after_ready": 0,
        "unplanned_state_movements": 0,
    }


def reconcile_materialization(plan: Mapping[str, Any], observed: Mapping[str, Any]) -> dict[str, Any]:
    """Reject observation that differs from the planned residency contract."""
    expected = expected_materialization(plan)
    if dict(observed) != expected:
        differences = sorted(key for key in set(expected) | set(observed)
                             if expected.get(key) != observed.get(key))
        raise SeamError(f"materialization reconciliation failed: {differences}")
    return {"clean": True, "expected": expected, "observed": deepcopy(dict(observed))}


def execution_receipt(plan: Mapping[str, Any], *, output: bytes,
                      observed_execution: Mapping[str, Any]) -> dict[str, Any]:
    """Attribute a result only to the exact proof-bearing frozen candidate."""
    validate_frozen_plan(plan)
    candidate = plan["candidate"]
    required = ("compute_unit_id", "memory_resource_id", "execution_unit_id",
                "physical_device_bdf", "runtime_identity", "implementation_id",
                "evidence_id", "observation_evidence_id", "observation_digest")
    expected = {field: candidate[field] for field in required}
    if dict(observed_execution) != expected:
        differences = sorted(field for field in set(expected) | set(observed_execution)
                             if expected.get(field) != observed_execution.get(field))
        raise SeamError(f"execution attribution differs from frozen plan: {differences}")
    return {"plan_digest": plan["plan_digest"],
            **deepcopy(expected),
            "output_sha256": sha256(output).hexdigest()}


def planner_purity_audit(path: Path, forbidden_tokens: Sequence[str]) -> dict[str, Any]:
    """Audit the planner implementation without embedding product nouns here."""
    text = path.read_text(encoding="utf-8").lower()
    matches = sorted(token for token in forbidden_tokens if token.lower() in text)
    return {"matches": matches}
