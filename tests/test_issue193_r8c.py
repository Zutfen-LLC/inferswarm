"""Issue #193 (R8-C) retention tests: authority, evidence bundle, terminal
reduction fail-closed behavior, and negative controls."""
import json
import os
import sys
import unittest
from pathlib import Path

from scripts import issue193_r8c_authority as auth

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
R8C = os.path.join(ROOT, "docs", "investigations", "qwen38-flash-next-r8-c")
R8B = os.path.join(ROOT, "docs", "investigations", "qwen38-flash-next-r8-b")


def jload(p):
    with open(p) as fh:
        return json.load(fh)


class TestAuthorityFreeze(unittest.TestCase):
    def test_predecessor_identity(self):
        self.assertEqual(auth.R8B_MERGE_SHA, "3448cc7d63853079fff2520952c2b65d586ae3e4")
        self.assertEqual(auth.R8B_TERMINAL, "R8B_QWEN38_NVIDIA_RPC_RUNTIME_QUALIFICATION_FAIL")

    def test_accepted_case256_streams_pinned(self):
        self.assertEqual(auth.R8B_CASE256_REFERENCE_TOKENS[:3], [561, 40554, 32039])
        self.assertEqual(auth.R8B_CASE256_CANDIDATE_TOKENS[:3], [561, 40554, 32039])
        self.assertNotEqual(auth.R8B_CASE256_REFERENCE_TOKENS,
                            auth.R8B_CASE256_CANDIDATE_TOKENS)

    def test_r8b_bundle_byte_preserved(self):
        r = auth.verify_r8b_bundle_unchanged(ROOT)
        self.assertTrue(r["ok"], r["problems"])
        self.assertGreater(r["checked"], 0)

    def test_experiment_matrix_frozen_fields(self):
        m = auth.EXPERIMENT_MATRIX
        for key in ("phase1_reproduction", "wedge_A_direct_vs_loopback_rpc",
                    "wedge_B_local_vs_remote_rpc", "wedge_C_full_topology",
                    "phase3_teacher_forced_logprob_capture"):
            self.assertIn(key, m)
        self.assertEqual(m["sentinel"], "case-256")
        # frozen descriptive buckets present and untouched
        b = m["phase3_teacher_forced_logprob_capture"]["frozen_buckets"]
        self.assertEqual(b, {"near_tie_lt": 0.10, "moderate_le": 1.0})

    def test_terminals_complete(self):
        self.assertEqual(len(auth.TERMINALS), 4)
        self.assertIn("R8C_QWEN38_RPC_DIVERGENCE_CAUSE_LOCALIZED", auth.TERMINALS)


class TestEvidenceBundle(unittest.TestCase):
    def test_host_inventory_raw_retained(self):
        d = os.path.join(R8C, "evidence", "host-inventory")
        for h in ("inferswarm01", "inferswarm03", "inferswarm04"):
            for suf in ("inventory-raw.txt", "nvidia-smi-q.xml"):
                self.assertTrue(os.path.exists(os.path.join(d, f"{h}-{suf}")), h + suf)

    def test_split_rehash_matches_accepted(self):
        d = jload(os.path.join(R8C, "evidence", "split-identity-r8c", "split-rehash.json"))
        self.assertTrue(d["all_ok"])
        for m in d["members"]:
            self.assertTrue(m["matches_accepted_pin"])

    def test_phase1_reproduction_derived(self):
        d = jload(os.path.join(R8C, "phase1-reproduction.json"))
        self.assertTrue(d["reproduced"])
        self.assertTrue(all(c["ok"] for c in d["checks"]))

    def test_wedge_evidence_pairs(self):
        ev = os.path.join(R8C, "evidence", "phase2-wedges")
        for f in ("wedge-A1-run1.json", "wedge-A1-run2.json",
                  "wedge-A2-run1.json", "wedge-A2-run2.json",
                  "wedge-B2-run1.json", "wedge-B2-run2.json"):
            self.assertTrue(os.path.exists(os.path.join(ev, f)), f)

    def test_accepted_log_carries_chain_evidence(self):
        log = open(os.path.join(R8B, "evidence", "reference", "reference-server.log"),
                   errors="replace").read()
        self.assertIn("unable to match sampler by name 'greedy'", log)
        self.assertIn("sampler chain: logits -> dist", log)

    def test_intervention_records_exist_and_single_factor(self):
        for arm in ("R", "C"):
            d = jload(os.path.join(R8C, "evidence", "phase5-intervention", f"iv-{arm}.json"))
            self.assertEqual(d["samplers"], ["top_k"])
            self.assertEqual(d["top_k"], 1)
            self.assertEqual(d["schema"], "inferswarm.issue193.intervention-run/1")

    def test_manifest_covers_evidence_tree(self):
        man = os.path.join(R8C, "MANIFEST.sha256")
        self.assertTrue(os.path.exists(man))
        listed = set()
        with open(man) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                digest, rel = line.split(None, 1)
                rel = rel.strip()
                if rel.endswith("MANIFEST.sha256"):
                    continue
                listed.add(rel)
                p = os.path.join(ROOT, rel)
                self.assertTrue(os.path.exists(p), rel)
                import hashlib
                h = hashlib.sha256(open(p, "rb").read()).hexdigest()
                self.assertEqual(h, digest, rel)
        # every retained evidence file is listed
        for dirpath, _dirs, files in os.walk(R8C):
            for f in files:
                rel = os.path.relpath(os.path.join(dirpath, f), ROOT)
                if f == "MANIFEST.sha256":
                    continue
                self.assertIn(rel, listed, rel)


