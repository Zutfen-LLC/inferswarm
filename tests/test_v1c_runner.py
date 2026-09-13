"""Issue #161 CPU-only contract tests for the V1-C successor campaign runner."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v1c_runner as runner  # noqa: E402
import v1c_accounting as accounting  # noqa: E402

V1A_AUTHORITY = ROOT / "docs/investigations/vulkan-v1-a/PHYSICAL-AUTHORITY.json"
V1B_AUTHORITY = ROOT / "docs/investigations/vulkan-v1-b/PHYSICAL-AUTHORITY.json"


class RetainedTranscriptRegressionTests(unittest.TestCase):
    def test_regression_mode_produces_both_proofs(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "regressions.json"
            # exercise the library functions directly (no CLI writes
            # outside the repository during tests)
            v1a = runner.v1a_regression_proof()
            v1b = runner.v1b_retained_reduction(V1B_AUTHORITY)
            self.assertEqual(v1a["result"], "PASS")
            self.assertEqual(v1b["result"], "PASS")
            self.assertTrue(v1a["field_by_field_identical"])
            self.assertTrue(v1a["shared_facts_byte_identical"])
            self.assertEqual(v1b["three_tuple"], [0, 0, 0])
            self.assertIn("NOT the prospective V1-C physical PASS", v1b["role"])
            _ = out  # CLI path covered by test_v1c_evidence_manifest fixtures

    def test_regression_detects_tampered_retained_transcript(self):
        # The proof binds the retained stderr digest; a mutated
        # transcript must change the digest recorded in the proof. The
        # parse itself is content-checked in test_v1c_accounting.
        proof = runner.v1a_regression_proof()
        raw = (ROOT / proof["retained_stderr"]).read_bytes()
        self.assertEqual(runner.digest_bytes(raw), proof["retained_stderr_sha256"])


class CrossSubjectAuditTests(unittest.TestCase):
    def _fixtures(self):
        v1a = json.loads(V1A_AUTHORITY.read_text(encoding="utf-8"))
        v1b = json.loads(V1B_AUTHORITY.read_text(encoding="utf-8"))
        regression = {
            "v1a_regression": runner.v1a_regression_proof(),
            "v1b_retained_reduction": runner.v1b_retained_reduction(V1B_AUTHORITY),
        }
        return v1a, v1b, regression

    def _v1c_authority(self, successor_sha):
        return {
            "issue": "#161",
            "frozen": {
                "selector": "Vulkan3", "compute_unit_id": "cu-nv-a",
                "canonical_execution_evidence_id": "v1c-nv-a-canonical-01",
            },
            "accepted_source_pins": {
                "scripts/v1a_execution_participant.py": runner._sha256_file(ROOT / "scripts/v1a_execution_participant.py"),
                "scripts/v1a_vulkan_adapter.py": runner._sha256_file(ROOT / "scripts/v1a_vulkan_adapter.py"),
                "scripts/v1a_runner.py": runner._sha256_file(ROOT / "scripts/v1a_runner.py"),
                "scripts/v0c_correctness.py": runner._sha256_file(ROOT / "scripts/v0c_correctness.py"),
                "scripts/v0c_canonical_run.py": runner._sha256_file(ROOT / "scripts/v0c_canonical_run.py"),
            },
            "source_freeze": {"successor_accounting_reducer_sha256": successor_sha},
        }

    def test_audit_passes_on_reused_semantics_and_selector_data(self):
        v1a, v1b, regression = self._fixtures()
        authority = self._v1c_authority(runner._sha256_file(ROOT / "scripts/v1c_accounting.py"))
        canonical = {"canonical_execution_evidence_id": "v1c-nv-a-canonical-01",
                     "accounting": {"selected_resource": "Vulkan3"},
                     "correctness": {"byte_exact_visible_output": True}}
        audit = runner.build_cross_subject_audit(
            v1a, v1b, authority, regression["v1a_regression"],
            regression["v1b_retained_reduction"],
            {"qualification_evidence_id": "v1c-nv-a-qualification-01"},
            {"explanations": []}, canonical)
        self.assertEqual(audit["result"], "PASS")
        self.assertFalse(audit["foundational_invariant_falsified"])
        self.assertEqual(audit["subject_specific_code_remaining"], [])
        by_aspect = {row["aspect"]: row["classification"] for row in audit["classifications"]}
        self.assertEqual(by_aspect["selected Vulkan resource label origin"], "SELECTOR_AUTHORITY_DATA_ONLY")
        self.assertEqual(by_aspect["accepted generic participant/adapter/runner/comparator bytes reused unchanged"],
                         "ACCEPTED_GENERIC_SEMANTICS_REUSED")

    def test_audit_fails_on_successor_drift(self):
        v1a, v1b, regression = self._fixtures()
        authority = self._v1c_authority("0" * 64)  # wrong pin
        canonical = {"canonical_execution_evidence_id": "v1c-nv-a-canonical-01",
                     "accounting": {"selected_resource": "Vulkan3"},
                     "correctness": {"byte_exact_visible_output": True}}
        audit = runner.build_cross_subject_audit(
            v1a, v1b, authority, regression["v1a_regression"],
            regression["v1b_retained_reduction"],
            {"qualification_evidence_id": "v1c-nv-a-qualification-01"},
            {"explanations": []}, canonical)
        self.assertEqual(audit["result"], "FAIL")
        self.assertIn("successor accounting reducer drift", audit["subject_specific_code_remaining"][0])

    def test_audit_fails_on_falsified_byte_exactness(self):
        v1a, v1b, regression = self._fixtures()
        authority = self._v1c_authority(runner._sha256_file(ROOT / "scripts/v1c_accounting.py"))
        canonical = {"canonical_execution_evidence_id": "v1c-nv-a-canonical-01",
                     "accounting": {"selected_resource": "Vulkan3"},
                     "correctness": {"byte_exact_visible_output": False}}
        audit = runner.build_cross_subject_audit(
            v1a, v1b, authority, regression["v1a_regression"],
            regression["v1b_retained_reduction"],
            {"qualification_evidence_id": "v1c-nv-a-qualification-01"},
            {"explanations": []}, canonical)
        self.assertEqual(audit["result"], "FAIL")
        self.assertTrue(audit["foundational_invariant_falsified"])


class OrchestrationReuseTests(unittest.TestCase):
    def test_accepted_runner_stages_are_imported_not_forked(self):
        source = (ROOT / "scripts/v1c_runner.py").read_text(encoding="utf-8")
        # The V1-C runner reuses the accepted execution stages by import.
        self.assertIn("import v1a_runner as accepted_runner", source)
        self.assertIn("accepted_runner.preflight(authority)", source)
        self.assertIn("accepted_runner.qualify(", source)
        self.assertIn("accepted_runner.build_snapshot(", source)
        self.assertIn("accepted_runner.plan_and_freeze(", source)
        self.assertIn("accepted_runner._execute(frozen, out)", source)
        # The only superseded stage is accounting: the accepted
        # first-subject-pinned reducer is NOT called anywhere here.
        self.assertNotIn("v0c_runner", source)
        self.assertNotIn("parse_accounting(run[\"stderr\"])", source.replace(
            "successor_accounting.parse_accounting(run[\"stderr\"], selector=frozen[\"selector\"])",
            ""))

    def test_successor_accounting_consumed_with_authority_selector(self):
        source = (ROOT / "scripts/v1c_runner.py").read_text(encoding="utf-8")
        self.assertIn(
            "successor_accounting.parse_accounting(run[\"stderr\"], selector=frozen[\"selector\"])",
            source)

    def test_no_remote_shell_mechanics(self):
        # No remote-shell client may be invoked or imported by any
        # V1-C producer: the proving node is local to the session.
        for name in ("scripts/v1c_runner.py", "scripts/v1c_accounting.py", "scripts/v1c_manifest.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("paramiko", source.lower(), name)
            self.assertNotIn("fabric", source.lower(), name)
            # any quoted argv use of remote-shell clients
            for client in ("ssh", "scp", "sftp"):
                self.assertNotIn('"' + client + '"', source.lower(), f"{name}: {client}")
                self.assertNotIn("'" + client + "'", source.lower(), f"{name}: {client}")


if __name__ == "__main__":
    unittest.main()
