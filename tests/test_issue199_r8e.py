"""Issue #199 R8-E focused tests (CPU-only, stdlib).

Covers: authority constants; accepted R8-D v2 byte-preservation binding;
decision-input loading (teacher-forced identities from accepted bytes);
instrumentation record shape; observation-record binding checks
(token-position binding, placement swap, n_probs substitution,
state-class separation); terminal-reduction fail-closedness; the
differential negative-control suite; manifest/producer-pin integrity.
"""
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import issue199_r8e_authority as A  # noqa: E402
import issue199_r8e_terminal_reduction as R_mod  # noqa: E402

R_char = lambda ref, cand, focus: R_mod.characterize(  # noqa: E731
    "synthetic-case", ref, cand, focus)

R8E = REPO / "docs/investigations/qwen38-flash-next-r8-e"
R8E_EV = R8E / "evidence"
R8D_V2 = REPO / "docs/investigations/qwen38-flash-next-r8-d-v2"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load(p):
    return json.loads(Path(p).read_text())


class AuthorityTests(unittest.TestCase):
    def test_start_main_is_accepted_pr197_merge(self):
        self.assertEqual(A.START_MAIN,
                         "f142a0d9b693f999685960c641b2a8fe362c4e1e")

    def test_accepted_r8d_v2_evidence_byte_preserved(self):
        ok, msg = A.r8d_v2_manifest_ok(str(REPO))
        self.assertTrue(ok, msg)

    def test_decision_inputs_from_accepted_bytes(self):
        d = A.load_decision_inputs(str(REPO))
        self.assertEqual(
            d["case-256"]["reference"]["generated_tokens"][:5],
            A.CASE256_PREFIX)
        self.assertEqual(
            d["case-256"]["reference"]["generated_tokens"][5], 271)
        self.assertEqual(
            d["case-256"]["candidate"]["generated_tokens"][5], 34227)
        self.assertEqual(
            d["case-4096"]["reference"]["generated_tokens"][0], 328)
        self.assertEqual(
            d["case-4096"]["candidate"]["generated_tokens"][0], 248046)
        self.assertEqual(len(
            d["case-4096"]["reference"]["prompt_token_ids"]), 4097)

    def test_wrong_decision_input_fails_closed(self):
        d = A.load_decision_inputs(str(REPO))
        d["case-256"]["reference"]["generated_tokens"][5] = 999
        # the assertions live in load_decision_inputs; simulate by
        # re-running against a sandboxed corrupted copy
        with tempfile.TemporaryDirectory() as tmp:
            import shutil
            root = Path(tmp)
            # copy only what load_decision_inputs reads, preserving the
            # docs/ prefix the R8D_RUN_RECORDS paths carry
            rel = Path("docs/investigations/qwen38-flash-next-r8-d-v2")
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(REPO / rel, dst)
            bad = dst / "evidence/reference/ref-run-1.json"
            j = load(bad)
            j["results"][0]["parsed_from_retained_bytes"][
                "generated_tokens"][5] = 999
            bad.write_text(json.dumps(j))
            with self.assertRaises(AssertionError):
                A.load_decision_inputs(str(root))

    def test_producer_pins_ok(self):
        ok, msg = A.producer_pins_ok(str(REPO))
        self.assertTrue(ok, msg)

    def test_serialize_request_canonical(self):
        b = A.serialize_request([1, 2, 3])
        self.assertEqual(
            b, json.dumps(
                {"samplers": ["top_k"], "top_k": 1, "temperature": 0.0,
                 "seed": 0, "cache_prompt": False, "stream": False,
                 "return_tokens": True, "n_predict": 8, "prompt": [1, 2, 3]},
                sort_keys=True, separators=(",", ":"),
                ensure_ascii=True).encode())
        for k in A.FORBIDDEN_REQUEST_KEYS:
            self.assertNotIn(k.encode(), b)


