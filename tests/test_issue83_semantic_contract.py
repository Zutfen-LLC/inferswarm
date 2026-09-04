"""Issue #83 semantic-contract tests.

Covers:
- the decision-stability theorems (m > 2E stability, 2E admissibility,
  tightness) on exact synthetic constructions;
- the first-divergence aggregator: reproduction gate passes on committed
  evidence, exact historical counts, and fail-closed behavior on mutated
  evidence (negative controls);
- structural: contract document preserves historical verdicts and holdout
  sealed state.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = (REPO_ROOT / "docs" / "qualification"
            / "gemma4-12b-it-semantic-83" / "evidence")
CONTRACT = (REPO_ROOT / "docs" / "qualification"
            / "gemma4-12b-it-semantic-83" / "SEMANTIC-CONTRACT.md")
AGGREGATOR = REPO_ROOT / "scripts" / "issue83_first_divergence.py"

E = 1.0


def run_aggregator(evidence_dir):
    return subprocess.run(
        [sys.executable, str(AGGREGATOR), "--evidence-dir", str(evidence_dir)],
        capture_output=True, text=True)


class DecisionStabilityTheorems(unittest.TestCase):
    def argmax(self, xs):
        return max(range(len(xs)), key=lambda i: xs[i])

    def bound_ok(self, r, c, E):
        return all(abs(c[i] - r[i]) <= E for i in range(len(r)))

    def test_thm1_margin_above_2E_forces_same_argmax(self):
        for m in (2 * E + 1e-9, 2.5 * E, 10 * E):
            r = [0.0, -m, -m - 1.0]
            # adversarial candidate: top1 pushed down, runner-up pushed up
            c = [-E, -m + E, -m - 1.0]
            self.assertTrue(self.bound_ok(r, c, E))
            self.assertEqual(self.argmax(r), 0)
            self.assertEqual(self.argmax(c), 0, f"m={m}")

    def test_thm2_candidate_argmax_is_admissible(self):
        r = [0.0, -0.5, -3.0]
        c = [-1.0, 0.5, -3.0]  # flips to token 1 under the bound
        self.assertTrue(self.bound_ok(r, c, E))
        j = self.argmax(c)
        self.assertLessEqual(r[0] - r[j], 2 * E)

    def test_thm3_flip_exists_for_margin_below_2E(self):
        m = 1.5
        eps = 2 * E - m
        r = [0.0, -m]
        c = [-E, -m + E - eps / 2]
        self.assertTrue(self.bound_ok(r, c, E))
        self.assertEqual(self.argmax(c), 1)  # flip achieved legally

    def test_thm3_tie_possible_at_exactly_2E(self):
        m = 2 * E
        r = [0.0, -m]
        c = [-E, -E]
        self.assertTrue(self.bound_ok(r, c, E))
        self.assertEqual(c[0], c[1])  # tie: identity not guaranteed

    def test_ambiguity_set_definition_matches_theorem2(self):
        r = [0.0, -1.4, -2.1, -8.0]
        A = {j for j in range(4) if r[0] - r[j] <= 2 * E}
        self.assertEqual(A, {0, 1})  # -2.1 gap 2.1 > 2E excluded


class AggregatorReproductionGate(unittest.TestCase):
    def test_committed_evidence_passes_and_reproduces_counts(self):
        proc = run_aggregator(EVIDENCE)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertIn("PASS", out["reproduction_gate"])
        self.assertEqual(out["divergence"]["diverged_cases"], 240)
        d = out["divergence"]
        self.assertEqual(
            sum(d["first_divergence_step_histogram"].values()), 240)
        rows = out["rows"]
        self.assertEqual(rows["same_prefix_rows"], 624)
        self.assertEqual(rows["first_divergence_rows"], 46)
        self.assertEqual(rows["flips_inadmissible"], 0)
        self.assertEqual(rows["theorem1_empirical_violations"], 0)
        self.assertEqual(
            rows["argmax_flips_strictly_before_first_divergence"], 0)
        self.assertEqual(rows["never_diverged_argmax_flips"], 0)
        self.assertEqual(rows["candidate_rank_under_ref_at_divergence"]["2"], 40)
        self.assertEqual(
            rows["full_domain_max_abs"]["max"], 14.1875)

    def _mutate(self, fn):
        tmp = tempfile.TemporaryDirectory()
        td = Path(tmp.name)
        for f in EVIDENCE.iterdir():
            (td / f.name).write_bytes(f.read_bytes())
        fn(td)
        return tmp, td

    def test_gate_fails_on_mutated_divergence_count(self):
        def mutate(td):
            p = td / "first-divergence-statistical.json"
            d = json.loads(p.read_text())
            # force one diverged case to look non-diverged
            for c in d["cases"]:
                if c["first_divergence_step"] is not None:
                    c["chain_tokens"] = list(c["ref_tokens"])
                    c["first_divergence_step"] = None
                    break
            p.write_text(json.dumps(d))
        tmp, td = self._mutate(mutate)
        with tmp:
            proc = run_aggregator(td)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("gate", proc.stderr)

    def test_gate_fails_on_inconsistent_first_divergence(self):
        def mutate(td):
            p = td / "first-divergence-stress.json"
            d = json.loads(p.read_text())
            for c in d["cases"]:
                if c["first_divergence_step"] is not None:
                    # claim divergence earlier than the tokens show
                    c["first_divergence_step"] = 0
                    c["chain_tokens"] = list(c["ref_tokens"])
                    break
            p.write_text(json.dumps(d))
        tmp, td = self._mutate(mutate)
        with tmp:
            proc = run_aggregator(td)
            self.assertNotEqual(proc.returncode, 0)

    def test_gate_fails_on_missing_row_in_metrics(self):
        def mutate(td):
            p = td / "same-prefix-error-metrics.json"
            d = json.loads(p.read_text())
            d["rows"] = d["rows"][:-1]
            p.write_text(json.dumps(d))
        tmp, td = self._mutate(mutate)
        with tmp:
            proc = run_aggregator(td)
            self.assertNotEqual(proc.returncode, 0)


class ContractDocument(unittest.TestCase):
    def test_preserves_historical_verdicts_and_holdout(self):
        text = CONTRACT.read_text()
        self.assertIn("CALIBRATION_SEMANTIC_FAIL", text)
        self.assertIn("R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL", text)
        self.assertIn("23311c55", text)
        self.assertIn("holdout remains sealed", text)
        # no threshold ratification from #81 numbers
        self.assertNotIn("E = 14.1875 is adopted", text)
        self.assertNotIn("adopt E =", text)

    def test_states_theorems_and_profiles(self):
        text = CONTRACT.read_text()
        self.assertIn("m > 2E", text)
        self.assertIn("A_E(r)", text)
        self.assertIn("EXACT_TOKENS_REQUIRED", text)
        self.assertIn("BIT_EXACT_REQUIRED", text)
        self.assertIn("teacher-forced", text)

    def test_evidence_files_have_sources(self):
        for name in ("first-divergence-statistical.json",
                     "first-divergence-stress.json"):
            d = json.loads((EVIDENCE / name).read_text())
            self.assertTrue(d["source_sha256"])
            self.assertTrue(d["ref_index_sha256"])
        m = json.loads((EVIDENCE / "same-prefix-error-metrics.json").read_text())
        self.assertTrue(all("ref_row_sha256" in r and
                            "chain_row_sha256" in r for r in m["rows"]))


if __name__ == "__main__":
    unittest.main()
