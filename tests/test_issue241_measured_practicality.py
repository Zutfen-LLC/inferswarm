"""Measured-wall custody controls; CPU-only, no physical producer invocation."""
from __future__ import annotations
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from scripts import issue241_constants as C
from scripts import issue241_dispatch as dispatch
from scripts import issue241_practicality as practicality
from scripts import issue241_comparator as comparator

AUTHORITY = {"schema": dispatch.AUTHORITY_SCHEMA, "head_sha": "a" * 40,
             "review_commit_id": "a" * 40, "dispatch_phrase": dispatch.DISPATCH_PHRASE,
             "pr_number": 242, "issue_number": 241}

class MeasuredPracticalityTests(unittest.TestCase):
    def fixture(self, root: Path, *, claimed_wall: float = 2.0) -> Path:
        measurements = {}
        for arm in ("B", "C"):
            measurements[arm] = {}
            for case in C.FIXTURE_CASES:
                timing = root / f"{arm}-{case}-timing.json"
                timing.write_text(json.dumps({"wall_s": 2.0, "arm": arm, "case_id": case}))
                run = root / f"{arm}-{case}-run.json"
                run.write_text(json.dumps({"schema": comparator.RUN_SCHEMA,
                    "arm": arm, "case_id": case, "ngl": 4,
                    "wall_time_s": 2.0, "dispatch_authority": AUTHORITY}))
                measurements[arm][case] = {
                    "wall_s": claimed_wall,
                    "timing_raw_path": timing.name,
                    "timing_raw_sha256": hashlib.sha256(timing.read_bytes()).hexdigest(),
                    "run_receipt_path": run.name,
                    "run_receipt_sha256": hashlib.sha256(run.read_bytes()).hexdigest()}
        receipt = root / "measured.json"
        receipt.write_text(json.dumps({
            "schema": "inferswarm.issue241.measured-wall-times/1",
            "campaign": C.CAMPAIGN_ID, "matched_ngl": 4,
            "dispatch_authority": AUTHORITY,
            "selected_receipt_sha256": "b" * 64,
            "measurements": measurements}))
        return receipt

    def test_missing_measurement_receipt_refuses_projection(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises((ValueError, FileNotFoundError)):
                practicality.project_from_measurements(Path(temp) / "none.json")

    def test_raw_timing_drives_projection_not_claimed_wall(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                practicality.project_from_measurements(self.fixture(Path(temp), claimed_wall=1.0))

    def test_bound_run_receipt_allows_projection(self):
        with tempfile.TemporaryDirectory() as temp:
            result = practicality.project_from_measurements(self.fixture(Path(temp)))
            self.assertEqual(result["matched_ngl"], 4)
            self.assertGreater(result["candidate"]["central_s"], 0)

    def test_tampered_run_receipt_blocks_projection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipt = self.fixture(root)
            (root / f"B-{C.FIXTURE_CASES[0]}-run.json").write_text("{}")
            with self.assertRaises(ValueError):
                practicality.project_from_measurements(receipt)

    def test_cross_head_run_receipt_blocks_projection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipt = self.fixture(root)
            doc = json.loads(receipt.read_text())
            doc["dispatch_authority"]["head_sha"] = "c" * 40
            receipt.write_text(json.dumps(doc))
            with self.assertRaises(ValueError):
                practicality.project_from_measurements(receipt)

    def test_nonfinite_wall_rejected(self):
        walls = {c: 1.0 for c in C.FIXTURE_CASES}
        walls["case-256"] = float("nan")
        with self.assertRaises(ValueError):
            practicality.project_arm(walls)

if __name__ == "__main__":
    unittest.main()
