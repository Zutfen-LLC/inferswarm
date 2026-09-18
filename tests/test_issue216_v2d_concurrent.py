#!/usr/bin/env python3
"""Issue #216 — V2-D concurrent V340L campaign contract tests.

The campaign is prospective: these tests exercise only frozen-plan and
sandbox-reducer semantics. They never contact a GPU host or mutate accepted
predecessor evidence.
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import issue216_campaign_plan as plan_mod  # noqa: E402
import issue216_terminal as terminal_mod  # noqa: E402
import issue216_concurrent as concurrent_mod  # noqa: E402


def valid_record() -> dict:
    clean = {"unexplained_persistent_host_mirror_bytes": 0,
             "source_fetches_after_ready": 0, "unplanned_state_movements": 0}
    participant = lambda die, selector, bdf: {
        "die": die, "selector": selector, "bdf": bdf, "result": "PASS",
        "full_offload": True, "byte_exact": True, "clean_exit": True,
        "finite_output": True, "fallback": False, "accounting": dict(clean),
    }
    return {
        "preflight": {"result": "PASS", "predecessors_preserved": True,
                      "two_distinct_dies": True, "gen3_x1_topology": True},
        "baselines": {"a": [participant("a", "Vulkan1", "06:00.0")] * 3,
                      "b": [participant("b", "Vulkan2", "09:00.0")] * 3},
        "concurrent": [{"id": f"repeat-{i}", "status": "PASS", "participants": {
            "a": participant("a", "Vulkan1", "06:00.0"),
            "b": participant("b", "Vulkan2", "09:00.0")},
            "intervals_ns": {"a": [0, 100], "b": [1, 101]}} for i in range(1, 4)],
        "transport": {"modes": ["single-a", "single-b", "dual"],
                      "directions": ["h2d", "d2h"], "all_required_sizes_present": True,
                      "uncertainty_present": True, "under_load_link_state": True},
        "soak": {"duration_seconds": 3600, "telemetry_cadence_seconds": 60,
                 "telemetry_samples": 61, "continuous_liveness": True,
                 "fatal_aer": False, "amdgpu_fault": False, "uncorrected_ecc_ras_growth": False,
                 "thermal_alarm": False, "host_peripheral_failure": False,
                 "silent_restart": False, "sentinels": ["PASS"] * 7},
        "fault_isolation": {"a-loss-b-survives": "PASS", "b-loss-a-survives": "PASS",
                            "final_concurrent_sentinel": "PASS"},
        "device_reset": {"result": "DEVICE_RESET_ISOLATION_NOT_AVAILABLE"},
        "claim_scope": {"aggregate_16gib": False, "model_program": False,
                        "planner_policy": False, "slowdown_is_correctness_failure": False},
    }


class CampaignPlanTests(unittest.TestCase):
    def test_plan_freezes_required_concurrent_scope(self):
        plan = plan_mod.build_plan()
        self.assertEqual(plan["campaign_id"], "issue216-v2d-v340l-concurrent-dual-die-v1")
        self.assertEqual(plan["starting_main"], "605d0b465dc2bd015a7c832c67f4adcd7aefeb61")
        self.assertEqual(plan["accepted_predecessors"]["v2c_merge"],
                         "605d0b465dc2bd015a7c832c67f4adcd7aefeb61")
        self.assertEqual(plan["concurrent"]["retained_repetitions"], 3)
        self.assertEqual(plan["soak"]["minimum_duration_seconds"], 3600)
        self.assertEqual(plan["soak"]["telemetry_cadence_seconds"], 60)
        self.assertEqual(plan["soak"]["sentinel_checkpoint_seconds"], 600)
        self.assertEqual(plan["device_reset"]["unsupported_terminal"],
                         "DEVICE_RESET_ISOLATION_NOT_AVAILABLE")
        self.assertEqual(plan["terminals"]["pass"],
                         "V2D_V340L_CONCURRENT_DUAL_DIE_STABILITY_PASS")
        self.assertIn("no aggregate/coherent 16 GiB single-address-space V340L memory",
                      plan["nonclaims"])

    def test_plan_digest_is_canonical_and_binds_every_frozen_field(self):
        plan = plan_mod.build_plan()
        payload = json.dumps(plan, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()
        self.assertEqual(plan_mod.plan_document()["campaign_plan_digest"],
                         hashlib.sha256(payload).hexdigest())
        self.assertEqual(plan["transport"]["modes"], ["single-a", "single-b", "dual"])
        self.assertEqual(plan["fault_isolation"]["arms"],
                         ["a-loss-b-survives", "b-loss-a-survives"])


class ConcurrentCollectorContractTests(unittest.TestCase):
    def test_repository_default_is_local_script_root(self):
        self.assertEqual(concurrent_mod.DEFAULT_REPO, concurrent_mod.SCRIPT_DIR.parent)


class TerminalReducerTests(unittest.TestCase):
    def test_complete_record_derives_exact_pass_terminal(self):
        reduced = terminal_mod.reduce_record(valid_record(), plan_mod.build_plan())
        self.assertEqual(reduced["terminal"], "V2D_V340L_CONCURRENT_DUAL_DIE_STABILITY_PASS")
        self.assertTrue(reduced["checks"]["concurrent_repetitions"])

    def test_same_die_no_overlap_fallback_accounting_and_soak_fault_fail_closed(self):
        mutations = {
            "same-die": lambda r: r["concurrent"][0]["participants"]["b"].__setitem__("bdf", "06:00.0"),
            "no-overlap": lambda r: r["concurrent"][0].__setitem__("intervals_ns", {"a": [0, 10], "b": [10, 20]}),
            "fallback": lambda r: r["concurrent"][0]["participants"]["b"].__setitem__("fallback", True),
            "accounting": lambda r: r["concurrent"][0]["participants"]["a"]["accounting"].__setitem__("source_fetches_after_ready", 1),
            "transport": lambda r: r["transport"].__setitem__("modes", ["single-a", "single-b"]),
            "telemetry-gap": lambda r: r["soak"].__setitem__("telemetry_samples", 2),
            "fatal-aer": lambda r: r["soak"].__setitem__("fatal_aer", True),
            "hidden-restart": lambda r: r["soak"].__setitem__("silent_restart", True),
            "isolation": lambda r: r["fault_isolation"].__setitem__("a-loss-b-survives", "FAIL"),
            "aggregate-claim": lambda r: r["claim_scope"].__setitem__("aggregate_16gib", True),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                record = valid_record()
                mutate(record)
                self.assertNotEqual(terminal_mod.reduce_record(record, plan_mod.build_plan())["terminal"],
                                    "V2D_V340L_CONCURRENT_DUAL_DIE_STABILITY_PASS")


if __name__ == "__main__":
    unittest.main()
