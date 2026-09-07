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
        return re.sub(r"/tmp/issue117-cpu-[^/]+", "<temporary>", value)
    return value


class ProofCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue117-proof-test-")
        cls.out = Path(cls.temp.name) / "evidence"
        cls.documents = proof.run_campaign(cls.out, fixture_path=FIXTURE_PATH)
        cls.summary = cls.documents["canonical-summary.json"]

    def test_terminal_disposition_is_implementation_freeze_pass(self):
        self.assertEqual(self.summary["terminal_disposition"],
                         "ISSUE117_IMPLEMENTATION_FREEZE_PASS")

    def test_v5_candidate_selected_through_ordinary_gates(self):
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

    def test_coordinator_bulk_bytes_are_zero(self):
        cold = self.documents["cold-acquisition.json"]
        self.assertEqual(cold["coordinator_bytes_observed"], 0)

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

    def test_negative_controls_all_failed_closed(self):
        controls = self.documents["negative-controls.json"]["controls"]
        self.assertGreaterEqual(len(controls), 10)
        for entry in controls:
            self.assertTrue(entry["failed_closed"], entry["control"])
            self.assertTrue(entry["matched"], entry["control"])

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
        self.assertEqual(audit, applicability.canonical_issue117_audit())
        self.assertEqual(audit["overall_result"],
                         applicability.DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY)

    def test_strategy_document_records_candidates_and_subjects(self):
        strategy_doc = self.documents["strategy.json"]
        self.assertEqual(strategy_doc["layer_count"], strategy.LAYER_COUNT)
        self.assertEqual(len(strategy_doc["candidates"]),
                         self.summary["candidate_count"])
        for candidate in strategy_doc["candidates"]:
            self.assertIn("qualification_subject_digest", candidate)
            self.assertIn("feasibility", candidate)

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
        self.assertIn("canonical-summary.json", manifest)


class CampaignFixtureBindingTests(unittest.TestCase):
    def test_committed_fixture_is_valid(self):
        document = json.loads(FIXTURE_PATH.read_text())
        fixture.validate_fixture_document(document)
        self.assertEqual(document["case_count"], 24)

    def test_qualification_record_binds_terminal_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            world = proof.build_world(Path(temp))
            record = world["qualification_record"]
        self.assertEqual(record["authority"]["terminal_disposition"],
                         "V5_QUALIFICATION_PASS")
        self.assertEqual(record["authority"]["terminal_adjudication_sha256"],
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
