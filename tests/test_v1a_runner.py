"""Issue #154 CPU-only contract tests for the V1-A physical campaign runner."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v1a_runner as runner  # noqa: E402
import v1a_vulkan_adapter as adapter  # noqa: E402
import v1a_execution_participant as participant  # noqa: E402

STDERR = """using device Vulkan1 (test accelerator) (0000:02:00.0)
offloaded 12/12 layers to GPU
"""

AUTHORITY = {
    "schema": "inferswarm.v1a.physical-authority/1",
    "physical_identity": {
        "hostname": "inferswarm02",
        "node_id": "node-inferswarm02",
        "compute_unit_id": "cu-opaque-a",
        "memory_resource_id": "mr-opaque-a",
        "memory_resource_bytes": 8589934592,
        "physical_device_bdf": "02:00.0",
    },
    "frozen": {
        "hostname": "inferswarm02",
        "node_id": "node-inferswarm02",
        "compute_unit_id": "cu-opaque-a",
        "memory_resource_id": "mr-opaque-a",
        "memory_bytes": 8589934592,
        "physical_device_bdf": "02:00.0",
        "selector": "Vulkan1",
        "execution_unit_id": "unit-opaque-a",
        "execution_contract_id": "contract-opaque-a",
        "implementation_id": "impl-opaque-a",
        "qualification_evidence_id": "v1a-qualification-opaque-a",
        "canonical_execution_evidence_id": "v1a-canonical-opaque-a",
        "logical_state_id": "state-opaque-a",
        "required_representation": "representation-opaque-a",
        "required_features": ["feature-a"],
        "required_memory_bytes": 400,
        "required_headroom_bytes": 100,
        "required_integrity_status": "QUALIFIED",
        "correctness_policy": "policy-opaque-a",
        "objective": "MIN_OBJECTIVE_VALUE",
        "runtime_identity": {"runtime": "opaque"},
    },
}

PRESSURE = {
    "node_id": "node-inferswarm02",
    "compute_unit_id": "cu-opaque-pressure",
    "physical_device_bdf": "04:00.0",
    "memory_resource": {"memory_resource_id": "mr-opaque-pressure", "bytes": 8589934592},
    "capabilities": [{
        "bound_node_id": "node-inferswarm02",
        "bound_compute_unit_id": "cu-opaque-pressure",
        "bound_memory_resource_id": "mr-opaque-pressure",
        "bound_execution_unit_id": "unit-opaque-a",
        "execution_contract_id": "contract-opaque-other",
        "implementation_id": "impl-opaque-pressure",
        "evidence_id": "evidence-pressure",
        "qualification_evidence_id": "qualification-pressure",
        "qualification_digest": "digest-pressure",
        "physical_device_bdf": "04:00.0",
        "runtime_identity": {"runtime": "pressure"},
        "representations": ["representation-opaque-a"],
        "required_features": ["feature-a"],
        "integrity_status": "QUALIFIED",
        "evidence_fresh": True,
        "economics": {"objective_value": 0.5},
    }],
}


class V1ARunnerTests(unittest.TestCase):
    def test_qualification_seals_contract_and_mints_capability_from_observation(self):
        observation = adapter.parse_backend_observation(
            stderr=STDERR, selector="Vulkan1", expected_bdf="02:00.0", node_id="node-inferswarm02",
            compute_unit_id="cu-opaque-a", memory_resource_id="mr-opaque-a",
            execution_unit_id="unit-opaque-a", execution_contract_id="contract-opaque-a",
            implementation_id="impl-opaque-a", evidence_id="v1a-qualification-opaque-a",
            runtime_identity={"runtime": "opaque"})
        capability = adapter.capability_record(
            node_id="node-inferswarm02", compute_unit_id="cu-opaque-a", memory_resource_id="mr-opaque-a",
            execution_unit_id="unit-opaque-a", execution_contract_id="contract-opaque-a",
            implementation_id="impl-opaque-a", evidence_id="v1a-qualification-opaque-a",
            bdf="02:00.0", runtime_identity={"runtime": "opaque"}, observation=observation)
        self.assertEqual(capability["execution_contract_id"], "contract-opaque-a")
        self.assertEqual(capability["qualification_digest"], observation.proof_digest)

    def test_snapshot_and_plan_select_the_qualified_participant_generically(self):
        authority = {**AUTHORITY, "physical_identity": {**AUTHORITY["physical_identity"], "ontology_pressure_resource": PRESSURE},
                     "capability_completion": {"representations": ["representation-opaque-a"],
                                               "required_features": ["feature-a"],
                                               "integrity_status": "QUALIFIED"}}
        observation = adapter.parse_backend_observation(
            stderr=STDERR, selector="Vulkan1", expected_bdf="02:00.0", node_id="node-inferswarm02",
            compute_unit_id="cu-opaque-a", memory_resource_id="mr-opaque-a",
            execution_unit_id="unit-opaque-a", execution_contract_id="contract-opaque-a",
            implementation_id="impl-opaque-a", evidence_id="v1a-qualification-opaque-a",
            runtime_identity={"runtime": "opaque"})
        capability = adapter.capability_record(
            node_id="node-inferswarm02", compute_unit_id="cu-opaque-a", memory_resource_id="mr-opaque-a",
            execution_unit_id="unit-opaque-a", execution_contract_id="contract-opaque-a",
            implementation_id="impl-opaque-a", evidence_id="v1a-qualification-opaque-a",
            bdf="02:00.0", runtime_identity={"runtime": "opaque"}, observation=observation)
        # The pressure resource has a better objective value but an
        # incompatible contract: the generic planner must exclude it.
        completion = authority["capability_completion"]
        capability = {**capability, "representations": list(completion["representations"]),
                      "required_features": list(completion["required_features"]),
                      "integrity_status": completion["integrity_status"],
                      "evidence_fresh": True, "economics": {"objective_value": 2.0}}
        snapshot = runner.build_snapshot(authority, capability)
        decision, plan = runner.plan_and_freeze(authority, snapshot)
        self.assertEqual(decision["selected_candidate"]["compute_unit_id"], "cu-opaque-a")
        excluded = [row for row in decision["explanations"] if row["disposition"] == "EXCLUDED"]
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0]["reason"], "EXECUTION_CONTRACT_UNSUPPORTED")
        participant.validate_frozen_plan(plan)

    def test_runner_source_contains_no_ssh_client_usage(self):
        source = (ROOT / "scripts" / "v1a_runner.py").read_text(encoding="utf-8")
        for forbidden in ("import paramiko", "subprocess.run([\"ssh\"", "ssh "):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
