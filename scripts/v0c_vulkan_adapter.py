#!/usr/bin/env python3
"""Issue #143 backend-local Vulkan participant adapter helpers.

The adapter owns backend-specific log parsing and turns a proven observation
into an opaque generic capability record. It never participates in generic
planning, and it fails closed when the selected physical device or full model
offload cannot be proven from the backend's own output.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping


class AdapterError(RuntimeError):
    """The backend observation cannot support a correctness-bearing result."""


_USING_DEVICE = re.compile(
    r"using device (?P<selector>\S+).*?\((?P<bdf>0000:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.\d)\)"
)
_OFFLOAD = re.compile(r"offloaded\s+(?P<done>\d+)\s*/\s*(?P<total>\d+)\s+layers\s+to\s+GPU")


def parse_backend_observation(*, stderr: str, selector: str,
                              expected_bdf: str) -> dict[str, Any]:
    """Extract and validate the backend's selected device and layer proof."""
    selected = []
    for line in stderr.splitlines():
        match = _USING_DEVICE.search(line)
        if match and match.group("selector") == selector:
            selected.append(match)
    if len(selected) != 1:
        raise AdapterError("backend selected-device proof missing or ambiguous")
    observed_bdf = selected[0].group("bdf").removeprefix("0000:")
    if observed_bdf != expected_bdf:
        raise AdapterError("backend selected a different physical device")
    offloads = [match for match in _OFFLOAD.finditer(stderr)]
    if len(offloads) != 1:
        raise AdapterError("backend offload proof missing or ambiguous")
    done, total = (int(offloads[0].group("done")), int(offloads[0].group("total")))
    if total <= 0 or done != total:
        raise AdapterError("backend did not fully offload the declared model")
    return {"physical_device_bdf": observed_bdf, "backend_selector": selector,
            "offloaded_layers": [done, total], "full_offload": True}


def capability_record(*, compute_unit_id: str, implementation_id: str,
                      evidence_id: str, bdf: str,
                      runtime_identity: Mapping[str, Any]) -> dict[str, Any]:
    """Create generic planner input from backend-local facts.

    The physical binding is explicit. Backend identification remains an opaque
    implementation identifier to the generic planner.
    """
    if not all(isinstance(value, str) and value for value in
               (compute_unit_id, implementation_id, evidence_id, bdf)):
        raise AdapterError("capability identity fields must be nonempty strings")
    if not runtime_identity:
        raise AdapterError("runtime identity is required")
    return {"bound_compute_unit_id": compute_unit_id,
            "implementation_id": implementation_id,
            "evidence_id": evidence_id,
            "physical_device_bdf": bdf,
            "runtime_identity": deepcopy(dict(runtime_identity))}
