from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/derive_phase1r_d4_placement.py"
HISTOGRAM = ROOT / "docs/investigations/data/p0i-routing-histogram.json"
D3 = ROOT / "docs/investigations/data/phase1r-d3-three-device-placement.json"
D4 = ROOT / "docs/investigations/data/phase1r-d4-capability-weighted-placement.json"


class D4PlacementTests(unittest.TestCase):
    def test_checked_in_artifact_is_mechanically_valid_and_companion_matches(self):
        artifact = json.loads(D4.read_text())
        self.assertEqual(artifact["schema"], "inferswarm.phase1r.d4-placement/1")
        self.assertEqual(artifact["status"], "FROZEN_BEFORE_D4_PERFORMANCE")
        a = artifact["partition"]["worker_a"]["flat_ids_in_rank_order"]
        b = artifact["partition"]["worker_b"]["flat_ids_in_rank_order"]
        local = artifact["partition"]["local_remainder"]["flat_ids"]
        self.assertEqual((len(a), len(b), len(local)), (3000, 3000, 4240))
        self.assertFalse(set(a) & set(b) or set(a) & set(local) or set(b) & set(local))
        self.assertEqual(set(a) | set(b) | set(local), set(range(10240)))
        d3 = json.loads(D3.read_text())
        self.assertEqual(set(a) | set(b), set(d3["ranking"]["ranked_union_flat_ids"]))
        self.assertEqual([row["slot"] for row in artifact["partition"]["worker_a"]["slot_mapping"]], list(range(3000)))
        digest = hashlib.sha256(D4.read_bytes()).hexdigest()
        companion = D4.with_suffix(".sha256.txt").read_text().split()[0]
        self.assertEqual(digest, companion)

    def test_derivation_is_byte_deterministic_for_frozen_inputs(self):
        artifact = json.loads(D4.read_text())
        c = artifact["calibration"]
        calibration = {"schema": "inferswarm.d4.worker-calibration/1",
                       "status": "FROZEN_BEFORE_D4_PLACEMENT_AND_PERFORMANCE",
                       "freetoken_sha": c["freetoken_sha"], "service_medians_us": c["service_medians_us"],
                       "normalized_capacity_targets": c["normalized_capacity_targets"],
                       "workers": {"a": {"physical_uuid": c["worker_a_uuid"]}, "b": {"physical_uuid": c["worker_b_uuid"]}}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); cal = root / "cal.json"; cal.write_text(json.dumps(calibration))
            outputs = [root / "one.json", root / "two.json"]
            for output in outputs:
                subprocess.run([sys.executable, str(SCRIPT), "--histogram", str(HISTOGRAM), "--calibration", str(cal),
                                "--d3-placement", str(D3), "--out", str(output)], check=True)
            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())


if __name__ == "__main__":
    unittest.main()
