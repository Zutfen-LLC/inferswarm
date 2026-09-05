"""Static contract tests for issue #93's prospective numerical-core doctrine."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs/qualification/post-v3-numerical-core-doctrine"
CONTRACT = ROOT / "docs/architecture/numerical-equivalence-contract.md"

FAMILY_MAP = ROOT / "docs/qualification/gemma4-12b-it-v1/manifests/checkpoint-family-map.json"


class Issue93NumericalCoreDoctrineTests(unittest.TestCase):
    def test_machine_classification_is_complete_and_tiered(self):
        payload = json.loads((AREA / "first-contract-classification.json").read_text())
        self.assertEqual(
            payload["terminal_disposition"],
            "NUMERICAL_CORE_TWO_TIER_DOCTRINE_ACCEPTED",
        )
        self.assertEqual(payload["classification_contract_version"], 1)
        self.assertTrue(payload["tier_change_requires_new_comparator_version"])
        self.assertEqual(payload["historical_contract"], "inferswarm.gemma4-heterogeneous-numerical-equivalence/1")
        entries = payload["families"]
        frozen_map = json.loads(FAMILY_MAP.read_text())
        frozen_pairs = {
            (checkpoint["family"], metric)
            for checkpoint in frozen_map["checkpoints"]
            for metric in checkpoint["mandatory_metrics"]
        }
        self.assertEqual(len(entries), len(frozen_pairs))
        self.assertEqual(
            {(entry["family"], entry["metric"]) for entry in entries},
            frozen_pairs,
        )
        self.assertTrue(all(entry["finite_required"] is True for entry in entries))
        self.assertEqual(
            {entry["tier"] for entry in entries},
            {"ACCEPTANCE_BEARING", "MANDATORY_TELEMETRY"},
        )
        consumer = [entry for entry in entries if entry["family"] == "fp32-consumer-logits"]
        self.assertTrue(all(entry["tier"] == "ACCEPTANCE_BEARING" for entry in consumer))
        self.assertEqual(
            {entry["tier"] for entry in entries if entry["family"] != "fp32-consumer-logits"},
            {"MANDATORY_TELEMETRY"},
        )
        self.assertIn("decision_local_E_D", payload["additional_acceptance_gates"])
        self.assertIn("exact_integrity", payload["preserved_invariants"])
        self.assertIn("finite_output", payload["preserved_invariants"])

    def test_decision_resolves_subsumption_and_telemetry_lifecycle(self):
        text = (AREA / "DECISION.md").read_text()
        for required in (
            "necessary operational rule",
            "downstream subsumption",
            "persistent or future-use state",
            "lossy semantic boundary",
            "DEGRADED",
            "does not turn a passing qualification into a failure",
            "new comparator/qualification contract version",
            "no threshold",
            "V3_HOLDOUT_FAIL",
        ):
            self.assertIn(required, text)

    def test_normative_contract_preserves_core_and_requires_prospective_tiers(self):
        text = CONTRACT.read_text()
        for required in (
            "acceptance-bearing numerical gates",
            "mandatory telemetry",
            "`E_full`",
            "`E_D`",
            "exact integrity",
            "finite output",
            "tier before physical calibration",
        ):
            self.assertIn(required, text)
        self.assertNotIn("matching semantic output cannot waive a failed mandatory numerical envelope.", text)


if __name__ == "__main__":
    unittest.main()
