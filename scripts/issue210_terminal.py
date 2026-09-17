#!/usr/bin/env python3
"""Issue #210 — build the V2-B terminal record and evidence manifest.

Pure CPU reduction over the committed V2-B evidence directory. The
terminal classification is DERIVED from the retained artifacts (both
dies' qualification/canonical/repeatability records, the portability
audit, the discovery bindings) — never a constant: any failing input
maps to the corresponding non-PASS terminal, and a one-die PASS is
never promoted to a dual-die board PASS.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

AREA = ROOT / "docs/investigations/vulkan-v2-b-v340l"
NS = "vulkan-v2-b-v340l"

ACCT_KEYS = ("unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready",
             "unplanned_state_movements")


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def die_facts(die: str) -> dict:
    qual = json.loads((AREA / "evidence" / f"v2b-v340l-{die}-qualification-01" /
                       "qualification.json").read_text())
    plan = json.loads((AREA / "evidence" / f"v2b-v340l-{die}-plan-01" /
                       "frozen-plan.json").read_text())
    canon = json.loads((AREA / "raw" / f"v2b-v340l-{die}-canonical-01" /
                        "canonical-execution.json").read_text())
    authority = json.loads((AREA / f"AUTHORITY-V340L-{die.upper()}.json").read_text())
    repeats = [canon]
    for suffix in ("-r2", "-r3"):
        repeats.append(json.loads(
            (AREA / "raw" / f"v2b-v340l-{die}-canonical-01{suffix}" /
             "canonical-execution.json").read_text()))
    acct_clean = all(all(r["accounting"][k] == 0 for k in ACCT_KEYS) for r in repeats)
    return {
        "die": die,
        "selector": authority["frozen"]["selector"],
        "pci_bdf": authority["frozen"]["physical_device_bdf"],
        "compute_unit_id": authority["frozen"]["compute_unit_id"],
        "memory_resource_id": authority["frozen"]["memory_resource_id"],
        "node_id": authority["frozen"]["node_id"],
        "authority_sha256": digest((AREA / f"AUTHORITY-V340L-{die.upper()}.json").read_bytes()),
        "qualification_result": qual["result"],
        "qualification_digest": qual["record_digest"],
        "offloaded_layer_count": len(qual["offloaded_layers"]),
        "offloaded_layers": list(qual["offloaded_layers"]),
        "offloaded_layers_full": all(x == 37 for x in qual["offloaded_layers"]) and len(qual["offloaded_layers"]) > 0,
        "plan_digest": plan["plan_digest"],
        "canonical_result": canon["result"],
        "canonical_digest": canon["record_digest"],
        "canonical_proof_digest": canon["canonical_proof_digest"],
        "canonical_observation_evidence_id":
            canon["canonical_observation"]["evidence_id"],
        "execution_receipt_output_sha256": canon["execution_receipt"]["output_sha256"],
        "candidate_id": canon["execution_receipt"]["candidate_id"],
        "byte_exact_visible_output": canon["correctness"]["byte_exact_visible_output"],
        "accounting_three_tuple": [canon["accounting"][k] for k in ACCT_KEYS],
        "repeat_canonical_digests": [r["record_digest"] for r in repeats],
        "repeat_stdout_sha256": [r["attempt"]["stdout_sha256"] for r in repeats],
        "repeat_all_accounting_clean": acct_clean,
        "repeat_count": len(repeats),
        # Repeatability at the visible-output level is proven by the byte-exact
        # comparator against the SAME frozen reference for every repeat: each
        # repeat's correctness byte_exact flag is retained below.
        "repeat_byte_exact": [r["correctness"]["byte_exact_visible_output"] for r in repeats],
        "selected_device_line": next(
            line for line in (AREA / "raw" / f"v2b-v340l-{die}-canonical-01" /
                              "stderr.txt").read_text().splitlines()
            if "using device" in line),
    }


def main() -> int:
    a = die_facts("a")
    b = die_facts("b")
    audit = json.loads((AREA / "PORTABILITY-AUDIT.json").read_text())
    cross = json.loads((AREA / "CROSS-DIE-COMPARISON.json").read_text())
    bindings = json.loads((AREA / "DISCOVERY-BINDINGS-R3.json").read_text())
    inventory = json.loads((AREA / "DISCOVERY-INVENTORY-R3.json").read_text())

    def die_passes(d: dict) -> bool:
        return (d["qualification_result"] == "PASS" and d["canonical_result"] == "PASS"
                and d["byte_exact_visible_output"] is True
                and all(v == 0 for v in d["accounting_three_tuple"])
                and d["repeat_count"] >= 3 and all(d["repeat_byte_exact"])
                and d["repeat_all_accounting_clean"]
                and d["offloaded_layers_full"] is True)

    a_pass, b_pass = die_passes(a), die_passes(b)
    bound = {x["selector"]: x["pci_bdf"] for x in bindings["bindings"]
             if x["binding_status"] == "BOUND"}
    selectors_bound = (bound.get(a["selector"]) == a["pci_bdf"]
                       and bound.get(b["selector"]) == b["pci_bdf"]
                       and a["pci_bdf"] != b["pci_bdf"])
    distinct_cus = (a["compute_unit_id"] != b["compute_unit_id"]
                    and a["pci_bdf"] != b["pci_bdf"] and a["selector"] != b["selector"])

    # --- terminal derivation (never a constant) ---
    if a_pass and b_pass and audit["result"] == "PASS" and selectors_bound and distinct_cus:
        terminal = "V2B_V340L_DUAL_DIE_QUALIFICATION_PASS"
    elif a_pass != b_pass:
        terminal = "V2B_V340L_PARTIAL_DIE_QUALIFICATION"
    elif not selectors_bound or not distinct_cus:
        terminal = "V2B_V340L_EVIDENCE_BLOCKED"
    else:
        terminal = "V2B_V340L_PHYSICAL_REPRODUCTION_FAIL"

    record = {
        "schema": "inferswarm.v2b.terminal/1",
        "issue": "#210",
        "campaign_main_at_start": "267b983de1249cad9c516e5c5c3cf86ed4a5a252",
        "freeze_commits": {
            "phase1_topology": "c26746c719e4f60fc6c5f85482e40483de5aa9ec",
            "authorities": "2c761e97e6c3a6f7281c98f92c2aff386f7ef684",
        },
        "terminal": terminal,
        "terminal_derivation": {
            "die_a_pass": a_pass, "die_b_pass": b_pass,
            "portability_audit_result": audit["result"],
            "selectors_bound_to_distinct_bdfs": selectors_bound,
            "distinct_compute_units": distinct_cus,
        },
        "die_a": a,
        "die_b": b,
        "cross_die_audit": {
            "result": cross["result"],
            "harness_source_hashes_identical": cross["harness_source_hashes_identical"],
            "frozen_field_differences": cross["frozen_field_differences"],
        },
        "discovery": {
            "inventory_measured_utc": inventory["measured_utc"],
            "reviewed_utc": bindings["reviewed_utc"],
            "binding_statuses": {x["selector"]: x["binding_status"]
                                 for x in bindings["bindings"]},
        },
        "nonclaims": [
            "no concurrent two-die performance scaling or shared Gen3 x1 contention claim",
            "no aggregate 16 GiB single-address-space semantics",
            "no production scheduler policy or preferred/default backend decision",
            "no x1 economic suitability claim (issue #35 owns that work)",
            "no Qwen3.8 or DeepSeek V4.1 qualification",
            "no mixed AMD/NVIDIA execution claim",
            "no SR-IOV VF support or ROCm/HIP qualification claim",
            "no public backend API stability claim",
        ],
        "successor_readiness": {
            "both_dies_eligible_for_later_simultaneous_testing": a_pass and b_pass,
            "facts_a_later_dual_die_or_35_campaign_must_preserve": {
                "root_port": "0000:00:1d.0 negotiated PCIe Gen3 x1 (8.0 GT/s x1)",
                "pm8533_upstream": "0000:02:00.0 negotiated Gen3 x1 (cap x16)",
                "gpu_to_switch_links": "Gen3 x16 both dies",
                "selectors": {a["selector"]: a["pci_bdf"], b["selector"]: b["pci_bdf"]},
            },
            "consumable_unchanged_per_die": [
                "authority bytes (sha-pinned)", "capability record", "frozen plan",
                "qualification/canonical/accounting semantics (V2-A harness imports)",
            ],
            "explicitly_unproven": [
                "concurrent dual-die scaling", "shared-x1 contention envelope",
                "thermals/power under dual load", "reset isolation",
                "model-specific Qwen/DeepSeek correctness", "mixed-vendor execution",
            ],
        },
    }
    out = AREA / "TERMINAL.json"
    out.write_bytes(json.dumps(record, indent=2, sort_keys=True).encode() + b"\n")
    print(canonical({"terminal": terminal, "die_a_pass": a_pass, "die_b_pass": b_pass,
                     "record_sha256": digest(out.read_bytes())}).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
