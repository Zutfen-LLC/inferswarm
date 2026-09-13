"""Issue #163 CPU-only contract tests for the V2-A evidence manifest."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v2a_manifest as manifest  # noqa: E402

CONTRACT = ROOT / "docs/investigations/vulkan-v2-a/manifest-contract.json"


def write_contract(temp: str, ladder: list) -> Path:
    contract = {
        "bundle": "bundle-under-test",
        "ladder": ladder,
        "sources": ["sources/one.py"],
        "tests": ["tests/test_one.py"],
    }
    root = Path(temp)
    (root / "sources").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "sources/one.py").write_text("one = 1\n")
    (root / "tests/test_one.py").write_text("def test_one():\n    assert True\n")
    (root / "bundle-under-test").mkdir(parents=True, exist_ok=True)
    path = root / "contract.json"
    path.write_text(json.dumps(contract))
    return path


class ManifestContractTests(unittest.TestCase):
    def test_repository_contract_ladder_is_increasing_and_registered(self):
        contract = manifest.load_contract(CONTRACT)
        rungs = [sorted(r["evidence"]) for r in contract["ladder"]]
        for earlier, later in zip(rungs, rungs[1:]):
            self.assertTrue(set(earlier) < set(later))
        self.assertIn("README.md", rungs[0])
        terminal = rungs[-1]
        for required in ("PORTABILITY-AUDIT.json", "FINAL-TERMINAL.json", "STATUS.json",
                         "evidence/v2a-amd-a-canonical-01/execution-receipt.json",
                         "evidence/v2a-nv-a-canonical-01/execution-receipt.json"):
            self.assertIn(required, terminal)

    def test_current_namespace_matches_a_ladder_rung(self):
        contract = manifest.load_contract(CONTRACT)
        # The repository bundle must sit exactly on one ladder rung at
        # all times (currently: README + retained replays).
        actual = manifest.current_inventory(ROOT / contract["bundle"])
        rungs = [frozenset(r["evidence"]) for r in contract["ladder"]]
        self.assertIn(actual, rungs)

    def test_missing_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            contract_path = write_contract(temp, [
                {"state": "a", "evidence": ["README.md", "EXTRA.json"]},
            ])
            contract = manifest.load_contract(contract_path)
            (Path(temp) / "bundle-under-test/README.md").write_text("readme\n")
            with self.assertRaises(manifest.ManifestError) as ctx:
                manifest.required_paths(contract, root=Path(temp))
            self.assertIn("EXTRA.json", str(ctx.exception))

    def test_unexpected_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            contract_path = write_contract(temp, [
                {"state": "a", "evidence": ["README.md"]},
            ])
            contract = manifest.load_contract(contract_path)
            (Path(temp) / "bundle-under-test/README.md").write_text("readme\n")
            (Path(temp) / "bundle-under-test/SNEAKY.json").write_text("{}\n")
            with self.assertRaises(manifest.ManifestError) as ctx:
                manifest.required_paths(contract, root=Path(temp))
            self.assertIn("SNEAKY.json", str(ctx.exception))

    def test_intermediate_state_not_on_ladder_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            contract_path = write_contract(temp, [
                {"state": "a", "evidence": ["README.md"]},
                {"state": "b", "evidence": ["README.md", "A.json", "B.json"]},
            ])
            contract = manifest.load_contract(contract_path)
            bundle = Path(temp) / "bundle-under-test"
            (bundle / "README.md").write_text("r\n")
            (bundle / "A.json").write_text("{}\n")  # B.json missing: incomplete
            with self.assertRaises(manifest.ManifestError):
                manifest.required_paths(contract, root=Path(temp))

    def test_write_then_check_roundtrip_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            contract_path = write_contract(temp, [
                {"state": "a", "evidence": ["README.md"]},
            ])
            contract = manifest.load_contract(contract_path)
            bundle = Path(temp) / "bundle-under-test"
            (bundle / "README.md").write_text("readme\n")
            (bundle / "MANIFEST.sha256").write_bytes(manifest.render(contract, root=Path(temp)))
            manifest.check(contract, root=Path(temp))
            # source drift -> manifest drift
            (Path(temp) / "sources/one.py").write_text("one = 2\n")
            with self.assertRaises(manifest.ManifestError):
                manifest.check(contract, root=Path(temp))
            (Path(temp) / "sources/one.py").write_text("one = 1\n")
            manifest.check(contract, root=Path(temp))
            # evidence drift -> manifest drift
            (bundle / "README.md").write_text("changed\n")
            with self.assertRaises(manifest.ManifestError):
                manifest.check(contract, root=Path(temp))

    def test_flat_ladder_rung_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            contract_path = write_contract(temp, [
                {"state": "a", "evidence": ["README.md"]},
                {"state": "b", "evidence": ["README.md"]},
            ])
            with self.assertRaises(manifest.ManifestError):
                manifest.load_contract(contract_path)


if __name__ == "__main__":
    unittest.main()