class InstrumentationTests(unittest.TestCase):
    def test_record_shape(self):
        d = load(R8E_EV / "instrumentation/instrumentation.json")
        self.assertEqual(d["base_commit"], A.LLAMA_CPP_COMMIT)
        self.assertEqual(len(d["binary_sha256"]), 64)
        self.assertEqual(d["accepted_llama_server_sha256_unchanged"],
                         A.ACCEPTED_BINARY_SHA256["llama-server"])
        self.assertEqual(d["accepted_ggml_rpc_server_sha256_unchanged"],
                         A.ACCEPTED_BINARY_SHA256["ggml-rpc-server"])

    def test_patch_bytes_retained(self):
        self.assertTrue((R8E_EV / "instrumentation/"
                         "applied-source.patch").exists())
        self.assertTrue((R8E_EV / "instrumentation/"
                         "apply_hook.py").exists())


class CaptureRecordTests(unittest.TestCase):
    """Binding checks against the retained observation records."""

    CASES = ["case-256", "case-4096"]
    ARMS = ["reference", "candidate"]

    def _caps(self, state="incremental", ext="obs"):
        d = R8E_EV / ("observations" if state == "incremental"
                      else "observations-tf")
        for case in self.CASES:
            for arm in self.ARMS:
                for i in (1, 2):
                    p = d / f"capture-{case}-{arm}-{ext}{i}.json"
                    if p.exists():
                        yield case, arm, i, load(p)

    def test_records_present(self):
        got = list(self._caps())
        self.assertEqual(len(got), 8,
                         f"expected 8 incremental captures, got {len(got)}")

    def test_binding_blocks(self):
        inputs = A.load_decision_inputs(str(REPO))
        import issue199_r8e_terminal_reduction as R
        for case, arm, i, rec in self._caps():
            probs, row = R.check_capture(rec, case, arm, inputs)
            self.assertEqual(probs, [], f"{case}/{arm}: {probs}")
            self.assertIsNotNone(row)

    def test_state_class_separation(self):
        for case, arm, i, rec in self._caps():
            self.assertEqual(rec["state_class"], "incremental")
        for case, arm, i, rec in self._caps(state="tf", ext="tf"):
            self.assertEqual(rec["state_class"], "tf")
            # tf captures must bind pos 0 with the tf prefix in-request
            self.assertEqual(rec["generated_position_observed"], 0)

    def test_incremental_tokens_equal_accepted(self):
        exp = {("case-256", "reference"): 271,
               ("case-256", "candidate"): 34227,
               ("case-4096", "reference"): 328,
               ("case-4096", "candidate"): 248046}
        pos = {"case-256": 5, "case-4096": 0}
        for case, arm, i, rec in self._caps():
            gt = rec["response_generated_tokens"]
            self.assertEqual(gt[pos[case]], exp[(case, arm)],
                             f"{case}/{arm}/obs{i}")

    def test_no_n_probs_anywhere(self):
        for case, arm, i, rec in self._caps():
            req = json.loads(base64.b64decode(rec["request_body_b64"]))
            for k in A.FORBIDDEN_REQUEST_KEYS:
                self.assertNotIn(k, req)

    def test_repeat_stability(self):
        for case in self.CASES:
            for arm in self.ARMS:
                d = R8E_EV / "observations"
                r1 = load(d / f"capture-{case}-{arm}-obs1.json")
                r2 = load(d / f"capture-{case}-{arm}-obs2.json")
                self.assertEqual(r1["response_generated_tokens"],
                                 r2["response_generated_tokens"])
                self.assertEqual(r1["f32_row_sha256"],
                                 r2["f32_row_sha256"])

    def test_repeat_stability_is_actual_byte_pinned(self):
        """The real evidence pin opens both fixed raw sidecars and both
        row copies; record digests are only cross-checks."""
        for case in self.CASES:
            for arm in self.ARMS:
                actual = []
                for i in (1, 2):
                    rec = load(R8E_EV / "observations" /
                               f"capture-{case}-{arm}-obs{i}.json")
                    view, ident, probs = R_mod.bind_repeat_to_bytes(
                        rec, str(REPO), case, arm, i)
                    self.assertEqual(probs, [], f"{case}/{arm}/obs{i}: {probs}")
                    self.assertEqual(ident["label"], f"{case}-{arm}-obs{i}")
                    self.assertTrue((R8E_EV / "observations" /
                                     Path(ident["raw_f32_rel"]).name).is_file())
                    self.assertEqual(view["actual_sha256"],
                                     sha(REPO / ident["row_copy_rel"]))
                    actual.append(view["actual_sha256"])
                self.assertEqual(actual[0], actual[1], f"{case}/{arm}")


