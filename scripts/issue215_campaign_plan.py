#!/usr/bin/env python3
"""Issue #215 — V2-C prospectively frozen campaign plan (freeze BEFORE the
first retained reboot).

Pure data: this module AUTHORS the frozen reboot sequence, minimum cycle
counts, per-cycle probes, failure predicates, post-boot sentinels, and the
terminal-reducer contract as a machine-readable document with a stable
digest. It executes nothing. The reducer (issue215_terminal.py) re-derives
every terminal predicate from retained cycle artifacts; the campaign plan
digest binds them.

Campaign identity
-----------------
campaign_id: issue215-v2c-v340l-platform-stability-v1
namespace:    docs/investigations/vulkan-v2-c-v340l-platform-stability/
host:         inferswarm02 (physical, current stabilized arrangement)

The campaign does NOT authorize any slot move, BIOS experiment, dual-die
concurrent stress, model program, SR-IOV, ROCm/HIP, or planner policy.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NS = "vulkan-v2-c-v340l-platform-stability"
AREA = ROOT / "docs" / "investigations" / NS

CAMPAIGN_ID = "issue215-v2c-v340l-platform-stability-v1"

# Frozen upstream identities (Phase 0 reconciliation, verified 2026-09-17).
STARTING_MAIN = "36d0d7a7301230512dbbc2bca65388b6800dec6f"
ACCEPTED_V2B_MERGE = "f91119d05e7079c780c7b88be6138fed0920b759"
ACCEPTED_V2A_MERGE = "e38ebe91a0604fb666397ddae675248e9f819f60"
ACCEPTED_V2B_TERMINAL = "V2B_V340L_DUAL_DIE_QUALIFICATION_PASS"
ACCEPTED_V2A_TERMINAL = "V2A_REUSABLE_DEVICE_QUALIFICATION_HARNESS_PASS"

# Physical subject identity (from the accepted V2-B campaign; re-verified
# mechanically against live host state in Phase 1 pre-reboot baseline).
RUNTIME_EXECUTABLE = "/home/zutfen/.cache/v0c-llama.cpp/build-v0c-vulkan/bin/llama-cli"
RUNTIME_EXECUTABLE_SHA256 = "5a8f5edec3cafce77e371b082f4dd52f07d38a72704a652063f6255a018c36ec"
RUNTIME_SOURCE = "/home/zutfen/.cache/v0c-llama.cpp"
RUNTIME_SOURCE_COMMIT = "8ea290247c87ced2ab245b056ffe96dbcf90d36c"
MODEL = "/home/zutfen/.cache/v0c-models/Qwen2.5-3B-Instruct-Q4_K_M.gguf"
MODEL_SHA256 = "9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94"
MODEL_BYTES = 1929903264

VEGA_DIE_IDS = {
    "a": {"vendor_device": "1002:6864", "compute_unit_id": "cu-v340l-die-a",
          "memory_resource_id": "mr-v340l-die-a-vram"},
    "b": {"vendor_device": "1002:6864", "compute_unit_id": "cu-v340l-die-b",
          "memory_resource_id": "mr-v340l-die-b-vram"},
}

# PCI identity of the V340L fabric (roles, not numeric authority: fresh BDFs
# are rediscovered every boot; these constants are used only to RECOGNIZE the
# intended topology, never to require historical numeric addresses).
PM8533_SWITCH_IDS = ("1022:1470", "1022:1471")  # Vega 10 PCIe Bridge upstream/downstream
PM8533_SWITCH_DEV = "11f8:8533"
INTEL_USB_ID = "8086:a2af"
NIC_ID = "10ec:8168"

# Frozen per-cycle post-boot snapshot schema (Phase 1 baseline + every cycle
# captures the exact same schema).
SNAPSHOT_SCHEMA = "inferswarm.v2c.post-boot-snapshot/1"

# Frozen readiness wait conditions (ordinary, prospectively defined).
READINESS = {
    "ssh_port_timeout_s": 10,
    "max_wait_ssh_s": 300,
    "max_wait_ping_s": 300,
    "max_wait_vulkan_s": 600,
    "vulkan_probe_cmd": f"{RUNTIME_EXECUTABLE} --list-devices",
    "network_sentinel": {"kind": "gateway_ping", "target": "10.0.0.1", "count": 3, "maxfail": 0},
}

# Frozen reboot sequence: >=3 ordinary warm reboots, >=1 additional warm or
# firmware reboot, >=1 full cold power-off -> power-on (operator-assisted).
SEQUENCE = {
    "cycles": [
        {"index": 0, "type": "baseline", "transition": None,
         "note": "pre-reboot baseline snapshot; not counted as a boot transition"},
        {"index": 1, "type": "warm", "transition": "systemctl reboot",
         "note": "ordinary OS reboot path"},
        {"index": 2, "type": "warm", "transition": "systemctl reboot",
         "note": "ordinary OS reboot path"},
        {"index": 3, "type": "warm", "transition": "systemctl reboot",
         "note": "ordinary OS reboot path"},
        {"index": 4, "type": "warm", "transition": "systemctl reboot",
         "note": "additional (4th) warm reboot satisfying the >=1 extra warm/firmware requirement"},
        {"index": 5, "type": "cold", "transition": "operator power-off -> power-on",
         "note": "full cold power cycle executed by the operator on signal; never counted as warm"},
    ],
    "denominator_rule": "every requested transition that reaches evaluation is retained, pass or fail; "
                        "a failed cycle is never omitted from the denominator",
    "cold_rule": "the cold cycle is a real power-off -> power-on only if operator power action is "
                 "recorded in the cycle artifact; otherwise the campaign ends warm-only",
}

# Per-cycle probes (all read-only; captured fresh each boot).
PER_CYCLE_PROBES = {
    "host": ["boot_id", "uptime", "uname -a", "/proc/cmdline", "dmidecode BIOS/board identity",
             "amdgpu module identity", "Vulkan loader + ICD identity"],
    "pci": ["lspci -PP -nn -vv full topology", "root port -> PM8533 -> Vega endpoint path",
            "endpoint/bridge driver binding", "final BAR/resource map", "LnkCap/LnkSta on endpoint, "
            "switch upstream, root port", "SR-IOV total/active VFs", "IOMMU groups", "irq assignments"],
    "vulkan": ["llama-cli --list-devices fresh enumeration", "identity probe binding selector->BDF"],
    "peripherals": ["NIC presence/driver/interface/MAC/link/address/route",
                    "USB host controllers + root hubs + attached input devices (lsusb)",
                    "storage controller/root fs mount + non-destructive read/write sentinel"],
    "errors": ["journalctl -b: AER/fatal/nonfatal PCIe, amdgpu init/reset/fault, DMAR/IOMMU faults, "
               "IRQ conflicts, NIC/USB/storage init errors, PCI BAR allocation failures/retries"],
}

# Failure predicates (Phase 3 gate; mechanically derived from snapshot bytes).
FAILURE_PREDICATES = {
    "v340l": [
        "exactly one PM8533 fanout topology present with exactly two Vega 1002:6864 physical functions",
        "both Vega functions amdgpu-bound",
        "final BARs assigned, non-overlapping, and every BAR has a real host bridge window",
        "both functions expose expected device-local capacity (~8 GiB) and usable Vulkan devices",
        "fresh selector->physical-device binding unique (2 distinct selectors, 2 distinct BDFs)",
        "root port + switch upstream retain Gen3 x1 (8.0 GT/s, width 1) campaign identity",
        "no unresolved final PCI resource allocation failure",
    ],
    "network": [
        "intended NIC present + driver-bound",
        "interface exists, carrier/link-up",
        "expected address/route via ordinary configuration (dhcp)",
        "gateway reachability sentinel passes (3/3)",
        "no manual driver reload or interface surgery",
    ],
    "usb": [
        "baseline USB host controller set remains enumerated (superset tolerated, disappearance fails)",
        "optional input device: if present at baseline, same device identity remains enumerated",
    ],
    "storage": [
        "boot/root storage controller + device present",
        "root filesystem mounted from the expected device/source",
        "non-destructive read/write health sentinel passes",
        "no storage controller resource failure",
    ],
    "kernel": [
        "unresolved BAR/resource allocation for a required device fails the cycle",
        "required endpoint/controller missing fails the cycle",
        "fatal AER on the qualified path fails the cycle (correctable physical-layer messages are "
        "retained as observations; they do not fail the cycle unless final device state is broken)",
        "IOMMU/DMAR fault invalidating device operation fails the cycle",
        "amdgpu init/reset/hang failure affecting either die fails the cycle",
        "manual recovery required fails the cycle",
    ],
}

# Phase 4 sentinel: bounded post-boot execution on each die separately using
# accepted #210 semantics. Smaller than full certification: 1 execution per
# die per boot, frozen reference + comparator, no fallback.
SENTINEL = {
    "argv": [RUNTIME_EXECUTABLE, "-m", MODEL, "--temp", "0", "--seed", "42", "-n", "8",
             "-ngl", "99", "--device", "<selector>", "-lv", "4",
             "-p", "The quick brown fox jumps over the lazy dog. Explain what happens next in one sentence:",
             "-st"],
    "n_tokens": 8,
    "comparator": "byte-exact-prefix-of-accepted-reference",
    "reference": "docs/investigations/vulkan-v1-a/reference-visible-output.txt",
    "reference_sha256": "9013db8fb38982f9085754e69fa3feb2f74c7372360da686fe90a3444f26182d",
    "reference_provenance": "accepted V1-A frozen visible greedy output (reused byte-identically by accepted V2-B)",
    "selector_resolution": "fresh per-boot discovery; never reuse a previous boot's selector authority",
    "repeats": 1,
    "accounting_keys": ["unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready",
                        "unplanned_state_movements"],
    "offload_requirement": "full offload (-ngl 99) with zero fallback; offloaded layers must equal the "
                           "accepted per-die full-offload count observed at qualification",
}

# Final-boot full canonical check: on the final accepted boot rerun the
# smallest existing full per-die #210-compatible canonical check.
FINAL_BOOT_FULL_CHECK = {
    "mode": "v2a_harness canonical execution via accepted authority semantics",
    "requirement": "die A and die B each pass one canonical execution with byte-exact visible output "
                   "and clean accounting; #210 evidence is never reinterpreted or overwritten",
}

TERMINALS = {
    "pass": "V2C_V340L_PLATFORM_STABILITY_PASS",
    "warm_only": "V2C_V340L_WARM_REBOOT_STABILITY_ONLY",
    "fail": "V2C_V340L_PLATFORM_STABILITY_FAIL",
    "blocked": "V2C_EVIDENCE_BLOCKED",
}

NONCLAIMS = [
    "no simultaneous dual-die correctness or throughput",
    "no shared-x1 contention envelope under concurrent load",
    "no sustained dual-load thermal/power stability",
    "no process/device fault isolation",
    "no aggregate 16 GiB single-address-space semantics",
    "no Qwen3.8 or DeepSeek V4.1 correctness",
    "no mixed AMD/NVIDIA execution",
    "no SR-IOV VF support",
    "no ROCm/HIP support",
    "no production Vulkan support",
    "no production platform certification",
    "no preferred/default backend or planner policy",
]


def build_plan() -> dict:
    return {
        "schema": "inferswarm.v2c.campaign-plan/1",
        "campaign_id": CAMPAIGN_ID,
        "issue": 215,
        "starting_main": STARTING_MAIN,
        "accepted_predecessors": {
            "v2b_merge": ACCEPTED_V2B_MERGE,
            "v2b_terminal": ACCEPTED_V2B_TERMINAL,
            "v2a_merge": ACCEPTED_V2A_MERGE,
            "v2a_terminal": ACCEPTED_V2A_TERMINAL,
        },
        "physical_subject": {
            "hostname": "inferswarm02",
            "runtime_executable": RUNTIME_EXECUTABLE,
            "runtime_executable_sha256": RUNTIME_EXECUTABLE_SHA256,
            "runtime_source": RUNTIME_SOURCE,
            "runtime_source_commit": RUNTIME_SOURCE_COMMIT,
            "model": MODEL,
            "model_sha256": MODEL_SHA256,
            "model_bytes": MODEL_BYTES,
            "vega_die_ids": VEGA_DIE_IDS,
            "pm8533_switch_ids": PM8533_SWITCH_IDS,
            "pm8533_switch_dev": PM8533_SWITCH_DEV,
            "expected_hbm_bytes_per_die": 8573157376,
        },
        "readiness": READINESS,
        "sequence": SEQUENCE,
        "per_cycle_probes": PER_CYCLE_PROBES,
        "failure_predicates": FAILURE_PREDICATES,
        "sentinel": SENTINEL,
        "final_boot_full_check": FINAL_BOOT_FULL_CHECK,
        "terminals": TERMINALS,
    }


def main() -> int:
    plan = build_plan()
    payload = json.dumps(plan, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    digest = hashlib.sha256(payload).hexdigest()
    AREA.mkdir(parents=True, exist_ok=True)
    doc = {"campaign_plan": plan, "campaign_plan_digest": digest}
    out = AREA / "CAMPAIGN-PLAN.json"
    out.write_bytes(json.dumps(doc, indent=1, sort_keys=True, allow_nan=False).encode() + b"\n")
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

