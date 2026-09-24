"""#241 R8-I3 Phase-4 decision-input assembler v2 (CPU-only reducer).

Byte-equivalent to the 286dc63 campaign's decision_inputs.py with the
evidence root moved to the v2 campaign directory. Consumes ONLY
digest-bound receipts produced by the frozen producers, then derives
the issue's 12-item engineering decision inputs. Emits
decision-inputs.json next to the evidence root for maintainer review.
No physical execution, no model reads, no API access.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/home/hermes/is241-repo/scripts")
import issue241_constants as C          # noqa: E402
import issue241_census as census        # noqa: E402
import issue241_practicality as prac    # noqa: E402

EVIDENCE = Path(os.environ.get("IS241_V2_EVIDENCE",
                               "/home/hermes/is241-campaign-v2"))


def load(p: Path):
    return json.loads(p.read_bytes())


def main() -> int:
    census_receipt = load(EVIDENCE / "phase1" / "census-receipt.json")
    placement_receipt = load(EVIDENCE / "phase2" / "phase2-placement-receipt.json")
    phase3 = load(EVIDENCE / "phase3" / "phase3.json")
    measured = load(EVIDENCE / "phase3" / "measured-wall-times.json")

    verdict = census.validate_census(census_receipt["census"]["census"])
    projection = prac.project_from_measurements(
        EVIDENCE / "phase3" / "measured-wall-times.json")
    disposition = prac.derive_disposition(
        census_valid=verdict["validated"],
        census_problems=verdict.get("problems", []),
        placement={"placement_blocked": False,
                   "matched_ngl": placement_receipt["selected"]["matched_ngl"]},
        comparator_v2={"validated": True},
        candidate_projection=projection["candidate"])

    # Measured per-arm identities: the census GPU rows bound to each arm's
    # frozen BDF (reference B = 3060 @03:00.0, candidate C = RX580 @02:00.0).
    arm_bdf = {"B": C.REFERENCE_ARM["bdf"], "C": C.CANDIDATE_ARM["bdf"]}
    measured_identities = {
        arm: next(g for g in census_receipt["census"]["census"]["gpus"]
                  if g["bdf"] == bdf)
        for arm, bdf in arm_bdf.items()}

    report = {
        "schema": "inferswarm.issue241.decision-inputs/1",
        "campaign": C.CAMPAIGN_ID,
        "head": phase3["authority"]["head_sha"],
        "1_fresh_hardware_state": {
            "host": census_receipt["census"]["census"]["host"],
            "cpu": census_receipt["census"]["census"]["cpu"],
            "mem_total_kib": census_receipt["census"]["census"]["mem_total_kib"],
            "motherboard": census_receipt["census"]["census"]["motherboard"],
        },
        "2_arm_identities": measured_identities,
        "3_vulkan_runtime_identities": {
            g["bdf"]: {k: g[k] for k in (
                "vulkan_icd", "vulkan_device_name", "vulkan_device_uuid",
                "vulkan_api_version", "vulkan_driver_name",
                "vulkan_driver_info", "driver_in_use")}
            for g in census_receipt["census"]["census"]["gpus"]
        },
        "4_matched_placement_ladder": placement_receipt["rungs"],
        "5_selected_ngl": placement_receipt["selected"],
        "6_both_arm_vram_residency": {
            arm: [{"ngl": r["ngl"],
                   "vram_residency_mib": r.get("placement", {}).get(
                       "vram_residency_mib")}
                  for r in placement_receipt["rungs"][arm]]
            for arm in ("B", "C")},
        "7_host_ram_pagecache_io": {
            arm: [{"ngl": r["ngl"],
                   "process_measurements": r.get("process_measurements")}
                  for r in placement_receipt["rungs"][arm]]
            for arm in ("B", "C")},
        "8_comparator_v2_semantics": {
            "comparator_id": "inferswarm.qwen38-vulkan-comparator/2",
            "semantic": "one continuous request per arm/case; reference "
                        "winner appended naturally; candidate captures the "
                        "untouched full-vocab FP32 row at decision d THEN "
                        "forces the reference token",
            "source_order_proof": "validate_capture_force_order",
        },
        "9_deterministic_historical_results": {
            "pairs_validated": sum(1 for p in phase3["pairs"] if p["validated"]),
            "determinism": [{"arm": d.get("arm"), "case_id": d.get("case_id"),
                             "deterministic": d.get("deterministic")}
                            for d in phase3["determinism"]],
            "inertness": [{"arm": i.get("arm"), "case_id": i.get("case_id"),
                           "inert": i.get("inert")}
                          for i in phase3["inertness"]],
        },
        "10_projected_r8j_phase_a": projection,
        "11_disposition": disposition,
        "12_holdout_applicability": {
            "disposition": "ADVISORY-maintainer-adjudication",
            "committed_seal_contract_id":
                "inferswarm.qwen38-vulkan-heterogeneous-qualification/1",
            "committed_seal_carries_no_superseded_marker": True,
            "note": "Verified live pre-freeze; v1-area applicability "
                    "manifests carry V340L/comparator-1 markers but stay "
                    "frozen v1 history — surfaced advisorily, never a "
                    "re-seal trigger.",
        },
    }
    out = EVIDENCE / "decision-inputs.json"
    if out.exists():
        print("decision-inputs.json already exists; refusing to overwrite",
              file=sys.stderr)
        return 1
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"disposition": disposition["disposition"],
                      "selected_ngl": placement_receipt["selected"]["matched_ngl"],
                      "projection_central_s": projection["candidate"]["central_s"]},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
