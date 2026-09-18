#!/usr/bin/env python3
"""Issue #216 fixture-only raw-receipt -> assembler -> reducer controls."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import issue216_assemble as assemble  # noqa: E402
import issue216_campaign_plan as plan  # noqa: E402
import issue216_physical_authority as authority  # noqa: E402
import issue216_terminal as terminal  # noqa: E402

AUTH = "a" * 64
PRODUCER = "b" * 64


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FixtureCampaign:
    """Synthetic, expressly non-physical tree with production receipt topology."""
    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="issue216-FIXTURE-NOT-PHYSICAL-"))
        (self.root / "FIXTURE-NOT-PHYSICAL").write_text("Synthetic schema fixture; never V340L evidence.\n")
        self.rows: dict[str, Path] = {}
        self.participants = {
            "a": {"selector": "Fresh-A", "bdf": "11:00.0", "physical_id": "fixture-die-a", "compute_unit_id": "fixture-cu-a", "memory_resource_id": "fixture-mr-a", "hbm_bytes": 8 * 1024**3},
            "b": {"selector": "Fresh-B", "bdf": "12:00.0", "physical_id": "fixture-die-b", "compute_unit_id": "fixture-cu-b", "memory_resource_id": "fixture-mr-b", "hbm_bytes": 8 * 1024**3},
        }
        self.mapping_digest = digest(assemble.canonical({"participants": self.participants}))
        self.build()

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def common(self, schema: str, receipt_id: str, attempt_id: str) -> dict:
        raw_rel = f"evidence/raw/{receipt_id}.raw"
        raw = ("raw:" + receipt_id).encode()
        raw_path = self.root / raw_rel
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw)
        return {"schema": schema, "campaign_id": assemble.FIXTURE_ID, "fixture": True,
                "receipt_id": receipt_id, "producer_path": "scripts/fixture-producer.py", "producer_sha256": PRODUCER,
                "repo_head": "fixture-head", "host": "fixture-host", "boot_id": "fixture-boot", "attempt_id": attempt_id,
                "authority_digest": AUTH, "fresh_mapping_digest": self.mapping_digest, "raw": {raw_rel: digest(raw)}}

    def write(self, key: str, schema: str, attempt: str, **extra: object) -> None:
        row = self.common(schema, key, attempt); row.update(extra)
        path = self.root / "evidence" / "receipts" / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(row, sort_keys=True) + "\n")
        self.rows[key] = path

    def load(self, key: str) -> dict:
        return json.loads(self.rows[key].read_text())

    def save(self, key: str, row: dict) -> None:
        self.rows[key].write_text(json.dumps(row, sort_keys=True) + "\n")

    def mutate(self, key: str, fn) -> None:
        row = self.load(key); fn(row); self.save(key, row)

    def build(self) -> None:
        self.write("fresh-map", "inferswarm.v2d.fresh-physical-mapping/1", "preflight-1", participants=self.participants, mapping_digest=self.mapping_digest)
        self.write("preflight", "inferswarm.v2d.preflight-receipt/1", "preflight-1",
                   accepted_predecessors={"v2b": "accepted-v2b", "v2c": "accepted-v2c", "x1": "accepted-35"},
                   topology={"root_port": "rp", "switch_upstream": "pm8533-up", "endpoint_a": "epa", "endpoint_b": "epb", "negotiated": "Gen3 x1"}, preexisting_fault=False)
        for die in ("a", "b"):
            for rep in range(1, 4):
                self.write(f"baseline-{die}-{rep}", "inferswarm.v2d.execution-attempt/1", f"baseline-{die}-{rep}", die=die, runtime="fixture-runtime", model="fixture-model", argv=["fixture"], clean_exit=True, correctness=True, offload=True, fallback=False, accounting=[0, 0, 0])
        for rep in range(1, 4):
            pair = {die: {"participant_receipt": f"baseline-{die}-{rep}", "die": die, "physical_id": self.participants[die]["physical_id"], "correctness": True, "offload": True, "fallback": False, "accounting": [0, 0, 0], "clean_exit": True} for die in ("a", "b")}
            self.write(f"concurrent-{rep}", "inferswarm.v2d.concurrent-attempt/1", f"concurrent-{rep}", participants=pair, workload_intervals_ns={"a": [1000, 2000], "b": [1500, 2500]})
        for mode in ("single-a", "single-b", "dual"):
            people = ("a", "b") if mode == "dual" else (("a",) if mode == "single-a" else ("b",))
            for direction in ("h2d", "d2h"):
                for size in (4096, 4 * 1024**2, 64 * 1024**2, 512 * 1024**2):
                    for rep in range(1, 6):
                        for person in people:
                            key = f"transport-{mode}-{direction}-{size}-{rep}-{person}"
                            self.write(key, "inferswarm.v2d.transport-sample/1", "transport-1", mode=mode, direction=direction, size_bytes=size, repetition=rep, participant=person, bytes_transferred=size, measured_value=1.0, interval_ns=[100, 200], dual_workload_overlap=(mode == "dual"))
        for seq in range(1, 62):
            self.write(f"telemetry-{seq}", "inferswarm.v2d.soak-telemetry/1", "soak-1", sequence=seq, monotonic_ns=seq * 60 * 1_000_000_000, amdgpu_reset=False, fatal_aer=False, uncorrected_ecc_growth=False, worker_restarted=False)
        for second in (0, 600, 1200, 1800, 2400, 3000, 3600):
            self.write(f"checkpoint-{second}", "inferswarm.v2d.soak-checkpoint/1", "soak-1", checkpoint_seconds=second, correctness=True)
        self.write("soak-run", "inferswarm.v2d.soak-run/1", "soak-1", started_monotonic_ns=0, ended_monotonic_ns=3600 * 1_000_000_000, telemetry_cadence_seconds=60, allowed_scheduling_tolerance_seconds=15, raw_stress_events=[], final_sentinel_correct=True)
        for arm, survivor in (("a-loss-b-survives", "b"), ("b-loss-a-survives", "a")):
            self.write(f"fault-{arm}", "inferswarm.v2d.fault-isolation/1", arm, arm=arm, pre_health=True, target_exited=True, survivor_same_pid=True, survivor_original_die=True, survivor_no_fallback=True, survivor_correctness=True, relaunch_fresh_rebind=True, per_die_recovery=True, final_concurrent_sentinel=True, survivor=survivor)
        self.write("reset", "inferswarm.v2d.reset-disposition/1", "reset-1", disposition="DEVICE_RESET_ISOLATION_NOT_AVAILABLE", documented_support_absent=True)

    def reduce(self) -> dict:
        return terminal.reduce_tree(self.root, AUTH, fixture=True)


class FixturePathTests(unittest.TestCase):
    def test_positive_fixture_traverses_raw_assembly_reducer_to_pass(self):
        f = FixtureCampaign(); self.addCleanup(f.close)
        result = f.reduce()
        self.assertTrue(result["fixture"])
        self.assertEqual(result["terminal"], plan.build_plan()["terminals"]["pass"])
        self.assertTrue(result["facts"]["transport_matrix_complete"])

    def test_all_twenty_controls_mutate_primary_receipts_and_run_real_path(self):
        terms = plan.build_plan()["terminals"]
        controls = {
            1: (lambda f: f.mutate("preflight", lambda r: r["accepted_predecessors"].update(v2b="superseded")), "reject"),
            2: (lambda f: f.mutate("preflight", lambda r: r["accepted_predecessors"].update(v2c="mutated")), "reject"),
            3: (lambda f: f.mutate("fresh-map", lambda r: r["participants"]["a"].update(bdf="stale")), "reject"),
            4: (lambda f: f.mutate("fresh-map", lambda r: r["participants"]["b"].update(physical_id="fixture-die-a")), "reject"),
            5: (lambda f: f.mutate("concurrent-1", lambda r: r.update(workload_intervals_ns={"a": [1, 2], "b": [2, 3]})), "reject"),
            6: (lambda f: f.mutate("concurrent-1", lambda r: r["participants"]["b"].update(physical_id="fixture-die-a")), "reject"),
            7: (lambda f: f.mutate("concurrent-1", lambda r: r["participants"]["a"].update(fallback=True)), terms["correctness_fail"]),
            8: (lambda f: f.mutate("concurrent-1", lambda r: r["participants"]["a"].update(accounting=[1, 0, 0])), terms["correctness_fail"]),
            9: (lambda f: f.mutate("preflight", lambda r: r["topology"].update(negotiated="Gen4 x16")), "reject"),
            10: (lambda f: f.mutate("transport-dual-h2d-4096-1-a", lambda r: r.update(mode="single-a")), "reject"),
            11: (lambda f: f.rows["concurrent-2"].unlink(), terms["post_concurrency_incomplete"]),
            12: (lambda f: f.mutate("telemetry-31", lambda r: r.update(monotonic_ns=30 * 60 * 1_000_000_000)), terms["post_concurrency_incomplete"]),
            13: (lambda f: f.mutate("telemetry-31", lambda r: r.update(amdgpu_reset=True)), terms["stress_fail"]),
            14: (lambda f: f.mutate("telemetry-31", lambda r: r.update(uncorrected_ecc_growth=True)), terms["stress_fail"]),
            15: (lambda f: f.mutate("telemetry-31", lambda r: r.update(worker_restarted=True)), terms["stress_fail"]),
            16: (lambda f: f.mutate("fault-a-loss-b-survives", lambda r: r.update(survivor_original_die=False)), terms["post_concurrency_incomplete"]),
            17: (lambda f: f.mutate("reset", lambda r: r.update(disposition="RESET_EXECUTED", documented_support_absent=False)), terms["post_concurrency_incomplete"]),
            18: (lambda f: f.mutate("transport-dual-h2d-4096-1-a", lambda r: r.update(measured_value=0.001)), terms["pass"]),
            19: (lambda f: f.mutate("fresh-map", lambda r: r.update(aggregate_memory_bytes=16 * 1024**3)), "reject"),
            20: (lambda f: f.mutate("preflight", lambda r: r.update(model_program_result="forbidden")), "reject"),
        }
        self.assertEqual(set(controls), set(range(1, 21)))
        for control, (mutation, expected) in controls.items():
            with self.subTest(control=control):
                f = FixtureCampaign(); self.addCleanup(f.close); mutation(f)
                if expected == "reject":
                    with self.assertRaises(assemble.AssemblyError):
                        f.reduce()
                else:
                    self.assertEqual(f.reduce()["terminal"], expected)

    def test_same_byte_symlink_and_hardlink_aliases_fail_closed(self):
        f = FixtureCampaign(); self.addCleanup(f.close)
        target = f.rows["preflight"]
        copied = target.with_name("copy.json"); copied.write_bytes(target.read_bytes())
        target.unlink(); target.symlink_to(copied.name)
        with self.assertRaises(assemble.AssemblyError): f.reduce()
        f = FixtureCampaign(); self.addCleanup(f.close)
        target = f.rows["preflight"]; alias = target.with_name("alias.json"); alias.hardlink_to(target)
        with self.assertRaises(assemble.AssemblyError): f.reduce()


class AuthorityAndPreexecutionTests(unittest.TestCase):
    def test_accepted_authority_is_byte_verified_and_plan_has_no_runtime_bdf_selector(self):
        doc = authority.build_authority(REPO)
        self.assertTrue(authority.verify_authority(doc, REPO))
        p = plan.build_plan()
        self.assertNotIn("selector", p["physical_resources"]["a"])
        self.assertNotIn("expected_bdf", p["physical_resources"]["a"])

    def test_repository_preexecution_namespace_contains_no_physical_receipts(self):
        assemble.assert_preexecution_namespace_clean(REPO)

    def test_taxonomy_is_exact_five_values(self):
        values = set(plan.build_plan()["terminals"].values())
        self.assertEqual(values, {"V2D_V340L_CONCURRENT_DUAL_DIE_STABILITY_PASS", "V2D_V340L_CONCURRENT_CORRECTNESS_FAIL", "V2D_V340L_PLATFORM_STRESS_FAIL", "V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY", "V2D_EVIDENCE_BLOCKED"})

if __name__ == "__main__":
    unittest.main()
