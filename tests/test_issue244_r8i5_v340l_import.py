"""Issue #244 Phase-0 durable import of accepted Issue #243 evidence."""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
AREA = REPO / "docs/investigations/qwen38-flash-next-r8-i4-v340l-z440"
MANIFEST = AREA / "MANIFEST.sha256"
SOURCE_MANIFEST = AREA / "SOURCE-MANIFEST.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Issue244DurableImportTests(unittest.TestCase):
    def test_import_has_a_complete_non_self_referential_manifest(self):
        listed = {}
        for line in MANIFEST.read_text().splitlines():
            digest, separator, relative = line.partition("  ")
            self.assertEqual(separator, "  ")
            self.assertEqual(len(digest), 64)
            self.assertNotIn(relative, listed)
            listed[relative] = digest

        expected = {
            path.relative_to(REPO).as_posix()
            for path in AREA.rglob("*")
            if path.is_file() and path != MANIFEST
        }
        expected.add("tests/test_issue244_r8i5_v340l_import.py")
        self.assertEqual(set(listed), expected)
        for relative, digest in listed.items():
            self.assertEqual(sha256(REPO / relative), digest, relative)

    def test_every_retrieved_remote_byte_is_cross_bound(self):
        source = json.loads(SOURCE_MANIFEST.read_text())
        self.assertEqual(source["schema"], "inferswarm.issue244.source-import/1")
        self.assertEqual(source["source_host"], "inferswarm05")
        self.assertEqual(source["source_root"], "/home/hermes/is243")
        self.assertEqual(source["file_count"], 81)
        self.assertEqual(len(source["files"]), source["file_count"])
        for record in source["files"]:
            self.assertEqual(len(record["sha256"]), 64)
            self.assertTrue(record["source_path"])
            target = AREA / record["repository_path"]
            self.assertTrue(target.is_file(), record["repository_path"])
            self.assertEqual(target.stat().st_size, record["bytes"])
            self.assertEqual(sha256(target), record["sha256"], record["repository_path"])

        decision = next(
            record
            for record in source["files"]
            if record.get("source_kind") == "accepted-decision-report-comment"
        )
        acceptance = next(
            record
            for record in source["files"]
            if record.get("source_kind") == "maintainer-acceptance-comment"
        )
        self.assertEqual(decision["source_path"].rsplit("/", 1)[-1], "5803481831")
        self.assertEqual(acceptance["source_path"].rsplit("/", 1)[-1], "5803559861")

    def test_accepted_decision_and_maintainer_go_are_retained(self):
        decision = (AREA / "retained/issue243-decision-comment-5803481831.md").read_text()
        acceptance = (
            AREA / "retained/issue243-maintainer-acceptance-comment-5803559861.md"
        ).read_text()
        self.assertIn("R8I4_V340_Z440_PRACTICAL_SINGLE_DIE_AND_DUAL_RESOURCE", decision)
        self.assertIn("GO for closure work", acceptance)
        self.assertIn("do not execute `c237-*` predictive calibration", acceptance)

    def test_topology_preserves_complete_paths_without_two_uplink_claim(self):
        topology = (
            AREA / "retained/raw/phase1/lspci-PP-nn.txt"
        ).read_text()
        self.assertIn(
            "00:03.0/03:00.0/04:00.0/05:00.0/06:00.0/07:00.0",
            topology,
        )
        self.assertIn(
            "00:03.0/03:00.0/04:01.0/09:00.0/0a:00.0/0b:00.0",
            topology,
        )
        ledger = (REPO / "docs/hardware/pcie-slot-ledger.md").read_text()
        self.assertIn("## inferswarm05", ledger)
        self.assertIn("shared upstream/root-port path", ledger)
        self.assertIn("not two independent host uplinks", ledger)

    def test_import_is_engineering_evidence_not_comparator_authority(self):
        readme = (AREA / "README.md").read_text()
        self.assertIn("R8I4_V340_Z440_PRACTICAL_SINGLE_DIE_AND_DUAL_RESOURCE", readme)
        self.assertIn("18.11 h", readme)
        self.assertIn("temporary 140 mm cooling arrangement", readme)
        self.assertIn("not a full-TDP or universal cooling qualification", readme)
        self.assertIn("does not authorize comparator/2 execution", readme)
        self.assertIn("or authorize R8-J", readme)


if __name__ == "__main__":
    unittest.main()
