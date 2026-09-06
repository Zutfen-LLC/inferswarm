"""Tests for the issue #108 post-v4 statistical and metric doctrine."""

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue108_post_v4_statistical_metric_doctrine as doctrine


class DoctrineRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = doctrine.build_record()

    def test_terminal_classification_is_accepted(self):
        self.assertEqual(
            self.record["terminal_classification"],
            "POST_V4_STATISTICAL_METRIC_DOCTRINE_ACCEPTED",
        )

    def test_mixture_campaign_identity_is_exact(self):
        self.assertEqual(
            doctrine.campaign_max_exceedance_probability(
                calibration_cases=1896, holdout_cases=24),
            1 / 80,
        )

    def test_named_strata_union_identity_covers_each_holdout_path(self):
        self.assertAlmostEqual(
            doctrine.stratified_campaign_exceedance_upper_bound(
                calibration_cases_per_stratum=[79] * 24,
                holdout_cases_per_stratum=[1] * 24),
            24 / 80,
        )

    def prospective_methodology(self, **changes):
        methodology = {
            "assumption_profile": "MIXTURE_POPULATION_EXCHANGEABILITY",
            "construction": "POOLED_ORDER_STATISTIC_PREDICTION",
            "qualification_claim": "ZERO_EXCEEDANCE_CAMPAIGN_MIXTURE",
            "declared_iid_mixture_target": True,
            "declared_named_strata": False,
            "claims_per_stratum_coverage": False,
        }
        methodology.update(changes)
        return methodology

    def test_contract_does_not_select_a_v5_construction(self):
        contract = self.record["statistical_contract"]
        self.assertNotIn("assumption_profile", contract)
        self.assertNotIn("construction", contract)

    def test_pooled_construction_is_rejected_under_within_stratum_only(self):
        with self.assertRaisesRegex(
                doctrine.DoctrineError, "INCOMPATIBLE_ASSUMPTION_CONSTRUCTION"):
            doctrine.validate_prospective_methodology(
                self.prospective_methodology(
                    assumption_profile="WITHIN_NAMED_STRATUM_EXCHANGEABILITY",
                    declared_iid_mixture_target=False,
                    declared_named_strata=True,
                ),
                self.record["statistical_contract"],
            )

    def test_pooled_mixture_claim_cannot_claim_per_stratum_coverage(self):
        with self.assertRaisesRegex(
                doctrine.DoctrineError,
                "MIXTURE_DOES_NOT_ESTABLISH_PER_STRATUM_COVERAGE"):
            doctrine.validate_prospective_methodology(
                self.prospective_methodology(claims_per_stratum_coverage=True),
                self.record["statistical_contract"],
            )

    def test_undeclared_cross_stratum_exchangeability_is_rejected(self):
        with self.assertRaisesRegex(
                doctrine.DoctrineError,
                "UNDECLARED_CROSS_STRATUM_EXCHANGEABILITY"):
            doctrine.validate_prospective_methodology(
                self.prospective_methodology(declared_iid_mixture_target=False),
                self.record["statistical_contract"],
            )

    def test_unpermitted_construction_is_rejected(self):
        with self.assertRaisesRegex(
                doctrine.DoctrineError, "UNPERMITTED_CONSTRUCTION_CLASS"):
            doctrine.validate_prospective_methodology(
                self.prospective_methodology(construction="UNSUPPORTED_CONSTRUCTION"),
                self.record["statistical_contract"],
            )

    def test_every_permitted_compatibility_is_prospectively_valid(self):
        contract = self.record["statistical_contract"]
        for entry in contract["compatibility_constraints"]:
            mixture = entry["assumption_profile"] == (
                "MIXTURE_POPULATION_EXCHANGEABILITY")
            doctrine.validate_prospective_methodology(
                self.prospective_methodology(
                    assumption_profile=entry["assumption_profile"],
                    construction=entry["construction"],
                    qualification_claim=entry["qualification_claims"][0],
                    declared_iid_mixture_target=mixture,
                    declared_named_strata=not mixture,
                ),
                contract,
            )

    def test_every_allowed_construction_has_a_complete_comparison(self):
        contract = self.record["statistical_contract"]
        comparison = contract["construction_comparison"]
        self.assertEqual(
            set(comparison), set(contract["permitted_construction_classes"]),
        )
        for entry in comparison.values():
            for field in (
                    "assumptions", "finite_sample_guarantee",
                    "familywise_composition", "sample_burden_scaling",
                    "failure_modes"):
                self.assertTrue(entry[field], field)

    def test_historical_source_hash_drift_is_rejected(self):
        bindings = copy.deepcopy(self.record["source_bindings"])
        bindings["historical_inputs"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(
                doctrine.DoctrineError, "HISTORICAL_SOURCE_HASH_DRIFT"):
            doctrine.verify_source_bindings(bindings)

    def test_retained_raw_row_hash_drift_is_rejected(self):
        raw_row = doctrine.REPO_ROOT / (
            "docs/qualification/gemma4-12b-it-post-v4-core-diagnosis/raw/"
            "h95-01-01-01/ref-decision-0.f32"
        )
        original_sha256_file = doctrine.sha256_file

        def drift_raw_row(path):
            if path == raw_row:
                return "0" * 64
            return original_sha256_file(path)

        with mock.patch.object(doctrine, "sha256_file", side_effect=drift_raw_row):
            with self.assertRaisesRegex(
                    doctrine.DoctrineError, "RETAINED_RAW_EVIDENCE_HASH_DRIFT"):
                doctrine.verify_source_bindings(self.record["source_bindings"])

    def test_missing_retained_raw_file_is_rejected(self):
        retention_path = doctrine.REPO_ROOT / doctrine.RETENTION_MANIFEST
        retention_manifest = json.loads(retention_path.read_text(encoding="utf-8"))
        retention_manifest["retained_durable_repo"]["files"][0]["path"] = (
            "docs/qualification/gemma4-12b-it-post-v4-core-diagnosis/raw/"
            "h95-01-01-01/missing-decision-0.f32"
        )
        with self.assertRaisesRegex(
                doctrine.DoctrineError, "RETAINED_RAW_EVIDENCE_FILE_MISSING"):
            doctrine.verify_retained_raw_evidence(retention_manifest)

    def test_metric_core_retires_p99_from_acceptance(self):
        metrics = self.record["metric_core_classification"]["metrics"]
        by_id = {metric["identity"]: metric for metric in metrics}
        self.assertEqual(
            by_id["fp32-consumer-logits:p99-absolute-error"]["tier"],
            "MANDATORY_TELEMETRY",
        )
        self.assertEqual(
            by_id["fp32-consumer-logits:max-absolute-difference"]["tier"],
            "ACCEPTANCE_BEARING",
        )
        self.assertEqual(
            by_id["decision_local_E_D"]["tier"],
            "ACCEPTANCE_BEARING",
        )

    def test_capture_rule_requires_every_canonical_decision(self):
        rule = self.record["metric_core_classification"]["capture_position_rule"]
        self.assertEqual(rule["current_gemma_profile"], "ALL_8_CANONICAL_DECISIONS")
        self.assertTrue(rule["subset_permitted_for_current_gemma_profile"] is False)

    def test_record_is_deterministic_and_json_serializable(self):
        self.assertEqual(
            json.loads(json.dumps(self.record, sort_keys=True)),
            json.loads(json.dumps(doctrine.build_record(), sort_keys=True)),
        )


if __name__ == "__main__":
    unittest.main()
