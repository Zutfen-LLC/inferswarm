"""Issue #195 R8-D v2 focused tests (CPU-only, stdlib).

Covers: authority freeze constants; byte-preservation of R8-A/B/C and
the superseded v1 bundle; run-record byte-exactness; prospective
reference-freeze mechanics; BLOCKED-vs-FAIL terminal semantics; the
differential negative-control suite; manifest/producer-pin integrity.
"""
import base64
import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import issue195_v2_authority as A  # noqa: E402

V1_AREA = REPO / "docs/investigations/qwen38-flash-next-r8-d"
V2_AREA = REPO / "docs/investigations/qwen38-flash-next-r8-d-v2"
V2_EV = V2_AREA / "evidence"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load(p):
    return json.loads(Path(p).read_text())


def run_reducer(area=None):
    env = dict(os.environ)
    if area:
        env["I195_AREA_OVERRIDE"] = str(area)
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys, json; sys.path.insert(0, %r); "
         "import issue195_v2_terminal_reduction as R; "
         "r = R.derive(); print(json.dumps("
         "{'terminal': r['terminal'], 'checks': r['checks'], "
         "'valid': r['has_valid_candidate_output']}))" % str(REPO / "scripts")],
        capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise AssertionError(r.stderr[-800:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def sandbox_copy(tmp):
    import shutil
    for src, rel in ((V2_AREA, "docs/investigations/qwen38-flash-next-r8-d-v2"),
                     (V1_AREA, "docs/investigations/qwen38-flash-next-r8-d"),
                     (REPO / "docs/investigations/qwen38-flash-next-r8-a",
                      "docs/investigations/qwen38-flash-next-r8-a"),
                     (REPO / "docs/investigations/qwen38-flash-next-r8-b",
                      "docs/investigations/qwen38-flash-next-r8-b"),
                     (REPO / "docs/investigations/qwen38-flash-next-r8-c",
                      "docs/investigations/qwen38-flash-next-r8-c")):
        dst = Path(tmp) / rel
        if not dst.exists():
            shutil.copytree(src, dst)
    return Path(tmp)


class TestAuthorityFreezeV2(unittest.TestCase):
    def test_freeze_constants(self):
        self.assertEqual(A.START_MAIN,
                         "f65b70970a9a10bf57bd58a902fe6e08b588c619")
        self.assertEqual(A.CAMPAIGN_ID,
                         "issue195-r8d-true-greedy-requal-v2")
        self.assertEqual(A.SUPERSEDED_V1_CAMPAIGN,
                         "issue195-r8d-true-greedy-requal-v1")
        self.assertEqual(A.REQUEST_CONTRACT["samplers"], ["top_k"])
        self.assertEqual(A.REQUEST_CONTRACT["top_k"], 1)
        self.assertEqual(A.REQUEST_CONTRACT["n_predict"], 8)
        self.assertNotIn("greedy", json.dumps(A.REQUEST_CONTRACT))
        self.assertIn("n_probs", A.FORBIDDEN_REQUEST_KEYS)

    def test_v2_namespace_is_additive_sibling(self):
        self.assertTrue((V2_AREA / "AUTHORITY-FREEZE-V2.md").exists())
        self.assertFalse((V1_AREA / "v2").exists())
        # v1 area manifest still covers exactly the v1 bytes
        listed = set()
        for line in (V1_AREA / "MANIFEST.sha256").read_text().splitlines():
            if line.strip():
                listed.add(line.split(None, 1)[1].lstrip("*"))
        ondisk = {str(p.relative_to(REPO)) for p in V1_AREA.rglob("*")
                  if p.is_file() and p.name not in
                  ("MANIFEST.sha256", "producer-hashes.json")}
        self.assertEqual(listed, ondisk)

    def test_predecessor_bundles_byte_preserved(self):
        for area in ("qwen38-flash-next-r8-a", "qwen38-flash-next-r8-b",
                     "qwen38-flash-next-r8-c"):
            m = REPO / "docs/investigations" / area / "MANIFEST.sha256"
            for line in m.read_text().splitlines():
                if not line.strip() or line.startswith("#"):
                    continue
                h, p = line.split(None, 1)
                self.assertEqual(sha(REPO / p.lstrip("*")), h,
                                 f"predecessor drift: {p}")

    def test_v1_evidence_byte_preserved(self):
        for line in (V1_AREA / "MANIFEST.sha256").read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            h, p = line.split(None, 1)
            self.assertEqual(sha(REPO / p.lstrip("*")), h,
                             f"v1 evidence drift: {p}")

    def test_split_rehash_matches_pins(self):
        d = load(V2_EV / "split-identity" / "split-rehash.json")
        self.assertTrue(d["all_members_match_r8a_pins"])
        self.assertEqual(d["total_bytes"], A.SPLIT_TOTAL_BYTES)
        for m in d["members"]:
            self.assertEqual(A.SPLIT_SHA256[m["file"]], m["sha256"])

    def test_host_inventory_fresh_all_hosts(self):
        by_host = {spec["host"]: spec for spec in A.TOPOLOGY.values()}
        for h in ("inferswarm01", "inferswarm03", "inferswarm04"):
            f = V2_EV / "host-inventory" / f"{h}-inventory-raw.txt"
            self.assertTrue(f.exists())
            t = f.read_text()
            self.assertIn(A.BINARY_SHA256["llama-server"], t)
            self.assertIn("2026-09-15", t)  # fresh at v2 freeze
            for g in by_host[h]["gpus"]:
                self.assertIn(g["uuid"], t)

    def test_producer_pins_current(self):
        d = load(V2_AREA / "producer-hashes.json")
        for rel, h in d.items():
            p = REPO / rel
            self.assertTrue(p.exists(), rel)
            self.assertEqual(sha(p), h, f"producer drift: {rel}")


class TestRunRecordByteExactness(unittest.TestCase):
    RUNS = None

    @classmethod
    def setUpClass(cls):
        cls.RUNS = ([V2_EV / "reference" / f"ref-run-{i}.json"
                     for i in (1, 2, 3)]
                    + [V2_EV / "candidate" / f"cand-run-{i}.json"
                       for i in (1, 2, 3)]
                    + [V2_EV / "candidate" / f"cand-restart-{c}.json"
                       for c in ("case-256", "case-4096")])

    def test_all_runs_present(self):
        if not (V2_EV / "reference" / "ref-run-1.json").exists():
            self.skipTest("campaign evidence not yet produced")
        for p in self.RUNS:
            self.assertTrue(p.exists(), p)

    def test_per_case_byte_envelope(self):
        if not self.RUNS[0].exists():
            self.skipTest("reference runs not yet produced")
        from issue195_v2_terminal_reduction import verify_run_record
        for p in self.RUNS:
            d = load(p)
            problems = []
            verify_run_record(d, p.name, problems)
            self.assertEqual(problems, [], f"{p.name}: {problems}")

    def test_request_bytes_deterministic_serialization(self):
        from issue195_v2_run_ladder import serialize_request
        if not self.RUNS[0].exists():
            self.skipTest("reference runs not yet produced")
        for p in self.RUNS:
            for r in load(p)["results"]:
                reqb = base64.b64decode(r["request_bytes_b64"])
                self.assertEqual(
                    reqb, serialize_request(r["prompt_token_ids"]),
                    f"{p.name}/{r['case_id']}: non-deterministic request")

    def test_no_forbidden_keys_in_requests(self):
        if not self.RUNS[0].exists():
            self.skipTest("reference runs not yet produced")
        for p in self.RUNS:
            for r in load(p)["results"]:
                body = json.loads(base64.b64decode(r["request_bytes_b64"]))
                for k in A.FORBIDDEN_REQUEST_KEYS:
                    self.assertNotIn(k, body)

    def test_prompt_ids_match_frozen_ladder(self):
        if not self.RUNS[0].exists():
            self.skipTest("reference runs not yet produced")
        ladder = load(REPO / A.FIXTURE_LADDER_PATH)
        want = {c["case_id"]: c["prompt_token_ids"] for c in ladder["cases"]}
        for p in self.RUNS:
            for r in load(p)["results"]:
                self.assertEqual(r["prompt_token_ids"],
                                 want[r["case_id"]])


class TestProspectiveReferenceFreeze(unittest.TestCase):
    def test_refreeze_pin_exists_and_binds(self):
        rf_path = V2_EV / "reference" / "REFREEZE.json"
        if not rf_path.exists():
            self.skipTest("reference not yet frozen")
        rf = load(rf_path)
        self.assertEqual(rf["campaign"], A.CAMPAIGN_ID)
        fr = V2_EV / "reference" / "frozen-reference.json"
        self.assertEqual(sha(fr), rf["frozen_reference_sha256"])
        # refreeze commit tree contains the pinned bytes
        show = subprocess.run(
            ["git", "-C", str(REPO), "show",
             f"{rf['refreeze_commit']}:" + A.R8D_V2_DIR
             + "/evidence/reference/frozen-reference.json"],
            capture_output=True, text=True)
        self.assertEqual(show.returncode, 0)
        self.assertEqual(hashlib.sha256(show.stdout.encode()).hexdigest(),
                         rf["frozen_reference_sha256"])

    def test_candidate_runs_record_freeze_identity(self):
        for i in (1, 2, 3):
            p = V2_EV / "candidate" / f"cand-run-{i}.json"
            if not p.exists():
                self.skipTest("candidate runs not yet produced")
            d = load(p)
            g = d.get("sampler_gate") or {}
            self.assertTrue(g.get("gate_passed"))
            self.assertEqual(len(g.get("refreeze_commit", "")), 40)
            self.assertTrue(d.get("git_clean"))

    def test_refreeze_commit_ancestor_of_candidate_heads(self):
        rf_path = V2_EV / "reference" / "REFREEZE.json"
        if not rf_path.exists():
            self.skipTest("reference not yet frozen")
        rf = load(rf_path)
        for i in (1, 2, 3):
            p = V2_EV / "candidate" / f"cand-run-{i}.json"
            if not p.exists():
                self.skipTest("candidate runs not yet produced")
            head = load(p)["git_head"]
            r = subprocess.run(
                ["git", "-C", str(REPO), "merge-base", "--is-ancestor",
                 rf["refreeze_commit"], head], capture_output=True)
            self.assertEqual(r.returncode, 0,
                             f"refreeze not ancestor of cand-run-{i} head")


class TestTerminalSemantics(unittest.TestCase):
    """BLOCKED-vs-FAIL semantics tests required by the correction."""

    def _sandbox(self):
        if not (V2_EV / "reference" / "ref-run-1.json").exists():
            self.skipTest("campaign evidence not yet produced")
        import tempfile
        tmp = tempfile.mkdtemp(prefix="i195v2-t-")
        sandbox_copy(tmp)
        return Path(tmp) / "docs/investigations/qwen38-flash-next-r8-d-v2", \
            Path(tmp)

    def _mutate_probe(self, area, variant, cls):
        p = area / "evidence/sampler-contract/sampler-probe-ref.json"
        d = load(p)
        d["variants"][variant]["classification"] = cls
        p.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")

    def test_pre_output_missing_sampler_contract_blocked(self):
        area, tmp = self._sandbox()
        try:
            self._mutate_probe(
                area, "canonical", "BLOCKED_NO_CHAIN_EVIDENCE")
            r = run_reducer(area)
            self.assertEqual(r["terminal"], A.TERMINAL_BLOCKED)
            self.assertFalse(r["checks"]["sampler_contract_proven_reference"])
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def _green_baseline(self, area):
        """Make the campaign PASS-shaped (candidate == frozen ref)."""
        fr = load(area / "evidence/reference/frozen-reference.json")
        for i in (1, 2, 3):
            p = area / f"evidence/candidate/cand-run-{i}.json"
            d = load(p)
            for r in d["results"]:
                fc = fr["cases"][r["case_id"]]
                resp = json.loads(base64.b64decode(r["response_bytes_b64"]))
                resp["tokens"] = fc["generated_tokens"]
                resp["stop_type"] = fc["stop_type"]
                resp["stopping_word"] = fc["stopping_word"]
                rb = json.dumps(resp, sort_keys=True,
                                separators=(",", ":")).encode()
                r["response_bytes_b64"] = base64.b64encode(rb).decode()
                r["response_sha256"] = hashlib.sha256(rb).hexdigest()
                r["parsed_from_retained_bytes"]["generated_tokens"] = \
                    fc["generated_tokens"]
                r["parsed_from_retained_bytes"]["stop_type"] = fc["stop_type"]
                r["parsed_from_retained_bytes"]["stopping_word"] = \
                    fc["stopping_word"]
            p.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")

    def _with_green(self, mutate):
        area, tmp = self._sandbox()
        try:
            self._green_baseline(area)
            base = run_reducer(area)
            # baseline must be PASS-shaped (all green) for the semantics
            # tests to be meaningful
            mutate(area)
            return base, run_reducer(area)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_token_mismatch_is_fail_not_blocked(self):
        def mutate(area):
            p = area / "evidence/candidate/cand-run-1.json"
            d = load(p)
            r = d["results"][0]
            resp = json.loads(base64.b64decode(r["response_bytes_b64"]))
            toks = list(resp["tokens"])
            toks[-1] += 1
            resp["tokens"] = toks
            rb = json.dumps(resp, sort_keys=True,
                            separators=(",", ":")).encode()
            r["response_bytes_b64"] = base64.b64encode(rb).decode()
            r["response_sha256"] = hashlib.sha256(rb).hexdigest()
            r["parsed_from_retained_bytes"]["generated_tokens"] = toks
            p.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")
        base, mut = self._with_green(mutate)
        self.assertEqual(base["terminal"], A.TERMINAL_PASS)
        self.assertEqual(mut["terminal"], A.TERMINAL_FAIL)
        self.assertFalse(mut["checks"]["all_cases_token_exact"])
        self.assertTrue(mut["valid"])

    def test_post_output_restart_failure_is_fail(self):
        def mutate(area):
            p = area / "evidence/candidate/restart-pid-proof.json"
            d = load(p)
            d["terminated_pids"][0]["confirmed_gone_before_relaunch"] = False
            p.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")
        base, mut = self._with_green(mutate)
        self.assertEqual(base["terminal"], A.TERMINAL_PASS)
        self.assertEqual(mut["terminal"], A.TERMINAL_FAIL)

    def test_post_output_sampler_reproof_failure_is_fail(self):
        def mutate(area):
            p = area / "evidence/candidate/sampler-probe-cand-restart.json"
            d = load(p)
            d["variants"]["canonical"]["classification"] = \
                "BLOCKED_NO_CHAIN_EVIDENCE"
            p.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")
        base, mut = self._with_green(mutate)
        self.assertEqual(base["terminal"], A.TERMINAL_PASS)
        self.assertEqual(mut["terminal"], A.TERMINAL_FAIL)

    def test_post_output_placement_failure_is_fail(self):
        def mutate(area):
            p = area / "evidence/candidate/cand-server.log"
            p.write_text(p.read_text().replace(
                "per_layer_token_embd", "PLE_REMOVED"))
        base, mut = self._with_green(mutate)
        self.assertEqual(base["terminal"], A.TERMINAL_PASS)
        self.assertEqual(mut["terminal"], A.TERMINAL_FAIL)

    def test_all_conditions_green_pass(self):
        area, tmp = self._sandbox()
        try:
            self._green_baseline(area)
            r = run_reducer(area)
            self.assertEqual(r["terminal"], A.TERMINAL_PASS)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_authored_pass_ignored(self):
        area, tmp = self._sandbox()
        try:
            (area / "terminal-reduction.json").write_text(json.dumps(
                {"terminal": A.TERMINAL_PASS, "authored": True}))
            r = run_reducer(area)
            self.assertNotEqual(r["terminal"], A.TERMINAL_PASS)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class TestNegativeControlsV2(unittest.TestCase):
    def test_all_controls_valid_and_differential(self):
        p = V2_EV / "negative-controls" / "negative-controls.json"
        if not p.exists():
            self.skipTest("negative controls not yet run")
        d = load(p)
        self.assertTrue(d["all_valid"])
        diff = [c for c in d["controls"] if c.get("differential")]
        self.assertGreaterEqual(len(d["controls"]), 17)
        self.assertGreaterEqual(len(diff), 15)
        for c in diff:
            self.assertNotIn(c, [None])


class TestManifestV2(unittest.TestCase):
    def test_manifest_covers_all_v2_evidence(self):
        m = V2_AREA / "MANIFEST.sha256"
        if not m.exists():
            self.skipTest("manifest not yet built")
        listed = set()
        for line in m.read_text().splitlines():
            if line.strip():
                h, p = line.split(None, 1)
                p = p.lstrip("*")
                listed.add(p)
                self.assertEqual(sha(REPO / p), h, f"row drift: {p}")
        ondisk = {str(p.relative_to(REPO)) for p in V2_AREA.rglob("*")
                  if p.is_file() and p.name not in
                  ("MANIFEST.sha256", "producer-hashes.json")}
        self.assertEqual(listed, ondisk, f"delta: {listed ^ ondisk}")

    def test_reducer_check_mode_green(self):
        if not (V2_AREA / "terminal-reduction.json").exists():
            self.skipTest("terminal reduction not yet run")
        r = subprocess.run(
            [sys.executable, str(REPO / "scripts"
                                 / "issue195_v2_terminal_reduction.py"),
             "--check"], capture_output=True, text=True, cwd=REPO)
        self.assertIn("CHECK OK", r.stdout, r.stderr)


class TestTerminalReductionV2(unittest.TestCase):
    def test_terminal_is_machine_derived_and_expected(self):
        p = V2_AREA / "terminal-reduction.json"
        if not p.exists():
            self.skipTest("terminal reduction not yet run")
        d = load(p)
        self.assertIn(d["terminal"], (A.TERMINAL_PASS, A.TERMINAL_FAIL,
                                      A.TERMINAL_BLOCKED))
        self.assertEqual(d["campaign"], A.CAMPAIGN_ID)
        live = run_reducer()
        self.assertEqual(live["terminal"], d["terminal"],
                         "authored terminal drifted from live derivation")


if __name__ == "__main__":
    unittest.main()
