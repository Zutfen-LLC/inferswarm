"""Issue #222 R7-C offline authority and capacity-gate regressions."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import issue222_r7c as r7c  # noqa: E402


class Issue222R7CTests(unittest.TestCase):
    def test_real_predecessors_and_stage_footprints_are_verified(self):
        authority = r7c.build_authority(ROOT, repo_head="f" * 40)
        self.assertEqual(authority["r7a"]["terminal"],
                         "R7A_DEEPSEEK_V41_SUBSTRATE_PREREQUISITE")
        self.assertEqual(authority["r7b"]["terminal"],
                         "R7B_DEEPSEEK_V41_PHYSICAL_GATE_READY")
        audit = authority["mainline_applicability_audit"]
        self.assertEqual(audit["start_after_r7b_merge"],
                         "54d36cb9d8a4c0603abeb18968a8ffb7b52ca10e")
        self.assertEqual(audit["reconciled_main"],
                         "fe690249873a9bf7ca19d788a2fab5e580473394")
        self.assertEqual(audit["r7_authority_or_strategy_changes"], [])
        stages = authority["stage_footprints"]
        self.assertEqual(set(stages), {"stage-a", "stage-b"})
        self.assertGreater(stages["stage-a"]["logical_required_bytes"], 0)
        self.assertGreater(stages["stage-b"]["logical_required_bytes"], 0)
        self.assertEqual(stages["stage-a"]["unassigned_tensors"], [])
        self.assertEqual(stages["stage-b"]["unassigned_tensors"], [])
        self.assertIn("embed.", stages["stage-a"]["ownership_rules"])
        self.assertIn("head.", stages["stage-b"]["ownership_rules"])
        self.assertEqual(authority["capacity_contract"]["simultaneous_logical_lower_bound_bytes"],
                         stages["stage-a"]["logical_required_bytes"]
                         + stages["stage-b"]["logical_required_bytes"])

    def test_alternate_cut_and_mutated_predecessor_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            r7c.copy_predecessor_inputs(ROOT, root)
            strategy_path = root / r7c.R7B_STRATEGY
            strategy = json.loads(strategy_path.read_text())
            strategy["cut_layer"] = 14
            strategy_path.write_text(json.dumps(strategy))
            with self.assertRaisesRegex(ValueError, "R7-B predecessor drift"):
                r7c.build_authority(root, repo_head="f" * 40)

            r7c.copy_predecessor_inputs(ROOT, root)
            census_path = root / r7c.R7A_CENSUS
            census_path.write_bytes(census_path.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "R7-A.*drift"):
                r7c.build_authority(root, repo_head="f" * 40)

    def test_aggregate_vram_cannot_substitute_for_per_stage_placement(self):
        stages = {
            "stage-a": {"logical_required_bytes": 30},
            "stage-b": {"logical_required_bytes": 30},
        }
        fleet = {
            "resources": [
                {"resource_id": "gpu-1", "compatible": True,
                 "usable_device_bytes": 20},
                {"resource_id": "gpu-2", "compatible": True,
                 "usable_device_bytes": 40},
            ]
        }
        result = r7c.legal_placement(stages, fleet)
        self.assertFalse(result["legal"])
        self.assertEqual(result["terminal"], r7c.CAPACITY_PREREQUISITE)
        self.assertEqual(result["aggregate_compatible_usable_bytes"], 60)
        self.assertEqual(result["rejected"]["stage-b"]["reason"],
                         "no single compatible resource satisfies the stage lower bound")

    def test_capacity_terminal_is_derived_not_authored(self):
        authority = r7c.build_authority(ROOT, repo_head="f" * 40)
        fleet = {
            "schema": r7c.FLEET_SCHEMA,
            "resources": [
                {"resource_id": "gpu-1", "compatible": True,
                 "usable_device_bytes": 1, "foreign_processes": []},
                {"resource_id": "gpu-2", "compatible": True,
                 "usable_device_bytes": 1, "foreign_processes": []},
            ],
        }
        reduced = r7c.reduction_document(authority, fleet)
        self.assertEqual(reduced["terminal"], r7c.CAPACITY_PREREQUISITE)
        self.assertEqual(set(reduced["placement"]["rejected"]),
                         {"stage-a", "stage-b"})

        forged = copy.deepcopy(reduced)
        forged["terminal"] = r7c.PASS_TERMINAL
        with self.assertRaisesRegex(ValueError, "authored terminal"):
            r7c.verify_committed_terminal(authority, fleet, forged)

    def test_fleet_assembly_requires_every_frozen_candidate_host(self):
        authority = r7c.build_authority(ROOT, repo_head="f" * 40)
        records = {
            "inferswarm01": {"host": "inferswarm01", "resources": [],
                              "problems": [], "collector_sha256": authority["producer_sha256"]},
            "inferswarm03": {"host": "inferswarm03", "resources": [],
                              "problems": [], "collector_sha256": authority["producer_sha256"]},
            "inferswarm02": {"host": "inferswarm02", "connection_failure": {
                "returncode": 255, "stderr": "timed out"}},
            "inferswarm04": {"host": "inferswarm04", "connection_failure": {
                "returncode": 255, "stderr": "timed out"}},
        }
        fleet = r7c.assemble_fleet(authority, records, collected_at_unix=1000)
        self.assertEqual(fleet["candidate_hosts"], list(r7c.CANDIDATE_HOSTS))
        self.assertEqual(fleet["unavailable_hosts"], ["inferswarm02", "inferswarm04"])
        self.assertEqual(set(fleet["host_records"]), set(r7c.CANDIDATE_HOSTS))
        self.assertEqual(len(fleet["resources"]), 0)
        with self.assertRaisesRegex(ValueError, "candidate-host set"):
            r7c.assemble_fleet(authority, {"inferswarm01": records["inferswarm01"]},
                               collected_at_unix=1000)

    def test_stale_and_foreign_process_fleet_rows_fail_closed(self):
        authority = r7c.build_authority(ROOT, repo_head="f" * 40)
        base_fleet = {
            "schema": r7c.FLEET_SCHEMA,
            "resources": [
                {"resource_id": "gpu-1", "compatible": True,
                 "usable_device_bytes": 1,
                 "foreign_processes": []},
            ],
        }
        stale = copy.deepcopy(base_fleet)
        stale["collected_at_unix"] = 0
        with self.assertRaisesRegex(ValueError, "freshness"):
            r7c.reduction_document(authority, stale, now_unix=1000)

        occupied = copy.deepcopy(base_fleet)
        occupied["collected_at_unix"] = 1000
        occupied["resources"][0]["foreign_processes"] = [{"pid": "9"}]
        reduced = r7c.reduction_document(authority, occupied, now_unix=1000)
        self.assertEqual(reduced["terminal"], r7c.CAPACITY_PREREQUISITE)
        self.assertEqual(reduced["placement"]["aggregate_compatible_usable_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
