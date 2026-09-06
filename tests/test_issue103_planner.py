"""Focused CPU proof tests for issue #103."""
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "scripts"))

import issue103_proof as proof  # noqa: E402


def normalize_volatile(value):
    if isinstance(value, dict):
        return {
            key: ("<volatile-digest>" if key == "evidence_digest"
                  else normalize_volatile(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [normalize_volatile(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"/tmp/issue103-cpu-[^/]+", "<temporary>", value)
        return value
    return value


class PlannerProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue103-proof-test-")
        cls.out = Path(cls.temp.name) / "evidence"
        cls.documents = proof.run_campaign(cls.out)
        cls.summary = cls.documents["canonical-summary.json"]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_terminal_pass_and_zero_invariants(self):
        self.assertEqual(self.summary["terminal_disposition"],
                         "ARTIFACT_LOCALITY_TRANSITION_PLANNING_PASS")
        self.assertEqual(self.summary["zero_invariants"], {
            "artifact_locality_changed_technical_feasibility": 0,
            "planner_model_specific_branches": 0,
            "unexplained_transition_bytes": 0,
            "ranking_input_without_frozen_provenance": 0,
            "coordinator_bulk_artifact_bytes_observed": 0,
            "unverified_state_used_as_locality_evidence": 0,
            "unauthorized_source_used_for_ranking": 0,
            "objective_cross_contamination_events": 0,
        })

    def test_transition_costs_and_rankings_for_both_inventory_arms(self):
        decisions = self.documents["objective-decisions.json"]
        self.assertEqual(decisions["arm_a"]["MIN_TRANSITION_COST"]["costs"],
                         {"A": 0.5, "B": 1.0, "C": 3.0})
        self.assertEqual(decisions["arm_a"]["MIN_TRANSITION_COST"]["ranking_order"],
                         ["A", "B", "C"])
        self.assertEqual(decisions["arm_b"]["MIN_TRANSITION_COST"]["costs"],
                         {"A": 0.5, "B": 1.0, "C": 0.0})
        self.assertEqual(decisions["arm_b"]["MIN_TRANSITION_COST"]["ranking_order"],
                         ["C", "A", "B"])

    def test_execution_objective_is_independent_of_locality(self):
        decisions = self.documents["objective-decisions.json"]
        for arm in ("arm_a", "arm_b"):
            self.assertEqual(decisions[arm]["WARM_DECODE_THROUGHPUT"]["selected_candidate_id"], "B")
            self.assertEqual(decisions[arm]["WARM_DECODE_THROUGHPUT"]["ranking_order"],
                             ["B", "C", "A"])

    def test_technical_feasibility_is_byte_identical_across_inventory_mutation(self):
        economics = self.documents["candidate-economics.json"]
        self.assertEqual(economics["arm_a"]["legal_candidate_ids"], ["A", "B", "C"])
        self.assertEqual(economics["arm_a"]["technical_feasibility"],
                         economics["arm_b"]["technical_feasibility"])
        self.assertEqual(economics["arm_a"]["legal_candidate_ids"],
                         economics["arm_b"]["legal_candidate_ids"])
        self.assertEqual(
            economics["arm_a"]["legal_candidate_set_and_feasibility"]["contract_digest"],
            economics["arm_b"]["legal_candidate_set_and_feasibility"]["contract_digest"],
        )

    def test_missing_evidence_is_feasible_unranked(self):
        controls = self.documents["negative-controls.json"]["controls"]
        for name in ("missing_path_bandwidth_evidence", "nonpositive_bandwidth",
                     "nonfinite_bandwidth", "wrong_target_applicability"):
            self.assertEqual(controls[name]["ranking_status"], "FEASIBLE_UNRANKED")
            self.assertTrue(controls[name]["technical_feasibility"])

    def test_all_adversarial_controls_are_retained(self):
        controls = self.documents["negative-controls.json"]["controls"]
        expected = {
            "unverified_local_object", "corrupt_local_object_after_verification",
            "stale_peer_advertisement", "unauthorized_source",
            "same_source_id_drifted_descriptor", "missing_path_bandwidth_evidence",
            "nonpositive_bandwidth", "nonfinite_bandwidth", "wrong_target_applicability",
            "candidate_order_permutation", "locality_feasibility_mutation",
            "objective_contamination_mutation", "unexplained_transfer_injection",
            "stale_ranking_provenance",
        }
        self.assertEqual(set(controls), expected)
        self.assertTrue(all(control["passed"] for control in controls.values()))

    def test_tie_breaking_is_independent_of_input_order(self):
        evidence = self.documents["tie-permutation.json"]
        self.assertEqual(evidence["selected_by_permutation"], {"ABC": "A", "CBA": "A"})
        self.assertEqual(evidence["ranking_by_permutation"]["ABC"],
                         evidence["ranking_by_permutation"]["CBA"])

    def test_frozen_evidence_regenerates_deterministically(self):
        with tempfile.TemporaryDirectory() as rerun:
            regenerated = proof.run_campaign(Path(rerun) / "evidence")
        for name in ("strategy.json", "requirements.json", "path-evidence.json",
                     "objective-decisions.json", "negative-controls.json",
                     "canonical-summary.json"):
            self.assertEqual(normalize_volatile(self.documents[name]),
                             normalize_volatile(regenerated[name]), name)


class RetainedEvidenceTests(unittest.TestCase):
    def test_committed_evidence_exists_and_matches_manifest(self):
        evidence = ROOT / "docs/implementation/artifact-locality-transition-planning-103/evidence"
        for path in evidence.glob("*.json"):
            self.assertTrue(path.is_file(), path.name)
        self.assertTrue((evidence / "MANIFEST.sha256").is_file())
        for line in (evidence / "MANIFEST.sha256").read_text().splitlines():
            digest, _, relative = line.partition("  ")
            target = ROOT / relative
            self.assertTrue(target.is_file(), relative)
            self.assertEqual(proof.sha(target), digest, relative)

    def test_committed_summary_records_isolation_and_non_claims(self):
        path = ROOT / "docs/implementation/artifact-locality-transition-planning-103/evidence/canonical-summary.json"
        summary = json.loads(path.read_text())
        self.assertEqual(summary["terminal_disposition"],
                         "ARTIFACT_LOCALITY_TRANSITION_PLANNING_PASS")
        self.assertTrue(summary["isolation"]["cpu_only"])
        self.assertFalse(summary["isolation"]["freetoken_tree_modified"])
        self.assertFalse(summary["isolation"]["issue97_evidence_touched"])
        self.assertTrue(summary["non_claims"])


if __name__ == "__main__":
    unittest.main()
