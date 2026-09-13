"""Issue #158 additive V1-B bundle-manifest tests."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v1b_manifest  # noqa: E402


class V1BManifestTests(unittest.TestCase):
    def test_committed_bundle_has_exact_inventory(self):
        v1b_manifest.check()

    def test_unexpected_bundle_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for relative in v1b_manifest.required_paths():
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((ROOT / relative).read_bytes())
            manifest = root / v1b_manifest.MANIFEST
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_bytes(v1b_manifest.render(root))
            (root / v1b_manifest.BUNDLE / "unexpected.txt").write_text("drift")
            with self.assertRaises(v1b_manifest.ManifestError):
                v1b_manifest.check(root)

    def test_tampered_evidence_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for relative in v1b_manifest.required_paths():
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((ROOT / relative).read_bytes())
            manifest = root / v1b_manifest.MANIFEST
            manifest.write_bytes(v1b_manifest.render(root))
            target = root / v1b_manifest.BUNDLE / "PHYSICAL-AUTHORITY.json"
            target.write_text(target.read_text() + " ")
            with self.assertRaises(v1b_manifest.ManifestError):
                v1b_manifest.check(root)


if __name__ == "__main__":
    unittest.main()
