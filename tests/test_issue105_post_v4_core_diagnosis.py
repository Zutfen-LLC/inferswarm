"""Tests for the issue #105 post-v4 core-diagnosis tool (CPU-only).

Two layers:
  1. real-evidence tests: the tool builds the full diagnosis from the
     committed pinned bytes and every asserted number re-derives;
  2. fail-closed negative controls: each mutation of a pinned input
     (committed or raw-row byte) is rejected with a hash-drift error;
     the classification logic is exercised on synthetic conditions.
"""

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue105_post_v4_core_diagnosis as diag


class RealEvidenceTests(unittest.TestCase):
    """The tool consumes the actual committed evidence."""

    @classmethod
    def setUpClass(cls):
        cls.record = diag.build_diagnosis()

    def test_classification_is_mixed(self):
        self.assertEqual(
            self.record["classification"], "V4_CORE_DIAGNOSIS_MIXED")

    def test_classification_conditions_derived(self):
        basis = self.record["classification_basis"]
        self.assertTrue(basis["single_case_dominates"])
        self.assertTrue(basis["ordinary_tail_supported"])
        self.assertTrue(basis["metric_design_contribution"])
        self.assertTrue(basis["contract_gap_present"])
        self.assertFalse(basis["execution_anomaly"])

    def test_p99_reproduced_from_raw_bytes(self):
        obs = self.record["failing_observation"]
        self.assertEqual(obs["p99_reproduced"], 16.765625)
        self.assertEqual(obs["p99_limit"], 16.640625)
        self.assertEqual(obs["p99_exceedance_absolute"], 0.125)
        self.assertEqual(obs["p99_max_decision_index"], 3)
        self.assertEqual(obs["row_element_count"], 262144)
        self.assertEqual(obs["dtype"], "float32")
        self.assertTrue(obs["row_sha256"] if "row_sha256" in obs else True)

    def test_all_core_envelopes_reproduce(self):
        obs = self.record["failing_observation"]
        self.assertEqual(obs["max_abs_envelope_reproduced"], 23.296875)
        self.assertEqual(
            obs["rms_envelope_reproduced"], 8.920099737721817)
        self.assertEqual(
            float.fromhex(obs["case_e_d_hex"]), 20.875)

    def test_rows_are_producer_bound(self):
        # reconstruct_failing_observation already asserts every staged row
        # equals the producer record's row_f32_sha256; here we re-derive
        # one independently.
        ref_case = json.loads(
            (ROOT / diag.RAW / "reference-case-href95.json").read_text())
        d3 = ref_case["decisions"][3]
        path = ROOT / diag.RAW / "ref-decision-3.f32"
        self.assertEqual(
            diag.sha256_file(path), d3["row_f32_sha256"])

    def test_p99_knife_edge_mechanism(self):
        obs = self.record["failing_observation"]
        self.assertEqual(obs["elements_over_p99_limit"], 2854)
        self.assertGreater(obs["fraction_over_p99_limit"], 0.01)
        self.assertLess(obs["fraction_over_p99_limit"], 0.011)
        self.assertEqual(obs["p99_plateau"]["count"], 10)
        # exceedance is exactly one lattice step
        self.assertEqual(obs["p99_exceedance_absolute"], 0.125)
        self.assertEqual(obs["tail_min_increment"], 0.000244140625)

    def test_family_distributions_complete(self):
        fams = self.record["family_distributions"]["families"]
        self.assertEqual(len(fams), 4)
        for fam, data in fams.items():
            self.assertEqual(data["statistical"]["n"], 1896)
            self.assertEqual(data["stress"]["n"], 8)
            self.assertEqual(data["holdout"]["n"], 24)
            self.assertTrue(data["statistical"]["limit_equals_stat_max"])
        p99 = fams["fp32-consumer-logits:p99-absolute-error"]
        self.assertEqual(p99["holdout"]["exceedances"], 1)
        for fam in ("fp32-consumer-logits:max-absolute-difference",
                    "fp32-consumer-logits:rms-difference",
                    "decision_local_E_D"):
            self.assertEqual(fams[fam]["holdout"]["exceedances"], 0)

    def test_cross_family_collinearity(self):
        corr = self.record["family_distributions"]["cross_family_spearman"]
        self.assertEqual(len(corr), 6)
        for pair, value in corr.items():
            self.assertGreater(value, 0.9, pair)

    def test_no_prospective_split(self):
        audit = self.record["applicability_split_audit"]
        self.assertIn("NO_PROSPECTIVE_SPLIT", audit["split_verdict"])
        cell = audit["failing_case_cell"]
        self.assertEqual(cell["content_class"], "ordinary-prose")
        self.assertEqual(cell["length_regime"], [4, 8])
        self.assertEqual(cell["cell_max_rank_among_24_cells"], 14)
        self.assertEqual(cell["cell_max_p99"], 11.0078125)
        self.assertAlmostEqual(
            audit["spearman_token_count_vs_p99"], 0.1132, places=3)

    def test_downstream_trace(self):
        trace = self.record["downstream_trace"]
        self.assertEqual(
            trace["semantic_totals"]["SEMANTIC_PASS"], 192)
        self.assertEqual(trace["semantic_totals"]["total"], 192)
        self.assertEqual(
            trace["telemetry_alert_case_ids"], ["h95-01-01-01"])
        profiles = trace["over_limit_profiles"]
        self.assertEqual(
            profiles["p99_decision"]["inside_top1024_domain"], 0)
        self.assertEqual(profiles["p99_decision"]["count"], 2854)
        self.assertEqual(
            profiles["worst_e_d_decision"]["decision_index"], 7)
        self.assertTrue(trace["worst_decision_domain_still_under_E_D_limit"])
        for d in trace["per_decision"]:
            self.assertTrue(d["decision_local_matches_committed"])
            self.assertEqual(d["verdict"], "SEMANTIC_PASS")

    def test_contract_audit_numbers(self):
        audit = self.record["statistical_contract_audit"]
        self.assertTrue(audit["frozen_replay_reproduced"])
        self.assertTrue(audit["correct_bounds"]["distribution_free_bound_vacuous"])
        self.assertAlmostEqual(
            audit["correct_bounds"]["familywise_full_cross_cell_homogeneity"],
            96.0 / 1897.0, places=12)
        self.assertEqual(
            audit["correct_bounds"]
            ["cases_per_cell_needed_distribution_free_95"], 1919)
        gap = audit["gap_analysis"]
        self.assertEqual(gap["failing_cell_max_rank_of_24"], 14)
        self.assertEqual(gap["global_p99_max_cell"]["content_class"],
                         "mathematics-numerals")

    def test_reducer_audit(self):
        audit = self.record["p99_reducer_audit"]
        self.assertIn("REQUIRE_DOCTRINE_REVIEW",
                      audit["diagnostic_conclusion"])
        self.assertTrue(
            audit["discretization"]["exceedance_equals_local_lattice_spacing"])
        self.assertEqual(
            audit["discretization"]["tail_min_increment"], 0.000244140625)
        self.assertEqual(
            audit["discretization"]["p99_magnitude_lattice_spacing"], 0.125)
        self.assertTrue(
            audit["position_subsampling_note"]
            ["decision2_would_exceed_max_abs_limit"])
        self.assertGreater(audit["correlations"]["vs_max_abs"], 0.98)

    def test_cross_campaign(self):
        cross = self.record["cross_campaign_comparison"]
        self.assertFalse(cross["same_cell"])
        self.assertFalse(cross["same_family"])
        self.assertEqual(cross["v3_failing"]["case_id"], "h86-03-05-01")
        self.assertEqual(cross["v3_failing"]["rank_above_all_calibration"], 1)
        self.assertEqual(cross["v3_failing"]["calibration_n"], 584)
        self.assertAlmostEqual(
            cross["v4_failing"]["runner_up_ratio"], 16.765625 / 5.25)

    def test_non_claims_present(self):
        self.assertEqual(len(self.record["non_claims"]), 6)

    def test_successor_directions_no_parameters(self):
        text = json.dumps(self.record["successor_directions"])
        self.assertIn("no parameters", text.lower())
        self.assertEqual(
            len(self.record["successor_directions"]["directions"]), 6)

    def test_provenance_binds_producers(self):
        accepted = self.record["provenance"]["accepted"]
        self.assertEqual(accepted["phase_a_calibration_producer"],
                         "57dfcb7289efac8f66de5b3abbe8de04f2580f75")
        self.assertEqual(accepted["phase_b_holdout_producer"],
                         "c60a4b7080913eba90585de8e8602460a7f5b1a7")
        self.assertEqual(
            len(self.record["provenance"]["pinned_rows_sha256"]), 16)
        self.assertEqual(
            len(self.record["provenance"]["node_retained_capture_bundles"]), 4)

    def test_record_is_deterministic(self):
        again = json.loads(json.dumps(self.record))
        rebuilt = diag.build_diagnosis()
        self.assertEqual(again, json.loads(json.dumps(rebuilt)))


