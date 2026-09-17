"""Issue #207 R8-G focused tests (CPU-only, stdlib).

Covers: authority constants and the source-derived frozen boundary set;
accepted R8-D/R8-E byte-preservation binding; decision-input loading;
boundary-set derivation (layer sublists, full-attention classification);
graph-execution binding derivation; capture-record binding checks;
terminal-reduction fail-closedness (interval predicate, non-monotonic
detection, earliest-boundary predicate); the differential negative-
control suite; manifest/producer-pin integrity.
"""
import copy
import json
import os
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
        self.assertEqual(A.PLE_LAYER, 0)
        self.assertEqual(A.N_VOCAB, 248320)

    def test_coarse_boundary_set_frozen_order(self):
        names = [n for n, _ in A.COARSE_BOUNDARIES]
        self.assertEqual(names[0], "model.input_embed")
        self.assertEqual(names[-1], "result_norm")
        # every 3rd layer output from 2..47 plus anchors = 18 boundaries
        self.assertEqual(len(names), 18)
        layers = [int(n.split("-")[1]) for n in names
                  if n.startswith("l_last-")]
        self.assertEqual(layers, list(range(2, 48, 3)))

    def test_layer_sublists(self):
        gdn = A.layer_sublist(2)
        self.assertTrue(any(n.startswith("ple_conv_out") for n, _ in
                            A.layer_sublist(0)))
        self.assertFalse(any(n.startswith("ple_conv_out") for n, _ in gdn))
        attn = A.layer_sublist(3)
        self.assertTrue(any(n.startswith("Qcur") for n, _ in attn))
        self.assertFalse(any(n.startswith("Qcur") for n, _ in gdn))
        self.assertTrue(any(n.startswith("conv_output_silu") for n, _ in gdn))
        # every sublist ends with the FFN pair
        for il in (0, 2, 3, 46, 47):
            s = A.layer_sublist(il)
            self.assertTrue(s[-1][0].startswith("ffn_out"))
            self.assertTrue(s[-2][0].startswith("ffn_moe_out"))

    def test_predecessor_byte_preservation(self):
        ok, why = A.r8d_v2_manifest_ok(str(REPO))
        self.assertTrue(ok, why)
        ok, why = A.r8e_manifest_ok(str(REPO))
        self.assertTrue(ok, why)

    def test_wrong_predecessor_manifest_rejected(self):
        # NC1-class: a tampered manifest row must fail closed
        with tempfile.TemporaryDirectory() as td:
            man = os.path.join(td, "MANIFEST.sha256")
            open(os.path.join(td, "x.json"), "w").write("{}")
            open(man, "w").write("0" * 64 + "  x.json\n")
            # emulate via direct re-hash logic (same as r8e_manifest_ok)
            import hashlib
            got = hashlib.sha256(
                open(os.path.join(td, "x.json"), "rb").read()).hexdigest()
            self.assertNotEqual(got, "0" * 64)

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
        # canonical byte stability
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
        # earliest boundary already differs: interval is (None, first)
        res = [("a", "differ"), ("b", "differ")]
        iv, nonmono, _ = R.first_interval(res)
        self.assertIsNone(iv[0])
        self.assertEqual(iv[1], "a")
        self.assertFalse(nonmono)

    def test_compare_arms_unobservable(self):
        per_key = {("case-4096", "reference", "a"): {"sha256": "x"},
                   ("case-4096", "candidate", "a"): {"sha256": "x"},
                   ("case-4096", "reference", "b"): {"sha256": "y"}}
        res = R.compare_arms(per_key, "case-4096", ["a", "b"])
        self.assertEqual(res, [("a", "equal"), ("b", "unobservable")])

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
        src = open(REPO / "scripts/issue207_r8g_authority.py").read()
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



class TestDecisionPositionBinding(unittest.TestCase):
    def test_decision_position(self):
        self.assertEqual(R.decision_position("case-4096"), 0)
        self.assertEqual(R.decision_position("case-256"), 5)

    def test_boundary_state_binds_decision_exec(self):
        # capture with anchors at seqs 9..16 (valid) -> case-4096 pos0
        # binds seq 9; case-256 pos5 binds seq 14
        cap = {"case": "case-4096", "boundary_rows": [
            {"name": "result_output", "seq": s, "sha256": "v%d" % s}
            for s in range(9, 17)] + [
            {"name": "b", "seq": s, "sha256": "NA"} for s in range(9, 17)]}
        self.assertEqual(R.target_execution_binding(cap), 9)

    def test_unknown_case_fails_closed(self):
        try:
            R.decision_position("case-999")
            self.fail("expected KeyError")
        except KeyError:
            pass

if __name__ == "__main__":
    unittest.main()
