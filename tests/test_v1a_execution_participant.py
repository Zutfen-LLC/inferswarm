"""Issue #154 reusable internal execution-participant contract tests."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v1a_execution_participant as participant  # noqa: E402
import v1a_vulkan_adapter as adapter  # noqa: E402

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
STDERR = """using device VkSelector (test accelerator) (0000:02:00.0)
offloaded 12/12 layers to GPU
"""


def resource(cu="cu-a", memory="mr-a", bdf="01:00.0", implementation="impl-a",
             contract="contract-opaque-a", score=2.0, node="node-a"):
    return {
        "node_id": node,
        "compute_unit_id": cu,
        "physical_device_bdf": bdf,
        "memory_resource": {"memory_resource_id": memory, "bytes": 1000},
        "capabilities": [{
            "bound_node_id": node,
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


def adapter_proof(plan):
    candidate = plan["candidate"]
    stderr = STDERR.replace("02:00.0", candidate["physical_device_bdf"])
    observation = adapter.parse_backend_observation(
        stderr=stderr, selector="VkSelector", expected_bdf=candidate["physical_device_bdf"],
        node_id=candidate["node_id"], compute_unit_id=candidate["compute_unit_id"],
        memory_resource_id=candidate["memory_resource_id"], execution_unit_id=candidate["execution_unit_id"],
        implementation_id=candidate["implementation_id"], evidence_id=candidate["evidence_id"],
        runtime_identity=candidate["runtime_identity"])
    return adapter.seal_canonical_execution_proof(
        observation=observation, plan_digest=plan["plan_digest"], candidate_id=candidate["candidate_id"],
        execution_evidence_id="canonical-run-a", stdout=b"runtime output", stderr=stderr, exit_code=0), observation


class V1AParticipantTests(unittest.TestCase):
    def plan(self, **kwargs):
        decision = participant.plan_execution_unit(
            execution_unit=UNIT, compute_units=[resource(**kwargs)], objective="MIN_OBJECTIVE_VALUE")
        return participant.freeze_plan(decision=decision, execution_unit=UNIT)

    def test_second_opaque_participant_is_eligible_and_objective_selects_it(self):
        first = resource(score=3.0)
        second = resource(cu="cu-b", memory="mr-b", bdf="02:00.0", implementation="impl-b", score=1.0)
        decision = participant.plan_execution_unit(
            execution_unit=UNIT, compute_units=[first, second], objective="MIN_OBJECTIVE_VALUE")
        self.assertEqual(decision["selected_candidate"]["compute_unit_id"], "cu-b")
        self.assertEqual({row["disposition"] for row in decision["explanations"]},
                         {"SELECTED", "LOWER_RANKED"})

    def test_missing_or_wrong_node_is_an_admission_exclusion(self):
        for resource_change, capability_change, reason in (
            ("", None, "NODE_IDENTITY_MISSING"),
            (None, "node-other", "CAPABILITY_NODE_BINDING_MISMATCH"),
        ):
            with self.subTest(reason=reason):
                candidate = resource()
                if resource_change is not None:
                    candidate["node_id"] = resource_change
                if capability_change is not None:
                    candidate["capabilities"][0]["bound_node_id"] = capability_change
                decision = participant.plan_execution_unit(
                    execution_unit=UNIT, compute_units=[candidate], objective="MIN_OBJECTIVE_VALUE")
                self.assertEqual(decision["explanations"][0]["reason"], reason)

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

    def test_recomputed_plan_cannot_substitute_node_or_candidate_identity(self):
        plan = self.plan()
        for field, value in (("node_id", "node-other"), ("candidate_id", "candidate-other")):
            altered = copy.deepcopy(plan)
            altered["candidate"][field] = value
            body = {key: altered[key] for key in altered if key != "plan_digest"}
            altered["plan_digest"] = participant._digest(body)
            with self.subTest(field=field), self.assertRaises(participant.ParticipantError):
                participant.validate_frozen_plan(altered)

    def test_adapter_validated_canonical_proof_receipts_generic_twelve_layer_run(self):
        plan = self.plan(bdf="02:00.0")
        proof, _ = adapter_proof(plan)
        receipt = participant.execution_receipt(plan=plan, output=b"result", canonical_proof=proof)
        self.assertEqual(receipt["candidate_id"], plan["candidate"]["candidate_id"])

    def test_mapping_qualification_proof_and_other_node_proof_cannot_receipt(self):
        plan = self.plan(bdf="02:00.0")
        proof, qualification = adapter_proof(plan)
        for invalid in ({"apparently": "correct"}, qualification,
                        adapter.seal_canonical_execution_proof(
                            observation=adapter.parse_backend_observation(
                                stderr=STDERR, selector="VkSelector", expected_bdf="02:00.0",
                                node_id="node-other", compute_unit_id=plan["candidate"]["compute_unit_id"],
                                memory_resource_id=plan["candidate"]["memory_resource_id"],
                                execution_unit_id=plan["candidate"]["execution_unit_id"],
                                implementation_id=plan["candidate"]["implementation_id"],
                                evidence_id=plan["candidate"]["evidence_id"],
                                runtime_identity=plan["candidate"]["runtime_identity"]),
                            plan_digest=plan["plan_digest"], candidate_id=plan["candidate"]["candidate_id"],
                            execution_evidence_id="other-node", stdout=b"runtime output", stderr=STDERR,
                            exit_code=0)):
            with self.subTest(invalid=type(invalid).__name__), self.assertRaises(participant.ParticipantError):
                participant.execution_receipt(plan=plan, output=b"result", canonical_proof=invalid)
        self.assertIsNotNone(proof)

    def test_generic_participant_source_has_no_model_layer_or_backend_coupling(self):
        source = (ROOT / "scripts" / "v1a_execution_participant.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("37", source)
        self.assertNotIn("offloaded_layers", source)
        audit = participant.source_token_audit(
            ROOT / "scripts" / "v1a_execution_participant.py",
            ["vulkan", "cuda", "amd", "nvidia", "radeon"],
        )
        self.assertEqual(audit["matches"], [])


if __name__ == "__main__":
    unittest.main()