class FailClosedTests(unittest.TestCase):
    """Every mutation of a pinned input must be rejected."""

    def test_raw_row_byte_mutation_rejected(self):
        path = ROOT / diag.RAW / "ref-decision-3.f32"
        original = path.read_bytes()
        mutated = bytearray(original)
        mutated[0] ^= 0x01
        try:
            path.write_bytes(bytes(mutated))
            with self.assertRaisesRegex(
                    diag.DiagnosisError, "RAW_ROW_HASH_DRIFT"):
                diag.build_diagnosis()
        finally:
            path.write_bytes(original)
        # restored: passes again
        self.assertIsNotNone(diag.build_diagnosis())

    def test_row_size_mutation_rejected(self):
        path = ROOT / diag.RAW / "cand-decision-7.f32"
        original = path.read_bytes()
        try:
            path.write_bytes(original[:-4])
            with self.assertRaisesRegex(
                    diag.DiagnosisError, "RAW_ROW"):
                diag.build_diagnosis()
        finally:
            path.write_bytes(original)

    def test_pinned_evidence_drift_rejected(self):
        # monkeypatch the pinned digest for one committed artifact
        rel = f"{diag.C97}/b/holdout-rows.json"
        original = diag.PINNED_FILE_SHA256[rel]
        diag.PINNED_FILE_SHA256[rel] = "0" * 64
        try:
            with self.assertRaisesRegex(
                    diag.DiagnosisError, "PINNED_EVIDENCE_HASH_DRIFT"):
                diag.build_diagnosis()
        finally:
            diag.PINNED_FILE_SHA256[rel] = original

    def test_pinned_row_digest_drift_rejected(self):
        original = diag.PINNED_ROW_SHA256["ref-decision-0.f32"]
        diag.PINNED_ROW_SHA256["ref-decision-0.f32"] = "1" * 64
        try:
            with self.assertRaisesRegex(
                    diag.DiagnosisError, "RAW_ROW_HASH_DRIFT"):
                diag.build_diagnosis()
        finally:
            diag.PINNED_ROW_SHA256["ref-decision-0.f32"] = original

    def test_producer_record_binding_rejected_on_swap(self):
        # swapping two staged candidate rows must be caught either by the
        # pin (file names) or by the producer-record binding
        d = ROOT / diag.RAW
        a = (d / "cand-decision-5.f32").read_bytes()
        b = (d / "cand-decision-6.f32").read_bytes()
        if a == b:
            self.skipTest("identical rows")
        try:
            (d / "cand-decision-5.f32").write_bytes(b)
            (d / "cand-decision-6.f32").write_bytes(a)
            with self.assertRaises(diag.DiagnosisError):
                diag.build_diagnosis()
        finally:
            (d / "cand-decision-5.f32").write_bytes(a)
            (d / "cand-decision-6.f32").write_bytes(b)

    def test_classify_logic_on_synthetic_conditions(self):
        base = {
            "single_case_dominates": True,
            "ordinary_tail_supported": True,
            "metric_design_contribution": True,
            "contract_gap_present": True,
            "execution_anomaly": False,
        }
        # full basis -> MIXED
        self.assertEqual(
            diag.classify(
                {"p99_max_decision_index": 3,
                 "p99_reproduced": 16.765625},
                {"split_verdict": "NO_PROSPECTIVE_SPLIT_DEMONSTRATED: x"},
                {"correct_bounds": {"distribution_free_bound_vacuous": True}},
                {"diagnostic_conclusion":
                 "REQUIRE_DOCTRINE_REVIEW (diagnostic only): x"},
            )["classification"],
            "V4_CORE_DIAGNOSIS_MIXED")
        # pure ordinary tail (no metric/contract contribution)
        self.assertEqual(
            diag.classify(
                {"p99_max_decision_index": 3,
                 "p99_reproduced": 16.765625},
                {"split_verdict": "NO_PROSPECTIVE_SPLIT_DEMONSTRATED: x"},
                {"correct_bounds": {"distribution_free_bound_vacuous": False}},
                {"diagnostic_conclusion": "retain"},
            )["classification"],
            "V4_CORE_DIAGNOSIS_ORDINARY_TAIL")
        # no tail support -> inconclusive
        self.assertEqual(
            diag.classify(
                {"p99_max_decision_index": 3,
                 "p99_reproduced": 16.765625},
                {"split_verdict": "split found"},
                {"correct_bounds": {"distribution_free_bound_vacuous": False}},
                {"diagnostic_conclusion": "retain"},
            )["classification"],
            "V4_CORE_DIAGNOSIS_INCONCLUSIVE")

    def test_nearest_rank_higher_frozen_rule(self):
        errs = [float(i) for i in range(100)]
        self.assertEqual(diag.nearest_rank_higher(errs), 98.0)  # ceil(0.99*100)-1 = 98th index
        errs = [0.5] * 262144
        self.assertEqual(diag.nearest_rank_higher(errs), 0.5)

    def test_purity_no_gpu_or_subprocess(self):
        import ast
        src = (ROOT / "scripts" / "issue105_post_v4_core_diagnosis.py")
        src.read_text()
        tree = ast.parse(src.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0],
                                     ("torch", "subprocess", "numpy"))
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(node.module.split(".")[0],
                                 ("torch", "subprocess", "numpy"))
        text = src.read_text()
        # docstrings may legitimately mention torch; code must not import it
        stripped = ast.dump(ast.parse(text))
        self.assertNotIn("cuda", text.replace("CUDA_VISIBLE_DEVICES", ""))


if __name__ == "__main__":
    unittest.main()
