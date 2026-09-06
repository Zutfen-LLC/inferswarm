"""Tests for the issue #109 Gemma v5 mixture-population methodology freeze."""

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue109_v5_methodology_freeze as freeze
import validate_issue109_prerequisites as prerequisites
from issue74_methodology import MethodologyError, canonical_json_bytes


class MethodologyFreezeRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = freeze.build_record()

    def test_terminal_classification_is_frozen(self):
        self.assertEqual(
            self.record["terminal_classification"],
            "GEMMA_V5_CORRECTED_QUALIFICATION_METHODOLOGY_FROZEN",
        )

    def test_selection_is_validated_against_the_unchanged_108_contract(self):
        # A tamper of the accepted #108 contract must be rejected by the same
        # validator #109 uses to justify its selection.
        contract_path = freeze.doctrine.AREA / "statistical-contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        tampered = copy.deepcopy(contract)
        tampered["permitted_construction_classes"] = ["ONLY_ONE"]
        with self.assertRaises(freeze.doctrine.DoctrineError):
            freeze.doctrine.validate_prospective_methodology(freeze.prospective_methodology(), tampered)
        # The real accepted contract validates the real v5 selection.
        freeze.doctrine.validate_prospective_methodology(freeze.prospective_methodology(), contract)

    def test_prospective_methodology_is_the_declared_mixture_pooled_selection(self):
        methodology = self.record["prospective_methodology"]
        self.assertEqual(methodology["assumption_profile"], "MIXTURE_POPULATION_EXCHANGEABILITY")
        self.assertEqual(methodology["construction"], "POOLED_ORDER_STATISTIC_PREDICTION")
        self.assertEqual(methodology["qualification_claim"], "ZERO_EXCEEDANCE_CAMPAIGN_MIXTURE")
        self.assertTrue(methodology["declared_iid_mixture_target"])
        self.assertFalse(methodology["declared_named_strata"])
        self.assertFalse(methodology["claims_per_stratum_coverage"])

    def test_predictive_design_matches_committed_statistical_derivation(self):
        design = self.record["predictive_design"]
        self.assertEqual((design["calibration_cases"], design["holdout_cases"]), (1416, 24))
        self.assertGreaterEqual(design["zero_exceedance_probability_at_least"], 0.95)

    def test_comparator_contract_has_three_core_and_thirteen_telemetry(self):
        contract = self.record["comparator_tier_contract"]
        self.assertEqual(len(contract["core_numerical_pairs"]), 2)
        self.assertEqual(len(contract["mandatory_telemetry_pairs"]), 13)

    def test_disjointness_proof_is_clean(self):
        proof = self.record["disjointness_proof"]
        self.assertEqual(proof["verdict"], "HISTORICAL_EXCLUSION_PASS_PREDICTIVE_COLLISIONS_RETAINED")

    def test_holdout_is_sealed_but_custody_is_honestly_incomplete(self):
        holdout = self.record["holdout"]
        self.assertEqual(holdout["state"], "SEALED_NOT_CONSUMED")
        self.assertEqual(holdout["custody_state"], "SEALED_CUSTODY_INCOMPLETE")
        self.assertFalse(holdout["custody_satisfied"])

    def test_physical_work_is_not_authorized_or_performed(self):
        self.assertFalse(self.record["physical_campaign_authorized"])
        self.assertEqual(self.record["physical_execution"], "PROHIBITED_AND_NOT_PERFORMED")
        self.assertEqual(self.record["holdout_decryption"], "PROHIBITED_AND_NOT_PERFORMED")

    def test_disjointness_tamper_is_rejected(self):
        proof = copy.deepcopy(self.record["disjointness_proof"])
        proof["verdict"] = "OVERLAP_FOUND"
        with self.assertRaisesRegex(freeze.MethodologyFreezeError, "historical exclusion proof"):
            freeze.verify_disjointness(proof)

    def test_nonzero_overlap_row_is_rejected_even_with_the_stated_verdict(self):
        proof = copy.deepcopy(self.record["disjointness_proof"])
        proof["historical_comparisons"][0]["prompt_sha256_overlap"] = 1
        with self.assertRaisesRegex(freeze.MethodologyFreezeError, "nonzero overlap"):
            freeze.verify_disjointness(proof)

    def test_mixture_population_tamper_is_rejected(self):
        mixture = copy.deepcopy(self.record["mixture_population"])
        mixture["component_count"] = 23
        with self.assertRaisesRegex(freeze.MethodologyFreezeError, "does not match the frozen declaration"):
            freeze.verify_mixture_population(mixture)

    def test_comparator_contract_tamper_is_rejected(self):
        contract = copy.deepcopy(self.record["comparator_tier_contract"])
        contract["core_numerical_pairs"].pop()
        with self.assertRaisesRegex(freeze.MethodologyFreezeError, "not mechanically derived"):
            freeze.verify_comparator_contract(contract)

    def test_statistical_derivation_tamper_is_rejected(self):
        derivation = copy.deepcopy(self.record["predictive_design"])
        derivation["calibration_cases"] = 1000
        with self.assertRaisesRegex(freeze.MethodologyFreezeError, "not mechanically derived"):
            freeze.verify_statistical_derivation(derivation)

    def test_holdout_commitment_unsealed_state_is_rejected(self):
        commitment = json.loads((freeze.MANIFESTS / "sealed-holdout-commitment.json").read_text())
        commitment["state"] = "CONSUMED"
        with self.assertRaisesRegex(freeze.MethodologyFreezeError, "not sealed"):
            freeze.verify_holdout_and_custody(commitment=commitment)

    def test_holdout_custody_premature_authorization_is_rejected(self):
        custody = json.loads((freeze.MANIFESTS / "holdout-custody-record.json").read_text())
        custody["unseal_authorized"] = True
        with self.assertRaisesRegex(freeze.MethodologyFreezeError, "must not authorize unseal"):
            freeze.verify_holdout_and_custody(custody=custody)

    def test_record_is_deterministic_and_json_serializable(self):
        self.assertEqual(
            json.loads(json.dumps(self.record, sort_keys=True)),
            json.loads(json.dumps(freeze.build_record(), sort_keys=True)),
        )

    def test_immutable_prerequisite_byte_and_ancestry_drift_fail_closed(self):
        document = prerequisites.validate_prerequisites()
        for name in ("issue108_statistical_contract", "issue108_metric_classification", "adr0012", "issue83_semantic_contract"):
            tampered = copy.deepcopy(document)
            next(row for row in tampered["bindings"] if row["name"] == name)["sha256"] = "0" * 64
            with self.subTest(name=name), self.assertRaisesRegex(Exception, "prerequisite drift"):
                prerequisites.validate_prerequisites(tampered)
        tampered = copy.deepcopy(document)
        tampered["accepted_issue108_merge"] = "0" * 40
        with self.assertRaisesRegex(Exception, "wrong accepted #108 merge"):
            prerequisites.validate_prerequisites(tampered)


if __name__ == "__main__":
    unittest.main()
