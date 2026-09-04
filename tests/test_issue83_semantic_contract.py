"""Issue #83 semantic-contract tests (PR #85 hardening pass).

Covers:
- the decision-stability theorems on exact synthetic constructions:
  m_D > 2E_D stability, 2E_D admissibility (necessity), strict flip
  below 2E_D, tie at exactly 2E_D, ambiguity-set definition;
- the fail-closed decision-domain containment rule: an actual candidate
  full-vocabulary winner outside D is DECISION_DOMAIN_ESCAPE (negative
  control), never "unstable", never ambiguity-admissible;
- tie-break semantics: frozen rule is applicability-bearing; equality
  margin m_D == 2E_D is treated as unstable;
- structural tests that E_full remains a mandatory full-vocabulary
  numerical envelope and E_D is supplemental, never a replacement;
- the first-divergence aggregator: reproduction gate passes on committed
  evidence, exact historical counts, and fail-closed behavior on mutated
  evidence (negative controls);
- structural: contract document preserves historical verdicts and holdout
  sealed state.

Pure logic only: no GPU, no torch, no model, no holdout access.
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
DOCTRINE = (REPO_ROOT / "docs" / "architecture"
            / "numerical-equivalence-contract.md")
AGGREGATOR = REPO_ROOT / "scripts" / "issue83_first_divergence.py"

E_D = 1.0

DECISION_DOMAIN_ESCAPE = "DECISION_DOMAIN_ESCAPE"
REFERENCE_DOMAIN_ESCAPE = "REFERENCE_DOMAIN_ESCAPE"
STABLE_DECISION_MISMATCH = "STABLE_DECISION_MISMATCH"
UNSTABLE_DECISION_INADMISSIBLE = "UNSTABLE_DECISION_INADMISSIBLE"
TIE_BREAK_MISMATCH = "TIE_BREAK_MISMATCH_INAPPLICABLE"


def argmax(xs, tie_break="lowest_id"):
    """Deterministic argmax under a frozen tie-break rule."""
    best = 0
    for i in range(1, len(xs)):
        if xs[i] > xs[best] or (xs[i] == xs[best] and tie_break == "highest_id"):
            best = i
    return best


def ambiguity_set(r, D, a, E_D):
    """A_ED(r) = { k in D | r[a] - r[k] <= 2 E_D }."""
    return {k for k in D if r[a] - r[k] <= 2 * E_D}


def margin_on_domain(r, D, a):
    """m_D = r[a] - r[b_D], b_D the reference runner-up within D."""
    return r[a] - max(r[k] for k in D if k != a)


def evaluate_decision(r, cand, D, E_D,
                      ref_tie_break="lowest_id",
                      cand_tie_break="lowest_id"):
    """Pure-logic decision-stability semantic gate (contract section 4.2).

    r/cand are full-vocabulary FP32 logit rows; D is the frozen decision
    domain. Returns (verdict, label) with verdict in {PASS, FAIL,
    INAPPLICABLE}. Containment of the ACTUAL emitted candidate winner is
    checked first and fail-closed.
    """
    if ref_tie_break != cand_tie_break:
        return "INAPPLICABLE", TIE_BREAK_MISMATCH
    a = argmax(r, tie_break=ref_tie_break)      # reference full-vocab winner
    if a not in D:
        return "FAIL", REFERENCE_DOMAIN_ESCAPE  # D invalid for this context
    j = argmax(cand, tie_break=cand_tie_break)  # actual emitted winner
    if j not in D:
        return "FAIL", DECISION_DOMAIN_ESCAPE
    m_D = margin_on_domain(r, D, a)
    if m_D > 2 * E_D:
        return ("PASS" if j == a else "FAIL"), STABLE_DECISION_MISMATCH
    A = ambiguity_set(r, D, a, E_D)
    return ("PASS" if j in A else "FAIL"), UNSTABLE_DECISION_INADMISSIBLE


def bound_ok_on_domain(r, c, D, E):
    return all(abs(c[i] - r[i]) <= E for i in D)


def norm(s):
    """Collapse whitespace/line wraps so wrapped markdown text is
    matchable."""
    return " ".join(s.split())


class DecisionStabilityTheorems(unittest.TestCase):
    def test_thm1_margin_above_2ED_forces_same_argmax_in_D(self):
        for m in (2 * E_D + 1e-9, 2.5 * E_D, 10 * E_D):
            r = [0.0, -m, -m - 1.0]
            # adversarial candidate: top1 pushed down, runner-up pushed up
            c = [-E_D, -m + E_D, -m - 1.0]
            D = {0, 1, 2}
            self.assertTrue(bound_ok_on_domain(r, c, D, E_D))
            self.assertEqual(argmax(r), 0)
            self.assertEqual(argmax(c), 0, f"m={m}")

    def test_thm2_in_domain_candidate_winner_is_admissible(self):
        r = [0.0, -0.5, -3.0]
        c = [-1.0, 0.5, -3.0]  # flips to token 1 under the bound
        D = {0, 1, 2}
        self.assertTrue(bound_ok_on_domain(r, c, D, E_D))
        j = argmax(c)
        self.assertIn(j, D)
        self.assertLessEqual(r[argmax(r)] - r[j], 2 * E_D)

    def test_thm3_strict_flip_exists_for_margin_below_2ED(self):
        m = 1.5
        eps = 2 * E_D - m
        r = [0.0, -m]
        c = [-E_D, -m + E_D - eps / 2]
        D = {0, 1}
        self.assertTrue(bound_ok_on_domain(r, c, D, E_D))
        self.assertEqual(argmax(c), 1)  # strict flip achieved legally

    def test_thm3_tie_possible_at_exactly_2ED(self):
        m = 2 * E_D
        r = [0.0, -m]
        c = [-E_D, -E_D]
        D = {0, 1}
        self.assertTrue(bound_ok_on_domain(r, c, D, E_D))
        self.assertEqual(c[0], c[1])  # tie: identity not guaranteed
        # the emitted token at the tie depends on the frozen tie-break rule
        self.assertEqual(argmax(c, tie_break="lowest_id"), 0)
        self.assertEqual(argmax(c, tie_break="highest_id"), 1)

    def test_ambiguity_set_definition_matches_theorem2(self):
        r = [0.0, -1.4, -2.1, -8.0]
        D = {0, 1, 2, 3}
        A = ambiguity_set(r, D, 0, E_D)
        self.assertEqual(A, {0, 1})  # -2.1 gap 2.1 > 2E_D excluded


class SemanticGateEvaluator(unittest.TestCase):
    """The contract's section-4.2 gate as pure logic, incl. fail-closed
    decision-domain containment."""

    def test_stable_decision_requires_exact_identity(self):
        r = [0.0, -3.0, -9.0]          # m_D = 3.0 > 2E_D = 2.0
        c = [0.0, -3.0, -9.0]
        verdict, label = evaluate_decision(r, c, {0, 1, 2}, E_D)
        self.assertEqual(verdict, "PASS")
        # a stable-decision mismatch fails with no tolerance
        c2 = [0.0, 0.5, -9.0]          # j = 1 != a, still in D
        verdict, label = evaluate_decision(r, c2, {0, 1, 2}, E_D)
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(label, STABLE_DECISION_MISMATCH)

    def test_unstable_decision_requires_ambiguity_membership(self):
        r = [0.0, -1.0, -2.5, -7.0]    # m_D = 1.0 <= 2E_D
        D = {0, 1, 2, 3}
        A = ambiguity_set(r, D, 0, E_D)
        self.assertEqual(A, {0, 1})    # gap 2.5 > 2E_D excluded
        verdict, _ = evaluate_decision(r, [0.0, -0.5, -2.5, -7.0], D, E_D)
        self.assertEqual(verdict, "PASS")  # j=1 inside A
        # emitted token inside D but OUTSIDE the ambiguity set fails
        verdict, label = evaluate_decision(r, [0.0, -1.0, 0.5, -7.0], D, E_D)
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(label, UNSTABLE_DECISION_INADMISSIBLE)

    def test_domain_escape_negative_control(self):
        """CRITICAL negative control: reference winner a in D; the
        candidate's best token INSIDE D satisfies Theorem 1; but another
        candidate token OUTSIDE D becomes the actual full-vocabulary
        winner. The gate MUST fail DECISION_DOMAIN_ESCAPE."""
        D = {0, 1}
        r = [0.0, -1.0, -5.0, -5.0, -5.0]   # a = 0 in D, m_D = 1.0
        E = 0.4                              # m_D = 1.0 > 2E = 0.8 (stable)
        # bound holds on D; argmax_D(cand) == a (theorem satisfied in D);
        # but token 4 (outside D) is boosted past everything in D:
        c = [-0.4, -1.0, -5.0, -5.0, 0.3]
        self.assertTrue(bound_ok_on_domain(r, c, D, E))
        self.assertEqual(argmax([c[i] for i in sorted(D)]),
                         list(sorted(D))[[c[i] for i in sorted(D)]
                                         .index(max(c[i] for i in D))])
        self.assertEqual(argmax(c), 4)          # actual winner outside D
        verdict, label = evaluate_decision(r, c, D, E)
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(label, DECISION_DOMAIN_ESCAPE)
        # it is NOT classified as unstable/ambiguity-admissible:
        self.assertNotEqual(label, UNSTABLE_DECISION_INADMISSIBLE)
        self.assertNotIn(argmax(c), ambiguity_set(r, D, 0, E))

    def test_domain_escape_checked_before_stability(self):
        # even a would-be stable decision escapes first (fail-closed order)
        D = {0, 1}
        r = [0.0, -5.0, -9.0]
        c = [0.0, -5.0, 1.0]              # m_D = 5.0 huge, but j = 2 outside
        verdict, label = evaluate_decision(r, c, D, 0.5)
        self.assertEqual((verdict, label), ("FAIL", DECISION_DOMAIN_ESCAPE))

    def test_reference_winner_outside_domain_is_invalid(self):
        r = [-5.0, 0.0, -1.0]             # full-vocab winner is token 1
        verdict, label = evaluate_decision(r, list(r), {0, 2}, E_D)
        self.assertEqual((verdict, label), ("FAIL", REFERENCE_DOMAIN_ESCAPE))

    def test_full_vocabulary_domain_never_escapes(self):
        V = 6
        D = set(range(V))
        r = [0.0, -0.5, -2.0, -3.0, -4.0, -5.0]
        c = [-1.0, 0.4, -2.0, -3.0, -4.0, -5.0]
        verdict, label = evaluate_decision(r, c, D, E_D)
        self.assertEqual(verdict, "PASS")  # j=1 in A_ED
        # containment cannot fail for D = full vocabulary by construction
        self.assertEqual(argmax(c), 1)
        self.assertIn(argmax(c), D)

    def test_equality_margin_treated_as_unstable(self):
        # m_D == 2E_D exactly: unstable branch (ambiguity), not guaranteed
        r = [0.0, -2.0, -9.0]
        D = {0, 1, 2}
        c = [-1.0, -1.0, -9.0]            # tie on the boundary
        self.assertEqual(margin_on_domain(r, D, 0), 2 * E_D)
        verdict, label = evaluate_decision(r, c, D, E_D)
        self.assertEqual(verdict, "PASS")  # tie-break lowest_id -> j=0=a,
        # but the SAME rows under the opposite frozen rule emit j=1:
        verdict2, _ = evaluate_decision(r, c, D, E_D,
                                        ref_tie_break="highest_id",
                                        cand_tie_break="highest_id")
        self.assertEqual(verdict2, "PASS")  # j=1 in A_ED (gap exactly 2E_D)
        self.assertEqual(argmax(c, tie_break="highest_id"), 1)
        # identity at equality is therefore NOT guaranteed by the envelope
        self.assertNotEqual(argmax(c, tie_break="lowest_id"),
                            argmax(c, tie_break="highest_id"))

    def test_mismatched_tie_break_rules_make_profile_inapplicable(self):
        r = [0.0, -2.0]
        c = [-1.0, -1.0]
        verdict, label = evaluate_decision(r, c, {0, 1}, E_D,
                                           ref_tie_break="lowest_id",
                                           cand_tie_break="highest_id")
        self.assertEqual(verdict, "INAPPLICABLE")
        self.assertEqual(label, TIE_BREAK_MISMATCH)


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
        self.assertIn("m_D > 2E_D", text)
        self.assertIn("A_ED(r)", text)
        self.assertIn("EXACT_TOKENS_REQUIRED", text)
        self.assertIn("BIT_EXACT_REQUIRED", text)
        self.assertIn("teacher-forced", text)

    def test_theorem1_proof_chain_terminates_in_negativity(self):
        text = norm(CONTRACT.read_text())
        self.assertIn("−(r_a − r_j) + 2 E_D", text)
        self.assertIn("−m_D + 2 E_D", text)
        self.assertIn("< 0", text)
        # the old flawed chain is gone: no bare comparison-against-margin
        # terminal step remains anywhere in the proof
        self.assertNotIn("2E < m", text)
        self.assertNotIn("≤ 2E < m", text)

    def test_two_envelope_separation_E_full_vs_E_D(self):
        text = norm(CONTRACT.read_text())
        self.assertIn("E_full", text)
        self.assertIn("E_D", text)
        # E_full is the mandatory full-vocabulary numerical envelope
        self.assertIn("ENTIRE vocabulary", text)
        self.assertIn("fp32-consumer-logits", text)
        self.assertIn("mandatory and not optional", text)
        # E_D supplements; never a replacement
        self.assertIn("supplemental", text)
        for forbidden in ("E_D replaces", "replaces `E_full`",
                          "replaces E_full", "waives `E_full`",
                          "E_D in place of"):
            self.assertNotIn(forbidden, text, forbidden)
        # conjunctive qualification requirement
        self.assertIn("BOTH", text)

    def test_containment_and_escape_wording(self):
        text = norm(CONTRACT.read_text())
        self.assertIn("DECISION_DOMAIN_ESCAPE", text)
        self.assertIn("actual candidate full-vocabulary emitted winner",
                      text)
        # escape is unconditional, not "unstable"
        self.assertIn("not classified as \"unstable\"", text)
        # prospective-domain validity rule, verbatim from the issue
        # (blockquote "> " markers stripped after whitespace normalization)
        self.assertIn(
            "A proper-subset decision domain is valid only for contexts "
            "whose qualification demonstrates zero decision-domain escapes "
            "under the frozen method", text.replace("> ", ""))
        # no results-informed domain sizing
        self.assertIn("rank-17", text)  # mentioned only to forbid its use
        self.assertIn("results-informed", text)

    def test_tie_break_wording(self):
        text = norm(CONTRACT.read_text())
        self.assertIn("tie-break", text)
        self.assertIn("implementation-defined", text)  # only to forbid it
        self.assertIn("must not be left \"implementation-defined\"", text)
        self.assertIn("m_D = 2E_D", text)
        self.assertIn("treated as **unstable**", text)
        # trichotomy is stated exactly
        self.assertIn("guaranteed argmax identity", text)
        self.assertIn("strict-flip construction exists", text)
        self.assertIn("a tie construction exists", text)

    def test_doctrine_keeps_full_vocab_envelope_mandatory(self):
        text = norm(DOCTRINE.read_text())
        # §5.4 numerical-layer rule preserved
        self.assertIn("full vocabulary when practical", text)
        self.assertIn("should not be the sole qualification domain", text)
        # E_full named as mandatory; E_D supplemental/conjunctive
        self.assertIn("E_full", text)
        self.assertIn("never a replacement", text)
        self.assertIn("supplemental", text)
        # containment fail-closed in unconditional failures (§6)
        self.assertIn("DECISION_DOMAIN_ESCAPE", text)
        # tie-break is applicability-bearing
        self.assertIn("tie-break", text)
        self.assertIn("applicability key", text)

    def test_evidence_files_have_sources(self):
        for name in ("first-divergence-statistical.json",
                     "first-divergence-stress.json"):
            d = json.loads((EVIDENCE / name).read_text())
            self.assertTrue(d["source_sha256"])
            self.assertTrue(d["ref_index_sha256"])
        m = json.loads((EVIDENCE / "same-prefix-error-metrics.json").read_text())
        self.assertTrue(all("ref_row_sha256" in r and
                            "chain_row_sha256" in r for r in m["rows"]))


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


def run_aggregator(evidence_dir):
    return subprocess.run(
        [sys.executable, str(AGGREGATOR), "--evidence-dir", str(evidence_dir)],
        capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
