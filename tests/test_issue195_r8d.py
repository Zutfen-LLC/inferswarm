"""Issue #195 R8-D focused retention tests (CPU-only, stdlib)."""
import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import issue195_r8d_authority as A  # noqa: E402

AREA = REPO / "docs" / "investigations" / "qwen38-flash-next-r8-d"
EV = AREA / "evidence"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load(p):
    return json.loads(Path(p).read_text())


class TestAuthorityFreeze(unittest.TestCase):
    def test_freeze_constants_bound(self):
        self.assertEqual(A.START_MAIN,
                         "f65b70970a9a10bf57bd58a902fe6e08b588c619")
        self.assertEqual(A.REQUEST_CONTRACT["samplers"], ["top_k"])
        self.assertEqual(A.REQUEST_CONTRACT["top_k"], 1)
        self.assertEqual(A.REQUEST_CONTRACT["n_predict"], 8)
        self.assertNotIn("greedy", json.dumps(A.REQUEST_CONTRACT))

    def test_terminals_distinct_and_exact(self):
        terms = {A.TERMINAL_PASS, A.TERMINAL_FAIL, A.TERMINAL_BLOCKED}
        self.assertEqual(len(terms), 3)
        self.assertEqual(A.TERMINAL_FAIL,
                         "R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_FAIL")

    def test_split_pins_match_r8a_census(self):
        census = load(REPO / "docs/investigations/qwen38-flash-next-r8-a"
                      / "gguf-census.json")
        for f, size, h in census["files"]:
            if "UD-IQ1_S" in f:
                name = f.split("/")[-1]
                self.assertEqual(A.SPLIT_SHA256[name], h)

    def test_predecessor_bundles_byte_preserved(self):
        for area in ("qwen38-flash-next-r8-a", "qwen38-flash-next-r8-b",
                     "qwen38-flash-next-r8-c"):
            m = REPO / "docs/investigations" / area / "MANIFEST.sha256"
            for line in m.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                h, p = line.split(None, 1)
                p = p.lstrip("*")
                self.assertEqual(sha(REPO / p), h,
                                 f"predecessor row drifted: {p}")


class TestTerminalReduction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = load(AREA / "terminal-reduction.json")

    def test_terminal_is_fail_and_machine_derived(self):
        self.assertEqual(self.doc["terminal"], A.TERMINAL_FAIL)

    def test_all_prereq_checks_green(self):
        skip = {"all_cases_token_exact", "stop_semantics_equal_all_cases"}
        for k, v in self.doc["checks"].items():
            if k not in skip:
                self.assertTrue(v, f"prereq check failed: {k}")

    def test_fail_driver_is_token_mismatch(self):
        self.assertFalse(self.doc["checks"]["all_cases_token_exact"])
        self.assertFalse(self.doc["checks"]["stop_semantics_equal_all_cases"])
        self.assertIn("valid candidate correctness output",
                      self.doc["terminal_basis"])

    def test_per_case_pattern(self):
        pc = self.doc["per_case"]
        self.assertTrue(pc["case-1024"]["token_exact"])
        self.assertTrue(pc["case-3072"]["token_exact"])
        self.assertFalse(pc["case-256"]["token_exact"])
        self.assertEqual(pc["case-256"]["first_divergence_position"], 5)
        self.assertFalse(pc["case-4096"]["token_exact"])
        self.assertEqual(pc["case-4096"]["first_divergence_position"], 0)

    def test_reducer_check_mode_green(self):
        r = subprocess.run(
            [sys.executable, str(REPO / "scripts"
                                 / "issue195_terminal_reduction.py"), "--check"],
            capture_output=True, text=True, cwd=REPO)
        self.assertIn("CHECK OK", r.stdout, r.stderr)

    def test_reducer_derives_from_bytes_not_authored_terminal(self):
        src = (REPO / "scripts/issue195_terminal_reduction.py").read_text()
        # main()'s write path (before the --check branch) must not load
        # the terminal-reduction.json it is about to produce
        main_fn = src.split("def main")[1]
        write_path = main_fn.split("if args.check:")[0]
        # the terminal/classification inputs are run/probe/inventory bytes;
        # the output doc is never loaded in the write path
        self.assertNotIn("load(out)", write_path)
        self.assertNotIn('load(os.path.join(AREA, "terminal-reduction',
                         write_path)


