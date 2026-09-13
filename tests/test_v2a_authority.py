"""Issue #163 CPU-only contract tests for the V2-A campaign authority."""
from __future__ import annotations

import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v2a_authority as authority  # noqa: E402

REFERENCE = b"The fox lands safely and trots away.\n"
NO_RECALIBRATION = authority.NO_RECALIBRATION


def reference_file(temp: str) -> Path:
    path = Path(temp) / "reference.txt"
    path.write_bytes(REFERENCE)
    return path


def build_authority(temp: str) -> dict:
    ref = reference_file(temp)
    return {
        "schema": authority.SCHEMA,
        "issue": "#163",
        "frozen": {
            "hostname": "node-t", "node_id": "node-t", "compute_unit_id": "cu-t",
            "memory_resource_id": "mr-t", "memory_bytes": 8589934592,
            "physical_device_bdf": "0a:00.0", "selector": "Vulkan7",
            "execution_unit_id": "unit-t", "execution_contract_id": "contract-t",
            "implementation_id": "impl-t", "logical_state_id": "state-t",
            "required_representation": "gguf-q4-k-m", "required_features": ["compute"],
            "required_memory_bytes": 3254091776, "required_headroom_bytes": 536870912,
            "required_integrity_status": "QUALIFIED",
            "correctness_policy": authority.ACCEPTED_COMPARATOR_POLICY,
            "objective": "MIN_OBJECTIVE_VALUE", "prompt": "prompt-t",
            "runtime_source": "/src", "runtime_source_commit": "c" * 40,
            "executable": "/bin/llama-cli", "executable_sha256": "a" * 64,
            "model": "/model.gguf", "model_sha256": "b" * 64, "model_bytes": 123,
            "qualification_evidence_id": "v2a-t-qualification-01",
            "canonical_execution_evidence_id": "v2a-t-canonical-01",
            "runtime_identity": {"selector": "Vulkan7", "driver": "d"},
        },
        "correctness": {
            "comparator_policy": authority.ACCEPTED_COMPARATOR_POLICY,
            "comparator_identity": "scripts/v0c_correctness.py",
            "comparator_sha256": hashlib.sha256(
                (ROOT / "scripts/v0c_correctness.py").read_bytes()).hexdigest(),
            "reference_sha256": hashlib.sha256(REFERENCE).hexdigest(),
            "reference_path": str(ref),
            "reference_provenance": "accepted pre-existing campaign evidence (fixture)",
            "no_recalibration": NO_RECALIBRATION,
        },
        "evidence": {"evidence_namespace": "vulkan-v2-a",
                     "plan_evidence_id": "v2a-t-plan-01",
                     "capability_evidence_id": "v2a-t-capability-01"},
        "nonclaims": ["internal harness only"],
    }


class AcceptanceTests(unittest.TestCase):
    def test_complete_authority_loads(self):
        with tempfile.TemporaryDirectory() as temp:
            document = build_authority(temp)
            loaded = authority.load_authority(document)
            self.assertEqual(loaded["frozen"]["selector"], "Vulkan7")

    def test_missing_frozen_field_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            document = build_authority(temp)
            del document["frozen"]["model_sha256"]
            with self.assertRaises(authority.AuthorityError):
                authority.load_authority(document)

    def test_wrong_schema_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            document = build_authority(temp)
            document["schema"] = "something.else/1"
            with self.assertRaises(authority.AuthorityError):
                authority.load_authority(document)

    def test_reference_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            document = build_authority(temp)
            reference_file(temp).write_bytes(b"tampered\n")
            with self.assertRaises(authority.AuthorityError):
                authority.load_authority(document)

    def test_loosened_comparator_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            document = build_authority(temp)
            document["correctness"]["comparator_policy"] = "fuzzy-tolerance-v1"
            with self.assertRaises(authority.AuthorityError):
                authority.load_authority(document)

    def test_missing_no_recalibration_rule_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            document = build_authority(temp)
            document["correctness"]["no_recalibration"] = "recalibration allowed"
            with self.assertRaises(authority.AuthorityError):
                authority.load_authority(document)

    def test_missing_correctness_provenance_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            document = build_authority(temp)
            del document["correctness"]["reference_provenance"]
            with self.assertRaises(authority.AuthorityError):
                authority.load_authority(document)

    def test_self_authorizing_provenance_rejected(self):
        for bad in ("reference derived from this campaign canonical output",
                    "self-authorized from discovery output",
                    "observed from qualification output of the harness"):
            with tempfile.TemporaryDirectory() as temp:
                document = build_authority(temp)
                document["correctness"]["reference_provenance"] = bad
                with self.assertRaises(authority.AuthorityError):
                    authority.load_authority(document)

    def test_malformed_selector_and_bdf_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            document = build_authority(temp)
            document["frozen"]["selector"] = "CUDA0"
            with self.assertRaises(authority.AuthorityError):
                authority.load_authority(document)
            document = build_authority(temp)
            document["frozen"]["physical_device_bdf"] = "0000:04:00.0"
            with self.assertRaises(authority.AuthorityError):
                authority.load_authority(document)

    def test_missing_evidence_block_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            document = build_authority(temp)
            del document["evidence"]
            with self.assertRaises(authority.AuthorityError):
                authority.load_authority(document)

    def test_missing_nonclaims_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            document = build_authority(temp)
            document["nonclaims"] = []
            with self.assertRaises(authority.AuthorityError):
                authority.load_authority(document)

    def test_reference_bytes_are_the_authorized_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            document = build_authority(temp)
            loaded = authority.load_authority(document)
            self.assertEqual(authority.reference_bytes(loaded, reference_root=Path(temp)), REFERENCE)


class TwoSyntheticSubjectsTests(unittest.TestCase):
    """Control 1: the same contract accepts two totally different subjects."""

    def test_two_opaque_subjects_both_load(self):
        with tempfile.TemporaryDirectory() as temp:
            first = build_authority(temp)
            second = build_authority(temp)
            second["frozen"].update({
                "node_id": "node-xyz-9", "compute_unit_id": "cu-opaque-α".replace("α", "aa"),
                "memory_resource_id": "mr-very-different", "physical_device_bdf": "1f:02.7",
                "selector": "Vulkan11", "implementation_id": "impl-other",
                "qualification_evidence_id": "v2a-other-qualification-77",
                "canonical_execution_evidence_id": "v2a-other-canonical-77",
            })
            second["evidence"] = {"evidence_namespace": "vulkan-v2-a",
                                  "plan_evidence_id": "v2a-other-plan-77",
                                  "capability_evidence_id": "v2a-other-capability-77"}
            a = authority.load_authority(first)
            b = authority.load_authority(second)
            self.assertNotEqual(a["frozen"]["selector"], b["frozen"]["selector"])
            self.assertNotEqual(a["frozen"]["compute_unit_id"], b["frozen"]["compute_unit_id"])


if __name__ == "__main__":
    unittest.main()
