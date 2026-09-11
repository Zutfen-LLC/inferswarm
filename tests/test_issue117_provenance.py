"""Regression tests for Issue #117 historical-provenance boundaries."""
import hashlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


IMMUTABLE_ACCEPTED_FILES = {
    "scripts/issue99_artifact_core.py":
        "8b88af5b2f738c2a7428c9538cf76a14f889cb573a1722122951c45fc5965321",
    "docs/implementation/plan-driven-artifact-acquisition-99/evidence/canonical-summary.json":
        "104e854dc4bf2106c8aafcfd93c74dbecb7b8f19633ae507c9946ced0a2452fe",
    "docs/implementation/plan-driven-artifact-orchestration-101/evidence/producer-hashes.json":
        "887ec2e8ef159601e343a4b0afa6b8f5ccb69c754231178375c4eec09925fe86",
    "docs/implementation/artifact-locality-transition-planning-103/evidence/producer-hashes.json":
        "643b5dc6672461f2c0b5e6f5c1679536eaff28423cb94a904b84f79f926135f0",
}


class Issue117ProvenanceTests(unittest.TestCase):
    def test_issue117_does_not_mutate_accepted_issue99_101_103_evidence(self):
        for relative, expected in IMMUTABLE_ACCEPTED_FILES.items():
            self.assertEqual(sha256(relative), expected, relative)

    def test_historical_manifests_keep_legacy_snapshot_rows_closed(self):
        manifests = {
            "docs/implementation/plan-driven-artifact-acquisition-99/evidence/MANIFEST.sha256": {
                ".github/workflows/ci.yml", "ARCHITECTURE.md", "ROADMAP.md",
                "docs/implementation/README.md", "tests/test_issue99_proof.py"},
            "docs/implementation/plan-driven-artifact-orchestration-101/evidence/MANIFEST.sha256": {
                ".github/workflows/ci.yml", "tests/test_issue101_proof.py"},
            "docs/implementation/artifact-locality-transition-planning-103/evidence/MANIFEST.sha256": {
                ".github/workflows/ci.yml", "tests/test_issue103_planner.py"},
        }
        for relative, snapshot_rows in manifests.items():
            for line in (ROOT / relative).read_text().splitlines():
                expected, path = line.split("  ", 1)
                if path not in snapshot_rows:
                    self.assertEqual(
                        sha256(path), expected, f"{relative}: {path}")
