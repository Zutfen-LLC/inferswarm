from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "derive_phase1r_d3_placement.py"
HISTOGRAM = ROOT / "docs" / "investigations" / "data" / "p0i-routing-histogram.json"


class D3PlacementTests(unittest.TestCase):
    def test_checked_in_artifact_is_deterministic_and_mechanically_valid(self):
        checked = ROOT / "docs" / "investigations" / "data" / "phase1r-d3-three-device-placement.json"
        with tempfile.TemporaryDirectory() as directory:
            derived = Path(directory) / "placement.json"
            subprocess.run([sys.executable, str(SCRIPT), "--histogram", str(HISTOGRAM), "--out", str(derived)], check=True)
            self.assertEqual(derived.read_bytes(), checked.read_bytes())
        artifact = json.loads(checked.read_text())
        self.assertEqual(artifact["status"], "FROZEN_BEFORE_D3_PERFORMANCE")
        self.assertEqual(artifact["geometry"]["gpu0_cache_slots"], 3774)
        self.assertEqual(artifact["geometry"]["worker_resident_bytes_each"], 5326848000)
        self.assertEqual(artifact["geometry"]["combined_worker_resident_bytes"], 10653696000)
        a = artifact["partition"]["worker_a"]["flat_ids_in_rank_order"]
        b = artifact["partition"]["worker_b"]["flat_ids_in_rank_order"]
        self.assertEqual((len(a), len(b), len(set(a) | set(b))), (3000, 3000, 6000))
        self.assertFalse(set(a) & set(b))
        for identity in artifact["partition"]["worker_a"]["identities"] + artifact["partition"]["worker_b"]["identities"]:
            self.assertEqual(identity["flat_id"], identity["layer"] * 256 + identity["expert_id"])
