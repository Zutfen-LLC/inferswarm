"""Deterministic CPU strategy and independent reference for issue #101."""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from issue99_artifact_core import (
    REQUIREMENT_CLASSES, derive_participant_requirements, digest_of_bytes,
    freeze_artifact_record, self_digest, validate_self_identity,
)

MODEL = {"model_id": "issue101/integer-polynomial", "revision": "fixture-v1",
         "representation": "little-endian-int32"}
REFERENCE = {1: 23, 2: 29}


class Fixture:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        data = struct.pack("<6i", 1, 2, 3, 4, 5, 6)
        (root / "coefficients.bin").write_bytes(data)
        self.records = {}
        for number in range(1, 7):
            start = (number - 1) * 4
            self.records[number] = freeze_artifact_record(
                kind="byte_range", content=data[start:start + 4],
                model_id=MODEL["model_id"], revision=MODEL["revision"],
                representation=MODEL["representation"],
                satisfies_logical_state_ids=[f"coefficient.{number}"],
                requirement_class="assigned_logical_state",
                origin={"source_object": "coefficients.bin",
                        "source_object_digest": digest_of_bytes(data),
                        "source_object_length": len(data),
                        "byte_start": start, "byte_end": start + 4})
        self.identity = {"model": MODEL, "upstream_digest": digest_of_bytes(data),
                         "upstream_bytes": len(data), "records": list(self.records.values()),
                         "reference_outputs": REFERENCE}

    def resolve(self, requirement_class: str, state_id: str):
        return [record for record in self.records.values()
                if record["requirement_class"] == requirement_class
                and state_id in record["satisfies_logical_state_ids"]]

    def plan(self, epoch: int, assignments: dict[str, list[int]]) -> dict[str, Any]:
        plan = {"epoch": epoch, "model": MODEL,
                "logical_state_units": [{"id": f"coefficient.{n}"} for n in range(1, 7)],
                "participants": [
                    {"participant_id": node, "node_id": node, "execution_unit_id": f"exec.{node}",
                     "required_state": {key: [f"coefficient.{n}" for n in numbers]
                                        if key == "assigned_logical_state" else []
                                        for key in REQUIREMENT_CLASSES}}
                    for node, numbers in assignments.items()]}
        plan["plan_digest"] = self_digest(plan, identity_field="plan_digest")
        return plan

    def requirements(self, plan):
        return derive_participant_requirements(plan, self.resolve)

    def seed(self, node, numbers):
        for number in numbers:
            record = self.records[number]
            node.cache.publish(record, struct.pack("<i", number))
            node.publish(record)


def execute(plan, participant, node, coordinator):
    """Materialize from verified cache and compare with a worked reference."""
    validate_self_identity(plan, identity_field="plan_digest")
    validate_self_identity(participant, identity_field="participant_requirements_digest")
    values = {}
    materializations = []
    for record in participant["required_artifacts"]:
        data = node.cache.open_verified(record)
        state = record["satisfies_logical_state_ids"][0]
        values[state] = struct.unpack("<i", data)[0]
        materializations.append({"logical_state_id": state,
                                 "verification": "VERIFIED_CACHE_SOURCE",
                                 "observed_bytes": len(data), "expected_bytes": record["length"]})
    assigned = next(p for p in plan["participants"]
                    if p["participant_id"] == participant["participant_id"])
    states = assigned["required_state"]["assigned_logical_state"]
    output = sum(values[state] * 2 ** index for index, state in enumerate(states))
    reconciliation = coordinator.reconcile(
        participant["participant_id"], [r["artifact_id"] for r in participant["required_artifacts"]],
        materializations)
    return {"output": output, "reference": REFERENCE[plan["epoch"]],
            "matches_reference": output == REFERENCE[plan["epoch"]],
            "reconciliation": reconciliation}
