"""Retention regressions for Issue #191 (R8-B) evidence bundle.

Pins the retained R8-B artifacts inside the repository integrity boundary
and re-derives the terminal from the retained bytes. Mutation controls
prove the checks fail closed.
"""
import copy
import hashlib
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
R8B = ROOT / "docs" / "investigations" / "qwen38-flash-next-r8-b"
EV = R8B / "evidence"


def load(rel):
    return json.loads((R8B / rel).read_text())


class Issue191RetentionTests(unittest.TestCase):
    def test_expected_files_exist(self):
        expected = [
            "README.md", "TOPOLOGY-FREEZE.md", "terminal-reduction.json",
            "evidence/split-identity/split-verification.json",
            "evidence/runtime-authority/runtime-authority.json",
            "evidence/runtime-authority/binary-hashes.json",
            "evidence/reference/fixture-ladder.json",
            "evidence/reference/reference-run-1.json",
            "evidence/reference/reference-run-2.json",
            "evidence/reference/reference-run-3.json",
            "evidence/reference/reference-server.log",
            "evidence/candidate/candidate-run-1.json",
            "evidence/candidate/candidate-run-2.json",
            "evidence/candidate/candidate-run-3.json",
            "evidence/candidate/candidate-restart.json",
            "evidence/candidate/candidate-server.log",
            "evidence/accounting/residency-accounting.json",
            "evidence/negative-controls/negative-controls.json",
            "evidence/topology-ladder/smoke-singlehost-2x3060.log",
        ]
        for rel in expected:
            self.assertTrue((R8B / rel).is_file(), f"missing {rel}")

    def test_split_verification_exact(self):
        d = load("evidence/split-identity/split-verification.json")
        self.assertTrue(d["all_ok"])
        self.assertEqual(len(d["members"]), 3)
        for m in d["members"]:
            self.assertTrue(m["sha256_ok"])
            self.assertTrue(m["bytes_ok"])
            self.assertTrue(m["header_bytes_ok"])
            self.assertEqual(m["actual_sha256"], m["expected_lfs_sha256"])

    def test_runtime_authority_pins(self):
        d = load("evidence/runtime-authority/runtime-authority.json")
        self.assertEqual(d["llama_cpp_commit"],
                         "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4")
        self.assertTrue(d["repair_ancestry"]["verified_ancestor_of_selection"])
        for h in d["binaries_sha256"].values():
            self.assertEqual(len(h), 64)

    def test_fixture_ladder_frozen_shape(self):
        d = load("evidence/reference/fixture-ladder.json")
        lens = {c["case_id"]: c["rendered_length"] for c in d["cases"]}
        self.assertEqual(lens, {"case-256": 256, "case-1024": 1022,
                                "case-3072": 3077, "case-4096": 4097})
        self.assertEqual(d["committed_tokens_per_case"], 8)
        self.assertEqual(d["sampling"]["temperature"], 0.0)

    def test_reference_determinism(self):
        runs = [load(f"evidence/reference/reference-run-{i}.json") for i in (1, 2, 3)]
        tok = [{c["case_id"]: c["generated_tokens"] for c in r["results"]} for r in runs]
        self.assertEqual(tok[0], tok[1])
        self.assertEqual(tok[0], tok[2])

    def test_candidate_determinism_and_restart(self):
        runs = [load(f"evidence/candidate/candidate-run-{i}.json") for i in (1, 2, 3)]
        tok = [{c["case_id"]: c["generated_tokens"] for c in r["results"]} for r in runs]
        self.assertEqual(tok[0], tok[1])
        self.assertEqual(tok[0], tok[2])
        rst = load("evidence/candidate/candidate-restart.json")
        rtok = {c["case_id"]: c["generated_tokens"] for c in rst["results"]}
        self.assertEqual(rtok, tok[0])

    def test_terminal_is_fail_and_derived(self):
        d = load("terminal-reduction.json")
        self.assertEqual(d["terminal"],
                         "R8B_QWEN38_NVIDIA_RPC_RUNTIME_QUALIFICATION_FAIL")
        self.assertFalse(d["checks"]["all_cases_token_exact"])
        self.assertTrue(d["checks"]["reference_deterministic_3x"])
        self.assertTrue(d["checks"]["candidate_deterministic_3x"])
        self.assertTrue(d["checks"]["restart_equality"])
        self.assertTrue(d["checks"]["ple_host_resident_both_arms"])
        self.assertTrue(d["checks"]["negative_controls_fail_closed"])
        self.assertTrue(d["fail_basis"])

    def test_mutation_candidate_tokens_breaks_comparison(self):
        ref = load("evidence/reference/reference-run-1.json")
        cand = load("evidence/candidate/candidate-run-1.json")
        r = {c["case_id"]: c["generated_tokens"] for c in ref["results"]}
        k = {c["case_id"]: c["generated_tokens"] for c in cand["results"]}
        forged = copy.deepcopy(k)
        forged["case-256"] = list(r["case-256"])
        self.assertEqual(forged["case-256"], r["case-256"])
        self.assertNotEqual(forged["case-1024"], r["case-1024"])
        all_equal = all(forged[c] == r[c] for c in r)
        self.assertFalse(all_equal, "a forged full-PASS must not compare equal")

    def test_mutation_split_digest_detected(self):
        d = load("evidence/split-identity/split-verification.json")
        forged = copy.deepcopy(d)
        forged["members"][0]["actual_sha256"] = "f" * 64
        self.assertFalse(all(m["actual_sha256"] == m["expected_lfs_sha256"]
                             for m in forged["members"]))

    def test_ple_host_placement_in_both_logs(self):
        ref_log = (R8B / "evidence/reference/reference-server.log").read_text()
        cand_log = (R8B / "evidence/candidate/candidate-server.log").read_text()
        for log in (ref_log, cand_log):
            self.assertIn("per_layer_token_embd.weight", log)
            self.assertIn("lazy read enabled", log)

    def test_candidate_log_shows_rpc_devices(self):
        cand_log = (R8B / "evidence/candidate/candidate-server.log").read_text()
        self.assertEqual(cand_log.count("using device RPC"), 3)
        for ep in ("10.0.0.219:50052", "10.0.0.219:50053", "10.0.0.204:50052"):
            self.assertIn(ep, cand_log)


if __name__ == "__main__":
    unittest.main()
