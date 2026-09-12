#!/usr/bin/env python3
"""Issue #154 backend-local adapter proof binding.

This CPU-only helper parses backend runtime diagnostics and seals their physical
identity/full-offload proof to opaque internal participant inputs.  It is not a
planner surface.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping


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
    physical_device_bdf: str
    backend_selector: str
    offloaded_layers: tuple[int, int]
    compute_unit_id: str
    memory_resource_id: str
    execution_unit_id: str
    implementation_id: str
    evidence_id: str
    runtime_identity: dict[str, Any]
    stderr_sha256: str
    proof_digest: str
    seal: object


def parse_backend_observation(*, stderr: str, selector: str, expected_bdf: str,
                              compute_unit_id: str, memory_resource_id: str,
                              execution_unit_id: str, implementation_id: str,
                              evidence_id: str, runtime_identity: Mapping[str, Any]) -> BackendObservation:
    """Parse one unambiguous selected-device and complete-offload observation."""
    if not isinstance(stderr, str) or not stderr or not all(_text(x) for x in (
            selector, expected_bdf, compute_unit_id, memory_resource_id, execution_unit_id,
            implementation_id, evidence_id)):
        raise AdapterError("required observation identity is missing")
    runtime = _runtime(runtime_identity)
    if _FALLBACK.search(stderr):
        raise AdapterError("runtime reported fallback")
    devices = list(_DEVICE.finditer(stderr))
    offloads = list(_OFFLOAD.finditer(stderr))
    if len(devices) != 1 or len(offloads) != 1:
        raise AdapterError("selected-device or offload proof missing or ambiguous")
    device, offload = devices[0], offloads[0]
    observed_bdf = device.group("bdf").removeprefix("0000:")
    done, total = int(offload.group("done")), int(offload.group("total"))
    if device.group("selector") != selector or observed_bdf != expected_bdf:
        raise AdapterError("runtime physical identity differs from requested identity")
    if total <= 0 or done != total:
        raise AdapterError("runtime did not fully offload the model")
    facts = {"physical_device_bdf": observed_bdf, "backend_selector": selector,
             "offloaded_layers": [done, total], "compute_unit_id": compute_unit_id,
             "memory_resource_id": memory_resource_id, "execution_unit_id": execution_unit_id,
             "implementation_id": implementation_id, "evidence_id": evidence_id,
             "runtime_identity": runtime, "stderr_sha256": sha256(stderr.encode()).hexdigest()}
    return BackendObservation(physical_device_bdf=observed_bdf, backend_selector=selector,
        offloaded_layers=(done, total), compute_unit_id=compute_unit_id,
        memory_resource_id=memory_resource_id, execution_unit_id=execution_unit_id,
        implementation_id=implementation_id, evidence_id=evidence_id, runtime_identity=runtime,
        stderr_sha256=facts["stderr_sha256"], proof_digest=sha256(_canonical(facts)).hexdigest(), seal=_SEAL)


def capability_record(*, compute_unit_id: str, memory_resource_id: str,
                      execution_unit_id: str, implementation_id: str, evidence_id: str,
                      bdf: str, runtime_identity: Mapping[str, Any], observation: BackendObservation) -> dict[str, Any]:
    """Convert only exactly matching sealed observations into capability facts."""
    if not isinstance(observation, BackendObservation) or observation.seal is not _SEAL:
        raise AdapterError("adapter-validated observation is required")
    runtime = _runtime(runtime_identity)
    expected = (compute_unit_id, memory_resource_id, execution_unit_id, implementation_id, evidence_id, bdf, runtime)
    actual = (observation.compute_unit_id, observation.memory_resource_id, observation.execution_unit_id,
              observation.implementation_id, observation.evidence_id, observation.physical_device_bdf,
              observation.runtime_identity)
    if expected != actual:
        raise AdapterError("capability inputs contradict sealed observation")
    return {"bound_compute_unit_id": compute_unit_id, "bound_memory_resource_id": memory_resource_id,
            "bound_execution_unit_id": execution_unit_id, "implementation_id": implementation_id,
            "evidence_id": evidence_id, "qualification_evidence_id": evidence_id,
            "qualification_digest": observation.proof_digest, "physical_device_bdf": bdf,
            "runtime_identity": deepcopy(runtime), "full_offload": True}
