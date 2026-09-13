"""Issue #161 additive V1-C bundle-manifest tests."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v1c_manifest  # noqa: E402


def _materialize_current_bundle(root: Path) -> None:
    """Copy the committed bundle state and a matching manifest into root."""
    for relative in v1c_manifest.required_paths():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    manifest = root / v1c_manifest.MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_bytes(v1c_manifest.render(root))


class V1CManifestTests(unittest.TestCase):
    def test_committed_bundle_has_exact_inventory(self):
        # The manifest must be current for whichever campaign rung the
        # committed bundle is in (Phase-0 namespace, regression proof,
        # prospective authority, or the terminal evidence inventory).
        v1c_manifest.check()

    def test_unexpected_bundle_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _materialize_current_bundle(root)
            (root / v1c_manifest.BUNDLE / "unexpected.txt").write_text("drift")
            with self.assertRaises(v1c_manifest.ManifestError):
                v1c_manifest.check(root)

    def test_tampered_evidence_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _materialize_current_bundle(root)
            target = root / v1c_manifest.BUNDLE / "README.md"
            target.write_text(target.read_text() + " ")
            with self.assertRaises(v1c_manifest.ManifestError):
                v1c_manifest.check(root)

    def test_inventory_ladder_only_grows_to_terminal(self):
        # Every rung is a subset of the next and of the terminal
        # inventory: the bundle only ever grows toward the terminal
        # state, and the terminal state contains the Phase-0 namespace.
        ladder = v1c_manifest.EVIDENCE_LADDER
        for smaller, larger in zip(ladder, ladder[1:]):
            self.assertLess(smaller, larger)
        self.assertIn("README.md", ladder[0])
        self.assertEqual(ladder[-1], v1c_manifest.EVIDENCE_TERMINAL)

    def test_manifest_pins_accepted_predecessor_sources(self):
        # The successor campaign must pin the accepted predecessor
        # sources so any drift in them fails this bundle's check.
        required = v1c_manifest.required_paths()
        for source in ("scripts/v1a_execution_participant.py", "scripts/v1a_vulkan_adapter.py",
                       "scripts/v1a_runner.py", "scripts/v0c_canonical_run.py", "scripts/v0c_correctness.py"):
            self.assertIn(source, required)


if __name__ == "__main__":
    unittest.main()
