"""Focused tests for the issue #117 V5 qualification-applicability barrier."""
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))

import issue117_applicability as applicability  # noqa: E402


class V5AuthorityIdentityTests(unittest.TestCase):
    def test_accepted_v5_files_are_byte_identical(self):
        record = applicability.verify_v5_authority(ROOT)
        self.assertEqual(record["verified_file_count"], len(applicability.V5_AUTHORITY_FILES))

    def test_terminal_adjudication_constant_matches_pinned_file(self):
        self.assertEqual(
            applicability.V5_AUTHORITY_FILES[
                "docs/qualification/gemma4-12b-it-v5-campaign-110/b/holdout-adjudication.json"],
            applicability.ACCEPTED_TERMINAL_ADJUDICATION_SHA256)

    def test_drifted_authority_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            name = "docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json"
            target = root / name
            target.parent.mkdir(parents=True)
            target.write_bytes(b'{"tampered": true}')
            with self.assertRaisesRegex(applicability.ApplicabilityBlocked, "drifted"):
                applicability.verify_v5_authority(root, files={
                    name: applicability.V5_AUTHORITY_FILES[name]})

    def test_missing_authority_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(applicability.ApplicabilityBlocked, "missing"):
                applicability.verify_v5_authority(Path(temp))


class AuditDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = applicability.canonical_issue117_audit()

    def test_covers_every_audited_surface_exactly_once(self):
        surfaces = [entry["surface"] for entry in self.audit["entries"]]
        self.assertEqual(sorted(surfaces), sorted(applicability.AUDITED_SURFACES))
        self.assertEqual(len(surfaces), len(set(surfaces)))

    def test_canonical_audit_is_control_artifact_materialization_only(self):
        self.assertEqual(
            applicability.validate_audit_document(self.audit),
            applicability.DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY)
        classes = {entry["classification"] for entry in self.audit["entries"]}
        self.assertNotIn(applicability.EXECUTION_MATH_AFFECTING, classes)
        self.assertNotIn(applicability.UNKNOWN, classes)

    def test_audit_is_self_consistent(self):
        again = applicability.canonical_issue117_audit()
        self.assertEqual(self.audit, again)

    def test_missing_surface_fails_closed(self):
        entries = [e for e in self.audit["entries"] if e["surface"] != "precision"]
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked, "missing"):
            applicability.build_audit_document(entries, authority=self.audit["authority"])

    def test_extra_surface_fails_closed(self):
        entries = list(self.audit["entries"]) + [
            {"surface": "not_a_real_surface", "classification": applicability.CONTROL_ONLY,
             "justification": "x"}]
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked, "extra"):
            applicability.build_audit_document(entries, authority=self.audit["authority"])

    def test_duplicated_surface_fails_closed(self):
        entries = list(self.audit["entries"]) + [dict(self.audit["entries"][0])]
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked, "duplicated"):
            applicability.build_audit_document(entries, authority=self.audit["authority"])

    def test_math_affecting_classification_requires_requalification(self):
        entries = [
            dict(entry) for entry in self.audit["entries"]
        ]
        for entry in entries:
            if entry["surface"] == "precision":
                entry["classification"] = applicability.EXECUTION_MATH_AFFECTING
        with self.assertRaisesRegex(
                applicability.ApplicabilityBlocked,
                applicability.R6_SUCCESSOR_REQUALIFICATION_REQUIRED):
            applicability.build_audit_document(entries, authority=self.audit["authority"])

    def test_unknown_classification_requires_requalification(self):
        entries = [dict(entry) for entry in self.audit["entries"]]
        for entry in entries:
            if entry["surface"] == "checkpoint_interpretation":
                entry["classification"] = applicability.UNKNOWN
        with self.assertRaisesRegex(
                applicability.ApplicabilityBlocked,
                applicability.R6_SUCCESSOR_REQUALIFICATION_REQUIRED):
            applicability.build_audit_document(entries, authority=self.audit["authority"])

    def test_undefined_classification_rejected(self):
        entries = [dict(entry) for entry in self.audit["entries"]]
        for entry in entries:
            if entry["surface"] == "prefill":
                entry["classification"] = "MAGIC_ONLY"
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked, "unknown classification"):
            applicability.build_audit_document(entries, authority=self.audit["authority"])

    def test_justification_required(self):
        entries = [dict(entry) for entry in self.audit["entries"]]
        for entry in entries:
            if entry["surface"] == "prefill":
                entry["justification"] = "  "
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked, "justification"):
            applicability.build_audit_document(entries, authority=self.audit["authority"])

    def test_tampered_frozen_audit_rejected(self):
        tampered = json.loads(json.dumps(self.audit))
        tampered["entries"][0]["classification"] = applicability.OBSERVABILITY_ONLY
        with self.assertRaises(applicability.ApplicabilityBlocked):
            applicability.validate_audit_document(tampered)


if __name__ == "__main__":
    unittest.main()
