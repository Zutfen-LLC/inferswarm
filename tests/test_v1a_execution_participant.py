"""Issue #154 reusable internal execution-participant contract tests."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v1a_execution_participant as participant  # noqa: E402


UNIT = {
    "execution_unit_id": "unit-opaque-a",
    "execution_contract_id": "contract-opaque-a",
    "logical_state_id": "state-opaque-a",
    "required_representation": "representation-opaque-a",
    "required_features": ["feature-a"],
    "required_memory_bytes": 400,
    "required_headroom_bytes": 100,
    "required_integrity_status": "QUALIFIED",
    "correctness_policy": "policy-opaque-a",
}


def resource(cu="cu-a", memory="mr-a", bdf="01:00.0", implementation="impl-a",
             contract="contract-opaque-a", score=2.0):
    return {
        "node_id": "node-a",
        "compute_unit_id": cu,
        "physical_device_bdf": bdf,
        "memory_resource": {"memory_resource_id": memory, "bytes": 1000},
        "capabilities": [{
            "bound_compute_unit_id": cu,
            "bound_memory_resource_id": memory,
            "bound_execution_unit_id": "unit-opaque-a",
            "execution_contract_id": contract,
            "implementation_id": implementation,
            "evidence_id": f"evidence-{implementation}",
            "qualification_evidence_id": f"qualification-{implementation}",
            "qualification_digest": f"digest-{implementation}",
            "physical_device_bdf": bdf,
            "runtime_identity": {"runtime": implementation},
            "representations": ["representation-opaque-a"],
            "required_features": ["feature-a"],
            "integrity_status": "QUALIFIED",
            "evidence_fresh": True,
            "economics": {"objective_value": score},
        }],
    }


class V1AParticipantTests(unittest.TestCase):
    def test_second_opaque_participant_is_eligible_and_objective_selects_it(self):
        first = resource(score=3.0)
        second = resource(cu="cu-b", memory="mr-b", bdf="02:00.0", implementation="impl-b", score=1.0)
        decision = participant.plan_execution_unit(
            execution_unit=UNIT, compute_units=[first, second], objective="MIN_OBJECTIVE_VALUE")
        self.assertEqual(decision["selected_candidate"]["compute_unit_id"], "cu-b")
        self.assertEqual({row["disposition"] for row in decision["explanations"]},
                         {"SELECTED", "LOWER_RANKED"})

    def test_binding_evidence_and_identity_mismatches_fail_closed(self):
        fields = (
            ("bound_compute_unit_id", "other", "CAPABILITY_COMPUTE_UNIT_BINDING_MISMATCH"),
            ("bound_memory_resource_id", "other", "CAPABILITY_MEMORY_RESOURCE_BINDING_MISMATCH"),
            ("bound_execution_unit_id", "other", "CAPABILITY_EXECUTION_UNIT_BINDING_MISMATCH"),
            ("execution_contract_id", "other", "EXECUTION_CONTRACT_UNSUPPORTED"),
            ("implementation_id", "", "CAPABILITY_IDENTITY_MISSING"),
            ("qualification_evidence_id", "", "QUALIFICATION_EVIDENCE_MISSING"),
            ("qualification_digest", "", "QUALIFICATION_EVIDENCE_MISSING"),
            ("physical_device_bdf", "", "PHYSICAL_IDENTITY_MISSING"),
        )
        for field, value, reason in fields:
            with self.subTest(field=field):
                candidate = resource()
                candidate["capabilities"][0][field] = value
                decision = participant.plan_execution_unit(
                    execution_unit=UNIT, compute_units=[candidate], objective="MIN_OBJECTIVE_VALUE")
                self.assertEqual(decision["explanations"][0]["reason"], reason)

    def test_stale_evidence_and_removed_capability_are_generic_exclusions(self):
        stale = resource()
        stale["capabilities"][0]["evidence_fresh"] = False
        missing = resource(cu="cu-b", memory="mr-b", bdf="02:00.0", implementation="impl-b")
        missing["capabilities"] = []
        decision = participant.plan_execution_unit(
            execution_unit=UNIT, compute_units=[stale, missing], objective="MIN_OBJECTIVE_VALUE")
        self.assertEqual(decision["explanations"][0]["reason"], "EVIDENCE_STALE")
        self.assertEqual(len(decision["candidates"]), 1)
        self.assertIsNone(decision["selected_candidate"])

    def test_frozen_plan_and_canonical_observation_bind_candidate_and_plan(self):
        decision = participant.plan_execution_unit(
            execution_unit=UNIT, compute_units=[resource()], objective="MIN_OBJECTIVE_VALUE")
        plan = participant.freeze_plan(decision=decision, execution_unit=UNIT)
        participant.validate_frozen_plan(plan)
        observation = participant.seal_canonical_execution_observation(
            plan=plan, execution_evidence_id="run-a", stdout_sha256="a" * 64,
            stderr_sha256="b" * 64, exit_code=0, offloaded_layers=[37, 37], fallback_free=True)
        receipt = participant.execution_receipt(plan=plan, output=b"result", canonical_observation=observation)
        self.assertEqual(receipt["candidate_id"], plan["candidate"]["candidate_id"])
        wrong = copy.deepcopy(observation)
        wrong["candidate_id"] = "candidate-other"
        with self.assertRaises(participant.ParticipantError):
            participant.execution_receipt(plan=plan, output=b"result", canonical_observation=wrong)

    def test_generic_participant_source_has_no_vendor_or_backend_tokens(self):
        audit = participant.source_token_audit(
            ROOT / "scripts" / "v1a_execution_participant.py",
            ["vulkan", "cuda", "amd", "nvidia", "radeon"],
        )
        self.assertEqual(audit["matches"], [])


if __name__ == "__main__":
    unittest.main()
