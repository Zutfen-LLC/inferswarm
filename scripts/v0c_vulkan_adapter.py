#!/usr/bin/env python3
"""Issue #143 backend-local Vulkan participant adapter helpers.

The adapter owns backend-specific log parsing and turns a proven observation
into an opaque generic capability record. It never participates in generic
planning, and it fails closed when the selected physical device or full model
offload cannot be proven from the backend's own output.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping


class AdapterError(RuntimeError):
    """The backend observation cannot support a correctness-bearing result."""


_USING_DEVICE = re.compile(
    r"using device (?P<selector>\S+).*?\((?P<bdf>0000:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.\d)\)"
)
_OFFLOAD = re.compile(r"offloaded\s+(?P<done>\d+)\s*/\s*(?P<total>\d+)\s+layers\s+to\s+GPU")
_FALLBACK = re.compile(r"\b(?:falling\s+back|fallback|using\s+cpu|cpu\s+fallback)\b", re.IGNORECASE)
_OBSERVATION_SEAL = object()


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise AdapterError("identity facts must be canonical JSON values") from error


def _require_identity_fields(**fields: Any) -> None:
    if not all(isinstance(value, str) and value for value in fields.values()):
        raise AdapterError("capability identity fields must be nonempty strings")


def _runtime_identity_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise AdapterError("runtime identity is required")
    copied = deepcopy(dict(value))
    _canonical_bytes(copied)
    return copied


def _observation_facts(*, physical_device_bdf: str, backend_selector: str,
                       offloaded_layers: tuple[int, int], compute_unit_id: str,
                       memory_resource_id: str, execution_unit_id: str,
                       implementation_id: str, evidence_id: str, runtime_identity: Mapping[str, Any],
                       stderr_sha256: str) -> dict[str, Any]:
    return {
        "physical_device_bdf": physical_device_bdf,
        "backend_selector": backend_selector,
        "offloaded_layers": list(offloaded_layers),
        "bound_compute_unit_id": compute_unit_id,
        "bound_memory_resource_id": memory_resource_id,
        "bound_execution_unit_id": execution_unit_id,
        "implementation_id": implementation_id,
        "evidence_id": evidence_id,
        "runtime_identity": dict(runtime_identity),
        "stderr_sha256": stderr_sha256,
    }


@dataclass(frozen=True)
class BackendObservation:
    """An adapter-created, sealed proof of one full-offload backend observation."""

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
    _proof_digest: str
    _seal: object

    def facts(self) -> dict[str, Any]:
        """Return an auditable copy without exposing the adapter seal."""
        return {
            **_observation_facts(
                physical_device_bdf=self.physical_device_bdf,
                backend_selector=self.backend_selector,
                offloaded_layers=self.offloaded_layers,
                compute_unit_id=self.compute_unit_id,
                memory_resource_id=self.memory_resource_id,
                execution_unit_id=self.execution_unit_id,
                implementation_id=self.implementation_id,
                evidence_id=self.evidence_id,
                runtime_identity=self.runtime_identity,
                stderr_sha256=self.stderr_sha256,
            ),
            "full_offload": True,
        }


def _validate_observation(observation: Any) -> BackendObservation:
    if not isinstance(observation, BackendObservation) or observation._seal is not _OBSERVATION_SEAL:
        raise AdapterError("capability requires an adapter-validated observation")
    _require_identity_fields(
        compute_unit_id=observation.compute_unit_id,
        memory_resource_id=observation.memory_resource_id,
        execution_unit_id=observation.execution_unit_id,
        implementation_id=observation.implementation_id,
        evidence_id=observation.evidence_id,
        bdf=observation.physical_device_bdf,
        selector=observation.backend_selector,
        stderr_sha256=observation.stderr_sha256,
    )
    runtime_identity = _runtime_identity_copy(observation.runtime_identity)
    facts = _observation_facts(
        physical_device_bdf=observation.physical_device_bdf,
        backend_selector=observation.backend_selector,
        offloaded_layers=observation.offloaded_layers,
        compute_unit_id=observation.compute_unit_id,
        memory_resource_id=observation.memory_resource_id,
        execution_unit_id=observation.execution_unit_id,
        implementation_id=observation.implementation_id,
        evidence_id=observation.evidence_id,
        runtime_identity=runtime_identity,
        stderr_sha256=observation.stderr_sha256,
    )
    if (not isinstance(observation.offloaded_layers, tuple)
            or len(observation.offloaded_layers) != 2
            or any(isinstance(value, bool) or not isinstance(value, int)
                   for value in observation.offloaded_layers)
            or observation.offloaded_layers[0] <= 0
            or observation.offloaded_layers[0] != observation.offloaded_layers[1]
            or sha256(_canonical_bytes(facts)).hexdigest() != observation._proof_digest):
        raise AdapterError("observation proof is malformed or contradicted")
    return observation


def parse_backend_observation(*, stderr: str, selector: str, expected_bdf: str,
                              compute_unit_id: str, memory_resource_id: str,
                              execution_unit_id: str, implementation_id: str,
                              evidence_id: str,
                              runtime_identity: Mapping[str, Any]) -> BackendObservation:
    """Mechanically bind one full-offload backend proof to all capability identities."""
    _require_identity_fields(
        selector=selector, expected_bdf=expected_bdf, compute_unit_id=compute_unit_id,
        memory_resource_id=memory_resource_id, execution_unit_id=execution_unit_id,
        implementation_id=implementation_id, evidence_id=evidence_id,
    )
    if not isinstance(stderr, str) or not stderr:
        raise AdapterError("backend stderr observation is required")
    runtime = _runtime_identity_copy(runtime_identity)
    if _FALLBACK.search(stderr):
        raise AdapterError("backend reported fallback execution")
    selected = [match for line in stderr.splitlines() if (match := _USING_DEVICE.search(line))]
    if len(selected) != 1:
        raise AdapterError("backend selected-device proof missing or ambiguous")
    if selected[0].group("selector") != selector:
        raise AdapterError("backend selected a different backend device")
    observed_bdf = selected[0].group("bdf").removeprefix("0000:")
    if observed_bdf != expected_bdf:
        raise AdapterError("backend selected a different physical device")
    offloads = [match for match in _OFFLOAD.finditer(stderr)]
    if len(offloads) != 1:
        raise AdapterError("backend offload proof missing or ambiguous")
    done, total = (int(offloads[0].group("done")), int(offloads[0].group("total")))
    if total <= 0 or done != total:
        raise AdapterError("backend did not fully offload the declared model")
    stderr_sha256 = sha256(stderr.encode("utf-8")).hexdigest()
    facts = _observation_facts(
        physical_device_bdf=observed_bdf, backend_selector=selector,
        offloaded_layers=(done, total), compute_unit_id=compute_unit_id,
        memory_resource_id=memory_resource_id, execution_unit_id=execution_unit_id,
        implementation_id=implementation_id,
        evidence_id=evidence_id, runtime_identity=runtime, stderr_sha256=stderr_sha256,
    )
    return BackendObservation(
        physical_device_bdf=observed_bdf, backend_selector=selector,
        offloaded_layers=(done, total), compute_unit_id=compute_unit_id,
        memory_resource_id=memory_resource_id, execution_unit_id=execution_unit_id,
        implementation_id=implementation_id,
        evidence_id=evidence_id, runtime_identity=runtime, stderr_sha256=stderr_sha256,
        _proof_digest=sha256(_canonical_bytes(facts)).hexdigest(), _seal=_OBSERVATION_SEAL,
    )


def capability_record(*, compute_unit_id: str, memory_resource_id: str,
                      execution_unit_id: str, implementation_id: str,
                      evidence_id: str, bdf: str,
                      runtime_identity: Mapping[str, Any],
                      observation: BackendObservation) -> dict[str, Any]:
    """Create planner input only from an exactly matching adapter proof."""
    _require_identity_fields(
        compute_unit_id=compute_unit_id, memory_resource_id=memory_resource_id,
        execution_unit_id=execution_unit_id, implementation_id=implementation_id,
        evidence_id=evidence_id, bdf=bdf,
    )
    runtime = _runtime_identity_copy(runtime_identity)
    proven = _validate_observation(observation)
    expected = {
        "compute_unit_id": compute_unit_id,
        "memory_resource_id": memory_resource_id,
        "execution_unit_id": execution_unit_id,
        "implementation_id": implementation_id,
        "evidence_id": evidence_id,
        "physical_device_bdf": bdf,
        "runtime_identity": runtime,
    }
    actual = {
        "compute_unit_id": proven.compute_unit_id,
        "memory_resource_id": proven.memory_resource_id,
        "execution_unit_id": proven.execution_unit_id,
        "implementation_id": proven.implementation_id,
        "evidence_id": proven.evidence_id,
        "physical_device_bdf": proven.physical_device_bdf,
        "runtime_identity": _runtime_identity_copy(proven.runtime_identity),
    }
    if actual != expected:
        raise AdapterError("capability identity contradicts validated observation")
    return {
        "bound_compute_unit_id": compute_unit_id,
        "bound_memory_resource_id": memory_resource_id,
        "bound_execution_unit_id": execution_unit_id,
        "implementation_id": implementation_id,
        "evidence_id": evidence_id,
        "observation_evidence_id": proven.evidence_id,
        "observation_digest": proven._proof_digest,
        "physical_device_bdf": bdf,
        "runtime_identity": deepcopy(runtime),
    }
