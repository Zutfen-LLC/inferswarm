"""Issue #222 R7-C offline authority and capacity-gate regressions."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import issue222_r7c as r7c  # noqa: E402
import finalize_repository as finalizer  # noqa: E402


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
        fleet = self._valid_fleet(authority)
        reduced = r7c.reduction_document(authority, fleet, now_unix=1000)
        self.assertEqual(reduced["terminal"], r7c.CAPACITY_PREREQUISITE)
        self.assertEqual(set(reduced["placement"]["rejected"]),
                         {"stage-a", "stage-b"})

        forged = copy.deepcopy(reduced)
        forged["terminal"] = r7c.PASS_TERMINAL
        with self.assertRaisesRegex(ValueError, "authored terminal"):
            r7c.verify_committed_terminal(authority, fleet, forged)

    def _receipt(self, argv, stdout="", stderr="", returncode=0):
        return {
            "argv": argv,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
        }

    def _valid_fleet(self, authority, collected_at=1000):
        gpu = self._receipt(
            ["nvidia-smi", "--query-gpu=index,uuid,pci.bus_id,name,memory.total,memory.free,memory.used,driver_version", "--format=csv,noheader,nounits"],
            "0, GPU-r7c-test, 00000000:01:00.0, Test GPU, 10, 1, 9, 1.0\n")
        apps = self._receipt(
            ["nvidia-smi", "--query-compute-apps=pid,gpu_uuid,used_memory", "--format=csv,noheader,nounits"])
        host = self._receipt(["hostname"], "inferswarm01\n")
        records = {
            "inferswarm01": {
                "schema": "inferswarm.issue222.r7c-host-record/1",
                "campaign_id": authority["campaign_id"],
                "authority_sha256": authority["authority_sha256"],
                "collector_sha256": authority["producer_sha256"],
                "host": "inferswarm01", "collected_at_unix": collected_at,
                "receipts": {"nvidia_smi_gpu": gpu, "nvidia_smi_apps": apps,
                             "hostname": host,
                             "storage": self._receipt(["df", "-B1", "."], "header\n"),
                             "memory": self._receipt(["free", "-b"], "header\n")},
                "resources": [{
                    "resource_id": "inferswarm01/gpu-0", "host": "inferswarm01",
                    "index": "0", "uuid": "GPU-r7c-test", "pci_bdf": "00000000:01:00.0",
                    "name": "Test GPU", "total_device_bytes": 10 * 1024 * 1024,
                    "available_device_bytes": 1024 * 1024,
                    "used_device_bytes": 9 * 1024 * 1024,
                    "usable_device_bytes": 1024 * 1024, "driver_version": "1.0",
                    "compatible": True, "foreign_processes": [],
                }], "problems": [],
            },
        }
        for host_name in r7c.CANDIDATE_HOSTS[1:]:
            stderr = "timed out"
            records[host_name] = {
                "schema": "inferswarm.issue222.r7c-connection-failure/1",
                "campaign_id": authority["campaign_id"],
                "authority_sha256": authority["authority_sha256"],
                "collector_sha256": authority["producer_sha256"],
                "host": host_name, "collected_at_unix": collected_at,
                "connection_failure": {"returncode": 255, "stderr": stderr,
                                       "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest()},
            }
        return r7c.assemble_fleet(authority, records,
                                  collected_at_unix=collected_at)

    def test_reducer_requires_assembled_fleet_provenance(self):
        authority = r7c.build_authority(ROOT, repo_head="f" * 40)
        bypassed = {
            "schema": r7c.FLEET_SCHEMA, "campaign_id": authority["campaign_id"],
            "authority_sha256": authority["authority_sha256"],
            "collected_at_unix": 1000,
            "resources": [{"resource_id": "forged", "compatible": True,
                           "usable_device_bytes": 1, "foreign_processes": []}],
        }
        with self.assertRaisesRegex(ValueError, "candidate-host|host record|assembled"):
            r7c.reduction_document(authority, bypassed, now_unix=1000)

    def test_reducer_reparses_raw_gpu_receipts_and_rejects_parsed_row_tamper(self):
        authority = r7c.build_authority(ROOT, repo_head="f" * 40)
        fleet = self._valid_fleet(authority)
        fleet["resources"][0]["usable_device_bytes"] = 999999999999
        with self.assertRaisesRegex(ValueError, "fleet.*assembled|resource.*receipt|receipt.*resource"):
            r7c.reduction_document(authority, fleet, now_unix=1000)

    def test_reducer_rejects_raw_receipt_hash_drift(self):
        authority = r7c.build_authority(ROOT, repo_head="f" * 40)
        fleet = self._valid_fleet(authority)
        fleet["host_records"]["inferswarm01"]["receipts"]["nvidia_smi_gpu"]["stdout"] += "forged\\n"
        with self.assertRaisesRegex(ValueError, "receipt.*hash|raw.*receipt"):
            r7c.reduction_document(authority, fleet, now_unix=1000)

    def test_reduction_requires_explicit_time_contract(self):
        authority = r7c.build_authority(ROOT, repo_head="f" * 40)
        fleet = self._valid_fleet(authority)
        with self.assertRaisesRegex(ValueError, "reduction.*time|freshness"):
            r7c.reduction_document(authority, fleet)

    def test_finalizer_reuses_the_preserved_reduction_time(self):
        authority = r7c.build_authority(ROOT, repo_head="f" * 40)
        fleet = self._valid_fleet(authority)
        committed = r7c.reduction_document(authority, fleet, now_unix=1000)
        self.assertEqual(committed["reduced_at_unix"], 1000)

        class Run:
            root = ROOT

            def read(_, path):
                return {
                    finalizer._R7C_AUTHORITY: r7c.canonical(authority),
                    finalizer._R7C_FLEET: r7c.canonical(fleet),
                    finalizer._R7C_TERMINAL: r7c.canonical(committed),
                }.get(path)

        stage = next(stage for stage in finalizer.default_registry()
                     if stage.id == "issue222-terminal")
        self.assertIn(finalizer._R7C_TERMINAL, stage.reads)
        self.assertEqual(finalizer._issue222_terminal_producer(Run(), Path(".")),
                         {finalizer._R7C_TERMINAL: r7c.canonical(committed)})

    def test_fleet_assembly_requires_every_frozen_candidate_host(self):
        authority = r7c.build_authority(ROOT, repo_head="f" * 40)
        records = copy.deepcopy(self._valid_fleet(authority)["host_records"])
        fleet = r7c.assemble_fleet(authority, records, collected_at_unix=1000)
        self.assertEqual(fleet["candidate_hosts"], list(r7c.CANDIDATE_HOSTS))
        self.assertEqual(fleet["unavailable_hosts"], ["inferswarm02", "inferswarm03", "inferswarm04"])
        self.assertEqual(set(fleet["host_records"]), set(r7c.CANDIDATE_HOSTS))
        self.assertEqual(len(fleet["resources"]), 1)
        with self.assertRaisesRegex(ValueError, "candidate-host set"):
            r7c.assemble_fleet(authority, {"inferswarm01": records["inferswarm01"]},
                               collected_at_unix=1000)

    def test_stale_and_foreign_process_fleet_rows_fail_closed(self):
        authority = r7c.build_authority(ROOT, repo_head="f" * 40)
        stale = self._valid_fleet(authority, collected_at=0)
        with self.assertRaisesRegex(ValueError, "freshness"):
            r7c.reduction_document(authority, stale, now_unix=1000)

        occupied = self._valid_fleet(authority)
        record = occupied["host_records"]["inferswarm01"]
        apps = record["receipts"]["nvidia_smi_apps"]
        apps["stdout"] = "9, GPU-r7c-test, 1\n"
        apps["stdout_sha256"] = hashlib.sha256(apps["stdout"].encode()).hexdigest()
        record["resources"], record["problems"] = r7c._raw_resources("inferswarm01", record["receipts"])
        occupied = r7c.assemble_fleet(authority, occupied["host_records"], collected_at_unix=1000)
        reduced = r7c.reduction_document(authority, occupied, now_unix=1000)
        self.assertEqual(reduced["terminal"], r7c.CAPACITY_PREREQUISITE)
        self.assertEqual(reduced["placement"]["aggregate_compatible_usable_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
