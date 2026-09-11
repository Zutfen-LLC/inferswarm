"""Repository-wide evidence-manifest lifecycle regressions (CPU-only)."""
from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue117_proof  # noqa: E402
import issue137_manifest  # noqa: E402
import issue137_phase1_inventory  # noqa: E402
import sync_project_status  # noqa: E402


FORBIDDEN_LIVING_PATHS = {
    ".github/workflows/ci.yml",
    "ARCHITECTURE.md",
    "README.md",
    "ROADMAP.md",
    "docs/implementation/README.md",
    "docs/integrations/freetoken.md",
    "docs/project-status.json",
    "docs/protocols/README.md",
}

LEGACY_SNAPSHOT_ROWS = {
    "docs/qualification/gemma4-12b-it-v1/MANIFEST.sha256": {
        ".github/workflows/ci.yml", "ARCHITECTURE.md", "ROADMAP.md",
        "docs/protocols/README.md", "tests/test_issue74_methodology.py",
    },
    "docs/implementation/plan-driven-artifact-acquisition-99/"
    "evidence/MANIFEST.sha256": {
        ".github/workflows/ci.yml", "ARCHITECTURE.md", "ROADMAP.md",
        "docs/implementation/README.md", "tests/test_issue99_proof.py",
    },
    "docs/implementation/plan-driven-artifact-orchestration-101/"
    "evidence/MANIFEST.sha256": {
        ".github/workflows/ci.yml", "tests/test_issue101_proof.py"},
    "docs/implementation/artifact-locality-transition-planning-103/"
    "evidence/MANIFEST.sha256": {
        ".github/workflows/ci.yml", "tests/test_issue103_planner.py"},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class EvidenceManifestLifecycleTests(unittest.TestCase):
    def copy_issue137_manifest_inputs(self, root):
        relative_paths = {
            *(str(issue137_manifest.BUNDLE / name)
              for name in issue137_manifest.EVIDENCE_FILES),
            *issue137_manifest.PRODUCERS,
        }
        for relative in relative_paths:
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        manifest = root / issue137_manifest.MANIFEST
        manifest.write_bytes(issue137_manifest.render(root))

    def test_manifests_are_current_outside_frozen_legacy_snapshots(self):
        manifests = sorted((ROOT / "docs").rglob("MANIFEST.sha256"))
        self.assertGreaterEqual(len(manifests), 9)
        for manifest in manifests:
            manifest_relative = manifest.relative_to(ROOT).as_posix()
            legacy_rows = LEGACY_SNAPSHOT_ROWS.get(manifest_relative, set())
            listed = set()
            for line in manifest.read_text().splitlines():
                digest, separator, relative = line.partition("  ")
                self.assertEqual(separator, "  ", manifest)
                self.assertEqual(len(digest), 64, manifest)
                self.assertNotIn(relative, listed, manifest)
                self.assertNotEqual(ROOT / relative, manifest, manifest)
                target = ROOT / relative
                self.assertTrue(target.is_file(), relative)
                if relative not in legacy_rows:
                    self.assertNotIn(relative, FORBIDDEN_LIVING_PATHS,
                                     manifest)
                    self.assertEqual(sha256(target), digest, relative)
                listed.add(relative)
            self.assertLessEqual(legacy_rows, listed)
            self.assertEqual(
                listed & FORBIDDEN_LIVING_PATHS,
                legacy_rows & FORBIDDEN_LIVING_PATHS)

    def test_status_synchronization_has_no_manifest_side_effect(self):
        source = (ROOT / "scripts" / "sync_project_status.py").read_text()
        self.assertNotIn("MANIFEST.sha256", source)
        self.assertFalse(
            any("MANIFEST" in path for path in sync_project_status.TARGETS))

    def test_issue117_parent_is_closed_to_later_slices(self):
        prefix = "arm-c-regime4-diagnosis-137/"
        self.assertFalse(
            any(path.startswith(prefix)
                for path in issue117_proof.COMMITTED_EVIDENCE_FILES))
        parent = ROOT / issue117_proof.AREA / "evidence" / "MANIFEST.sha256"
        self.assertFalse(any(
            line.split("  ", 1)[1].startswith(
                str(issue117_proof.AREA / "evidence" / prefix))
            for line in parent.read_text().splitlines()
        ))

    def test_issue137_bundle_manifest_is_acyclic_and_complete(self):
        issue137_manifest.check(ROOT)
        entries = issue137_manifest.parse(
            (ROOT / issue137_manifest.MANIFEST).read_bytes())
        self.assertNotIn(str(issue137_manifest.MANIFEST), entries)
        self.assertEqual(
            set(entries), set(issue137_manifest.expected_entries(ROOT)))

    def test_issue137_manifest_rejects_changed_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_issue137_manifest_inputs(root)
            issue137_manifest.check(root)
            readme = root / issue137_manifest.BUNDLE / "README.md"
            readme.write_bytes(readme.read_bytes() + b"\nmutation\n")
            with self.assertRaisesRegex(
                    issue137_manifest.ManifestError, "manifest drift"):
                issue137_manifest.check(root)

    def test_issue137_manifest_rejects_undeclared_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_issue137_manifest_inputs(root)
            rogue = root / issue137_manifest.BUNDLE / "undeclared.json"
            rogue.write_text("{}\n")
            with self.assertRaisesRegex(
                    issue137_manifest.ManifestError, "unexpected"):
                issue137_manifest.check(root)

    def test_issue137_parent_authority_is_the_accepted_git_object(self):
        authority = issue137_phase1_inventory.accepted_manifest_bytes(ROOT)
        self.assertEqual(
            hashlib.sha256(authority).hexdigest(),
            issue137_phase1_inventory.AUTHORITY_MANIFEST_SHA256)
        committed = (
            ROOT / issue137_manifest.BUNDLE / "phase1-inventory.json"
        ).read_text()
        self.assertIn(issue137_phase1_inventory.AUTHORITY_MANIFEST_SHA256,
                      committed)


if __name__ == "__main__":
    unittest.main()
