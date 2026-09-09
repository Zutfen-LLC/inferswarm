"""Focused tests for the issue #117 CPU integration-freeze campaign."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue117_applicability as applicability  # noqa: E402
import issue117_gemma_strategy as strategy  # noqa: E402
import issue117_integration_fixture as fixture  # noqa: E402
import issue117_planner as planner  # noqa: E402
import issue117_proof as proof  # noqa: E402

FIXTURE_PATH = ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
FIXTURE_PATH = FIXTURE_PATH / "evidence" / "integration-fixture.json"


def normalize_volatile(value):
    if isinstance(value, dict):
        return {key: normalize_volatile(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_volatile(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"/tmp/[^/\"]+", "<temporary>", value)
    return value


class ProofCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue117-proof-test-")
        cls.out = Path(cls.temp.name) / "evidence"
        cls.documents = proof.run_campaign(cls.out, fixture_path=FIXTURE_PATH)
        cls.summary = cls.documents["v5-qualification-subject-recovery.json"]

    def test_current_state_record_is_the_additive_recovery_record(self):
        self.assertEqual(self.summary["schema"],
                         "inferswarm.issue117.current-gate-state/1")
        self.assertEqual(self.summary["classification"],
                         "V5_QUALIFICATION_SUBJECT_PROVENANCE_RECOVERED")
        self.assertEqual(self.summary["checkpoint_authority"], "RECOVERED")
        self.assertEqual(self.summary["qualification_subject"], "RECOVERED")
        self.assertEqual(self.summary["current_issue117_state"],
                         "ISSUE117_IMPLEMENTATION_FREEZE_PENDING_RE_EVALUATION")
        self.assertEqual(self.summary["cpu_fixture_disposition"],
                         "ISSUE117_CPU_FIXTURE_PASS")
        self.assertFalse(self.summary["physical_preflight_executed"])
        self.assertFalse(self.summary["physical_arms_executed"])

    def test_accepted_118_canonical_summary_is_preserved_byte_exact(self):
        import hashlib
        committed = (ROOT / proof.AREA / "evidence" / "canonical-summary.json")
        self.assertEqual(
            hashlib.sha256(committed.read_bytes()).hexdigest(),
            proof.ACCEPTED_118_CANONICAL_SUMMARY_SHA256)
        historical = json.loads(committed.read_text())
        self.assertEqual(historical["terminal_disposition"],
                         "ISSUE117_IMPLEMENTATION_FREEZE_BLOCKED")
        # the additive record names the historical disposition it supersedes
        self.assertEqual(self.summary["issue117_previous_freeze_disposition"],
                         historical["terminal_disposition"])
        self.assertEqual(
            self.summary["accepted_118_canonical_summary_sha256"],
            "sha256:" + proof.ACCEPTED_118_CANONICAL_SUMMARY_SHA256)
        # the campaign never writes the historical file
        self.assertNotIn("canonical-summary.json", proof.EVIDENCE_FILES)
        self.assertIn("canonical-summary.json", proof.COMMITTED_EVIDENCE_FILES)

    def test_accepted_v5_geometry_selected_through_ordinary_gates(self):
        decision = self.documents["planner-decision.json"]
        record = self.documents["qualification-record.json"]
        v5_row = next(row for row in decision["candidates"]
                      if row["candidate_id"] == self.summary["selected_candidate_id"])
        self.assertEqual(v5_row["gates"]["qualification_applicability"]["status"],
                         planner.QUALIFICATION_APPLICABLE)
        self.assertEqual(v5_row["gates"]["qualification_applicability"]["matched_record_ids"],
                         [record["qualification_record_id"]])
        self.assertTrue(v5_row["gates"]["technical_feasibility"]["passed"])
        self.assertTrue(v5_row["gates"]["hard_policy_eligible"]["passed"])

    def test_qualification_record_is_fixture_scoped(self):
        record = self.documents["qualification-record.json"]
        self.assertEqual(record["scope"], "issue117-cpu-fixture")
        self.assertNotEqual(
            record["authority"]["terminal_adjudication_sha256"],
            applicability.ACCEPTED_TERMINAL_ADJUDICATION_SHA256)
        expected = proof.fixture_adjudication_identity(
            self.summary["fixture_digest"],
            record["qualification_subject_digest"])
        self.assertEqual(record["authority"]["terminal_adjudication_sha256"], expected)

    def test_every_other_candidate_is_excluded_with_reasons(self):
        decision = self.documents["planner-decision.json"]
        others = [row for row in decision["candidates"]
                  if row["candidate_id"] != self.summary["selected_candidate_id"]]
        self.assertTrue(others)
        for row in others:
            self.assertFalse(row["admissible"], row["candidate_id"])
            self.assertTrue(row["admission_failures"], row["candidate_id"])
        reasons = {reason for row in others for reason in row["admission_failures"]}
        self.assertIn(planner.REASON_SUBJECT_MISMATCH, reasons)
        self.assertIn("CAPACITY_INFEASIBLE", reasons)
        self.assertIn("HARD_POLICY_EXCLUSION", reasons)

    def test_explanations_are_retained(self):
        decision = self.documents["planner-decision.json"]
        dispositions = {entry["disposition"] for entry in decision["explanations"]}
        self.assertIn("SELECTED", dispositions)
        self.assertIn("EXCLUDED", dispositions)

    def test_cold_acquisition_is_participant_exact(self):
        cold = self.documents["cold-acquisition.json"]
        for participant, entry in cold["per_participant"].items():
            self.assertEqual(entry["transferred_bytes"],
                             sum(t["bytes"] for t in entry["transfers"]),
                             participant)
            self.assertLessEqual(entry["transferred_bytes"], entry["required_bytes"])
            for transfer in entry["transfers"]:
                self.assertEqual(transfer["source_id"], "issue117-origin")
                self.assertEqual(transfer["endpoint_scheme"], "file")

    def test_coordinator_bulk_bytes_are_zero_and_source_side_is_accounted(self):
        cold = self.documents["cold-acquisition.json"]
        self.assertEqual(cold["coordinator_bytes_observed"], 0)
        summary = self.summary
        self.assertGreater(summary["source_side_model_bytes_hashed"], 0)

    def test_warm_restart_reacquires_zero_weight_bytes(self):
        warm = self.documents["warm-restart.json"]
        self.assertEqual(warm["warm_restart_model_weight_transfer_bytes"], 0)
        hit_bytes = sum(entry["cache_hit_bytes"]
                        for entry in warm["per_participant"].values())
        self.assertGreater(hit_bytes, 0)

    def test_locality_mutation_changes_only_economics(self):
        mutation = self.documents["locality-mutation.json"]
        self.assertTrue(mutation["all_gates_unchanged"])
        self.assertTrue(mutation["economics_changed"])
        self.assertEqual(mutation["selected_candidate_id"],
                         self.summary["selected_candidate_id"])

    def test_zero_invariants_are_all_zero_and_complete(self):
        zero = self.documents["zero-invariants.json"]
        self.assertTrue(zero)
        for name, value in zero.items():
            self.assertEqual(value, 0, name)
        # the fencing counters are part of the derived zero-invariants
        for name in ("stale_result_committed", "wrong_session_result_committed",
                     "wrong_epoch_result_committed", "wrong_realization_result_committed",
                     "wrong_plan_result_committed", "wrong_contract_result_committed",
                     "wrong_position_result_committed",
                     "malformed_position_result_committed"):
            self.assertIn(name, zero)
        # the host-mirror/movement and control-plane byte invariants are derived
        self.assertIn("unexplained_persistent_host_mirror_bytes", zero)
        self.assertIn("unplanned_steady_state_model_state_movement_bytes", zero)
        self.assertIn("control_plane_document_byte_payloads", zero)

    def test_negative_controls_all_failed_closed(self):
        controls = self.documents["negative-controls.json"]["controls"]
        self.assertGreaterEqual(len(controls), 15)
        for entry in controls:
            self.assertTrue(entry["failed_closed"], entry["control"])
            self.assertTrue(entry["matched"], entry["control"])
        names = {entry["control"] for entry in controls}
        self.assertIn("changed_execution_producer_requires_requalification", names)
        self.assertIn("fence_ledger_derivation_is_non_vacuous", names)
        self.assertIn("staging_ledger_derivation_is_non_vacuous", names)
        self.assertIn(
            "accepted_v5_qualification_subject_provenance_recovered", names)
        self.assertIn(
            "accepted_subject_evidence_tampering_is_fail_closed", names)
        self.assertIn("lying_subject_digest_is_control_plane_misuse", names)
        self.assertIn("v5_authority_byte_tampering_is_fail_closed", names)

    def test_fencing_negatives_failed_closed(self):
        fencing = self.documents["fencing.json"]
        self.assertEqual(fencing["committed_results"],
                         2 * fencing["fixture_case_count"])
        self.assertTrue(fencing["all_negatives_failed_closed"])
        summary = fencing["summary"]
        for name in ("stale_result_committed", "wrong_session_result_committed",
                     "wrong_plan_result_committed", "wrong_epoch_result_committed",
                     "wrong_position_result_committed"):
            self.assertEqual(summary[name], 0, name)
        self.assertGreaterEqual(summary["fence_rejections"], 5)
        # every attempted result is retained (committed records + rejections)
        self.assertEqual(len(fencing["committed_result_records"]),
                         fencing["committed_results"])
        self.assertEqual(len(fencing["rejected_attempt_records"]),
                         summary["fence_rejections"])

    def test_witnesses_are_stable_across_restart(self):
        warm = self.documents["warm-restart.json"]
        self.assertEqual(warm["witnesses"],
                         self.documents["materialization-witnesses.json"])

    def test_purity_audit_is_clean(self):
        purity = self.documents["purity-audit.json"]
        self.assertEqual(purity["violations"], [])
        self.assertEqual(purity["planner_model_specific_branches"], 0)

    def test_applicability_audit_is_frozen_and_clean(self):
        audit = self.documents["applicability-audit.json"]
        self.assertEqual(audit, applicability.canonical_issue117_audit(ROOT))
        self.assertEqual(audit["overall_result"],
                         applicability.DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY)
        self.assertEqual(audit["authority"]["integration_producer"],
                         applicability.FROZEN_INTEGRATION_PRODUCER)

    def test_strategy_document_records_candidates_and_subjects(self):
        strategy_doc = self.documents["strategy.json"]
        self.assertEqual(strategy_doc["layer_count"], strategy.LAYER_COUNT)
        self.assertEqual(len(strategy_doc["candidates"]),
                         self.summary["candidate_count"])
        for candidate in strategy_doc["candidates"]:
            self.assertIn("qualification_subject_digest", candidate)
            self.assertIn("feasibility", candidate)
            self.assertEqual(candidate["feasibility"]["accounting_source"],
                             "exact_participant_requirements")

    def test_campaign_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temp:
            again = proof.run_campaign(Path(temp), fixture_path=FIXTURE_PATH)
        left = normalize_volatile(self.documents)
        right = normalize_volatile(again)
        self.assertEqual(left, right)

    def test_evidence_files_written_with_manifest(self):
        for name in proof.EVIDENCE_FILES:
            self.assertTrue((self.out / name).is_file(), name)
        manifest = (self.out / "MANIFEST.sha256").read_text()
        self.assertIn("v5-qualification-subject-recovery.json", manifest)
        for name in proof.COMMITTED_EVIDENCE_FILES:
            self.assertIn(name, manifest)
        # the frozen methodology is hash-bound (P2)
        self.assertIn(
            "docs/implementation/r6-successor-dense-full-integration-117/METHODOLOGY.md",
            manifest)

    def test_committed_retention_manifest_and_producer_hashes_match_checkout(self):
        evidence_root = ROOT / proof.AREA / "evidence"
        entries = {}
        for line in (evidence_root / "MANIFEST.sha256").read_text().splitlines():
            digest, relative = line.split("  ", 1)
            entries[relative] = digest
        expected_paths = {
            *(str(proof.AREA / "evidence" / name) for name in proof.EVIDENCE_FILES),
            *(str(proof.AREA / "evidence" / name)
              for name in proof.COMMITTED_EVIDENCE_FILES),
            *proof.PRODUCERS,
            str(proof.AREA / "METHODOLOGY.md"),
            str(proof.AREA / "README.md"),
            str(proof.AREA / "METHODOLOGY-ARM-C-RETRY.md"),
            str(proof.AREA / "CHECKPOINT-AUTHORITY-BLOCKER.md"),
            ".github/workflows/ci.yml",
        }
        self.assertEqual(set(entries), expected_paths)
        for relative, digest in entries.items():
            self.assertEqual(digest, proof.sha(ROOT / relative), relative)
        producer_hashes = json.loads((evidence_root / "producer-hashes.json").read_text())
        self.assertEqual(producer_hashes,
                         {path: proof.sha(ROOT / path) for path in proof.PRODUCERS})

    def test_future_state_updates_cannot_rewrite_the_historical_summary(self):
        # a mutated working-tree canonical-summary must abort the campaign:
        # current state belongs in the additive record only
        with tempfile.TemporaryDirectory() as temp:
            committed = (ROOT / proof.AREA / "evidence"
                         / "canonical-summary.json")
            original = committed.read_bytes()
            drifted = json.loads(original)
            drifted["terminal_disposition"] = "MUTATED"
            try:
                committed.write_text(json.dumps(drifted))
                with self.assertRaisesRegex(AssertionError, "drifted"):
                    proof.run_campaign(Path(temp), fixture_path=FIXTURE_PATH)
            finally:
                committed.write_bytes(original)

    def test_committed_documentation_synchronization_record(self):
        path = (ROOT / proof.AREA / "evidence"
                / "documentation-synchronization.json")
        record = json.loads(path.read_text())
        self.assertEqual(
            record["record_digest"],
            proof.self_digest(record, identity_field="record_digest"))
        self.assertEqual(len(record["facts_recorded"]), 12)


class CampaignFixtureBindingTests(unittest.TestCase):
    def test_committed_fixture_is_valid(self):
        document = json.loads(FIXTURE_PATH.read_text())
        fixture.validate_fixture_document(document)
        self.assertEqual(document["case_count"], 24)

    def test_retained_v5_qualification_authority_is_recovered(self):
        record = strategy.retained_v5_qualification_authority()
        self.assertEqual(record["authority"]["terminal_disposition"],
                         "V5_QUALIFICATION_PASS")
        self.assertEqual(
            record["authority"]["terminal_adjudication_sha256"],
            applicability.ACCEPTED_TERMINAL_ADJUDICATION_SHA256)

    def test_guard_rejects_complete_repository_requirement(self):
        with tempfile.TemporaryDirectory() as temp:
            world = proof.build_world(Path(temp))
            requirements = world["requirements"]
            total = strategy.checkpoint_weight_bytes(world["catalog"])
            planner.guard_participant_exact(requirements, total_model_weight_bytes=total)
            tampered = json.loads(json.dumps(requirements))
            for record in tampered["participants"][0]["required_artifacts"]:
                record["length"] = total
            with self.assertRaisesRegex(planner.PlannerError,
                                        "REQUIRES_COMPLETE_MODEL_REPOSITORY"):
                planner.guard_participant_exact(tampered, total_model_weight_bytes=total)


if __name__ == "__main__":
    unittest.main()