class TestTerminalReduction(unittest.TestCase):
    def test_terminal_derived(self):
        d = jload(os.path.join(R8C, "terminal-reduction.json"))
        self.assertEqual(d["terminal"], "R8C_QWEN38_RPC_DIVERGENCE_CAUSE_LOCALIZED")
        self.assertTrue(all(c["ok"] for c in d["checks"]))
        self.assertGreaterEqual(len(d["checks"]), 12)

    def test_non_claims_preserved(self):
        d = jload(os.path.join(R8C, "terminal-reduction.json"))
        self.assertTrue(any("requalification" in n for n in d["non_claims"]))

    def test_r8b_historical_not_reinterpreted(self):
        d = jload(os.path.join(R8C, "terminal-reduction.json"))
        self.assertIn("NOT reinterpreted as PASS", d["classification"])


class TestNegativeControls(unittest.TestCase):
    """Fail-closed behavior of the reducers against mutated evidence."""

    def setUp(self):
        import tempfile
        import shutil
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def _run_phase1_reducer_on(self, mutate_fn):
        """Run the REAL phase-1 reducer against a mutated copy of the evidence
        tree; return (rc, stdout). Mutations copy the tree to tmp first."""
        import shutil
        import subprocess
        tree = os.path.join(self.tmp, "ev")
        shutil.copytree(os.path.join(R8C, "evidence", "phase1-reproduction"), tree)
        mutate_fn(tree)
        # the reducer resolves EV relative to its own file; patch via env-free
        # approach: run a small driver importing the reducer with monkeypatched EV
        driver = os.path.join(self.tmp, "drv.py")
        with open(driver, "w") as fh:
            fh.write(
                "import importlib.util, os, sys\n"
                f"spec = importlib.util.spec_from_file_location('p1r', {os.path.join(ROOT, 'scripts', 'issue193_phase1_reduction.py')!r})\n"
                "m = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(m)\n"
                f"m.EV = {tree!r}\n"
                "sys.exit(0 if m.main() else 1)\n")  # main() exits itself; defensive
        r = subprocess.run([sys.executable, driver],
                           capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def test_phase1_reducer_fails_on_mutated_tokens(self):
        def mutate(tree):
            p = os.path.join(tree, "r8c-R-run1.json")
            d = jload(p)
            d["results"][0]["generated_tokens"][3] += 1
            json.dump(d, open(p, "w"))
        rc, out = self._run_phase1_reducer_on(mutate)
        self.assertNotEqual(rc, 0, out)

    def test_phase1_reducer_fails_on_removed_run(self):
        def mutate(tree):
            os.remove(os.path.join(tree, "r8c-R-run2.json"))
        rc, out = self._run_phase1_reducer_on(mutate)
        self.assertNotEqual(rc, 0, out)

    def test_terminal_reducer_runs_green_on_retained_bytes(self):
        import subprocess
        r = subprocess.run(
            [sys.executable,
             os.path.join(ROOT, "scripts", "issue193_terminal_reduction.py")],
            capture_output=True, text=True, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("R8C_QWEN38_RPC_DIVERGENCE_CAUSE_LOCALIZED", r.stdout)

    def test_reducers_use_the_bootstrap_selected_interpreter(self):
        """Detached suite workers intentionally do not contain ``.venv``."""
        source = Path(__file__).read_text(encoding="utf-8")
        forbidden = 'os.path.join(ROOT, ".venv", "bin", ' + '"python")'
        self.assertNotIn(forbidden, source)
        self.assertIn("subprocess.run([sys.executable, " + "driver]", source)
        self.assertIn("[sys.executable,\n             " +
                      'os.path.join(ROOT, "scripts",', source)

    def test_sampler_chain_finding_requires_accepted_log(self):
        # the finding is bound to RETAINED accepted bytes, not rerun claims:
        log = open(os.path.join(R8B, "evidence", "reference", "reference-server.log"),
                   errors="replace").read()
        self.assertGreaterEqual(log.count("unable to match sampler by name 'greedy'"), 12)
        self.assertGreaterEqual(log.count("sampler chain: logits -> dist"), 2)


if __name__ == "__main__":
    unittest.main()