class NonPerturbationTests(unittest.TestCase):
    def test_accepted_binary_controls_reproduce_r8d(self):
        exp = {("case-256", "reference"): 271,
               ("case-256", "candidate"): 34227,
               ("case-4096", "reference"): 328,
               ("case-4096", "candidate"): 248046}
        pos = {"case-256": 5, "case-4096": 0}
        n = 0
        for p in sorted((R8E_EV / "nonperturbation").glob("capture-*.json")):
            rec = load(p)
            case, arm = rec["case"], rec["arm"]
            gt = rec["response_generated_tokens"]
            self.assertEqual(gt[pos[case]], exp[(case, arm)], p.name)
            self.assertEqual(rec["mode"], "accepted")
            n += 1
        self.assertEqual(n, 8)


class CharacterizationTests(unittest.TestCase):
    """Mutation tests around characterize() semantics (correction round
    for the NO-GO review of PR #205).

    Fixtures are SYNTHETIC (arbitrary token ids / logits, NOT the
    observed R8-E values) so no class boundary can have been tuned to
    the retained campaign data.
    """

    FOCUS = [101, 202]

    @staticmethod
    def _view(top, focus_ranks, n_nonfinite=0, focus_logits=None):
        """Build an arm_view-shaped dict from explicit rank facts."""
        focus = {}
        for tok, rank in focus_ranks.items():
            logit = None
            if focus_logits and tok in focus_logits:
                logit = focus_logits[tok]
            else:
                for t, v in top:
                    if t == tok:
                        logit = v
            focus[tok] = {"rank": rank, "logit": logit}
        w, wl = top[0]
        r, rl = top[1] if len(top) > 1 else (None, None)
        return {
            "top16_ids": [t for t, _v in top],
            "top16": top, "winner": w, "winner_logit": wl,
            "runner_up": r, "runner_up_logit": rl,
            "top1_top2_margin": (wl - rl) if r is not None else None,
            "focus_tokens": focus, "n_nonfinite": n_nonfinite,
        }

    @staticmethod
    def _coherent_top16():
        """16-entry top list, arbitrary synthetic ids/logits."""
        return [[7000 + i, 10.0 - 0.31 * i] for i in range(16)]

    def _pair(self, ref_ranks, cand_ranks, ref_top=None, cand_top=None,
              ref_nonfinite=0, cand_nonfinite=0):
        ref_top = ref_top if ref_top is not None else self._coherent_top16()
        cand_top = (cand_top if cand_top is not None
                    else [list(x) for x in ref_top])
        ref = self._view(ref_top, ref_ranks, ref_nonfinite)
        cand = self._view(cand_top, cand_ranks, cand_nonfinite)
        return ref, cand

    def test_clean_focal_swap_is_narrow_inversion(self):
        # focal tokens 101/202 trade ranks 1<->2; rest of top-16 shared
        ref_top = [[101, 9.5], [202, 9.1]] + self._coherent_top16()[2:]
        cand_top = [[202, 9.4], [101, 9.2]] + self._coherent_top16()[2:]
        ref, cand = self._pair(
            {101: 1, 202: 2}, {101: 2, 202: 1},
            ref_top=ref_top, cand_top=cand_top)
        c = R_char(ref, cand, self.FOCUS)
        self.assertEqual(c["characterization"], "narrow-winner-inversion")
        self.assertTrue(c["focal_rank_facts"][
                            "both_focal_rank_1_or_2_in_both_arms"])
        self.assertTrue(c["focal_rank_facts"]["focal_ordering_inverted"])

    def test_high_overlap_alone_does_not_imply_narrow(self):
        # 15/16 of the top-16 set is shared, but a focal winner sits at
        # rank 5 in one arm: overlap-only reasoning would wrongly call
        # this a narrow inversion.
        ref_top = [[101, 9.5], [7001, 9.0], [7002, 8.8], [7003, 8.6],
                   [202, 8.4]] + self._coherent_top16()[5:]
        cand_top = [[202, 9.6], [101, 9.3]] + self._coherent_top16()[2:]
        ref, cand = self._pair(
            {101: 1, 202: 5}, {101: 2, 202: 1},
            ref_top=ref_top, cand_top=cand_top)
        c = R_char(ref, cand, self.FOCUS)
        self.assertEqual(c["top16_overlap_count"], 16 - 1)
        self.assertEqual(c["characterization"], "broader-focal-shift")

    def test_focal_rank5_to_rank1_not_clean_swap(self):
        # the exact shape under review: one focal token moves rank 5->1
        # while the opposing winner moves 1->2. This must NOT classify
        # as the same clean 1<->2 inversion as a mutual swap.
        ref_top = [[101, 9.5], [7001, 9.0], [7002, 8.8], [7003, 8.6],
                   [202, 8.4]] + self._coherent_top16()[5:]
        cand_top = [[202, 12.9], [101, 9.9], [7001, 8.9], [7002, 8.7],
                    [7003, 8.5]] + self._coherent_top16()[5:]
        ref, cand = self._pair(
            {101: 1, 202: 5}, {101: 2, 202: 1},
            ref_top=ref_top, cand_top=cand_top)
        c = R_char(ref, cand, self.FOCUS)
        self.assertEqual(c["characterization"], "broader-focal-shift")
        self.assertFalse(c["focal_rank_facts"][
                             "both_focal_rank_1_or_2_in_both_arms"])
        # descriptive raw delta retained WITHOUT thresholding it
        self.assertAlmostEqual(
            c["cross_arm_logit_deltas"]["202"], 12.9 - 8.4)

    def test_nonfinite_forces_materially_different(self):
        ref, cand = self._pair({101: 1, 202: 2}, {101: 2, 202: 1},
                               cand_nonfinite=2)
        c = R_char(ref, cand, self.FOCUS)
        self.assertEqual(
            c["characterization"], "materially-different-score-structure")

    def test_low_overlap_continues_shifted(self):
        base = self._coherent_top16()
        other = [[8000 + i, 9.9 - 0.3 * i] for i in range(16)]
        ref, cand = self._pair(
            {101: 1, 202: 2}, {101: 2, 202: 1},
            ref_top=[[101, 9.5], [202, 9.1]] + base[2:],
            cand_top=[[202, 9.4], [101, 9.2]] + other[2:])
        c = R_char(ref, cand, self.FOCUS)
        self.assertLess(c["top16_overlap_count"], 12)
        self.assertEqual(
            c["characterization"], "materially-different-score-structure")

    def test_focal_missing_from_top16_is_materially_different(self):
        base = self._coherent_top16()
        ref_top = [[101, 9.5], [202, 9.1]] + base[2:]
        cand_top = [[202, 9.4], [101, 9.2]] + base[2:14] + \
            [[9001, 1.0], [9002, 0.9]]
        ref, cand = self._pair(
            {101: 1, 202: 2}, {101: None, 202: 1},
            ref_top=ref_top, cand_top=cand_top)
        c = R_char(ref, cand, self.FOCUS)
        self.assertEqual(
            c["characterization"], "materially-different-score-structure")
        self.assertTrue(c["focal_rank_facts"]["any_focal_rank_missing"])

    def test_uninverted_focal_ordering_not_narrow(self):
        # focal tokens hold ranks 1 and 2 in both arms but the ORDER is
        # the same (no winner change at all between arms for the focal
        # pair): structurally not an inversion.
        ref_top = [[101, 9.5], [202, 9.1]] + self._coherent_top16()[2:]
        cand_top = [[101, 9.4], [202, 9.2]] + self._coherent_top16()[2:]
        ref, cand = self._pair(
            {101: 1, 202: 2}, {101: 1, 202: 2},
            ref_top=ref_top, cand_top=cand_top)
        c = R_char(ref, cand, self.FOCUS)
        self.assertEqual(c["characterization"], "broader-focal-shift")


    def test_forged_hook_focus_rank_contradicts_bytes(self):
        """Correction-round P2 regression: authored hook 'focus' ranks
        are cross-checked against the bytes-derived view; a capture
        whose bytes show the focal winner at rank 5 while the authored
        focus row claims rank 2 must fail closed."""
        import issue199_r8e_terminal_reduction as R
        inputs = A.load_decision_inputs(str(REPO))
        rel = ("evidence/observations/"
               "capture-case-4096-reference-obs1.json")
        rec = load(R8E_EV / "observations" /
                   "capture-case-4096-reference-obs1.json")
        self.assertEqual(rec["label"], "case-4096-reference-obs1")
        # forge the authored focus rank for EOS: bytes say rank 5
        for hr in rec["hook_rows"]:
            if hr["pos"] == 0:
                hr["focus"] = [[328, 1, 15.0245876],
                               [248046, 2, 13.2554426]]
        probs, row = R.check_capture(rec, "case-4096", "reference",
                                     inputs)
        # check_capture itself still passes (binding-only); the
        # bytes-vs-authored contradiction is caught in derive() —
        # prove it there through the real bytes_derived_view +
        # cross-check path:
        bview, bprob = R.bytes_derived_view(rec, str(REPO),
                                            "case-4096", "reference")
        self.assertTrue(any("hook focal 248046 disagrees" in x
                            for x in bprob), bprob)
        self.assertIsNotNone(bview)
        self.assertEqual(bview["focus_tokens"][248046]["rank"], 5)
        hview = R.arm_view(row, [328, 248046])
        self.assertEqual(hview["focus_tokens"][248046]["rank"], 2)
        # and the derive-level cross-check flags exactly this pair
        xb = []
        for tok in (328, 248046):
            br = bview["focus_tokens"][tok]["rank"]
            hr_ = hview["focus_tokens"][tok]["rank"]
            if br != hr_:
                xb.append(tok)
        self.assertEqual(xb, [248046])


