#!/usr/bin/env python3
"""Issue #210 — build the V2-B terminal record and evidence manifest.

Pure CPU reduction over the committed V2-B evidence directory. The
terminal classification is DERIVED from the retained artifacts (both
dies' qualification/canonical/repeatability records, the portability
audit, the discovery bindings, the retained Phase-1 PCI topology and
the accepted V2-A predecessor identity) — never a constant: any failing
input maps to the corresponding non-PASS terminal, and a one-die PASS
is never promoted to a dual-die board PASS.

Mechanical PASS predicates (correction round: maintainer findings on
PR #212) — every one is re-derived from retained bytes on each run:

* per die: qualification PASS, canonical PASS, byte-exact visible
  output, full 37/37 offload, accounting 0/0/0 on the canonical record
  AND every retained repeat, raw stdout/stderr digests re-hashed from
  the retained raw bytes agree with the recorded digests;
* selector <-> BDF bindings from the retained R3 discovery bindings,
  correct per authority and distinct across dies;
* distinct Compute Unit identities;
* portability audit PASS;
* retained Phase-1 topology evidence exists for this campaign and
  mechanically proves root port 0000:00:1d.0 negotiated PCIe Gen3 x1
  (8.0 GT/s, width 1) and PM8533 upstream 0000:02:00.0 (11f8:8533)
  negotiated Gen3 x1 — parsed from raw/phase1/pci-topology.json, never
  from prose or constants;
* the accepted V2-A predecessor identity: both V2-B authorities
  declare merge e38ebe91a0604fb666397ddae675248e9f819f60 with terminal
  V2A_REUSABLE_DEVICE_QUALIFICATION_HARNESS_PASS, and the retained
  accepted V2-A terminal artifact carries that exact terminal.

An env seam (INFERSWARM_ISSUE210_ROOT) redirects the repository root so
mutation controls run against a sandbox copy of the evidence area; the
canonical committed evidence is never mutated in place.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

NS = "vulkan-v2-b-v340l"
ROOT_SEAM = "INFERSWARM_ISSUE210_ROOT"

ACCT_KEYS = ("unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready",
             "unplanned_state_movements")

# Campaign physical facts (subject-specific, Issue #210 only).
ROOT_PORT_BDF = "0000:00:1d.0"
PM8533_UPSTREAM_BDF = "0000:02:00.0"
PM8533_UPSTREAM_VENDOR = "0x11f8"
PM8533_UPSTREAM_DEVICE = "0x8533"
GEN3_CURRENT_SPEED = "8.0 GT/s PCIe"
X1_CURRENT_WIDTH = "1"

# Accepted predecessor identity (Issue #163 / PR #164, V2-A harness).
ACCEPTED_V2A_MERGE = "e38ebe91a0604fb666397ddae675248e9f819f60"
ACCEPTED_V2A_TERMINAL = "V2A_REUSABLE_DEVICE_QUALIFICATION_HARNESS_PASS"
V2A_TERMINAL_REL = "docs/investigations/vulkan-v2-a/FINAL-TERMINAL.json"


def repo_root() -> Path:
    override = os.environ.get(ROOT_SEAM)
    return Path(override) if override else ROOT


def area() -> Path:
    return repo_root() / "docs" / "investigations" / NS


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def phase1_topology_facts() -> dict:
    """Re-derive the Gen3 x1 upstream topology from retained Phase-1 bytes.

    The facts come from this campaign's own raw Phase-1 probe output
    (raw/phase1/pci-topology.json, sha-pinned by the V2-B manifest) —
    never from authority prose or constants. Missing entries, missing
    speed/width fields, or non-Gen3/non-x1 negotiations all fail the
    corresponding predicate.
    """
    top_path = area() / "raw" / "phase1" / "pci-topology.json"
    top = json.loads(top_path.read_text())

    def gen3_x1(entry: object) -> bool:
        return (isinstance(entry, dict)
                and entry.get("current_link_speed") == GEN3_CURRENT_SPEED
                and entry.get("current_link_width") == X1_CURRENT_WIDTH)

    rp = top.get(ROOT_PORT_BDF)
    up = top.get(PM8533_UPSTREAM_BDF)
    upstream_is_pm8533 = (isinstance(up, dict)
                          and up.get("vendor") == PM8533_UPSTREAM_VENDOR
                          and up.get("device") == PM8533_UPSTREAM_DEVICE)
    return {
        "raw_file": "raw/phase1/pci-topology.json",
        "raw_file_sha256": digest(top_path.read_bytes()),
        "root_port_bdf": ROOT_PORT_BDF,
        "root_port_present": rp is not None,
        "root_port_current_link_speed": (rp or {}).get("current_link_speed"),
        "root_port_current_link_width": (rp or {}).get("current_link_width"),
        "root_port_gen3_x1": gen3_x1(rp),
        "pm8533_upstream_bdf": PM8533_UPSTREAM_BDF,
        "pm8533_upstream_present": up is not None,
        "pm8533_upstream_is_11f8_8533": upstream_is_pm8533,
        "pm8533_upstream_current_link_speed": (up or {}).get("current_link_speed"),
        "pm8533_upstream_current_link_width": (up or {}).get("current_link_width"),
        "pm8533_upstream_gen3_x1": gen3_x1(up),
        "phase1_topology_evidence_complete": (
            rp is not None and up is not None
            and (rp or {}).get("current_link_speed") is not None
            and (rp or {}).get("current_link_width") is not None
            and (up or {}).get("current_link_speed") is not None
            and (up or {}).get("current_link_width") is not None),
    }


def predecessor_facts() -> dict:
    """Verify the accepted V2-A predecessor identity from retained bytes.

    Both V2-B authorities must declare the accepted V2-A merge and its
    accepted terminal, and the retained accepted V2-A terminal artifact
    (byte-pinned by the accepted V2-A manifest) must carry exactly that
    terminal. A wrong or superseded predecessor identity fails closed.
    """
    preds = []
    for die in ("A", "B"):
        doc = json.loads((area() / f"AUTHORITY-V340L-{die}.json").read_text())
        preds.append(doc.get("predecessors", {}))
    terminal_path = repo_root() / V2A_TERMINAL_REL
    terminal_bytes = terminal_path.read_bytes()
    retained_terminal = json.loads(terminal_bytes).get("terminal")
    declares_merge = all(p.get("v2a_merge") == ACCEPTED_V2A_MERGE for p in preds)
    declares_terminal = all(p.get("v2a_terminal") == ACCEPTED_V2A_TERMINAL for p in preds)
    return {
        "accepted_v2a_merge": ACCEPTED_V2A_MERGE,
        "accepted_v2a_terminal": ACCEPTED_V2A_TERMINAL,
        "retained_v2a_terminal_artifact": V2A_TERMINAL_REL,
        "retained_v2a_terminal_sha256": digest(terminal_bytes),
        "retained_v2a_terminal_value": retained_terminal,
        "both_authorities_declare_accepted_merge": declares_merge,
        "both_authorities_declare_accepted_terminal": declares_terminal,
        "retained_v2a_terminal_is_accepted": retained_terminal == ACCEPTED_V2A_TERMINAL,
    }


def die_facts(die: str) -> dict:
    qual = json.loads((area() / "evidence" / f"v2b-v340l-{die}-qualification-01" /
                       "qualification.json").read_text())
    plan = json.loads((area() / "evidence" / f"v2b-v340l-{die}-plan-01" /
                       "frozen-plan.json").read_text())
    canon = json.loads((area() / "raw" / f"v2b-v340l-{die}-canonical-01" /
                        "canonical-execution.json").read_text())
    authority = json.loads((area() / f"AUTHORITY-V340L-{die.upper()}.json").read_text())
    repeats = [canon]
    for suffix in ("-r2", "-r3"):
        repeats.append(json.loads(
            (area() / "raw" / f"v2b-v340l-{die}-canonical-01{suffix}" /
             "canonical-execution.json").read_text()))
    acct_clean = all(all(r["accounting"][k] == 0 for k in ACCT_KEYS) for r in repeats)
    return {
        "die": die,
        "selector": authority["frozen"]["selector"],
        "pci_bdf": authority["frozen"]["physical_device_bdf"],
        "compute_unit_id": authority["frozen"]["compute_unit_id"],
        "memory_resource_id": authority["frozen"]["memory_resource_id"],
        "node_id": authority["frozen"]["node_id"],
        "authority_sha256": digest((area() / f"AUTHORITY-V340L-{die.upper()}.json").read_bytes()),
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
        "raw_digests_match_records": all(
            digest((area() / "raw" / f"v2b-v340l-{die}-canonical-01{suffix}" /
                    "stdout.txt").read_bytes()) == r["attempt"]["stdout_sha256"]
            and digest((area() / "raw" / f"v2b-v340l-{die}-canonical-01{suffix}" /
                       "stderr.txt").read_bytes()) == r["attempt"]["stderr_sha256"]
            for r, suffix in zip(repeats, ("", "-r2", "-r3"))),
        "selected_device_line": next(
            line for line in (area() / "raw" / f"v2b-v340l-{die}-canonical-01" /
                              "stderr.txt").read_text().splitlines()
            if "using device" in line),
    }


def derive_record() -> dict:
    a = die_facts("a")
    b = die_facts("b")
    audit = json.loads((area() / "PORTABILITY-AUDIT.json").read_text())
    cross = json.loads((area() / "CROSS-DIE-COMPARISON.json").read_text())
    bindings = json.loads((area() / "DISCOVERY-BINDINGS-R3.json").read_text())
    inventory = json.loads((area() / "DISCOVERY-INVENTORY-R3.json").read_text())
    topology = phase1_topology_facts()
    predecessor = predecessor_facts()

    def die_passes(d: dict) -> bool:
        return (d["qualification_result"] == "PASS" and d["canonical_result"] == "PASS"
                and d["byte_exact_visible_output"] is True
                and all(v == 0 for v in d["accounting_three_tuple"])
                and d["repeat_count"] >= 3 and all(d["repeat_byte_exact"])
                and d["repeat_all_accounting_clean"]
                and d["offloaded_layers_full"] is True
                and d["raw_digests_match_records"] is True)

    a_pass, b_pass = die_passes(a), die_passes(b)
    bound = {x["selector"]: x["pci_bdf"] for x in bindings["bindings"]
             if x["binding_status"] == "BOUND"}
    selectors_bound = (bound.get(a["selector"]) == a["pci_bdf"]
                       and bound.get(b["selector"]) == b["pci_bdf"]
                       and a["pci_bdf"] != b["pci_bdf"])
    distinct_cus = (a["compute_unit_id"] != b["compute_unit_id"]
                    and a["pci_bdf"] != b["pci_bdf"] and a["selector"] != b["selector"])
    topology_ok = (topology["phase1_topology_evidence_complete"]
                   and topology["root_port_gen3_x1"]
                   and topology["pm8533_upstream_gen3_x1"]
                   and topology["pm8533_upstream_is_11f8_8533"])
    predecessor_ok = (predecessor["both_authorities_declare_accepted_merge"]
                      and predecessor["both_authorities_declare_accepted_terminal"]
                      and predecessor["retained_v2a_terminal_is_accepted"])

    # --- terminal derivation (never a constant) ---
    if (a_pass and b_pass and audit["result"] == "PASS" and selectors_bound
            and distinct_cus and topology_ok and predecessor_ok):
        terminal = "V2B_V340L_DUAL_DIE_QUALIFICATION_PASS"
    elif a_pass != b_pass:
        terminal = "V2B_V340L_PARTIAL_DIE_QUALIFICATION"
    elif not (selectors_bound and distinct_cus and topology_ok and predecessor_ok):
        terminal = "V2B_V340L_EVIDENCE_BLOCKED"
    else:
        terminal = "V2B_V340L_PHYSICAL_REPRODUCTION_FAIL"

    return {
        "schema": "inferswarm.v2b.terminal/2",
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
            "phase1_topology_evidence_complete": topology["phase1_topology_evidence_complete"],
            "root_port_gen3_x1": topology["root_port_gen3_x1"],
            "pm8533_upstream_gen3_x1": topology["pm8533_upstream_gen3_x1"],
            "accepted_v2a_predecessor_verified": predecessor_ok,
        },
        "phase1_topology": topology,
        "accepted_predecessor": predecessor,
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


def main() -> int:
    record = derive_record()
    out = area() / "TERMINAL.json"
    out.write_bytes(json.dumps(record, indent=2, sort_keys=True).encode() + b"\n")
    print(canonical({"terminal": record["terminal"],
                     "die_a_pass": record["terminal_derivation"]["die_a_pass"],
                     "die_b_pass": record["terminal_derivation"]["die_b_pass"],
                     "record_sha256": digest(out.read_bytes())}).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
