"""Deterministic opaque CPU fixture for issue #103."""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from issue99_artifact_core import (
    REQUIREMENT_CLASSES,
    NodeArtifactCache,
    derive_participant_requirements,
    digest_of_bytes,
    freeze_artifact_record,
    self_digest,
)
from issue101_orchestration import Node


MODEL = {
    "model_id": "issue103/opaque-state-fixture",
    "revision": "fixture-v1",
    "representation": "little-endian-int32",
}
REQUIRED_NUMBERS = (1, 2, 3)


class Strategy:
    """Expose the frozen legal set and independent technical checks."""

    def __init__(self):
        self._candidates = [
            {"candidate_id": "A", "participant_id": "P-A", "node_id": "A",
             "resource_capacity": 1, "required_capacity": 1,
             "policy_eligible": True, "integrity_eligible": True},
            {"candidate_id": "B", "participant_id": "P-B", "node_id": "B",
             "resource_capacity": 1, "required_capacity": 1,
             "policy_eligible": True, "integrity_eligible": True},
            {"candidate_id": "C", "participant_id": "P-C", "node_id": "C",
             "resource_capacity": 1, "required_capacity": 1,
             "policy_eligible": True, "integrity_eligible": True},
        ]

    def legal_candidates(self):
        return [dict(candidate) for candidate in self._candidates]

    def feasibility(self, candidate):
        return {
            "technical_feasibility": candidate["resource_capacity"] >= candidate["required_capacity"],
            "hard_policy_eligible": bool(candidate["policy_eligible"]),
            "integrity_eligible": bool(candidate["integrity_eligible"]),
        }

    def frozen_document(self):
        document = {"schema": "issue103.strategy/1", "candidates": self.legal_candidates(),
                    "feasibility": {c["candidate_id"]: self.feasibility(c)
                                     for c in self._candidates}}
        document["strategy_digest"] = self_digest(document, identity_field="strategy_digest")
        return document


class Fixture:
    """Create exact three-artifact requirements without exposing fixture nouns."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        data = struct.pack("<3i", *REQUIRED_NUMBERS)
        (root / "state.bin").write_bytes(data)
        self.records = {}
        source_digest = digest_of_bytes(data)
        for number in REQUIRED_NUMBERS:
            start = (number - 1) * 4
            self.records[number] = freeze_artifact_record(
                kind="byte_range",
                content=data[start:start + 4],
                model_id=MODEL["model_id"],
                revision=MODEL["revision"],
                representation=MODEL["representation"],
                satisfies_logical_state_ids=[f"unit.{number}"],
                requirement_class="assigned_logical_state",
                origin={"source_object": "state.bin", "source_object_digest": source_digest,
                        "source_object_length": len(data), "byte_start": start,
                        "byte_end": start + 4},
            )
        self.identity = {
            "schema": "issue103.fixture/1",
            "model": MODEL,
            "upstream_digest": source_digest,
            "upstream_bytes": len(data),
            "records": list(self.records.values()),
            "required_artifact_ids": [self.records[n]["artifact_id"] for n in REQUIRED_NUMBERS],
        }

    def resolve(self, requirement_class: str, state_id: str):
        return [record for record in self.records.values()
                if record["requirement_class"] == requirement_class
                and state_id in record["satisfies_logical_state_ids"]]

    def plan(self, epoch: int = 1):
        plan = {
            "schema": "issue103.execution-plan/1",
            "epoch": epoch,
            "model": MODEL,
            "logical_state_units": [{"id": f"unit.{number}"} for number in REQUIRED_NUMBERS],
            "participants": [
                {"participant_id": f"P-{node_id}", "node_id": node_id,
                 "execution_unit_id": f"unit-for-{node_id}",
                 "required_state": {
                     key: [f"unit.{number}" for number in REQUIRED_NUMBERS]
                     if key == "assigned_logical_state" else []
                     for key in REQUIREMENT_CLASSES}}
                for node_id in ("A", "B", "C")
            ],
        }
        plan["plan_digest"] = self_digest(plan, identity_field="plan_digest")
        return plan

    def requirements(self, plan):
        return derive_participant_requirements(plan, self.resolve)

    def node(self, root: Path, node_id: str):
        return Node(node_id, NodeArtifactCache(root / node_id))

    def seed(self, node, numbers, *, advertise=True):
        for number in numbers:
            record = self.records[number]
            data = struct.pack("<i", number)
            node.cache.publish(record, data)
            if advertise:
                node.publish(record)
