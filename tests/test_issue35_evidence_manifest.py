"""Evidence-manifest lifecycle tests for the Issue #35 namespace.

The manifest generator is the ACCEPTED generalized V2-A generator
(``scripts/v2a_manifest.py``), imported not forked, driven by the
namespace's own inventory contract. These tests pin:

* the contract itself is a valid ladder (strictly increasing rungs,
  sources and tests listed);
* every pinned source/test matches its recorded digest at the current
  ladder rung (delegate to the generator's own ``check``);
* negative controls: tampering with a rung file, an unexpected extra
  file, and a removed file each fail closed.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v2a_manifest as generator  # noqa: E402

BUNDLE = "docs/investigations/link-x1-envelope"
CONTRACT = ROOT / BUNDLE / "manifest-contract.json"


class Issue35ManifestTests(unittest.TestCase):
    def setUp(self):
        if not CONTRACT.is_file():
            self.skipTest("manifest contract not yet committed")
        self.contract = generator.load_contract(CONTRACT)

    def test_contract_ladder_is_strictly_increasing(self):
        rungs = [sorted(r["evidence"]) for r in self.contract["ladder"]]
        for earlier, later in zip(rungs, rungs[1:]):
            self.assertLess(set(earlier), set(later))

    def test_manifest_check_passes_at_current_rung(self):
        # Delegate to the accepted generator: verifies the on-disk bundle
        # equals exactly one ladder rung and every digest matches.
        generator.check(self.contract, ROOT)

    def test_declared_sources_and_tests_exist(self):
        for relative in [*self.contract["sources"], *self.contract["tests"]]:
            self.assertTrue((ROOT / relative).is_file(),
                            f"pinned path missing: {relative}")

    def test_manifest_file_exists_and_is_canonical(self):
        manifest = ROOT / BUNDLE / "MANIFEST.sha256"
        self.assertTrue(manifest.is_file())
        self.assertEqual(manifest.read_bytes(),
                         generator.render(self.contract, ROOT))


class Issue35ManifestNegativeControls(unittest.TestCase):
    """Fail-closed controls against a copied repository tree."""

    def _copy_tree(self, tmp: Path) -> Path:
        bundle_files = [CONTRACT, ROOT / BUNDLE / "MANIFEST.sha256"]
        for rung in json.loads(CONTRACT.read_text())["ladder"]:
            for rel in rung["evidence"]:
                src = ROOT / BUNDLE / rel
                if src.is_file():
                    bundle_files.append(src)
        for key in ("sources", "tests"):
            for rel in json.loads(CONTRACT.read_text())[key]:
                f = ROOT / rel
                if f.is_file():
                    bundle_files.append(f)
        for f in bundle_files:
            dest = tmp / f.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
        return tmp

    def test_tampered_evidence_file_fails(self):
        contract = json.loads(CONTRACT.read_text())
        evidence = contract["ladder"][-1]["evidence"]
        with tempfile.TemporaryDirectory() as tmp:
            root = self._copy_tree(Path(tmp))
            target = root / BUNDLE / sorted(evidence)[0]
            if not target.is_file():
                self.skipTest("terminal rung not yet reached")
            target.write_bytes(target.read_bytes() + b"x")
            with self.assertRaises(generator.ManifestError):
                generator.check(generator.load_contract(CONTRACT), root)

    def test_unexpected_extra_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._copy_tree(Path(tmp))
            extra = root / BUNDLE / "evidence" / "EXTRA-UNEXPECTED.json"
            extra.parent.mkdir(parents=True, exist_ok=True)
            extra.write_text("{}\n")
            with self.assertRaises(generator.ManifestError):
                generator.check(generator.load_contract(CONTRACT), root)

    def test_missing_manifest_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._copy_tree(Path(tmp))
            (root / BUNDLE / "MANIFEST.sha256").unlink()
            with self.assertRaises(generator.ManifestError):
                generator.check(generator.load_contract(CONTRACT), root)


if __name__ == "__main__":
    unittest.main()