class RealEvidenceCharacterizationTests(unittest.TestCase):
    """Pin the corrected reduction on the retained campaign evidence."""

    def _derive(self):
        import issue199_r8e_terminal_reduction as R
        return R.derive()

    def test_case256_is_narrow_inversion(self):
        d = self._derive()
        c = d["per_case"]["case-256"]
        self.assertEqual(c["characterization"], "narrow-winner-inversion")
        self.assertEqual(c["focal_ranks"],
                         {"reference|271": 1, "reference|34227": 2,
                          "candidate|271": 2, "candidate|34227": 1})

    def test_case4096_is_broader_focal_shift(self):
        d = self._derive()
        c = d["per_case"]["case-4096"]
        self.assertEqual(c["characterization"], "broader-focal-shift")
        self.assertEqual(c["focal_ranks"],
                         {"reference|328": 1, "reference|248046": 5,
                          "candidate|328": 2, "candidate|248046": 1})
        self.assertFalse(c["focal_rank_facts"][
                             "both_focal_rank_1_or_2_in_both_arms"])
        # raw descriptive deltas retained, unthresholded
        self.assertAlmostEqual(
            c["cross_arm_logit_deltas"]["248046"], 3.380929, places=6)
        self.assertAlmostEqual(
            c["cross_arm_logit_deltas"]["328"], 0.3927708, places=6)

    def test_terminal_is_deeper_localization(self):
        d = self._derive()
        self.assertEqual(d["terminal"],
                         "R8E_DEEPER_RUNTIME_LOCALIZATION_JUSTIFIED")
        self.assertEqual(d["problems"], [])


