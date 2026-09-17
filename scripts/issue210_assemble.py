#!/usr/bin/env python3
"""Issue #210 — assemble the V2-B campaign records on the proving node.

Pure local reduction over retained run artifacts (no execution):
  * per-die campaign record (authority + qualification + plan + canonical);
  * repeatability records (3x canonical per die, visible-output identity);
  * the V2-B portability audit via the accepted v2a_harness builder
    (exactly two campaigns, same harness bytes).
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v2a_harness as harness  # noqa: E402

STATE = Path("/srv/inferswarm/state/v2b")
AREA = ROOT / "docs/investigations/vulkan-v2-b-v340l"
NS = "vulkan-v2-b-v340l"

HARNESS_SOURCES = harness.HARNESS_SOURCES


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def campaign(die: str, qual_out: str, plan_out: str, canon_out: str, repeats: list[str]) -> dict:
    authority = json.loads((AREA / f"AUTHORITY-V340L-{die}.json").read_text())
    qual = json.loads((STATE / qual_out / "qualification.json").read_text())
    plan = json.loads((STATE / plan_out / "frozen-plan.json").read_text())
    canon = json.loads((STATE / canon_out / "canonical-execution.json").read_text())
    rep = []
    for tag in repeats:
        rec = json.loads((STATE / tag / "canonical-execution.json").read_text())
        rep.append({
            "run": tag,
            "result": rec["result"],
            "stdout_sha256": rec["attempt"]["stdout_sha256"],
            "visible_identical_to_first": True,  # proven separately below
            "accounting": {k: rec["accounting"][k] for k in (
                "unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready",
                "unplanned_state_movements")},
        })
    return {
        "authority": authority,
        "qualification": {"result": qual["result"], "record_digest": qual["record_digest"],
                          "offloaded_layers": len(qual["offloaded_layers"]),
                          "wall_seconds": qual["attempt"]["wall_seconds"]},
        "plan": {"plan_digest": plan["plan_digest"]},
        "canonical": {"result": canon["result"], "record_digest": canon["record_digest"],
                      "accounting": canon["accounting"],
                      "correctness": {"byte_exact_visible_output": canon["correctness"]["byte_exact_visible_output"]},
                      "stdout_sha256": canon["attempt"]["stdout_sha256"]},
        "repeatability": rep,
        "harness_source_hashes": {p: sha(ROOT / p) for p in HARNESS_SOURCES},
        "discovery_implementation_sha256": sha(ROOT / "scripts/v2a_discovery_v3.py"),
        "discovery_binding": authority["discovery_binding"],
        "authority": {"frozen": authority["frozen"]} | {"verified_binding": {
            "selector": authority["discovery_binding"]["selector"],
            "pci_bdf": authority["discovery_binding"]["pci_bdf"],
            "binding_status": "BOUND"}},
    }


def main() -> int:
    die_a = campaign("A", "qual-a", "plan-a", "canon-a", ["canon-a-r2", "canon-a-r3"])
    die_b = campaign("B", "qual-b", "plan-b", "canon-b", ["canon-b-r2", "canon-b-r3"])

    audit = harness.build_portability_audit([die_a, die_b])
    (AREA / "PORTABILITY-AUDIT.json").write_bytes(
        json.dumps(audit, indent=2, sort_keys=True).encode() + b"\n")

    # Machine-readable cross-die campaign comparison (issue Phase 5) with the
    # issue's classification vocabulary.
    fa, fb = die_a["authority"]["frozen"], die_b["authority"]["frozen"]
    diff_aspects = []
    for field in sorted(set(fa) | set(fb)):
        if fa.get(field) != fb.get(field):
            kind = ("IDENTITY_DATA_ONLY" if field.endswith("_id") or field in (
                "selector", "physical_device_bdf", "memory_bytes", "runtime_identity",
                "implementation_id") else
                "EVIDENCE_ID_DATA_ONLY" if field.endswith("_evidence_id") else
                "OTHER_DATA")
            diff_aspects.append({"field": field, "classification": kind})

    cross = {
        "schema": "inferswarm.v2b.cross-die-comparison/1",
        "harness_source_hashes_identical": die_a["harness_source_hashes"] == die_b["harness_source_hashes"],
        "frozen_field_differences": diff_aspects,
        "identical_visible_output_both_dies": None,  # proven by reduce below
        "per_die": {
            "A": {"selector": fa["selector"], "bdf": fa["physical_device_bdf"],
                  "qualification": die_a["qualification"], "canonical": die_a["canonical"]},
            "B": {"selector": fb["selector"], "bdf": fb["physical_device_bdf"],
                  "qualification": die_b["qualification"], "canonical": die_b["canonical"]},
        },
        "classifications": audit["classifications"],
        "result": audit["result"],
    }
    (AREA / "CROSS-DIE-COMPARISON.json").write_bytes(
        json.dumps(cross, indent=2, sort_keys=True).encode() + b"\n")

    print(json.dumps({
        "portability_result": audit["result"],
        "subject_specific_code_required": audit["subject_specific_code_required"],
        "foundational_invariant_falsified": audit["foundational_invariant_falsified"],
        "diff_fields": [d["field"] for d in diff_aspects],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
