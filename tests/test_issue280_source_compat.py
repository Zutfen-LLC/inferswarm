"""Successor source identity, executable inserted D1 metadata, and gate drift."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "docs/investigations/vulkan-same-request-280/compatibility"

def load(name):
    path = ROOT / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

class SuccessorSourceTests(unittest.TestCase):
    def successor(self):
        path = ROOT / "scripts/issue280_source_compat.py"
        self.assertTrue(path.exists(), "successor transform absent")
        return load("issue280_source_compat")

    def test_additive_successor_preserves_other_five_files(self):
        m = self.successor()
        old = load("issue280_source")
        originals = {p: (BUNDLE / "source-semantics" / p).read_bytes() for p in old.SOURCE_HASHES}
        prior, _ = old.transform(originals)
        new, identity = m.transform(originals)
        for path in prior:
            if path != "src/llama-context.cpp":
                self.assertEqual(new[path], prior[path])
        self.assertIn('n_seqs_unq', new["src/llama-context.cpp"].decode())
        self.assertEqual(identity["predecessor_transformed_sha256"]["src/llama-context.cpp"],
                         hashlib.sha256(prior["src/llama-context.cpp"]).hexdigest())

    def test_bundle_manifest_emitter_is_deterministic_and_terminal(self):
        import subprocess
        import sys
        tool = BUNDLE / "manifest.py"
        self.assertTrue(tool.is_file(), "bundle-local manifest emitter missing")
        first = subprocess.check_output([sys.executable, str(tool)], cwd=ROOT)
        second = subprocess.check_output([sys.executable, str(tool)], cwd=ROOT)
        self.assertEqual(first, second)
        rows = [line.split("  ", 1) for line in first.decode().splitlines()]
        self.assertTrue(rows)
        for digest, relative in rows:
            self.assertNotIn("__pycache__", relative)
            self.assertFalse(relative.endswith("/MANIFEST.sha256"))
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), digest)
        self.assertIn("scripts/issue280_observer.py", [p for _, p in rows])
        self.assertIn(str((BUNDLE / "observer-R1-cold.i280.raw.gz").relative_to(ROOT)),
                      [p for _, p in rows])

    def test_inserted_cpu_probe_executes_complete_ids(self):
        m = self.successor()
        v = m.cpu_probe()
        self.assertTrue(v["ok"], v)
        self.assertEqual(v["rows"][0]["seq_ids_unq"], [0])
        self.assertEqual(v["rows"][0]["sequences"], 31)
        self.assertEqual(v["rows"][1]["seq_ids_unq"], [0, 1])
        self.assertEqual(v["rows"][2]["seq_ids_unq"], [7])

    def test_unpinned_transform_rejected(self):
        m = self.successor()
        with self.assertRaisesRegex(ValueError, "pinned source identity"):
            m.transform({})

    def test_full_tree_identity_drift_rejected(self):
        m = self.successor()
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            import shutil
            shutil.copytree(BUNDLE / "instrumentation", td / "overlay")
            identity = td / "overlay/source-identity.json"
            data = json.loads(identity.read_text())
            data["full_transformed_git_tree"] = "0" * 40
            identity.write_text(json.dumps(data))
            m.OVERLAY = td / "overlay"
            self.assertFalse(m.cpu_probe()["ok"])

class PermanentGateTests(unittest.TestCase):
    def gate(self):
        self.assertTrue((ROOT / "scripts/issue280_compatibility.py").exists(), "permanent compatibility gate absent")
        return load("issue280_compatibility")

    def test_bound_fixture_and_source_probe_pass(self):
        v = self.gate().check_compatibility()
        self.assertTrue(v["ok"], v)
        self.assertTrue(v["source_probe"]["ok"])
        self.assertEqual(v["replay"]["graph_count"], 40)

    def test_broken_producer_module_is_structured_false(self):
        m = self.gate()
        original = m.load_script
        def broken(name):
            if name == "issue280_source_compat":
                raise SyntaxError("producer syntax drift")
            return original(name)
        m.load_script = broken
        try:
            result = m.check_compatibility()
        except SyntaxError:
            self.fail("producer drift escaped instead of returning fail-closed verdict")
        self.assertFalse(result["ok"])
        self.assertIn("producer syntax drift", result["problems"][0])

    def test_missing_or_drifted_fixture_provenance_fail(self):
        m = self.gate()
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            self.assertFalse(m.check_compatibility(td)["ok"])
            for p in BUNDLE.iterdir():
                if p.is_file():
                    (td / p.name).write_bytes(p.read_bytes())
            p = td / "observer-R1-cold.i280.raw.gz"
            p.write_bytes(gzip.compress(b"drift", mtime=0))
            self.assertFalse(m.check_compatibility(td)["ok"])

    def test_model_or_producer_drift_fail_without_cached_result(self):
        m = self.gate()
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            for p in BUNDLE.iterdir():
                if p.is_file():
                    (td / p.name).write_bytes(p.read_bytes())
            terminal = td / "TERMINAL.json"
            data = json.loads(terminal.read_text())
            for category, field in (("model", "sha256"), ("build", "source_pin")):
                altered = json.loads(json.dumps(data))
                altered[category][field] = "drift"
                terminal.write_text(json.dumps(altered))
                self.assertFalse(m.check_compatibility(td)["ok"])
                terminal.write_text(json.dumps(data))

if __name__ == "__main__":
    unittest.main()
