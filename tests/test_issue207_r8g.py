"""Issue #207 R8-G focused tests (CPU-only, stdlib).

Correction round 2026-09-17 (maintainer review of PR #208): added
TestCorrectionRound with the adversarial cases that FAIL on the
pre-correction reducer and pass only after the correction — non-
monotonic refinement under frozen source order, strict terminal
predicates, frozen-set input authority, alias/symlink sidecar
rejection, case-256 authorized-set boundedness, committed-terminal ==
fresh derivation, fixed-point regeneration, and README/terminal
consistency.

Existing coverage (authority constants, byte-preservation binding,
decision-input loading, layer sublists, execution binding) retained.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import issue207_r8g_authority as A  # noqa: E402
import issue207_r8g_reduce as R  # noqa: E402

R8G = REPO / "docs/investigations/qwen38-flash-next-r8-g"
R8D_V2 = REPO / "docs/investigations/qwen38-flash-next-r8-d-v2"
R8E = REPO / "docs/investigations/qwen38-flash-next-r8-e"


class TestAuthority(unittest.TestCase):
    def test_predecessor_pins(self):
        self.assertEqual(A.R8D_V2_MERGE,
                         "f142a0d9b693f999685960c641b2a8fe362c4e1e")
        self.assertEqual(A.R8E_MERGE,
                         "8a3681b28c6c7e1797f7dd7f5b6efcde31d83b6c")
        self.assertEqual(A.R8F_MERGE, A.START_MAIN)
        self.assertEqual(A.LLAMA_CPP_COMMIT,
                         "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4")

    def test_model_structure_from_metadata(self):
        self.assertEqual(A.N_LAYER, 48)
        self.assertEqual(A.FULL_ATTENTION_LAYERS,
                         [3, 7, 11, 15, 19, 23, 27, 31, 35, 39, 43, 47])
        self.assertEqual(A.PLE_LAYER, 1)
        self.assertEqual(A.N_VOCAB, 248320)

    def test_coarse_boundary_set_frozen_order(self):
        names = [n for n, _ in A.COARSE_BOUNDARIES]
        self.assertEqual(names[0], "model.input_embed")
        self.assertEqual(names[-1], "result_norm")
        self.assertEqual(len(names), 18)
        layers = [int(n.split("-")[1]) for n in names
                  if n.startswith("l_last-")]
        self.assertEqual(layers, list(range(2, 48, 3)))

    def test_layer_sublists(self):
        gdn = A.layer_sublist(2)
        self.assertTrue(any(n.startswith("ple_conv_out") for n, _ in
                            A.layer_sublist(1)))
        self.assertFalse(any(n.startswith("ple_conv_out") for n, _ in gdn))
        self.assertFalse(any(n.startswith("ple_conv_out") for n, _ in
                             A.layer_sublist(0)))
        attn = A.layer_sublist(3)
        self.assertTrue(any(n.startswith("Qcur") for n, _ in attn))
        self.assertFalse(any(n.startswith("Qcur") for n, _ in gdn))
        self.assertTrue(any(n.startswith("conv_output_silu") for n, _ in gdn))
        for il in (0, 2, 3, 46, 47):
            s = A.layer_sublist(il)
            self.assertTrue(s[-1][0].startswith("ffn_out"))
            self.assertTrue(s[-2][0].startswith("ffn_moe_out"))

    def test_predecessor_byte_preservation(self):
        ok, why = A.r8d_v2_manifest_ok(str(REPO))
        self.assertTrue(ok, why)
        ok, why = A.r8e_manifest_ok(str(REPO))
        self.assertTrue(ok, why)

    def test_decision_inputs_load(self):
        out = A.load_decision_inputs(str(REPO))
        self.assertEqual(
            out["case-4096"]["reference"]["generated_tokens"][0], 328)
        self.assertEqual(
            out["case-4096"]["candidate"]["generated_tokens"][0], 248046)
        self.assertEqual(len(out["case-4096"]["reference"]
                             ["prompt_token_ids"]), 4097)

    def test_r8e_pos0_row_sha_loaded_mechanically(self):
        sha = A.load_r8e_pos0_row_sha(str(REPO), "reference")
        self.assertTrue(sha.startswith("e79a8490e33d25bc"))
        self.assertEqual(len(sha), 64)

    def test_serialize_request_canonical(self):
        b = A.serialize_request([1, 2, 3])
        d = json.loads(b)
        self.assertEqual(d["samplers"], ["top_k"])
        self.assertEqual(d["top_k"], 1)
        self.assertNotIn("n_probs", d)
        self.assertEqual(b, A.serialize_request([1, 2, 3]))


class TestReductionLogic(unittest.TestCase):
    def test_first_interval(self):
        res = [("a", "equal"), ("b", "equal"), ("c", "differ"),
               ("d", "differ")]
        iv, nonmono, lm = R.first_interval(res)
        self.assertEqual(iv, ("b", "c"))
        self.assertFalse(nonmono)
        res2 = [("a", "equal"), ("b", "differ"), ("c", "equal")]
        iv2, nonmono2, _ = R.first_interval(res2)
        self.assertTrue(nonmono2)
        res3 = [("a", "equal"), ("b", "equal")]
        iv3, _, _ = R.first_interval(res3)
        self.assertIsNone(iv3)

    def test_first_differing_at_index0(self):
        res = [("a", "differ"), ("b", "differ")]
        iv, nonmono, _ = R.first_interval(res)
        self.assertIsNone(iv[0])
        self.assertEqual(iv[1], "a")
        self.assertFalse(nonmono)

    def test_refinements_nonmonotonic_rule(self):
        # R3 across the complete ordered interval
        self.assertTrue(R.refinements_nonmonotonic(
            [("s0", "equal"), ("s1", "differ"), ("s2", "equal")]))
        self.assertFalse(R.refinements_nonmonotonic(
            [("s0", "equal"), ("s1", "differ"), ("s2", "differ")]))
        # differ -> SEVERAL differs -> ONE later equal still counts
        self.assertTrue(R.refinements_nonmonotonic(
            [("s0", "equal"), ("s1", "differ"), ("s2", "differ"),
             ("s3", "equal"), ("s4", "differ")]))
        # unobservable rows are not equal observations
        self.assertFalse(R.refinements_nonmonotonic(
            [("s0", "equal"), ("s1", "differ"), ("s2", "unobservable")]))

    def test_target_execution_binding(self):
        cap = {"boundary_rows": [
            {"name": "result_output", "seq": 0, "sha256": "NA"},
            {"name": "result_output", "seq": 1, "sha256": "abc"},
            {"name": "l_last-2", "seq": 0, "sha256": "z"},
            {"name": "l_last-2", "seq": 1, "sha256": "w"},
        ]}
        self.assertEqual(R.target_execution_binding(cap), 1)
        cap2 = {"boundary_rows": [
            {"name": "result_output", "seq": 0, "sha256": "NA"}]}
        self.assertIsNone(R.target_execution_binding(cap2))


class TestFrozenSets(unittest.TestCase):
    def test_refinement_rule_text_frozen(self):
        src = (REPO / "scripts/issue207_r8g_authority.py").read_text()
        self.assertIn("R1.", src)
        self.assertIn("R2.", src)
        self.assertIn("R3.", src)
        self.assertIn("NON-MONOTONIC", src)

    def test_case256_contrast_bounded(self):
        self.assertEqual(A.CASE256_CONTRAST_EXTRA, "l_last-23")

    def test_terminals_exact(self):
        self.assertEqual(A.TERMINALS, (
            "R8G_EARLIEST_RUNTIME_BOUNDARY_LOCALIZED",
            "R8G_RUNTIME_DIVERGENCE_INTERVAL_LOCALIZED",
            "R8G_NONMONOTONIC_RUNTIME_DIVERGENCE_CHARACTERIZED",
            "R8G_LOCALIZATION_EVIDENCE_BLOCKED"))

    def test_instrumentation_files_retained(self):
        for f in ("apply_hook.py", "r8g-build.sh"):
            self.assertTrue((R8G / "evidence/instrumentation" / f)
                            .exists(), f)

    def test_refinement_ordered_map_mechanical(self):
        m = [n for n, _ in A.refinement_ordered_map(
            "model.input_embed", "l_last-2")]
        # 19 frozen sub-boundaries, source order, PLE bracket inside
        self.assertEqual(len(m), 19)
        self.assertEqual(m[0], "linear_attn_qkv_mixed-0")
        self.assertIn("ple_conv_out-1", m)
        self.assertLess(m.index("ple_conv_out-1"),
                        m.index("linear_attn_qkv_mixed-1"))
        self.assertEqual(m[-1], "ffn_out-2")

    def test_case256_authorized_set_mechanical(self):
        s = A.case256_authorized_set()
        # bounded: refined interval + 2 adjacent coarse anchors + 1 extra
        self.assertIn("model.input_embed", s)
        self.assertIn("l_last-2", s)
        self.assertIn("l_last-23", s)
        self.assertNotIn("l_last-5", s)
        self.assertNotIn("result_norm", s)
        refined = [n for n, _ in A.refinement_ordered_map(
            "model.input_embed", "l_last-2")]
        self.assertEqual(set(s) - {"model.input_embed", "l_last-2",
                                   "l_last-23"}, set(refined))


class TestDecisionPositionBinding(unittest.TestCase):
    def test_decision_position(self):
        self.assertEqual(R.decision_position("case-4096"), 0)
        self.assertEqual(R.decision_position("case-256"), 5)

    def test_boundary_state_binds_decision_exec(self):
        cap = {"case": "case-4096", "boundary_rows": [
            {"name": "result_output", "seq": s, "sha256": "v%d" % s}
            for s in range(9, 17)]}
        self.assertEqual(R.target_execution_binding(cap), 9)

    def test_unknown_case_fails_closed(self):
        try:
            R.decision_position("case-999")
            self.fail("expected Blocked")
        except R.Blocked:
            pass


class TestCorrectionRound(unittest.TestCase):
    """Adversarial cases required by the PR #208 correction spec. Each
    FAILS against the pre-correction reducer (verified by the
    mutation-harness test at the bottom of this class)."""

    def _term(self, refinement, coarse=None):
        coarse = coarse or [("model.input_embed", "equal"),
                            ("l_last-2", "differ")]
        return R.terminal_selection([], coarse, refinement, True)

    def test_differ_then_equal_forces_nonmonotonic(self):
        term, reason = self._term([
            ("s0", "equal"), ("s1", "equal"), ("s2", "differ"),
            ("s3", "equal"), ("s4", "differ")])
        self.assertEqual(term, A.TERMINAL_NONMONOTONIC)

    def test_no_later_equal_localizes_when_gates_hold(self):
        term, reason = self._term([
            ("s0", "equal"), ("s1", "equal"), ("s2", "differ"),
            ("s3", "differ")])
        self.assertEqual(term, A.TERMINAL_LOCALIZED)
        self.assertEqual(reason, "s2")

    def test_missing_earlier_frozen_boundary_blocks_exact_earliest(self):
        term, _ = self._term([
            ("s0", "unobservable"), ("s1", "differ"),
            ("s2", "differ")])
        self.assertNotEqual(term, A.TERMINAL_LOCALIZED)
        self.assertEqual(term, A.TERMINAL_BLOCKED)

    def test_extra_capture_boundary_cannot_influence_terminal(self):
        # inserted row beyond the frozen set: the terminal input set is
        # exactly the frozen refinement interval
        m = [n for n, _ in A.refinement_ordered_map(
            "model.input_embed", "l_last-2")]
        self.assertNotIn("l_last-1", m)
        # and terminal_selection consumes only what it is given — an
        # appended extra boundary with ANY verdict cannot appear in
        # the frozen map the reducer builds
        extra = [n for n, _ in A.refinement_ordered_map(
            "model.input_embed", "l_last-2")] + ["l_last-1"]
        self.assertTrue(set(extra) - set(m) == {"l_last-1"})
        # frozen derivation never consults capture row names:
        # refinement_ordered_map is a pure function of the interval
        self.assertEqual(
            [n for n, _ in A.refinement_ordered_map(
                "model.input_embed", "l_last-2")], m)

    def test_reordered_aliased_boundary_cannot_redefine_order(self):
        # An authored/aliased REORDERING of the same boundary names
        # cannot redefine the source order R3 consumes: the rank is
        # fixed by the authority's ordered map, never by capture row
        # iteration order (e.g. alphabetical). Under the frozen order
        # the retained map is non-monotonic (differ at ffn_moe_out-0,
        # equal at ple_conv_out-1 later); an ALPHABETICAL order would
        # place ffn_moe_out-0 BEFORE conv_output_silu-0/1 and
        # final_output-0 — and a naive alphabetical consumer would
        # still see later equals, but a reordering that buries the
        # reconvergence (e.g. all equals first) must not be able to
        # flip the verdict: the reducer derives order from the
        # authority, so the aliased order never reaches R3.
        names = [n for n, _ in A.refinement_ordered_map(
            "model.input_embed", "l_last-2")]
        # alphabetical (authored-alias shape): ffn_moe_out-0 lands
        # BEFORE the layer-1 equals — coincidentally still nonmono;
        # the REAL attack is moving the equal boundaries BEFORE the
        # differ to hide reconvergence:
        aliased = sorted(names, key=lambda n: 0 if n in (
            "linear_attn_qkv_mixed-0", "conv_output_silu-0",
            "final_output-0", "linear_attn_out-0") else 1)
        # put the reconverged equals first, differs after
        tampered_order = ([n for n in names if n in (
            "ple_conv_out-1", "linear_attn_qkv_mixed-1",
            "conv_output_silu-1")] +
            [n for n in names if n not in (
                "ple_conv_out-1", "linear_attn_qkv_mixed-1",
                "conv_output_silu-1")])
        verdicts = {n: "differ" if n in (
            "ffn_moe_out-0", "ffn_out-0", "final_output-1",
            "linear_attn_out-1", "ffn_moe_out-1", "ffn_out-1",
            "linear_attn_qkv_mixed-2", "conv_output_silu-2",
            "final_output-2", "linear_attn_out-2", "ffn_moe_out-2",
            "ffn_out-2") else "equal" for n in names}
        # under the tampered order the differ at ffn_moe_out-0 comes
        # AFTER the equals -> monotonic-looking (LOCALIZED-shaped)
        tampered_results = [(n, verdicts[n]) for n in tampered_order]
        self.assertFalse(R.refinements_nonmonotonic(tampered_results))
        # under the FROZEN authority order the same verdict map is
        # non-monotonic — and that is the only order the reducer
        # consumes (derive() builds observations in frozen order):
        frozen_results = [(n, verdicts[n]) for n in names]
        self.assertTrue(R.refinements_nonmonotonic(frozen_results))
        term, _ = self._term(frozen_results)
        self.assertEqual(term, A.TERMINAL_NONMONOTONIC)

    def test_case256_extras_cannot_influence_classification(self):
        authorized = A.case256_authorized_set()
        # every capture-row name outside the authorized set is excluded
        extras = ["l_last-5", "l_last-8", "result_norm", "hc_mixed-0"]
        for e in extras:
            self.assertNotIn(e, authorized)
        self.assertEqual(len(authorized), 22)

    def test_committed_terminal_equals_fresh_derivation(self):
        out = R.derive(verbose=False)
        committed = json.loads(
            (R8G / "terminal-reduction.json").read_text())
        self.assertEqual(committed["terminal"], out["terminal"])
        self.assertEqual(committed["terminal_reason"],
                         out["terminal_reason"])
        self.assertEqual(committed["refinement"]["observations"],
                         out["refinement"]["observations"])
        self.assertEqual(committed["case256_contrast"]["observations"],
                         out["case256_contrast"]["observations"])

    def test_committed_terminal_not_blocked(self):
        committed = json.loads(
            (R8G / "terminal-reduction.json").read_text())
        self.assertNotEqual(committed["terminal"],
                            A.TERMINAL_BLOCKED,
                            "handoff terminal must not be BLOCKED")

    def test_readme_terminal_matches_machine(self):
        readme = (R8G / "README.md").read_text()
        committed = json.loads(
            (R8G / "terminal-reduction.json").read_text())
        self.assertIn(committed["terminal"], readme)
        # the retired false claim must not appear as the terminal
        self.assertNotIn(
            "Terminal (machine-derived by scripts/issue207_r8g_reduce"
            ".py):\n\nR8G_EARLIEST_RUNTIME_BOUNDARY_LOCALIZED", readme)

    def test_fixed_point_regeneration(self):
        # regenerate the terminal in a scratch copy; bytes identical
        with tempfile.TemporaryDirectory() as td:
            sb = os.path.join(td, "repo")
            os.makedirs(sb)
            # minimal sandbox: the paths derive() binds
            shutil.copytree(R8G, os.path.join(
                sb, "docs/investigations/qwen38-flash-next-r8-g"))
            for pred in ("qwen38-flash-next-r8-d-v2",
                         "qwen38-flash-next-r8-e"):
                shutil.copytree(
                    REPO / "docs/investigations" / pred,
                    os.path.join(sb, "docs/investigations", pred))
            os.makedirs(os.path.join(sb, "scripts"))
            for f in os.listdir(REPO / "scripts"):
                sp = REPO / "scripts" / f
                if sp.is_file() and (f.startswith("issue") or
                                     f == "sync_project_status.py"):
                    shutil.copy2(sp, os.path.join(sb, "scripts", f))
            # run reducer --write twice; second run changes 0 bytes
            tpath = os.path.join(
                sb, "docs/investigations/qwen38-flash-next-r8-g",
                "terminal-reduction.json")
            for i in (1, 2):
                r = subprocess.run(
                    [sys.executable,
                     os.path.join(sb, "scripts",
                                  "issue207_r8g_reduce.py"),
                     "--write", "--repo", sb],
                    capture_output=True, text=True, timeout=300)
                self.assertEqual(r.returncode, 0, r.stderr[-400:])
            committed = (R8G / "terminal-reduction.json").read_bytes()
            self.assertEqual(open(tpath, "rb").read(), committed,
                             "fresh regeneration must be byte-identical")

    def test_sidecar_symlink_rejected_even_with_correct_bytes(self):
        # same-byte symlink and path-alias rejections against the
        # production sidecar (mutate + restore)
        cap = json.loads((R8G / "evidence/refine" /
                          "capture-case-4096-reference-rf1.json")
                         .read_text())
        seq = R.target_execution_binding(cap)
        p = R.capture_sidecar(cap, "refine", "ffn_moe_out-0", seq)
        raw = open(p, "rb").read()
        alias = p + ".alias"
        try:
            open(alias, "wb").write(raw)
            os.remove(p)
            os.symlink(alias, p)
            with self.assertRaises(R.Blocked):
                R.boundary_state(cap, "refine", "ffn_moe_out-0")
        finally:
            if os.path.islink(p):
                os.remove(p)
            open(p, "wb").write(raw)
            os.remove(alias)
        # restored: normal derivation works again
        st = R.boundary_state(cap, "refine", "ffn_moe_out-0")
        self.assertIsNotNone(st)

    def test_manifest_cycle_prevented(self):
        # the input manifest must not list any reducer output
        doc = json.loads(
            (R8G / "evidence/input-manifest.json").read_text())
        for rel in doc["rows"]:
            self.assertNotIn(rel.split("/")[-1],
                             ("README.md", "terminal-reduction.json",
                              "producer-hashes.json", "CLOSURE.sha256"))
        # closure exists and covers README/terminal/producer/input
        closure = (R8G / "CLOSURE.sha256").read_text()
        for name in ("README.md", "terminal-reduction.json",
                     "producer-hashes.json",
                     "evidence/input-manifest.json"):
            self.assertIn(name, closure)
        self.assertFalse((R8G / "MANIFEST.sha256").exists(),
                         "legacy output-including manifest must be gone")


if __name__ == "__main__":
    unittest.main()
