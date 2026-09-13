#!/usr/bin/env python3
"""Issue #154 backend-local adapter proof binding.

The adapter is the only component with backend/vendor awareness. It parses
raw runtime output, rejects fallback or incomplete offload, validates the
selected physical device, and seals opaque proof capsules. Every sealed
capsule binds the execution contract: a qualification observation sealed
for contract A can never be enriched into a contract-B capability, and a
canonical proof sealed under contract A can never satisfy a contract-B
plan.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping

import v1a_execution_participant as participant


class AdapterError(RuntimeError):
    """Runtime output cannot establish a correctness-bearing observation."""


_DEVICE = re.compile(r"using device (?P<selector>\S+).*?\((?P<bdf>0000:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.\d)\)")
_OFFLOAD = re.compile(r"offloaded\s+(?P<done>\d+)\s*/\s*(?P<total>\d+)\s+layers\s+to\s+GPU")
_FALLBACK = re.compile(r"\b(?:falling\s+back|fallback|using\s+cpu|cpu\s+fallback)\b", re.I)
_SEAL = object()


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise AdapterError("identity facts must be canonical") from error


def _digest(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _runtime(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise AdapterError("runtime identity is required")
    result = deepcopy(dict(value))
    _canonical(result)
    return result


@dataclass(frozen=True)
class BackendObservation:
    node_id: str
    physical_device_bdf: str
    backend_selector: str
    offloaded_layers: tuple[int, int]
    compute_unit_id: str
    memory_resource_id: str
    execution_unit_id: str
    execution_contract_id: str
    implementation_id: str
    evidence_id: str
    runtime_identity: dict[str, Any]
    stderr_sha256: str
    proof_digest: str
    seal: object


def _observation_facts(observation: BackendObservation) -> dict[str, Any]:
    return {"node_id": observation.node_id, "physical_device_bdf": observation.physical_device_bdf,
            "backend_selector": observation.backend_selector, "offloaded_layers": list(observation.offloaded_layers),
            "compute_unit_id": observation.compute_unit_id, "memory_resource_id": observation.memory_resource_id,
            "execution_unit_id": observation.execution_unit_id,
            "execution_contract_id": observation.execution_contract_id,
            "implementation_id": observation.implementation_id,
            "evidence_id": observation.evidence_id, "runtime_identity": observation.runtime_identity,
            "stderr_sha256": observation.stderr_sha256}


def _validate_observation(observation: Any) -> BackendObservation:
    if not isinstance(observation, BackendObservation) or observation.seal is not _SEAL:
        raise AdapterError("adapter-validated observation is required")
    facts = _observation_facts(observation)
    if not _text(observation.execution_contract_id):
        raise AdapterError("sealed observation does not bind an execution contract")
    if _digest(facts) != observation.proof_digest:
        raise AdapterError("adapter observation is altered")
    done, total = observation.offloaded_layers
    if total <= 0 or done != total:
        raise AdapterError("runtime did not fully offload the model")
    return observation


def parse_backend_observation(*, stderr: str, selector: str, expected_bdf: str, node_id: str,
                              compute_unit_id: str, memory_resource_id: str, execution_unit_id: str,
                              execution_contract_id: str, implementation_id: str, evidence_id: str,
                              runtime_identity: Mapping[str, Any]) -> BackendObservation:
    """Parse one unambiguous selected-device and complete-offload observation.

    The execution contract is a required sealed identity: the observation
    proves the runtime run performed under exactly this contract, so the
    contract cannot be attached or replaced later by record enrichment.
    """
    if not isinstance(stderr, str) or not stderr or not all(_text(x) for x in (
            selector, expected_bdf, node_id, compute_unit_id, memory_resource_id,
            execution_unit_id, execution_contract_id, implementation_id, evidence_id)):
        raise AdapterError("required observation identity is missing")
    runtime = _runtime(runtime_identity)
    if _FALLBACK.search(stderr):
        raise AdapterError("runtime reported fallback")
    devices, offloads = list(_DEVICE.finditer(stderr)), list(_OFFLOAD.finditer(stderr))
    if len(devices) != 1 or len(offloads) != 1:
        raise AdapterError("selected-device or offload proof missing or ambiguous")
    device, offload = devices[0], offloads[0]
    observed_bdf = device.group("bdf").removeprefix("0000:")
    done, total = int(offload.group("done")), int(offload.group("total"))
    if device.group("selector") != selector or observed_bdf != expected_bdf:
        raise AdapterError("runtime physical identity differs from requested identity")
    if total <= 0 or done != total:
        raise AdapterError("runtime did not fully offload the model")
    facts = {"node_id": node_id, "physical_device_bdf": observed_bdf, "backend_selector": selector,
             "offloaded_layers": [done, total], "compute_unit_id": compute_unit_id,
             "memory_resource_id": memory_resource_id, "execution_unit_id": execution_unit_id,
             "execution_contract_id": execution_contract_id, "implementation_id": implementation_id,
             "evidence_id": evidence_id,
             "runtime_identity": runtime, "stderr_sha256": sha256(stderr.encode()).hexdigest()}
    return BackendObservation(**{key: value for key, value in facts.items() if key != "offloaded_layers"},
                              offloaded_layers=(done, total),
                              proof_digest=_digest(facts), seal=_SEAL)


def capability_record(*, node_id: str, compute_unit_id: str, memory_resource_id: str,
                      execution_unit_id: str, execution_contract_id: str, implementation_id: str,
                      evidence_id: str, bdf: str, runtime_identity: Mapping[str, Any],
                      observation: BackendObservation) -> dict[str, Any]:
    """Convert only exactly matching sealed observations into capability facts.

    The expected execution-contract ID must be supplied and must equal the
    contract sealed inside the observation; a mismatch fails closed, so a
    valid contract-A observation can never mint a contract-B capability.
    """
    observation = _validate_observation(observation)
    runtime = _runtime(runtime_identity)
    expected = (node_id, compute_unit_id, memory_resource_id, execution_unit_id,
                execution_contract_id, implementation_id, evidence_id, bdf, runtime)
    actual = (observation.node_id, observation.compute_unit_id, observation.memory_resource_id,
              observation.execution_unit_id, observation.execution_contract_id,
              observation.implementation_id, observation.evidence_id,
              observation.physical_device_bdf, observation.runtime_identity)
    if expected != actual:
        raise AdapterError("capability inputs contradict sealed observation")
    return {"bound_node_id": node_id, "bound_compute_unit_id": compute_unit_id,
            "bound_memory_resource_id": memory_resource_id, "bound_execution_unit_id": execution_unit_id,
            "execution_contract_id": observation.execution_contract_id,
            "implementation_id": implementation_id, "evidence_id": evidence_id,
            "qualification_evidence_id": evidence_id, "qualification_digest": observation.proof_digest,
            "physical_device_bdf": bdf, "runtime_identity": deepcopy(runtime), "full_offload": True}


def seal_canonical_execution_proof(*, observation: BackendObservation, plan_digest: str, candidate_id: str,
                                   execution_contract_id: str, execution_evidence_id: str, stdout: bytes,
                                   stderr: str, exit_code: int) -> participant.AdapterCanonicalExecutionProof:
    """Seal canonical output only after adapter validation of the raw runtime observation.

    The canonical proof inherits the execution contract sealed in the
    adapter-validated observation; a caller-supplied contract that differs
    from the sealed contract fails closed.
    """
    observation = _validate_observation(observation)
    if not all(_text(value) for value in (plan_digest, candidate_id, execution_contract_id,
                                          execution_evidence_id)):
        raise AdapterError("canonical plan/candidate/contract/evidence identity is missing")
    if execution_contract_id != observation.execution_contract_id:
        raise AdapterError("canonical contract differs from sealed observation contract")
    if not isinstance(stdout, bytes) or not isinstance(stderr, str) or exit_code != 0:
        raise AdapterError("canonical runtime did not exit cleanly")
    if sha256(stderr.encode()).hexdigest() != observation.stderr_sha256:
        raise AdapterError("canonical stderr differs from validated observation")
    facts = {"plan_digest": plan_digest, "candidate_id": candidate_id, "node_id": observation.node_id,
             "compute_unit_id": observation.compute_unit_id, "memory_resource_id": observation.memory_resource_id,
             "execution_unit_id": observation.execution_unit_id,
             "execution_contract_id": observation.execution_contract_id,
             "implementation_id": observation.implementation_id, "evidence_id": observation.evidence_id,
             "physical_device_bdf": observation.physical_device_bdf,
             "runtime_identity": deepcopy(observation.runtime_identity), "execution_evidence_id": execution_evidence_id,
             "stdout_sha256": sha256(stdout).hexdigest(), "stderr_sha256": observation.stderr_sha256,
             "backend_observation_digest": observation.proof_digest}
    return participant._adapter_canonical_proof(facts=facts)


def validate_canonical_execution_proof(proof: Any) -> None:
    """Validate the opaque proof digest before adapter consumers trust it."""
    try:
        participant._validate_adapter_canonical_proof(proof)
    except participant.ParticipantError as error:
        raise AdapterError(str(error)) from error
