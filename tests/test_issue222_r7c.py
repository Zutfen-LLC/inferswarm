"""Issue #222 R7-C offline authority and capacity-gate regressions."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import issue222_r7c as r7c  # noqa: E402
import finalize_repository as finalizer  # noqa: E402
import plan_ci  # noqa: E402


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
        # 20 + 40 aggregate still cannot host one 30-byte stage: stage A takes
        # the only large-enough resource and stage B is left without a distinct
        # one. The reason is derived, not the size claim.
        self.assertEqual(result["rejected"]["stage-b"]["reason"],
                         "every compatible resource large enough for this stage is "
                         "already assigned to another stage")
        self.assertEqual(result["rejected"]["stage-b"]["deficit_bytes"], 0)

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
            "0, GPU-r7c-test, 00000000:01:00.0, NVIDIA GeForce RTX 3060, 10, 1, 9, 1.0\n")
        apps = self._receipt(
            ["nvidia-smi", "--query-compute-apps=pid,gpu_uuid,used_memory", "--format=csv,noheader,nounits"])
        host = self._receipt(["hostname"], "inferswarm01\n")
        receipts = {"nvidia_smi_gpu": gpu, "nvidia_smi_apps": apps, "hostname": host,
                    "storage": self._receipt(["df", "-B1", "."], "header\n"),
                    "memory": self._receipt(["free", "-b"], "header\n")}
        # The fixture exercises the producer's own parser: rows are never
        # hand-authored, so a parser hardening cannot silently stop being
        # covered by the fixture.
        resources, problems = r7c._raw_resources("inferswarm01", receipts)
        records = {
            "inferswarm01": {
                "schema": "inferswarm.issue222.r7c-host-record/1",
                "campaign_id": authority["campaign_id"],
                "authority_sha256": authority["authority_sha256"],
                "collector_sha256": authority["producer_sha256"],
                "host": "inferswarm01", "collected_at_unix": collected_at,
                "receipts": receipts, "resources": resources, "problems": problems,
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

    def test_committed_authority_terminal_and_bounds_are_pinned(self):
        """The delivered bundle's own bounds and terminal are asserted, not implied."""
        root = Path(__file__).resolve().parents[1]
        area = root / r7c.AREA
        authority = json.loads((area / "authority.json").read_text())
        fleet = json.loads((area / "fleet-census.json").read_text())
        committed = json.loads((area / "terminal-reduction.json").read_text())
        r7c.verify_committed_terminal(authority, fleet, committed, root=root)
        self.assertEqual(committed["terminal"], r7c.CAPACITY_PREREQUISITE)
        # The Issue #222 acceptance values, asserted against the retained bytes.
        self.assertEqual(authority["stage_footprints"]["stage-a"]["logical_required_bytes"],
                         352235502576)
        self.assertEqual(authority["stage_footprints"]["stage-b"]["logical_required_bytes"],
                         149147108832)
        self.assertEqual(committed["placement"]["rejected"]["stage-a"]["required_lower_bound_bytes"],
                         352235502576)
        self.assertEqual(committed["placement"]["rejected"]["stage-b"]["required_lower_bound_bytes"],
                         149147108832)
        self.assertFalse(committed["placement"]["legal"])

    def test_resigned_authority_cannot_bypass_authority_derivation(self):
        """A self-consistent re-signed authority must fail closed (round-1 P1)."""
        authority = r7c.build_authority(ROOT, repo_head="f" * 40)
        fleet = self._valid_fleet(authority)

        def _alternate_cut(document):
            document["strategy"].update({"cut_layer": 14, "stage_a_layers": [0, 14],
                                         "stage_b_layers": [14, 40]})

        attacks = {
            "alternate cut 14": _alternate_cut,
            "authored stage-a lower bound": lambda d: d["stage_footprints"]["stage-a"].update(
                {"logical_required_bytes": 1}),
            "authored stage-a tensor count": lambda d: d["stage_footprints"]["stage-a"].update(
                {"tensor_count": 1}),
            "emptied stage-b shard list": lambda d: d["stage_footprints"]["stage-b"].update(
                {"shards": []}),
            "substituted model revision": lambda d: d["model"].update({"revision": "0" * 40}),
            "substituted runtime revision": lambda d: d["runtime"].update({"revision": "1" * 40}),
            "substituted producer identity": lambda d: d.update({"producer_sha256": "deadbeef" * 8}),
            "dropped R7-B binding": lambda d: d["r7b"].update({"terminal_sha256": "0" * 64}),
        }
        for name, mutate in attacks.items():
            with self.subTest(attack=name):
                forged = copy.deepcopy(authority)
                mutate(forged)
                forged.pop("authority_sha256")
                forged["authority_sha256"] = hashlib.sha256(r7c.canonical(forged)).hexdigest()
                resealed = copy.deepcopy(fleet)
                resealed["authority_sha256"] = forged["authority_sha256"]
                for host in resealed["host_records"]:
                    resealed["host_records"][host]["authority_sha256"] = forged["authority_sha256"]
                with self.assertRaisesRegex(ValueError, "not the deterministic derivation"):
                    r7c.reduction_document(forged, resealed, now_unix=1000)

    def test_authority_derivation_requires_pinned_repo_head(self):
        authority = r7c.build_authority(ROOT, repo_head="f" * 40)
        for bad in (None, "", "abc", 12345):
            with self.subTest(repo_head=bad):
                forged = copy.deepcopy(authority)
                forged["repo_head"] = bad
                forged.pop("authority_sha256")
                forged["authority_sha256"] = hashlib.sha256(r7c.canonical(forged)).hexdigest()
                with self.assertRaisesRegex(ValueError, "repo head"):
                    r7c.verify_authority_derivation(forged, ROOT)

    def test_retained_mainline_changed_path_census_is_rederivable(self):
        root = Path(__file__).resolve().parents[1]
        retained = (root / r7c.MAINLINE_PATHS).read_bytes()
        self.assertEqual(retained, r7c.derive_mainline_changed_paths(root))
        audit = r7c.mainline_applicability_audit(root)
        self.assertEqual(audit["r7_authority_or_strategy_changes"], [])
        self.assertEqual(audit["reconciled_main"], r7c.RECONCILED_MAIN)

    def _gpu_receipt(self, stdout):
        return self._receipt(
            ["nvidia-smi", "--query-gpu=index,uuid,pci.bus_id,name,memory.total,memory.free,memory.used,driver_version", "--format=csv,noheader,nounits"],
            stdout)

    def test_device_compatibility_is_derived_from_receipt_bytes(self):
        self.assertTrue(r7c._compatible_device("NVIDIA GeForce RTX 3090"))
        self.assertFalse(r7c._compatible_device("AMD Radeon RX 7900 XTX"))
        receipts = {
            "nvidia_smi_gpu": self._gpu_receipt(
                "0, GPU-x, 00000000:01:00.0, AMD Radeon RX 7900 XTX, 24576, 24123, 1, 1.0\n"),
            "nvidia_smi_apps": self._receipt(
                ["nvidia-smi", "--query-compute-apps=pid,gpu_uuid,used_memory", "--format=csv,noheader,nounits"]),
            "hostname": self._receipt(["hostname"], "inferswarm01\n"),
            "storage": self._receipt(["df", "-B1", "."], "header\n"),
            "memory": self._receipt(["free", "-b"], "header\n"),
        }
        resources, _ = r7c._raw_resources("inferswarm01", receipts)
        self.assertFalse(resources[0]["compatible"])

    def test_duplicate_pci_bdf_fails_closed(self):
        receipts = {
            "nvidia_smi_gpu": self._gpu_receipt(
                "0, GPU-a, 00000000:01:00.0, NVIDIA GeForce RTX 3060, 12288, 11907, 1, 1.0\n"
                "1, GPU-b, 00000000:01:00.0, NVIDIA GeForce RTX 3060, 12288, 11907, 1, 1.0\n"),
            "nvidia_smi_apps": self._receipt(
                ["nvidia-smi", "--query-compute-apps=pid,gpu_uuid,used_memory", "--format=csv,noheader,nounits"]),
            "hostname": self._receipt(["hostname"], "inferswarm01\n"),
            "storage": self._receipt(["df", "-B1", "."], "header\n"),
            "memory": self._receipt(["free", "-b"], "header\n"),
        }
        with self.assertRaisesRegex(ValueError, "contradictory"):
            r7c._raw_resources("inferswarm01", receipts)

    def test_legal_capacity_cannot_emit_pass_from_this_reducer(self):
        """The PASS terminal stays unreachable: a legal fleet raises instead."""
        authority = r7c.build_authority(ROOT, repo_head="f" * 40)
        fleet = self._valid_fleet(authority)
        record = fleet["host_records"]["inferswarm01"]
        record["receipts"]["nvidia_smi_gpu"] = self._gpu_receipt(
            "0, GPU-huge-a, 00000000:01:00.0, NVIDIA GeForce RTX 3090, 1048576, 1048576, 0, 1.0\n"
            "1, GPU-huge-b, 00000000:02:00.0, NVIDIA GeForce RTX 3090, 1048576, 1048576, 0, 1.0\n")
        record["resources"], record["problems"] = r7c._raw_resources(
            "inferswarm01", record["receipts"])
        legal = r7c.assemble_fleet(authority, fleet["host_records"], collected_at_unix=1000)
        self.assertTrue(r7c.legal_placement(
            authority["stage_footprints"], legal)["legal"])
        with self.assertRaisesRegex(ValueError, "no PASS is admitted"):
            r7c.reduction_document(authority, legal, now_unix=1000)

    def test_retained_changed_path_census_is_part_of_the_authority_derivation(self):
        """The authority must be a pure function of retained bytes, with no git.

        The finalizer sandbox has no repository and no git, so the derivation
        must succeed from the copied predecessor tree plus the retained
        changed-path census alone - and must fail closed when that census is
        altered.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            r7c.copy_predecessor_inputs(ROOT, root)
            census = root / r7c.MAINLINE_PATHS
            census.parent.mkdir(parents=True, exist_ok=True)
            census.write_bytes((ROOT / r7c.MAINLINE_PATHS).read_bytes())
            committed = json.loads((ROOT / r7c.AREA / "authority.json").read_text())
            # Positive control: a git-free sandbox still reproduces the authority.
            r7c.verify_authority_derivation(committed, root)
            self.assertFalse((root / ".git").exists())
            # Negative control: an altered retained census breaks the derivation.
            census.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "not the deterministic derivation"):
                r7c.verify_authority_derivation(committed, root)

    def test_resource_exhaustion_reports_an_accurate_reason(self):
        """A stage blocked by an already-assigned resource is not misreported."""
        stages = {
            "stage-a": {"logical_required_bytes": 30},
            "stage-b": {"logical_required_bytes": 30},
        }
        fleet = {"resources": [{"resource_id": "gpu-1", "compatible": True,
                                "usable_device_bytes": 100, "foreign_processes": []}]}
        result = r7c.legal_placement(stages, fleet)
        self.assertFalse(result["legal"])
        self.assertEqual(result["placements"], {"stage-a": "gpu-1"})
        rejected = result["rejected"]["stage-b"]
        self.assertEqual(rejected["deficit_bytes"], 0)
        self.assertEqual(rejected["reason"],
                         "every compatible resource large enough for this stage is "
                         "already assigned to another stage")
        # The size-based claim is reserved for a genuinely undersized fleet.
        undersized = {"resources": [{"resource_id": "gpu-1", "compatible": True,
                                     "usable_device_bytes": 20, "foreign_processes": []}]}
        size_result = r7c.legal_placement(stages, undersized)
        self.assertEqual(size_result["rejected"]["stage-a"]["reason"],
                         "no single compatible resource satisfies the stage lower bound")
        self.assertEqual(size_result["rejected"]["stage-a"]["deficit_bytes"], 10)

    def test_readme_claims_match_the_retained_evidence(self):
        """Pin the README's machine-checkable claims AND their attributions.

        A stale `repo_head` citation in the README was filed as a P1 twice
        because no control tied the prose to the evidence. This control derives
        each pinned value from the retained bytes, asserts it inside the exact
        phrase that attributes it, refuses any 40-hex identity the README cites
        that is not a retained identity, and checks the superseded-observation
        paragraph against those commits' own censuses.
        """
        root = Path(__file__).resolve().parents[1]
        area = root / r7c.AREA
        readme = (area / "README.md").read_text()
        flat = " ".join(readme.split())  # prose claims may wrap across lines
        authority = json.loads((area / "authority.json").read_text())
        fleet = json.loads((area / "fleet-census.json").read_text())
        committed = json.loads((area / "terminal-reduction.json").read_text())
        r7b_terminal = json.loads((root / r7c.R7B_TERMINAL).read_text())
        r7a_census = json.loads((root / r7c.R7A_CENSUS).read_text())
        audit = authority["mainline_applicability_audit"]
        rejected = committed["placement"]["rejected"]
        stage_a = authority["stage_footprints"]["stage-a"]
        stage_b = authority["stage_footprints"]["stage-b"]
        claims = {
            "repo_head": authority["repo_head"],
            "R7-A merge": r7b_terminal["predecessor"]["merge"],
            "R7-B merge": r7c.R7B_MERGE,
            "reconciled main": r7c.RECONCILED_MAIN,
            "model revision": authority["model"]["revision"],
            "runtime revision": authority["runtime"]["revision"],
            "sharded safetensors": f"{len({row['shard'] for row in r7a_census['tensors']})} official sharded",
            "terminal": committed["terminal"],
            "phase": f"stopped at Phase {committed['phase_stop'].split()[1]}",
            "stage-a bound": f"{stage_a['logical_required_bytes']:,}",
            "stage-b bound": f"{stage_b['logical_required_bytes']:,}",
            "stage-a tensors": f"{stage_a['tensor_count']:,}",
            "stage-b tensors": f"{stage_b['tensor_count']:,}",
            "stage-a shard count": f"| {len(stage_a['shards'])} |",
            "stage-b shard count": f"| {len(stage_b['shards'])} |",
            "changed paths": f"{audit['changed_path_count']:,}",
            "campaign gate paths": f"{audit['scope_counts']['campaign_gate_ordering_or_ci']} campaign-gate/CI paths",
            "vulkan paths": f"{audit['scope_counts']['vulkan_campaigns_and_hardware_inventory']:,} separate V340L Vulkan/hardware paths",
            "other paths": f"{audit['scope_counts']['other_docs_or_tests']} other documentation/test paths",
            "largest usable": f"{rejected['stage-a']['largest_compatible_usable_bytes']:,}",
            "stage-a deficit": f"{rejected['stage-a']['deficit_bytes']:,}",
            "stage-b deficit": f"{rejected['stage-b']['deficit_bytes']:,}",
            "aggregate": f"{committed['placement']['aggregate_compatible_usable_bytes']:,}",
        }
        for label, value in claims.items():
            with self.subTest(claim=label):
                self.assertGreater(len(value), 1, f"degenerate derived claim {label}")
                self.assertIn(value, flat, f"README does not state {label}={value}")
        for resource in fleet["resources"]:
            with self.subTest(resource=resource["resource_id"]):
                self.assertIn(resource["resource_id"], flat)
                self.assertIn(resource["name"], flat)
                self.assertIn(f"{resource['available_device_bytes']:,}", flat)
            # The exact table row, so a single-cell corruption cannot hide
            # behind the same figure appearing in the prose.
            foreign = ", ".join(f"PID {p['pid']} ({p['used_memory_mib']} MiB)"
                                for p in resource["foreign_processes"]) or "none"
            row = (f"| `{resource['resource_id']}` | {resource['name']} | "
                   f"{resource['available_device_bytes']:,} | {foreign} |")
            with self.subTest(row=resource["resource_id"]):
                self.assertIn(row, flat, f"README does not state the row: {row}")
        for process in [p for r in fleet["resources"] for p in r["foreign_processes"]]:
            with self.subTest(foreign_pid=process["pid"]):
                self.assertIn(process["pid"], flat)
                self.assertIn(f"({process['used_memory_mib']} MiB)", flat)
        if not fleet["unavailable_hosts"]:
            self.assertIn("`unavailable_hosts` is empty", flat)
        # No stale identity may hide in the prose: every 40-hex token the README
        # cites must be one of the retained identities. This is the check whose
        # absence let a stale generation head survive two rounds.
        known = {authority["repo_head"], r7b_terminal["predecessor"]["merge"],
                 r7c.R7B_MERGE, r7c.RECONCILED_MAIN,
                 authority["model"]["revision"], authority["runtime"]["revision"]}
        for token in re.findall(r"\b[0-9a-f]{40}\b", flat):
            with self.subTest(hex_token=token):
                self.assertIn(token, known,
                              f"README cites an identity that is not retained: {token}")
        # The superseded-observation paragraph cites specific commits; pin the
        # facts it attributes to them against those commits' retained censuses.
        blobs = {}
        for commit in ("1001c47", "cf391c1", "beb5d79", "1cd140e"):
            blob = subprocess.run(
                ["git", "-C", str(root), "show",
                 f"{commit}:{r7c.AREA}/fleet-census.json"],
                capture_output=True, text=True)
            self.assertEqual(blob.returncode, 0, blob.stderr)
            self.assertIn(commit, flat)
            blobs[commit] = json.loads(blob.stdout)
        superseded = blobs["1001c47"]
        self.assertEqual(superseded, blobs["cf391c1"])
        self.assertEqual(superseded, blobs["beb5d79"])
        self.assertEqual(superseded["unavailable_hosts"],
                         ["inferswarm02", "inferswarm04"])
        self.assertEqual(len(superseded["resources"]), 4)
        self.assertIn(f"{max(r['usable_device_bytes'] for r in superseded['resources']):,}", flat)
        self.assertIn(superseded["host_records"]["inferswarm01"]["collector_sha256"][:8], flat)
        later = blobs["1cd140e"]
        self.assertEqual(later["unavailable_hosts"], [])
        self.assertEqual(len(later["resources"]), len(fleet["resources"]))
        self.assertEqual(max(r["usable_device_bytes"] for r in later["resources"]),
                         rejected["stage-a"]["largest_compatible_usable_bytes"])
        # Attribution-level pins: a figure is also asserted inside the exact
        # phrase that attributes it, so a corrupted figure cannot hide behind a
        # duplicate occurrence elsewhere in the README.
        words = {4: "four", 6: "six"}
        superseded_largest = max(r["usable_device_bytes"] for r in superseded["resources"])
        sentences = [
            f"Corrected producer/authority head: `{authority['repo_head']}`",
            f"R7-A: merge `{r7b_terminal['predecessor']['merge']}`, terminal `{authority['r7a']['terminal']}`",
            f"R7-B: merge `{r7c.R7B_MERGE}`, terminal `{authority['r7b']['terminal']}`",
            f"Official subject: `{authority['model']['repository']}` at `{authority['model']['revision']}`; "
            f"{len({row['shard'] for row in r7a_census['tensors']})} official sharded safetensors, "
            "with no conversion authority",
            f"Runtime: vLLM `{authority['runtime']['revision']}`",
            f"Strategy: the accepted `{authority['strategy']['shape']}` subject with fixed cut "
            f"{authority['strategy']['cut_layer']}",
            f"stage A `[{authority['strategy']['stage_a_layers'][0]},{authority['strategy']['stage_a_layers'][1]})`, "
            f"stage B `[{authority['strategy']['stage_b_layers'][0]},{authority['strategy']['stage_b_layers'][1]})`",
            f"All {words[len(fleet['candidate_hosts'])]} hosts were reachable and returned "
            f"{words[len(fleet['resources'])]} GPU resources",
            f'`unavailable_hosts: ["{superseded["unavailable_hosts"][0]}", '
            f'"{superseded["unavailable_hosts"][1]}"]`, {words[len(superseded["resources"])]} resources, '
            f"and deficits computed against a {superseded_largest:,}-byte largest resource",
            "pre-hardening producer bytes (`collector_sha256` "
            f"`{superseded['host_records']['inferswarm01']['collector_sha256'][:8]}...`)",
            f"an all-reachable, {words[len(later['resources'])]}-resource census with the accepted "
            f"largest resource ({rejected['stage-a']['largest_compatible_usable_bytes']:,})",
            f"The largest single compatible usable resource is "
            f"{rejected['stage-a']['largest_compatible_usable_bytes']:,} bytes",
            f"leaving per-resource deficits of {rejected['stage-a']['deficit_bytes']:,} bytes for "
            f"stage A and {rejected['stage-b']['deficit_bytes']:,} bytes for stage B",
            "aggregate of the compatible, unoccupied resources "
            f"({committed['placement']['aggregate_compatible_usable_bytes']:,} bytes)",
            f"The reduction stopped at Phase {committed['phase_stop'].split()[1]}",
        ]
        for sentence in sentences:
            with self.subTest(sentence=sentence):
                self.assertIn(sentence, flat, f"README does not state: {sentence}")
        # The controls paragraph must keep quoting the message the reducer
        # actually raises, and must keep disclosing the no-anchor boundary.
        probe_authority = r7c.build_authority(ROOT, repo_head="f" * 40)
        probe_fleet = self._valid_fleet(probe_authority)
        probe_terminal = r7c.reduction_document(probe_authority, probe_fleet, now_unix=1000)
        tampered = copy.deepcopy(probe_terminal)
        tampered["placement"]["aggregate_compatible_usable_bytes"] += 1
        with self.assertRaises(ValueError) as caught:
            r7c.verify_committed_terminal(probe_authority, probe_fleet, tampered)
        self.assertIn(str(caught.exception).removeprefix("ISSUE222_FAIL: "), flat)
        self.assertIn("no out-of-band signing anchor", flat)
        self.assertIn("a terminal string is not acceptance", flat)

    def test_readme_sections_state_their_own_retained_values(self):
        """Section-scoped pins: a value must appear in the section that owns it.

        The sibling control asserts presence in the whole document, so a value
        that legitimately occurs twice can mask a corruption of one instance.
        This control pins each phrase inside its owning section - including the
        canonical terminal declaration, both contract-table rows, the superseded
        paragraph's candidate count, and the controls paragraph's corrected
        clause and disclosures.
        """
        root = Path(__file__).resolve().parents[1]
        area = root / r7c.AREA
        readme = (area / "README.md").read_text()
        sections, current = {}, "preamble"
        for line in readme.splitlines():
            if line.startswith("## "):
                current = line[3:].strip()
            sections.setdefault(current, []).append(line)
        sections = {name: " ".join(" ".join(lines).split())
                    for name, lines in sections.items()}
        authority = json.loads((area / "authority.json").read_text())
        fleet = json.loads((area / "fleet-census.json").read_text())
        committed = json.loads((area / "terminal-reduction.json").read_text())
        r7b_terminal = json.loads((root / r7c.R7B_TERMINAL).read_text())
        r7a_census = json.loads((root / r7c.R7A_CENSUS).read_text())
        audit = authority["mainline_applicability_audit"]
        rejected = committed["placement"]["rejected"]
        stage_a = authority["stage_footprints"]["stage-a"]
        stage_b = authority["stage_footprints"]["stage-b"]
        strategy = authority["strategy"]
        layers_a, layers_b = strategy["stage_a_layers"], strategy["stage_b_layers"]
        largest = rejected["stage-a"]["largest_compatible_usable_bytes"]
        words = {2: "two", 4: "four", 5: "five", 6: "six"}
        shard_count = len({row["shard"] for row in r7a_census["tensors"]})
        phase = committed["phase_stop"].split()[1]
        group = next(name for name, modules in plan_ci.GROUP_TEST_MODULES.items()
                     if "test_issue222_r7c" in modules)
        occupied_resources = [r for r in fleet["resources"] if r["foreign_processes"]]
        occupied_hosts = sorted({r["host"] for r in occupied_resources})
        biggest = max(fleet["resources"], key=lambda r: r["usable_device_bytes"])
        superseded_blob = subprocess.run(
            ["git", "-C", str(root), "show", f"1001c47:{r7c.AREA}/fleet-census.json"],
            capture_output=True, text=True)
        self.assertEqual(superseded_blob.returncode, 0, superseded_blob.stderr)
        superseded = json.loads(superseded_blob.stdout)
        old_largest = max(r["usable_device_bytes"] for r in superseded["resources"])
        previously_unavailable = superseded["unavailable_hosts"]
        old_collector = superseded["host_records"]["inferswarm01"]["collector_sha256"]
        model_name = authority["model"]["repository"].split("/", 1)[1].replace("-", " ")
        probe_authority = r7c.build_authority(ROOT, repo_head="f" * 40)
        probe_fleet = self._valid_fleet(probe_authority)
        probe_terminal = r7c.reduction_document(probe_authority, probe_fleet, now_unix=1000)
        tampered = copy.deepcopy(probe_terminal)
        tampered["placement"]["aggregate_compatible_usable_bytes"] += 1
        with self.assertRaises(ValueError) as caught:
            r7c.verify_committed_terminal(probe_authority, probe_fleet, tampered)
        rejection_message = str(caught.exception).removeprefix("ISSUE222_FAIL: ")

        expected = {
            "preamble": [f"# R7-C — {model_name} current-fleet physical feasibility"],
            "Authority": [
                f"Starting reconciled main: `{r7c.RECONCILED_MAIN}`",
                f"Corrected producer/authority head: `{authority['repo_head']}`",
                f"R7-A: merge `{r7b_terminal['predecessor']['merge']}`, terminal "
                f"`{authority['r7a']['terminal']}`",
                f"R7-B: merge `{r7c.R7B_MERGE}`, terminal `{authority['r7b']['terminal']}`",
                f"Official subject: `{authority['model']['repository']}` at "
                f"`{authority['model']['revision']}`; {shard_count} official sharded "
                "safetensors, with no conversion authority",
                f"Runtime: vLLM `{authority['runtime']['revision']}`",
                f"Strategy: the accepted `{strategy['shape']}` subject with fixed cut "
                f"{strategy['cut_layer']}: stage A `[{layers_a[0]},{layers_a[1]})`, "
                f"stage B `[{layers_b[0]},{layers_b[1]})`",
                f"classifies the {audit['changed_path_count']:,} changed paths",
                f"{audit['scope_counts']['campaign_gate_ordering_or_ci']} campaign-gate/CI paths, "
                f"{audit['scope_counts']['vulkan_campaigns_and_hardware_inventory']:,} separate "
                f"V340L Vulkan/hardware paths, and "
                f"{audit['scope_counts']['other_docs_or_tests']} other documentation/test paths",
                f"`git diff --name-only {r7c.R7B_MERGE}..{r7c.RECONCILED_MAIN}`",
                f"focused test in the `{group}` CI group",
            ],
            "Derived text-only stage contract": [
                f"| A `[{layers_a[0]},{layers_a[1]})` plus embeddings | "
                f"{stage_a['tensor_count']:,} | {len(stage_a['shards'])} | "
                f"{stage_a['logical_required_bytes']:,} bytes |",
                f"| B `[{layers_b[0]},{layers_b[1]})` plus norm/head | "
                f"{stage_b['tensor_count']:,} | {len(stage_b['shards'])} | "
                f"{stage_b['logical_required_bytes']:,} bytes |",
                f"because Phase {phase} stopped the campaign",
            ],
            "Fresh fleet census and legal placement": [
                f"run read-only on all {words[len(fleet['candidate_hosts'])]} current "
                "NVIDIA candidates",
                f"All {words[len(fleet['candidate_hosts'])]} hosts were reachable and "
                f"returned {words[len(fleet['resources'])]} GPU resources",
                "`unavailable_hosts` is empty",
                f"and `{previously_unavailable[0]}` and `{previously_unavailable[1]}` are "
                "present with full host records",
                f"The {words[len(occupied_resources)]} `{occupied_hosts[0]}` resources carry "
                "visible foreign compute processes",
                f"The largest single compatible usable resource is {largest:,} bytes "
                f"(`{biggest['resource_id']}`, the {biggest['name'].replace('NVIDIA GeForce ', '')})",
                f"leaving per-resource deficits of {rejected['stage-a']['deficit_bytes']:,} bytes "
                f"for stage A and {rejected['stage-b']['deficit_bytes']:,} bytes for stage B",
                "aggregate of the compatible, unoccupied resources "
                f"({committed['placement']['aggregate_compatible_usable_bytes']:,} bytes)",
            ],
            "Terminal": [
                f"`{committed['terminal']}`",
                f"The reduction stopped at Phase {phase}.",
                # An authored disclosure (not a derived value): pinning its
                # presence is what stops it being silently reworded into its
                # own negation.
                "No official checkpoint body bytes were acquired; no model runtime "
                "initialized; no tensor sentinel, full-model forward pass, benchmark, "
                "serving run, AMD/Vulkan path, or alternate placement mechanism was executed.",
            ],
            "Superseded observation": [
                f'`unavailable_hosts: ["{previously_unavailable[0]}", '
                f'"{previously_unavailable[1]}"]`, {words[len(superseded["resources"])]} resources, '
                f"and deficits computed against a {old_largest:,}-byte largest resource",
                f"pre-hardening producer bytes (`collector_sha256` `{old_collector[:8]}...`)",
                f"first by the re-observation committed at `1cd140e`, which already carried an "
                f"all-reachable, {words[len(fleet['resources'])]}-resource census with the "
                f"accepted largest resource ({largest:,})",
                f"proved only that the {words[len(superseded['resources'])]} candidates were "
                f"probed and that {words[len(previously_unavailable)]} of them did not answer "
                "at that time",
            ],
            "Controls and scope": [
                "the retained terminal *document* is not reachable through it",
                rejection_message,
                "no out-of-band signing anchor",
                "a terminal string is not acceptance",
            ],
        }
        self.assertEqual(sorted(sections), sorted(expected))
        for name, phrases in expected.items():
            for phrase in phrases:
                with self.subTest(section=name, phrase=phrase):
                    self.assertIn(phrase, sections[name],
                                  f"section {name!r} does not state: {phrase}")
        for commit in ("1001c47", "cf391c1", "beb5d79", "1cd140e"):
            with self.subTest(superseded_commit=commit):
                self.assertIn(commit, sections["Superseded observation"])

    def test_missing_raw_receipt_and_unknown_device_row_fail_closed(self):
        """The two receipt-surface claims the README's control list makes."""
        authority = r7c.build_authority(ROOT, repo_head="f" * 40)
        fleet = self._valid_fleet(authority)

        missing = copy.deepcopy(fleet)
        del missing["host_records"]["inferswarm01"]["receipts"]["nvidia_smi_apps"]
        with self.assertRaisesRegex(ValueError, "raw receipt absent"):
            r7c.reduction_document(authority, missing, now_unix=1000)

        unknown = copy.deepcopy(fleet)
        record = unknown["host_records"]["inferswarm01"]
        record["receipts"]["nvidia_smi_apps"] = self._receipt(
            ["nvidia-smi", "--query-compute-apps=pid,gpu_uuid,used_memory",
             "--format=csv,noheader,nounits"],
            "4242, GPU-not-in-the-gpu-receipt, 512\n")
        with self.assertRaisesRegex(ValueError, "names unknown GPU"):
            r7c.reduction_document(authority, unknown, now_unix=1000)


if __name__ == "__main__":
    unittest.main()
