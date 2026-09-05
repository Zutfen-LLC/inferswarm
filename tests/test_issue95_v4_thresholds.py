import copy
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from issue74_methodology import ENVELOPES, MethodologyError, canonical_json_bytes, sha256_bytes, sha256_file
from issue95_v4_contract import comparator_tier_contract
from issue95_v4_methodology import (
    CONTRACT_ID,
    MARGIN_DEFINITION,
    V4_SELECTION_STATE,
)
from issue95_v4_thresholds import derive_v4_threshold_artifacts


V4 = ROOT / "docs/qualification/gemma4-12b-it-v4"
MANIFESTS = V4 / "manifests"


def load(name):
    return json.loads((MANIFESTS / name).read_text())


class Issue95V4ThresholdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = load("calibration-corpus.json")
        cls.pool = load("stress-pool.json")
        cls.commitment = load("stress-selection-commitment.json")
        cls.holdout = load("sealed-holdout-commitment.json")
        cls.custody = load("holdout-custody-record.json")
        cls.contract = comparator_tier_contract()

    def evidence(self):
        corpus = copy.deepcopy(self.corpus)
        pool = copy.deepcopy(self.pool)
        commitment = copy.deepcopy(self.commitment)
        margins = {
            "schema": "inferswarm.issue95.v4-reference-margin-summary/1",
            "contract_id": CONTRACT_ID,
            "margin_definition": MARGIN_DEFINITION,
            "stress_pool_sha256": sha256_bytes(canonical_json_bytes(pool)),
            "cases": [
                {"case_id": case["case_id"], "case_sha256": case["case_sha256"],
                 "top1_margin_hex": float(index + 1).hex()}
                for index, case in enumerate(pool["cases"])
            ],
        }
        ranked = sorted(
            ((float.fromhex(row["top1_margin_hex"]), row["case_id"]) for row in margins["cases"]),
            key=lambda item: (item[0], item[1]),
        )
        selected_rows = []
        pool_by_id = {case["case_id"]: case for case in pool["cases"]}
        for group, rows in (("four-smallest-including-zero", ranked[:4]), ("four-largest", ranked[-4:])):
            selected_rows.extend({
                "selection_group": group, "case": pool_by_id[case_id],
                "reference_top1_margin_hex": margin.hex(), "exact_zero_margin": margin == 0.0,
            } for margin, case_id in rows)
        selected = {
            "schema": "inferswarm.issue95.v4-selected-stress-eighth/1", "contract_id": CONTRACT_ID,
            "margin_definition": MARGIN_DEFINITION,
            "margin_definition_unchanged_from": "v1 pre-registered producer definition (FreeToken 29e04d0)",
            "stress_pool_sha256": sha256_bytes(canonical_json_bytes(pool)),
            "selection_commitment_sha256": sha256_bytes(canonical_json_bytes(commitment)),
            "reference_margin_summary_sha256": sha256_bytes(canonical_json_bytes(margins)),
            "selection_inputs": "MATCHED_REFERENCE_MARGINS_ONLY",
            "eligibility_rule": commitment["eligibility_rule"], "selection_rule": commitment["selection_rule"],
            "minimum_eligible_cases": 8, "eligible_case_count": 48, "ineligible_case_count": 0,
            "ineligible_cases": [], "selected_count": 8, "selected": selected_rows,
            "state": V4_SELECTION_STATE,
        }
        self.assertEqual(selected["state"], V4_SELECTION_STATE)
        all_cases = corpus["cases"] + [row["case"] for row in selected["selected"]]
        domain_rows = []
        summary_rows = []
        for index, case in enumerate(all_cases):
            decisions = [
                {"decision_index": decision_index,
                 "domain_membership_sha256": f"{index * 8 + decision_index:064x}",
                 "domain_size": 1024,
                 "decision_local_error_hex": float((decision_index + 1) / 8).hex()}
                for decision_index in range(8)
            ]
            domain_rows.append({
                "case_id": case["case_id"], "case_sha256": case["case_sha256"],
                "decisions": [{key: row[key] for key in ("decision_index", "domain_membership_sha256", "domain_size")}
                              for row in decisions],
            })
            summary_rows.append({
                "case_id": case["case_id"], "case_sha256": case["case_sha256"],
                "exact_integrity": "PASS", "finite": True, "evidence_complete": True,
                "envelopes": {metric: float(index + 1).hex() for metric in ENVELOPES},
                "case_e_d_hex": float(1.0).hex(), "decisions": decisions,
            })
        domain = {
            "schema": "inferswarm.issue95.v4-decision-domain-manifest/1",
            "contract_id": CONTRACT_ID,
            "construction": "reference-top-1024-with-cutoff-ties/1", "k": 1024,
            "reference_derived_only": True, "candidate_membership_influence": "PROHIBITED",
            "statistical_cases": domain_rows[:1896], "stress_cases": domain_rows[1896:],
        }
        summary = {
            "schema": "inferswarm.issue95.v4-calibration-summary/1",
            "contract_id": CONTRACT_ID, "tooling_version": "inferswarm.issue95.v4-threshold-tooling/1",
            "calibration_corpus_sha256": sha256_bytes(canonical_json_bytes(corpus)),
            "stress_pool_sha256": sha256_bytes(canonical_json_bytes(pool)),
            "stress_selection_commitment_sha256": sha256_bytes(canonical_json_bytes(commitment)),
            "reference_margin_summary_sha256": sha256_bytes(canonical_json_bytes(margins)),
            "stress_selection_sha256": sha256_bytes(canonical_json_bytes(selected)),
            "decision_domain_manifest_sha256": sha256_bytes(canonical_json_bytes(domain)),
            "evidence_sha256": ["a" * 64],
            "statistical_cases": summary_rows[:1896], "stress_cases": summary_rows[1896:],
        }
        return corpus, pool, commitment, margins, selected, domain, summary

    def derive(self, **overrides):
        corpus, pool, commitment, margins, selected, domain, summary = self.evidence()
        values = {
            "calibration_corpus": corpus, "stress_pool": pool,
            "selection_commitment": commitment, "reference_margin_summary": margins,
            "selected_stress": selected, "decision_domain_manifest": domain,
            "calibration_summary": summary, "comparator_contract": copy.deepcopy(self.contract),
            "holdout_commitment": copy.deepcopy(self.holdout),
            "holdout_custody_record": copy.deepcopy(self.custody),
        }
        values.update(overrides)
        return derive_v4_threshold_artifacts(**values)

    def test_derives_four_core_limits_and_twelve_telemetry_bands_from_complete_evidence(self):
        result = self.derive()
        core = result["core_threshold_manifest"]
        telemetry = result["telemetry_reference_bands"]
        self.assertEqual(len(core["limits"]), 4)
        self.assertEqual(len(telemetry["bands"]), 12)
        self.assertEqual(core["limits"]["decision_local_E_D"]["limit_hex"], float(1.0).hex())
        self.assertEqual(core["limits"]["fp32-consumer-logits:max-absolute-difference"]["limit_hex"], float(1904).hex())
        self.assertEqual(telemetry["finite_exceedance"], "TELEMETRY_ALERT_NOT_QUALIFICATION_FAILURE")
        self.assertEqual(core["provenance"]["holdout_commitment_sha256"], sha256_bytes(canonical_json_bytes(self.holdout)))
        self.assertEqual(core["provenance"]["holdout_custody_record_sha256"], sha256_bytes(canonical_json_bytes(self.custody)))

    def test_deriver_binds_its_own_program_bytes(self):
        result = self.derive()
        self.assertEqual(result["core_threshold_manifest"]["provenance"]["derivation_program_sha256"], sha256_file(SCRIPTS / "issue95_v4_thresholds.py"))
        with self.assertRaises(TypeError):
            self.derive(program_sha256="0" * 64)

    def test_rejects_legacy_caller_supplied_maximum_maps(self):
        with self.assertRaises(TypeError):
            derive_v4_threshold_artifacts({"decision_local_E_D": 1.0}, {"decision_local_E_D": 1.0}, calibration_case_count=1896, selected_stress_count=8, provenance={})

    def test_rejects_nonfinite_or_incomplete_case_evidence(self):
        corpus, pool, commitment, margins, selected, domain, summary = self.evidence()
        summary["statistical_cases"][0]["envelopes"][ENVELOPES[0]] = math.inf.hex()
        with self.assertRaisesRegex(MethodologyError, "finite"):
            self.derive(calibration_summary=summary)
        summary = self.evidence()[-1]
        summary["statistical_cases"][0]["decisions"].pop()
        with self.assertRaisesRegex(MethodologyError, "8"):
            self.derive(calibration_summary=summary)

    def test_rejects_non_selector_selected_stress_and_domain_identity_drift(self):
        selected = self.evidence()[4]
        selected["selected"].reverse()
        with self.assertRaisesRegex(MethodologyError, "SELECTED_EIGHT_NOT_SELECTOR_DERIVED"):
            self.derive(selected_stress=selected)
        domain = self.evidence()[5]
        domain["statistical_cases"][0]["decisions"][0]["domain_size"] = 1
        summary = self.evidence()[-1]
        summary["decision_domain_manifest_sha256"] = sha256_bytes(canonical_json_bytes(domain))
        with self.assertRaisesRegex(MethodologyError, "domain"):
            self.derive(decision_domain_manifest=domain, calibration_summary=summary)

    def test_rejects_substituted_frozen_corpus_contract_or_holdout_identity(self):
        corpus = self.evidence()[0]
        corpus["cases"][0]["prompt_text"] += " substituted"
        with self.assertRaisesRegex(MethodologyError, "corpus hash mismatch"):
            self.derive(calibration_corpus=corpus)
        contract = copy.deepcopy(self.contract)
        contract["core_numerical_pairs"].pop()
        with self.assertRaisesRegex(MethodologyError, "contract"):
            self.derive(comparator_contract=contract)
        holdout = copy.deepcopy(self.holdout)
        holdout["state"] = "CONSUMED"
        with self.assertRaisesRegex(MethodologyError, "holdout"):
            self.derive(holdout_commitment=holdout)
        custody = copy.deepcopy(self.custody)
        custody["holdout_state"] = "CONSUMED"
        with self.assertRaisesRegex(MethodologyError, "holdout custody record hash mismatch"):
            self.derive(holdout_custody_record=custody)


if __name__ == "__main__":
    unittest.main()
