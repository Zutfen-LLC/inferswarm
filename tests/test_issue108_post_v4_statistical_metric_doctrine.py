"""Tests for the issue #108 post-v4 statistical and metric doctrine."""

import copy
import json
import sys
import unittest
from pathlib import Path


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

    def test_v4_style_claim_is_rejected_under_within_cell_only(self):
        contract = copy.deepcopy(self.record["statistical_contract"])
        contract["assumption_profile"] = "WITHIN_NAMED_STRATUM_EXCHANGEABILITY"
        contract["construction"] = "POOLED_CALIBRATION_MAXIMUM"
        with self.assertRaisesRegex(
                doctrine.DoctrineError, "UNSUPPORTED_POOLED_MAXIMUM_CLAIM"):
            doctrine.validate_statistical_contract(contract)

    def test_historical_source_hash_drift_is_rejected(self):
        bindings = copy.deepcopy(self.record["source_bindings"])
        bindings["historical_inputs"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(
                doctrine.DoctrineError, "HISTORICAL_SOURCE_HASH_DRIFT"):
            doctrine.verify_source_bindings(bindings)

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
