"""Issue #143 S2 execution-seam contract tests (CPU-only)."""
from __future__ import annotations

import copy
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v0c_execution_seam as seam  # noqa: E402


AMD_CU = {
    "compute_unit_id": "cu-amd-a",
    "node_id": "node-inferswarm02",
    "memory_resource": {"memory_resource_id": "mr-amd-a-vram", "bytes": 8589934592},
    "capabilities": [{
        "implementation_id": "impl-portable-amd-a",
        "required_features": ["compute"],
        "representations": ["gguf-q4-k-m"],
        "integrity_status": "QUALIFIED",
        "economics": {"startup_seconds": 26.48, "decode_tokens_per_second": 43.7},
        "evidence_id": "evidence-amd-a",
        "evidence_fresh": True,
    }],
}
CUDA_CU = {
    "compute_unit_id": "cu-nv-a",
    "node_id": "node-inferswarm02",
    "memory_resource": {"memory_resource_id": "mr-nv-a-vram", "bytes": 8589934592},
    "capabilities": [{
        "implementation_id": "impl-native-nv-a",
        "required_features": ["compute"],
        "representations": ["gguf-q4-k-m"],
        "integrity_status": "QUALIFIED",
        "economics": {"startup_seconds": 11.364, "decode_tokens_per_second": 108.0},
        "evidence_id": "evidence-nv-a",
        "evidence_fresh": True,
    }],
}
UNIT = {
    "execution_unit_id": "unit-q4km-whole-model",
    "required_representation": "gguf-q4-k-m",
    "required_features": ["compute"],
    "required_memory_bytes": 3254091776,
    "required_headroom_bytes": 536870912,
    "required_integrity_status": "QUALIFIED",
}


class V0CExecutionSeamTests(unittest.TestCase):
    def test_selects_by_generic_facts_and_keeps_all_explanations(self):
        decision = seam.plan_execution_unit(
            execution_unit=UNIT,
            compute_units=[AMD_CU, CUDA_CU],
            objective="MIN_STARTUP_SECONDS",
        )
        self.assertEqual(decision["selected_candidate_id"], "unit-q4km-whole-model@cu-nv-a")
        self.assertEqual(
            {row["candidate_id"] for row in decision["explanations"]},
            {"unit-q4km-whole-model@cu-amd-a", "unit-q4km-whole-model@cu-nv-a"},
        )
        self.assertEqual(decision["explanations"][0]["reason"], "LOWER_RANKED_BY_OBJECTIVE")

    def test_rejects_capability_bound_to_wrong_physical_device(self):
        wrong = copy.deepcopy(AMD_CU)
        wrong["capabilities"][0]["bound_compute_unit_id"] = "cu-nv-a"
        decision = seam.plan_execution_unit(
            execution_unit=UNIT, compute_units=[wrong], objective="MIN_STARTUP_SECONDS"
        )
        self.assertIsNone(decision["selected_candidate_id"])
        self.assertEqual(decision["explanations"][0]["reason"], "CAPABILITY_DEVICE_BINDING_MISMATCH")

    def test_rejects_missing_representation_or_stale_evidence(self):
        unavailable = copy.deepcopy(AMD_CU)
        unavailable["capabilities"][0]["representations"] = ["other"]
        stale = copy.deepcopy(CUDA_CU)
        stale["capabilities"][0]["evidence_fresh"] = False
        decision = seam.plan_execution_unit(
            execution_unit=UNIT, compute_units=[unavailable, stale], objective="MIN_STARTUP_SECONDS"
        )
        reasons = {row["reason"] for row in decision["explanations"]}
        self.assertEqual(reasons, {"REPRESENTATION_UNSUPPORTED", "EVIDENCE_STALE"})

    def test_freezes_plan_and_rejects_identity_tampering(self):
        decision = seam.plan_execution_unit(
            execution_unit=UNIT, compute_units=[AMD_CU], objective="MIN_STARTUP_SECONDS"
        )
        plan = seam.freeze_plan(decision=decision, execution_unit=UNIT)
        seam.validate_frozen_plan(plan)
        tampered = copy.deepcopy(plan)
        tampered["candidate"]["compute_unit_id"] = "cu-other"
        with self.assertRaises(seam.SeamError):
            seam.validate_frozen_plan(tampered)

    def test_reconciles_only_expected_materialization_and_result_identity(self):
        decision = seam.plan_execution_unit(
            execution_unit=UNIT, compute_units=[AMD_CU], objective="MIN_STARTUP_SECONDS"
        )
        plan = seam.freeze_plan(decision=decision, execution_unit=UNIT)
        expected = seam.expected_materialization(plan)
        reconciliation = seam.reconcile_materialization(plan, expected)
        self.assertTrue(reconciliation["clean"])
        observed = copy.deepcopy(expected)
        observed["source_fetches_after_ready"] = 1
        with self.assertRaises(seam.SeamError):
            seam.reconcile_materialization(plan, observed)
        receipt = seam.execution_receipt(plan, output=b"known output", device_identity="cu-amd-a")
        self.assertEqual(receipt["output_sha256"], hashlib.sha256(b"known output").hexdigest())
        with self.assertRaises(seam.SeamError):
            seam.execution_receipt(plan, output=b"known output", device_identity="cu-other")

    def test_generic_planner_contains_no_backend_or_vendor_branches(self):
        audit = seam.planner_purity_audit(
            ROOT / "scripts" / "v0c_execution_seam.py",
            forbidden_tokens=["vulkan", "cuda", "amd", "nvidia", "radeon"],
        )
        self.assertEqual(audit["matches"], [])


if __name__ == "__main__":
    unittest.main()
