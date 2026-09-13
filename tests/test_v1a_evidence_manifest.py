"""Issue #154 additive V1-A bundle-manifest tests."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v1a_manifest  # noqa: E402


class V1AManifestTests(unittest.TestCase):
    def test_committed_bundle_has_exact_inventory(self):
        v1a_manifest.check()

    def test_unexpected_bundle_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for relative in v1a_manifest.required_paths():
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((ROOT / relative).read_bytes())
            manifest = root / v1a_manifest.MANIFEST
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_bytes(v1a_manifest.render(root))
            (root / v1a_manifest.BUNDLE / "unexpected.txt").write_text("drift")
            with self.assertRaises(v1a_manifest.ManifestError):
                v1a_manifest.check(root)


if __name__ == "__main__":
    unittest.main()
