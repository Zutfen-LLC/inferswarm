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


if __name__ == "__main__":
    unittest.main()