class TerminalReductionTests(unittest.TestCase):
    def _run(self, area=None):
        env = dict(os.environ)
        if area:
            env["I199_AREA_OVERRIDE"] = str(area)
        r = subprocess.run(
            [sys.executable, "-c",
             "import sys, json; sys.path.insert(0, %r); "
             "import issue199_r8e_terminal_reduction as R; "
             "r = R.derive(); print(json.dumps("
             "{'terminal': r['terminal'], 'problems': r['problems']}))"
             % str(REPO / "scripts")],
            capture_output=True, text=True, env=env)
        if r.returncode != 0:
            raise AssertionError(r.stderr[-800:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_derives_valid_terminal(self):
        r = self._run()
        self.assertIn(r["terminal"], (
            "R8E_RESIDUAL_DIVERGENCE_CHARACTERIZED",
            "R8E_DEEPER_RUNTIME_LOCALIZATION_JUSTIFIED",
            "R8E_EVIDENCE_BLOCKED"))
        return r

    def test_terminal_written_matches_derive(self):
        if not (R8E / "terminal-reduction.json").exists():
            self.skipTest("terminal not yet written")
        d = load(R8E / "terminal-reduction.json")
        r = self._run()
        self.assertEqual(d["terminal"], r["terminal"])


class ManifestTests(unittest.TestCase):
    def test_manifest_covers_all_evidence(self):
        man = R8E / "MANIFEST.sha256"
        self.assertTrue(man.exists())
        listed = {}
        for line in man.read_text().splitlines():
            digest, name = line.split("  ", 1)
            listed[name] = digest
        on_disk = {p.relative_to(REPO).as_posix()
                   for p in R8E.rglob("*")
                   if p.is_file() and p.name not in (
                       "MANIFEST.sha256", "producer-hashes.json")}
        self.assertEqual(set(listed), on_disk,
                         f"drift: {set(listed) ^ on_disk}")
        for name, digest in listed.items():
            self.assertEqual(sha(REPO / name), digest, name)

    def test_manifest_excludes_itself(self):
        for line in (R8E / "MANIFEST.sha256").read_text().splitlines():
            self.assertNotIn("MANIFEST.sha256", line)

    def test_producer_hashes_pin_all_producers(self):
        pins = load(R8E / "producer-hashes.json")
        for rel in A.R8E_PRODUCERS:
            self.assertIn(rel, pins)
            self.assertEqual(sha(REPO / rel), pins[rel])

    def test_repeat_byte_adversaries_are_retained_and_green(self):
        d = load(R8E_EV / "negative-controls/negative-controls.json")
        self.assertTrue(d["all_moved"])
        names = {x["control"]: x for x in d["controls"]}
        for name in (
                "NC11 stale obs2 authored digest after raw-byte mutation",
                "NC12 obs2 label aliases obs1 label",
                "NC13 obs2 observation-path aliases obs1 JSONL",
                "NC14 obs2 raw-sidecar aliases obs1",
                "NC15 obs2 raw-hook sidecar mutation only",
                "NC16 obs2 retained row-copy mutation only",
                "NC17 internally consistent but byte-different obs2"):
            self.assertIn(name, names)
            self.assertTrue(names[name]["moved"], name)


if __name__ == "__main__":
    unittest.main()
