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

# Runtime/model and selector/BDF facts are intentionally NOT repeated here.
# `issue216_physical_authority.py` derives those immutable identities from the
# accepted V2-B and V2-C authority bytes, then a fresh mapping receipt binds
# execution-time selectors to those intended physical devices.
RUNTIME_AUTHORITY = {
    "physical_authority_path": "docs/investigations/vulkan-v2-d-v340l-concurrent/PHYSICAL-AUTHORITY.json",
    "physical_authority_schema": "inferswarm.v2d.physical-authority/1",
    "comparator": "scripts/v0c_correctness.py",
    "accounting_reducer": "scripts/v1c_accounting.py",
}

TERMINALS = {
    "pass": "V2D_V340L_CONCURRENT_DUAL_DIE_STABILITY_PASS",
    "correctness_fail": "V2D_V340L_CONCURRENT_CORRECTNESS_FAIL",
    "stress_fail": "V2D_V340L_PLATFORM_STRESS_FAIL",
    "blocked": "V2D_EVIDENCE_BLOCKED",
    # Prospective taxonomy correction: lack/corruption of a later mandatory
    # receipt is not affirmative platform failure and cannot erase an observed
    # concurrent result by relabeling it BLOCKED.
    "post_concurrency_incomplete": "V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY",
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
        "runtime_authority": RUNTIME_AUTHORITY,
        "physical_resources": {
            # Roles and immutable CU/MR identities only. Current selector/BDF
            # mappings are execution-time observations in FRESH-PHYSICAL-MAPPING.
            "a": {"compute_unit_id": "cu-v340l-die-a", "memory_resource_id": "mr-v340l-die-a-vram",
                  "vram_bytes": 8573157376},
            "b": {"compute_unit_id": "cu-v340l-die-b", "memory_resource_id": "mr-v340l-die-b-vram",
                  "vram_bytes": 8573157376},
            "shared_upstream": {"required_negotiated": "Gen3 x1", "switch": "PM8533",
                                "topology_assignment": "fresh preflight only"},
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
            "participants": "derived exclusively from fresh physical-authority mapping receipt",
            "synchronization": "same-host start gate plus retained per-die workload-activity interval; wrapper lifetime alone is insufficient",
            "overlap_requirement": "strict positive monotonic intersection of per-die correctness-bearing workload activity intervals",
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
        "producer_contract": {
            "raw_receipt_schemas": [
                "inferswarm.v2d.physical-authority/1",
                "inferswarm.v2d.fresh-physical-mapping/1",
                "inferswarm.v2d.preflight-receipt/1",
                "inferswarm.v2d.execution-attempt/1",
                "inferswarm.v2d.participant-receipt/1",
                "inferswarm.v2d.concurrent-attempt/1",
                "inferswarm.v2d.transport-sample/1",
                "inferswarm.v2d.transport-run/1",
                "inferswarm.v2d.transport-reduction/1",
                "inferswarm.v2d.soak-telemetry/1",
                "inferswarm.v2d.soak-checkpoint/1",
                "inferswarm.v2d.soak-run/1",
                "inferswarm.v2d.fault-isolation/1",
                "inferswarm.v2d.reset-disposition/1",
                "inferswarm.v2d.campaign-assembly/2",
                "inferswarm.v2d.terminal-reduction/3",
            ],
            "required_producers": [
                "scripts/issue216_physical_authority.py", "scripts/issue216_preflight.py",
                "scripts/issue216_concurrent.py", "scripts/issue216_transport.py",
                "scripts/issue216_soak.py", "scripts/issue216_fault_isolation.py",
                "scripts/issue216_reset.py", "scripts/issue216_assemble.py",
                "scripts/issue216_terminal.py", "scripts/issue216_manifest.py",
            ],
            "receipt_binding_required": ["campaign_id", "attempt_id", "producer_path_sha256",
                "repo_head", "host", "boot_id", "authority_digest", "fresh_mapping_digest",
                "runtime_binary_sha256", "model_sha256", "selector_bdf_physical_identity",
                "argv", "raw_paths_sha256", "source_receipt_identities"],
        },
        "validation_order": "Issue #213: focused/preservation/manifest/terminal/finalizer/status/CI-planner before review; one full suite and one hosted CI only on final reviewed head",
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
