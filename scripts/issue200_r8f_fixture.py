"""Deterministic CPU fixture for issue #200 (R8-F) source-policy proof.

Mirrors the accepted issue #101 fixture pattern (``issue101_fixture.py``): a
small integer "release" whose members become byte-range artifacts. R8-F adds
one thing #101's fixture did not need: a release larger than any one frozen
plan's required subset, so a Node can hold a full release as optional local
backing while a given plan requires only some of it (ADR 0009 / model-
artifact-distribution.md Sec. 9).
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from issue99_artifact_core import (
    REQUIREMENT_CLASSES, derive_participant_requirements, digest_of_bytes,
    freeze_artifact_record, self_digest,
)

MODEL = {"model_id": "issue200/r8f-release-fixture", "revision": "fixture-v1",
         "representation": "little-endian-int32"}
WRONG_MODEL = {"model_id": "issue200/r8f-release-fixture", "revision": "fixture-v2-wrong",
              "representation": "little-endian-int32"}
RELEASE_SIZE = 8


class ReleaseFixture:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        values = list(range(1, RELEASE_SIZE + 1))
        data = struct.pack(f"<{RELEASE_SIZE}i", *values)
        (root / "release.bin").write_bytes(data)
        self.release_bytes = data
        self.records: dict[int, dict[str, Any]] = {}
        for number in values:
            start = (number - 1) * 4
            self.records[number] = freeze_artifact_record(
                kind="byte_range", content=data[start:start + 4],
                model_id=MODEL["model_id"], revision=MODEL["revision"],
                representation=MODEL["representation"],
                satisfies_logical_state_ids=[f"member.{number}"],
                requirement_class="assigned_logical_state",
                origin={"source_object": "release.bin",
                        "source_object_digest": digest_of_bytes(data),
                        "source_object_length": len(data),
                        "byte_start": start, "byte_end": start + 4})
        # A structurally valid record whose provenance deliberately does not
        # match MODEL (wrong revision) - used by negative controls only, and
        # never registered as satisfying any frozen plan's requirement.
        self.wrong_revision_record = freeze_artifact_record(
            kind="byte_range", content=data[0:4],
            model_id=WRONG_MODEL["model_id"], revision=WRONG_MODEL["revision"],
            representation=WRONG_MODEL["representation"],
            satisfies_logical_state_ids=["member.1"],
            requirement_class="assigned_logical_state",
            origin={"source_object": "release.bin",
                    "source_object_digest": digest_of_bytes(data),
                    "source_object_length": len(data),
                    "byte_start": 0, "byte_end": 4})

    def resolve(self, requirement_class: str, state_id: str):
        return [record for record in self.records.values()
                if record["requirement_class"] == requirement_class
                and state_id in record["satisfies_logical_state_ids"]]

    def plan(self, epoch: int, assignments: dict[str, tuple[str, list[int]]]) -> dict[str, Any]:
        plan = {"epoch": epoch, "model": MODEL,
                "logical_state_units": [{"id": f"member.{n}"} for n in range(1, RELEASE_SIZE + 1)],
                "participants": [
                    {"participant_id": participant, "node_id": node,
                     "execution_unit_id": f"exec.{participant}",
                     "required_state": {key: [f"member.{n}" for n in numbers]
                                        if key == "assigned_logical_state" else []
                                        for key in REQUIREMENT_CLASSES}}
                    for participant, (node, numbers) in assignments.items()]}
        plan["plan_digest"] = self_digest(plan, identity_field="plan_digest")
        return plan

    def requirements(self, plan):
        return derive_participant_requirements(plan, self.resolve)

    def stage_full_release(self, node) -> int:
        """Verify-then-publish every release member into a Node's own durable
        cache as optional local backing (Phase 2), independent of what any
        one frozen plan currently requires. Uses only the accepted #101
        ``NodeArtifactCache.publish`` verify-then-publish primitive; nothing
        is advertised as a peer Source by this call alone."""
        total = 0
        for number, record in self.records.items():
            node.cache.publish(record, struct.pack("<i", number))
            total += record["length"]
        return total

    def seed_and_advertise(self, node, numbers):
        """Verify-then-publish and advertise a subset (accepted #101 pattern),
        so other participants can resolve it as a peer Source."""
        for number in numbers:
            record = self.records[number]
            node.cache.publish(record, struct.pack("<i", number))
            node.publish(record)
