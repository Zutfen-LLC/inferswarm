"""Repository-wide evidence-manifest lifecycle regressions (CPU-only)."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_ci_test_retention as retention  # noqa: E402
import issue117_proof  # noqa: E402
import issue137_phase1_inventory  # noqa: E402
import sync_project_status  # noqa: E402

ISSUE137_BUNDLE = ("docs/implementation/r6-successor-dense-full-integration-117/"
                   "evidence/arm-c-regime4-diagnosis-137/")
ISSUE137_MANIFEST = ISSUE137_BUNDLE + "MANIFEST.sha256"


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
    @classmethod
    def setUpClass(cls):
        cls.audit = retention.load_audit(ROOT)
        cls.retired, errors = retention.load_retired_rows(ROOT, cls.audit)
        assert not errors, errors

    def copy_issue137_bundle(self, root):
        """Scratch copy of the #137 bundle, its row targets, and tombstones."""
        rows = retention.parse_sha256sum(
            (ROOT / ISSUE137_MANIFEST).read_text(), "")
        for relative in [ISSUE137_MANIFEST, str(retention.RETIRED_ROWS), *rows]:
            if (ROOT / relative).is_file():
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination)
        for present in retention.files_under(ROOT, ISSUE137_BUNDLE):
            destination = root / present
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / present, destination)

    def issue137_errors(self, root):
        bundle = retention.replacement_bundle(self.audit, ISSUE137_BUNDLE)
        retired, _ = retention.load_retired_rows(root, self.audit)
        return retention.bundle_errors(root, bundle, retired)

    def test_manifests_are_current_outside_frozen_legacy_snapshots(self):
        manifests = sorted((ROOT / "docs").rglob("MANIFEST.sha256"))
        self.assertGreaterEqual(len(manifests), 9)
        for manifest in manifests:
            manifest_relative = manifest.relative_to(ROOT).as_posix()
            manifest_digest = sha256(manifest)
            legacy_rows = LEGACY_SNAPSHOT_ROWS.get(manifest_relative, set())
            listed = set()
            for line in manifest.read_text().splitlines():
                digest, separator, relative = line.partition("  ")
                self.assertEqual(separator, "  ", manifest)
                self.assertEqual(len(digest), 64, manifest)
                self.assertNotIn(relative, listed, manifest)
                self.assertNotEqual(ROOT / relative, manifest, manifest)
                listed.add(relative)
                target = ROOT / relative
                if not target.is_file():
                    # a deliberately deleted test file keeps its accepted
                    # row; only an exact Issue #246 tombstone excuses it
                    self.assertTrue(self.retired.permits(
                        manifest_relative, manifest_digest, relative, digest),
                        f"{manifest_relative}: row target missing without "
                        f"an exact retired-row tombstone: {relative}")
                    continue
                if relative not in legacy_rows:
                    self.assertNotIn(relative, FORBIDDEN_LIVING_PATHS,
                                     manifest)
                    self.assertEqual(sha256(target), digest, relative)
            self.assertLessEqual(legacy_rows, listed)
            self.assertEqual(
                listed & FORBIDDEN_LIVING_PATHS,
                legacy_rows & FORBIDDEN_LIVING_PATHS)

    def test_real_retired_rows_are_exactly_the_missing_manifest_targets(self):
        missing = set()
        for manifest in (ROOT / "docs").rglob("MANIFEST.sha256"):
            rows = retention.parse_sha256sum(manifest.read_text(), "")
            missing |= {(manifest.relative_to(ROOT).as_posix(), target)
                        for target in rows if not (ROOT / target).exists()}
        tombstoned = {(e["manifest"], e["target"])
                      for e in self.retired.entries
                      if e["manifest"].endswith("MANIFEST.sha256")}
        self.assertEqual(missing, tombstoned)

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
        rows = retention.parse_sha256sum(
            (ROOT / ISSUE137_MANIFEST).read_text(), "")
        self.assertNotIn(ISSUE137_MANIFEST, rows)
        self.assertEqual(self.issue137_errors(ROOT), [])
        # every bundle file other than the manifest itself is a row
        self.assertEqual(
            set(retention.files_under(ROOT, ISSUE137_BUNDLE))
            - {ISSUE137_MANIFEST},
            {r for r in rows if r.startswith(ISSUE137_BUNDLE)})

    def test_issue137_manifest_rejects_changed_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_issue137_bundle(root)
            self.assertEqual(self.issue137_errors(root), [])
            readme = root / ISSUE137_BUNDLE / "README.md"
            readme.write_bytes(readme.read_bytes() + b"\nmutation\n")
            self.assertTrue(any("accepted evidence changed" in e
                                for e in self.issue137_errors(root)))

    def test_issue137_manifest_rejects_undeclared_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_issue137_bundle(root)
            (root / ISSUE137_BUNDLE / "undeclared.json").write_text("{}\n")
            self.assertTrue(any("undeclared evidence file" in e
                                for e in self.issue137_errors(root)))

    def test_issue137_retired_test_rows_need_their_exact_tombstones(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_issue137_bundle(root)
            (root / retention.RETIRED_ROWS).write_text(json.dumps({
                "schema": retention.RETIRED_ROWS_SCHEMA,
                "retirements": []}))
            errors = self.issue137_errors(root)
            self.assertTrue(any(
                "accepted row missing: tests/test_issue137_regime4_diagnosis.py"
                in e for e in errors), errors)

    def test_issue137_parent_authority_is_the_accepted_git_object(self):
        authority = issue137_phase1_inventory.accepted_manifest_bytes(ROOT)
        self.assertEqual(
            hashlib.sha256(authority).hexdigest(),
            issue137_phase1_inventory.AUTHORITY_MANIFEST_SHA256)
        committed = (
            ROOT / ISSUE137_BUNDLE / "phase1-inventory.json"
        ).read_text()
        self.assertIn(issue137_phase1_inventory.AUTHORITY_MANIFEST_SHA256,
                      committed)


if __name__ == "__main__":
    unittest.main()