class TestEvidenceRetention(unittest.TestCase):
    def test_manifest_covers_all_evidence(self):
        m = AREA / "MANIFEST.sha256"
        listed = set()
        for line in m.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                h, p = line.split(None, 1)
                p = p.lstrip("*")
                listed.add(p)
                self.assertEqual(sha(REPO / p), h, f"row drift: {p}")
        ondisk = {str(p.relative_to(REPO))
                  for p in AREA.rglob("*")
                  if p.is_file() and p.name not in
                  ("MANIFEST.sha256", "producer-hashes.json")}
        self.assertEqual(listed, ondisk,
                         f"delta: {listed ^ ondisk}")

    def test_host_inventory_present_all_hosts(self):
        for h in ("inferswarm01", "inferswarm03", "inferswarm04"):
            f = EV / "host-inventory" / f"{h}-inventory-raw.txt"
            self.assertTrue(f.exists())
            t = f.read_text()
            self.assertIn("=== binary hashes ===", t)
            self.assertIn(A.BINARY_SHA256["llama-server"], t)

    def test_split_rehash_matches_pins(self):
        d = load(EV / "split-identity" / "split-rehash.json")
        self.assertTrue(d["all_members_match_r8a_pins"])
        self.assertEqual(d["total_bytes"], A.SPLIT_TOTAL_BYTES)

    def test_reference_frozen_doc_matches_run_bytes(self):
        frozen = load(EV / "reference" / "frozen-reference.json")
        run = load(EV / "reference" / "ref-run-1.json")
        for r in run["results"]:
            c = frozen["cases"][r["case_id"]]
            self.assertEqual(c["generated_tokens"], r["generated_tokens"])
            self.assertEqual(c["stop_type"], r["stop_type"])

    def test_reference_deterministic_3x(self):
        runs = [load(EV / "reference" / f"ref-run-{i}.json") for i in (1, 2, 3)]
        for ci in range(4):
            a = runs[0]["results"][ci]
            for i in (1, 2):
                b = runs[i]["results"][ci]
                self.assertEqual(a["generated_tokens"], b["generated_tokens"])
                self.assertEqual(a["stop_type"], b["stop_type"])

    def test_candidate_deterministic_3x(self):
        runs = [load(EV / "candidate" / f"cand-run-{i}.json") for i in (1, 2, 3)]
        for ci in range(4):
            a = runs[0]["results"][ci]
            for i in (1, 2):
                b = runs[i]["results"][ci]
                self.assertEqual(a["generated_tokens"], b["generated_tokens"])

    def test_request_contract_identical_all_runs(self):
        paths = ([EV / "reference" / f"ref-run-{i}.json" for i in (1, 2, 3)]
                 + [EV / "candidate" / f"cand-run-{i}.json" for i in (1, 2, 3)])
        for p in paths:
            self.assertEqual(load(p)["request_contract"],
                             A.REQUEST_CONTRACT, f"contract drift: {p}")

    def test_case4096_candidate_eos_is_real_prefill(self):
        d = load(EV / "candidate" / "cand-run-1.json")
        r = [x for x in d["results"] if x["case_id"] == "case-4096"][0]
        self.assertEqual(r["stop_type"], "eos")
        self.assertEqual(r["generated_tokens"], [248046])
        self.assertEqual(r["prompt_len"], 4097)
        t = r["timings"]
        self.assertGreater(t["prompt_ms"], 10000)  # full prefill happened
        self.assertEqual(t["prompt_n"], 4097)

    def test_sampler_probes_classified(self):
        for p in (EV / "sampler-contract" / "sampler-probe-ref.json",
                  EV / "candidate" / "sampler-probe-cand.json",
                  EV / "candidate" / "sampler-probe-cand-restart.json"):
            d = load(p)
            v = d["variants"]
            self.assertEqual(v["canonical"]["classification"],
                             "TRUE_GREEDY_PROVEN")
            self.assertIn("logits -> top-k -> dist",
                          v["canonical"]["log_evidence"]["chains"])
            self.assertEqual(
                v["canonical"]["log_evidence"]["unresolved_warnings"], 0)
            self.assertEqual(v["legacy"]["classification"],
                             "NONCANONICAL_LEGACY_GREEDY")
            self.assertGreaterEqual(
                v["legacy"]["log_evidence"]["greedy_unresolved_warnings"], 1)
            self.assertEqual(v["wide"]["classification"], "NOT_TRUE_GREEDY")

    def test_no_nprobs_in_correctness_requests(self):
        for arm, names in (("reference", ["ref-run-1.json", "ref-run-2.json",
                                          "ref-run-3.json"]),
                           ("candidate", ["cand-run-1.json", "cand-run-2.json",
                                          "cand-run-3.json"])):
            for n in names:
                rc = load(EV / arm / n)["request_contract"]
                self.assertNotIn("n_probs", rc)

    def test_restart_sentinels_identity(self):
        for c in ("case-256", "case-4096"):
            rr = load(EV / "candidate" / f"cand-restart-{c}.json")
            pre = load(EV / "candidate" / "cand-run-1.json")
            rt = [x for x in rr["results"] if x["case_id"] == c][0]
            pt = [x for x in pre["results"] if x["case_id"] == c][0]
            self.assertEqual(rt["generated_tokens"], pt["generated_tokens"])
            self.assertEqual(rt["stop_type"], pt["stop_type"])

    def test_negative_controls_all_fail_closed(self):
        d = load(EV / "negative-controls" / "negative-controls.json")
        self.assertTrue(d["all_fail_closed"])
        self.assertGreaterEqual(len(d["controls"]), 13)


class TestProducerHashes(unittest.TestCase):
    def test_producer_hashes_current(self):
        d = load(AREA / "producer-hashes.json")
        for rel, h in d.items():
            p = REPO / rel
            self.assertTrue(p.exists(), rel)
            self.assertEqual(sha(p), h, f"producer drift: {rel}")


if __name__ == "__main__":
    unittest.main()
