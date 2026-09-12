"""Issue #143 V0-C bundle-local evidence-manifest tests (CPU-only)."""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v0c_manifest  # noqa: E402


class V0CEvidenceManifestTests(unittest.TestCase):
    def copy_inputs(self, root: Path, *, include_manifest: bool = True) -> None:
        for relative in v0c_manifest.required_paths():
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        if include_manifest:
            manifest = root / v0c_manifest.MANIFEST
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_bytes(v0c_manifest.render(root))

    def test_committed_manifest_is_complete_and_current(self):
        v0c_manifest.check(ROOT)
        entries = v0c_manifest.parse(
            (ROOT / v0c_manifest.MANIFEST).read_bytes()
        )
        self.assertEqual(set(entries), set(v0c_manifest.expected_entries(ROOT)))
        self.assertNotIn(v0c_manifest.MANIFEST.as_posix(), entries)
        self.assertIn("docs/investigations/vulkan-v0-c/METHODOLOGY.md", entries)
        self.assertIn(
            "docs/investigations/vulkan-v0-c/FINAL-TERMINAL.md", entries,
        )
        self.assertIn(
            "docs/investigations/vulkan-v0-c/raw/v0c-amd-a-01/stderr.txt",
            entries,
        )
        self.assertEqual(set(v0c_manifest.SOURCES), {
            "scripts/v0c_canonical_run.py",
            "scripts/v0c_execution_seam.py",
            "scripts/v0c_manifest.py",
            "scripts/v0c_vulkan_adapter.py",
        })
        self.assertEqual(set(v0c_manifest.TESTS), {
            "tests/test_v0c_canonical_run.py",
            "tests/test_v0c_evidence_manifest.py",
            "tests/test_v0c_execution_seam.py",
            "tests/test_v0c_vulkan_adapter.py",
        })
        self.assertTrue(set(v0c_manifest.SOURCES | v0c_manifest.TESTS) <= set(entries))

    def test_rejects_missing_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_inputs(root, include_manifest=False)
            with self.assertRaisesRegex(v0c_manifest.ManifestError, "manifest missing"):
                v0c_manifest.check(root)

    def test_rejects_drifted_retained_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_inputs(root)
            raw = root / "docs/investigations/vulkan-v0-c/raw/v0c-amd-a-01/stderr.txt"
            raw.write_bytes(raw.read_bytes() + b"mutation\n")
            with self.assertRaisesRegex(v0c_manifest.ManifestError, "manifest drift"):
                v0c_manifest.check(root)

    def test_rejects_unexpected_bundle_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_inputs(root)
            rogue = root / v0c_manifest.BUNDLE / "unreviewed-observation.txt"
            rogue.write_text("unexpected\n", encoding="utf-8")
            with self.assertRaisesRegex(v0c_manifest.ManifestError, "unexpected"):
                v0c_manifest.check(root)

    def test_rejects_incomplete_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_inputs(root)
            manifest = root / v0c_manifest.MANIFEST
            lines = manifest.read_text(encoding="utf-8").splitlines(keepends=True)
            manifest.write_text("".join(lines[1:]), encoding="utf-8")
            with self.assertRaisesRegex(v0c_manifest.ManifestError, "incomplete"):
                v0c_manifest.check(root)

    def test_rejects_missing_required_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_inputs(root)
            (root / "scripts/v0c_vulkan_adapter.py").unlink()
            with self.assertRaisesRegex(v0c_manifest.ManifestError, "input missing"):
                v0c_manifest.check(root)


if __name__ == "__main__":
    unittest.main()
