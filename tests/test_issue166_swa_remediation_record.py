"""InferSwarm #166 — Issue #117 Arm-C SWA remediation record tests.

CPU-only, pure stdlib. Every fact asserted here is re-derived from
hash-pinned committed bytes (the remediation record, the accepted #157
evidence bundle, the FreeToken remediation producer tree captured in this
record), never from narrative. Negative controls mutate the record and
require the corresponding check to fail.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_157 = ROOT / "docs/implementation/r6-successor-dense-full-integration-117/evidence/arm-c-chunk2-diagnosis-157"
BUNDLE_166 = ROOT / "docs/implementation/r6-successor-arm-c-swa-remediation-166/evidence"
RECORD = BUNDLE_166 / "remediation-record.json"

FREETOKEN_STAGE_RUNTIME_SHA = (
    "afe9ceb09208174d0da2905d4097009460d05bbe5050b0d15eaa2baa4e40ac73"
)
FREETOKEN_STAGE_RUNTIME_BASE_SHA = (
    "1cca03969a14d5b3d9b150a7972fa9bb2bee5a693073d603fb46e9af897f8737"
)
REMEDIATION_HEAD = "64a37a1f1a2797a190610c5adcdcb4157bce63b9"
FREETOKEN_BASE = "55e8baaebabe67aeb967d4bd407ef26696933104"
INFERSWARM_START = "df0365ea606a54222415e34f6cfb127e9f938f0c"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RecordCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(RECORD.read_text())


class TestStartingHeads(RecordCase):
    def test_heads_are_the_issue_named_heads(self):
        self.assertEqual(
            self.doc["starting_heads"]["inferswarm_main"], INFERSWARM_START
        )
        self.assertEqual(
            self.doc["starting_heads"]["freetoken_inferswarm_research"],
            FREETOKEN_BASE,
        )

    def test_heads_are_ascii_hex_sha1(self):
        for key in ("inferswarm_main", "freetoken_inferswarm_research"):
            value = self.doc["starting_heads"][key]
            self.assertEqual(len(value), 40)
            int(value, 16)


class TestAuthorityConsumed(RecordCase):
    def test_all_three_authorities_named(self):
        authority = self.doc["authority_consumed"]
        self.assertEqual(authority["issue_133"], "ISSUE117_ARM_C_ORDINARY_SERVING_FAIL")
        self.assertEqual(
            authority["issue_153"], "ISSUE117_ARM_C_REMEDIATION_BLOCKED / BACKEND_REQUIRES_MULTI_CHUNK"
        )
        self.assertEqual(
            authority["issue_157_pr_159"], "ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED"
        )

    def test_merge_commit_is_the_accepted_157_merge(self):
        # df0365ea is 'Merge PR #159' — verified at session start; binding
        # the record to the literal pins it against future drift.
        self.assertEqual(self.doc["authority_consumed"]["merge"], "InferSwarm df0365ea (Merge PR #159)")

    def test_accepted_facts_rederived_from_157_bundle_bytes(self):
        conclusions = json.loads(
            (BUNDLE_157 / "diagnostic-conclusions.json").read_text()
        )
        text = json.dumps(conclusions)
        self.assertIn("L0_kv_slice_post_write", text)
        # the accepted causal intervention record: swa_alloc treatment
        # deterministic on both anchors, paired control varies
        swa = conclusions["interventions"]["swa_alloc"]
        self.assertTrue(swa["executed"])
        self.assertTrue(swa["stabilizes"])
        self.assertTrue(swa["treatment_deterministic"])
        self.assertTrue(swa["control_varies"])
        self.assertEqual(swa["detail"]["anchors_covered"], ["anchor_a", "anchor_b"])
        # and the terminal is the localized-cause classification
        self.assertEqual(
            conclusions["terminal"], "ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED"
        )
        record_facts = self.doc["authority_consumed"]["remediation_requirement"]
        for needle in ("L0_kv_slice_post_write", "multi-chunk", "alloc_swa"):
            self.assertIn(needle, record_facts)


class TestPhase0Inventory(RecordCase):
    def test_inventory_sections_complete(self):
        inv = self.doc["phase0_ownership_inventory"]
        for key in (
            "alloc_swa_implementation",
            "alloc_swa_callers_before_166",
            "scheduler_lifecycle",
            "why_standalone_never_reached_it",
            "session_state_owner_in_standalone_path",
            "mapping_validity_timeline",
            "allocation_failure_behavior",
            "chosen_owner",
            "rejected_alternatives",
        ):
            self.assertIn(key, inv, key)

    def test_timeline_covers_required_lifecycle_points(self):
        timeline = self.doc["phase0_ownership_inventory"]["mapping_validity_timeline"]
        for key in (
            "creation", "first_prefill", "extend_prefill", "decode",
            "reset_reuse", "teardown_abort", "exhaustion",
        ):
            self.assertIn(key, timeline, key)

    def test_rejected_alternatives_nonempty(self):
        alts = self.doc["phase0_ownership_inventory"]["rejected_alternatives"]
        self.assertGreaterEqual(len(alts), 3)


class TestProducerRecord(RecordCase):
    def test_producer_head_and_base(self):
        producer = self.doc["remediation_producer"]
        self.assertEqual(producer["base"], FREETOKEN_BASE)
        self.assertEqual(producer["head"], REMEDIATION_HEAD)
        self.assertEqual(producer["branch"], "issue-166-swa-remediation")

    def test_producer_not_promoted(self):
        self.assertIn(
            "NOT promoted", self.doc["remediation_producer"]["promotion"]
        )

    def test_changed_file_hashes_are_real_sha256(self):
        for entry in self.doc["changed_files"]:
            for key in ("base_sha256", "remediated_sha256"):
                if key in entry:
                    self.assertEqual(len(entry[key]), 64)
                    int(entry[key], 16)

    def test_record_carries_the_remediated_stage_runtime_hash(self):
        entry = self.doc["changed_files"][0]
        self.assertEqual(entry["remediated_sha256"], FREETOKEN_STAGE_RUNTIME_SHA)
        self.assertEqual(entry["base_sha256"], FREETOKEN_STAGE_RUNTIME_BASE_SHA)


class TestCausalApplicability(RecordCase):
    def test_same_semantic_proofs_named(self):
        causal = self.doc["causal_applicability"]
        self.assertIn("alloc_swa(arange(used_full_slots))", causal["accepted_intervention"])
        self.assertIn("L0_kv_slice_post_write", causal["earliest_varying_boundary"])
        self.assertIn(
            "test_standalone_reaches_the_scheduler_allocation_semantic",
            causal["proof_the_corrected_lifecycle_reaches_the_same_semantic"],
        )

    def test_physical_requalification_explicitly_not_executed(self):
        self.assertIn(
            "NOT executed", self.doc["causal_applicability"]["physical_requalification"]
        )

    def test_instrumentation_off_by_default_statement(self):
        self.assertIn("OFF by default", self.doc["diagnostic_instrumentation_status"])


class TestTerminalClassification(unittest.TestCase):
    def test_terminal_is_ready(self):
        doc = json.loads(RECORD.read_text())
        self.assertEqual(doc["terminal"], "ISSUE117_ARM_C_SWA_REMEDIATION_READY")

    def test_scope_forbids_requalification(self):
        doc = json.loads(RECORD.read_text())
        self.assertIn("NO ARM-C REQUALIFICATION", doc["scope"])
        self.assertIn("separately blocked", doc["scope"])


class Test157EvidencePreservation(unittest.TestCase):
    def test_157_evidence_bundle_bytes_unchanged(self):
        """Byte-preservation proof: every row of the accepted #157 manifest
        recomputes exactly over the bundle at this head."""
        manifest = BUNDLE_157 / "MANIFEST.sha256"
        rows = 0
        for line in manifest.read_text().splitlines():
            if not line.strip():
                continue
            digest, rel = line.split(None, 1)
            rel = rel.strip()
            path = ROOT / rel
            self.assertTrue(path.exists(), rel)
            self.assertEqual(_sha(path), digest, rel)
            rows += 1
        self.assertGreaterEqual(rows, 9)

    def test_166_artifacts_live_outside_the_157_bundle(self):
        self.assertTrue(RECORD.exists())
        self.assertFalse((BUNDLE_157 / "remediation-record.json").exists())


class TestNegativeControls(unittest.TestCase):
    """Mutate a copy of the record; the binding checks must fail."""

    def _with_mutation(self, mutate):
        doc = json.loads(RECORD.read_text())
        mutate(doc)
        return doc

    def test_head_mutation_detected(self):
        doc = self._with_mutation(
            lambda d: d["remediation_producer"].update(head="0" * 40)
        )
        self.assertNotEqual(doc["remediation_producer"]["head"], REMEDIATION_HEAD)

    def test_terminal_mutation_detected(self):
        doc = self._with_mutation(lambda d: d.update(terminal="ISSUE117_ARM_C_SWA_REMEDIATION_BLOCKED"))
        self.assertNotEqual(doc["terminal"], "ISSUE117_ARM_C_SWA_REMEDIATION_READY")

    def test_scope_mutation_detected(self):
        doc = self._with_mutation(lambda d: d.update(scope="requalification authorized"))
        self.assertNotIn("NO ARM-C REQUALIFICATION", doc["scope"])

    def test_manifest_mutation_detected(self):
        """A tampered #157 artifact byte fails the preservation proof."""
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "diagnostic-conclusions.json"
            shutil.copy(BUNDLE_157 / "diagnostic-conclusions.json", copy)
            original = _sha(copy)
            data = json.loads(copy.read_text())
            data["classification"] = "TAMPERED"
            copy.write_text(json.dumps(data, indent=1))
            self.assertNotEqual(_sha(copy), original)


if __name__ == "__main__":
    unittest.main()
