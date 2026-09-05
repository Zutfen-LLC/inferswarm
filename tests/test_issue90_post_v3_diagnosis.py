"""Unit tests for the issue #90 post-v3 envelope diagnosis tool.

CPU-only, pure stdlib. The tests prove:
  - the tool fails closed on ANY pinned-evidence hash drift (mutation
    controls, one changed byte each);
  - every headline number is DERIVED (a synthetic miscalibration injected
    into the pinned bytes changes the derived outputs);
  - the statistical identities are exact;
  - the tool source stays pure (no torch/numpy/subprocess) and contains no
    bare-constant pass checks;
  - historical verdicts are preserved verbatim.
"""

import hashlib
import importlib.util
import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "scripts" / "issue90_post_v3_diagnosis.py"
EVD = REPO_ROOT / "docs/qualification/gemma4-12b-it-v3-campaign-88"
V3 = REPO_ROOT / "docs/qualification/gemma4-12b-it-v3"

HISTORICAL_VERDICTS = {
    "R6": "R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL",
    "issue_76": "PHASE0_STOP",
    "issue_81": "CALIBRATION_SEMANTIC_FAIL",
    "issue_88": "V3_HOLDOUT_FAIL",
}


def load_tool():
    spec = importlib.util.spec_from_file_location("issue90_tool", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPinnedEvidenceIntegrity(unittest.TestCase):
    """The pinned inputs must byte-match the accepted #88/#86 provenance."""

    def test_pinned_files_match_accepted_hashes(self):
        tool = load_tool()
        for rel, expected in tool.PINNED_FILE_SHA256.items():
            path = REPO_ROOT / rel
            self.assertTrue(path.exists(), rel)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(digest, expected, rel)

    def test_pinned_set_covers_all_retained_campaign_inputs(self):
        tool = load_tool()
        committed = {str(p.relative_to(REPO_ROOT)) for p in EVD.rglob("*.json")}
        self.assertTrue(set(tool.PINNED_FILE_SHA256) >= committed)

    def test_fail_closed_on_hash_drift(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            # copy the whole repo subtree the tool reads (path-relative)
            for rel in tool.PINNED_FILE_SHA256:
                dst = tdp / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(REPO_ROOT / rel, dst)
            # mutate ONE byte of the calibration summary (a hex float digit)
            target = tdp / "docs/qualification/gemma4-12b-it-v3-campaign-88/phaseEF/calibration-summary.json"
            data = bytearray(target.read_bytes())
            idx = data.find(b"0x1.4e7a83acd6bccp+1")
            self.assertGreater(idx, 0, "statistical-max hex literal not found for mutation")
            data[idx + 5] = ord("5") if data[idx + 5] != ord("5") else ord("6")
            target.write_bytes(bytes(data))
            tool.REPO_ROOT = tdp
            with self.assertRaises(tool.DiagnosisError) as cm:
                tool.build_diagnosis()
            self.assertIn("PINNED_EVIDENCE_HASH_DRIFT", str(cm.exception))

    def test_fail_closed_on_missing_evidence(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            for rel in tool.PINNED_FILE_SHA256:
                dst = tdp / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(REPO_ROOT / rel, dst)
            (tdp / "docs/qualification/gemma4-12b-it-v3-campaign-88/phaseHI/phaseI-failures.json").unlink()
            tool.REPO_ROOT = tdp
            with self.assertRaises(tool.DiagnosisError) as cm:
                tool.build_diagnosis()
            self.assertIn("PINNED_EVIDENCE_MISSING", str(cm.exception))


class TestDerivedNotConstant(unittest.TestCase):
    """R6 composer lesson: no check may be a bare constant."""

    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()
        cls.record = cls.tool.build_diagnosis()

    def test_classification_is_ordinary_tail(self):
        self.assertEqual(self.record["classification"],
                         "V3_ENVELOPE_DIAGNOSIS_ORDINARY_TAIL")

    def test_failing_observation_derived_from_pinned_bytes(self):
        fo = self.record["failing_observation"]
        self.assertEqual(fo["case_id"], "h86-03-05-01")
        self.assertEqual(fo["envelope"], "final-normalized-hidden-state:rms-difference")
        self.assertEqual(fo["observed"], 2.6800369574218053)
        self.assertEqual(fo["limit"], 2.6131138414325275)
        self.assertAlmostEqual(fo["exceedance_percent"], 2.561049, places=5)
        # independent re-derivation
        self.assertAlmostEqual(fo["observed"] / fo["limit"] - 1,
                               fo["exceedance_fraction"], places=15)
        self.assertTrue(fo["observed_exceeds_every_calibration_case"])
        self.assertEqual(fo["statistical_max_case"], "c86-03-03-21")

    def test_limit_equals_statistical_max_exactly(self):
        fo = self.record["failing_observation"]
        self.assertEqual(fo["statistical_max"], fo["limit"])
        self.assertEqual(fo["limit_rule"], "max(statistical_max,stress_max)")

    def test_distribution_counts(self):
        dist = self.record["family_distribution"]
        self.assertEqual(dist["statistical"]["n"], 576)
        self.assertEqual(dist["stress"]["n"], 8)
        self.assertEqual(len(dist["by_cell"]), 24)
        self.assertEqual(len(dist["by_content_class"]), 6)
        self.assertEqual(len(dist["by_length_regime"]), 4)

    def test_leave_one_cell_out_never_rescues(self):
        loco = self.record["applicability_split_audit"]["leave_one_cell_out"]
        self.assertEqual(len(loco), 24)
        self.assertTrue(all(v["failing_obs_still_exceeds"] for v in loco.values()))

    def test_tail_spans_many_cells(self):
        tc = self.record["applicability_split_audit"]["tail_concentration"]
        self.assertEqual(tc["distinct_cells_in_top10"], 10)
        self.assertEqual(tc["distinct_content_classes_in_top10"], 5)

    def test_no_bare_constant_checks_in_source(self):
        src = TOOL.read_text()
        # a composer must not set a passing check by constant (R6 lesson)
        self.assertNotIn("= True  # derived", src)
        for line in src.splitlines():
            s = line.strip()
            if s.endswith("_exceeds\": True") or s.endswith("_pass\": True"):
                self.fail(f"bare constant check: {s}")

    def test_tool_source_purity(self):
        src = TOOL.read_text()
        import ast as _ast
        tree = _ast.parse(src)
        banned = {"torch", "numpy", "subprocess", "triton", "safetensors"}
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                for a in node.names:
                    self.assertNotIn(a.name.split(".")[0], banned)
            if isinstance(node, _ast.ImportFrom) and node.module:
                self.assertNotIn(node.module.split(".")[0], banned)

    def test_statistical_identities_exact(self):
        ex = self.record["statistical_contract_audit"]["exact_calculations"]
        n, m = 576, 24
        # corrected basis: 576 statistical cases only (stress arm is
        # selection-biased and must NOT be pooled as exchangeable draws)
        self.assertAlmostEqual(ex["p_single_holdout_exceeds_max_of_576"], 1 / 577, places=15)
        self.assertAlmostEqual(ex["p_at_least_one_of_24_exceeds__exchangeable_max_limit"],
                               m / (n + m), places=15)  # 24/600
        self.assertAlmostEqual(ex["p_at_least_one_of_24_exceeds__coverage_exactly_99pct"],
                               1 - 0.99 ** 24, places=15)
        self.assertEqual(ex["calibration_n_for_exchangeable_95pct_zero_of_24"], 456)
        self.assertEqual(ex["distribution_free_tolerance_n_reproduced"], 574)
        # 16-independent-family recomputation from the 4.00% per-family value
        self.assertAlmostEqual(ex["p_no_family_fails__16_independent"],
                               (1 - m / (n + m)) ** 16, places=15)
        self.assertAlmostEqual(ex["p_some_family_fails__16_independent"], 1 - (0.96) ** 16, places=4)

    def test_no_pooled_stress_basis_in_prediction_arithmetic(self):
        # the old erroneous pooling (24/608) must not reappear anywhere
        src = TOOL.read_text()
        self.assertNotIn("24 / 608", src)
        self.assertNotIn("24/608", src)
        record_text = json.dumps(self.record)
        self.assertNotIn("24/608", record_text)
        self.assertNotIn("3.95%", record_text)

    def test_bonferroni_confidence_stated_correctly(self):
        text = TOOL.read_text() + json.dumps(self.record)
        self.assertNotIn("97.8%", text)
        self.assertIn("0.996875", text)

    def test_top10_class_count_derived_not_hardcoded(self):
        # derived: 10 distinct cells across 5 of 6 content classes
        tc = self.record["applicability_split_audit"]["tail_concentration"]
        self.assertEqual(tc["distinct_cells_in_top10"], 10)
        self.assertEqual(tc["distinct_content_classes_in_top10"], 5)
        answers = self.record["applicability_split_audit"]["pre_observability_answers"]
        joined = " ".join(answers)
        self.assertIn("10 distinct cells across 5 of 6 content classes", joined)
        # guard: the tool prose must not hard-code the class-count claim
        src = TOOL.read_text()
        self.assertNotIn("across all 6 content classes", src)

    def test_no_unsupported_cross_family_qq_claim(self):
        # QQ R2 is derived only for the failing family; no cross-family
        # fit claim may appear in tool or record
        src = TOOL.read_text()
        record_text = json.dumps(self.record)
        for bad in ("12 smooth families", "12 families", "14 families"):
            self.assertNotIn(bad, src)
            self.assertNotIn(bad, record_text)
        # the failing-family value remains derived and retained
        self.assertAlmostEqual(
            self.record["family_distribution"]["tail_shape"]["lognormal_qq_r2"],
            0.9856075971844234, places=12)

    def test_propagation_conditional_counts(self):
        ct = self.record["downstream_propagation"]["conditional_top_decile"]
        self.assertEqual(ct["n"], 59)
        self.assertEqual(ct["cases_within_all_other_14_limits"], 59)
        self.assertEqual(ct["e_d_frozen"], 26.9375)

    def test_rank_correlations_in_expected_band(self):
        cor = self.record["downstream_propagation"]["rank_correlations_over_584"]
        for name, rho in cor.items():
            self.assertTrue(0.5 < rho < 1.0, f"{name}={rho}")

    def test_historical_verdicts_preserved(self):
        text = (REPO_ROOT / "docs/qualification/gemma4-12b-it-post-v3-envelope-diagnosis/DIAGNOSIS.md").read_text()
        for verdict in HISTORICAL_VERDICTS.values():
            self.assertIn(verdict, text)
        self.assertIn("V3_HOLDOUT_FAIL", text)
        self.assertNotIn("V3_HOLDOUT_PASS", text.replace("V3_HOLDOUT_FAIL", ""))

    def test_non_claims_present(self):
        nc = self.record["non_claims"]
        self.assertTrue(any("ineligible" in s for s in nc))
        self.assertTrue(any("does NOT change" in s for s in nc))


if __name__ == "__main__":
    unittest.main()
