#!/usr/bin/env python3
"""Issue #216 — V2-D prospective concurrent V340L campaign plan.

This pure stdlib producer freezes the bounded concurrent-dual-die experiment
before any retained physical result.  It performs no host action.  The plan
binds the runtime subject, participant assignments, synchronized workload,
transport shapes, soak cadence, process-fault arms, terminal reducer, and
nonclaims.  Device reset is deliberately conditional: unsupported mechanisms
must reduce to DEVICE_RESET_ISOLATION_NOT_AVAILABLE rather than being probed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs" / "investigations" / "vulkan-v2-d-v340l-concurrent"
CAMPAIGN_ID = "issue216-v2d-v340l-concurrent-dual-die-v1"
STARTING_MAIN = "605d0b465dc2bd015a7c832c67f4adcd7aefeb61"

RUNTIME = {
    "executable": "/home/hermes/v0a/llama.cpp/build-vulkan/bin/llama-cli",
    "executable_sha256": "c4bcd6a94e0b7fdb1959e6542ce0f85bb905c6c9083fcd1a7b6b0daf15e2c9be",
    "source_commit": "8ea290247c87ced2ab245b056ffe96dbcf90d36c",
    "model": "/home/hermes/v0a/models/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
    "model_sha256": "9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94",
    "reference": "docs/investigations/vulkan-v1-a/reference-visible-output.txt",
    "reference_sha256": "9013db8fb38982f9085754e69fa3feb2f74c7372360da686fe90a3444f26182d",
    "comparator": "scripts/v0c_correctness.py",
    "accounting_reducer": "scripts/v1c_accounting.py",
}

TERMINALS = {
    "pass": "V2D_V340L_CONCURRENT_DUAL_DIE_STABILITY_PASS",
    "correctness_fail": "V2D_V340L_CONCURRENT_CORRECTNESS_FAIL",
    "stress_fail": "V2D_V340L_PLATFORM_STRESS_FAIL",
    "blocked": "V2D_EVIDENCE_BLOCKED",
}


def build_plan() -> dict:
    return {
        "schema": "inferswarm.v2d.campaign-plan/1",
        "campaign_id": CAMPAIGN_ID,
        "issue": 216,
        "starting_main": STARTING_MAIN,
        "host": "inferswarm02",
        "accepted_predecessors": {
            "v2a_merge": "e38ebe91a0604fb666397ddae675248e9f819f60",
            "v2a_terminal": "V2A_REUSABLE_DEVICE_QUALIFICATION_HARNESS_PASS",
            "v2b_merge": "f91119d05e7079c780c7b88be6138fed0920b759",
            "v2b_terminal": "V2B_V340L_DUAL_DIE_QUALIFICATION_PASS",
            "v2c_merge": STARTING_MAIN,
            "v2c_terminal": "V2C_V340L_PLATFORM_STABILITY_PASS",
            "x1_merge": "8aadbd6ea3c635741cc67fcc9d9ba1d1dd8d500a",
            "x1_terminal": "X1_MINIMUM_VIABLE_PARTICIPANT_ENVELOPE_ESTABLISHED",
        },
        "runtime": RUNTIME,
        "physical_resources": {
            "a": {"selector": "Vulkan1", "expected_bdf": "06:00.0",
                  "compute_unit_id": "cu-v340l-die-a", "memory_resource_id": "mr-v340l-die-a-vram",
                  "vram_bytes": 8573157376},
            "b": {"selector": "Vulkan2", "expected_bdf": "09:00.0",
                  "compute_unit_id": "cu-v340l-die-b", "memory_resource_id": "mr-v340l-die-b-vram",
                  "vram_bytes": 8573157376},
            "shared_upstream": {"root_port": "00:1d.0", "switch_upstream": "02:00.0",
                                "required_negotiated": "Gen3 x1", "switch": "PM8533"},
        },
        "preflight": {
            "required": ["host_kernel_amdgpu_icd_runtime", "full_pci_topology_and_bars",
                         "under_load_link_state", "fresh_two_die_binding", "hbm_cu_ecc_sriov",
                         "v2c_platform_peripheral_health", "clean_preload_aer_amdgpu_journal"],
            "sentinel_repetitions_per_die": 1,
        },
        "baselines": {"repetitions_per_die": 3, "workload": "v2-compatible-8-token-sentinel",
                      "telemetry": ["service_time", "utilization", "hbm", "clocks", "temperature",
                                    "power", "fan", "ecc_ras", "aer_amdgpu", "link_state"]},
        "concurrent": {
            "retained_repetitions": 3,
            "warmups": 1,
            "participants": {"a": "Vulkan1", "b": "Vulkan2"},
            "synchronization": "same-host start-gate file; both child receipts record monotonic start/end",
            "overlap_requirement": "strict positive monotonic interval intersection for every retained repeat",
            "workload": "v2-compatible-8-token-sentinel",
            "required": ["byte_exact", "full_offload", "zero_accounting", "clean_exit",
                         "no_nan_inf", "per_die_attribution", "no_cross_substitution"],
        },
        "transport": {
            "modes": ["single-a", "single-b", "dual"],
            "directions": ["h2d", "d2h"],
            "sizes_bytes": [4194304, 67108864, 536870912],
            "latency_size_bytes": 4096,
            "repetitions": 5,
            "uncertainty": "sample_count,min,max,median,mean",
            "tool": "issue216_transport.py Vulkan transfer benchmark",
            "link_capture": "before-and-after full root/switch/endpoint lspci -PP -nn -vv",
        },
        "soak": {
            "minimum_duration_seconds": 3600,
            "telemetry_cadence_seconds": 60,
            "sentinel_checkpoint_seconds": 600,
            "workload": "paired bounded V2-compatible sentinel loop",
            "continuous_liveness_required": True,
            "stop_conditions": ["worker_crash_or_hang", "amdgpu_reset_or_hang", "fatal_aer",
                                "uncorrected_ecc_ras_growth", "thermal_alarm_or_shutdown",
                                "host_or_required_peripheral_failure", "sentinel_failure"],
        },
        "fault_isolation": {
            "arms": ["a-loss-b-survives", "b-loss-a-survives"],
            "termination": "SIGTERM; verify exit; SIGKILL only after frozen 30-second grace",
            "required": ["survivor_keeps_original_selector_bdf", "survivor_no_fallback",
                         "relaunch_lost_participant", "per_die_resentinel", "final_concurrent_sentinel"],
        },
        "device_reset": {
            "require_documented_supported_mechanism": True,
            "unsupported_terminal": "DEVICE_RESET_ISOLATION_NOT_AVAILABLE",
            "prohibited": ["pci_remove_rescan", "bus_reset", "undocumented_sysfs_reset", "power_state_hack"],
        },
        "terminals": TERMINALS,
        "nonclaims": [
            "no aggregate/coherent 16 GiB single-address-space V340L memory",
            "no Qwen3.8 or DeepSeek V4.1 model-program qualification",
            "no mixed AMD/NVIDIA execution", "no SR-IOV VF support", "no ROCm/HIP support",
            "no generic planner scoring or automatic placement policy", "no production service or HA claim",
        ],
        "validation_order": "Issue #213: focused/preservation/reducer/finalizer before review; one full suite and one hosted CI only on final reviewed head",
    }


def plan_document() -> dict:
    plan = build_plan()
    payload = json.dumps(plan, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"campaign_plan": plan, "campaign_plan_digest": hashlib.sha256(payload).hexdigest()}


def main() -> int:
    AREA.mkdir(parents=True, exist_ok=True)
    (AREA / "CAMPAIGN-PLAN.json").write_text(
        json.dumps(plan_document(), indent=1, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(plan_document()["campaign_plan_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
