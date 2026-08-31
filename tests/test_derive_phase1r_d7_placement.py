from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from derive_phase1r_d7_placement import minimum_split_layer_count, participation

SCRIPT = ROOT / "scripts/derive_phase1r_d7_placement.py"
D3 = ROOT / "docs/investigations/data/phase1r-d3-three-device-placement.json"
D7 = ROOT / "docs/investigations/data/phase1r-d7-fanin-sparse-placement.json"
ROUTING = Path("/home/zutfen/inferswarm-phase0-runs/2026-08-27-p0i-routing-1-qwen36-routing/exact-routing.jsonl")


class D7PlacementTests(unittest.TestCase):
    def test_frozen_artifact_preserves_union_and_exact_geometry(self):
        artifact = json.loads(D7.read_text())
        d3 = json.loads(D3.read_text())
        self.assertEqual(artifact["schema"], "inferswarm.phase1r.d7-placement/1")
        self.assertEqual(artifact["status"], "FROZEN_BEFORE_D7_PERFORMANCE")
        a = artifact["partition"]["worker_a"]["flat_ids_in_rank_order"]
        b = artifact["partition"]["worker_b"]["flat_ids_in_rank_order"]
        local = artifact["partition"]["local_remainder"]["flat_ids"]
        self.assertEqual((len(a), len(b), len(local)), (3000, 3000, 4240))
        self.assertFalse(set(a) & set(b) or set(a) & set(local) or set(b) & set(local))
        self.assertEqual(set(a) | set(b), set(d3["ranking"]["ranked_union_flat_ids"]))
        self.assertEqual(set(a) | set(b) | set(local), set(range(10240)))
        self.assertEqual(artifact["derivation"]["split_layer_count"], 0)
        self.assertEqual(artifact["validation"]["minimum_split_layer_count"], 0)
        self.assertTrue(all(not row["split"] for row in artifact["derivation"]["per_layer_ownership"]))
        for layer in range(40):
            owners = {"A" if flat in set(a) else "B" for flat in set(a) | set(b) if flat // 256 == layer}
            self.assertEqual(len(owners), 1)

    def test_companion_and_byte_deterministic_rerun(self):
        companion = D7.with_suffix(".sha256.txt").read_text().split()[0]
        self.assertEqual(hashlib.sha256(D7.read_bytes()).hexdigest(), companion)
        if not ROUTING.exists():
            self.skipTest("frozen external exact-route evidence is host-local")
        with tempfile.TemporaryDirectory() as directory:
            outputs = [Path(directory) / "one.json", Path(directory) / "two.json"]
            for output in outputs:
                subprocess.run([sys.executable, str(SCRIPT), "--exact-routing", str(ROUTING),
                                "--d3-placement", str(D3), "--out", str(output)], check=True)
            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
            self.assertEqual(outputs[0].read_bytes(), D7.read_bytes())

    def test_joint_participation_calculation(self):
        events = [(0, (0, 1, 2)), (0, (0, 3, 4)), (0, (3, 5, 6)), (0, (7, 8, 9))]
        report = participation(events, {0, 1}, {3, 5})
        self.assertEqual(report["counts"], {"zero": 1, "a_only": 1, "b_only": 1, "both": 1,
                                            "a_active": 2, "b_active": 2})
        self.assertEqual(report["mean_remote_workers_active"], 1.0)
        self.assertEqual(report["median_remote_workers_active"], 1)
        self.assertEqual(report["p95_remote_workers_active"], 2)

    def test_whole_layer_and_minimum_split_behavior(self):
        self.assertEqual(minimum_split_layer_count([2, 1], 3), 0)
        self.assertEqual(minimum_split_layer_count([2, 2], 3), 1)

    def test_capability_tie_break_is_deterministic_and_reduces_a_activity(self):
        artifact = json.loads(D7.read_text())
        expected = artifact["predicted_d7_participation"]["expected_active_layer_events"]
        self.assertLess(expected["a"]["equal_workload_rate"]["value"],
                        expected["b"]["equal_workload_rate"]["value"])
        self.assertEqual(artifact["derivation"]["worker_a_whole_layers"],
                         sorted(artifact["derivation"]["worker_a_whole_layers"]))


if __name__ == "__main__":
    unittest.main()
